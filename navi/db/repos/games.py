# navi/db/repos/games.py - moved from schema.py (no behaviour change)
from __future__ import annotations

import logging
import sqlite3

from navi.db.connection import _db_write

logger = logging.getLogger("navi.db.games")


def save_fff_result(
    conn: sqlite3.Connection,
    game_id: str,
    user_id: int,
    guild_id: int,
    username: str,
    correct: int,
    total: int,
    avg_ms: int | None,
    boli: int,
) -> None:
    """Persist a Fastest Fingers First result."""
    def _write() -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO fff_scores
                (game_id, user_id, guild_id, username, correct_answers,
                 total_questions, avg_response_ms, boli_awarded)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [game_id, user_id, guild_id, username, correct, total, avg_ms, boli],
        )
        conn.commit()
    _db_write(_write)


def get_fff_leaderboard(
    conn: sqlite3.Connection,
    guild_id: int,
    limit: int = 10,
    global_scope: bool = False,
) -> list[dict]:
    """Return top FFF scores for a guild (or globally), ranked by correct_answers DESC,
    then avg_response_ms ASC (faster wins on ties)."""
    if global_scope:
        rows = conn.execute(
            """
            SELECT username, correct_answers, total_questions, avg_response_ms, boli_awarded, played_at
            FROM fff_scores
            ORDER BY correct_answers DESC, avg_response_ms ASC NULLS LAST
            LIMIT ?
            """,
            [limit],
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT username, correct_answers, total_questions, avg_response_ms, boli_awarded, played_at
            FROM fff_scores
            WHERE guild_id = ?
            ORDER BY correct_answers DESC, avg_response_ms ASC NULLS LAST
            LIMIT ?
            """,
            [guild_id, limit],
        ).fetchall()
    return [
        {
            "username": r[0],
            "correct_answers": r[1],
            "total_questions": r[2],
            "avg_response_ms": r[3],
            "boli_awarded": r[4],
            "played_at": r[5],
        }
        for r in rows
    ]


def save_survival_result(
    conn: sqlite3.Connection,
    game_id: str,
    user_id: int,
    guild_id: int,
    username: str,
    streak: int,
    difficulty: str,
    category: str | None,
    boli: int,
) -> None:
    """Persist a Survival Mode result."""
    def _write() -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO survival_scores
                (game_id, user_id, guild_id, username, streak, difficulty, category, boli_awarded)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [game_id, user_id, guild_id, username, streak, difficulty, category, boli],
        )
        conn.commit()
    _db_write(_write)


def get_survival_leaderboard(
    conn: sqlite3.Connection,
    guild_id: int,
    limit: int = 10,
    global_scope: bool = False,
) -> list[dict]:
    """Return top Survival streaks for a guild (or globally), ranked by streak DESC."""
    if global_scope:
        rows = conn.execute(
            """
            SELECT username, streak, difficulty, category, boli_awarded, played_at
            FROM survival_scores
            ORDER BY streak DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT username, streak, difficulty, category, boli_awarded, played_at
            FROM survival_scores
            WHERE guild_id = ?
            ORDER BY streak DESC
            LIMIT ?
            """,
            [guild_id, limit],
        ).fetchall()
    return [
        {
            "username": r[0],
            "streak": r[1],
            "difficulty": r[2],
            "category": r[3],
            "boli_awarded": r[4],
            "played_at": r[5],
        }
        for r in rows
    ]


def get_survival_personal_best(
    conn: sqlite3.Connection,
    user_id: int,
    difficulty: str,
    category: str | None,
) -> int:
    """Return a user's best streak for a given difficulty+category combo (0 if none)."""
    if category:
        row = conn.execute(
            """
            SELECT MAX(streak) FROM survival_scores
            WHERE user_id = ? AND difficulty = ? AND category = ?
            """,
            [user_id, difficulty, category],
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT MAX(streak) FROM survival_scores
            WHERE user_id = ? AND difficulty = ? AND category IS NULL
            """,
            [user_id, difficulty],
        ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0
