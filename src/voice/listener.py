"""Sources of user input: typed text or spoken words.

Both expose ``listen()`` returning the user's text, or None if nothing was
said, so the application loop is identical for typing and talking.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from src.voice.audio_capture import AudioCapture
from src.voice.audio_utils import pcm_to_wav
from src.voice.speech_recognition import SpeechRecognizer

log = logging.getLogger(__name__)

SpeechStartHook = Callable[[], Awaitable[None]]


class Listener(ABC):
    @abstractmethod
    async def listen(self, on_speech_start: SpeechStartHook | None = None) -> str | None:
        """Wait for the next user input. Returns None on timeout/silence."""

    async def wait_for_interruption(self) -> None:
        """Return when the user tries to interrupt. Default: never."""
        await asyncio.Event().wait()


class TextListener(Listener):
    """Reads lines from the terminal without blocking the event loop or leaving threads behind."""

    def __init__(self, prompt: str = "You: ") -> None:
        self._prompt = prompt

    async def listen(self, on_speech_start: SpeechStartHook | None = None) -> str | None:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()

        def on_readable() -> None:
            line = sys.stdin.readline()
            if not future.done():
                future.set_result(line)

        sys.stdout.write(self._prompt)
        sys.stdout.flush()
        loop.add_reader(sys.stdin.fileno(), on_readable)
        try:
            line = await future
        finally:
            loop.remove_reader(sys.stdin.fileno())
        if line == "":  # EOF (Ctrl-D / closed pipe)
            raise EOFError
        return line.strip() or None


class VoiceListener(Listener):
    """Microphone -> VAD -> speech recognition."""

    def __init__(self, capture: AudioCapture, recognizer: SpeechRecognizer, timeout_s: float = 20.0,
                 min_speech_bytes: int = 8000) -> None:
        self._capture = capture
        self._recognizer = recognizer
        self._timeout = timeout_s
        self._min_bytes = min_speech_bytes  # ~0.25s at 16kHz: ignore clicks and coughs

    async def listen(self, on_speech_start: SpeechStartHook | None = None) -> str | None:
        pcm = await self._capture.record_utterance(self._timeout, on_speech_start)
        if not pcm or len(pcm) < self._min_bytes:
            return None
        text = await self._recognizer.transcribe(pcm_to_wav(pcm, self._capture.sample_rate))
        return text or None

    async def wait_for_interruption(self) -> None:
        await self._capture.wait_for_interruption()
