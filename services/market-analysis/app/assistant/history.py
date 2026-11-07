"""Per-session conversation turns, stored next to the onboarding profile.

Uses the OnboardingStore's SQLite connection and lock, so turns disappear
with the session (30 days) and a deleted session cannot leave turns behind.
Only the user's text, the reply and the topics are kept; no raw statistics.
"""
from __future__ import annotations

import json

from app.onboarding import SESSION_TTL, OnboardingStore

MAX_TURNS = 50


class AssistantHistory:
    def __init__(self, store: OnboardingStore):
        self.store = store
        with store.lock, store.connection:
            store.connection.executescript("""
                CREATE TABLE IF NOT EXISTS assistant_turns (
                    owner TEXT NOT NULL, seq INTEGER NOT NULL, created REAL NOT NULL,
                    client_message_id TEXT, user_text TEXT, response TEXT NOT NULL,
                    PRIMARY KEY (owner, seq)
                );
                CREATE INDEX IF NOT EXISTS assistant_turns_message ON assistant_turns(owner, client_message_id);
            """)

    def _purge(self, now):
        self.store.connection.execute("DELETE FROM assistant_turns WHERE created < ?", (now - SESSION_TTL,))
        self.store.connection.execute(
            "DELETE FROM assistant_turns WHERE owner NOT IN (SELECT owner FROM onboarding_sessions)")

    def find(self, owner: str, client_message_id: str | None):
        if not client_message_id:
            return None
        with self.store.lock:
            row = self.store.connection.execute(
                "SELECT response FROM assistant_turns WHERE owner=? AND client_message_id=?",
                (owner, client_message_id)).fetchone()
            return json.loads(row["response"]) if row else None

    def add(self, owner: str, client_message_id: str | None, user_text: str | None, response: dict):
        with self.store.lock, self.store.connection:
            now = self.store.clock()
            self._purge(now)
            row = self.store.connection.execute(
                "SELECT COALESCE(MAX(seq), 0) AS seq FROM assistant_turns WHERE owner=?", (owner,)).fetchone()
            self.store.connection.execute(
                "INSERT INTO assistant_turns VALUES (?,?,?,?,?,?)",
                (owner, row["seq"] + 1, now, client_message_id, user_text, json.dumps(response, ensure_ascii=False)))
            self.store.connection.execute(
                """DELETE FROM assistant_turns WHERE owner=? AND seq NOT IN
                   (SELECT seq FROM assistant_turns WHERE owner=? ORDER BY seq DESC LIMIT ?)""",
                (owner, owner, MAX_TURNS))

    def recent(self, owner: str, limit: int = 20) -> list[dict]:
        with self.store.lock:
            rows = self.store.connection.execute(
                "SELECT seq, created, user_text, response FROM assistant_turns WHERE owner=? ORDER BY seq DESC LIMIT ?",
                (owner, limit)).fetchall()
        return [{"seq": r["seq"], "created": r["created"], "user_text": r["user_text"],
                 "response": json.loads(r["response"])} for r in reversed(rows)]

    def last(self, owner: str) -> dict | None:
        turns = self.recent(owner, 1)
        return turns[-1]["response"] if turns else None

    def clear(self, owner: str) -> int:
        with self.store.lock, self.store.connection:
            return self.store.connection.execute("DELETE FROM assistant_turns WHERE owner=?", (owner,)).rowcount
