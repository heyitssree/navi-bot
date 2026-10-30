# navi/db/repos/users.py - users table (v2). Balances are written only by navi.services.points.
from __future__ import annotations

import logging
import random
import sqlite3

from navi.db.connection import _db_write

logger = logging.getLogger("navi.db.users")


def get_user_profile(
    conn: sqlite3.Connection,
    user_id: int,
) -> dict | None:
    """Return user profile dict or None if user doesn't exist.

    boli_points = native pool; external_boli = partner pool (can be negative);
    total_boli_points = both - use this for display.
    """
    row = conn.execute(
        """
        SELECT user_id, display_name, rashi, boli_points, partner_points, experience,
               last_seen, prediction_count, extra_actions
        FROM users WHERE user_id = ?
        """,
        [user_id],
    ).fetchone()
    if not row:
        return None
    return {
        "user_id": row[0],
        "username": row[1],
        "rashi": row[2],
        "boli_points": row[3],
        "external_boli": row[4],
        "total_boli_points": row[3] + row[4],
        "experience": row[5],
        "last_seen": row[6],
        "prediction_count": row[7],
        "extra_actions": row[8],
    }


def upsert_user(
    conn: sqlite3.Connection,
    user_id: int,
    username: str,
    rashi: str | None = None,
) -> None:
    """Insert or update a user record."""
    def _write() -> None:
        conn.execute(
            """
            INSERT INTO users (user_id, display_name, rashi) VALUES (?, ?, ?)
            ON CONFLICT (user_id) DO UPDATE SET
                display_name = excluded.display_name,
                rashi = COALESCE(excluded.rashi, users.rashi),
                last_seen = CURRENT_TIMESTAMP
            """,
            [user_id, username, rashi],
        )
        conn.commit()
    _db_write(_write)


def bulk_update_last_seen(conn: sqlite3.Connection, seen: dict[int, str]) -> int:
    """Write many last_seen timestamps (UTC 'YYYY-MM-DD HH:MM:SS') in one executemany. Returns rows given."""
    if not seen:
        return 0
    rows = [(ts, uid) for uid, ts in seen.items()]
    _db_write(lambda: (
        conn.executemany("UPDATE users SET last_seen = ? WHERE user_id = ?", rows),
        conn.commit(),
    ))
    return len(rows)


def get_last_seen(conn: sqlite3.Connection, user_id: int) -> str | None:
    """Return the stored last_seen text for a user, or None when the user has no record."""
    row = conn.execute("SELECT last_seen FROM users WHERE user_id = ?", [user_id]).fetchone()
    return str(row[0]) if row and row[0] else None


def get_leaderboard(
    conn: sqlite3.Connection,
    limit: int = 10,
    offset: int = 0,
) -> list[dict]:
    """Return users sorted by total Boli Points (native + partner), with pagination."""
    rows = conn.execute(
        "SELECT display_name, rashi, boli_points + partner_points AS total, prediction_count, experience "
        "FROM users ORDER BY total DESC, user_id ASC LIMIT ? OFFSET ?",
        [limit, offset],
    ).fetchall()
    return [
        {
            "username": r[0],
            "rashi": r[1],
            "boli_points": r[2],   # total, for display
            "prediction_count": r[3],
            "experience": r[4],
        }
        for r in rows
    ]


def count_leaderboard_entries(conn: sqlite3.Connection) -> int:
    """Return total number of users."""
    row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
    return row[0] if row else 0


def get_user_strikes(conn: sqlite3.Connection, user_id: int) -> int:
    """Return the current strike count for a user (0 if not found)."""
    row = conn.execute("SELECT strikes FROM users WHERE user_id = ?", [user_id]).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def increment_user_strikes(conn: sqlite3.Connection, user_id: int) -> int:
    """Increment strikes by 1 and return the new count."""
    _db_write(lambda: (
        conn.execute("UPDATE users SET strikes = strikes + 1 WHERE user_id = ?", [user_id]),
        conn.commit(),
    ))
    return get_user_strikes(conn, user_id)


def reset_user_strikes(conn: sqlite3.Connection, user_id: int) -> None:
    """Reset a user's strikes to 0."""
    _db_write(lambda: (
        conn.execute("UPDATE users SET strikes = 0 WHERE user_id = ?", [user_id]),
        conn.commit(),
    ))


def reset_all_strikes(conn: sqlite3.Connection) -> int:
    """Reset strikes to 0 for every user. Returns the number of rows affected."""
    count = conn.execute("SELECT COUNT(*) FROM users WHERE strikes > 0").fetchone()[0]
    _db_write(lambda: (
        conn.execute("UPDATE users SET strikes = 0"),
        conn.commit(),
    ))
    return count


def get_random_recent_user(
    conn: sqlite3.Connection,
    exclude_id: int,
    exclude_ids: frozenset[int] | set[int] = frozenset(),
) -> dict | None:
    """Return a random user who used /navi in the last 24 hours, excluding exclude_id.

    Returns dict with keys user_id and username, or None if no candidates.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT u.user_id, u.display_name
        FROM users u
        INNER JOIN prediction_history h ON h.user_id = u.user_id
        WHERE u.user_id != ?
          AND h.created_at >= datetime('now', '-1 day')
        """,
        [exclude_id],
    ).fetchall()
    rows = [r for r in rows if r[0] not in exclude_ids]     # e.g. users who opted out of Navi
    if not rows:
        return None
    row = random.choice(rows)
    return {"user_id": row[0], "username": row[1]}


def get_active_user_ids_previous_day(conn: sqlite3.Connection) -> list[int]:
    """Return user_ids active during the previous IST day window (7am-6:59am).

    'Active' means last_seen fell within that window. Used for the daily lucky draw at 7am IST.
    """
    # 7:00am IST = 1:30am UTC, so window = yesterday 01:30:00 UTC -> today 01:29:59 UTC
    rows = conn.execute(
        """
        SELECT user_id FROM users
        WHERE last_seen >= datetime('now', '-1 day', 'start of day', '+1 hours', '+30 minutes')
          AND last_seen <  datetime('now', 'start of day', '+1 hours', '+30 minutes')
        """,
    ).fetchall()
    return [r[0] for r in rows]


def get_top_n_from_user_ids(
    conn: sqlite3.Connection,
    user_ids: list[int],
    n: int = 10,
) -> list[dict]:
    """Return up to n users sorted by boli_points DESC, filtered to the given user_id list."""
    if not user_ids:
        return []
    placeholders = ",".join("?" * len(user_ids))
    rows = conn.execute(
        f"""
        SELECT user_id, display_name, boli_points FROM users
        WHERE user_id IN ({placeholders})
        ORDER BY boli_points DESC, user_id ASC
        LIMIT ?
        """,
        [*user_ids, n],
    ).fetchall()
    return [{"user_id": r[0], "username": r[1], "boli_points": r[2]} for r in rows]


def increment_prediction_count(
    conn: sqlite3.Connection,
    user_id: int,
) -> None:
    _db_write(lambda: (
        conn.execute("UPDATE users SET prediction_count = prediction_count + 1 WHERE user_id = ?", [user_id]),
        conn.commit(),
    ))
