"""Movement safety policy.

Motors may move only when ALL of these hold:
  1. ``MOVEMENT_ENABLED=true`` in configuration,
  2. the user has explicitly *armed* movement at runtime (it never starts armed),
  3. the emergency stop is not latched,
and every command is clamped to a maximum speed and duration.
Stopping is always allowed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


class MovementDenied(RuntimeError):
    """A movement command was refused by the safety policy (message explains why)."""


@dataclass(frozen=True)
class Limits:
    max_speed: float = 0.6
    default_speed: float = 0.5
    max_run_s: float = 2.0
    default_run_s: float = 1.0


class MotionSafety:
    def __init__(self, enabled: bool, limits: Limits | None = None) -> None:
        self.enabled = enabled
        self.limits = limits or Limits()
        self.armed = False
        self.estop_latched = False

    def arm(self) -> None:
        """Explicitly allow movement (only meaningful when enabled in config)."""
        if not self.enabled:
            raise MovementDenied("Movement is disabled in the configuration (MOVEMENT_ENABLED=false).")
        if self.estop_latched:
            raise MovementDenied("Emergency stop is latched; reset it first.")
        self.armed = True
        log.warning("Movement ARMED")

    def disarm(self) -> None:
        self.armed = False
        log.info("Movement disarmed")

    def emergency_stop(self) -> None:
        """Latch the emergency stop and disarm. Must be reset explicitly."""
        self.estop_latched = True
        self.armed = False
        log.warning("EMERGENCY STOP latched")

    def reset_estop(self) -> None:
        self.estop_latched = False
        log.info("Emergency stop reset (movement stays disarmed)")

    def authorize(self, speed: float | None, duration_s: float | None) -> tuple[float, float]:
        """Validate a move request and return the clamped ``(speed, duration_s)``."""
        if not self.enabled:
            raise MovementDenied("Movement is disabled in the configuration.")
        if self.estop_latched:
            raise MovementDenied("Emergency stop is latched.")
        if not self.armed:
            raise MovementDenied("Movement is not armed. Arm it first.")
        lim = self.limits
        speed = lim.default_speed if speed is None else speed
        duration_s = lim.default_run_s if duration_s is None else duration_s
        if speed <= 0 or duration_s <= 0:
            raise MovementDenied("Speed and duration must be positive.")
        return min(speed, lim.max_speed), min(duration_s, lim.max_run_s)
