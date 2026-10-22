"""SQLite-backed per-number conversation history."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import closing

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_number TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_number ON messages (from_number, id);
"""


class HistoryStore:
    """Stores conversation turns. `created_at` is Unix time in seconds."""

    def __init__(
        self,
        path: str,
        ttl_hours: float = 12.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = path
        self.ttl_seconds = ttl_hours * 3600
        self.clock = clock
        with closing(self._connect()) as conn, conn:
            if path != ":memory:":
                conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def recent(self, from_number: str, max_turns: int) -> list[dict[str, str]]:
        """Last `max_turns` user/assistant pairs, oldest first. Expired history is deleted."""
        with closing(self._connect()) as conn, conn:
            (last,) = conn.execute(
                "SELECT MAX(created_at) FROM messages WHERE from_number = ?",
                (from_number,),
            ).fetchone()
            if last is None:
                return []
            if self.clock() - last > self.ttl_seconds:
                conn.execute("DELETE FROM messages WHERE from_number = ?", (from_number,))
                return []
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE from_number = ? "
                "ORDER BY id DESC LIMIT ?",
                (from_number, max_turns * 2),
            ).fetchall()

        messages = [{"role": role, "content": content} for role, content in reversed(rows)]
        # The Messages API conversation must open with a user turn.
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        return messages

    def append_turn(self, from_number: str, user_content: str, assistant_content: str) -> None:
        now = self.clock()
        with closing(self._connect()) as conn, conn:
            conn.executemany(
                "INSERT INTO messages (from_number, role, content, created_at) VALUES (?, ?, ?, ?)",
                [
                    (from_number, "user", user_content, now),
                    (from_number, "assistant", assistant_content, now),
                ],
            )
            # Opportunistically drop every conversation that has gone stale.
            conn.execute(
                "DELETE FROM messages WHERE from_number IN ("
                " SELECT from_number FROM messages GROUP BY from_number"
                " HAVING MAX(created_at) < ?)",
                (now - self.ttl_seconds,),
            )

    def clear(self, from_number: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM messages WHERE from_number = ?", (from_number,))


class KeyedLocks:
    """One lock per key, so messages from the same number are handled in order."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def get(self, key: str) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = self._locks[key] = threading.Lock()
            return lock
