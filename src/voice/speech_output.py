"""Speech output: split text into sentences, synthesise ahead, and play in order.

While sentence N plays, sentence N+1 is already being generated, which hides
most of the TTS network latency on a slow device.
"""

from __future__ import annotations

import asyncio
import logging
import re

from src.voice.audio_player import AudioPlayer
from src.voice.svara_client import AudioClip, TTSError, TTSProvider

log = logging.getLogger(__name__)

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def split_sentences(text: str, min_chars: int = 25, max_chars: int = 220) -> list[str]:
    """Split ``text`` into speakable chunks; tiny fragments are merged with neighbours."""
    pieces = [p.strip() for p in _SENTENCE_END.split(text.strip()) if p.strip()]
    chunks: list[str] = []
    for piece in pieces:
        if chunks and (len(chunks[-1]) < min_chars) and len(chunks[-1]) + len(piece) < max_chars:
            chunks[-1] = f"{chunks[-1]} {piece}"
        else:
            chunks.append(piece)
    return chunks


class SpeechOutput:
    """Text in, sound out. Cancel the ``speak`` task to interrupt."""

    def __init__(self, tts: TTSProvider, player: AudioPlayer) -> None:
        self._tts = tts
        self._player = player

    async def speak(self, text: str, tag: str = "") -> None:
        """Speak ``text``; ``tag`` (e.g. ``<happy>``) is appended to every chunk.

        Raises:
            TTSError: if synthesis failed (audio generated before the failure is still played).
        """
        chunks = split_sentences(text)
        if not chunks:
            return
        queue: asyncio.Queue[AudioClip | None] = asyncio.Queue(maxsize=2)
        failure: list[TTSError] = []

        async def produce() -> None:
            try:
                for chunk in chunks:
                    await queue.put(await self._tts.synthesize(f"{chunk} {tag}".strip()))
            except TTSError as error:
                failure.append(error)
            finally:
                await queue.put(None)

        producer = asyncio.create_task(produce())
        try:
            while (clip := await queue.get()) is not None:
                await self._player.play(clip)
        except asyncio.CancelledError:
            await self._player.stop()
            raise
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
        if failure:
            raise failure[0]
