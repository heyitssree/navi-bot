# navi/db/repos/settings.py - moved from schema.py (no behaviour change)
from __future__ import annotations

import logging
import sqlite3

from navi.db.connection import _db_write

logger = logging.getLogger("navi.db.settings")


def get_config_float(conn: sqlite3.Connection, key: str, default: float) -> float:
    row = conn.execute("SELECT value_float FROM bot_config WHERE key = ?", [key]).fetchone()
    return float(row[0]) if row and row[0] is not None else default


def get_config_int(conn: sqlite3.Connection, key: str, default: int) -> int:
    row = conn.execute("SELECT value_int FROM bot_config WHERE key = ?", [key]).fetchone()
    return int(row[0]) if row and row[0] is not None else default


def set_config_float(conn: sqlite3.Connection, key: str, value: float) -> None:
    _db_write(lambda: (
        conn.execute("UPDATE bot_config SET value_float = ? WHERE key = ?", [value, key]),
        conn.commit(),
    ))


def set_config_int(conn: sqlite3.Connection, key: str, value: int) -> None:
    _db_write(lambda: (
        conn.execute("UPDATE bot_config SET value_int = ? WHERE key = ?", [value, key]),
        conn.commit(),
    ))


def get_config_str(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value_str FROM bot_config WHERE key = ?", [key]).fetchone()
    return str(row[0]) if row and row[0] is not None else default


def set_config_str(conn: sqlite3.Connection, key: str, value: str) -> None:
    _db_write(lambda: (
        conn.execute(
            "INSERT INTO bot_config (key, value_str) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value_str = excluded.value_str",
            [key, value],
        ),
        conn.commit(),
    ))


def get_all_configs(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT key, value_str, value_float, value_int FROM bot_config").fetchall()
    config = {}
    for r in rows:
        key = r[0]
        if r[2] is not None:
            config[key] = r[2]
        elif r[3] is not None:
            config[key] = r[3]
        else:
            config[key] = r[1]
    return config


def get_testing_guilds(conn: sqlite3.Connection) -> set[int]:
    """Return the set of guild IDs with testing mode enabled."""
    rows = conn.execute("SELECT guild_id FROM testing_guilds").fetchall()
    return {int(r[0]) for r in rows}


def set_testing_guild(conn: sqlite3.Connection, guild_id: int, enabled: bool) -> None:
    """Enable or disable testing mode for a guild."""
    if enabled:
        _db_write(lambda: (
            conn.execute("INSERT OR IGNORE INTO testing_guilds (guild_id) VALUES (?)", [guild_id]),
            conn.commit(),
        ))
    else:
        _db_write(lambda: (
            conn.execute("DELETE FROM testing_guilds WHERE guild_id = ?", [guild_id]),
            conn.commit(),
        ))
