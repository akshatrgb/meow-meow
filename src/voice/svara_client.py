"""Text-to-speech providers.

Svara (Kenpath) is built against its documented, OpenAI-compatible server API
(github.com/Kenpath/svara-tts-inference):

    POST {base_url}/audio/speech   JSON: input, voice, response_format, stream
    GET  {base_url}/voices
    GET  {origin}/health

``base_url`` therefore ends in ``/v1``. The docs show ``api_key="unused"`` in the
OpenAI SDK example but do not specify an auth header. We send a standard
``Authorization: Bearer <key>`` header only when a key is configured -- confirm
this against your Svara provider's dashboard.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import requests

from src.config.settings import Settings
from src.voice.audio_utils import make_tone_wav

log = logging.getLogger(__name__)

# Emotion tags documented on the svara-tts-v1 model card (placed after the sentence).
SVARA_EMOTION_TAGS = {
    "HAPPY": "<happy>", "EXCITED": "<happy>", "LOVE": "<happy>", "SAD": "<sad>",
}


class TTSError(RuntimeError):
    """Speech synthesis failed. Messages never contain credentials."""


@dataclass(frozen=True)
class AudioClip:
    """Synthesised audio ready to play."""

    data: bytes
    format: str = "wav"


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> AudioClip:
        """Convert ``text`` to speech."""


class SvaraClient(TTSProvider):
    """Client for a Svara OpenAI-compatible speech endpoint (WAV output)."""

    def __init__(self, base_url: str, api_key: str = "", voice: str = "en_female",
                 timeout_s: float = 30.0, retries: int = 1, session: Any | None = None,
                 sleep=time.sleep) -> None:
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self.voice = voice
        self._timeout = timeout_s
        self._retries = retries
        self._session = session or requests.Session()
        self._sleep = sleep

    @classmethod
    def from_settings(cls, s: Settings) -> "SvaraClient":
        return cls(s.svara_base_url, s.svara_api_key, s.svara_voice, s.svara_timeout_s)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def synthesize(self, text: str) -> AudioClip:
        return await asyncio.to_thread(self.synthesize_sync, text)

    def synthesize_sync(self, text: str) -> AudioClip:
        """Blocking synthesis with one retry for transient failures."""
        payload = {"input": text, "voice": self.voice, "response_format": "wav", "stream": False}
        last: TTSError | None = None
        for attempt in range(self._retries + 1):
            try:
                return self._request(payload)
            except _Transient as error:
                last = TTSError(str(error))
                if attempt < self._retries:
                    log.warning("Svara request failed (%s); retrying", error)
                    self._sleep(0.5)
        assert last is not None
        raise last

    def list_voices(self) -> Any:
        """Raw JSON from ``GET /voices`` (response schema is not documented)."""
        try:
            response = self._session.get(f"{self._base}/voices", headers=self._headers(),
                                         timeout=self._timeout)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TTSError(f"Could not list Svara voices ({type(exc).__name__}).") from exc

    def _request(self, payload: dict[str, Any]) -> AudioClip:
        try:
            response = self._session.post(f"{self._base}/audio/speech", headers=self._headers(),
                                          json=payload, timeout=self._timeout)
        except requests.RequestException as exc:
            raise _Transient(f"Svara unreachable ({type(exc).__name__})") from exc
        status = response.status_code
        if status in (401, 403):
            raise TTSError("Svara rejected the API key.")
        if status == 404:
            raise TTSError("Svara endpoint not found; check SVARA_BASE_URL (it should end in /v1).")
        if status in (408, 429) or status >= 500:
            raise _Transient(f"Svara error {status}")
        if status >= 400:
            raise TTSError(f"Svara error {status}: {response.text[:120]}")
        audio = response.content
        if not audio.startswith(b"RIFF"):
            raise TTSError("Svara returned audio that is not WAV; check the server response_format.")
        return AudioClip(audio, "wav")


class _Transient(TTSError):
    """Internal: failure worth one retry."""


class MockTTS(TTSProvider):
    """Generates a short tone proportional to the text length. No network."""

    async def synthesize(self, text: str) -> AudioClip:
        duration = min(3.0, 0.25 + 0.06 * len(text))
        return AudioClip(make_tone_wav(duration), "wav")
