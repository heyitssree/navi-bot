# navi/db/repos/permissions.py - per-user grants (e.g. permission = 'teach'); used from Phase 6
from __future__ import annotations

import sqlite3

from navi.db.connection import _db_write


def grant(conn: sqlite3.Connection, user_id: int, permission: str, granted_by: int) -> None:
    _db_write(lambda: (
        conn.execute(
            "INSERT OR REPLACE INTO permissions (user_id, permission, granted_by) VALUES (?, ?, ?)",
            [user_id, permission, granted_by],
        ),
        conn.commit(),
    ))


def revoke(conn: sqlite3.Connection, user_id: int, permission: str) -> bool:
    def _write() -> int:
        cur = conn.execute("DELETE FROM permissions WHERE user_id = ? AND permission = ?", [user_id, permission])
        conn.commit()
        return cur.rowcount
    return _db_write(_write) > 0


def has_permission(conn: sqlite3.Connection, user_id: int, permission: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM permissions WHERE user_id = ? AND permission = ?", [user_id, permission]
    ).fetchone() is not None


def list_permission(conn: sqlite3.Connection, permission: str) -> list[int]:
    return [r[0] for r in conn.execute(
        "SELECT user_id FROM permissions WHERE permission = ? ORDER BY user_id", [permission])]
