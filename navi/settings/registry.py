# navi/settings/registry.py - every runtime setting, declared once.
#
# The /admin panel, /admin set|get|reset, validation, defaults, export/import and tools/migrate_v2.py all read from
# this table, so a new knob only needs one new Setting line to show up everywhere. Code reads values at use time with
# ctx.settings.get with the key; nothing is read at import time, so changes apply without a restart (except settings
# marked restart=True).

from __future__ import annotations

from dataclasses import dataclass

CATEGORIES = ("System", "AI", "Safety", "Features", "Chances", "Limits", "Channels", "Privacy")
KINDS = ("bool", "int", "float", "str", "choice", "channel", "role", "id_list")


@dataclass(frozen=True)
class Setting:
    key: str                      # "chance.passive_curse_reply"
    kind: str                     # bool | int | float | str | choice | channel | role | id_list
    default: object
    category: str                 # one of CATEGORIES
    label: str                    # shown in the /admin panel
    help: str = ""
    min: float | None = None
    max: float | None = None
    choices: tuple[str, ...] = ()
    legacy_keys: tuple[str, ...] = ()   # old bot_config keys migrated into this one
    hidden: bool = False                # internal state, not shown in the panel
    restart: bool = False               # change only takes effect after a restart


def _feature(name: str, label: str, *, default: bool = True, help: str = "", legacy: tuple[str, ...] = ()) -> Setting:
    return Setting(f"feature.{name}", "bool", default, "Features", label, help, legacy_keys=legacy)


def _limit(key: str, label: str, default: int, lo: int, hi: int, help: str = "", legacy: tuple[str, ...] = ()) -> Setting:
    category = {"ai": "AI", "privacy": "Privacy"}.get(key.split(".")[0], "Limits")
    return Setting(key, "int", default, category, label, help, min=lo, max=hi, legacy_keys=legacy)


def _chance(key: str, label: str, default: float, legacy: tuple[str, ...] = ()) -> Setting:
    return Setting(key, "float", default, "Chances", label, "Probability from 0.0 to 1.0.", min=0.0, max=1.0, legacy_keys=legacy)


SETTINGS: tuple[Setting, ...] = (
    # ---- System
    Setting("system.killswitch", "bool", False, "System", "Master kill switch",
            "Silences everything except /admin.", legacy_keys=("master_killswitch",)),
    Setting("system.testing_guilds", "id_list", [], "System", "Testing guilds",
            "Guild IDs in testing mode: no rate limits, no rewards. Use /admin testing in the guild itself."),
    Setting("system.panel_role", "role", None, "System", "Panel role",
            "Role (besides the owner) that may use /admin."),
    Setting("state.lucky_draw_last_date", "str", "", "System", "Lucky draw last run", hidden=True,
            legacy_keys=("lucky_draw_last_date",)),
    # ---- AI
    Setting("ai.provider", "choice", "gemini", "AI", "LLM provider",
            "off = no LLM calls; everything falls back to templates and canned text.", choices=("gemini", "off")),
    Setting("ai.gemini_keys", "choice", "free_then_paid", "AI", "Gemini keys",
            "free_only never touches the paid key (replaces the old Free-Only killswitch).",
            choices=("free_only", "free_then_paid")),
    Setting("ai.model", "str", "", "AI", "Model override",
            "Empty = use LLM_MODEL from the environment (default gemini-3.5-flash-lite)."),
    Setting("ai.bedrock_model_id", "str", "", "AI", "Bedrock model id",
            "Global inference profile id for Claude Haiku 5.5 (used from Phase 7). Empty = BEDROCK_MODEL_ID env.",
            restart=True),
    _limit("ai.rpm_budget", "Requests per minute", 10, 1, 600, "Shared LLM budget across all features."),
    _limit("ai.daily_call_cap", "Daily call cap", 1500, 1, 100000, "Hard stop on LLM calls per day (spend guard)."),
    Setting("ai.temperature", "float", 0.6, "AI", "Temperature", "Lower = more predictable.", min=0.0, max=1.0),
    _limit("ai.max_output_tokens", "Max output tokens", 200, 16, 4096, "Short replies; summaries and audits get 4x."),
    _limit("ai.qa_cooldown_seconds", "Q&A cooldown (s)", 30, 0, 3600, "Per user, mention Q&A and context replies."),
    _limit("ai.qa_daily_cap", "Q&A per user per day", 25, 1, 1000, "Per user."),
    _limit("ai.qa_cache_ttl_days", "Q&A cache TTL (days)", 7, 1, 90, "How long cached answers are reused."),
    # ---- Safety
    Setting("safety.allow_malayalam_script", "bool", False, "Safety", "Allow Malayalam script",
            "Off: any reply containing Malayalam script is replaced by a fallback."),
    Setting("safety.template_auto_approve", "bool", False, "Safety", "Auto-approve templates",
            "Off: generated templates wait for /admin review."),
    Setting("safety.template_batch_size", "int", 20, "Safety", "Template batch size", min=1, max=100),
    # ---- Features
    _feature("navi", "Navi predictions", legacy=("feature_navi",)),
    _feature("curses", "Curses and blessings", legacy=("feature_curses",)),
    _feature("passive_curse_replies", "Passive curse replies", legacy=("feature_curse_replies",)),
    _feature("kochi_replies", "Kochi slang replies", legacy=("feature_kochi_replies",)),
    _feature("boli_points", "Slang points", legacy=("feature_boli_points",)),
    _feature("gambling", "Gambling", legacy=("feature_gambling",)),
    _feature("local_media", "Local media shortcuts", legacy=("feature_local_media",)),
    _feature("vibe_check", "Vibe check", legacy=("feature_vibe_check",)),
    _feature("link_summary", "Link summaries", legacy=("feature_link_summary",)),
    _feature("kanmanilla", "Kanmanilla", legacy=("feature_kanmanilla",)),
    _feature("welcome", "Welcome messages", legacy=("feature_welcome",)),
    _feature("temp_vc", "Temporary voice channels", legacy=("feature_temp_vc",)),
    _feature("audit", "Mod audit", legacy=("feature_audit",)),
    _feature("mod_tldr", "Mod TL;DR", legacy=("feature_mod_tldr",)),
    _feature("strikes", "3-strike system", legacy=("feature_strikes",)),
    _feature("partner_api", "Partner API awards", legacy=("feature_partner_api",)),
    _feature("navi_challenge", "Navi Challenge", default=False, legacy=("feature_navi_challenge",),
             help="Stays off until the Phase 5 safety eval passes."),
    _feature("type_race", "Type Race", default=False, legacy=("feature_type_race",),
             help="Stays off until the Phase 5 safety eval passes."),
    _feature("mention_qa", "Mention Q&A", help="Answer questions when Navi is @mentioned."),
    _feature("context_replies", "Context replies", default=False,
             help="Conversation-aware replies in the bot-commands channel (needs channel.bot_commands)."),
    _feature("teach", "/teach"),
    _feature("market", "Stock market"),
    _feature("shop", "Shop"),
    _feature("gift", "/gift"),
    _feature("lucky_draw", "Daily lucky draw"),
    Setting("emoji.link_summary", "str", "📰", "Features", "Link summary emoji",
            "React with this emoji to summarise a link.", legacy_keys=("link_summary_emoji",)),
    # ---- Chances
    _chance("chance.cache_reuse", "Reuse today's prediction", 0.50, ("cache_reuse_chance",)),
    _chance("chance.kochi_reply", "Kochi slang reply", 0.28, ("kochi_reply_chance",)),
    _chance("chance.passive_curse_reply", "Passive curse reply", 0.25, ("curse_reply_chance",)),
    _chance("chance.universal_blessing", "Universal blessing", 0.05, ("universal_blessing_chance",)),
    _chance("chance.backfire_mild", "Curse backfire - Mild", 0.10, ("backfire_chance_mild",)),
    _chance("chance.backfire_moderate", "Curse backfire - Moderate", 0.15, ("backfire_chance_moderate",)),
    _chance("chance.backfire_severe", "Curse backfire - Severe", 0.20, ("backfire_chance_severe",)),
    # ---- Limits and tuning
    _limit("limit.navi_cooldown_seconds", "/navi spam cooldown (s)", 60, 0, 3600, legacy=("navi_cooldown_seconds",)),
    _limit("limit.daily_cosmic_actions", "Cosmic actions per day", 20, 1, 1000, "Curses and blessings per user."),
    _limit("limit.game_daily", "Gambling plays per day", 30, 1, 1000, "Combined across all gambling games."),
    _limit("limit.llm_game_daily", "LLM game attempts per day", 2, 1, 100),
    _limit("limit.gift_daily", "Gift total per day", 0, 0, 1000000, "Most Boli a user may gift per day. 0 = no limit."),
    _limit("limit.media_per_user", "Media shortcuts per user", 20, 0, 1000, legacy=("local_media_max_per_user",)),
    _limit("limit.media_global", "Media shortcuts in total", 200, 0, 100000, legacy=("local_media_max_global",)),
    _limit("limit.market_expiry_days", "Holding expiry (days)", 7, 1, 365),
    _limit("limit.temp_vc_minutes", "Temp voice channel lifetime (min)", 30, 1, 1440),
    _limit("economy.lucky_draw_amount", "Lucky draw prize", 200, 1, 100000),
    _limit("slang.spam_window_seconds", "Slang spam window (s)", 60, 1, 3600),
    _limit("slang.spam_threshold", "Slang spam threshold", 2, 1, 50),
    _limit("slang.cooldown_minutes", "Slang spam cooldown (min)", 5, 1, 1440),
    _limit("slang.max_words", "Slang spam max words", 2, 1, 20),
    _limit("slang.max_chars", "Slang spam max chars", 20, 1, 500),
    _limit("vibe.window_seconds", "Vibe window (s)", 15, 1, 600),
    _limit("vibe.min_messages", "Vibe min messages", 10, 1, 500),
    Setting("vibe.heated_ratio", "float", 0.30, "Limits", "Vibe heated ratio",
            "Share of heated messages that triggers the calming message.", min=0.0, max=1.0),
    _limit("vibe.cooldown_seconds", "Vibe cooldown (s)", 60, 1, 3600),
    _limit("partner.rate_limit_rpm", "Partner API requests/min per guild", 10, 1, 1000),
    _limit("partner.min_xp", "Partner minimum XP award", 5, 0, 1000),
    # ---- Channels
    Setting("channel.bot_commands", "channel", None, "Channels", "Bot-commands channel",
            "Context-aware replies only happen here."),
    Setting("channel.mod_alerts", "channel", None, "Channels", "Mod alerts channel",
            "Strike escalations go here. Empty = the channel named by MOD_CHANNEL_NAME."),
    # ---- Privacy
    _limit("privacy.optin_cooldown_days", "Opt-in cooldown (days)", 7, 0, 365),
    Setting("privacy.block_optout_with_strikes", "bool", True, "Privacy", "Block opt-out with strikes",
            "Users with strikes cannot opt out."),
    Setting("privacy.audit_includes_optouts", "bool", False, "Privacy", "Audit includes opted-out users"),
)

# Old bot_config keys that are intentionally not carried over (no code reads them any more).
INTENTIONALLY_DROPPED: dict[str, str] = {
    "WEATHER_ALERT_TIME": "daily weather/omen post was removed in the bot split (Phase 1 dead-code removal)",
    "reversal_chance_owner": "no caller since the bamboozled-bot split (Phase 1 dead-code removal)",
}

# Old values that must not be carried over: the default wins (seed drift, see CHANGELOG-v2 Phase 0).
RESET_ON_MIGRATE: frozenset[str] = frozenset({"feature_navi_challenge", "feature_type_race"})

# Registry keys used by Phase 3 databases that were renamed in Phase 4 (migration 0002 renames the stored rows).
RENAMED_IN_PHASE_4: dict[str, str] = {
    "feature.curse_replies": "feature.passive_curse_replies",
    "feature.link_summary_emoji": "emoji.link_summary",
    "limit.local_media_max_per_user": "limit.media_per_user",
    "limit.local_media_max_global": "limit.media_global",
}

BY_KEY: dict[str, Setting] = {s.key: s for s in SETTINGS}
BY_LEGACY: dict[str, Setting] = {lk: s for s in SETTINGS for lk in s.legacy_keys}
assert len(BY_KEY) == len(SETTINGS), "duplicate setting key"
assert all(s.category in CATEGORIES and s.kind in KINDS for s in SETTINGS)


def resolve(key: str) -> Setting:
    """Look up a setting by registry key or old bot_config key. Unknown keys raise (typo protection)."""
    setting = BY_KEY.get(key) or BY_LEGACY.get(key)
    if setting is None:
        raise KeyError(f"unknown setting: {key!r}")
    return setting
