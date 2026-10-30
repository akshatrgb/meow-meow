import random

import pytest

from src.ai.personality import Emotion
from src.core.state_manager import State
from src.display.animations import Animator
from src.display.expressions import EMOTION_TO_EXPRESSION, EXPRESSIONS, Expression
from src.display.palette import EYE_LEVEL, build_ramp, rgb565_tables


def test_every_emotion_and_expression_is_defined():
    assert set(EMOTION_TO_EXPRESSION) == set(Emotion)
    assert set(EXPRESSIONS) == set(Expression)


def settle(anim, seconds=3.0, dt=0.05):
    state = None
    for _ in range(int(seconds / dt)):
        state = anim.update(dt)
    return state


def test_animator_converges_to_expression():
    anim = Animator(random.Random(1))
    anim.set_expression(Expression.SLEEPY)
    s = settle(anim, 4)
    assert s.lid_top == pytest.approx(0.55, abs=0.08)
    assert s.height == pytest.approx(60, abs=1)


def test_blinks_happen_and_close_the_eye():
    anim = Animator(random.Random(2))
    blinks = [anim.update(0.05).blink for _ in range(400)]  # 20 simulated seconds
    assert max(blinks) > 0.9
    assert blinks.count(0.0) > len(blinks) * 0.7  # mostly open


def test_gaze_stays_inside_bounds():
    anim = Animator(random.Random(3))
    for _ in range(600):
        s = anim.update(0.05)
        assert abs(s.gaze_x) <= 12.01 and abs(s.gaze_y) <= 10.01


def test_static_scene_yields_stable_keys_so_frames_can_be_skipped():
    anim = Animator(random.Random(4))
    settle(anim, 5)
    # between blinks/glances consecutive keys repeat
    keys = [anim.update(0.05).key() for _ in range(40)]
    assert len(set(keys)) < len(keys)


def test_huge_dt_is_clamped():
    assert Animator().update(100.0).width > 0


# ---- renderer / manager (need Pillow)
PIL = pytest.importorskip("PIL")


def test_every_expression_renders_non_empty_frames():
    from src.display.eye_renderer import EyeRenderer

    renderer = EyeRenderer()
    for expression in Expression:
        anim = Animator(random.Random(5))
        anim.set_expression(expression)
        image = renderer.render(settle(anim, 2))
        assert image.size == (240, 240) and image.mode == "L"
        assert image.getbbox() is not None, expression
        assert image.getextrema()[1] > 0


def test_closed_eye_is_much_flatter_than_open_eye():
    from dataclasses import replace

    from src.display.eye_renderer import EyeRenderer

    renderer = EyeRenderer()
    open_state = Animator(random.Random(6)).update(0.0)
    open_box = renderer.render(open_state).getbbox()
    closed_box = renderer.render(replace(open_state, blink=1.0)).getbbox()
    assert (closed_box[3] - closed_box[1]) < (open_box[3] - open_box[1]) * 0.3


def test_ramp_and_rgb565():
    ramp = build_ramp((0, 200, 255))
    assert ramp[0] == (0, 0, 0) and ramp[EYE_LEVEL] == (0, 200, 255) and ramp[255] == (255, 255, 255)
    hi, lo = rgb565_tables(ramp)
    assert (hi[255], lo[255]) == (0xFF, 0xFF) and (hi[0], lo[0]) == (0, 0)


def test_display_manager_follows_events_and_skips_identical_frames():
    from src.display.display_manager import DisplayManager
    from src.display.eye_renderer import EyeRenderer
    from src.hardware.display_device import MockDisplayDevice

    now = [0.0]
    device = MockDisplayDevice()
    manager = DisplayManager(device, EyeRenderer(), clock=lambda: now[0], animator=Animator(random.Random(7)))

    def advance(seconds, dt=0.05):
        for _ in range(int(seconds / dt)):
            now[0] += dt
            manager.tick()

    advance(0.2)
    assert device.frames >= 1
    manager.on_emotion(Emotion.SAD)
    manager.on_state(State.SPEAKING)
    advance(2)
    assert manager._animator.expression is Expression.SAD
    manager.on_state(State.IDLE)
    assert manager._animator.expression is Expression.NORMAL
    manager.on_state(State.OFFLINE)
    assert manager._animator.expression is Expression.OFFLINE
    advance(8)
    total_ticks = int(10.2 / 0.05)
    assert device.frames < total_ticks * 0.6  # frames were skipped when nothing changed
    assert device.ascii().strip()  # dim OFFLINE eyes are still drawn


def test_idle_eventually_falls_asleep():
    from src.display.display_manager import DisplayManager
    from src.display.eye_renderer import EyeRenderer
    from src.hardware.display_device import MockDisplayDevice

    now = [0.0]
    manager = DisplayManager(MockDisplayDevice(), EyeRenderer(), idle_sleep_s=10, clock=lambda: now[0])
    now[0] = 11.0
    manager.tick()
    assert manager._animator.expression is Expression.SLEEPY


def test_mock_device_writes_preview_png(tmp_path):
    from src.display.eye_renderer import EyeRenderer
    from src.hardware.display_device import MockDisplayDevice

    device = MockDisplayDevice(preview_path=tmp_path / "eyes.png", preview_interval_s=0)
    device.show(EyeRenderer().render(Animator().update(0.0)))
    assert (tmp_path / "eyes.png").stat().st_size > 100
