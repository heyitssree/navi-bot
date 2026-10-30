# navi/db/repos/privacy.py - privacy_state lives in its OWN file (data/privacy.db) and is never purged.
# Only user_id, status and changed_at are stored. Phase 6 builds /privacy on top of this.
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
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    return conn


def set_status(conn: sqlite3.Connection, user_id: int, status: str) -> None:
    conn.execute(
        "INSERT INTO privacy_state (user_id, status, changed_at) VALUES (?, ?, datetime('now'))"
        " ON CONFLICT (user_id) DO UPDATE SET status = excluded.status, changed_at = excluded.changed_at",
        [user_id, status],
    )
    conn.commit()


def is_opted_out(conn: sqlite3.Connection, user_id: int) -> bool:
    row = conn.execute("SELECT status FROM privacy_state WHERE user_id = ?", [user_id]).fetchone()
    return bool(row and row[0] == "out")
