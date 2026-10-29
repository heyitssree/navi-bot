# navi/db/repos/counters.py - moved from schema.py (no behaviour change)
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone

from navi.db.connection import _db_write

logger = logging.getLogger("navi.db.counters")


_IST = timezone(timedelta(hours=5, minutes=30))


def _today_ist() -> date:
    """Return the current date in IST (UTC+5:30), used for daily quota resets."""
    return datetime.now(_IST).date()


def get_daily_action_count(conn: sqlite3.Connection, user_id: int) -> int:
    """Return today's combined curse/bless action count. Returns 0 if the record is from a previous day."""
    row = conn.execute(
        "SELECT daily_action_count, last_action_date FROM user_stats WHERE user_id = ?",
        [user_id],
    ).fetchone()
    if not row:
        return 0
    count, last_date = row
    if last_date != _today_ist():
        return 0
    return int(count) if count else 0


def increment_daily_action_count(conn: sqlite3.Connection, user_id: int) -> int:
    """Increment daily action count (resetting to 1 if it's a new day). Returns new count."""
    today = _today_ist()
    _db_write(lambda: (
        conn.execute(
            """
            UPDATE user_stats
            SET
                daily_action_count = CASE WHEN last_action_date = ? THEN daily_action_count + 1 ELSE 1 END,
                last_action_date = ?
            WHERE user_id = ?
            """,
            [today, today, user_id],
        ),
        conn.commit(),
    ))
    row = conn.execute(
        "SELECT daily_action_count FROM user_stats WHERE user_id = ?", [user_id]
    ).fetchone()
    return int(row[0]) if row and row[0] else 1


def get_extra_actions(conn: sqlite3.Connection, user_id: int) -> int:
    """Return the number of purchased extra actions remaining for a user."""
    row = conn.execute(
        "SELECT extra_actions FROM user_stats WHERE user_id = ?", [user_id]
    ).fetchone()
    return int(row[0]) if row and row[0] else 0


def decrement_extra_actions(conn: sqlite3.Connection, user_id: int) -> None:
    """Consume one extra action token, flooring at 0."""
    _db_write(lambda: (
        conn.execute(
            "UPDATE user_stats SET extra_actions = CASE WHEN extra_actions > 0 THEN extra_actions - 1 ELSE 0 END WHERE user_id = ?",
            [user_id],
        ),
        conn.commit(),
    ))


def add_extra_actions(conn: sqlite3.Connection, user_id: int, amount: int) -> None:
    """Add purchased extra action tokens to a user's balance."""
    _db_write(lambda: (
        conn.execute(
            "UPDATE user_stats SET extra_actions = extra_actions + ? WHERE user_id = ?",
            [amount, user_id],
        ),
        conn.commit(),
    ))


def get_daily_refill_count(conn: sqlite3.Connection, user_id: int) -> int:
    """Return how many action refills the user has bought today (IST). 0 if a different day."""
    row = conn.execute(
        "SELECT daily_refill_count, last_refill_date FROM user_stats WHERE user_id = ?",
        [user_id],
    ).fetchone()
    if not row:
        return 0
    count, last_date = row
    if last_date != _today_ist():
        return 0
    return int(count) if count else 0


def increment_daily_refill_count(conn: sqlite3.Connection, user_id: int) -> int:
    """Increment today's refill count (resetting to 1 if it's a new day). Returns new count."""
    today = _today_ist()
    _db_write(lambda: (
        conn.execute(
            """
            UPDATE user_stats
            SET
                daily_refill_count = CASE WHEN last_refill_date = ? THEN daily_refill_count + 1 ELSE 1 END,
                last_refill_date = ?
            WHERE user_id = ?
            """,
            [today, today, user_id],
        ),
        conn.commit(),
    ))
    row = conn.execute(
        "SELECT daily_refill_count FROM user_stats WHERE user_id = ?", [user_id]
    ).fetchone()
    return int(row[0]) if row and row[0] else 1


_GAME_DAILY_LIMIT = 30


def get_game_daily_count(conn: sqlite3.Connection, user_id: int, game_name: str) -> int:
    """Return today's play count for the given game (IST). Returns 0 if no record today."""
    today = _today_ist()
    row = conn.execute(
        "SELECT play_count FROM game_daily_counts WHERE user_id = ? AND game_name = ? AND play_date = ?",
        [user_id, game_name, today],
    ).fetchone()
    return int(row[0]) if row else 0


def get_total_game_daily_count(conn: sqlite3.Connection, user_id: int) -> int:
    """Return total plays across ALL games today (IST). Used for the combined 30/day limit."""
    today = _today_ist()
    row = conn.execute(
        "SELECT COALESCE(SUM(play_count), 0) FROM game_daily_counts WHERE user_id = ? AND play_date = ?",
        [user_id, today],
    ).fetchone()
    return int(row[0]) if row else 0


def increment_game_daily_count(conn: sqlite3.Connection, user_id: int, game_name: str) -> int:
    """Increment today's play count for the given game. Returns the new count."""
    today = _today_ist()
    _db_write(lambda: (
        conn.execute(
            """
            INSERT INTO game_daily_counts (user_id, game_name, play_date, play_count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT (user_id, game_name, play_date) DO UPDATE SET
                play_count = play_count + 1
            """,
            [user_id, game_name, today],
        ),
        conn.commit(),
    ))
    row = conn.execute(
        "SELECT play_count FROM game_daily_counts WHERE user_id = ? AND game_name = ? AND play_date = ?",
        [user_id, game_name, today],
    ).fetchone()
    return int(row[0]) if row else 1


_GEMINI_GAME_DAILY_LIMIT = 2


def get_gemini_game_daily_count(conn: sqlite3.Connection, user_id: int, game_name: str) -> int:
    """Return today's attempt count for navi_challenge or type_race."""
    table = "navi_challenge_attempts" if game_name == "navi_challenge" else "type_race_attempts"
    today = _today_ist()
    row = conn.execute(
        f"SELECT play_count FROM {table} WHERE user_id = ? AND play_date = ?",
        [user_id, today],
    ).fetchone()
    return int(row[0]) if row else 0


def increment_gemini_game_count(conn: sqlite3.Connection, user_id: int, game_name: str) -> int:
    """Increment attempt count. Returns new count."""
    table = "navi_challenge_attempts" if game_name == "navi_challenge" else "type_race_attempts"
    today = _today_ist()
    _db_write(lambda: (
        conn.execute(
            f"INSERT INTO {table} (user_id, play_date, play_count) VALUES (?, ?, 1) "
            f"ON CONFLICT (user_id, play_date) DO UPDATE SET play_count = play_count + 1",
            [user_id, today],
        ),
        conn.commit(),
    ))
    row = conn.execute(
        f"SELECT play_count FROM {table} WHERE user_id = ? AND play_date = ?",
        [user_id, today],
    ).fetchone()
    return int(row[0]) if row else 1


def reset_gemini_game_count(conn: sqlite3.Connection, user_id: int, game_name: str) -> None:
    """Delete today's attempt record for a user in navi_challenge or type_race."""
    table = "navi_challenge_attempts" if game_name == "navi_challenge" else "type_race_attempts"
    today = _today_ist()
    _db_write(lambda: (
        conn.execute(f"DELETE FROM {table} WHERE user_id = ? AND play_date = ?", [user_id, today]),
        conn.commit(),
    ))


def reset_gambling_count(conn: sqlite3.Connection, user_id: int) -> None:
    """Delete all of today's gambling play counts for a user."""
    today = _today_ist()
    _db_write(lambda: (
        conn.execute(
            "DELETE FROM game_daily_counts WHERE user_id = ? AND play_date = ?",
            [user_id, today],
        ),
        conn.commit(),
    ))
