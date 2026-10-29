# navi/db/repos/content.py - moved from schema.py (no behaviour change)
from __future__ import annotations

import logging
import random
import sqlite3

from navi.db.connection import _db_write

logger = logging.getLogger("navi.db.content")


def get_cached_prediction(
    conn: sqlite3.Connection,
    cache_type: str,
    min_count: int = 50,
) -> str | None:
    """Return a random cached template for a given cache_type, or None.

    Only serves from cache when at least *min_count* entries exist.
    """
    result = conn.execute(
        "SELECT COUNT(*) FROM predictions_cache WHERE cache_type = ?",
        [cache_type],
    ).fetchone()
    count = result[0] if result else 0

    if count < min_count:
        return None

    row = conn.execute(
        """
        SELECT template_text FROM predictions_cache
        WHERE cache_type = ?
        ORDER BY RANDOM() LIMIT 1
        """,
        [cache_type],
    ).fetchone()
    return row[0] if row else None


def save_prediction(
    conn: sqlite3.Connection,
    cache_type: str,
    template_text: str,
    user_id: int | None = None,
    original_prompt: str | None = None,
) -> None:
    """Save a generalized (templatized) prediction to the cache."""
    exists = conn.execute(
        "SELECT 1 FROM predictions_cache WHERE template_text = ? AND cache_type = ?",
        [template_text, cache_type],
    ).fetchone()
    if exists:
        return

    def _write() -> None:
        conn.execute(
            """
            INSERT INTO predictions_cache (id, cache_type, user_id, original_prompt, template_text)
            VALUES (NULL, ?, ?, ?, ?)
            """,
            [cache_type, user_id, original_prompt, template_text],
        )
        conn.commit()
    _db_write(_write)


def get_last_n_predictions(
    conn: sqlite3.Connection,
    user_id: int,
    n: int = 3,
) -> list[str]:
    """Return the user's last N doomed predictions, newest first."""
    rows = conn.execute(
        """
        SELECT prediction_text FROM user_prediction_history
        WHERE user_id = ?
        ORDER BY timestamp DESC LIMIT ?
        """,
        [user_id, n],
    ).fetchall()
    return [r[0] for r in rows]


def save_user_prediction(
    conn: sqlite3.Connection,
    user_id: int,
    prediction_text: str,
) -> None:
    """Persist a prediction to the user's history."""
    def _write() -> None:
        conn.execute(
            """
            INSERT INTO user_prediction_history (id, user_id, prediction_text)
            VALUES (NULL, ?, ?)
            """,
            [user_id, prediction_text],
        )
        conn.commit()
    _db_write(_write)


def get_todays_user_prediction(
    conn: sqlite3.Connection,
    user_id: int,
) -> str | None:
    """Check if the user already received a prediction today, return it if so."""
    row = conn.execute(
        """
        SELECT prediction_text FROM user_prediction_history
        WHERE user_id = ? AND DATE(timestamp) = DATE('now')
        ORDER BY timestamp DESC LIMIT 1
        """,
        [user_id]
    ).fetchone()
    return row[0] if row else None


def get_score_comment(conn: sqlite3.Connection, game_type: str, score: int) -> str | None:
    """Return a cached funny comment for the given score bucket, or None if uncached."""
    bucket = min(score // 10, 9)
    rows = conn.execute(
        "SELECT comment FROM gemini_score_comments WHERE game_type = ? AND score_bucket = ?",
        [game_type, bucket],
    ).fetchall()
    return random.choice(rows)[0] if rows else None


def save_score_comment(conn: sqlite3.Connection, game_type: str, score: int, comment: str) -> None:
    """Cache a funny Gemini-generated score comment for future reuse."""
    bucket = min(score // 10, 9)
    _db_write(lambda: (
        conn.execute(
            "INSERT INTO gemini_score_comments (game_type, score_bucket, comment) VALUES (?, ?, ?)",
            [game_type, bucket, comment],
        ),
        conn.commit(),
    ))


def get_movie_dialogue_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM movie_dialogues").fetchone()
    return int(row[0]) if row else 0


def get_random_movie_dialogue(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT dialogue FROM movie_dialogues ORDER BY RANDOM() LIMIT 1").fetchone()
    return row[0] if row else None


def dialogue_exists(conn: sqlite3.Connection, dialogue: str) -> bool:
    """Return True if this exact dialogue is already cached."""
    row = conn.execute(
        "SELECT 1 FROM movie_dialogues WHERE dialogue = ? LIMIT 1", [dialogue]
    ).fetchone()
    return row is not None


def save_movie_dialogue(conn: sqlite3.Connection, dialogue: str) -> None:
    """Insert a new dialogue, silently ignore if it already exists (UNIQUE constraint)."""
    _db_write(lambda: (
        conn.execute("INSERT OR IGNORE INTO movie_dialogues (dialogue) VALUES (?)", [dialogue]),
        conn.commit(),
    ))
