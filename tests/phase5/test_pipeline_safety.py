"""Safety wired into the router, the passive curse reply, the template pool and the bot's mention settings."""
import json
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from navi.app import build
from navi.data.curse_data import CURSE_BACK_REPLIES, DOOMED_PREDICTIONS
from navi.db.repos.users import upsert_user
from navi.handlers.passive_curse import handle_passive_curse
from navi.llm.base import LLMRequest
from navi.llm.policy import build_policy
from navi.llm.router import LLMRouter
from navi.services import mentions, template_pool
from navi.services.predictions import get_navi_prediction
from navi.services.template_pool import (fill, generate_batch, parse_batch, pick, seed_templates, store_generated,
                                         store_rejected, validate_candidate)
from tests.legacy.harness import FakeLLM, FakeUser, make_config, make_ctx, make_message, points, seed
from tests.phase1.test_llm_router import FakeProvider


# ------------------------------------------------------------------- router

class SpyProvider(FakeProvider):
    def __init__(self, text):
        super().__init__(text)
        self.systems = []

    async def generate(self, req, key=None):
        self.systems.append(req.system)
        return await super().generate(req, key)


async def test_policy_is_appended_to_every_system_prompt(db):
    prov = SpyProvider("ok")
    r = LLMRouter(prov, rpm_limit=100)
    r.policy = build_policy(db)
    for purpose in ("qa", "summary", "mod", "prediction", "vibe"):
        await r.generate(LLMRequest(purpose=purpose, system="BASE", prompt="p"), fallback="FB")
    assert len(prov.systems) == 5 and all(s.startswith("BASE") and "CONTENT RULES" in s for s in prov.systems)


async def test_blocked_reply_becomes_fallback_and_is_recorded(db, blocked):
    prov = FakeProvider("well zorgblat to you")
    r = LLMRouter(prov, rpm_limit=100)
    seen = []
    r.on_reject = lambda req, text, reasons: seen.append((req.purpose, text, reasons))
    res = await r.generate(LLMRequest(purpose="qa", system="s", prompt="p"), fallback="FALLBACK TEXT")
    assert (res.text, res.outcome, res.from_cache) == ("FALLBACK TEXT", "safety", True)
    assert seen == [("qa", "well zorgblat to you", ["blocklist"])]


def test_store_rejected_keeps_the_text_for_review_and_logs_an_event(db):
    store_rejected(db, "qa_answer", "bad reply", ["blocklist", "mention"])
    assert db.execute("SELECT status, source FROM content WHERE text='bad reply'").fetchone()[0] == "rejected"
    ev = db.execute("SELECT kind, name, detail FROM events").fetchone()
    assert (ev[0], ev[1], json.loads(ev[2])) == ("safety_reject", "qa_answer", {"reasons": ["blocklist", "mention"]})


async def test_clean_reply_passes_untouched(db, blocked):
    r = LLMRouter(FakeProvider("a perfectly nice answer"), rpm_limit=100)
    res = await r.generate(LLMRequest(purpose="qa", system="s", prompt="p"), fallback="FB")
    assert (res.text, res.outcome) == ("a perfectly nice answer", "ok")


# ------------------------------------------------------------------- passive curse: template only

class ExplodingLLM(FakeLLM):
    async def generate(self, *a, **k):
        raise AssertionError("the passive curse reply must not call the LLM")

    async def cache_only(self, *a, **k):
        raise AssertionError("the passive curse reply must not touch the LLM router")


@pytest.fixture()
def curse_env(db, monkeypatch):
    ctx = make_ctx(db, llm=ExplodingLLM())
    seed_templates(db)
    seed(db, FakeUser(1, "asha"))
    monkeypatch.setattr(random, "random", lambda: 0.0)          # always under the 25% chance

    async def no_sleep(_):
        return None

    monkeypatch.setattr("asyncio.sleep", no_sleep)
    return ctx


async def test_passive_curse_makes_no_llm_calls_and_keeps_the_boli_award(curse_env):
    ctx = curse_env
    msg = make_message(FakeUser(1, "asha"), "you absolute mandan")
    await handle_passive_curse(ctx, msg)
    assert points(ctx.db, 1) == 1                                         # +1 Boli exactly as before
    assert ctx.db.execute("SELECT experience FROM users WHERE user_id=1").fetchone()[0] == 1
    assert ctx.db.execute("SELECT reason, detail FROM points_ledger WHERE user_id=1").fetchone()[:] == ("curse_word_said", "mandan")
    reply = msg.reply.await_args.args[0]
    assert "{user}" not in reply and "{curse}" not in reply
    assert reply in {fill(t, "asha", "mandan") for t in (*DOOMED_PREDICTIONS, *CURSE_BACK_REPLIES)}
    assert [u.id for u in msg.reply.await_args.kwargs["allowed_mentions"].users] == [1]  # can only ping the author


async def test_passive_curse_respects_chance_and_switch(curse_env, monkeypatch):
    ctx = curse_env
    monkeypatch.setattr(random, "random", lambda: 0.99)
    msg = make_message(FakeUser(1, "asha"), "mandan")
    await handle_passive_curse(ctx, msg)
    assert msg.reply.await_count == 0 and points(ctx.db, 1) == 0
    monkeypatch.setattr(random, "random", lambda: 0.0)
    ctx.settings.set("feature.passive_curse_replies", False)
    await handle_passive_curse(ctx, msg)
    assert msg.reply.await_count == 0
    await handle_passive_curse(make_ctx(ctx.db, llm=ExplodingLLM()), make_message(FakeUser(1, "asha"), "nothing rude here"))


async def test_passive_curse_with_an_empty_pool_falls_back_to_the_built_in_lines(db, monkeypatch):
    ctx = make_ctx(db, llm=ExplodingLLM())
    seed(db, FakeUser(1, "asha"))
    monkeypatch.setattr(random, "random", lambda: 0.0)
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    msg = make_message(FakeUser(1, "asha"), "mandan")
    await handle_passive_curse(ctx, msg)
    assert msg.reply.await_count == 1


def test_pick_avoids_the_last_five_templates_for_a_user(db):
    ctx = make_ctx(db)
    for i in range(8):
        db.execute("INSERT INTO content (kind, text, status, source) VALUES ('curse_back', ?, 'active', 'seed')", [f"line {i} for {{user}} {{curse}}"])
    db.commit()
    got = [pick(ctx, "curse_back", 1, "asha", "mandan") for _ in range(8)]
    for i in range(5, 8):
        assert len(set(got[i - 5:i + 1])) == 6, got                      # any 6 in a row are all different
    assert all("asha" in g and "mandan" in g for g in got)
    other = pick(ctx, "curse_back", 2, "ben", "kozhi")
    assert "ben" in other                                               # recent-list is per user
    db.execute("UPDATE content SET status='pending' WHERE kind='curse_back'")
    db.commit()
    assert pick(ctx, "curse_back", 1, "asha") is None                    # only active templates are served


def test_pick_repeats_when_the_pool_is_tiny(db):
    ctx = make_ctx(db)
    db.execute("INSERT INTO content (kind, text, status, source) VALUES ('curse_back', 'only {user}', 'active', 'seed')")
    db.commit()
    assert [pick(ctx, "curse_back", 1, "a") for _ in range(3)] == ["only a"] * 3


def test_seed_templates_is_idempotent_and_marked_seed(db):
    n = seed_templates(db)
    assert n == len(set(DOOMED_PREDICTIONS) | set(CURSE_BACK_REPLIES)) and seed_templates(db) == 0
    assert db.execute("SELECT DISTINCT source, status FROM content WHERE kind='curse_back'").fetchall()[0][:] == ("seed", "active")


def test_get_curse_prompt_and_the_curse_cache_path_are_gone():
    import navi.llm.prompts as prompts
    from pathlib import Path

    assert not hasattr(prompts, "get_curse_prompt")
    assert 'cache_type="curse"' not in "".join(p.read_text() for p in Path("navi").rglob("*.py"))


# ------------------------------------------------------------------- generated templates

def test_parse_batch_tolerates_fences_and_chatter():
    assert parse_batch('Sure!\n```json\n["a {user}", "b {user}"]\n```') == ["a {user}", "b {user}"]
    assert parse_batch("no json here") == [] and parse_batch("[1, 2]") == [] and parse_batch('{"a": 1}') == []


def test_validate_candidate_rules(blocked):
    ok = "Bad luck for {user}, the bus leaves a minute early."
    assert validate_candidate(ok, "curse_back", []) is None
    assert validate_candidate("The bus leaves early.", "curse_back", []) == "no_user_placeholder"
    assert validate_candidate("{user} " + "word " * 15, "curse_back", []) == "too_long"
    assert validate_candidate("{user} " + "word " * 15, "prediction", []) is None           # predictions may use 25 words
    assert validate_candidate("{user} meets a zorgblat today", "curse_back", []) == "unsafe"
    assert validate_candidate("Bad luck for {user}, the bus leaves a minute early!", "curse_back", [ok]) == "near_duplicate"
    assert validate_candidate("{user}'s chai goes cold at the worst moment.", "curse_back", [ok]) is None


def test_store_generated_status_follows_auto_approve_and_safety(db, blocked):
    ctx = make_ctx(db)
    assert store_generated(ctx, "curse_back", "Cold chai for {user}.") == "pending"
    ctx.settings.set("safety.template_auto_approve", True)
    assert store_generated(ctx, "curse_back", "Late bus for {user}.") == "active"
    assert store_generated(ctx, "curse_back", "{user} zorgblat") == "rejected"
    assert dict(db.execute("SELECT text, status FROM content WHERE source='llm'")) == {
        "Cold chai for {user}.": "pending", "Late bus for {user}.": "active", "{user} zorgblat": "rejected"}


async def test_generate_batch_validates_and_queues_for_review(db, blocked):
    batch = json.dumps(["Cold chai for {user}.", "Cold chai for {user}!", "no placeholder here", "{user} zorgblat", "Late bus for {user}.", 42])
    ctx = make_ctx(db, llm=FakeLLM(text=batch))
    ctx.settings.set("safety.template_batch_size", 6)
    stats = await generate_batch(ctx, "curse_back")
    assert stats["added"] == 2 and stats["near_duplicate"] == 1 and stats["no_user_placeholder"] == 1 and stats["unsafe"] == 1
    assert {r[0]: r[1] for r in db.execute("SELECT text, status FROM content")} == {"Cold chai for {user}.": "pending", "Late bus for {user}.": "pending"}
    req = ctx.llm.requests[0]["req"]
    assert req.purpose == "template_batch" and "6" in req.prompt and "{user}" in req.prompt and "15 words" in req.prompt


async def test_generate_batch_without_a_live_reply_adds_nothing(db):
    ctx = make_ctx(db, llm=FakeLLM(text="fallback", from_cache=True))
    assert (await generate_batch(ctx, "prediction"))["no_reply"] == 1
    assert db.execute("SELECT COUNT(*) FROM content").fetchone()[0] == 0


async def test_live_prediction_templates_wait_for_review(db):
    ctx = make_ctx(db, llm=FakeLLM(text="Asha, doom awaits at Kowdiar."))
    upsert_user(db, 5, "Asha")
    await get_navi_prediction(ctx, 5, "Asha", 1)
    assert db.execute("SELECT status, text FROM content WHERE kind='prediction'").fetchone()[:] == ("pending", "{user}, doom awaits at Kowdiar.")


# ------------------------------------------------------------------- mentions

def test_bot_wide_allowed_mentions_block_everyone_and_roles():
    bot, _ = build(make_config())
    am = bot.allowed_mentions
    assert (am.everyone, am.roles, am.users) == (False, False, True)


def test_only_user_and_nobody():
    am = mentions.only_user(SimpleNamespace(id=5), 6)
    assert (am.everyone, am.roles, [u.id for u in am.users]) == (False, False, [5, 6])
    assert am.to_dict() == {"parse": [], "users": [5, 6], "replied_user": True}          # what discord.py actually sends (the real library, not a fake)
    assert mentions.nobody().users is False and mentions.nobody().everyone is False


def test_llm_text_sends_use_restricted_mentions():
    from pathlib import Path

    for rel, needle in (("handlers/mention_qa.py", "allowed_mentions=only_user"), ("handlers/vibe.py", "allowed_mentions=nobody()"),
                        ("cogs/summaries.py", "allowed_mentions=nobody()"), ("cogs/predictions.py", "allowed_mentions=only_user"),
                        ("handlers/passive_curse.py", "allowed_mentions=only_user")):
        assert needle in Path("navi", rel).read_text(), rel
