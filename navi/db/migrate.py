# navi/db/migrate.py - schema_version runner
#
# Migrations live in navi/db/migrations/ and are applied in numeric order:
#   m0001_baseline.py   -> module with apply(conn)
#   0002_v2.sql         -> plain SQL script (executed with executescript)
# Applied versions are recorded in schema_version. The baseline is idempotent, so databases that predate the
# runner simply get version 1 recorded on first start.

from __future__ import annotations

import importlib
import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger("navi.db.migrate")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_NAME_RE = re.compile(r"^(?:m)?(\d{4})_.+\.(py|sql)$")


def discover() -> list[tuple[int, Path]]:
    found = []
    for p in MIGRATIONS_DIR.iterdir():
        m = _NAME_RE.match(p.name)
        if m:
            found.append((int(m.group(1)), p))
    return sorted(found)


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def migrate(conn: sqlite3.Connection) -> int:
    """Apply every pending migration. Returns the resulting schema version."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.commit()
    done = current_version(conn)
    for version, path in discover():
        if version <= done:
            continue
        logger.info("Applying migration %s", path.name)
        if path.suffix == ".py":
            importlib.import_module(f"navi.db.migrations.{path.stem}").apply(conn)
        else:
            conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, datetime('now'))", [version])
        conn.commit()
        done = version
    return done
