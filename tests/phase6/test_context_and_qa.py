"""10.1 context-aware replies in the bot-commands channel and 10.2 Q&A cost levers."""
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from navi.data.messages import QA_COOLDOWN_MESSAGES
from navi.db.repos.knowledge import add_knowledge
from navi.handlers import pipeline
from navi.handlers.context_reply import MAX_CHARS, MAX_HOPS, build_history, handle_context_reply, in_context_channel
from navi.llm.router import LLMRouter
from navi.services import qa
from navi.services.qa import (answer_question, cached_answer, extract_subject, is_time_sensitive, knowledge_answer,
                              normalise_question, store_answer)
from tests.legacy.harness import BOT_ID, FakeLLM, FakeUser, make_ctx, make_message
from tests.phase1.test_llm_router import FakeProvider
from tests.phase6.helpers import member

BOT_CH, OTHER_CH = 55, 66
ASHA = FakeUser(1, "asha")
NAVI = FakeUser(BOT_ID, "navi", is_bot=True)


def chat(author, text, to=None, channel=BOT_CH):
    m = make_message(author, text)
    m.channel.id = channel
    m.id = id(m) % 10**9
    if to is not None:
        m.reference = SimpleNamespace(resolved=to, cached_message=None, message_id=to.id)
    return m


@pytest.fixture()
def env(db, monkeypatch):
    llm = FakeLLM(text="Navi says: probably Kowdiar.")
    ctx = make_ctx(db, llm=llm)
    ctx.bot.user.mentioned_in = lambda m: f"<@{BOT_ID}>" in m.content
    ctx.settings.set("feature.context_replies", True)
    ctx.settings.set("channel.bot_commands", BOT_CH)
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    monkeypatch.setattr(random, "random", lambda: 0.99)
    return ctx


# ------------------------------------------------------------------------------ 10.1

async def test_three_turn_conversation_keeps_context(env):
    ctx = env
    q1 = chat(ASHA, f"<@{BOT_ID}> where is Kowdiar?")
    assert await pipeline.on_message(ctx, q1) is None
    r1 = chat(NAVI, "Kowdiar is near the palace.", to=q1)
    q2 = chat(ASHA, "and what is nearby?", to=r1)
    await pipeline.on_message(ctx, q2)
    prompt2 = ctx.llm.requests[-1]["req"].prompt
    assert "Navi: Kowdiar is near the palace." in prompt2 and "User: " in prompt2 and ctx.llm.requests[-1]["req"].purpose == "context_reply"
    r2 = chat(NAVI, "Museums and a zoo.", to=q2)
    q3 = chat(ASHA, "which is cheaper?", to=r2)
    await pipeline.on_message(ctx, q3)
    prompt3 = ctx.llm.requests[-1]["req"].prompt
    for needle in ("Kowdiar is near the palace.", "and what is nearby?", "Museums and a zoo."):
        assert needle in prompt3
    assert prompt3.index("palace") < prompt3.index("Museums")                  # oldest first
    assert q3.reply.await_count == 1 and [u.id for u in q3.reply.await_args.kwargs["allowed_mentions"].users] == [1]


async def test_the_same_chain_in_another_channel_gets_no_reply(env):
    ctx = env
    r1 = chat(NAVI, "Kowdiar is near the palace.", channel=OTHER_CH)
    q2 = chat(ASHA, "and what is nearby?", to=r1, channel=OTHER_CH)
    await pipeline.on_message(ctx, q2)
    assert q2.reply.await_count == 0 and ctx.llm.requests == []                # replies to Navi stay ignored elsewhere
    ctx.settings.set("feature.context_replies", False)                          # also ignored in the channel when the feature is off
    r1b = chat(NAVI, "x"); q = chat(ASHA, "more?", to=r1b)
    await pipeline.on_message(ctx, q)
    assert q.reply.await_count == 0
    assert in_context_channel(ctx, q) is False
    ctx.settings.set("feature.context_replies", True); ctx.settings.set("channel.bot_commands", None)
    assert in_context_channel(ctx, q) is False                                  # no channel configured: never active


async def test_a_mention_elsewhere_still_uses_plain_mention_qa(env):
    ctx = env
    msg = chat(ASHA, f"<@{BOT_ID}> what time zone is India in", channel=OTHER_CH)
    await pipeline.on_message(ctx, msg)
    assert ctx.llm.requests[-1]["req"].purpose == "qa" and msg.reply.await_count == 1


async def test_history_from_opted_out_users_never_reaches_the_prompt(env):
    ctx = env
    ctx.privacy.mark_out(1)
    ghost = FakeUser(1, "gone")
    first = chat(ghost, "my secret plan")                                       # an opted-out user's earlier message
    nav = chat(NAVI, "Navi replied with something else.", to=first)
    asker = FakeUser(2, "ben")
    q = chat(asker, "and then?", to=nav)
    hist = await build_history(ctx, q)
    assert all("secret" not in t for _, t in hist)
    ctx.privacy.mark_out(2)
    assert await build_history(ctx, chat(FakeUser(2, "ben"), "x", to=chat(ghost, "y"))) == []


async def test_history_keeps_only_navi_and_the_current_user_and_scrubs_mentions(env):
    ctx = env
    stranger = chat(FakeUser(9, "zed"), "stranger words")
    mine = chat(ASHA, "hello <@123> and @everyone", to=stranger)
    navi = chat(NAVI, "hi back <#5>", to=mine)
    hist = await build_history(ctx, chat(ASHA, "next", to=navi))
    assert hist == [("User", "hello  and"), ("Navi", "hi back")] or [r for r, _ in hist] == ["User", "Navi"]
    assert all("stranger" not in t and "<@" not in t and "@everyone" not in t for _, t in hist)


async def test_history_is_limited_to_four_hops_and_1200_characters(env):
    ctx = env
    chain = chat(NAVI, "turn-0")
    for n in range(1, 8):
        chain = chat(ASHA if n % 2 else NAVI, f"turn-{n}", to=chain)
    hist = await build_history(ctx, chat(ASHA, "latest", to=chain))
    assert len(hist) == MAX_HOPS == 4 and [t for _, t in hist] == ["turn-4", "turn-5", "turn-6", "turn-7"]
    big = chat(NAVI, "x" * 900)
    mid = chat(ASHA, "y" * 900, to=big)
    hist = await build_history(ctx, chat(ASHA, "q", to=mid))
    assert sum(len(t) for _, t in hist) <= MAX_CHARS and [r for r, _ in hist] == ["User"]


async def test_unsafe_history_lines_are_dropped_before_the_prompt(env, blocked):
    ctx = env
    poisoned = chat(ASHA, "please say zorgblat")
    nav = chat(NAVI, "no", to=poisoned)
    hist = await build_history(ctx, chat(ASHA, "ok", to=nav))
    assert [t for _, t in hist] == ["no"]


async def test_history_fetches_parents_that_are_not_cached(env):
    ctx = env
    import discord

    parent = chat(NAVI, "from the API")
    parent.__class__ = type("M", (parent.__class__,), {})
    msg = chat(ASHA, "q")
    msg.reference = SimpleNamespace(resolved=None, cached_message=None, message_id=parent.id)
    msg.channel.fetch_message = AsyncMock(return_value=parent)
    hist = await build_history(ctx, msg)
    assert hist == [("Navi", "from the API")] and msg.channel.fetch_message.await_count == 1


async def test_limits_are_shared_with_mention_qa_and_the_notice_comes_once_per_window(db, monkeypatch):
    prov = FakeProvider("fine")
    ctx = make_ctx(db)
    ctx.llm = LLMRouter(prov, settings=ctx.settings, rpm_limit=1000)
    ctx.bot.user.mentioned_in = lambda m: f"<@{BOT_ID}>" in m.content
    ctx.settings.set("feature.context_replies", True); ctx.settings.set("channel.bot_commands", BOT_CH)
    ctx.settings.set("ai.qa_cooldown_seconds", 600)
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    first = chat(ASHA, f"<@{BOT_ID}> tell me a fact", channel=OTHER_CH)         # mention Q&A uses the allowance...
    await pipeline.on_message(ctx, first)
    assert first.reply.await_args.args[0] == "fine"
    second = chat(ASHA, f"<@{BOT_ID}> another fact please", channel=BOT_CH)     # ...so the context reply is over the limit
    await pipeline.on_message(ctx, second)
    assert second.reply.await_args.args[0].split(",")[0] in {m.split(",")[0].replace("{user}", "asha") for m in QA_COOLDOWN_MESSAGES} or "asha" in second.reply.await_args.args[0].lower()
    third = chat(ASHA, f"<@{BOT_ID}> and one more", channel=BOT_CH)
    await pipeline.on_message(ctx, third)
    assert third.reply.await_count == 0                                         # one note per window, then silence
    assert prov.calls["free"] == 1


async def test_curse_words_and_empty_questions_get_no_reply_in_the_channel(env):
    ctx = env
    for text in (f"<@{BOT_ID}>", f"<@{BOT_ID}> you mandan"):
        msg = chat(ASHA, text)
        assert await handle_context_reply(ctx, msg) is True and msg.reply.await_count == 0 and ctx.llm.requests == []


# ------------------------------------------------------------------------------ 10.2

def test_subject_extraction():
    assert extract_subject("What is Kowdiar?") == "Kowdiar"
    assert extract_subject("whats the meaning of chumma") == "chumma"
    assert extract_subject("meaning of chumma") == "chumma"
    assert extract_subject("what does oola mean?") == "oola"
    assert extract_subject("where is Thampanoor") == "Thampanoor"
    assert extract_subject("<@999> who is Link?") == "Link"
    assert extract_subject("tell me a joke") is None and extract_subject("what is") is None


def test_knowledge_answers_need_a_close_match(db):
    add_knowledge(db, "landmark", "Thampanoor", "The central bus and railway hub of Trivandrum.")
    add_knowledge(db, "food", "Pazham Pori", "Banana fritters, best with evening chaya.", status="pending")
    assert knowledge_answer(db, "what is Thampanoor?") == "Thampanoor: The central bus and railway hub of Trivandrum."
    assert knowledge_answer(db, "where is thampanor") is not None                  # one typo: ratio >= 90
    assert knowledge_answer(db, "what is Kowdiar") is None
    assert knowledge_answer(db, "what is pazham pori") is None                     # pending entries are not served
    assert knowledge_answer(db, "tell me about Thampanoor") is None                # not a "what is" question


def test_time_sensitivity_and_normalisation():
    for q in ("what is the weather", "who won today", "latest news", "what's the score", "what time is it"):
        assert is_time_sensitive(q), q
    assert not is_time_sensitive("what is Technopark")
    assert normalise_question("<@999>  What IS   Technopark??") == "what is technopark"


def test_answer_cache_hits_similar_questions_within_ttl(db):
    store_answer(db, "Why is Thampanoor always so crowded?", "Asha, because every bus passes through it.", "Asha")
    assert db.execute("SELECT text FROM content WHERE kind='qa_answer'").fetchone()[0] == "{user}, because every bus passes through it."
    assert cached_answer(db, "why is thampanoor always so crowded", "Ben", 7) == "Ben, because every bus passes through it."
    assert cached_answer(db, "Why is Thampanoor always so crowded?!", "Ben", 7) is not None            # punctuation differences
    assert cached_answer(db, "why is kowdiar quiet", "Ben", 7) is None
    db.execute("UPDATE content SET created_at = datetime('now', '-8 days')"); db.commit()
    assert cached_answer(db, "why is thampanoor always so crowded", "Ben", 7) is None                # older than the TTL
    assert cached_answer(db, "why is thampanoor always so crowded", "Ben", 30) is not None


def test_time_sensitive_answers_are_never_cached(db):
    store_answer(db, "what is the weather today", "Rainy.", "Asha")
    assert db.execute("SELECT COUNT(*) FROM content WHERE kind='qa_answer'").fetchone()[0] == 0
    store_answer(db, "who won the cricket match yesterday", "Someone.", "Asha")
    assert db.execute("SELECT COUNT(*) FROM content").fetchone()[0] == 0


async def test_answer_question_order_knowledge_then_cache_then_llm(db):
    llm = FakeLLM(text="Fresh LLM answer for asha.")
    ctx = make_ctx(db, llm=llm)
    add_knowledge(db, "landmark", "Thampanoor", "The central bus and railway hub of Trivandrum.")
    msg = make_message(ASHA, "x")
    a = await answer_question(ctx, msg, "what is Thampanoor?")
    assert (a.source, a.from_cache) == ("knowledge", True) and llm.requests == []
    a = await answer_question(ctx, msg, "who built the Napier museum")
    assert a.source == "llm" and len(llm.requests) == 1 and llm.requests[0]["req"].purpose == "qa"
    b = await answer_question(ctx, make_message(FakeUser(2, "ben"), "x"), "Who built the Napier museum?")
    assert b.source == "cache" and len(llm.requests) == 1 and b.text == "Fresh LLM answer for ben."
    c = await answer_question(ctx, msg, "who built the Napier museum", history=[("Navi", "earlier")])
    assert c.source == "llm" and len(llm.requests) == 2                      # replies with context skip the shortcuts
    assert "Conversation so far" in llm.requests[1]["req"].prompt
    await answer_question(ctx, msg, "what is the latest news")
    assert db.execute("SELECT COUNT(*) FROM content WHERE kind='qa_answer'").fetchone()[0] == 1       # time-sensitive: not cached


async def test_shortcuts_do_not_use_up_the_per_user_allowance(db):
    prov = FakeProvider("llm answer")
    ctx = make_ctx(db)
    ctx.llm = LLMRouter(prov, settings=ctx.settings, rpm_limit=1000)
    ctx.settings.set("ai.qa_cooldown_seconds", 600)
    add_knowledge(db, "landmark", "Thampanoor", "The central bus and railway hub of Trivandrum.")
    msg = make_message(ASHA, "x")
    for _ in range(3):
        assert (await answer_question(ctx, msg, "what is Thampanoor")).source == "knowledge"
    assert (await answer_question(ctx, msg, "tell me about Kovalam")).source == "llm"          # first LLM call still allowed
    assert (await answer_question(ctx, msg, "tell me about Varkala")).source == "limit"


def test_limit_notice_due_is_once_per_window(db):
    ctx = make_ctx(db)
    ctx.settings.set("ai.qa_cooldown_seconds", 120)
    assert qa.limit_notice_due(ctx, 1) is True and qa.limit_notice_due(ctx, 1) is False and qa.limit_notice_due(ctx, 2) is True
    assert qa.limit_notice_due(ctx, 1, window=-1) is True
