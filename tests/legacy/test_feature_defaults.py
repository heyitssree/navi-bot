"""Feature defaults now come from one place: the settings registry (Phase 3)."""
from navi.db.repos.settings import get_config_int
from navi.settings.registry import BY_KEY, resolve
from navi.settings.store import FeatureFlags


def test_llm_games_are_disabled_by_default():
    assert resolve("feature_navi_challenge").default is False
    assert resolve("feature_type_race").default is False


def test_fresh_database_agrees_with_registry(db):
    """Phase 0 'Found, not fixed': the DB seed used to say 1 while bot.py said 0. No seed rows exist any more."""
    assert get_config_int(db, "feature_navi_challenge", 1) == 0
    assert get_config_int(db, "feature_type_race", 1) == 0
    flags = FeatureFlags()
    flags.bind(db)
    flags.load()
    assert flags.feat("feature_type_race") is False and flags.feat("feature_curses") is True


def test_every_default_is_valid_for_its_kind():
    for s in BY_KEY.values():
        if s.kind == "bool":
            assert isinstance(s.default, bool)
        if s.kind == "float" and s.min is not None:
            assert s.min <= s.default <= s.max
