import json
import sqlite3

import pytest

from navi.db.connection import init_db
from tests.phase3.legacy_fixture import build
from tools import migrate_v2


@pytest.fixture()
def migrated(tmp_path):
    src = build(tmp_path / "old.db")
    before = src.read_bytes()
    report = migrate_v2.run(src, tmp_path / "v2" / "navi.db", tmp_path / "v2" / "privacy.db")
    assert src.read_bytes() == before        # the source is never modified
    old = sqlite3.connect(src)
    new = sqlite3.connect(tmp_path / "v2" / "navi.db")
    return report, old, new, tmp_path


def test_all_invariants_hold(migrated):
    report, *_ = migrated
    assert report.failures == []


def test_balances_xp_strikes_and_counts_identical(migrated):
    _, old, new, _ = migrated
    assert {r[0]: r[1:] for r in new.execute("SELECT user_id, boli_points, experience, strikes, prediction_count FROM users WHERE user_id <= 4")} == \
        {r[0]: r[1:] for r in old.execute("SELECT user_id, boli_points, experience, strikes, prediction_count FROM user_stats")}
    assert new.execute("SELECT partner_points FROM users WHERE user_id=1").fetchone()[0] == 40     # 50 - 10
    assert new.execute("SELECT partner_points FROM users WHERE user_id=3").fetchone()[0] == 30
    assert new.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 6                            # 4 + two log-only users


def test_ledger_sums_equal_balances_and_has_opening_rows(migrated):
    _, _, new, _ = migrated
    for uid, boli, partner in new.execute("SELECT user_id, boli_points, partner_points FROM users"):
        sums = dict(new.execute("SELECT pool, SUM(delta) FROM points_ledger WHERE user_id=? GROUP BY pool", [uid]))
        assert sums.get("native", 0) == boli and sums.get("partner", 0) == partner
    assert new.execute("SELECT COUNT(*) FROM points_ledger WHERE reason='opening_balance'").fetchone()[0] == 12


def test_history_rows(migrated):
    _, _, new, _ = migrated
    q = lambda sql, *a: new.execute(sql, a).fetchall()   # noqa: E731
    assert q("SELECT user_id, delta, counterparty_id FROM points_ledger WHERE reason='gift_sent' ORDER BY id") == [(3, -40, 1), (1, -5, 2), (3, -9, 77)]
    assert q("SELECT user_id, delta FROM points_ledger WHERE reason='gift_received' ORDER BY id") == [(1, 40), (2, 5)]    # the received half of the gift to unknown user 77 is skipped
    partner = q("SELECT ref, delta, pool FROM points_ledger WHERE reason='partner_award' ORDER BY id")
    assert ("g1", 50, "partner") in partner and ("g2", -10, "partner") in partner and ("g3:3", 30, "partner") in partner
    assert ("g5", 0, "partner") in partner                      # score-log row without points row: history only
    assert all(r[0] != "g4" for r in partner)                   # user 99 has no profile
    detail = json.loads(q("SELECT detail FROM points_ledger WHERE ref='g1'")[0][0])
    assert detail == {"game_type": "wordle", "raw_points": 50, "guild_id": 7}
    # curse/bless logs: delta 0, word in detail, legacy classification
    kinds = dict(q("SELECT detail, reason FROM points_ledger WHERE reason LIKE 'curse%'"))
    assert kinds["backfire_vattan"] == "curse_backfire" and kinds["proxy_navi_self"] == "curse_self"
    assert kinds["madiyan"] == kinds["potion_vazha"] == kinds["potion_backfire_oolan"] == "curse_received"
    assert q("SELECT COUNT(*) FROM points_ledger WHERE reason LIKE 'curse%' AND delta != 0") == [(0,)]
    assert q("SELECT COUNT(*) FROM points_ledger WHERE reason='bless_received'") == [(4,)]


def test_other_tables(migrated):
    _, old, new, _ = migrated
    for o, n in (("user_holdings", "holdings"), ("user_perks", "perks"), ("local_media", "media"), ("local_knowledge", "knowledge"),
                 ("market_items", "market_items"), ("market_price_history", "market_prices"), ("app_emojis", "app_emojis"),
                 ("user_prediction_history", "prediction_history")):
        assert old.execute(f"SELECT COUNT(*) FROM {o}").fetchone() == new.execute(f"SELECT COUNT(*) FROM {n}").fetchone(), o
    assert new.execute("SELECT COUNT(*) FROM game_results").fetchone()[0] == 6
    assert new.execute("SELECT game, score, json_extract(details,'$.avg_response_ms') FROM game_results WHERE game_id='f2'").fetchone() == ("fff", 8, 700)
    assert new.execute("SELECT location, storage_type, animated, discord_id FROM media WHERE shortcut='dance'").fetchone() == ("", "app_emoji", 1, "123")
    assert dict(new.execute("SELECT counter, value FROM daily_counters WHERE user_id=1")) == {
        "cosmic_action": 7, "refill": 1, "game:flip": 3, "game:slots": 2, "llm_game:navi_challenge": 2}
    kinds = dict(new.execute("SELECT kind, COUNT(*) FROM content GROUP BY kind"))
    assert kinds == {"prediction": 2, "curse_back": 1, "score_comment": 1, "movie_dialogue": 1}
    assert new.execute("SELECT key FROM content WHERE kind='score_comment'").fetchone()[0] == "navi_challenge:70"
    assert dict(new.execute("SELECT kind, COUNT(*) FROM events GROUP BY kind")) == {"command": 1, "session": 1, "llm_call": 1}


def test_settings_mapped_through_the_registry(migrated):
    _, _, new, _ = migrated
    s = {k: json.loads(v) for k, v in new.execute("SELECT key, value FROM settings")}
    assert s["chance.passive_curse_reply"] == 0.4 and s["chance.backfire_mild"] == 0.3
    assert s["feature.gambling"] is False and s["state.lucky_draw_last_date"] == "2026-10-29"
    assert s["system.testing_guilds"] == [555]
    assert "feature.navi_challenge" not in s and "feature.type_race" not in s       # seed drift: defaults win
    assert not any(k in s for k in ("WEATHER_ALERT_TIME", "reversal_chance_owner"))


def test_privacy_db_created_empty(migrated):
    *_, tmp = migrated
    p = sqlite3.connect(tmp / "v2" / "privacy.db")
    assert p.execute("SELECT COUNT(*) FROM privacy_state").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError):
        p.execute("INSERT INTO privacy_state VALUES (1, 'maybe', 'now')")


def test_result_is_a_working_v2_database(migrated):
    *_, tmp = migrated
    conn = init_db(tmp / "v2" / "navi.db")        # the bot can open it (no legacy guard, no pending migrations)
    from navi.db.repos.users import get_leaderboard

    assert get_leaderboard(conn, 3)[0]["username"] == "chitra"


def test_refuses_to_overwrite_and_unknown_config_key_fails_loudly(tmp_path):
    src = build(tmp_path / "old.db")
    migrate_v2.run(src, tmp_path / "a.db", tmp_path / "p.db")
    with pytest.raises(migrate_v2.MigrationError, match="already exists"):
        migrate_v2.run(src, tmp_path / "a.db", tmp_path / "p2.db")
    c = sqlite3.connect(src)
    c.execute("INSERT INTO bot_config (key, value_int) VALUES ('mystery_knob', 1)")
    c.commit(); c.close()
    with pytest.raises(migrate_v2.MigrationError, match="mystery_knob"):
        migrate_v2.run(src, tmp_path / "b.db", tmp_path / "p3.db")
    assert not (tmp_path / "b.db").exists()          # a failed migration leaves no half-written file


def test_verify_detects_tampering(migrated):
    _, old, new, _ = migrated
    new.execute("UPDATE users SET boli_points = boli_points + 1 WHERE user_id = 1")
    failures = migrate_v2.verify(old, new)
    assert any("user 1" in f for f in failures)


def test_non_legacy_source_is_rejected(tmp_path):
    v2 = tmp_path / "x.db"
    init_db(v2).close()
    with pytest.raises(migrate_v2.MigrationError, match="not a pre-v2"):
        migrate_v2.run(v2, tmp_path / "y.db", tmp_path / "py.db")
