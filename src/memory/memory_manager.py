"""Persistent memory: explicit facts plus a short rolling window of recent turns.

Design rules:
- Facts are only stored when the user explicitly asks ("remember that ...").
- Recent turns are a small rolling window (so a restart keeps context), not a
  full transcript, and can be turned off with ``MEMORY_PERSIST_HISTORY=false``.
- Anything that looks like a credential is refused.
- Memory content is never written to logs.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from src.memory.database import Database

_SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"\b(?:api[_\s-]?key|secret|token|password|passcode|pin)\b", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"),  # long opaque strings
]
_WORD = re.compile(r"[a-z0-9']+")
_STOPWORDS = frozenset(
    "a an the and or but is are was were to of in on at for with my me i you your it that this "
    "do does did be been have has had what who how when where why can could would should".split()
)

_CLEAR_ALL = re.compile(
    r"^(?:please\s+)?(?:meow meow[,\s]+)?(?:forget everything|forget all(?: of)? (?:that|it)?|"
    r"clear (?:your |all )?memory|wipe (?:your )?memory|erase (?:your )?memory)\b", re.IGNORECASE)
_REMEMBER = re.compile(
    r"^(?:please\s+)?(?:meow meow[,\s]+)?(?:please\s+)?remember(?: that)?\s+(.+)$", re.IGNORECASE)
_FORGET = re.compile(
    r"^(?:please\s+)?(?:meow meow[,\s]+)?forget(?: that)?\s+(.+)$", re.IGNORECASE)


@dataclass(frozen=True)
class MemoryCommand:
    """An explicit memory instruction found in the user's message."""

    kind: str  # "remember" | "forget" | "clear"
    text: str = ""


class MemoryManager:
    """High-level memory API on top of :class:`Database`."""

    def __init__(self, db: Database, *, max_turns: int = 40, max_facts: int = 200,
                 persist_history: bool = True) -> None:
        self._db = db
        self._max_turns = max_turns
        self._max_facts = max_facts
        self.persist_history = persist_history

    @classmethod
    def open(cls, path: Path | str | None, **kwargs) -> "MemoryManager":
        return cls(Database(path), **kwargs)

    # ------------------------------------------------------------- commands
    @staticmethod
    def parse_command(user_text: str) -> MemoryCommand | None:
        """Detect explicit remember/forget instructions in ``user_text``."""
        text = user_text.strip().rstrip(".!")
        if _CLEAR_ALL.match(text):
            return MemoryCommand("clear")
        if m := _REMEMBER.match(text):
            return MemoryCommand("remember", m.group(1).strip())
        if m := _FORGET.match(text):
            return MemoryCommand("forget", m.group(1).strip())
        return None

    # ---------------------------------------------------------------- facts
    @staticmethod
    def looks_sensitive(text: str) -> bool:
        """True if ``text`` looks like a credential and must not be stored."""
        return any(p.search(text) for p in _SECRET_PATTERNS)

    def remember(self, text: str, source: str = "user") -> bool:
        """Store a fact. Returns False if it was refused or already known."""
        fact = " ".join(text.split())[:300]
        if not fact or self.looks_sensitive(fact):
            return False
        exists = self._db.conn.execute(
            "SELECT 1 FROM facts WHERE lower(content) = lower(?)", (fact,)).fetchone()
        if exists:
            return False
        self._db.conn.execute(
            "INSERT INTO facts (ts, content, source) VALUES (?, ?, ?)", (time.time(), fact, source))
        # Keep the table bounded: drop the oldest beyond the limit.
        self._db.conn.execute(
            "DELETE FROM facts WHERE id NOT IN (SELECT id FROM facts ORDER BY id DESC LIMIT ?)",
            (self._max_facts,))
        self._db.conn.commit()
        return True

    def facts(self) -> list[str]:
        """All remembered facts, oldest first."""
        rows = self._db.conn.execute("SELECT content FROM facts ORDER BY id").fetchall()
        return [r["content"] for r in rows]

    def relevant_facts(self, query: str, limit: int = 6) -> list[str]:
        """Facts most related to ``query``, topped up with the newest facts."""
        rows = self._db.conn.execute("SELECT id, content FROM facts ORDER BY id DESC").fetchall()
        if len(rows) <= limit:
            return [r["content"] for r in reversed(rows)]
        wanted = self._tokens(query)
        scored = [(len(wanted & self._tokens(r["content"])), r["id"], r["content"]) for r in rows]
        matches = sorted((s for s in scored if s[0] > 0), key=lambda s: (-s[0], -s[1]))[:limit]
        chosen = {s[1]: s[2] for s in matches}
        for _, row_id, content in scored:  # newest first
            if len(chosen) >= limit:
                break
            chosen.setdefault(row_id, content)
        return [chosen[k] for k in sorted(chosen)]

    def forget(self, text: str) -> int:
        """Delete facts containing ``text``. Returns how many were removed."""
        like = f"%{text.lower()}%"
        cur = self._db.conn.execute("DELETE FROM facts WHERE lower(content) LIKE ?", (like,))
        self._db.conn.commit()
        return cur.rowcount

    # ---------------------------------------------------------------- turns
    def record_turn(self, role: str, content: str, emotion: str = "NEUTRAL") -> None:
        """Append to the rolling history window (no-op if persistence is off)."""
        if not self.persist_history or self._max_turns <= 0 or self.looks_sensitive(content):
            return
        self._db.conn.execute(
            "INSERT INTO turns (ts, role, content, emotion) VALUES (?, ?, ?, ?)",
            (time.time(), role, content[:1000], emotion))
        self._db.conn.execute(
            "DELETE FROM turns WHERE id NOT IN (SELECT id FROM turns ORDER BY id DESC LIMIT ?)",
            (self._max_turns,))
        self._db.conn.commit()

    def recent_turns(self, limit: int | None = None) -> list[tuple[str, str, str]]:
        """Recent ``(role, content, emotion)`` tuples, oldest first."""
        rows = self._db.conn.execute(
            "SELECT role, content, emotion FROM turns ORDER BY id DESC LIMIT ?",
            (limit or self._max_turns,)).fetchall()
        return [(r["role"], r["content"], r["emotion"]) for r in reversed(rows)]

    # ---------------------------------------------------------------- admin
    def clear(self) -> None:
        """Erase all facts and history."""
        self._db.conn.execute("DELETE FROM facts")
        self._db.conn.execute("DELETE FROM turns")
        self._db.conn.commit()

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS and len(w) > 1}
