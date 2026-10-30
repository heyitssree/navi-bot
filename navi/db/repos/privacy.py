# navi/db/repos/privacy.py - privacy_state lives in its OWN file (data/privacy.db) and is never purged.
# Only user_id, status and changed_at are stored. navi.services.privacy builds /privacy on top of this.
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS privacy_state (
  user_id INTEGER PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('out', 'in')),
  changed_at TEXT NOT NULL);
"""


def connect_privacy(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    return conn


def set_status(conn: sqlite3.Connection, user_id: int, status: str, changed_at: str | None = None) -> None:
    conn.execute(
        "INSERT INTO privacy_state (user_id, status, changed_at) VALUES (?, ?, COALESCE(?, datetime('now')))"
        " ON CONFLICT (user_id) DO UPDATE SET status = excluded.status, changed_at = excluded.changed_at",
        [user_id, status, changed_at],
    )
    conn.commit()


def is_opted_out(conn: sqlite3.Connection, user_id: int) -> bool:
    row = conn.execute("SELECT status FROM privacy_state WHERE user_id = ?", [user_id]).fetchone()
    return bool(row and row[0] == "out")


def get_state(conn: sqlite3.Connection, user_id: int) -> tuple[str, str] | None:
    """(status, changed_at) or None if the user never used /privacy."""
    row = conn.execute("SELECT status, changed_at FROM privacy_state WHERE user_id = ?", [user_id]).fetchone()
    return (row[0], row[1]) if row else None


def opted_out_ids(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT user_id FROM privacy_state WHERE status = 'out'")}
