"""A tiny asyncio publish/subscribe bus that decouples modules.

The AI code publishes *what happened* (emotion changed, state changed); the
display subscribes. Neither imports the other.
"""

from __future__ import annotations

import inspect
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

# Topics
STATE_CHANGED = "state.changed"      # payload: State
EMOTION_CHANGED = "emotion.changed"  # payload: Emotion
USER_SPOKE = "user.spoke"            # payload: str (never logged)
ASSISTANT_REPLIED = "assistant.replied"  # payload: Reply

Handler = Callable[[Any], Awaitable[None] | None]


class EventBus:
    """Publish/subscribe. A failing handler never affects other handlers or the publisher."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._handlers[topic].append(handler)

    async def publish(self, topic: str, payload: Any = None) -> None:
        for handler in list(self._handlers[topic]):
            try:
                result = handler(payload)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001 - isolate subscribers
                log.exception("Event handler failed for %s", topic)
