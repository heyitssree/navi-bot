# navi/settings/store.py - in-memory feature toggle cache backed by bot_config (Phase 4 turns this into the registry)

from __future__ import annotations

import logging

from navi.db.repos.settings import get_config_int, get_testing_guilds, set_config_int

logger = logging.getLogger("navi.settings")

DEFAULTS: dict[str, int] = {
    "master_killswitch":       0,
    "feature_navi":            1,
    "feature_curses":          1,
    "feature_gambling":        1,
    "feature_local_media":     1,
    "feature_boli_points":     1,
    "feature_kochi_replies":   1,
    "feature_curse_replies":   1,
    "feature_vibe_check":      1,
    "feature_link_summary":    1,
    "feature_kanmanilla":      1,
    "feature_welcome":         1,
    "feature_temp_vc":         1,
    "feature_audit":           1,
    "feature_mod_tldr":        1,
    "feature_strikes":         1,
    "feature_navi_challenge":  0,  # DISABLED - Gemini outputting inappropriate language
    "feature_type_race":       0,  # DISABLED - Gemini outputting inappropriate language
}


class FeatureFlags:
    """Avoids a DB read on every message/interaction. Loaded in on_ready; updated on every /admin toggle."""

    def __init__(self) -> None:
        self.cache: dict[str, int] = dict(DEFAULTS)
        self.testing_guild_ids: set[int] = set()  # guilds with testing mode on (no rate limits, no rewards)
        self._db = None

    def bind(self, db) -> None:
        self._db = db

    def feat(self, key: str) -> bool:
        """Return True if the feature is enabled in the in-memory cache."""
        return bool(self.cache.get(key, DEFAULTS.get(key, 1)))

    def is_testing_guild(self, guild_id: int | None) -> bool:
        return guild_id is not None and guild_id in self.testing_guild_ids

    def load(self) -> None:
        """Reload all toggle values from DB into the in-memory cache."""
        for key, default in DEFAULTS.items():
            self.cache[key] = get_config_int(self._db, key, default)
        logger.info("Feature toggle cache loaded: %s", self.cache)

    def load_testing_guilds(self) -> None:
        self.testing_guild_ids.update(get_testing_guilds(self._db))
        logger.info("Testing guilds loaded: %s", self.testing_guild_ids)

    def set_feature(self, key: str, value: int) -> None:
        """Persist a feature toggle to DB and update in-memory cache."""
        set_config_int(self._db, key, value)
        self.cache[key] = value
