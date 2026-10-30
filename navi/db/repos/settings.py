# navi/db/repos/settings.py - raw access to the settings table (JSON overrides; defaults live in the registry).
# Application code uses navi.settings.store.Settings (ctx.settings), which validates values and keeps a cache.

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


def delete_setting(conn: sqlite3.Connection, key: str, updated_by: int | None = None) -> bool:
    """Remove an override so the registry default applies again. Returns True if an override existed."""
    setting = resolve(key)
    old = get_setting(conn, setting.key)

    def _write() -> bool:
        cur = conn.execute("DELETE FROM settings WHERE key = ?", [setting.key])
        if cur.rowcount:
            conn.execute(
                "INSERT INTO events (kind, user_id, name, detail) VALUES ('setting_change', ?, ?, ?)",
                [updated_by, setting.key, json.dumps({"old": old, "new": setting.default, "reset": True})],
            )
        conn.commit()
        return cur.rowcount > 0

    return _db_write(_write)


def load_overrides(conn: sqlite3.Connection) -> dict[str, object]:
    """Every stored override keyed by registry key (unknown or unparsable rows are skipped with a warning)."""
    out: dict[str, object] = {}
    for key, raw in conn.execute("SELECT key, value FROM settings"):
        try:
            out[resolve(key).key] = json.loads(raw)
        except KeyError:
            logger.warning("Ignoring unknown stored setting %r", key)
        except ValueError:
            logger.warning("Bad JSON for stored setting %r", key)
    return out
