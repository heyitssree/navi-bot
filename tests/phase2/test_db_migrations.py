import json
import sqlite3
from pathlib import Path

from navi.db.connection import init_db
from navi.db.migrate import current_version, discover, migrate

ROOT = Path(__file__).resolve().parents[2]


def _schema(conn):
    rows = sorted(tuple(r) for r in conn.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE name NOT IN ('schema_version') AND name NOT LIKE 'sqlite_%'"))
    return [list(r) for r in rows]


def test_baseline_schema_identical_to_pre_refactor_ddl(tmp_path):
    conn = init_db(tmp_path / "a.db")
    assert _schema(conn) == json.loads((ROOT / "tests/fixtures/baseline_schema.json").read_text())
    assert conn.execute("SELECT COUNT(*) FROM market_items").fetchone()[0] == 6  # seeded


def test_runner_records_version_and_is_idempotent(tmp_path):
    conn = init_db(tmp_path / "a.db")
    top = max(v for v, _ in discover())
    assert current_version(conn) == top
    assert migrate(conn) == top
    assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == len(discover())


def test_existing_pre_runner_database_gets_baseline_recorded(tmp_path):
    """A database created before the runner existed has no schema_version table."""
    path = tmp_path / "old.db"
    conn = init_db(path)
    conn.execute("DROP TABLE schema_version")
    conn.execute("UPDATE bot_config SET value_float = 0.77 WHERE key = 'curse_reply_chance'")
    conn.commit()
    conn.close()
    conn = init_db(path)
    assert current_version(conn) >= 1
    assert conn.execute("SELECT value_float FROM bot_config WHERE key='curse_reply_chance'").fetchone()[0] == 0.77


def test_dev_database_copy_migrates_without_data_loss(tmp_path):
    src = ROOT / "data/dev/navi_dev.db"
    if not src.exists():
        return
    dst = tmp_path / "copy.db"
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    s.backup(d)
    s.close()
    before = {t: d.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
              for (t,) in d.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    d.close()
    conn = init_db(dst)
    for t, n in before.items():
        assert conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] >= n, t
