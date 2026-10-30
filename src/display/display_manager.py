"""Connects robot state/emotion events to the eyes and drives the render loop.

CPU-saving rules: a frame is only rendered and sent over SPI when it would
look different from the previous one, and rendering runs in a worker thread so
the event loop (audio, networking) is never blocked.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from src.ai.personality import Emotion
from src.core.event_bus import EMOTION_CHANGED, STATE_CHANGED, EventBus
from src.core.state_manager import State
from src.display.animations import Animator
from src.display.expressions import EMOTION_TO_EXPRESSION, Expression
from src.hardware.display_device import DisplayDevice

log = logging.getLogger(__name__)


class DisplayManager:
    def __init__(
        self,
        device: DisplayDevice,
        renderer,
        *,
        fps: int = 12,
        idle_sleep_s: float = 180.0,
        animator: Animator | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._device = device
        self._renderer = renderer
        self._frame_time = 1.0 / fps
        self._idle_sleep_s = idle_sleep_s
        self._animator = animator or Animator()
        self._clock = clock
        self._mood = Expression.NORMAL
        self._state = State.IDLE
        self._idle_since = clock()
        self._last_key: tuple | None = None
        self._last_tick = clock()
        self._task: asyncio.Task | None = None

    def attach(self, bus: EventBus) -> None:
        bus.subscribe(STATE_CHANGED, self.on_state)
        bus.subscribe(EMOTION_CHANGED, self.on_emotion)

    # ------------------------------------------------------------- events
    def on_emotion(self, emotion: Emotion) -> None:
        self._mood = EMOTION_TO_EXPRESSION.get(emotion, Expression.NORMAL)

    def on_state(self, state: State) -> None:
        self._state = state
        if state is State.IDLE:
            self._idle_since = self._clock()
            self._mood = Expression.NORMAL
        self._apply_expression()

    def _apply_expression(self) -> None:
        by_state = {
            State.LISTENING: Expression.CURIOUS,
            State.THINKING: Expression.THINKING,
            State.OFFLINE: Expression.OFFLINE,
            State.SLEEPING: Expression.SLEEPY,
            State.ERROR: Expression.CONFUSED,
            State.SPEAKING: self._mood,
            State.IDLE: Expression.NORMAL,
        }
        self._animator.set_expression(by_state[self._state])

    # --------------------------------------------------------------- loop
    def tick(self) -> bool:
        """Advance animation; render and send a frame if it changed. Returns True if sent."""
        now = self._clock()
        dt, self._last_tick = now - self._last_tick, now
        if self._state is State.IDLE and now - self._idle_since > self._idle_sleep_s:
            self._animator.set_expression(Expression.SLEEPY)
        state = self._animator.update(dt)
        key = state.key()
        if key == self._last_key:
            return False
        self._last_key = key
        self._device.show(self._renderer.render(state))
        return True

    async def run(self) -> None:
        """Render until cancelled."""
        log.info("Display loop started")
        while True:
            started = self._clock()
            try:
                await asyncio.to_thread(self.tick)
            except Exception:  # noqa: BLE001 - a display glitch must not kill the robot
                log.exception("Display frame failed")
                await asyncio.sleep(1.0)
            await asyncio.sleep(max(0.0, self._frame_time - (self._clock() - started)))

    def start(self) -> None:
        self._task = asyncio.create_task(self.run(), name="display")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        self._device.close()
