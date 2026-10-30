"""Characterisation of the AI-free curse (navi) and bless (chunk) games. Rules must not change."""
import asyncio
import random

import pytest

from navi.data.curse_data import COMPLIMENTS, CURSE_WORDS
from navi.db.repos.counters import add_extra_actions, get_daily_action_count, get_extra_actions
from navi.db.repos.perks import grant_perk
from navi.db.repos.settings import get_config_float, set_config_float
from navi.handlers import curse_commands, pipeline
from navi.services.quota import DAILY_QUOTA
from tests.legacy.harness import FakeUser, make_ctx, make_message, points, seed, xp

CASTER = FakeUser(1, "caster")
TARGET = FakeUser(2, "target")

BY_TIER = {t: next(c for c in CURSE_WORDS if c["tier"] == t) for t in ("Mild", "Moderate", "Severe")}
TIER_DEFAULT = {"Mild": 0.10, "Moderate": 0.15, "Severe": 0.20}


class _Navi:
    """Tiny shim so the original test bodies read the same: navi.on_message(msg)."""

    def __init__(self, ctx):
        self.ctx = ctx

    async def on_message(self, msg):
        await pipeline.on_message(self.ctx, msg)


@pytest.fixture()
def env(db, monkeypatch):
    ctx = make_ctx(db)
    monkeypatch.setattr(_Holder, "navi", _Navi(ctx))
    seed(db, CASTER, TARGET)
    return db


class _Holder:
    navi = None


class _NaviProxy:
    def __getattr__(self, name):
        return getattr(_Holder.navi, name)


navi = _NaviProxy()


def force(monkeypatch, curse, roll):
    """Fix the curse chosen and the value returned by random.random()."""
    monkeypatch.setattr(curse_commands, "get_random_curse", lambda: curse)
    monkeypatch.setattr(random, "random", lambda: roll)


def two_calls(monkeypatch, curse, rolls):
    it = iter(rolls)
    monkeypatch.setattr(curse_commands, "get_random_curse", lambda: curse)
    monkeypatch.setattr(random, "random", lambda: next(it))


def test_tier_data_matches_documented_defaults():
    for tier, entry in BY_TIER.items():
        assert entry["backfire_chance"] == TIER_DEFAULT[tier]
        assert entry["target_damage"] == entry["invoker_reward"]
    assert len(CURSE_WORDS) == 17


@pytest.mark.parametrize("tier", ["Mild", "Moderate", "Severe"])
async def test_curse_lands_below_backfire_threshold_is_backfire(env, monkeypatch, tier):
    c = BY_TIER[tier]
    force(monkeypatch, c, TIER_DEFAULT[tier] - 0.001)  # roll < chance -> backfire
    msg = make_message(CASTER, "navi <@2>", mentions=[TARGET])
    await navi.on_message(msg)
    assert points(env, CASTER.id) == -c["target_damage"]
    assert points(env, TARGET.id) == c["target_damage"]


@pytest.mark.parametrize("tier", ["Mild", "Moderate", "Severe"])
async def test_curse_lands_at_or_above_threshold(env, monkeypatch, tier):
    c = BY_TIER[tier]
    force(monkeypatch, c, TIER_DEFAULT[tier])  # roll == chance -> lands
    msg = make_message(CASTER, "navi <@2>", mentions=[TARGET])
    await navi.on_message(msg)
    assert points(env, TARGET.id) == -c["target_damage"]
    assert points(env, CASTER.id) == c["invoker_reward"]
    msg.reply.assert_awaited_once()


@pytest.mark.parametrize("perk", ["curse_protection", "deflector_shield"])
async def test_protected_or_shielded_always_bounce(env, monkeypatch, perk):
    c = BY_TIER["Mild"]
    grant_perk(env, TARGET.id, perk, 1)
    force(monkeypatch, c, 0.999)  # would land for an unprotected target
    await navi.on_message(make_message(CASTER, "navi <@2>", mentions=[TARGET]))
    assert points(env, CASTER.id) == -c["target_damage"]
    assert points(env, TARGET.id) == c["target_damage"]


async def test_backfire_tier_is_configurable(env, monkeypatch):
    c = BY_TIER["Mild"]
    set_config_float(env, "backfire_chance_mild", 0.90)
    force(monkeypatch, c, 0.50)
    await navi.on_message(make_message(CASTER, "navi <@2>", mentions=[TARGET]))
    assert points(env, CASTER.id) == -c["target_damage"]


def test_fixed_in_v2_set_config_float_now_takes_effect(env):
    """Phase 0 'Found, not fixed': set_config_float used to be a silent no-op for rows that were never seeded.
    The settings table upserts, so the override is stored and read back."""
    assert get_config_float(env, "backfire_chance_mild", 0.10) == 0.10
    set_config_float(env, "backfire_chance_mild", 0.90)
    assert get_config_float(env, "backfire_chance_mild", 0.10) == 0.90
    assert get_config_float(env, "chance.backfire_mild", 0.10) == 0.90   # registry key and old name are the same setting


async def test_reply_curse_same_rules(env, monkeypatch):
    c = BY_TIER["Moderate"]
    force(monkeypatch, c, 0.99)
    await navi.on_message(make_message(CASTER, "navi", reference_author=TARGET))
    assert points(env, TARGET.id) == -c["target_damage"]
    assert points(env, CASTER.id) == c["invoker_reward"]
    force(monkeypatch, c, 0.0)
    await navi.on_message(make_message(CASTER, "navi", reference_author=TARGET))
    assert points(env, CASTER.id) == c["invoker_reward"] - c["target_damage"]


async def test_self_curse_costs_damage_no_roll(env, monkeypatch):
    c = BY_TIER["Severe"]
    force(monkeypatch, c, 0.0)
    await navi.on_message(make_message(CASTER, "navi"))
    assert points(env, CASTER.id) == -c["target_damage"]


async def test_curse_on_bot_user_is_deflected_without_points(env, monkeypatch):
    force(monkeypatch, BY_TIER["Mild"], 0.99)
    me = FakeUser(999, "navi-bot")
    await navi.on_message(make_message(CASTER, "navi <@999>", mentions=[me]))
    assert points(env, CASTER.id) == 0


async def test_quota_accounting_and_block(env, monkeypatch):
    c = BY_TIER["Mild"]
    force(monkeypatch, c, 0.99)
    for _ in range(DAILY_QUOTA):
        await navi.on_message(make_message(CASTER, "navi <@2>", mentions=[TARGET]))
    assert get_daily_action_count(env, CASTER.id) == DAILY_QUOTA
    before = points(env, TARGET.id)
    blocked = make_message(CASTER, "navi <@2>", mentions=[TARGET])
    await navi.on_message(blocked)
    assert points(env, TARGET.id) == before  # blocked, no change
    assert "/shop buy" in blocked.reply.await_args.args[0]


async def test_extra_actions_allow_over_quota_and_are_consumed(env, monkeypatch):
    c = BY_TIER["Mild"]
    force(monkeypatch, c, 0.99)
    for _ in range(DAILY_QUOTA):
        await navi.on_message(make_message(CASTER, "navi <@2>", mentions=[TARGET]))
    add_extra_actions(env, CASTER.id, 2)
    await navi.on_message(make_message(CASTER, "navi <@2>", mentions=[TARGET]))
    assert get_extra_actions(env, CASTER.id) == 1
    assert get_daily_action_count(env, CASTER.id) == DAILY_QUOTA + 1


async def test_potion_echo_sign_follows_first_curse(env, monkeypatch):
    """Multiplier Potion: the 2nd curse reverses iff the 1st did."""
    c = BY_TIER["Mild"]
    grant_perk(env, CASTER.id, "multiplier_potion", 1)
    captured = []

    def fake_task(coro):
        captured.append(coro)
        return None

    async def no_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "create_task", fake_task)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    force(monkeypatch, c, 0.99)  # first lands
    msg = make_message(CASTER, "navi <@2>", mentions=[TARGET])
    await navi.on_message(msg)
    await captured.pop()
    assert points(env, TARGET.id) == -2 * c["target_damage"]
    assert points(env, CASTER.id) == 2 * c["invoker_reward"]

    env.execute("UPDATE users SET boli_points = 0")
    env.commit()
    force(monkeypatch, c, 0.0)  # first backfires
    await navi.on_message(make_message(CASTER, "navi <@2>", mentions=[TARGET]))
    await captured.pop()
    assert points(env, CASTER.id) == -2 * c["target_damage"]
    assert points(env, TARGET.id) == 2 * c["target_damage"]


# ------------------------------ bless -----------------------------------

def bless(monkeypatch, compliment, universal_roll):
    monkeypatch.setattr(curse_commands, "get_random_compliment", lambda: compliment)
    monkeypatch.setattr(random, "random", lambda: universal_roll)


@pytest.mark.parametrize("comp", COMPLIMENTS[::6])
async def test_bless_caster_share_minimum_one(env, monkeypatch, comp):
    bless(monkeypatch, comp, 0.99)
    await navi.on_message(make_message(CASTER, "chunk <@2>", mentions=[TARGET]))
    tp = comp["points"]
    cp = max(1, round(tp * comp["caster_share_pct"] / 100))
    assert points(env, TARGET.id) == tp and xp(env, TARGET.id) == tp
    assert points(env, CASTER.id) == cp and xp(env, CASTER.id) == cp


async def test_bless_minimum_one_for_tiny_share(env, monkeypatch):
    bless(monkeypatch, {"word": "w", "points": 1, "caster_share_pct": 15}, 0.99)
    await navi.on_message(make_message(CASTER, "chunk <@2>", mentions=[TARGET]))
    assert points(env, CASTER.id) == 1


async def test_universal_blessing_gives_100_both(env, monkeypatch):
    bless(monkeypatch, COMPLIMENTS[0], 0.0)
    await navi.on_message(make_message(CASTER, "chunk <@2>", mentions=[TARGET]))
    assert points(env, TARGET.id) == 100 and points(env, CASTER.id) == 100


async def test_self_bless_target_only(env, monkeypatch):
    bless(monkeypatch, COMPLIMENTS[0], 0.99)
    await navi.on_message(make_message(CASTER, "chunk"))
    assert points(env, CASTER.id) == COMPLIMENTS[0]["points"]


async def test_cursing_someone_who_never_posted_is_still_recorded(db, monkeypatch):
    """The old curse_logs table kept such rows; the ledger needs a profile, so the target gets one."""
    from navi.db.repos.points import get_bless_leaderboard, get_curse_leaderboard

    ctx = make_ctx(db)
    seed(db, CASTER)
    ghost = FakeUser(77, "ghost")
    force(monkeypatch, BY_TIER["Mild"], 0.99)
    await pipeline.on_message(ctx, make_message(CASTER, "navi <@77>", mentions=[ghost]))
    assert points(db, 77) == -BY_TIER["Mild"]["target_damage"]
    assert get_curse_leaderboard(db)[0]["username"] == "ghost"
    bless(monkeypatch, COMPLIMENTS[0], 0.99)
    await pipeline.on_message(ctx, make_message(CASTER, "chunk <@77>", mentions=[ghost]))
    assert get_bless_leaderboard(db)[0]["username"] == "ghost"
