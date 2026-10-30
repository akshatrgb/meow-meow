"""Speech-to-text providers.

Whisper-class models are far too heavy for a Pi Zero W, so recognition is done
by a cloud service that speaks the de-facto standard OpenAI
``/audio/transcriptions`` protocol (Groq, OpenAI and others). Swapping provider
is a configuration change.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

import requests

from src.config.settings import Settings

log = logging.getLogger(__name__)


class STTError(RuntimeError):
    """Speech recognition failed. Messages never contain credentials."""


class SpeechRecognizer(ABC):
    @abstractmethod
    async def transcribe(self, wav_bytes: bytes) -> str:
        """Return the recognised text ('' if nothing intelligible)."""


class OpenAICompatibleRecognizer(SpeechRecognizer):
    """POST multipart audio to ``{base_url}/audio/transcriptions``."""

    def __init__(self, base_url: str, api_key: str, model: str, language: str = "en",
                 timeout_s: float = 20.0, session: Any | None = None) -> None:
        self._url = base_url.rstrip("/") + "/audio/transcriptions"
        self._api_key = api_key
        self._model = model
        self._language = language
        self._timeout = timeout_s
        self._session = session or requests.Session()

    @classmethod
    def from_settings(cls, s: Settings) -> "OpenAICompatibleRecognizer":
        return cls(s.stt_base_url, s.stt_api_key, s.stt_model, s.stt_language, s.stt_timeout_s)

    async def transcribe(self, wav_bytes: bytes) -> str:
        return await asyncio.to_thread(self._transcribe_sync, wav_bytes)

    def _transcribe_sync(self, wav_bytes: bytes) -> str:
        data = {"model": self._model, "response_format": "json"}
        if self._language:
            data["language"] = self._language
        try:
            response = self._session.post(
                self._url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                files={"file": ("speech.wav", wav_bytes, "audio/wav")},
                data=data,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise STTError(f"Speech service unreachable ({type(exc).__name__}).") from exc
        if response.status_code in (401, 403):
            raise STTError("Speech service rejected the API key.")
        if response.status_code >= 400:
            raise STTError(f"Speech service error {response.status_code}.")
        try:
            return str(response.json().get("text", "")).strip()
        except (ValueError, AttributeError) as exc:
            raise STTError("Speech service returned an unreadable response.") from exc


class MockRecognizer(SpeechRecognizer):
    """Returns a fixed phrase; for tests and development without a speech key."""

    def __init__(self, text: str = "hello meow meow") -> None:
        self._text = text

    async def transcribe(self, wav_bytes: bytes) -> str:
        return self._text
