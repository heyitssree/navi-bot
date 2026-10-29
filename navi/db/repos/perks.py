# navi/db/repos/perks.py - moved from schema.py (no behaviour change)
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime

from navi.db.connection import _db_write

logger = logging.getLogger("navi.db.perks")


def has_active_perk(
    conn: sqlite3.Connection,
    user_id: int,
    perk_type: str,
) -> bool:
    """Return True if the user has a non-expired perk of the given type."""
    row = conn.execute(
        "SELECT 1 FROM user_perks WHERE user_id = ? AND perk_type = ? AND expires_at > CURRENT_TIMESTAMP",
        [user_id, perk_type],
    ).fetchone()
    return row is not None


def grant_perk(
    conn: sqlite3.Connection,
    user_id: int,
    perk_type: str,
    duration_hours: float = 24,
) -> None:
    """Grant a timed perk to a user, extending if they already have one.

    duration_hours may be fractional (e.g. 0.5 for 30 minutes).
    """
    duration_seconds = int(duration_hours * 3600)

    def _write() -> None:
        conn.execute(
            """
            INSERT INTO user_perks (user_id, perk_type, expires_at)
            VALUES (?, ?, datetime('now', '+' || ? || ' seconds'))
            ON CONFLICT (user_id, perk_type) DO UPDATE SET
                expires_at = CASE
                    WHEN user_perks.expires_at > excluded.expires_at
                    THEN user_perks.expires_at
                    ELSE excluded.expires_at
                END
            """,
            [user_id, perk_type, duration_seconds],
        )
        conn.commit()
    _db_write(_write)


def get_perk_expiry(
    conn: sqlite3.Connection,
    user_id: int,
    perk_type: str,
) -> datetime | None:
    """Return the expiry datetime of a perk, or None if not active."""
    row = conn.execute(
        "SELECT expires_at FROM user_perks WHERE user_id = ? AND perk_type = ? AND expires_at > CURRENT_TIMESTAMP",
        [user_id, perk_type],
    ).fetchone()
    if not row:
        return None
    val = row[0]
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            return None
    return None


def clear_perk(
    conn: sqlite3.Connection,
    user_id: int,
    perk_type: str,
) -> bool:
    """Delete a perk record (active or expired) for a user. Returns True if a row was removed."""
    def _write() -> int:
        cur = conn.execute(
            "DELETE FROM user_perks WHERE user_id = ? AND perk_type = ?",
            [user_id, perk_type],
        )
        conn.commit()
        return cur.rowcount
    return _db_write(_write) > 0
