# navi/services/retention.py - daily housekeeping so the database stays small
#
#   events                  older than 90 days are deleted
#   prediction_history      only the newest 20 per user are kept
#   daily_counters          rows older than 14 days are deleted
#   points_ledger           high-volume reasons (slang, game) older than 180 days are compacted into one
#                           rollup row per user, pool and reason (sums are preserved, so balances still reconcile)

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3

logger = logging.getLogger("navi.services.retention")

EVENT_DAYS = 90
PREDICTIONS_PER_USER = 20
COUNTER_DAYS = 14
LEDGER_COMPACT_DAYS = 180
COMPACT_REASONS = ("slang", "game")
INTERVAL_SECONDS = 24 * 3600


def run_retention(conn: sqlite3.Connection) -> dict[str, int]:
    """Run every retention rule once. Returns how many rows each rule removed."""
    removed: dict[str, int] = {}
    try:
        removed["events"] = conn.execute(
            "DELETE FROM events WHERE created_at < datetime('now', ?)", [f"-{EVENT_DAYS} days"]
        ).rowcount
        removed["prediction_history"] = conn.execute(
            """
            DELETE FROM prediction_history WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC, id DESC) AS rn
                    FROM prediction_history
                ) WHERE rn > ?
            )
            """,
            [PREDICTIONS_PER_USER],
        ).rowcount
        removed["daily_counters"] = conn.execute(
            "DELETE FROM daily_counters WHERE day < date('now', ?)", [f"-{COUNTER_DAYS} days"]
        ).rowcount
        removed["ledger_compacted"] = _compact_ledger(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    logger.info("Retention removed: %s", removed)
    return removed


def _compact_ledger(conn: sqlite3.Connection) -> int:
    marks = ",".join("?" * len(COMPACT_REASONS))
    cutoff = f"-{LEDGER_COMPACT_DAYS} days"
    groups = conn.execute(
        f"""
        SELECT user_id, pool, reason, SUM(delta), SUM(xp_delta), COUNT(*), MAX(created_at)
        FROM points_ledger
        WHERE reason IN ({marks}) AND ref IS NULL AND created_at < datetime('now', ?)
        GROUP BY user_id, pool, reason
        HAVING COUNT(*) > 1
        """,
        [*COMPACT_REASONS, cutoff],
    ).fetchall()
    removed = 0
    for user_id, pool, reason, delta, xp, count, newest in groups:
        conn.execute(
            "DELETE FROM points_ledger WHERE user_id = ? AND pool = ? AND reason = ? AND ref IS NULL"
            " AND created_at < datetime('now', ?)",
            [user_id, pool, reason, cutoff],
        )
        conn.execute(
            "INSERT INTO points_ledger (user_id, pool, delta, xp_delta, reason, detail, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [user_id, pool, delta, xp, reason, json.dumps({"rollup": count}), newest],
        )
        removed += count - 1
    return removed


async def retention_loop(ctx) -> None:
    await asyncio.sleep(120)  # let startup finish first
    while True:
        try:
            await asyncio.get_running_loop().run_in_executor(None, run_retention, ctx.db)
        except Exception as exc:
            logger.error("Retention failed: %s", exc)
        await asyncio.sleep(INTERVAL_SECONDS)
