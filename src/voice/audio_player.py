"""Audio playback through ALSA's ``aplay``.

WAV bytes are streamed to ``aplay`` over stdin, so no temporary audio files are
ever written to the SD card (and there is nothing to clean up).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from abc import ABC, abstractmethod

from src.hardware.microphone import AudioError
from src.voice.audio_utils import wav_duration
from src.voice.svara_client import AudioClip

log = logging.getLogger(__name__)


class AudioPlayer(ABC):
    @abstractmethod
    async def play(self, clip: AudioClip) -> None:
        """Play ``clip`` and return when finished (or stopped)."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop any playback immediately. Safe to call when idle."""


class AplayPlayer(AudioPlayer):
    def __init__(self, device: str = "default") -> None:
        self._device = device
        self._proc: asyncio.subprocess.Process | None = None

    async def play(self, clip: AudioClip) -> None:
        if shutil.which("aplay") is None:
            raise AudioError("`aplay` not found. Install it with: sudo apt install alsa-utils")
        proc = await asyncio.create_subprocess_exec(
            "aplay", "-q", "-D", self._device,
            stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        self._proc = proc
        try:
            _, stderr = await proc.communicate(clip.data)
        except asyncio.CancelledError:
            await self.stop()
            raise
        finally:
            if self._proc is proc:
                self._proc = None
        if proc.returncode not in (0, -15):  # -15: terminated by stop()
            raise AudioError(f"Playback failed: {stderr.decode(errors='replace').strip()[:200]}")

    async def stop(self) -> None:
        proc = self._proc
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 1.0)
            except asyncio.TimeoutError:
                proc.kill()


class MockPlayer(AudioPlayer):
    """Pretends to play: waits briefly so the 'speaking' state is observable."""

    def __init__(self, max_wait_s: float = 1.0) -> None:
        self.played: list[AudioClip] = []
        self._max_wait = max_wait_s

    async def play(self, clip: AudioClip) -> None:
        self.played.append(clip)
        log.info("[mock speaker] playing %.1fs of audio", wav_duration(clip.data))
        await asyncio.sleep(min(wav_duration(clip.data), self._max_wait))

    async def stop(self) -> None:
        return None
