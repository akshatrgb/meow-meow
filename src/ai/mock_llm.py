"""An offline stand-in for the LLM so the rest of the robot can be developed
and tested without an API key. It cycles through every emotion, which makes it
handy for checking the eyes."""

from __future__ import annotations

import itertools
import json
from typing import Sequence

from src.ai.personality import Emotion


class MockChatClient:
    def __init__(self) -> None:
        self._emotions = itertools.cycle(Emotion)

    async def acomplete(self, messages: Sequence[dict[str, str]]) -> str:
        said = messages[-1]["content"]
        emotion = next(self._emotions)
        return json.dumps({"message": f"[mock] You said: {said}. Meow meow!", "emotion": emotion.value})
