# navi/db/repos/events.py - moved from schema.py (no behaviour change)
from __future__ import annotations

import csv
import logging
import sqlite3

from navi.db.connection import _db_write

logger = logging.getLogger("navi.db.events")


def log_command_event(
    conn: sqlite3.Connection,
    user_id: int,
    username: str,
    command: str,
    subcommand: str | None = None,
    channel_id: int | None = None,
    guild_id: int | None = None,
    latency_ms: int | None = None,
    used_cache: int = 0,
) -> None:
    """Record a single command invocation for usage analytics."""
    def _write() -> None:
        conn.execute(
            """
            INSERT INTO command_events
                (id, user_id, username, command, subcommand, channel_id, guild_id, latency_ms, used_cache)
            VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [user_id, username, command, subcommand, channel_id, guild_id, latency_ms, used_cache],
        )
        conn.commit()
    _db_write(_write)


def log_session_event(
    conn: sqlite3.Connection,
    event_type: str,
    detail: str | None = None,
) -> None:
    """Record a bot lifecycle event (start, stop, ready, error)."""
    def _write() -> None:
        conn.execute(
            "INSERT INTO session_events (id, event_type, detail) VALUES (NULL, ?, ?)",
            [event_type, detail],
        )
        conn.commit()
    _db_write(_write)


def log_api_call(
    conn: sqlite3.Connection,
    key_used: str,
    cache_hit: bool = False,
    command: str | None = None,
    latency_ms: int | None = None,
    error: str | None = None,
) -> None:
    """Record a Gemini API call for cost and cache visibility."""
    def _write() -> None:
        conn.execute(
            """
            INSERT INTO api_call_log (id, key_used, cache_hit, command, latency_ms, error)
            VALUES (NULL, ?, ?, ?, ?, ?)
            """,
            [key_used, int(cache_hit), command, latency_ms, error],
        )
        conn.commit()
    _db_write(_write)


def export_stats_csv(
    conn: sqlite3.Connection,
    path: str = "data/user_stats_backup.csv",
) -> None:
    """Export user_stats to CSV. Useful before wiping the DB."""
    rows = conn.execute(
        "SELECT user_id, username, rashi, boli_points, prediction_count FROM user_stats"
    ).fetchall()
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["user_id", "username", "rashi", "boli_points", "prediction_count"])
        writer.writerows(rows)
    logger.info("Exported %d user records to %s", len(rows), path)


def get_table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Return row counts for all tables. Used by /health command."""
    tables = ["predictions_cache", "user_stats", "user_prediction_history", "curse_logs", "daily_omens"]
    counts = {}
    for table in tables:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        counts[table] = row[0] if row else 0
    return counts


def get_health_stats(conn: sqlite3.Connection) -> dict:
    """Return a rich set of runtime statistics for the /health command."""
    stats: dict = {}

    # --- User activity ---
    stats["total_users"] = (
        conn.execute("SELECT COUNT(*) FROM user_stats").fetchone() or (0,)
    )[0]
    stats["active_today"] = (
        conn.execute(
            "SELECT COUNT(*) FROM user_stats WHERE DATE(last_seen) = DATE('now')"
        ).fetchone() or (0,)
    )[0]
    stats["active_week"] = (
        conn.execute(
            "SELECT COUNT(*) FROM user_stats WHERE last_seen >= datetime('now', '-7 days')"
        ).fetchone() or (0,)
    )[0]
    stats["total_boli_points"] = (
        conn.execute("SELECT COALESCE(SUM(boli_points), 0) FROM user_stats").fetchone() or (0,)
    )[0]
    top_row = conn.execute(
        "SELECT username, boli_points FROM user_stats ORDER BY boli_points DESC LIMIT 1"
    ).fetchone()
    stats["top_user"] = f"{top_row[0]} ({top_row[1]} pts)" if top_row else "N/A"

    # --- Prediction activity ---
    stats["predictions_today"] = (
        conn.execute(
            "SELECT COUNT(*) FROM user_prediction_history WHERE DATE(timestamp) = DATE('now')"
        ).fetchone() or (0,)
    )[0]
    cache_rows = conn.execute(
        "SELECT cache_type, COUNT(*) FROM predictions_cache GROUP BY cache_type ORDER BY cache_type"
    ).fetchall()
    stats["cache_by_type"] = {r[0]: r[1] for r in cache_rows}

    # --- Curse log ---
    stats["curses_today"] = (
        conn.execute(
            "SELECT COUNT(*) FROM curse_logs WHERE DATE(timestamp) = DATE('now')"
        ).fetchone() or (0,)
    )[0]
    stats["curses_total"] = (
        conn.execute("SELECT COUNT(*) FROM curse_logs").fetchone() or (0,)
    )[0]
    top_curse = conn.execute(
        "SELECT curse_used, COUNT(*) AS n FROM curse_logs GROUP BY curse_used ORDER BY n DESC LIMIT 1"
    ).fetchone()
    stats["top_curse"] = f'"{top_curse[0]}" × {top_curse[1]}' if top_curse else "N/A"

    # --- Active perks ---
    stats["active_perks"] = (
        conn.execute(
            "SELECT COUNT(*) FROM user_perks WHERE expires_at > CURRENT_TIMESTAMP"
        ).fetchone() or (0,)
    )[0]

    return stats
