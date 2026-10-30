# navi/db/repos/points.py - points_ledger reads and the single transactional write (v2)
#
# apply_entry() is called ONLY by navi.services.points: it changes the balance and appends the ledger row in one
# transaction, so SUM(points_ledger.delta) per user and pool always equals users.boli_points / partner_points.
from __future__ import annotations

import json
import logging
import math
import sqlite3

from navi.db.connection import _db_write

logger = logging.getLogger("navi.db.points")

CURSED_REASONS = ("curse_received", "curse_word_said")   # counted by the "most cursed" leaderboard
BLESSED_REASONS = ("bless_received",)

_BALANCE_COLUMN = {"native": "boli_points", "partner": "partner_points"}


def apply_entry(
    conn: sqlite3.Connection,
    user_id: int,
    delta: int,
    xp: int,
    reason: str,
    *,
    pool: str = "native",
    counterparty_id: int | None = None,
    detail: str | None = None,
    ref: str | None = None,
    log_only: bool = False,
) -> bool:
    """Apply a balance/XP change and its ledger row atomically.

    Returns False (and changes nothing) when the user does not exist, when (reason, ref) was already recorded
    (idempotent partner awards), or when there is nothing to record (delta == 0, xp == 0 and not log_only).
    log_only=True writes a history row even for delta == 0 (curse on a protected target, etc.).
    """
    xp = max(0, int(xp))   # XP never decreases
    delta = int(delta)
    if delta == 0 and xp == 0 and not log_only:
        return False
    column = _BALANCE_COLUMN[pool]

    def _write() -> bool:
        try:
            cur = conn.execute(
                f"UPDATE users SET {column} = {column} + ?, experience = experience + ? WHERE user_id = ?",
                [delta, xp, user_id],
            )
            if cur.rowcount == 0:
                conn.rollback()
                return False
            conn.execute(
                """
                INSERT INTO points_ledger (user_id, pool, delta, xp_delta, reason, counterparty_id, detail, ref)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [user_id, pool, delta, xp, reason, counterparty_id, detail, ref],
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            conn.rollback()   # duplicate (reason, ref)
            return False
        except Exception:
            conn.rollback()
            raise

    return _db_write(_write)


def get_experience(conn: sqlite3.Connection, user_id: int) -> int:
    """Return raw experience points for a user (0 if not found)."""
    row = conn.execute("SELECT experience FROM users WHERE user_id = ?", [user_id]).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def points_for_level(level: int) -> int:
    """Total Boli Points required to reach *level* from zero.

    Formula: 5 * n * (n + 3)
    Per-level cost grows by 10 each step:
      Level 1  ->  20 pts total
      Level 10 ->  650 pts total
      Level 50 ->  13,250 pts total
      Level 100 -> 51,500 pts total
    """
    if level <= 0:
        return 0
    n = min(level, 100)
    return 5 * n * (n + 3)


def get_level_from_points(points: int) -> int:
    """Compute level (0-100) from lifetime XP (experience column).

    Solves 5n(n+3) <= points for the largest integer n.
    """
    if points <= 0:
        return 0
    # 5n^2 + 15n - points = 0  ->  n = (-15 + sqrt(225 + 20*points)) / 10
    n = int((-15 + math.sqrt(225 + 20 * points)) / 10)
    return min(max(n, 0), 100)


def get_gift_daily_total(conn: sqlite3.Connection, sender_id: int) -> int:
    """Return total Boli gifted by sender_id today (UTC date)."""
    row = conn.execute(
        """
        SELECT COALESCE(SUM(-delta), 0) FROM points_ledger
        WHERE user_id = ? AND reason = 'gift_sent' AND DATE(created_at) = DATE('now')
        """,
        [sender_id],
    ).fetchone()
    return int(row[0]) if row else 0


def partner_score_exists(conn: sqlite3.Connection, game_id: str) -> bool:
    """Return True if this partner game_id has already been processed."""
    prefix = game_id + ":"   # batch awards are stored per player as "<game_id>:<discord_id>"
    row = conn.execute(
        "SELECT 1 FROM points_ledger WHERE reason = 'partner_award' AND (ref = ? OR substr(ref, 1, ?) = ?)",
        [game_id, len(prefix), prefix],
    ).fetchone()
    return row is not None


def get_recent_partner_logs(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """Return the most recent partner score submissions."""
    rows = conn.execute(
        """
        SELECT l.ref, COALESCE(u.display_name, ''), l.detail, l.delta, l.created_at
        FROM points_ledger l LEFT JOIN users u ON u.user_id = l.user_id
        WHERE l.reason = 'partner_award' ORDER BY l.id DESC LIMIT ?
        """,
        [limit],
    ).fetchall()
    out = []
    for ref, username, detail, delta, created_at in rows:
        try:
            info = json.loads(detail) if detail else {}
        except ValueError:
            info = {}
        out.append({
            "game_id": ref, "username": username, "game_type": info.get("game_type", "default"),
            "raw_points": info.get("raw_points"), "boli_awarded": delta, "received_at": created_at,
        })
    return out


def _count_leaderboard(conn: sqlite3.Connection, reasons: tuple[str, ...], limit: int) -> list[dict]:
    marks = ",".join("?" * len(reasons))
    rows = conn.execute(
        f"""
        SELECT l.user_id, COALESCE(u.display_name, ''), COUNT(*) AS hits
        FROM points_ledger l LEFT JOIN users u ON u.user_id = l.user_id
        WHERE l.reason IN ({marks})
        GROUP BY l.user_id
        ORDER BY hits DESC, l.user_id ASC
        LIMIT ?
        """,
        [*reasons, limit],
    ).fetchall()
    return [{"user_id": r[0], "username": r[1], "hits": r[2]} for r in rows]


def get_curse_leaderboard(conn: sqlite3.Connection, limit: int = 5) -> list[dict]:
    """Return the most-cursed users (backfires and self-curses are not counted)."""
    return _count_leaderboard(conn, CURSED_REASONS, limit)


def get_bless_leaderboard(conn: sqlite3.Connection, limit: int = 5) -> list[dict]:
    """Return the most-blessed users."""
    return _count_leaderboard(conn, BLESSED_REASONS, limit)
