import asyncio

import pytest

from src.movement.intents import parse_movement
from src.movement.motor_controller import Direction, MockMotorDriver, MotorController
from src.movement.safety import Limits, MotionSafety, MovementDenied


def make(enabled=True, armed=True):
    driver = MockMotorDriver()
    safety = MotionSafety(enabled, Limits(max_speed=0.6, default_speed=0.5, max_run_s=2.0, default_run_s=1.0))
    controller = MotorController(driver, safety)
    if armed:
        safety.arm()
    return controller, driver, safety


def test_starts_in_safe_state_and_unarmed():
    controller, driver, safety = make(armed=False)
    assert driver.safe_calls == 1 and not safety.armed


def test_cannot_move_when_disabled_or_unarmed():
    controller, driver, _ = make(enabled=False, armed=False)
    with pytest.raises(MovementDenied):
        asyncio.run(controller.move(Direction.FORWARD))
    controller, driver, _ = make(enabled=True, armed=False)
    with pytest.raises(MovementDenied):
        asyncio.run(controller.move(Direction.FORWARD))
    assert all(c == (0.0, 0.0) for c in driver.calls)


def test_arming_requires_enabled_config():
    with pytest.raises(MovementDenied):
        MotionSafety(False).arm()


def test_speed_and_duration_are_clamped():
    _, _, safety = make()
    assert safety.authorize(5.0, 99.0) == (0.6, 2.0)
    assert safety.authorize(None, None) == (0.5, 1.0)
    with pytest.raises(MovementDenied):
        safety.authorize(-1, 1)


def test_directions_map_to_wheels_and_auto_stop_after_timeout():
    async def scenario(direction):
        controller, driver, _ = make()
        await controller.move(direction, speed=0.5, duration_s=0.05)
        moving = driver.calls[-1]
        await asyncio.sleep(0.15)
        return moving, driver.calls[-1], controller.moving

    assert asyncio.run(scenario(Direction.FORWARD))[0] == (0.5, 0.5)
    assert asyncio.run(scenario(Direction.BACKWARD))[0] == (-0.5, -0.5)
    assert asyncio.run(scenario(Direction.LEFT))[0] == (-0.5, 0.5)
    assert asyncio.run(scenario(Direction.RIGHT))[0] == (0.5, -0.5)
    _, after, moving = asyncio.run(scenario(Direction.FORWARD))
    assert after == (0.0, 0.0) and not moving


def test_stop_cancels_pending_move_and_is_always_allowed():
    async def scenario():
        controller, driver, safety = make()
        await controller.move(Direction.FORWARD, duration_s=1.0)
        safety.disarm()
        await controller.stop()
        return driver.calls[-1], controller.moving

    assert asyncio.run(scenario()) == ((0.0, 0.0), False)


def test_emergency_stop_latches_until_reset():
    async def scenario():
        controller, driver, safety = make()
        await controller.move(Direction.FORWARD)
        await controller.emergency_stop()
        stopped = driver.calls[-1]
        with pytest.raises(MovementDenied):
            await controller.move(Direction.FORWARD)
        with pytest.raises(MovementDenied):
            safety.arm()
        safety.reset_estop()
        safety.arm()
        await controller.move(Direction.FORWARD, duration_s=0.05)
        await controller.stop()
        return stopped

    assert asyncio.run(scenario()) == (0.0, 0.0)


def test_new_move_replaces_old_one():
    async def scenario():
        controller, driver, _ = make()
        await controller.move(Direction.FORWARD, duration_s=0.3)
        await controller.move(Direction.LEFT, duration_s=0.05)
        await asyncio.sleep(0.15)
        return driver.calls[-1]

    assert asyncio.run(scenario()) == (0.0, 0.0)


def test_close_leaves_motors_safe():
    async def scenario():
        controller, driver, safety = make()
        await controller.move(Direction.FORWARD)
        await controller.close()
        return driver.calls[-1], driver.closed, safety.armed

    assert asyncio.run(scenario()) == ((0.0, 0.0), True, False)


@pytest.mark.parametrize("text,action,secs", [
    ("forward", "forward", None),
    ("Meow meow, please go forward for 2 seconds", "forward", 2.0),
    ("turn left", "left", None),
    ("turn to the right please", "right", None),
    ("go back", "backward", None),
    ("stop", "stop", None),
    ("emergency stop!", "estop", None),
    ("enable movement", "arm", None),
    ("disable motors", "disarm", None),
])
def test_movement_commands_are_recognised(text, action, secs):
    intent = parse_movement(text)
    assert intent is not None and (intent.action, intent.duration_s) == (action, secs)


@pytest.mark.parametrize("text", [
    "I can't stop thinking about you", "what is a forward pass", "please don't go back to sleep",
    "turn on the lights", "tell me a story about going forward in life", "hello", "",
])
def test_conversation_never_triggers_movement(text):
    assert parse_movement(text) is None
