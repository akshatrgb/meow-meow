"""Robot-level state machine (what Meow Meow is doing right now)."""

from __future__ import annotations

import logging
from enum import StrEnum

from src.core.event_bus import STATE_CHANGED, EventBus

log = logging.getLogger(__name__)


class State(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    OFFLINE = "offline"
    SLEEPING = "sleeping"
    ERROR = "error"


class StateManager:
    """Holds the current :class:`State` and announces changes on the bus."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._state = State.IDLE

    @property
    def state(self) -> State:
        return self._state

    async def set(self, state: State) -> None:
        if state == self._state:
            return
        log.debug("state %s -> %s", self._state, state)
        self._state = state
        await self._bus.publish(STATE_CHANGED, state)
