"""Display hardware: a real ST7789 over SPI and a mock for development.

The ST7789 driver is written directly against ``spidev`` + ``gpiozero`` so it
needs no NumPy and converts frames to RGB565 with two ``bytes.translate``
calls -- fast enough for a Pi Zero W.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

from src.config.settings import Settings
from src.display.palette import Color, build_ramp, rgb565_tables

log = logging.getLogger(__name__)

SIZE = 240


class DisplayDevice(ABC):
    size: int = SIZE

    @abstractmethod
    def show(self, image) -> None:
        """Show a ``size``x``size`` mode "L" intensity image (see :mod:`src.display.palette`)."""

    @abstractmethod
    def close(self) -> None:
        """Blank the screen and release hardware."""


class MockDisplayDevice(DisplayDevice):
    """No hardware. Keeps the last frame; can write a PNG preview and an ASCII dump."""

    def __init__(self, eye_color: Color = (0x35, 0xD0, 0xFF), preview_path: str | Path | None = None,
                 preview_interval_s: float = 1.0) -> None:
        self._ramp = build_ramp(eye_color)
        self._preview = Path(preview_path) if preview_path else None
        self._interval = preview_interval_s
        self._last_write = 0.0
        self.frames = 0
        self.last_image = None

    def show(self, image) -> None:
        self.frames += 1
        self.last_image = image
        now = time.monotonic()
        if self._preview and now - self._last_write >= self._interval:
            self._last_write = now
            self.save_png(self._preview)

    def save_png(self, path: str | Path) -> None:
        """Write the last frame, coloured, to ``path``."""
        from PIL import Image

        if self.last_image is None:
            return
        channels = [self.last_image.point([c[i] for c in self._ramp]) for i in range(3)]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Image.merge("RGB", channels).save(path)

    def ascii(self, columns: int = 60) -> str:
        """Coarse text rendering of the last frame, for terminals."""
        if self.last_image is None:
            return ""
        rows = columns // 2
        small = self.last_image.resize((columns, rows))
        chars = " .:-=+*#%@"
        data = small.tobytes()
        return "\n".join(
            "".join(chars[data[y * columns + x] * (len(chars) - 1) // 255] for x in range(columns))
            for y in range(rows)
        )

    def close(self) -> None:
        return None


# ST7789 commands
_SWRESET, _SLPOUT, _COLMOD, _MADCTL = 0x01, 0x11, 0x3A, 0x36
_CASET, _RASET, _RAMWR, _INVON, _NORON, _DISPON, _DISPOFF = 0x2A, 0x2B, 0x2C, 0x21, 0x13, 0x29, 0x28
_MADCTL_BY_ROTATION = {0: 0x00, 90: 0x60, 180: 0xC0, 270: 0xA0}
_OFFSET_BY_ROTATION = {0: (0, 0), 90: (0, 0), 180: (0, 80), 270: (80, 0)}  # (x, y) for 240x240 panels

_INIT_SEQUENCE = [
    (0xB2, [0x0C, 0x0C, 0x00, 0x33, 0x33]),
    (0xB7, [0x35]),
    (0xBB, [0x19]),
    (0xC0, [0x2C]),
    (0xC2, [0x01]),
    (0xC3, [0x12]),
    (0xC4, [0x20]),
    (0xC6, [0x0F]),
    (0xD0, [0xA4, 0xA1]),
    (0xE0, [0xD0, 0x04, 0x0D, 0x11, 0x13, 0x2B, 0x3F, 0x54, 0x4C, 0x18, 0x0D, 0x0B, 0x1F, 0x23]),
    (0xE1, [0xD0, 0x04, 0x0C, 0x11, 0x13, 0x2C, 0x3F, 0x44, 0x51, 0x2F, 0x1F, 0x1F, 0x20, 0x23]),
]


class ST7789Device(DisplayDevice):
    """1.3" 240x240 ST7789 on SPI0 (CE0) with DC/RST/backlight on GPIO."""

    def __init__(self, s: Settings) -> None:
        import spidev
        from gpiozero import DigitalOutputDevice

        self._ramp_hi, self._ramp_lo = rgb565_tables(build_ramp(s.eye_color))
        self._dc = DigitalOutputDevice(s.display_dc_pin, initial_value=False)
        self._rst = DigitalOutputDevice(s.display_rst_pin, initial_value=True)
        self._bl = DigitalOutputDevice(s.display_bl_pin, initial_value=False)
        default_x, default_y = _OFFSET_BY_ROTATION[s.display_rotation]
        self._x_off = default_x if s.display_x_offset is None else s.display_x_offset
        self._y_off = default_y if s.display_y_offset is None else s.display_y_offset
        self._spi = spidev.SpiDev()
        self._spi.open(0, 0)
        self._spi.max_speed_hz = s.display_spi_hz
        self._spi.mode = s.display_spi_mode
        self._init_panel(s.display_rotation)
        self._fill_black()
        self._bl.on()
        log.info("ST7789 ready (rotation %d, offset %d,%d, %d Hz, SPI mode %d)",
                 s.display_rotation, self._x_off, self._y_off, s.display_spi_hz, s.display_spi_mode)

    def _command(self, cmd: int, data: list[int] | None = None) -> None:
        self._dc.off()
        self._spi.writebytes([cmd])
        if data:
            self._dc.on()
            self._spi.writebytes(data)

    def _init_panel(self, rotation: int) -> None:
        self._rst.on(); time.sleep(0.01)
        self._rst.off(); time.sleep(0.02)
        self._rst.on(); time.sleep(0.15)
        self._command(_SWRESET); time.sleep(0.15)
        self._command(_SLPOUT); time.sleep(0.12)
        self._command(_COLMOD, [0x05])
        self._command(_MADCTL, [_MADCTL_BY_ROTATION[rotation]])
        for cmd, data in _INIT_SEQUENCE:
            self._command(cmd, data)
        self._command(_INVON)
        self._command(_NORON)
        self._command(_DISPON); time.sleep(0.12)

    def _set_window(self) -> None:
        x0, x1 = self._x_off, self._x_off + SIZE - 1
        y0, y1 = self._y_off, self._y_off + SIZE - 1
        self._command(_CASET, [x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF])
        self._command(_RASET, [y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF])
        self._command(_RAMWR)

    def _push(self, rgb565: bytes) -> None:
        self._set_window()
        self._dc.on()
        self._spi.writebytes2(rgb565)

    def _fill_black(self) -> None:
        self._push(bytes(SIZE * SIZE * 2))

    def show(self, image) -> None:
        data = image.tobytes()
        out = bytearray(len(data) * 2)
        out[0::2] = data.translate(self._ramp_hi)
        out[1::2] = data.translate(self._ramp_lo)
        self._push(bytes(out))

    def close(self) -> None:
        try:
            self._fill_black()
            self._bl.off()
            self._command(_DISPOFF)
        finally:
            self._spi.close()
            for pin in (self._dc, self._rst, self._bl):
                pin.close()


def create_display_device(s: Settings) -> DisplayDevice:
    """Build the configured device; falls back to the mock if hardware setup fails."""
    if s.display == "real":
        try:
            return ST7789Device(s)
        except Exception as error:  # noqa: BLE001 - hardware libs raise many kinds
            log.error("Display hardware unavailable (%s: %s); using mock display",
                      type(error).__name__, error)
    return MockDisplayDevice(s.eye_color, s.display_preview_path or None)
