# navi/db/repos/points.py - moved from schema.py (no behaviour change)
from __future__ import annotations

import logging
import math
import sqlite3

from navi.db.connection import _db_write
from navi.db.repos.users import get_user_profile

logger = logging.getLogger("navi.db.points")


def update_boli_points(
    conn: sqlite3.Connection,
    user_id: int,
    delta: int,
) -> None:
    """Add (or subtract) Boli Points for a user."""
    _db_write(lambda: (
        conn.execute(
            "UPDATE user_stats SET boli_points = boli_points + ? WHERE user_id = ?",
            [delta, user_id],
        ),
        conn.commit(),
    ))


def add_experience(
    conn: sqlite3.Connection,
    user_id: int,
    delta: int,
) -> None:
    """Add XP for a user. XP never decreases — negative deltas are silently clamped to 0."""
    if delta <= 0:
        return
    _db_write(lambda: (
        conn.execute(
            "UPDATE user_stats SET experience = experience + ? WHERE user_id = ?",
            [delta, user_id],
        ),
        conn.commit(),
    ))


def get_experience(conn: sqlite3.Connection, user_id: int) -> int:
    """Return raw experience points for a user (0 if not found)."""
    row = conn.execute(
        "SELECT experience FROM user_stats WHERE user_id = ?", [user_id]
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def set_user_points(conn: sqlite3.Connection, user_id: int, username: str, points: int, prediction_count: int = 0, rashi: str | None = None) -> None:
    """Upsert a user's Boli Points directly — used for manual data restore."""
    existing = get_user_profile(conn, user_id)
    def _write() -> None:
        if existing is None:
            conn.execute(
                "INSERT INTO user_stats (user_id, username, rashi, boli_points, last_seen, prediction_count) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)",
                [user_id, username, rashi, points, prediction_count],
            )
        else:
            conn.execute(
                "UPDATE user_stats SET boli_points=?, prediction_count=?, username=?, rashi=COALESCE(?, rashi) WHERE user_id=?",
                [points, prediction_count, username, rashi, user_id],
            )
        conn.commit()
    _db_write(_write)


def points_for_level(level: int) -> int:
    """Total Boli Points required to reach *level* from zero.

    Formula: 5 * n * (n + 3)
    Per-level cost grows by 10 each step:
      Level 1  →  20 pts total
      Level 10 →  650 pts total
      Level 50 →  13,250 pts total
      Level 100 → 51,500 pts total
    """
    if level <= 0:
        return 0
    n = min(level, 100)
    return 5 * n * (n + 3)


def get_level_from_points(points: int) -> int:
    """Compute level (0–100) from lifetime XP (experience column).

    Solves 5n(n+3) ≤ points for the largest integer n.
    """
    if points <= 0:
        return 0
    # 5n² + 15n - points = 0  →  n = (-15 + sqrt(225 + 20·points)) / 10
    n = int((-15 + math.sqrt(225 + 20 * points)) / 10)
    return min(max(n, 0), 100)


def get_gift_daily_total(conn: sqlite3.Connection, sender_id: int) -> int:
    """Return total Boli gifted by sender_id today (UTC date)."""
    row = conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0) FROM gift_log
        WHERE sender_id = ? AND DATE(gifted_at) = DATE('now')
        """,
        [sender_id],
    ).fetchone()
    return int(row[0]) if row else 0


def record_gift(
    conn: sqlite3.Connection,
    sender_id: int,
    recipient_id: int,
    amount: int,
) -> None:
    """Record a gift transaction for daily cap tracking."""
    def _write() -> None:
        conn.execute(
            "INSERT INTO gift_log (sender_id, recipient_id, amount) VALUES (?, ?, ?)",
            [sender_id, recipient_id, amount],
        )
        conn.commit()
    _db_write(_write)


def partner_score_exists(conn: sqlite3.Connection, game_id: str) -> bool:
    """Return True if this game_id has already been processed."""
    row = conn.execute(
        "SELECT 1 FROM partner_score_log WHERE game_id = ?", [game_id]
    ).fetchone()
    return row is not None


def log_partner_score(
    conn: sqlite3.Connection,
    game_id: str,
    user_id: int,
    guild_id: int,
    username: str,
    raw_points: int,
    boli_awarded: int,
    xp_awarded: int,
    game_type: str = "default",
) -> None:
    """Persist an inbound partner-bot score submission."""
    def _write() -> None:
        conn.execute(
            """
            INSERT INTO partner_score_log
                (game_id, user_id, guild_id, username, raw_points, boli_awarded, xp_awarded, game_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [game_id, user_id, guild_id, username, raw_points, boli_awarded, xp_awarded, game_type],
        )
        conn.commit()
    _db_write(_write)


def add_external_boli(
    conn: sqlite3.Connection,
    user_id: int,
    username: str,
    points: int,
    game_id: str | None = None,
    source_game: str = "partner",
) -> None:
    """Record an external boli award in the separate external_boli_points table.

    Points are stored as-is (can be negative for deductions).
    Does NOT touch user_stats.boli_points — the combined total is exposed
    through boli_totals_view and get_user_profile()'s total_boli_points field.
    """
    def _write() -> None:
        conn.execute(
            """
            INSERT INTO external_boli_points (user_id, username, points, source_game, game_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            [user_id, username, points, source_game, game_id],
        )
        conn.commit()
    _db_write(_write)


def get_recent_partner_logs(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """Return the most recent partner score submissions."""
    rows = conn.execute(
        """
        SELECT game_id, username, game_type, raw_points, boli_awarded, received_at
        FROM partner_score_log ORDER BY received_at DESC LIMIT ?
        """,
        [limit],
    ).fetchall()
    return [
        {
            "game_id": r[0], "username": r[1], "game_type": r[2],
            "raw_points": r[3], "boli_awarded": r[4], "received_at": r[5],
        }
        for r in rows
    ]


def log_curse(
    conn: sqlite3.Connection,
    user_id: int,
    username: str,
    curse_used: str,
) -> None:
    def _write() -> None:
        conn.execute(
            """
            INSERT INTO curse_logs (id, user_id, username, curse_used)
            VALUES (NULL, ?, ?, ?)
            """,
            [user_id, username, curse_used],
        )
        conn.commit()
    _db_write(_write)


def log_bless(
    conn: sqlite3.Connection,
    user_id: int,
    username: str,
    bless_used: str,
) -> None:
    """Log a successful bless event (recipient's perspective)."""
    def _write() -> None:
        conn.execute(
            """
            INSERT INTO bless_logs (id, user_id, username, bless_used)
            VALUES (NULL, ?, ?, ?)
            """,
            [user_id, username, bless_used],
        )
        conn.commit()
    _db_write(_write)


def get_curse_leaderboard(
    conn: sqlite3.Connection,
    limit: int = 5,
) -> list[dict]:
    """Return the most-cursed users (excluding backfires from the count)."""
    rows = conn.execute(
        """
        SELECT user_id, username, COUNT(*) AS hits
        FROM curse_logs
        WHERE curse_used NOT LIKE 'backfire_%' AND curse_used NOT LIKE 'proxy_%'
        GROUP BY user_id, username
        ORDER BY hits DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    return [{"user_id": r[0], "username": r[1], "hits": r[2]} for r in rows]


def get_bless_leaderboard(
    conn: sqlite3.Connection,
    limit: int = 5,
) -> list[dict]:
    """Return the most-blessed users."""
    rows = conn.execute(
        """
        SELECT user_id, username, COUNT(*) AS hits
        FROM bless_logs
        GROUP BY user_id, username
        ORDER BY hits DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    return [{"user_id": r[0], "username": r[1], "hits": r[2]} for r in rows]
