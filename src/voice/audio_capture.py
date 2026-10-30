"""Voice activity detection and utterance capture.

Energy-based VAD with an adaptive noise floor. It is deliberately simple: the
Pi Zero W cannot afford a neural VAD, and an RMS gate works well for a
close-range microphone. Heavy lifting (speech recognition) happens in the cloud.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from enum import Enum
from typing import Callable

from src.hardware.microphone import PcmSource
from src.voice.audio_utils import apply_gain, rms

log = logging.getLogger(__name__)

CHUNK_MS = 30


class VadEvent(Enum):
    NONE = 0
    SPEECH_STARTED = 1
    UTTERANCE_COMPLETE = 2


class UtteranceDetector:
    """Feed it PCM chunks; it reports when speech starts and when the utterance ends.

    The threshold is ``max(min_rms, noise_floor * threshold_factor) * threshold_scale``
    where the noise floor tracks the quiet chunks. ``threshold_scale > 1`` is used
    during playback (barge-in) so the robot's own voice does not trigger it.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        *,
        min_rms: float = 300.0,
        threshold_factor: float = 3.0,
        silence_ms: int = 800,
        min_speech_ms: int = 240,
        max_utterance_s: float = 15.0,
        preroll_ms: int = 300,
        threshold_scale: float = 1.0,
    ) -> None:
        self._rate = sample_rate
        self._min_rms = min_rms
        self._factor = threshold_factor
        self._silence_ms = silence_ms
        self._min_speech_ms = min_speech_ms
        self._max_ms = max_utterance_s * 1000
        self._preroll_ms = preroll_ms
        self._scale = threshold_scale
        self.reset()

    def reset(self) -> None:
        self._noise: float | None = None
        self._preroll: deque[tuple[bytes, float]] = deque()
        self._preroll_total = 0.0
        self._voiced_ms = 0.0
        self._speaking = False
        self._silent_ms = 0.0
        self._total_ms = 0.0
        self._buffer = bytearray()

    @property
    def threshold(self) -> float:
        noise = self._noise or 0.0
        return max(self._min_rms, noise * self._factor) * self._scale

    def audio(self) -> bytes:
        """PCM of the utterance captured so far (including pre-roll)."""
        return bytes(self._buffer)

    def feed(self, chunk: bytes) -> VadEvent:
        ms = len(chunk) / 2 / self._rate * 1000
        level = rms(chunk)
        voiced = level > self.threshold

        if not self._speaking:
            if not voiced:  # only quiet audio updates the noise floor
                self._noise = level if self._noise is None else 0.95 * self._noise + 0.05 * level
            self._preroll.append((chunk, ms))
            self._preroll_total += ms
            while self._preroll_total > self._preroll_ms and len(self._preroll) > 1:
                _, dropped = self._preroll.popleft()
                self._preroll_total -= dropped
            self._voiced_ms = self._voiced_ms + ms if voiced else 0.0
            if self._voiced_ms >= self._min_speech_ms:
                self._speaking = True
                self._buffer = bytearray(b"".join(c for c, _ in self._preroll))
                self._total_ms = self._preroll_total
                self._silent_ms = 0.0
                return VadEvent.SPEECH_STARTED
            return VadEvent.NONE

        self._buffer += chunk
        self._total_ms += ms
        self._silent_ms = 0.0 if voiced else self._silent_ms + ms
        if self._silent_ms >= self._silence_ms or self._total_ms >= self._max_ms:
            return VadEvent.UTTERANCE_COMPLETE
        return VadEvent.NONE


class AudioCapture:
    """Records one spoken utterance from a :class:`PcmSource`."""

    def __init__(
        self,
        source: PcmSource,
        *,
        gain: float = 1.0,
        min_rms: float = 300.0,
        threshold_factor: float = 3.0,
        silence_ms: int = 800,
        max_utterance_s: float = 15.0,
    ) -> None:
        self._source = source
        self._gain = gain
        self._vad_args = dict(min_rms=min_rms, threshold_factor=threshold_factor,
                              silence_ms=silence_ms, max_utterance_s=max_utterance_s)
        self._chunk_bytes = int(source.sample_rate * CHUNK_MS / 1000) * 2

    @property
    def sample_rate(self) -> int:
        return self._source.sample_rate

    async def record_utterance(
        self, timeout_s: float, on_speech_start: Callable[[], object] | None = None
    ) -> bytes | None:
        """Wait up to ``timeout_s`` for speech; return its PCM, or None on silence."""
        detector = UtteranceDetector(self._source.sample_rate, **self._vad_args)
        deadline = time.monotonic() + timeout_s
        await self._source.start()
        try:
            while True:
                chunk = apply_gain(await self._source.read(self._chunk_bytes), self._gain)
                event = detector.feed(chunk)
                if event is VadEvent.SPEECH_STARTED:
                    deadline = float("inf")  # never cut a person off mid-sentence
                    if on_speech_start is not None:
                        result = on_speech_start()
                        if asyncio.iscoroutine(result):
                            await result
                elif event is VadEvent.UTTERANCE_COMPLETE:
                    return detector.audio()
                elif time.monotonic() > deadline:
                    return None
        finally:
            await self._source.stop()

    async def wait_for_interruption(self, threshold_scale: float = 3.0) -> None:
        """Return when someone speaks loudly (used for barge-in during playback)."""
        detector = UtteranceDetector(self._source.sample_rate, threshold_scale=threshold_scale,
                                     min_speech_ms=300, **{k: v for k, v in self._vad_args.items()
                                                           if k in ("min_rms", "threshold_factor")})
        await self._source.start()
        try:
            while detector.feed(apply_gain(await self._source.read(self._chunk_bytes), self._gain)) \
                    is not VadEvent.SPEECH_STARTED:
                pass
        finally:
            await self._source.stop()
