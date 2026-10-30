# navi/db/repos/events.py - moved from schema.py (no behaviour change)
from __future__ import annotations

import csv
import json
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
    """Record a single command invocation for usage analytics (events.kind = 'command')."""
    info = {k: v for k, v in (("sub", subcommand), ("cache", used_cache or None)) if v}
    detail = json.dumps(info) if info else None
    def _write() -> None:
        conn.execute(
            "INSERT INTO events (kind, user_id, guild_id, channel_id, name, detail, latency_ms)"
            " VALUES ('command', ?, ?, ?, ?, ?, ?)",
            [user_id, guild_id, channel_id, command, detail, latency_ms],
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
        conn.execute("INSERT INTO events (kind, name, detail) VALUES ('session', ?, ?)", [event_type, detail])
        conn.commit()
    _db_write(_write)


def log_llm_call(
    conn: sqlite3.Connection,
    provider: str,
    model: str,
    purpose: str,
    outcome: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int | None = None,
) -> None:
    """Record one LLM router decision (events.kind = 'llm_call')."""
    detail = json.dumps({"provider": provider, "model": model, "in": input_tokens, "out": output_tokens,
                         "outcome": outcome})
    def _write() -> None:
        conn.execute(
            "INSERT INTO events (kind, name, detail, latency_ms) VALUES ('llm_call', ?, ?, ?)",
            [purpose, detail, latency_ms],
        )
        conn.commit()
    _db_write(_write)


def count_llm_calls_today(conn: sqlite3.Connection) -> int:
    """How many events since IST midnight were real provider calls."""
    from datetime import datetime, timedelta, timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    midnight = datetime.now(ist).replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = midnight.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute(
        """
        SELECT COUNT(*) FROM events
        WHERE kind = 'llm_call' AND created_at >= ?
          AND json_extract(detail, '$.outcome') IN ('ok', 'safety', 'error', 'empty')
        """,
        [cutoff],
    ).fetchone()
    return int(row[0]) if row else 0


def export_stats_csv(
    conn: sqlite3.Connection,
    path: str = "data/user_stats_backup.csv",
) -> None:
    """Export users to CSV. Useful before wiping the DB."""
    rows = conn.execute(
        "SELECT user_id, display_name, rashi, boli_points, prediction_count FROM users"
    ).fetchall()
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["user_id", "username", "rashi", "boli_points", "prediction_count"])
        writer.writerows(rows)
    logger.info("Exported %d user records to %s", len(rows), path)


def get_table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Return row counts for the main tables. Used by /admin status."""
    tables = ["content", "users", "prediction_history", "points_ledger", "events"]
    counts = {}
    for table in tables:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        counts[table] = row[0] if row else 0
    return counts


def get_health_stats(conn: sqlite3.Connection) -> dict:
    """Return a rich set of runtime statistics for /admin status."""
    def one(sql: str, params: list | None = None):
        return (conn.execute(sql, params or []).fetchone() or (0,))[0]

    cursed = "('curse_received', 'curse_word_said')"
    stats: dict = {}
    # --- User activity ---
    stats["total_users"] = one("SELECT COUNT(*) FROM users")
    stats["active_today"] = one("SELECT COUNT(*) FROM users WHERE DATE(last_seen) = DATE('now')")
    stats["active_week"] = one("SELECT COUNT(*) FROM users WHERE last_seen >= datetime('now', '-7 days')")
    stats["total_boli_points"] = one("SELECT COALESCE(SUM(boli_points), 0) FROM users")
    top_row = conn.execute(
        "SELECT display_name, boli_points FROM users ORDER BY boli_points DESC, user_id ASC LIMIT 1"
    ).fetchone()
    stats["top_user"] = f"{top_row[0]} ({top_row[1]} pts)" if top_row else "N/A"
    # --- Prediction activity ---
    stats["predictions_today"] = one("SELECT COUNT(*) FROM prediction_history WHERE DATE(created_at) = DATE('now')")
    cache_rows = conn.execute(
        "SELECT kind, COUNT(*) FROM content WHERE status = 'active' GROUP BY kind ORDER BY kind"
    ).fetchall()
    stats["cache_by_type"] = {r[0]: r[1] for r in cache_rows}
    # --- Curse log ---
    stats["curses_today"] = one(
        f"SELECT COUNT(*) FROM points_ledger WHERE reason IN {cursed} AND DATE(created_at) = DATE('now')")
    stats["curses_total"] = one(f"SELECT COUNT(*) FROM points_ledger WHERE reason IN {cursed}")
    top_curse = conn.execute(
        f"SELECT detail, COUNT(*) AS n FROM points_ledger WHERE reason IN {cursed} AND detail IS NOT NULL "
        "GROUP BY detail ORDER BY n DESC, detail ASC LIMIT 1"
    ).fetchone()
    stats["top_curse"] = f'"{top_curse[0]}" × {top_curse[1]}' if top_curse else "N/A"
    # --- Active perks ---
    stats["active_perks"] = one("SELECT COUNT(*) FROM perks WHERE expires_at > CURRENT_TIMESTAMP")
    return stats


def llm_usage_today(conn: sqlite3.Connection) -> tuple[int, int, int]:
    """(provider calls, input tokens, output tokens) since IST midnight, from events kind='llm_call'."""
    from datetime import datetime, timedelta, timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    midnight = datetime.now(ist).replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = midnight.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(json_extract(detail, '$.in')), 0), COALESCE(SUM(json_extract(detail, '$.out')), 0)
        FROM events
        WHERE kind = 'llm_call' AND created_at >= ? AND json_extract(detail, '$.outcome') IN ('ok', 'safety', 'error', 'empty')
        """,
        [cutoff],
    ).fetchone()
    return int(row[0]), int(row[1]), int(row[2])
