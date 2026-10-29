# navi/db/repos/media.py - moved from schema.py (no behaviour change)
from __future__ import annotations

import logging
import sqlite3

from navi.db.connection import _db_write

logger = logging.getLogger("navi.db.media")


def save_local_media(
    conn: sqlite3.Connection,
    user_id: int,
    shortcut: str,
    file_path: str,
    media_type: str,
    source_url: str | None = None,
    storage_type: str = "local",
    discord_id: str | None = None,
    discord_name: str | None = None,
    animated: bool = False,
) -> None:
    """Insert a local media entry, replacing any existing entry for the same shortcut."""
    def _write() -> None:
        conn.execute(
            """
            INSERT INTO local_media
                (shortcut, user_id, file_path, media_type, source_url, created_at,
                 storage_type, discord_id, discord_name, animated)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?)
            ON CONFLICT (shortcut) DO UPDATE SET
                user_id = excluded.user_id,
                file_path = excluded.file_path,
                media_type = excluded.media_type,
                source_url = excluded.source_url,
                created_at = CURRENT_TIMESTAMP,
                storage_type = excluded.storage_type,
                discord_id = excluded.discord_id,
                discord_name = excluded.discord_name,
                animated = excluded.animated
            """,
            [shortcut, user_id, file_path, media_type, source_url,
             storage_type, discord_id, discord_name, int(animated)],
        )
        conn.commit()
    _db_write(_write)


def get_local_media(
    conn: sqlite3.Connection,
    shortcut: str,
) -> dict | None:
    """Return local media entry for the given shortcut, or None if not found."""
    row = conn.execute(
        """SELECT shortcut, user_id, file_path, media_type, source_url, created_at,
                  storage_type, discord_id, discord_name, animated
           FROM local_media WHERE shortcut = ?""",
        [shortcut],
    ).fetchone()
    if not row:
        return None
    return {
        "shortcut": row[0],
        "user_id": row[1],
        "file_path": row[2],
        "media_type": row[3],
        "source_url": row[4],
        "created_at": row[5],
        "storage_type": row[6] or "local",
        "discord_id": row[7],
        "discord_name": row[8],
        "animated": bool(row[9]) if row[9] is not None else False,
    }


def get_user_local_media_count(conn: sqlite3.Connection, user_id: int) -> int:
    """Return how many local media entries the user has saved."""
    row = conn.execute(
        "SELECT COUNT(*) FROM local_media WHERE user_id = ?", [user_id]
    ).fetchone()
    return row[0] if row else 0


def get_global_local_media_count(conn: sqlite3.Connection) -> int:
    """Return total number of local media entries stored globally."""
    row = conn.execute("SELECT COUNT(*) FROM local_media").fetchone()
    return row[0] if row else 0


def list_user_local_media(
    conn: sqlite3.Connection,
    user_id: int,
    media_type: str | None = None,
) -> list[dict]:
    """Return all local media entries owned by a user, newest first.

    Includes storage_type, discord_id, discord_name, and animated so callers
    can build emoji previews without a second per-row DB fetch.
    """
    if media_type:
        rows = conn.execute(
            """SELECT shortcut, file_path, media_type, created_at,
                      storage_type, discord_id, discord_name, animated
               FROM local_media
               WHERE user_id = ? AND media_type = ?
               ORDER BY created_at DESC""",
            [user_id, media_type],
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT shortcut, file_path, media_type, created_at,
                      storage_type, discord_id, discord_name, animated
               FROM local_media
               WHERE user_id = ?
               ORDER BY created_at DESC""",
            [user_id],
        ).fetchall()
    return [
        {
            "shortcut":     r[0],
            "file_path":    r[1],
            "media_type":   r[2],
            "created_at":   r[3],
            "storage_type": r[4] or "local",
            "discord_id":   r[5],
            "discord_name": r[6],
            "animated":     bool(r[7]) if r[7] is not None else False,
        }
        for r in rows
    ]


def delete_local_media(conn: sqlite3.Connection, shortcut: str) -> bool:
    """Delete a local media entry by shortcut. Returns True if a row was deleted."""
    existing = conn.execute(
        "SELECT 1 FROM local_media WHERE shortcut = ?", [shortcut]
    ).fetchone()
    if not existing:
        return False
    _db_write(lambda: (
        conn.execute("DELETE FROM local_media WHERE shortcut = ?", [shortcut]),
        conn.commit(),
    ))
    return True


_APP_EMOJI_LIMIT = 2000


_APP_EMOJI_EVICT_THRESHOLD = 1900


def save_app_emoji(
    conn: sqlite3.Connection,
    emoji_id: str,
    name: str,
    animated: bool = False,
    original_id: str | None = None,
) -> None:
    """Record a newly uploaded application emoji in the DB."""
    def _write() -> None:
        conn.execute(
            """
            INSERT INTO app_emojis (emoji_id, name, last_used, original_id, animated)
            VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)
            ON CONFLICT (emoji_id) DO UPDATE SET
                name = excluded.name,
                last_used = CURRENT_TIMESTAMP,
                animated = excluded.animated
            """,
            [emoji_id, name, original_id, int(animated)],
        )
        conn.commit()
    _db_write(_write)


def get_oldest_app_emoji(conn: sqlite3.Connection) -> dict | None:
    """Return the least-recently-used application emoji record, or None if none exist."""
    row = conn.execute(
        "SELECT emoji_id, name, animated FROM app_emojis ORDER BY last_used ASC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    return {"emoji_id": row[0], "name": row[1], "animated": bool(row[2])}


def delete_app_emoji_record(conn: sqlite3.Connection, emoji_id: str) -> None:
    """Remove an application emoji record from the DB."""
    _db_write(lambda: (
        conn.execute("DELETE FROM app_emojis WHERE emoji_id = ?", [emoji_id]),
        conn.commit(),
    ))


def update_app_emoji_last_used(conn: sqlite3.Connection, emoji_id: str) -> None:
    """Bump the last_used timestamp for an application emoji (LRU refresh)."""
    _db_write(lambda: (
        conn.execute(
            "UPDATE app_emojis SET last_used = CURRENT_TIMESTAMP WHERE emoji_id = ?",
            [emoji_id],
        ),
        conn.commit(),
    ))


def count_app_emojis(conn: sqlite3.Connection) -> int:
    """Return the number of application emojis tracked in the DB."""
    row = conn.execute("SELECT COUNT(*) FROM app_emojis").fetchone()
    return row[0] if row else 0
