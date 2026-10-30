"""Feature defaults now come from one place: the settings registry (Phase 3)."""
from navi.settings.registry import BY_KEY, resolve
from navi.settings.store import Settings


def test_llm_games_are_disabled_by_default():
    assert resolve("feature_navi_challenge").default is False
    assert resolve("feature_type_race").default is False


def test_fresh_database_agrees_with_registry(db):
    """Phase 0 'Found, not fixed': the DB seed used to say 1 while bot.py said 0. No seed rows exist any more."""
    flags = Settings()
    flags.bind(db)
    flags.load()
    assert flags.get("feature.navi_challenge") is False and flags.get("feature.type_race") is False
    assert flags.get("feature.curses") is True


def test_every_default_is_valid_for_its_kind():
    for s in BY_KEY.values():
        if s.kind == "bool":
            assert isinstance(s.default, bool)
        if s.kind == "float" and s.min is not None:
            assert s.min <= s.default <= s.max
