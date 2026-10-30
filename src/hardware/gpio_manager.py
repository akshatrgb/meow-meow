"""GPIO pin ownership registry.

Nothing in the robot may use a pin without claiming it here, so two components
can never silently share one. Bus pins (I2S audio, SPI0 display) are claimed
unconditionally, even when the component runs in mock mode, because the wiring
plan always reserves them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.config.settings import Settings

# BCM GPIO number -> physical header pin on the 40-pin connector.
PHYSICAL_PIN = {
    2: 3, 3: 5, 4: 7, 5: 29, 6: 31, 7: 26, 8: 24, 9: 21, 10: 19, 11: 23,
    12: 32, 13: 33, 14: 8, 15: 10, 16: 36, 17: 11, 18: 12, 19: 35, 20: 38,
    21: 40, 22: 15, 23: 16, 24: 18, 25: 22, 26: 37, 27: 13,
}

# Fixed-function bus pins on the Pi Zero W.
I2S_PINS = {18: "I2S BCLK (mic SCK + amp BCLK)", 19: "I2S LRCLK (mic WS + amp LRC)",
            20: "I2S DIN (mic SD)", 21: "I2S DOUT (amp DIN)"}
SPI0_PINS = {8: "SPI0 CE0 (display CS)", 10: "SPI0 MOSI (display SDA)",
             11: "SPI0 SCLK (display SCL)", 9: "SPI0 MISO (unused, reserved)",
             7: "SPI0 CE1 (reserved)"}


class PinConflictError(RuntimeError):
    """Two components tried to use the same GPIO pin."""


@dataclass(frozen=True)
class PinClaim:
    gpio: int
    owner: str
    function: str


class PinRegistry:
    """Tracks which component owns which BCM GPIO pin."""

    def __init__(self) -> None:
        self._claims: dict[int, PinClaim] = {}

    def claim(self, owner: str, pins: dict[int, str] | Iterable[int]) -> None:
        """Claim pins for ``owner``.

        Args:
            owner: component name, e.g. ``"motors"``.
            pins: mapping ``gpio -> function`` or an iterable of gpio numbers.

        Raises:
            PinConflictError: if a pin is out of range or already claimed.
        """
        items = pins.items() if isinstance(pins, dict) else ((p, "") for p in pins)
        new: list[PinClaim] = []
        problems: list[str] = []
        for gpio, function in items:
            if not 2 <= gpio <= 27:
                problems.append(f"GPIO{gpio} ({owner}) is not a usable header pin (2-27)")
                continue
            existing = self._claims.get(gpio) or next((c for c in new if c.gpio == gpio), None)
            if existing:
                problems.append(
                    f"GPIO{gpio} wanted by {owner} ({function or 'pin'}) "
                    f"but already used by {existing.owner} ({existing.function or 'pin'})"
                )
            else:
                new.append(PinClaim(gpio, owner, function))
        if problems:
            raise PinConflictError("; ".join(problems))
        for claim in new:
            self._claims[claim.gpio] = claim

    def table(self) -> list[PinClaim]:
        """All claims sorted by GPIO number."""
        return sorted(self._claims.values(), key=lambda c: c.gpio)


def build_pin_registry(s: Settings) -> PinRegistry:
    """Claim every pin of the planned robot and fail fast on conflicts."""
    reg = PinRegistry()
    reg.claim("i2s-audio", I2S_PINS)
    reg.claim("display", {
        **SPI0_PINS,
        s.display_dc_pin: "display DC",
        s.display_rst_pin: "display RST",
        s.display_bl_pin: "display backlight",
    })
    reg.claim("motors", {
        s.motor_ain1_pin: "AIN1", s.motor_ain2_pin: "AIN2", s.motor_pwma_pin: "PWMA",
        s.motor_bin1_pin: "BIN1", s.motor_bin2_pin: "BIN2", s.motor_pwmb_pin: "PWMB",
        s.motor_stby_pin: "STBY",
    })
    return reg


def format_pin_table(reg: PinRegistry) -> str:
    """Human readable wiring table for diagnostics."""
    rows = ["GPIO  Header  Owner        Function", "----  ------  -----------  --------------------------"]
    for c in reg.table():
        rows.append(f"{c.gpio:<4}  {PHYSICAL_PIN.get(c.gpio, '?'):<6}  {c.owner:<11}  {c.function}")
    return "\n".join(rows)
