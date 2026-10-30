"""Maps the renderer's grayscale intensity image to colours.

The renderer draws a single-channel (0-255) image. Intensity 0 is the black
background, ``EYE_LEVEL`` is the eye colour and 255 is white (sparkle
highlights). One 256-entry ramp turns that into any colour format.
"""

from __future__ import annotations

EYE_LEVEL = 200
Color = tuple[int, int, int]


def build_ramp(eye_color: Color) -> list[Color]:
    """256 RGB entries: black -> eye colour (at EYE_LEVEL) -> white (at 255)."""
    ramp: list[Color] = []
    for i in range(256):
        if i <= EYE_LEVEL:
            f = i / EYE_LEVEL
            ramp.append(tuple(int(c * f) for c in eye_color))  # type: ignore[arg-type]
        else:
            f = (i - EYE_LEVEL) / (255 - EYE_LEVEL)
            ramp.append(tuple(int(c + (255 - c) * f) for c in eye_color))  # type: ignore[arg-type]
    return ramp


def rgb565_tables(ramp: list[Color]) -> tuple[bytes, bytes]:
    """(high_byte_table, low_byte_table) for ``bytes.translate`` -> big-endian RGB565."""
    hi, lo = bytearray(256), bytearray(256)
    for i, (r, g, b) in enumerate(ramp):
        value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        hi[i], lo[i] = value >> 8, value & 0xFF
    return bytes(hi), bytes(lo)
