import json
import re
from pathlib import Path

from navi.db.repos.users import upsert_user
from navi.services.points import award
from navi.services.retention import run_retention
from navi.settings.store import Settings


def _age(db, table, days, where="1=1", column="created_at"):
    db.execute(f"UPDATE {table} SET {column} = datetime('now', '-{days} days') WHERE {where}")
    db.commit()


def test_events_older_than_90_days_are_deleted(db):
    db.execute("INSERT INTO events (kind, name) VALUES ('command', 'old'), ('command', 'new')")
    _age(db, "events", 91, "name = 'old'")
    assert run_retention(db)["events"] == 1
    assert [r[0] for r in db.execute("SELECT name FROM events")] == ["new"]


def test_prediction_history_keeps_newest_20_per_user(db):
    for uid in (1, 2):
        upsert_user(db, uid, f"u{uid}")
    for i in range(25):
        db.execute("INSERT INTO prediction_history (user_id, text, created_at) VALUES (1, ?, datetime('now', ?))", [f"p{i}", f"-{100 - i} minutes"])
    db.execute("INSERT INTO prediction_history (user_id, text) VALUES (2, 'only')")
    db.commit()
    assert run_retention(db)["prediction_history"] == 5
    kept = [r[0] for r in db.execute("SELECT text FROM prediction_history WHERE user_id = 1 ORDER BY created_at")]
    assert kept == [f"p{i}" for i in range(5, 25)]
    assert db.execute("SELECT COUNT(*) FROM prediction_history WHERE user_id = 2").fetchone()[0] == 1


def test_daily_counters_older_than_14_days_are_deleted(db):
    db.execute("INSERT INTO daily_counters VALUES (1, date('now', '-15 days'), 'cosmic_action', 3), (1, date('now', '-13 days'), 'cosmic_action', 2)")
    db.commit()
    assert run_retention(db)["daily_counters"] == 1


def test_ledger_compaction_keeps_sums_and_balances(db):
    upsert_user(db, 1, "a"); upsert_user(db, 2, "b")
    for i in range(10):
        award(db, 1, 2, 1, reason="slang")
        award(db, 1, -1, reason="game", detail="flip:bet")
    award(db, 1, 5, reason="curse_cast")
    award(db, 2, 4, 4, reason="slang")
    award(db, 1, 3, reason="slang")                                         # recent: untouched
    db.execute("UPDATE points_ledger SET created_at = datetime('now', '-200 days') WHERE id <= 20 OR user_id = 2")
    db.commit()
    before = {u: db.execute("SELECT SUM(delta), SUM(xp_delta) FROM points_ledger WHERE user_id=?", [u]).fetchone() for u in (1, 2)}
    assert run_retention(db)["ledger_compacted"] == 18
    after = {u: db.execute("SELECT SUM(delta), SUM(xp_delta) FROM points_ledger WHERE user_id=?", [u]).fetchone() for u in (1, 2)}
    assert before == after
    rolled = db.execute("SELECT user_id, reason, delta, xp_delta, detail FROM points_ledger WHERE detail LIKE '%rollup%' ORDER BY user_id, reason").fetchall()
    assert [(r[0], r[1], r[2], r[3], json.loads(r[4])["rollup"]) for r in rolled] == [(1, "game", -10, 0, 10), (1, "slang", 20, 10, 10)]
    assert db.execute("SELECT COUNT(*) FROM points_ledger WHERE reason='curse_cast'").fetchone()[0] == 1   # never compacted
    for uid in (1, 2):
        bal = db.execute("SELECT boli_points FROM users WHERE user_id=?", [uid]).fetchone()[0]
        assert db.execute("SELECT SUM(delta) FROM points_ledger WHERE user_id=?", [uid]).fetchone()[0] == bal
    assert run_retention(db)["ledger_compacted"] == 0                       # idempotent


def test_settings_cache_loads_overrides_and_persists(db):
    flags = Settings(); flags.bind(db)
    assert flags.get("feature.curses") and not flags.get("system.killswitch")
    flags.set("system.killswitch", True, by=9)
    assert flags.get("system.killswitch")
    other = Settings(); other.bind(db); other.load()
    assert other.get("system.killswitch") is True and other.get("chance.kochi_reply") == 0.28
    assert db.execute("SELECT updated_by FROM settings WHERE key='system.killswitch'").fetchone()[0] == 9


def test_only_the_points_repo_writes_balance_columns():
    """No SQL outside repos/points.py may update boli_points, partner_points or experience."""
    pattern = re.compile(r"(boli_points|partner_points|experience)\s*=\s*(?!excluded)", re.I)
    offenders = []
    for path in Path("navi").rglob("*.py"):
        if path.as_posix().endswith(("db/repos/points.py", "db/migrations/__init__.py")):
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"UPDATE\s+users\s+SET[^\"']*(boli_points|partner_points|experience)\b", line, re.I):
                offenders.append(f"{path}:{n}")
    assert not offenders, offenders
