"""Small, dependency-free PCM/WAV helpers.

(The stdlib ``audioop`` module was removed in Python 3.13, so these use ``array``.)
"""

from __future__ import annotations

import io
import math
import struct
import sys
import wave
from array import array


def _samples(pcm: bytes) -> array:
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


def rms(pcm: bytes) -> float:
    """Root-mean-square level of signed 16-bit mono PCM."""
    samples = _samples(pcm)
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def apply_gain(pcm: bytes, gain: float) -> bytes:
    """Multiply 16-bit PCM by ``gain`` with clipping."""
    if gain == 1.0:
        return pcm
    samples = _samples(pcm)
    for i, s in enumerate(samples):
        v = int(s * gain)
        samples[i] = 32767 if v > 32767 else -32768 if v < -32768 else v
    if sys.byteorder == "big":
        samples.byteswap()
    return samples.tobytes()


def pcm_to_wav(pcm: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """Wrap raw signed 16-bit PCM in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def wav_duration(wav_bytes: bytes) -> float:
    """Duration in seconds of a WAV file held in memory; 0.0 if unreadable."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except (wave.Error, EOFError):
        return 0.0


def make_tone_wav(duration_s: float, freq: float = 440.0, sample_rate: int = 16000,
                  volume: float = 0.15) -> bytes:
    """A soft sine tone, used by the mock TTS so playback paths can be tested."""
    count = int(duration_s * sample_rate)
    amp = int(32767 * volume)
    fade = max(1, int(0.02 * sample_rate))
    frames = bytearray()
    for i in range(count):
        envelope = min(1.0, i / fade, (count - i) / fade)
        frames += struct.pack("<h", int(amp * envelope * math.sin(2 * math.pi * freq * i / sample_rate)))
    return pcm_to_wav(bytes(frames), sample_rate)
