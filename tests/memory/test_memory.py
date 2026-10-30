import stat
import sys

import pytest

from src.memory.memory_manager import MemoryManager


def mem(**kw):
    return MemoryManager.open(None, **kw)


@pytest.mark.parametrize("text,kind,payload", [
    ("remember that my dog is called Bruno", "remember", "my dog is called Bruno"),
    ("Please remember I hate mushrooms.", "remember", "I hate mushrooms"),
    ("meow meow, remember that I like tea", "remember", "I like tea"),
    ("forget that I like tea", "forget", "I like tea"),
    ("forget everything", "clear", ""),
    ("clear your memory", "clear", ""),
])
def test_parse_command(text, kind, payload):
    cmd = MemoryManager.parse_command(text)
    assert cmd is not None and (cmd.kind, cmd.text) == (kind, payload)


@pytest.mark.parametrize("text", ["I remember when we met", "do you remember me?", "hello", "forgetful me"])
def test_ordinary_chat_is_not_a_command(text):
    assert MemoryManager.parse_command(text) is None


def test_remember_dedupes_and_lists():
    m = mem()
    assert m.remember("likes tea") is True
    assert m.remember("Likes Tea") is False
    assert m.facts() == ["likes tea"]


@pytest.mark.parametrize("secret", [
    "my api key is abc", "password is hunter2", "sk-or-v1-abcdef123456789012",
    "token 0123456789abcdef0123456789abcdef0123",
])
def test_secrets_are_refused(secret):
    m = mem()
    assert m.remember(secret) is False and m.facts() == []


def test_forget_removes_matching_facts():
    m = mem()
    m.remember("likes tea"); m.remember("likes cats")
    assert m.forget("tea") == 1
    assert m.facts() == ["likes cats"]


def test_fact_limit_drops_oldest():
    m = mem(max_facts=3)
    for i in range(5):
        m.remember(f"fact number {i}")
    assert m.facts() == ["fact number 2", "fact number 3", "fact number 4"]


def test_relevant_facts_prefers_overlap_then_fills_with_recent():
    m = mem()
    for fact in ["dog is called Bruno", "likes green tea", "birthday is in May", "works as a nurse",
                 "sister lives in Paris", "hates mushrooms", "plays guitar", "owns a red bike"]:
        m.remember(fact)
    got = m.relevant_facts("what is my dog called", limit=3)
    assert "dog is called Bruno" in got and len(got) == 3


def test_turn_window_is_bounded_and_oldest_first():
    m = mem(max_turns=4)
    for i in range(6):
        m.record_turn("user", f"msg{i}")
    assert [c for _, c, _ in m.recent_turns()] == ["msg2", "msg3", "msg4", "msg5"]


def test_history_persistence_can_be_disabled():
    m = mem(persist_history=False)
    m.record_turn("user", "hello")
    assert m.recent_turns() == []


def test_secret_looking_turns_are_not_stored():
    m = mem()
    m.record_turn("user", "my password is hunter2")
    assert m.recent_turns() == []


def test_clear_erases_everything():
    m = mem()
    m.remember("a"); m.record_turn("user", "b")
    m.clear()
    assert m.facts() == [] and m.recent_turns() == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_database_file_is_owner_only(tmp_path):
    path = tmp_path / "sub" / "m.db"
    MemoryManager.open(path).close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
