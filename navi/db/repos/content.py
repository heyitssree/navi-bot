# navi/db/repos/content.py - reusable generated text (content table) and per-user prediction history (v2)
from __future__ import annotations

import logging
import random
import sqlite3

from navi.db.connection import _db_write

logger = logging.getLogger("navi.db.content")

# Old predictions_cache.cache_type -> content.kind
KIND_BY_CACHE_TYPE = {"navi": "prediction", "curse": "curse_back", "qa": "qa_answer"}


def kind_for(cache_type: str) -> str:
    return KIND_BY_CACHE_TYPE.get(cache_type, cache_type)


def get_cached_prediction(
    conn: sqlite3.Connection,
    cache_type: str,
    min_count: int = 50,
) -> str | None:
    """Return a random active template for a cache type, or None.

    Only serves from the pool when at least *min_count* active entries exist.
    """
    kind = kind_for(cache_type)
    result = conn.execute(
        "SELECT COUNT(*) FROM content WHERE kind = ? AND status = 'active'", [kind]
    ).fetchone()
    if (result[0] if result else 0) < min_count:
        return None
    row = conn.execute(
        "SELECT text FROM content WHERE kind = ? AND status = 'active' ORDER BY RANDOM() LIMIT 1", [kind]
    ).fetchone()
    return row[0] if row else None


def save_prediction(
    conn: sqlite3.Connection,
    cache_type: str,
    template_text: str,
    user_id: int | None = None,
    original_prompt: str | None = None,
    source: str = "llm",
) -> None:
    """Save a generalized (templatized) prediction to the pool. user_id/original_prompt are no longer stored."""
    def _write() -> None:
        conn.execute(
            "INSERT OR IGNORE INTO content (kind, text, status, source) VALUES (?, ?, 'active', ?)",
            [kind_for(cache_type), template_text, source],
        )
        conn.commit()
    _db_write(_write)


def get_last_n_predictions(conn: sqlite3.Connection, user_id: int, n: int = 3) -> list[str]:
    """Return the user's last N predictions, newest first."""
    rows = conn.execute(
        "SELECT text FROM prediction_history WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
        [user_id, n],
    ).fetchall()
    return [r[0] for r in rows]


def save_user_prediction(conn: sqlite3.Connection, user_id: int, prediction_text: str) -> None:
    """Persist a prediction to the user's history."""
    def _write() -> None:
        conn.execute("INSERT INTO prediction_history (user_id, text) VALUES (?, ?)", [user_id, prediction_text])
        conn.commit()
    _db_write(_write)


def get_todays_user_prediction(conn: sqlite3.Connection, user_id: int) -> str | None:
    """Check if the user already received a prediction today, return it if so."""
    row = conn.execute(
        """
        SELECT text FROM prediction_history
        WHERE user_id = ? AND DATE(created_at) = DATE('now')
        ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        [user_id],
    ).fetchone()
    return row[0] if row else None


def _score_key(game_type: str, score: int) -> str:
    return f"{game_type}:{min(score // 10, 9) * 10}"


def get_score_comment(conn: sqlite3.Connection, game_type: str, score: int) -> str | None:
    """Return a cached funny comment for the given score bucket, or None if uncached."""
    rows = conn.execute(
        "SELECT text FROM content WHERE kind = 'score_comment' AND key = ? AND status = 'active'",
        [_score_key(game_type, score)],
    ).fetchall()
    return random.choice(rows)[0] if rows else None


def save_score_comment(conn: sqlite3.Connection, game_type: str, score: int, comment: str) -> None:
    """Cache a funny generated score comment for future reuse."""
    _db_write(lambda: (
        conn.execute(
            "INSERT OR IGNORE INTO content (kind, key, text, status, source) VALUES ('score_comment', ?, ?, 'active', 'llm')",
            [_score_key(game_type, score), comment],
        ),
        conn.commit(),
    ))


def get_movie_dialogue_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM content WHERE kind = 'movie_dialogue'").fetchone()
    return int(row[0]) if row else 0


def get_random_movie_dialogue(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT text FROM content WHERE kind = 'movie_dialogue' AND status = 'active' ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def dialogue_exists(conn: sqlite3.Connection, dialogue: str) -> bool:
    """Return True if this exact dialogue is already cached."""
    row = conn.execute(
        "SELECT 1 FROM content WHERE kind = 'movie_dialogue' AND text = ? LIMIT 1", [dialogue]
    ).fetchone()
    return row is not None


def save_movie_dialogue(conn: sqlite3.Connection, dialogue: str) -> None:
    """Insert a new dialogue, silently ignore if it already exists."""
    _db_write(lambda: (
        conn.execute(
            "INSERT OR IGNORE INTO content (kind, text, status, source) VALUES ('movie_dialogue', ?, 'active', 'llm')",
            [dialogue],
        ),
        conn.commit(),
    ))
