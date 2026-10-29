# navi/db/connection.py - SQLite connection, PRAGMAs and the single write-retry helper

from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Callable, TypeVar

logger = logging.getLogger("navi.db")

_T = TypeVar("_T")

# ---------------------------------------------------------------------------
# DB write retry with exponential backoff (handles "database is locked")
# ---------------------------------------------------------------------------

_DB_RETRY_ATTEMPTS = 5
_DB_RETRY_BASE_DELAY = 0.1  # seconds


def _db_write(fn: Callable[[], _T]) -> _T:
    """Execute a SQLite write callable with exponential backoff on lock errors.

    Retries up to _DB_RETRY_ATTEMPTS times (0.1s, 0.2s, 0.4s, 0.8s, 1.6s).
    Re-raises the last exception if all attempts fail.
    """
    last_exc: Exception | None = None
    for attempt in range(_DB_RETRY_ATTEMPTS):
        try:
            result = fn()
            return result
        except Exception as exc:
            msg = str(exc).lower()
            if "database is locked" not in msg:
                raise
            last_exc = exc
            delay = _DB_RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                "SQLite locked (attempt %d/%d) — retrying in %.2fs", attempt + 1, _DB_RETRY_ATTEMPTS, delay
            )
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]


_db_path_env = os.getenv("DB_PATH")
_default_db = Path("data") / "navi.db"
# Databases created before the Navi rename used this file name; keep using it if it still exists.
_legacy_db = Path("data") / ("astro" + "_bot.db")
if _db_path_env:
    DB_PATH = Path(_db_path_env)
elif not _default_db.exists() and _legacy_db.exists():
    DB_PATH = _legacy_db
else:
    DB_PATH = _default_db


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the database with the bot's PRAGMAs. Returns a connection to reuse for the bot's lifetime.

    WAL mode enables crash-safe concurrent reads without locking corruption.
    """
    target = Path(path) if path is not None else DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(target),
        check_same_thread=False,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: Path | None = None) -> sqlite3.Connection:
    """Open the database and bring the schema up to date (see navi.db.migrate)."""
    from navi.db.migrate import migrate

    conn = connect(path)
    migrate(conn)
    logger.info("SQLite initialised at %s", path or DB_PATH)
    return conn
