"""Conversation state: history, token budget, memory context and reply parsing.

The LLM client only does HTTP. Everything about *what* to send lives here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.ai.openrouter_client import ChatClient
from src.ai.personality import Emotion, Reply, build_system_prompt, parse_reply
from src.memory.memory_manager import MemoryManager

log = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (about 4 characters per token) without a tokenizer."""
    return len(text) // 4 + 4


@dataclass
class _Turn:
    role: str  # "user" | "assistant"
    content: str  # for assistant turns: the JSON form, to keep the output format sticky


class ConversationManager:
    """Builds prompts, trims history to a budget and parses replies."""

    def __init__(
        self,
        llm: ChatClient,
        memory: MemoryManager | None = None,
        *,
        token_budget: int = 1500,
        max_messages: int = 24,
    ) -> None:
        self._llm = llm
        self._memory = memory
        self._token_budget = token_budget
        self._max_messages = max_messages
        self._history: list[_Turn] = []
        self._restore_history()

    @property
    def history_length(self) -> int:
        return len(self._history)

    async def respond(self, user_text: str) -> Reply:
        """Produce Meow Meow's reply to ``user_text``.

        Explicit memory commands ("remember that...", "forget everything") are
        handled here; everything else goes to the LLM.

        Raises:
            LLMError: when the LLM call fails (history is left unchanged).
        """
        notes: list[str] = []
        if self._memory is not None:
            command = self._memory.parse_command(user_text)
            if command is not None:
                if command.kind == "clear":
                    self.clear()
                    return Reply("Okay, my memory is all wiped. Fresh start, meow meow!", Emotion.NEUTRAL)
                if command.kind == "forget":
                    removed = self._memory.forget(command.text)
                    note = ("You just forgot what they asked." if removed
                            else "You had nothing saved matching that; say so kindly.")
                    notes.append(note)
                elif command.kind == "remember":
                    if self._memory.remember(command.text):
                        notes.append("You just saved what the user asked you to remember. "
                                     "Confirm warmly in one short sentence.")
                    elif self._memory.looks_sensitive(command.text):
                        return Reply("I can't keep secrets like passwords or keys in my memory, "
                                     "that wouldn't be safe. Anything else, meow meow?", Emotion.NEUTRAL)
                    else:
                        notes.append("You already knew that; say so playfully.")

        facts = self._memory.relevant_facts(user_text) if self._memory is not None else []
        messages = [{"role": "system", "content": build_system_prompt(facts, notes)}]
        messages.extend({"role": t.role, "content": t.content} for t in self._trimmed_history())
        messages.append({"role": "user", "content": user_text})

        raw = await self._llm.acomplete(messages)
        reply = parse_reply(raw)

        self._history.append(_Turn("user", user_text))
        self._history.append(_Turn("assistant", reply.as_history_json()))
        self._history = self._history[-self._max_messages * 2:]
        if self._memory is not None:
            self._memory.record_turn("user", user_text)
            self._memory.record_turn("assistant", reply.message, reply.emotion.value)
        return reply

    def clear(self) -> None:
        """Forget the in-memory conversation and wipe persistent memory."""
        self._history.clear()
        if self._memory is not None:
            self._memory.clear()

    def _trimmed_history(self) -> list[_Turn]:
        """Newest turns that fit both the message and token budgets, oldest first."""
        kept: list[_Turn] = []
        used = 0
        for turn in reversed(self._history[-self._max_messages:]):
            cost = estimate_tokens(turn.content)
            if used + cost > self._token_budget:
                break
            kept.append(turn)
            used += cost
        kept.reverse()
        while kept and kept[0].role != "user":  # always start on a user turn
            kept.pop(0)
        return kept

    def _restore_history(self) -> None:
        if self._memory is None or not self._memory.persist_history:
            return
        for role, content, emotion in self._memory.recent_turns(self._max_messages):
            if role == "assistant":
                try:
                    content = Reply(content, Emotion(emotion)).as_history_json()
                except ValueError:
                    content = Reply(content).as_history_json()
            self._history.append(_Turn(role, content))
        log.info("Restored %d earlier messages", len(self._history))
