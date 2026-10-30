"""SQLite storage for Meow Meow's memory."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL NOT NULL,
    content TEXT NOT NULL,
    source  TEXT NOT NULL DEFAULT 'user'
);
CREATE TABLE IF NOT EXISTS turns (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL NOT NULL,
    role    TEXT NOT NULL,
    content TEXT NOT NULL,
    emotion TEXT NOT NULL DEFAULT 'NEUTRAL'
);
"""


class Database:
    """Opens (and creates) the memory database with owner-only permissions.

    ``path=None`` gives an in-memory database, used by tests and mock runs.
    """

    def __init__(self, path: Path | str | None) -> None:
        if path is None:
            target = ":memory:"
        else:
            file = Path(path)
            file.parent.mkdir(parents=True, exist_ok=True)
            target = str(file)
        self.conn = sqlite3.connect(target)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA synchronous=NORMAL")  # fewer SD-card writes
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        if path is not None:
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass  # e.g. unsupported filesystem; not fatal

    def close(self) -> None:
        self.conn.close()
