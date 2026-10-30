# navi/db/repos/counters.py - daily_counters (one row per user, IST day and counter) + purchased extra actions
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone

from navi.db.connection import _db_write

logger = logging.getLogger("navi.db.counters")

_IST = timezone(timedelta(hours=5, minutes=30))

# counter names
COSMIC_ACTION = "cosmic_action"
REFILL = "refill"


def _today_ist() -> date:
    """Return the current date in IST (UTC+5:30), used for daily quota resets."""
    return datetime.now(_IST).date()


def _get(conn: sqlite3.Connection, user_id: int, counter: str) -> int:
    row = conn.execute(
        "SELECT value FROM daily_counters WHERE user_id = ? AND day = ? AND counter = ?",
        [user_id, _today_ist().isoformat(), counter],
    ).fetchone()
    return int(row[0]) if row else 0


def _increment(conn: sqlite3.Connection, user_id: int, counter: str) -> int:
    day = _today_ist().isoformat()
    _db_write(lambda: (
        conn.execute(
            """
            INSERT INTO daily_counters (user_id, day, counter, value) VALUES (?, ?, ?, 1)
            ON CONFLICT (user_id, day, counter) DO UPDATE SET value = value + 1
            """,
            [user_id, day, counter],
        ),
        conn.commit(),
    ))
    return _get(conn, user_id, counter)


def _reset(conn: sqlite3.Connection, user_id: int, counter_pattern: str) -> None:
    _db_write(lambda: (
        conn.execute(
            "DELETE FROM daily_counters WHERE user_id = ? AND day = ? AND counter LIKE ?",
            [user_id, _today_ist().isoformat(), counter_pattern],
        ),
        conn.commit(),
    ))


def get_daily_action_count(conn: sqlite3.Connection, user_id: int) -> int:
    """Return today's combined curse/bless action count (0 on a new day)."""
    return _get(conn, user_id, COSMIC_ACTION)


def increment_daily_action_count(conn: sqlite3.Connection, user_id: int) -> int:
    """Increment today's cosmic action count. Returns new count."""
    return _increment(conn, user_id, COSMIC_ACTION)


def get_extra_actions(conn: sqlite3.Connection, user_id: int) -> int:
    """Return the number of purchased extra actions remaining for a user."""
    row = conn.execute("SELECT extra_actions FROM users WHERE user_id = ?", [user_id]).fetchone()
    return int(row[0]) if row and row[0] else 0


def decrement_extra_actions(conn: sqlite3.Connection, user_id: int) -> None:
    """Consume one extra action token, flooring at 0."""
    _db_write(lambda: (
        conn.execute(
            "UPDATE users SET extra_actions = CASE WHEN extra_actions > 0 THEN extra_actions - 1 ELSE 0 END WHERE user_id = ?",
            [user_id],
        ),
        conn.commit(),
    ))


def add_extra_actions(conn: sqlite3.Connection, user_id: int, amount: int) -> None:
    """Add purchased extra action tokens to a user's balance."""
    _db_write(lambda: (
        conn.execute("UPDATE users SET extra_actions = extra_actions + ? WHERE user_id = ?", [amount, user_id]),
        conn.commit(),
    ))


def get_daily_refill_count(conn: sqlite3.Connection, user_id: int) -> int:
    """Return how many action refills the user has bought today (IST)."""
    return _get(conn, user_id, REFILL)


def increment_daily_refill_count(conn: sqlite3.Connection, user_id: int) -> int:
    """Increment today's refill count. Returns new count."""
    return _increment(conn, user_id, REFILL)


_GAME_DAILY_LIMIT = 30


def get_game_daily_count(conn: sqlite3.Connection, user_id: int, game_name: str) -> int:
    """Return today's play count for the given game (IST)."""
    return _get(conn, user_id, f"game:{game_name}")


def get_total_game_daily_count(conn: sqlite3.Connection, user_id: int) -> int:
    """Return total plays across ALL games today (IST). Used for the combined 30/day limit."""
    row = conn.execute(
        "SELECT COALESCE(SUM(value), 0) FROM daily_counters WHERE user_id = ? AND day = ? AND counter LIKE 'game:%'",
        [user_id, _today_ist().isoformat()],
    ).fetchone()
    return int(row[0]) if row else 0


def increment_game_daily_count(conn: sqlite3.Connection, user_id: int, game_name: str) -> int:
    """Increment today's play count for the given game. Returns the new count."""
    return _increment(conn, user_id, f"game:{game_name}")


_GEMINI_GAME_DAILY_LIMIT = 2


def get_gemini_game_daily_count(conn: sqlite3.Connection, user_id: int, game_name: str) -> int:
    """Return today's attempt count for navi_challenge or type_race."""
    return _get(conn, user_id, f"llm_game:{game_name}")


def increment_gemini_game_count(conn: sqlite3.Connection, user_id: int, game_name: str) -> int:
    """Increment attempt count. Returns new count."""
    return _increment(conn, user_id, f"llm_game:{game_name}")


def reset_gemini_game_count(conn: sqlite3.Connection, user_id: int, game_name: str) -> None:
    """Delete today's attempt record for a user in navi_challenge or type_race."""
    _reset(conn, user_id, f"llm_game:{game_name}")


def reset_gambling_count(conn: sqlite3.Connection, user_id: int) -> None:
    """Delete all of today's gambling play counts for a user."""
    _reset(conn, user_id, "game:%")
