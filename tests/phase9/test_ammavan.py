"""Ammavan (proxy-curse / AI-chat bot): rare curse-back, frequent playful reply; every other bot, and Navi's own loops, stay out."""
import pytest

from navi.data import curse_data
from navi.handlers import pipeline
from navi.handlers.kochi import handle_kochi
from navi.llm.safety import SafetyFilter
from navi.services import ammavan as am
from tests.legacy.harness import BOT_ID, FakeLLM, FakeUser, make_ctx, make_message

AMMAVAN = FakeUser(900, "Ammavan", is_bot=True)
OTHER_BOT = FakeUser(901, "SomeBot", is_bot=True)
ASHA = FakeUser(5, "asha")
HIT, MISS = (lambda: 0.0), (lambda: 0.99)
CH = 10


@pytest.fixture()
def ctx(db):
    c = make_ctx(db, llm=FakeLLM("Quite the answer, that."))
    c.settings.set("ammavan.bot_ids", [900])
    c.bot.user.mentioned_in = lambda m: False
    return c


def msg(author, content, ref_id=None, mid=1, channel=CH):
    m = make_message(author, content)
    m.id, m.channel.id = mid, channel
    if ref_id is not None:
        m.reference = type("Ref", (), {"message_id": ref_id, "resolved": None, "cached_message": None})()
    return m


# ------------------------------------------------------------------------------ Kochi

async def test_kochi_mocking_is_off_by_default_and_never_replies(db, monkeypatch):
    ctx = make_ctx(db)
    monkeypatch.setattr("navi.handlers.kochi.random.random", lambda: 0.0)
    m = make_message(ASHA, "machane adipoli")
    assert ctx.settings.get("feature.kochi_replies") is False
    assert await handle_kochi(ctx, m) is False and m.reply.await_count == 0


# ------------------------------------------------------------------------------ curse back

async def test_curse_back_when_ammavan_proxy_curses(ctx):
    am.track_human(ctx, msg(ASHA, ". <@7> you there", mid=1), now=100)
    reply = msg(AMMAVAN, "poda <@7> you there", mid=2)
    assert await am.handle_ammavan(ctx, reply, rand=HIT, now=102) is True
    sent = reply.reply.await_args
    assert sent.args[0] and not sent.args[0].lstrip().startswith(".") and sent.kwargs["allowed_mentions"].users is False
    assert ctx.llm.requests == []                                        # a reviewed template, never the LLM


async def test_curse_back_chance_is_five_percent(ctx):
    am.track_human(ctx, msg(ASHA, ". hello"), now=100)
    reply = msg(AMMAVAN, "poda hello")
    assert ctx.settings.get("chance.ammavan_curse_back") == 0.05
    assert await am.handle_ammavan(ctx, reply, rand=lambda: 0.06, now=101) is False and reply.reply.await_count == 0


@pytest.mark.parametrize("gap,content", [(20, "poda hello"), (2, "unrelated thing from ammavan")])
async def test_not_a_proxy_curse_when_too_late_or_text_does_not_match(ctx, gap, content):
    am.track_human(ctx, msg(ASHA, ". hello"), now=100)
    reply = msg(AMMAVAN, content)
    assert await am.handle_ammavan(ctx, reply, rand=HIT, now=100 + gap) is False


async def test_ammavans_other_interactions_are_left_alone(ctx):
    reply = msg(AMMAVAN, "Daily reward claimed! You now have 500 coins.")
    assert await am.handle_ammavan(ctx, reply, rand=HIT, now=100) is False and reply.reply.await_count == 0


# ------------------------------------------------------------------------------ witty reply

async def test_witty_remark_on_ammavans_ai_answer(ctx):
    trigger = msg(ASHA, "ammava what is the capital of Kerala", mid=50)
    am.track_human(ctx, trigger, now=100)
    answer = msg(AMMAVAN, "The capital of Kerala is Thiruvananthapuram.", ref_id=50, mid=51)
    assert await am.handle_ammavan(ctx, answer, rand=HIT, now=103) is True
    assert answer.reply.await_args.args[0] == "Quite the answer, that."
    prompt = ctx.llm.requests[0]["req"].prompt
    assert "Thiruvananthapuram" in prompt and "ammava what" not in prompt          # sees Ammavan's answer, not the person's question
    assert "community" in prompt and "never any person" in prompt and "Kerala" in prompt


async def test_reply_chance_is_thirty_percent(ctx):
    am.track_human(ctx, msg(ASHA, "ammava hi", mid=50), now=100)
    answer = msg(AMMAVAN, "Hello there!", ref_id=50)
    assert ctx.settings.get("chance.ammavan_witty_reply") == 0.30
    assert await am.handle_ammavan(ctx, answer, rand=lambda: 0.31, now=101) is False and ctx.llm.requests == []
    assert await am.handle_ammavan(ctx, answer, rand=lambda: 0.29, now=102) is True


async def test_reply_sees_what_ammavan_said_and_what_was_asked_even_in_manglish(ctx):
    am.track_human(ctx, msg(ASHA, "ammava ponmudi evide aanu <@7>?", mid=50), now=100)
    answer = msg(AMMAVAN, "Ponmudi Thiruvananthapuram-il aanu, ente mone.", ref_id=50)
    assert await am.handle_ammavan(ctx, answer, rand=HIT, now=101) is True
    prompt = ctx.llm.requests[0]["req"].prompt
    assert 'Someone asked Ammavan: "ponmudi evide aanu ?"' in prompt and "Ponmudi Thiruvananthapuram-il aanu" in prompt
    assert "Manglish" in prompt and "reply in English only" in prompt


async def test_ai_answer_must_follow_an_ammava_text_and_reply_to_it(ctx):
    am.track_human(ctx, msg(ASHA, "Ammava hi", mid=50), now=100)                   # capital A: not Ammavan's trigger
    assert await am.handle_ammavan(ctx, msg(AMMAVAN, "Hello!", mid=51), rand=HIT, now=101) is False
    am.track_human(ctx, msg(ASHA, "ammava hi", mid=60), now=200)
    assert await am.handle_ammavan(ctx, msg(AMMAVAN, "Hello!", ref_id=999), rand=HIT, now=201) is False      # reply to something else
    assert await am.handle_ammavan(ctx, msg(AMMAVAN, "Hello!", ref_id=60), rand=HIT, now=240) is False      # too late


async def test_no_remark_when_the_model_fails_or_answers_from_cache(db):
    ctx = make_ctx(db, llm=FakeLLM("cached text", from_cache=True))
    ctx.settings.set("ammavan.bot_ids", [900])
    am.track_human(ctx, msg(ASHA, "ammava hi", mid=50), now=100)
    answer = msg(AMMAVAN, "Hello there!", ref_id=50)
    assert await am.handle_ammavan(ctx, answer, rand=HIT, now=101) is False and answer.reply.await_count == 0


async def test_replies_never_start_with_a_dot_or_ammava(db):
    for text in (". sneaky", "Ammavan is wise", "ammava knows"):
        ctx = make_ctx(db, llm=FakeLLM(text))
        ctx.settings.set("ammavan.bot_ids", [900])
        am.track_human(ctx, msg(ASHA, "ammava hi", mid=50), now=100)
        answer = msg(AMMAVAN, "Hello there!", ref_id=50)
        await am.handle_ammavan(ctx, answer, rand=HIT, now=101)
        out = answer.reply.await_args.args[0]
        assert not out.lstrip().startswith(".") and not out.lower().startswith("ammava"), out


# ------------------------------------------------------------------------------ not interfering

async def test_only_the_configured_ammavan_id_is_ever_answered(ctx):
    am.track_human(ctx, msg(ASHA, ". hello"), now=100)
    other = msg(OTHER_BOT, "poda hello")
    assert await am.handle_ammavan(ctx, other, rand=HIT, now=101) is False and other.reply.await_count == 0


async def test_switched_off_or_without_an_id_nothing_happens(ctx):
    am.track_human(ctx, msg(ASHA, ". hello"), now=100)
    ctx.settings.set("feature.ammavan_reactions", False)
    assert await am.handle_ammavan(ctx, msg(AMMAVAN, "poda hello"), rand=HIT, now=101) is False
    ctx.settings.set("feature.ammavan_reactions", True)
    ctx.settings.set("ammavan.bot_ids", [])
    assert await am.handle_ammavan(ctx, msg(AMMAVAN, "poda hello"), rand=HIT, now=101) is False


async def test_no_loop_when_ammavan_replies_to_navi(ctx):
    am.track_human(ctx, msg(ASHA, ". hello"), now=100)
    reply = msg(AMMAVAN, "poda hello")
    parent = type("Parent", (), {"author": FakeUser(BOT_ID, "Navi", is_bot=True)})()
    reply.reference = type("Ref", (), {"message_id": 1, "resolved": parent, "cached_message": None})()
    assert await am.handle_ammavan(ctx, reply, rand=HIT, now=101) is False


async def test_one_reaction_per_channel_per_minute(ctx):
    am.track_human(ctx, msg(ASHA, ". hello"), now=100)
    assert await am.handle_ammavan(ctx, msg(AMMAVAN, "poda hello"), rand=HIT, now=101) is True
    assert await am.handle_ammavan(ctx, msg(AMMAVAN, "poda hello"), rand=HIT, now=130) is False
    am.track_human(ctx, msg(ASHA, ". again"), now=170)
    assert await am.handle_ammavan(ctx, msg(AMMAVAN, "poda again"), rand=HIT, now=171) is True


async def test_opted_out_people_are_never_involved(ctx):
    ctx.privacy.is_opted_out = lambda uid: uid == 7
    am.track_human(ctx, msg(ASHA, ". <@7> hello"), now=100)
    assert await am.handle_ammavan(ctx, msg(AMMAVAN, "poda <@7> hello"), rand=HIT, now=101) is False       # the target opted out
    ctx.privacy.is_opted_out = lambda uid: uid == 5
    am.track_human(ctx, msg(ASHA, ". hello"), now=300)
    assert await am.handle_ammavan(ctx, msg(AMMAVAN, "poda hello"), rand=HIT, now=301) is False            # the sender opted out


# ------------------------------------------------------------------------------ pipeline

async def test_pipeline_routes_only_ammavan_and_ignores_every_other_bot(ctx, monkeypatch):
    monkeypatch.setattr("navi.services.ammavan.random.random", lambda: 0.0)
    await pipeline.on_message(ctx, msg(ASHA, ". hello", mid=1))
    other = msg(OTHER_BOT, "poda hello", mid=2)
    await pipeline.on_message(ctx, other)
    assert other.reply.await_count == 0
    a = msg(AMMAVAN, "poda hello", mid=3)
    await pipeline.on_message(ctx, a)
    assert a.reply.await_count == 1


async def test_pipeline_survives_an_error_in_the_ammavan_path(ctx, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr("navi.services.ammavan.handle_ammavan", boom)
    await pipeline.on_message(ctx, msg(AMMAVAN, "anything"))                      # must not raise


# ------------------------------------------------------------------------------ Navi never triggers Ammavan

@pytest.mark.parametrize("text,ok", [(". hi", False), ("  .hi", False), ("ammava hi", False), ("Ammavan hi", False), ("hello .", True),
                                     ("The cosmos says hi", True), ("Mama, ammavan is great", True)])
def test_safety_filter_rejects_texts_that_would_trigger_ammavan(text, ok):
    assert SafetyFilter().check(text, "qa").ok is ok


def test_static_navi_texts_never_start_with_a_dot_or_ammava():
    from navi.data.messages import FALLBACK_MESSAGES

    pools = [FALLBACK_MESSAGES, curse_data.CURSE_BACK_REPLIES, curse_data.DOOMED_PREDICTIONS, curse_data.KOCHI_SLANG_RESPONSES]
    for text in (t for pool in pools for t in pool):
        assert not text.lstrip().startswith(".") and not text.lstrip().lower().startswith("ammava"), text


async def test_missing_channel_access_is_logged_not_raised(ctx):
    import discord

    async def forbidden(*a, **k):
        raise discord.Forbidden(type("R", (), {"status": 403, "reason": "Forbidden"})(), "Missing Access")

    m = msg(ASHA, "hello")
    m.channel.typing = forbidden
    original = pipeline.HANDLERS[:]
    pipeline.HANDLERS[:] = [forbidden]
    try:
        await pipeline.on_message(ctx, m)                                          # must not raise
    finally:
        pipeline.HANDLERS[:] = original
