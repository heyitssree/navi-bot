# navi/db/repos/games.py - game_results (FFF and Survival share one table; extras live in the details JSON)
from __future__ import annotations

import json
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
    """Persist a Fastest Fingers First result (score = correct answers). username is no longer stored."""
    details = json.dumps({"total_questions": total, "avg_response_ms": avg_ms, "boli_awarded": boli})

    def _write() -> None:
        conn.execute(
            "INSERT OR IGNORE INTO game_results (game, user_id, guild_id, game_id, score, details)"
            " VALUES ('fff', ?, ?, ?, ?, ?)",
            [user_id, guild_id, game_id, correct, details],
        )
        conn.commit()
    _db_write(_write)


def get_fff_leaderboard(
    conn: sqlite3.Connection,
    guild_id: int,
    limit: int = 10,
    global_scope: bool = False,
) -> list[dict]:
    """Top FFF scores for a guild (or globally): most correct answers, then fastest average (ties: lowest user id)."""
    where = "g.game = 'fff'" + ("" if global_scope else " AND g.guild_id = ?")
    params: list = [] if global_scope else [guild_id]
    rows = conn.execute(
        f"""
        SELECT COALESCE(u.display_name, ''), g.score,
               json_extract(g.details, '$.total_questions'), json_extract(g.details, '$.avg_response_ms'),
               json_extract(g.details, '$.boli_awarded'), g.played_at
        FROM game_results g LEFT JOIN users u ON u.user_id = g.user_id
        WHERE {where}
        ORDER BY g.score DESC, json_extract(g.details, '$.avg_response_ms') ASC NULLS LAST, g.user_id ASC, g.id ASC
        LIMIT ?
        """,
        [*params, limit],
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
    """Persist a Survival Mode result (score = streak)."""
    details = json.dumps({"difficulty": difficulty, "category": category, "boli_awarded": boli})

    def _write() -> None:
        conn.execute(
            "INSERT OR IGNORE INTO game_results (game, user_id, guild_id, game_id, score, details)"
            " VALUES ('survival', ?, ?, ?, ?, ?)",
            [user_id, guild_id, game_id, streak, details],
        )
        conn.commit()
    _db_write(_write)


def get_survival_leaderboard(
    conn: sqlite3.Connection,
    guild_id: int,
    limit: int = 10,
    global_scope: bool = False,
) -> list[dict]:
    """Top Survival streaks for a guild (or globally), ranked by streak DESC (ties: lowest user id)."""
    where = "g.game = 'survival'" + ("" if global_scope else " AND g.guild_id = ?")
    params: list = [] if global_scope else [guild_id]
    rows = conn.execute(
        f"""
        SELECT COALESCE(u.display_name, ''), g.score, json_extract(g.details, '$.difficulty'),
               json_extract(g.details, '$.category'), json_extract(g.details, '$.boli_awarded'), g.played_at
        FROM game_results g LEFT JOIN users u ON u.user_id = g.user_id
        WHERE {where}
        ORDER BY g.score DESC, g.user_id ASC, g.id ASC
        LIMIT ?
        """,
        [*params, limit],
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
    cat = "json_extract(details, '$.category') = ?" if category else "json_extract(details, '$.category') IS NULL"
    params: list = [user_id, difficulty] + ([category] if category else [])
    row = conn.execute(
        f"""
        SELECT MAX(score) FROM game_results
        WHERE game = 'survival' AND user_id = ? AND json_extract(details, '$.difficulty') = ? AND {cat}
        """,
        params,
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0
