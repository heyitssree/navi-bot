"""Characterises the two disagreeing sources of feature defaults (fixed in Phase 1/4)."""

import bot as navi


def test_in_memory_defaults_disable_llm_games():
    assert navi._FEATURE_DEFAULTS["feature_navi_challenge"] == 0
    assert navi._FEATURE_DEFAULTS["feature_type_race"] == 0


def test_found_not_fixed_db_seed_disagrees(db):
    seeded = dict(db.execute(
        "SELECT key, value_int FROM bot_config WHERE key IN ('feature_navi_challenge','feature_type_race')"))
    # Spec section 2.3: schema seeds 1 while bot.py defaults to 0.
    assert seeded == {"feature_navi_challenge": 1, "feature_type_race": 1}
