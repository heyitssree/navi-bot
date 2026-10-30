import json
import re
from pathlib import Path

import pytest

from navi.settings.registry import BY_KEY, BY_LEGACY, CATEGORIES, INTENTIONALLY_DROPPED, KINDS, SETTINGS, resolve
from navi.settings.store import Settings, SettingError, format_value, parse, validate

# Every row of the spec's inventory (section 8.2), as registry keys. ".../" rows are expanded.
INVENTORY = """
system.killswitch system.testing_guilds system.panel_role
ai.provider ai.fallback_provider ai.price_input_per_mtok ai.price_output_per_mtok ai.gemini_keys ai.model ai.bedrock_model_id ai.rpm_budget ai.daily_call_cap ai.temperature ai.max_output_tokens
ai.qa_cooldown_seconds ai.qa_daily_cap ai.qa_cache_ttl_days
safety.allow_malayalam_script safety.template_auto_approve safety.template_batch_size
feature.navi feature.curses feature.passive_curse_replies feature.kochi_replies feature.boli_points feature.gambling
feature.local_media feature.vibe_check feature.link_summary feature.kanmanilla feature.welcome feature.temp_vc feature.audit
feature.mod_tldr feature.strikes feature.partner_api feature.navi_challenge feature.type_race feature.mention_qa
feature.context_replies feature.teach feature.market feature.shop feature.gift feature.lucky_draw
chance.cache_reuse chance.kochi_reply chance.passive_curse_reply chance.universal_blessing
chance.backfire_mild chance.backfire_moderate chance.backfire_severe
limit.navi_cooldown_seconds limit.daily_cosmic_actions limit.game_daily limit.llm_game_daily limit.gift_daily
limit.media_per_user limit.media_global limit.market_expiry_days limit.temp_vc_minutes economy.lucky_draw_amount
slang.spam_window_seconds slang.spam_threshold slang.cooldown_minutes slang.max_words slang.max_chars
vibe.window_seconds vibe.min_messages vibe.heated_ratio vibe.cooldown_seconds
partner.rate_limit_rpm partner.min_xp
channel.bot_commands channel.mod_alerts emoji.link_summary
privacy.optin_cooldown_days privacy.block_optout_with_strikes privacy.audit_includes_optouts
state.lucky_draw_last_date
feature.chat_redirect chat.redirect_calls chat.redirect_window_seconds chat.redirect_cooldown_seconds
""".split()          # last row: added after the spec (owner request, Phase 8): AI chat redirect to bot-commands

SAMPLE = {"bool": "off", "int": None, "float": None, "str": "hello", "channel": "<#123>", "role": "<@&456>", "id_list": "1 2 3"}


def test_every_inventory_row_is_in_the_registry_and_nothing_extra():
    assert set(INVENTORY) == set(BY_KEY)


def test_registry_is_well_formed():
    for s in SETTINGS:
        assert s.category in CATEGORIES and s.kind in KINDS and s.label
        if s.kind == "choice":
            assert s.default in s.choices
        if s.kind in ("int", "float") and s.min is not None:
            assert s.min <= s.default <= s.max, s.key
        assert validate(s, s.default) == s.default or s.kind in ("channel", "role"), s.key      # defaults pass their own validation


def test_spec_defaults():
    d = {k: BY_KEY[k].default for k in BY_KEY}
    assert d["ai.temperature"] == 0.6 and d["ai.rpm_budget"] == 10 and d["ai.daily_call_cap"] == 1500
    assert d["feature.navi_challenge"] is False and d["feature.type_race"] is False and d["feature.context_replies"] is False
    assert d["limit.daily_cosmic_actions"] == 20 and (d["limit.game_daily"], d["limit.llm_game_daily"]) == (30, 2)
    assert (d["chance.backfire_mild"], d["chance.backfire_moderate"], d["chance.backfire_severe"]) == (0.10, 0.15, 0.20)
    assert d["economy.lucky_draw_amount"] == 200 and d["privacy.optin_cooldown_days"] == 7
    assert d["privacy.block_optout_with_strikes"] is True and d["privacy.audit_includes_optouts"] is False
    assert d["ai.qa_cooldown_seconds"] == 30 and d["ai.qa_daily_cap"] == 25 and d["ai.qa_cache_ttl_days"] == 7


def test_every_old_bot_config_key_is_mapped_or_dropped():
    old = {"master_killswitch", "feature_navi", "feature_curses", "feature_gambling", "feature_local_media", "feature_boli_points",
           "feature_kochi_replies", "feature_curse_replies", "feature_vibe_check", "feature_link_summary", "feature_kanmanilla",
           "feature_welcome", "feature_temp_vc", "feature_audit", "feature_mod_tldr", "feature_strikes", "feature_navi_challenge",
           "feature_type_race", "feature_partner_api", "cache_reuse_chance", "kochi_reply_chance", "curse_reply_chance",
           "universal_blessing_chance", "backfire_chance_mild", "backfire_chance_moderate", "backfire_chance_severe",
           "navi_cooldown_seconds", "local_media_max_per_user", "local_media_max_global", "link_summary_emoji",
           "lucky_draw_last_date", "WEATHER_ALERT_TIME", "reversal_chance_owner"}
    assert all(k in BY_LEGACY or k in INTENTIONALLY_DROPPED for k in old)


@pytest.mark.parametrize("setting", [s for s in SETTINGS if not s.hidden], ids=lambda s: s.key)
def test_every_visible_setting_is_editable_through_parse_set_reset_and_export(setting, db):
    """The gate: every inventory row can be edited (as /admin set and the panel modal do), reset and exported."""
    store = Settings(); store.bind(db)
    text = {"int": str(int(setting.min if setting.min is not None else 1) + 0 if setting.min is not None else 1),
            "float": f"{(setting.min or 0.0) + 0.01:g}", "choice": setting.choices[-1] if setting.choices else ""}.get(setting.kind, SAMPLE.get(setting.kind))
    if setting.kind == "int" and text == str(int(setting.default)):
        text = str(int(setting.default) + 1)
    if setting.kind == "bool":
        text = "off" if setting.default else "on"
    store.set_text(setting.key, text, by=5)
    assert not store.is_default(setting.key) or store.get(setting.key) == setting.default
    exported = json.loads(store.export_json())["settings"]
    assert setting.key in exported
    store.reset(setting.key, by=5)
    assert store.get(setting.key) == setting.default and store.is_default(setting.key)


def test_parse_each_kind():
    flag = resolve("feature.gambling")
    assert [parse(flag, t) for t in ("on", "TRUE", "yes", "1")] == [True] * 4 and parse(flag, "off") is False
    with pytest.raises(SettingError):
        parse(flag, "maybe")
    cd = resolve("limit.navi_cooldown_seconds")
    assert parse(cd, " 90 ") == 90
    for bad in ("abc", "1.5", "-1", "99999"):
        with pytest.raises(SettingError):
            parse(cd, bad)
    ch = resolve("chance.kochi_reply")
    assert parse(ch, "0.5") == 0.5
    for bad in ("2", "-0.1", "x"):
        with pytest.raises(SettingError):
            parse(ch, bad)
    provider = resolve("ai.provider")
    assert parse(provider, "off") == "off"
    assert parse(provider, "bedrock") == "bedrock"
    with pytest.raises(SettingError, match="gemini, bedrock, off"):
        parse(provider, "claude")
    chan = resolve("channel.bot_commands")
    assert parse(chan, "<#123456>") == 123456 and parse(chan, "987") == 987 and parse(chan, "none") is None
    with pytest.raises(SettingError):
        parse(chan, "general")
    role = resolve("system.panel_role")
    assert parse(role, "<@&55>") == 55
    ids = resolve("system.testing_guilds")
    assert parse(ids, "3, 1  2,2") == [1, 2, 3]
    with pytest.raises(SettingError):
        parse(ids, "1, x")
    with pytest.raises(SettingError):
        validate(resolve("emoji.link_summary"), "x" * 300)


def test_format_value():
    assert format_value(resolve("feature.gambling"), True) == "on"
    assert format_value(resolve("channel.bot_commands"), None) == "not set"
    assert format_value(resolve("channel.bot_commands"), 5) == "<#5>"
    assert format_value(resolve("system.panel_role"), 5) == "<@&5>"
    assert format_value(resolve("chance.kochi_reply"), 0.28) == "0.28"
    assert format_value(resolve("ai.model"), "") == "(empty)"


def test_store_set_get_reset_observers_and_events(db):
    store = Settings(); store.bind(db)
    seen = []
    store.on_change(lambda s, v: seen.append((s.key, v)))
    assert store.get("chance.kochi_reply") == 0.28 and store.get("curse_reply_chance") == 0.25      # old names resolve
    assert store.set("chance.kochi_reply", 0.5, by=7) == 0.5
    with pytest.raises(SettingError):
        store.set("chance.kochi_reply", 5, by=7)
    assert store.get("chance.kochi_reply") == 0.5               # a rejected value changes nothing
    assert store.reset("chance.kochi_reply", by=7) and not store.reset("chance.kochi_reply")
    assert seen == [("chance.kochi_reply", 0.5), ("chance.kochi_reply", 0.28), ("chance.kochi_reply", 0.28)]
    events = [json.loads(r[0]) for r in db.execute("SELECT detail FROM events WHERE kind='setting_change' ORDER BY id")]
    assert events[0] == {"old": 0.28, "new": 0.5} and events[1]["reset"] is True
    with pytest.raises(KeyError):
        store.get("nope")


def test_category_counts_and_is_testing_guild(db):
    store = Settings(); store.bind(db)
    store.set("ai.rpm_budget", 20); store.set("system.testing_guilds", [42])
    counts = store.category_counts()
    assert counts["AI"][0] == 1 and counts["System"][0] == 1 and sum(t for _, t in counts.values()) == len([s for s in SETTINGS if not s.hidden])
    assert store.is_testing_guild(42) and not store.is_testing_guild(43) and not store.is_testing_guild(None)


def test_export_import_roundtrip_and_errors(db):
    a = Settings(); a.bind(db)
    a.set("chance.kochi_reply", 0.9); a.set("feature.welcome", False); a.set("channel.mod_alerts", 77)
    dump = a.export_json()
    b = Settings()
    applied, errors = b.import_json(dump, by=1)
    assert sorted(applied) == ["chance.kochi_reply", "channel.mod_alerts", "feature.welcome"] and errors == []
    assert b.get("feature.welcome") is False and b.get("channel.mod_alerts") == 77
    bad = json.dumps({"version": 1, "settings": {"chance.kochi_reply": 5, "nope.key": 1, "feature.teach": False}})
    applied, errors = Settings().import_json(bad)
    assert applied == ["feature.teach"] and len(errors) == 2
    assert Settings().import_json("not json")[1] and Settings().import_json("[]")[1]


def test_settings_load_reads_stored_overrides(db):
    a = Settings(); a.bind(db); a.set("ai.rpm_budget", 33)
    b = Settings(); b.bind(db); b.load()
    assert b.get("ai.rpm_budget") == 33


# ------------------------------------------------------------------------------- the gate: no old-style call sites

def test_no_old_style_config_calls_remain_and_every_key_is_registered():
    forbidden = re.compile(r"get_config_(?:float|int|str)|set_config_(?:float|int|str)|\.feat\(|set_feature\(|get_all_configs|get_testing_guilds")
    offenders, keys = [], set()
    for path in Path("navi").rglob("*.py"):
        text = path.read_text()
        if path.name in ("registry.py", "store.py") and "settings" in path.parts:
            text = re.sub(r'""".*?"""', "", text, flags=re.S)       # docstrings mention the API
        if forbidden.search(text):
            offenders.append(str(path))
        keys |= set(re.findall(r'settings\.(?:get|set|set_text|reset|is_default)\(\s*["\']([^"\']+)["\']', text))
        keys |= set(re.findall(r'ctx\.settings\.get\(\s*_tier_key\[', text) and ["chance.backfire_mild"])
    assert not offenders, offenders
    assert keys and keys <= set(BY_KEY), keys - set(BY_KEY)


def test_old_hardcoded_constants_are_gone():
    gone = ["DAILY_QUOTA", "_GAME_DAILY_LIMIT", "_GEMINI_GAME_DAILY_LIMIT", "MARKET_EXPIRY_DAYS", "_TEMP_VC_DURATION",
            "_LUCKY_DRAW_AMOUNT", "_SLANG_SPAM", "_SLANG_COOLDOWN", "_VIBE_", "_RATE_LIMIT_RPM", "_MIN_XP"]
    text = "\n".join(p.read_text() for p in Path("navi").rglob("*.py"))
    assert [g for g in gone if re.search(r"(?<![\w.])%s" % re.escape(g), text)] == []


def test_every_setting_used_in_code_is_consumed_somewhere():
    """A registry entry nobody reads would be a dead knob. Allow-list: settings whose consumer arrives in a later phase."""
    later = {"ai.bedrock_model_id"}          # its consumer (the Bedrock provider) arrives in Phase 7
    text = "\n".join(p.read_text() for p in Path("navi").rglob("*.py") if "registry.py" not in p.name)
    unused = {k for k in BY_KEY if f'"{k}"' not in text and f"'{k}'" not in text}
    assert unused - later == set(), unused - later
