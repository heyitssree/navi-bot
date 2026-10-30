# navi/db/repos/settings.py - JSON overrides in the settings table (defaults live in the registry)
#
# get_config_*/set_config_* keep their old signatures for the existing call sites; keys may be registry keys or old
# bot_config names (resolved through the registry, unknown keys raise). The default argument is ignored: the
# registry default is the single source of truth. Writes are upserts (the old UPDATE-only version silently did
# nothing for rows that had never been seeded).

from __future__ import annotations

import json
import logging
import sqlite3

from navi.db.connection import _db_write
from navi.settings.registry import resolve

logger = logging.getLogger("navi.db.settings")


def get_setting(conn: sqlite3.Connection, key: str):
    """Return the stored override for a setting, or its registry default."""
    setting = resolve(key)
    row = conn.execute("SELECT value FROM settings WHERE key = ?", [setting.key]).fetchone()
    if row is None:
        return setting.default
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        logger.warning("Bad JSON in settings[%s]; using default", setting.key)
        return setting.default


def set_setting(conn: sqlite3.Connection, key: str, value, updated_by: int | None = None) -> None:
    """Store an override (JSON) and record a setting_change event with the old and new value."""
    setting = resolve(key)
    old = get_setting(conn, setting.key)

    def _write() -> None:
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_by, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_by = excluded.updated_by,
                                            updated_at = CURRENT_TIMESTAMP
            """,
            [setting.key, json.dumps(value), updated_by],
        )
        conn.execute(
            "INSERT INTO events (kind, user_id, name, detail) VALUES ('setting_change', ?, ?, ?)",
            [updated_by, setting.key, json.dumps({"old": old, "new": value})],
        )
        conn.commit()

    _db_write(_write)


def get_config_float(conn: sqlite3.Connection, key: str, default: float = 0.0) -> float:
    return float(get_setting(conn, key))


def get_config_int(conn: sqlite3.Connection, key: str, default: int = 0) -> int:
    return int(get_setting(conn, key))


def get_config_str(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    return str(get_setting(conn, key))


def set_config_float(conn: sqlite3.Connection, key: str, value: float) -> None:
    set_setting(conn, key, float(value))


def set_config_int(conn: sqlite3.Connection, key: str, value: int) -> None:
    setting = resolve(key)
    set_setting(conn, key, bool(value) if setting.kind == "bool" else int(value))


def set_config_str(conn: sqlite3.Connection, key: str, value: str) -> None:
    set_setting(conn, key, str(value))


def get_all_configs(conn: sqlite3.Connection) -> dict:
    """Effective values of every non-hidden setting (override or default), keyed by registry key."""
    from navi.settings.registry import SETTINGS

    return {s.key: get_setting(conn, s.key) for s in SETTINGS if not s.hidden}


def get_testing_guilds(conn: sqlite3.Connection) -> set[int]:
    """Return the set of guild IDs with testing mode enabled."""
    return {int(g) for g in get_setting(conn, "system.testing_guilds")}


def set_testing_guild(conn: sqlite3.Connection, guild_id: int, enabled: bool) -> None:
    """Enable or disable testing mode for a guild."""
    guilds = get_testing_guilds(conn)
    if enabled:
        guilds.add(int(guild_id))
    else:
        guilds.discard(int(guild_id))
    set_setting(conn, "system.testing_guilds", sorted(guilds))
