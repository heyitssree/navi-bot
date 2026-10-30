# navi/settings/store.py - in-memory cache over the settings table (overrides) + registry defaults
#
# feat() and set_feature() accept registry keys ("feature.curses") or the old names ("feature_curses").
# Phase 4 grows this into the full store behind the /admin panel.

from __future__ import annotations

import json
import logging

from navi.db.repos.settings import get_testing_guilds, set_setting
from navi.settings.registry import SETTINGS, resolve

logger = logging.getLogger("navi.settings")


class FeatureFlags:
    """Avoids a DB read on every message/interaction. Loaded in on_ready; updated on every /admin toggle."""

    def __init__(self) -> None:
        self.cache: dict[str, object] = {s.key: s.default for s in SETTINGS}   # registry key -> effective value
        self.testing_guild_ids: set[int] = set()  # guilds with testing mode on (no rate limits, no rewards)
        self._db = None

    def bind(self, db) -> None:
        self._db = db

    def get(self, key: str):
        setting = resolve(key)
        return self.cache.get(setting.key, setting.default)

    def feat(self, key: str) -> bool:
        """Return True if the feature is enabled in the in-memory cache."""
        return bool(self.get(key))

    def override(self, key: str, value) -> None:
        """Change the cached value only (no DB write) - used by tests and by set_feature."""
        self.cache[resolve(key).key] = value

    def is_testing_guild(self, guild_id: int | None) -> bool:
        return guild_id is not None and guild_id in self.testing_guild_ids

    def load(self) -> None:
        """Reload every override from the settings table into the in-memory cache."""
        self.cache = {s.key: s.default for s in SETTINGS}
        for key, raw in self._db.execute("SELECT key, value FROM settings"):
            try:
                self.cache[resolve(key).key] = json.loads(raw)
            except KeyError:
                logger.warning("Ignoring unknown stored setting %r", key)
            except ValueError:
                logger.warning("Bad JSON for stored setting %r", key)
        logger.info("Settings cache loaded (%d overrides)", len(self.cache))

    def load_testing_guilds(self) -> None:
        self.testing_guild_ids.update(get_testing_guilds(self._db))
        logger.info("Testing guilds loaded: %s", self.testing_guild_ids)

    def set_feature(self, key: str, value: int, updated_by: int | None = None) -> None:
        """Persist a feature toggle to DB and update the in-memory cache."""
        setting = resolve(key)
        stored = bool(value) if setting.kind == "bool" else value
        set_setting(self._db, setting.key, stored, updated_by)
        self.cache[setting.key] = stored
