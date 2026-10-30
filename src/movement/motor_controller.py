"""Motor control for a TB6612FNG dual H-bridge.

Safe by construction:
- the driver starts (and ends) in a safe state: STBY low, all pins low;
- nothing moves without ``MotionSafety`` approval;
- every move has a timeout that stops the motors automatically;
- stopping is always allowed and cancels any pending move.

Wiring (TB6612FNG): AIN1/AIN2/PWMA drive motor A (left), BIN1/BIN2/PWMB drive
motor B (right), STBY enables the chip (low = motors off).
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from enum import StrEnum

from src.config.settings import Settings
from src.movement.safety import Limits, MotionSafety, MovementDenied

log = logging.getLogger(__name__)


class Direction(StrEnum):
    FORWARD = "forward"
    BACKWARD = "backward"
    LEFT = "left"
    RIGHT = "right"


# (left wheel, right wheel) direction multipliers; turns spin in place.
_WHEELS = {
    Direction.FORWARD: (1, 1),
    Direction.BACKWARD: (-1, -1),
    Direction.LEFT: (-1, 1),
    Direction.RIGHT: (1, -1),
}


class MotorDriver(ABC):
    """Low-level two-wheel driver. Speeds are -1..1 (negative = reverse)."""

    @abstractmethod
    def drive(self, left: float, right: float) -> None: ...

    @abstractmethod
    def safe_state(self) -> None:
        """Brake/coast and disable the driver chip."""

    @abstractmethod
    def close(self) -> None: ...


class MockMotorDriver(MotorDriver):
    """Records commands; moves nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple[float, float]] = []
        self.safe_calls = 0
        self.closed = False

    def drive(self, left: float, right: float) -> None:
        self.calls.append((left, right))
        log.info("[mock motors] left=%.2f right=%.2f", left, right)

    def safe_state(self) -> None:
        self.safe_calls += 1
        self.calls.append((0.0, 0.0))

    def close(self) -> None:
        self.safe_state()
        self.closed = True


class TB6612Driver(MotorDriver):
    """Real TB6612FNG via gpiozero. Starts disabled (STBY low)."""

    def __init__(self, s: Settings) -> None:
        from gpiozero import DigitalOutputDevice, PWMOutputDevice

        self._stby = DigitalOutputDevice(s.motor_stby_pin, initial_value=False)
        self._a = (DigitalOutputDevice(s.motor_ain1_pin, initial_value=False),
                   DigitalOutputDevice(s.motor_ain2_pin, initial_value=False),
                   PWMOutputDevice(s.motor_pwma_pin, initial_value=0, frequency=1000))
        self._b = (DigitalOutputDevice(s.motor_bin1_pin, initial_value=False),
                   DigitalOutputDevice(s.motor_bin2_pin, initial_value=False),
                   PWMOutputDevice(s.motor_pwmb_pin, initial_value=0, frequency=1000))

    @staticmethod
    def _set(channel, speed: float) -> None:
        in1, in2, pwm = channel
        if speed > 0:
            in1.on(); in2.off()
        elif speed < 0:
            in1.off(); in2.on()
        else:
            in1.off(); in2.off()
        pwm.value = min(1.0, abs(speed))

    def drive(self, left: float, right: float) -> None:
        self._set(self._a, left)
        self._set(self._b, right)
        self._stby.on()

    def safe_state(self) -> None:
        self._stby.off()
        self._set(self._a, 0.0)
        self._set(self._b, 0.0)

    def close(self) -> None:
        self.safe_state()
        for dev in (*self._a, *self._b, self._stby):
            dev.close()


class MotorController:
    """The only way the rest of the robot moves its wheels."""

    def __init__(self, driver: MotorDriver, safety: MotionSafety) -> None:
        self._driver = driver
        self.safety = safety
        self._stop_task: asyncio.Task | None = None
        self._driver.safe_state()  # known-safe state at startup

    @classmethod
    def from_settings(cls, s: Settings) -> "MotorController":
        if s.motors == "real":
            try:
                driver: MotorDriver = TB6612Driver(s)
            except Exception as error:  # noqa: BLE001
                log.error("Motor hardware unavailable (%s: %s); using mock motors",
                          type(error).__name__, error)
                driver = MockMotorDriver()
        else:
            driver = MockMotorDriver()
        limits = Limits(s.motor_max_speed, s.motor_default_speed, s.motor_max_run_s, s.motor_default_run_s)
        return cls(driver, MotionSafety(s.movement_enabled, limits))

    @property
    def moving(self) -> bool:
        return self._stop_task is not None and not self._stop_task.done()

    async def move(self, direction: Direction, speed: float | None = None,
                   duration_s: float | None = None) -> None:
        """Move for a bounded time, then stop automatically.

        Raises:
            MovementDenied: if the safety policy refuses the request.
        """
        speed, duration_s = self.safety.authorize(speed, duration_s)
        await self._cancel_pending()
        left, right = _WHEELS[direction]
        self._driver.drive(left * speed, right * speed)
        self._stop_task = asyncio.create_task(self._stop_after(duration_s))
        log.info("Moving %s at %.2f for %.1fs", direction, speed, duration_s)

    async def stop(self) -> None:
        """Stop now. Always allowed."""
        await self._cancel_pending()
        self._driver.safe_state()

    async def emergency_stop(self) -> None:
        """Stop and latch the emergency stop until explicitly reset."""
        self.safety.emergency_stop()
        await self.stop()

    async def close(self) -> None:
        """Safe shutdown: stop, disarm, release the hardware."""
        self.safety.disarm()
        await self._cancel_pending()
        self._driver.close()

    async def _stop_after(self, seconds: float) -> None:
        try:
            await asyncio.sleep(seconds)
        finally:  # runs on cancellation too, so a cancelled task can never leave motors on
            self._driver.safe_state()

    async def _cancel_pending(self) -> None:
        task, self._stop_task = self._stop_task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
