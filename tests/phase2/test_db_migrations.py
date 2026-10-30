import json
import sqlite3
from pathlib import Path

import pytest

from navi.db.connection import LegacyDatabaseError, init_db
from navi.db.migrate import current_version, discover, migrate

ROOT = Path(__file__).resolve().parents[2]
SPEC_TABLES = {"users", "daily_counters", "points_ledger", "holdings", "perks", "media", "app_emojis", "game_results",
               "prediction_history", "events", "content", "knowledge", "market_items", "market_prices", "settings",
               "permissions"}


def _schema(conn):
    rows = sorted(tuple(r) for r in conn.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE name NOT IN ('schema_version') AND name NOT LIKE 'sqlite_%'"))
    return [list(r) for r in rows]


def test_v2_has_exactly_the_sixteen_spec_tables(tmp_path):
    conn = init_db(tmp_path / "a.db")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    assert tables - {"schema_version"} == SPEC_TABLES


def test_schema_snapshot_guards_accidental_ddl_changes(tmp_path):
    conn = init_db(tmp_path / "a.db")
    assert _schema(conn) == json.loads((ROOT / "tests/fixtures/v2_schema.json").read_text())
    assert conn.execute("SELECT COUNT(*) FROM market_items").fetchone()[0] == 0   # seeded at startup, not by DDL


def test_connection_pragmas(tmp_path):
    conn = init_db(tmp_path / "a.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1   # NORMAL


def test_runner_records_version_and_is_idempotent(tmp_path):
    conn = init_db(tmp_path / "a.db")
    top = max(v for v, _ in discover())
    assert current_version(conn) == top
    assert migrate(conn) == top
    assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == len(discover())


def test_reopening_keeps_data(tmp_path):
    path = tmp_path / "a.db"
    conn = init_db(path)
    conn.execute("INSERT INTO users (user_id, display_name) VALUES (1, 'a')")
    conn.commit()
    conn.close()
    assert init_db(path).execute("SELECT display_name FROM users").fetchone()[0] == "a"


def test_pre_v2_database_is_refused_with_instructions(tmp_path):
    from tools.legacy_schema import apply

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    apply(old)
    old.close()
    with pytest.raises(LegacyDatabaseError, match="migrate_v2"):
        init_db(path)
