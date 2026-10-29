# navi/db/repos/users.py - moved from schema.py (no behaviour change)
from __future__ import annotations

import logging
import random
import sqlite3
from datetime import datetime

from navi.db.connection import _db_write

logger = logging.getLogger("navi.db.users")


def get_user_profile(
    conn: sqlite3.Connection,
    user_id: int,
) -> dict | None:
    """Return user profile dict or None if user doesn't exist.

    boli_points = native (internal) points only.
    external_boli = sum of all external partner awards (can be negative).
    total_boli_points = boli_points + external_boli — use this for display.
    """
    row = conn.execute(
        """
        SELECT u.user_id, u.username, u.rashi, u.boli_points, u.experience,
               u.last_seen, u.prediction_count, u.daily_action_count,
               u.last_action_date, u.extra_actions,
               COALESCE((
                   SELECT SUM(e.points) FROM external_boli_points e WHERE e.user_id = u.user_id
               ), 0)
        FROM user_stats u WHERE u.user_id = ?
        """,
        [user_id],
    ).fetchone()
    if not row:
        return None
    native = row[3]
    external = row[10]
    return {
        "user_id": row[0],
        "username": row[1],
        "rashi": row[2],
        "boli_points": native,
        "external_boli": external,
        "total_boli_points": native + external,
        "experience": row[4],
        "last_seen": row[5],
        "prediction_count": row[6],
        "daily_action_count": row[7],
        "last_action_date": row[8],
        "extra_actions": row[9],
    }


def upsert_user(
    conn: sqlite3.Connection,
    user_id: int,
    username: str,
    rashi: str | None = None,
) -> None:
    """Insert or update a user record."""
    existing = get_user_profile(conn, user_id)

    def _write() -> None:
        if existing is None:
            conn.execute(
                """
                INSERT INTO user_stats (user_id, username, rashi, boli_points, last_seen, prediction_count)
                VALUES (?, ?, ?, 0, CURRENT_TIMESTAMP, 0)
                """,
                [user_id, username, rashi],
            )
        elif rashi:
            conn.execute(
                "UPDATE user_stats SET username=?, rashi=?, last_seen=CURRENT_TIMESTAMP WHERE user_id=?",
                [username, rashi, user_id],
            )
        else:
            conn.execute(
                "UPDATE user_stats SET username=?, last_seen=CURRENT_TIMESTAMP WHERE user_id=?",
                [username, user_id],
            )
        conn.commit()
    _db_write(_write)


def bulk_update_last_seen(conn: sqlite3.Connection, seen: dict[int, str]) -> int:
    """Write many last_seen timestamps (UTC 'YYYY-MM-DD HH:MM:SS') in one executemany. Returns rows given."""
    if not seen:
        return 0
    rows = [(ts, uid) for uid, ts in seen.items()]
    _db_write(lambda: (
        conn.executemany("UPDATE user_stats SET last_seen = ? WHERE user_id = ?", rows),
        conn.commit(),
    ))
    return len(rows)


def get_last_seen(conn: sqlite3.Connection, user_id: int) -> str | None:
    """Return the stored last_seen text for a user, or None when the user has no record."""
    row = conn.execute("SELECT last_seen FROM user_stats WHERE user_id = ?", [user_id]).fetchone()
    if not row or not row[0]:
        return None
    val = row[0]  # PARSE_DECLTYPES turns TIMESTAMP columns into datetime objects
    return val.strftime("%Y-%m-%d %H:%M:%S") if isinstance(val, datetime) else str(val)


def get_leaderboard(
    conn: sqlite3.Connection,
    limit: int = 10,
    offset: int = 0,
) -> list[dict]:
    """Return users sorted by total Boli Points (native + external), with pagination."""
    rows = conn.execute(
        "SELECT username, rashi, total_boli_points, prediction_count, experience "
        "FROM boli_totals_view ORDER BY total_boli_points DESC LIMIT ? OFFSET ?",
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
    """Return total number of users with a stats record."""
    row = conn.execute("SELECT COUNT(*) FROM user_stats").fetchone()
    return row[0] if row else 0


def get_user_strikes(conn: sqlite3.Connection, user_id: int) -> int:
    """Return the current strike count for a user (0 if not found)."""
    row = conn.execute(
        "SELECT strikes FROM user_stats WHERE user_id = ?", [user_id]
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def increment_user_strikes(conn: sqlite3.Connection, user_id: int) -> int:
    """Increment strikes by 1 and return the new count."""
    _db_write(lambda: (
        conn.execute(
            "UPDATE user_stats SET strikes = strikes + 1 WHERE user_id = ?", [user_id]
        ),
        conn.commit(),
    ))
    return get_user_strikes(conn, user_id)


def reset_user_strikes(conn: sqlite3.Connection, user_id: int) -> None:
    """Reset a user's strikes to 0."""
    _db_write(lambda: (
        conn.execute("UPDATE user_stats SET strikes = 0 WHERE user_id = ?", [user_id]),
        conn.commit(),
    ))


def reset_all_strikes(conn: sqlite3.Connection) -> int:
    """Reset strikes to 0 for every user. Returns the number of rows affected."""
    count = conn.execute("SELECT COUNT(*) FROM user_stats WHERE strikes > 0").fetchone()[0]
    _db_write(lambda: (
        conn.execute("UPDATE user_stats SET strikes = 0"),
        conn.commit(),
    ))
    return count


def get_random_recent_user(
    conn: sqlite3.Connection,
    exclude_id: int,
) -> dict | None:
    """Return a random user who used /navi in the last 24 hours, excluding exclude_id.

    Returns dict with keys user_id and username, or None if no candidates.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT u.user_id, u.username
        FROM user_stats u
        INNER JOIN user_prediction_history h ON h.user_id = u.user_id
        WHERE u.user_id != ?
          AND h.timestamp >= datetime('now', '-1 day')
        """,
        [exclude_id],
    ).fetchall()
    if not rows:
        return None
    row = random.choice(rows)
    return {"user_id": row[0], "username": row[1]}


def get_active_user_ids_previous_day(conn: sqlite3.Connection) -> list[int]:
    """Return user_ids active during the previous IST day window (7am–6:59am).

    'Active' means last_seen fell within that window.
    Used for the daily lucky draw at 7am IST.
    """
    # Previous day window in UTC:
    # 7:00am IST = 1:30am UTC, so window = yesterday 01:30:00 UTC → today 01:29:59 UTC
    rows = conn.execute(
        """
        SELECT user_id FROM user_stats
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
    """Return up to n users sorted by boli_points DESC, filtered to the given user_id list.

    Returns list of dicts with user_id, username, boli_points.
    """
    if not user_ids:
        return []
    placeholders = ",".join("?" * len(user_ids))
    rows = conn.execute(
        f"""
        SELECT user_id, username, boli_points FROM user_stats
        WHERE user_id IN ({placeholders})
        ORDER BY boli_points DESC
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
        conn.execute(
            "UPDATE user_stats SET prediction_count = prediction_count + 1 WHERE user_id = ?",
            [user_id],
        ),
        conn.commit(),
    ))
