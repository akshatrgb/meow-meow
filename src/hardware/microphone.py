"""Microphone access. ALSA's ``arecord`` is used instead of PyAudio: no compiled
dependency, tiny memory footprint, and it works with the I2S sound card
produced by the device-tree overlay."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import Iterable

log = logging.getLogger(__name__)


class AudioError(RuntimeError):
    """Capture or playback hardware failed."""


class PcmSource(ABC):
    """A stream of signed 16-bit mono PCM chunks."""

    sample_rate: int = 16000

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def read(self, n_bytes: int) -> bytes:
        """Read exactly ``n_bytes`` (raises :class:`AudioError` on failure)."""

    @abstractmethod
    async def stop(self) -> None: ...


class ArecordSource(PcmSource):
    """Streams raw PCM from ``arecord`` (ALSA)."""

    def __init__(self, device: str = "default", sample_rate: int = 16000, read_timeout_s: float = 3.0) -> None:
        self.device = device
        self.sample_rate = sample_rate
        self._read_timeout = read_timeout_s
        self._proc: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        if self._proc is not None:
            return
        if shutil.which("arecord") is None:
            raise AudioError("`arecord` not found. Install it with: sudo apt install alsa-utils")
        self._proc = await asyncio.create_subprocess_exec(
            "arecord", "-q", "-D", self.device, "-t", "raw", "-f", "S16_LE",
            "-r", str(self.sample_rate), "-c", "1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )

    async def read(self, n_bytes: int) -> bytes:
        if self._proc is None or self._proc.stdout is None:
            raise AudioError("Microphone is not started.")
        try:
            return await asyncio.wait_for(self._proc.stdout.readexactly(n_bytes), self._read_timeout)
        except asyncio.TimeoutError as exc:
            raise AudioError("Microphone produced no audio (check AUDIO_IN_DEVICE).") from exc
        except asyncio.IncompleteReadError as exc:
            detail = await self._stderr_text()
            raise AudioError(f"Microphone stream ended. {detail}".strip()) from exc

    async def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 2.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

    async def _stderr_text(self) -> str:
        if self._proc is None or self._proc.stderr is None:
            return ""
        try:
            data = await asyncio.wait_for(self._proc.stderr.read(300), 0.5)
            return data.decode(errors="replace").strip()
        except asyncio.TimeoutError:
            return ""


class ListSource(PcmSource):
    """Plays back prepared chunks, then silence. For tests and mock mode."""

    def __init__(self, chunks: Iterable[bytes], sample_rate: int = 16000) -> None:
        self.sample_rate = sample_rate
        self._chunks = list(chunks)
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def read(self, n_bytes: int) -> bytes:
        await asyncio.sleep(0)
        if self._chunks:
            return self._chunks.pop(0)
        return b"\x00" * n_bytes

    async def stop(self) -> None:
        self.stopped = True


def list_capture_devices() -> str:
    """Output of ``arecord -l`` for diagnostics (empty string if unavailable)."""
    if shutil.which("arecord") is None:
        return ""
    result = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=5, check=False)
    return (result.stdout or result.stderr).strip()
