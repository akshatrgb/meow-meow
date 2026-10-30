import asyncio
import json

import pytest

from src.ai.conversation_manager import ConversationManager, estimate_tokens
from src.ai.openrouter_client import LLMConnectionError
from src.ai.personality import Emotion
from src.memory.memory_manager import MemoryManager


class ScriptedLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    async def acomplete(self, messages):
        self.calls.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def reply(msg="ok", emotion="HAPPY"):
    return json.dumps({"message": msg, "emotion": emotion})


def run(coro):
    return asyncio.run(coro)


def test_reply_is_parsed_and_history_is_sent_next_turn():
    llm = ScriptedLLM(reply("first"), reply("second"))
    cm = ConversationManager(llm)
    r = run(cm.respond("hello"))
    assert (r.message, r.emotion) == ("first", Emotion.HAPPY)
    run(cm.respond("again"))
    roles = [m["role"] for m in llm.calls[1]]
    assert roles == ["system", "user", "assistant", "user"]
    assert json.loads(llm.calls[1][2]["content"])["message"] == "first"


def test_failed_call_leaves_history_unchanged():
    llm = ScriptedLLM(LLMConnectionError("down"), reply())
    cm = ConversationManager(llm)
    with pytest.raises(LLMConnectionError):
        run(cm.respond("hello"))
    assert cm.history_length == 0
    run(cm.respond("hello again"))
    assert cm.history_length == 2


def test_history_respects_token_budget_and_starts_on_user_turn():
    llm = ScriptedLLM(*[reply("x" * 200) for _ in range(6)])
    cm = ConversationManager(llm, token_budget=estimate_tokens("y" * 300) * 2 + 10)
    for _ in range(5):
        run(cm.respond("y" * 300))
    sent = llm.calls[-1]
    assert len(sent) < 11  # trimmed
    assert sent[1]["role"] == "user"


def test_history_respects_message_limit():
    llm = ScriptedLLM(*[reply() for _ in range(10)])
    cm = ConversationManager(llm, max_messages=4)
    for i in range(10):
        run(cm.respond(f"m{i}"))
    assert cm.history_length <= 8


def test_remember_command_saves_fact_and_injects_it():
    memory = MemoryManager.open(None)
    llm = ScriptedLLM(reply("Got it!"), reply("Blue!"))
    cm = ConversationManager(llm, memory)
    run(cm.respond("remember that my favourite colour is blue"))
    assert memory.facts() == ["my favourite colour is blue"]
    assert "saved what the user asked" in llm.calls[0][0]["content"]
    run(cm.respond("what colour do I like?"))
    assert "my favourite colour is blue" in llm.calls[1][0]["content"]


def test_secret_is_refused_without_calling_the_llm():
    memory = MemoryManager.open(None)
    llm = ScriptedLLM()
    cm = ConversationManager(llm, memory)
    r = run(cm.respond("remember that my password is hunter2"))
    assert memory.facts() == [] and llm.calls == []
    assert "can't keep secrets" in r.message


def test_forget_everything_wipes_memory_without_calling_the_llm():
    memory = MemoryManager.open(None)
    memory.remember("likes tea")
    llm = ScriptedLLM(reply())
    cm = ConversationManager(llm, memory)
    run(cm.respond("hi"))
    r = run(cm.respond("forget everything"))
    assert memory.facts() == [] and memory.recent_turns() == [] and cm.history_length == 0
    assert "wiped" in r.message and len(llm.calls) == 1


def test_history_survives_a_restart(tmp_path):
    path = tmp_path / "m.db"
    m1 = MemoryManager.open(path)
    run(ConversationManager(ScriptedLLM(reply("hello friend", "LOVE")), m1).respond("hi there"))
    m1.close()

    llm = ScriptedLLM(reply())
    cm2 = ConversationManager(llm, MemoryManager.open(path))
    assert cm2.history_length == 2
    run(cm2.respond("back again"))
    assert json.loads(llm.calls[0][2]["content"]) == {"message": "hello friend", "emotion": "LOVE"}
