import json
import sqlite3

import pytest

from navi.db.repos import counters, games, market
from navi.db.repos.content import (dialogue_exists, get_cached_prediction, get_last_n_predictions, get_score_comment,
                                   get_todays_user_prediction, save_movie_dialogue, save_prediction, save_score_comment,
                                   save_user_prediction)
from navi.db.repos.events import get_health_stats, get_table_counts, log_command_event, log_llm_call, log_session_event
from navi.db.repos.knowledge import get_random_knowledge_terms, seed_local_knowledge
from navi.db.repos.media import get_local_media, list_user_local_media, save_local_media
from navi.db.repos.perks import clear_perk, get_perk_expiry, grant_perk, has_active_perk
from navi.db.repos.permissions import grant, has_permission, list_permission, revoke
from navi.db.repos.points import (get_bless_leaderboard, get_curse_leaderboard, get_gift_daily_total,
                                  get_recent_partner_logs, partner_score_exists)
from navi.db.repos.settings import delete_setting, get_setting, load_overrides, set_setting
from navi.db.repos.users import (get_active_user_ids_previous_day, get_leaderboard, get_user_profile, get_user_strikes,
                                 increment_user_strikes, reset_all_strikes, upsert_user)
from navi.services import curse_game
from navi.services.points import add_experience, add_partner_points, award, set_user_points, update_boli_points


def ledger_total(db, uid, pool="native"):
    return db.execute("SELECT COALESCE(SUM(delta),0) FROM points_ledger WHERE user_id=? AND pool=?", [uid, pool]).fetchone()[0]


@pytest.fixture()
def users(db):
    for uid, name in ((1, "asha"), (2, "ben"), (3, "chitra")):
        upsert_user(db, uid, name)
    return db


# ------------------------------------------------------------------ points service

def test_award_changes_balance_xp_and_writes_one_ledger_row(users):
    assert award(users, 1, 10, 4, reason="slang", detail="chumma")
    row = users.execute("SELECT boli_points, experience FROM users WHERE user_id=1").fetchone()
    assert tuple(row) == (10, 4)
    led = users.execute("SELECT user_id, pool, delta, xp_delta, reason, detail FROM points_ledger").fetchall()
    assert [tuple(r) for r in led] == [(1, "native", 10, 4, "slang", "chumma")]


def test_negative_xp_is_ignored_and_zero_awards_are_not_logged(users):
    assert not add_experience(users, 1, -5, reason="x")
    assert not award(users, 1, 0, 0, reason="noop")
    assert users.execute("SELECT COUNT(*) FROM points_ledger").fetchone()[0] == 0
    assert award(users, 1, 0, 0, reason="history", log_only=True)       # history-only rows are allowed
    assert users.execute("SELECT COUNT(*) FROM points_ledger").fetchone()[0] == 1


def test_unknown_user_changes_nothing(db):
    assert update_boli_points(db, 404, 10, reason="x") is False
    assert db.execute("SELECT COUNT(*) FROM points_ledger").fetchone()[0] == 0


def test_ledger_always_reconciles_with_balances(users):
    update_boli_points(users, 1, 50, reason="a")
    update_boli_points(users, 1, -20, reason="b")
    award(users, 2, 7, 7, reason="c")
    for uid in (1, 2, 3):
        bal = users.execute("SELECT boli_points FROM users WHERE user_id=?", [uid]).fetchone()[0]
        assert ledger_total(users, uid) == bal


def test_failed_write_rolls_back_the_balance(users):
    """Balance and ledger row are one transaction: a duplicate partner ref must not move the balance."""
    assert add_partner_points(users, 1, 25, game_id="gameA", xp=3)
    assert not add_partner_points(users, 1, 25, game_id="gameA", xp=3)
    row = users.execute("SELECT partner_points, experience, boli_points FROM users WHERE user_id=1").fetchone()
    assert tuple(row) == (25, 3, 0)
    assert ledger_total(users, 1, "partner") == 25
    assert partner_score_exists(users, "gameA") and not partner_score_exists(users, "gameB")


def test_batch_partner_ids_count_as_the_game(users):
    add_partner_points(users, 1, 5, game_id="batch1:1")
    assert partner_score_exists(users, "batch1") and not partner_score_exists(users, "batch")


def test_recent_partner_logs(users):
    add_partner_points(users, 1, 9, game_id="g9", source_game="wordle", extra={"raw_points": 90})
    log = get_recent_partner_logs(users, 5)[0]
    assert (log["game_id"], log["username"], log["game_type"], log["raw_points"], log["boli_awarded"]) == ("g9", "asha", "wordle", 90, 9)


def test_set_user_points_records_the_difference(users):
    update_boli_points(users, 1, 30, reason="a")
    set_user_points(users, 1, "asha", 100, prediction_count=4, rashi="Mesham")
    p = get_user_profile(users, 1)
    assert (p["boli_points"], p["prediction_count"], p["rashi"]) == (100, 4, "Mesham")
    assert ledger_total(users, 1) == 100
    set_user_points(users, 50, "newbie", 5)
    assert get_user_profile(users, 50)["boli_points"] == 5 and ledger_total(users, 50) == 5


def test_gift_daily_total(users):
    award(users, 1, -30, reason="gift_sent", counterparty_id=2)
    award(users, 2, 30, reason="gift_received", counterparty_id=1)
    assert get_gift_daily_total(users, 1) == 30 and get_gift_daily_total(users, 2) == 0


# ------------------------------------------------------------------ curse game ledger helpers

def test_land_curse_protected_target_keeps_points_but_is_still_counted(users):
    curse_game.land_curse(users, 1, 2, damage=5, reward=5, word="kozhi", protected=True)
    assert get_user_profile(users, 2)["boli_points"] == 0 and get_user_profile(users, 1)["boli_points"] == 5
    assert get_curse_leaderboard(users)[0] == {"user_id": 2, "username": "ben", "hits": 1}


def test_land_and_backfire_and_self_curse_totals(users):
    curse_game.land_curse(users, 1, 2, 10, 10, "vattan", protected=False)
    assert (get_user_profile(users, 2)["boli_points"], get_user_profile(users, 1)["boli_points"]) == (-10, 10)
    curse_game.backfire_curse(users, 1, 2, 5, "kozhi")
    assert (get_user_profile(users, 2)["boli_points"], get_user_profile(users, 1)["boli_points"]) == (-5, 5)
    curse_game.self_curse(users, 3, 20, "dushtan")
    assert get_user_profile(users, 3)["boli_points"] == -20
    # only landed curses count on the "most cursed" board; backfires and self-curses do not
    assert [(r["user_id"], r["hits"]) for r in get_curse_leaderboard(users)] == [(2, 1)]


def test_bless_leaderboard_and_caster_share(users):
    curse_game.land_bless(users, 1, 2, 10, 2, "puli")
    curse_game.land_bless(users, 3, 3, 15, 4, "poli")          # self-bless: no caster row
    assert (get_user_profile(users, 2)["boli_points"], get_user_profile(users, 1)["boli_points"]) == (10, 2)
    assert get_user_profile(users, 3)["boli_points"] == 15 and get_user_profile(users, 3)["experience"] == 15
    assert sorted((r["user_id"], r["hits"]) for r in get_bless_leaderboard(users)) == [(2, 1), (3, 1)]


def test_passive_curse_word_counts_as_cursed(users):
    award(users, 1, 1, 1, reason="curse_word_said", detail="kozhi", log_only=True)
    assert get_curse_leaderboard(users)[0]["user_id"] == 1


# ------------------------------------------------------------------ users / counters / settings

def test_profile_and_leaderboard_total_both_pools(users):
    update_boli_points(users, 1, 10, reason="a")
    add_partner_points(users, 2, 50, game_id="x")
    top = get_leaderboard(users, 3)
    assert [(r["username"], r["boli_points"]) for r in top] == [("ben", 50), ("asha", 10), ("chitra", 0)]
    p = get_user_profile(users, 2)
    assert (p["boli_points"], p["external_boli"], p["total_boli_points"]) == (0, 50, 50)


def test_strikes(users):
    assert increment_user_strikes(users, 1) == 1 and increment_user_strikes(users, 1) == 2
    assert reset_all_strikes(users) == 1 and get_user_strikes(users, 1) == 0


def test_daily_counters(users):
    assert counters.get_daily_action_count(users, 1) == 0
    assert counters.increment_daily_action_count(users, 1) == 1 and counters.increment_daily_action_count(users, 1) == 2
    counters.increment_game_daily_count(users, 1, "flip"); counters.increment_game_daily_count(users, 1, "slots")
    assert counters.get_game_daily_count(users, 1, "flip") == 1 and counters.get_total_game_daily_count(users, 1) == 2
    counters.increment_gemini_game_count(users, 1, "navi_challenge")
    assert counters.get_total_game_daily_count(users, 1) == 2          # llm games are not part of the combined limit
    counters.reset_gambling_count(users, 1)
    assert counters.get_total_game_daily_count(users, 1) == 0 and counters.get_gemini_game_daily_count(users, 1, "navi_challenge") == 1
    counters.add_extra_actions(users, 1, 3); counters.decrement_extra_actions(users, 1)
    assert counters.get_extra_actions(users, 1) == 2


def test_settings_overrides_defaults_and_events(db):
    assert get_setting(db, "chance.passive_curse_reply") == 0.25 and get_setting(db, "curse_reply_chance") == 0.25   # old name works
    set_setting(db, "chance.passive_curse_reply", 0.5, updated_by=7)
    assert get_setting(db, "curse_reply_chance") == 0.5
    ev = db.execute("SELECT kind, user_id, name, detail FROM events WHERE kind='setting_change'").fetchone()
    assert (ev[0], ev[1], ev[2], json.loads(ev[3])) == ("setting_change", 7, "chance.passive_curse_reply", {"old": 0.25, "new": 0.5})
    assert delete_setting(db, "chance.passive_curse_reply", updated_by=7) and not delete_setting(db, "chance.passive_curse_reply")
    assert get_setting(db, "chance.passive_curse_reply") == 0.25
    with pytest.raises(KeyError):
        get_setting(db, "not_a_setting")
    set_setting(db, "feature.gambling", False)
    assert load_overrides(db) == {"feature.gambling": False}


# ------------------------------------------------------------------ content / media / market / games / events

def test_content_pool_and_history(db):
    for i in range(5):
        save_prediction(db, "navi", f"doom {{user}} {i}")
    save_prediction(db, "navi", "doom {user} 0")                          # exact duplicate ignored
    assert get_cached_prediction(db, "navi", min_count=6) is None and "doom" in get_cached_prediction(db, "navi", min_count=5)
    assert get_cached_prediction(db, "curse", min_count=1) is None
    upsert_user(db, 1, "a")
    save_user_prediction(db, 1, "first"); save_user_prediction(db, 1, "second")
    assert get_last_n_predictions(db, 1, 2) == ["second", "first"] and get_todays_user_prediction(db, 1) == "second"
    save_score_comment(db, "navi_challenge", 75, "c1"); save_score_comment(db, "navi_challenge", 79, "c2")
    assert get_score_comment(db, "navi_challenge", 71) in {"c1", "c2"} and get_score_comment(db, "navi_challenge", 10) is None
    save_movie_dialogue(db, "line"); save_movie_dialogue(db, "line")
    assert dialogue_exists(db, "line") and db.execute("SELECT COUNT(*) FROM content WHERE kind='movie_dialogue'").fetchone()[0] == 1


def test_knowledge_seed_and_pick(db):
    seed_local_knowledge(db)
    n = db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
    assert n > 50
    seed_local_knowledge(db)
    assert db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0] == n
    assert len(get_random_knowledge_terms(db, 3)) == 3


def test_media_roundtrip_and_perks(users):
    save_local_media(users, 1, "lol", "data/lol.png", "emoji")
    save_local_media(users, 1, "dance", "", "sticker", storage_type="app_emoji", discord_id="9", discord_name="dance", animated=True)
    assert get_local_media(users, "dance")["animated"] is True and get_local_media(users, "lol")["file_path"] == "data/lol.png"
    assert [e["shortcut"] for e in list_user_local_media(users, 1, media_type="sticker")] == ["dance"]
    grant_perk(users, 1, "curse_protection", 1)
    assert has_active_perk(users, 1, "curse_protection") and get_perk_expiry(users, 1, "curse_protection") is not None
    assert clear_perk(users, 1, "curse_protection") and not has_active_perk(users, 1, "curse_protection")


def test_market_and_holdings(users):
    from datetime import datetime, timedelta, timezone

    from navi.db.repos.market import _MARKET_SEED_ITEMS

    for item in _MARKET_SEED_ITEMS[:2]:
        users.execute("INSERT INTO market_items (item_id, name, emoji, base_price, current_price, volatility, description) VALUES (?,?,?,?,?,?,?)",
                      [item["item_id"], item["name"], item["emoji"], item["base_price"], item["current_price"], item["volatility"], item["description"]])
    users.commit()
    iid = _MARKET_SEED_ITEMS[0]["item_id"]
    market.buy_holding(users, 1, iid, 3, 80, datetime.now(timezone.utc) + timedelta(days=7))
    market.buy_holding(users, 1, iid, 1, 80, datetime.now(timezone.utc) - timedelta(days=1))   # already expired
    assert [h["quantity"] for h in market.get_user_holdings(users, 1)] == [3]
    assert [r["user_id"] for r in market.expire_stale_holdings(users)] == [1]
    hid = market.get_user_holding_for_item(users, 1, iid)[0]["id"]
    market.reduce_holding(users, hid, 3)
    assert market.get_user_holdings(users, 1) == []
    market.record_price_history(users, iid, 77, "2026-10-29 00:00:00")
    assert market.get_price_history(users, iid) == [{"date": "2026-10-29 00:00:00", "price": 77}]


def test_game_results_leaderboards(users):
    games.save_fff_result(users, "f1", 1, 7, "asha", 8, 10, 900, 20)
    games.save_fff_result(users, "f2", 3, 7, "chitra", 8, 10, 700, 20)
    games.save_fff_result(users, "f2", 3, 7, "chitra", 9, 10, 100, 20)       # duplicate game_id ignored
    games.save_fff_result(users, "f3", 2, 8, "ben", 5, 10, None, 5)
    assert [r["username"] for r in games.get_fff_leaderboard(users, 7, 10)] == ["chitra", "asha"]
    assert [r["username"] for r in games.get_fff_leaderboard(users, 0, 10, global_scope=True)] == ["chitra", "asha", "ben"]
    games.save_survival_result(users, "s1", 1, 7, "asha", 12, "hard", None, 30)
    games.save_survival_result(users, "s2", 1, 7, "asha", 20, "hard", "movies", 40)
    assert games.get_survival_personal_best(users, 1, "hard", None) == 12
    assert games.get_survival_personal_best(users, 1, "hard", "movies") == 20 and games.get_survival_personal_best(users, 1, "easy", None) == 0
    assert games.get_survival_leaderboard(users, 7, 5)[0]["streak"] == 20


def test_events_and_health(users):
    log_command_event(users, 1, "asha", "navi", subcommand="x", channel_id=5, guild_id=6, latency_ms=12)
    log_session_event(users, "start")
    log_llm_call(users, "gemini", "m", "qa", "ok", 3, 4, 99)
    assert dict(users.execute("SELECT kind, COUNT(*) FROM events GROUP BY kind")) == {"command": 1, "session": 1, "llm_call": 1}
    curse_game.land_curse(users, 1, 2, 5, 5, "kozhi", protected=False)
    stats = get_health_stats(users)
    assert stats["total_users"] == 3 and stats["curses_total"] == 1 and stats["top_curse"] == '"kozhi" × 1'
    assert set(get_table_counts(users)) >= {"users", "points_ledger", "content"}
    assert get_active_user_ids_previous_day(users) is not None


def test_permissions(users):
    grant(users, 2, "teach", granted_by=1)
    assert has_permission(users, 2, "teach") and list_permission(users, "teach") == [2]
    assert revoke(users, 2, "teach") and not revoke(users, 2, "teach")
