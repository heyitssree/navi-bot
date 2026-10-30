# navi/settings/registry.py - every runtime setting, declared once.
#
# Phase 3 ships the registry needed by the data model (tools/migrate_v2.py maps old bot_config keys through
# legacy_keys; the settings table stores overrides). Phase 4 completes the inventory (AI knobs, limits, channels,
# privacy) and builds the /admin panel on top of it.

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Setting:
    key: str                      # "chance.passive_curse_reply"
    kind: str                     # bool | int | float | str | choice | channel | role | id_list
    default: object
    category: str                 # System | AI | Safety | Features | Chances | Limits | Channels | Privacy
    label: str                    # shown in /admin panel
    help: str = ""
    min: float | None = None
    max: float | None = None
    choices: tuple[str, ...] = ()
    legacy_keys: tuple[str, ...] = ()   # old bot_config keys migrated into this one
    hidden: bool = False                # internal state, not shown in the panel


def _feature(name: str, label: str, *, default: bool = True, help: str = "") -> Setting:
    return Setting(f"feature.{name}", "bool", default, "Features", label, help, legacy_keys=(f"feature_{name}",))


SETTINGS: tuple[Setting, ...] = (
    Setting("system.killswitch", "bool", False, "System", "Master kill switch",
            "Silences everything except /admin.", legacy_keys=("master_killswitch",)),
    Setting("system.testing_guilds", "id_list", [], "System", "Testing guilds",
            "Guilds in testing mode: no rate limits, no rewards."),
    Setting("limit.navi_cooldown_seconds", "int", 60, "Limits", "Spam cooldown (s)", min=0, max=3600,
            legacy_keys=("navi_cooldown_seconds",)),
    Setting("limit.local_media_max_per_user", "int", 20, "Limits", "Media shortcuts per user", min=0,
            legacy_keys=("local_media_max_per_user",)),
    Setting("limit.local_media_max_global", "int", 200, "Limits", "Media shortcuts in total", min=0,
            legacy_keys=("local_media_max_global",)),
    Setting("chance.passive_curse_reply", "float", 0.25, "Chances", "Passive curse reply", min=0.0, max=1.0,
            legacy_keys=("curse_reply_chance",)),
    Setting("chance.kochi_reply", "float", 0.28, "Chances", "Kochi slang reply", min=0.0, max=1.0,
            legacy_keys=("kochi_reply_chance",)),
    Setting("chance.cache_reuse", "float", 0.50, "Chances", "Reuse today's prediction", min=0.0, max=1.0,
            legacy_keys=("cache_reuse_chance",)),
    Setting("chance.universal_blessing", "float", 0.05, "Chances", "Universal blessing", min=0.0, max=1.0,
            legacy_keys=("universal_blessing_chance",)),
    Setting("chance.backfire_mild", "float", 0.10, "Chances", "Curse backfire - Mild", min=0.0, max=1.0,
            legacy_keys=("backfire_chance_mild",)),
    Setting("chance.backfire_moderate", "float", 0.15, "Chances", "Curse backfire - Moderate", min=0.0, max=1.0,
            legacy_keys=("backfire_chance_moderate",)),
    Setting("chance.backfire_severe", "float", 0.20, "Chances", "Curse backfire - Severe", min=0.0, max=1.0,
            legacy_keys=("backfire_chance_severe",)),
    Setting("feature.link_summary_emoji", "str", "📰", "Features", "Link summary emoji",
            legacy_keys=("link_summary_emoji",)),
    _feature("navi", "Navi predictions"),
    _feature("curses", "Curses and blessings"),
    _feature("gambling", "Gambling"),
    _feature("local_media", "Local media shortcuts"),
    _feature("boli_points", "Boli points tracking"),
    _feature("kochi_replies", "Kochi slang replies"),
    _feature("curse_replies", "Passive curse replies"),
    _feature("vibe_check", "Vibe check"),
    _feature("link_summary", "Link summary"),
    _feature("kanmanilla", "Kanmanilla"),
    _feature("welcome", "Welcome messages"),
    _feature("temp_vc", "Temporary voice channels"),
    _feature("audit", "Mod audit"),
    _feature("mod_tldr", "Mod TL;DR"),
    _feature("strikes", "3-strike system"),
    _feature("partner_api", "Partner API awards"),
    _feature("navi_challenge", "Navi Challenge", default=False,
             help="Disabled until the Phase 5 safety eval passes."),
    _feature("type_race", "Type Race", default=False,
             help="Disabled until the Phase 5 safety eval passes."),
    Setting("state.lucky_draw_last_date", "str", "", "System", "Lucky draw last run", hidden=True,
            legacy_keys=("lucky_draw_last_date",)),
)

# Old bot_config keys that are intentionally not carried over (no code reads them any more).
INTENTIONALLY_DROPPED: dict[str, str] = {
    "WEATHER_ALERT_TIME": "daily weather/omen post was removed in the bot split (Phase 1 dead-code removal)",
    "reversal_chance_owner": "no caller since the bamboozled-bot split (Phase 1 dead-code removal)",
}

# Old values that must not be carried over: the default wins (seed drift, see CHANGELOG-v2 Phase 0).
RESET_ON_MIGRATE: frozenset[str] = frozenset({"feature_navi_challenge", "feature_type_race"})

BY_KEY: dict[str, Setting] = {s.key: s for s in SETTINGS}
BY_LEGACY: dict[str, Setting] = {lk: s for s in SETTINGS for lk in s.legacy_keys}
assert len(BY_KEY) == len(SETTINGS), "duplicate setting key"


def resolve(key: str) -> Setting:
    """Look up a setting by registry key or legacy bot_config key. Unknown keys raise (typo protection)."""
    setting = BY_KEY.get(key) or BY_LEGACY.get(key)
    if setting is None:
        raise KeyError(f"unknown setting: {key!r}")
    return setting
