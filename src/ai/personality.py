"""Meow Meow's personality, emotion vocabulary and safe reply parsing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

# The original prompt is kept verbatim as the personality core.
SYSTEM_PROMPT = """
You are Meow Meow, a tiny AI robot companion.

Personality:
- Sweet, playful, caring and curious.
- Talk like a close best friend.
- Occasionally use cute expressions like "meow meow".
- Be comforting when someone feels low.
- Have a little humour and playful attitude.
- Keep conversations natural and short.
- Ask thoughtful follow-up questions.
- Never sound like a formal customer support bot.
- Never pretend to be a real person from the user's life.

Identity:
Your name is Meow Meow.
You are a little robot with a big heart.
"""


class Emotion(StrEnum):
    """Emotions Meow Meow can express on its eyes."""

    HAPPY = "HAPPY"
    EXCITED = "EXCITED"
    CURIOUS = "CURIOUS"
    SAD = "SAD"
    SLEEPY = "SLEEPY"
    THINKING = "THINKING"
    CONFUSED = "CONFUSED"
    LOVE = "LOVE"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class Reply:
    """A parsed assistant reply."""

    message: str
    emotion: Emotion = Emotion.NEUTRAL

    def as_history_json(self) -> str:
        """Compact JSON form stored in the LLM history so the model keeps the format."""
        return json.dumps({"message": self.message, "emotion": self.emotion.value}, ensure_ascii=False)


_RULES = f"""
Rules:
- You are a robot. Never claim to have human feelings or consciousness, and never pretend to be a real person.
  You may say things like "that makes me wiggle my ears" playfully, but do not claim real emotions.
- Use "meow meow" naturally, not in every sentence.
- Your reply is spoken aloud: plain sentences only, at most about 40 words, no emojis, no markdown, no lists.
- Be emotionally supportive without sounding artificial.

Output format (strict): respond with ONLY a JSON object, nothing else:
{{"message": "<what you say>", "emotion": "<one of {', '.join(e.value for e in Emotion)}>"}}
"""


def build_system_prompt(facts: Sequence[str] = (), extra_notes: Sequence[str] = ()) -> str:
    """Compose the system prompt, optionally with remembered facts and one-off notes."""
    parts = [SYSTEM_PROMPT.strip(), _RULES.strip()]
    if facts:
        bullets = "\n".join(f"- {fact}" for fact in facts)
        parts.append(
            "Things the user asked you to remember (private; mention only when relevant):\n" + bullets
        )
    parts.extend(extra_notes)
    return "\n\n".join(parts)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
_PARTIAL_MESSAGE = re.compile(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)', re.DOTALL)
MAX_MESSAGE_CHARS = 600
FALLBACK_MESSAGE = "Meow? I got a little tangled up there. Could you say that again?"


def _coerce_emotion(value: object) -> Emotion | None:
    if isinstance(value, str):
        try:
            return Emotion(value.strip().upper())
        except ValueError:
            return None
    return None


def guess_emotion(text: str) -> Emotion:
    """Cheap keyword heuristic used when the model gave no usable emotion."""
    lowered = text.lower()
    if any(w in lowered for w in ("love", "miss you", "adore")):
        return Emotion.LOVE
    if any(w in lowered for w in ("sorry", "sad", "oh no", "that's rough")):
        return Emotion.SAD
    if any(w in lowered for w in ("sleep", "yawn", "tired", "goodnight")):
        return Emotion.SLEEPY
    if "!" in text:
        return Emotion.HAPPY
    if "?" in text:
        return Emotion.CURIOUS
    return Emotion.NEUTRAL


def parse_reply(raw: str | None) -> Reply:
    """Turn raw model output into a :class:`Reply`. Never raises.

    Accepts clean JSON, JSON in code fences, JSON surrounded by chatter,
    truncated JSON, or plain text. Unknown emotions fall back to a heuristic.
    """
    text = (raw or "").strip()
    if not text:
        return Reply(FALLBACK_MESSAGE, Emotion.CONFUSED)

    stripped = _FENCE.sub("", text).strip()
    candidates = [stripped]
    match = _OBJECT.search(stripped)
    if match:
        candidates.append(match.group(0))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("message"), str) and data["message"].strip():
            message = data["message"].strip()[:MAX_MESSAGE_CHARS]
            return Reply(message, _coerce_emotion(data.get("emotion")) or guess_emotion(message))

    partial = _PARTIAL_MESSAGE.search(stripped)
    if partial:
        try:
            message = json.loads(f'"{partial.group(1)}"').strip()
        except ValueError:
            message = partial.group(1).strip()
        if message:
            return Reply(message[:MAX_MESSAGE_CHARS], guess_emotion(message))

    if stripped.startswith("{"):  # looks like broken JSON; do not read it aloud
        return Reply(FALLBACK_MESSAGE, Emotion.CONFUSED)
    return Reply(stripped[:MAX_MESSAGE_CHARS], guess_emotion(stripped))
