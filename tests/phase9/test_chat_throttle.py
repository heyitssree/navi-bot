"""AI conversation is rate-limited outside the bot-commands channel: 4 per 5 minutes, one redirect note, 5 quiet minutes. Nothing else is touched."""
from unittest.mock import AsyncMock

import pytest

from navi.handlers.mention_qa import handle_mention_qa
from navi.services import chat_throttle as ct
from tests.legacy.harness import BOT_ID, FakeLLM, FakeUser, make_ctx, make_message

FREE = 777
GENERAL = 10


@pytest.fixture()
def ctx(db):
    c = make_ctx(db, llm=FakeLLM())
    c.settings.set("channel.bot_commands", FREE)
    c.bot.user.mentioned_in = lambda m: f"<@{BOT_ID}>" in m.content
    return c


def test_fifth_attempt_in_five_minutes_is_redirected_then_silent_then_fresh(ctx):
    t = 1000.0
    assert [ct.check(ctx, 1, GENERAL, t + i) for i in range(4)] == [ct.ALLOW] * 4
    assert ct.check(ctx, 1, GENERAL, t + 5) == ct.REDIRECT                       # the 5th call
    assert ct.check(ctx, 1, GENERAL, t + 6) == ct.SILENT                         # no second note
    assert ct.check(ctx, 1, GENERAL, t + 5 + 299) == ct.SILENT                   # still inside the 5 quiet minutes
    assert ct.check(ctx, 1, GENERAL, t + 5 + 301) == ct.ALLOW                    # quiet time over: a fresh allowance of 4 (this is #1)
    assert [ct.check(ctx, 1, GENERAL, t + 400 + i) for i in range(3)] == [ct.ALLOW] * 3     # #2 to #4
    assert ct.check(ctx, 1, GENERAL, t + 404) == ct.REDIRECT                     # #5 inside the window


def test_slow_talkers_are_never_limited(ctx):
    assert all(ct.check(ctx, 1, GENERAL, 1000 + i * 100) == ct.ALLOW for i in range(20))      # one call every 100 s


def test_bot_commands_channel_is_unlimited_and_does_not_count(ctx):
    assert all(ct.check(ctx, 1, FREE, 1000 + i) == ct.ALLOW for i in range(50))
    assert [ct.check(ctx, 1, GENERAL, 1100 + i) for i in range(4)] == [ct.ALLOW] * 4          # the 50 above used no allowance


def test_in_the_quiet_period_bot_commands_still_works(ctx):
    for i in range(5):
        ct.check(ctx, 1, GENERAL, 1000 + i)
    assert ct.check(ctx, 1, GENERAL, 1010) == ct.SILENT and ct.check(ctx, 1, FREE, 1010) == ct.ALLOW


def test_each_person_has_their_own_allowance(ctx):
    for i in range(5):
        ct.check(ctx, 1, GENERAL, 1000 + i)
    assert ct.check(ctx, 2, GENERAL, 1006) == ct.ALLOW


def test_switched_off_or_without_a_bot_commands_channel_nothing_is_limited(ctx):
    ctx.settings.set("feature.chat_redirect", False)
    assert all(ct.check(ctx, 1, GENERAL, 1000 + i) == ct.ALLOW for i in range(20))
    ctx.settings.set("feature.chat_redirect", True)
    ctx.settings.set("channel.bot_commands", None)
    assert all(ct.check(ctx, 2, GENERAL, 1000 + i) == ct.ALLOW for i in range(20))


def test_numbers_are_settings(ctx):
    ctx.settings.set("chat.redirect_calls", 2)
    ctx.settings.set("chat.redirect_cooldown_seconds", 60)
    assert [ct.check(ctx, 1, GENERAL, 1000 + i) for i in range(3)] == [ct.ALLOW, ct.ALLOW, ct.REDIRECT]
    assert ct.check(ctx, 1, GENERAL, 1061) == ct.SILENT and ct.check(ctx, 1, GENERAL, 1063) == ct.ALLOW


def test_redirect_note_names_the_channel_and_the_minutes(ctx):
    text = ct.redirect_text(ctx, FakeUser(1, "asha"))
    assert "asha" in text and f"<#{FREE}>" in text and "5 minutes" in text


async def test_handler_answers_four_then_redirects_once_then_ignores(ctx):
    asha = FakeUser(1, "asha")
    sent = []
    for n in range(8):
        msg = make_message(asha, f"<@{BOT_ID}> what is Technopark {n}?")
        assert await handle_mention_qa(ctx, msg) is True                   # always consumed: never falls through to other handlers
        sent.append(msg.reply.await_count)
    assert sent == [1, 1, 1, 1, 1, 0, 0, 0]                                # 4 answers, 1 redirect note, then silence
    assert len(ctx.llm.requests) <= 4                                       # the redirect and the silence never reach the model


async def test_handler_in_bot_commands_never_limits(ctx):
    asha = FakeUser(1, "asha")
    for n in range(10):
        msg = make_message(asha, f"<@{BOT_ID}> question number {n}?")
        msg.channel.id = FREE
        await handle_mention_qa(ctx, msg)
        assert msg.reply.await_count == 1 and f"<#{FREE}>" not in msg.reply.await_args.args[0]


async def test_other_features_are_untouched_during_the_quiet_period(ctx):
    asha = FakeUser(1, "asha")
    for n in range(5):
        await handle_mention_qa(ctx, make_message(asha, f"<@{BOT_ID}> hello {n}"))
    plain = make_message(asha, "navi chunk")                                # not a mention: the handler ignores it, so the pipeline continues
    assert await handle_mention_qa(ctx, plain) is False and plain.reply.await_count == 0
    assert isinstance(ctx.bot.application_info, AsyncMock)


def test_off_topic_is_a_free_channel_by_name_and_does_not_use_up_the_allowance(ctx):
    assert ctx.settings.get("channel.free_chat_names") == "off-topic"
    assert all(ct.check(ctx, 1, 55, 1000 + i, channel_name="off-topic") == ct.ALLOW for i in range(30))
    assert all(ct.check(ctx, 1, 55, 1100 + i, channel_name="Off-Topic") == ct.ALLOW for i in range(5))                 # case-insensitive
    assert [ct.check(ctx, 1, GENERAL, 1200 + i, channel_name="general") for i in range(5)] == [ct.ALLOW] * 4 + [ct.REDIRECT]
    for i in range(6):
        ct.check(ctx, 2, GENERAL, 1300 + i, channel_name="general")
    assert ct.check(ctx, 2, 55, 1310, channel_name="off-topic") == ct.ALLOW                                              # even during the quiet period


def test_free_names_are_a_setting(ctx):
    ctx.settings.set("channel.free_chat_names", "off-topic, #memes")
    assert ct.free_names(ctx) == {"off-topic", "memes"}
    ctx.settings.set("channel.free_chat_names", "")
    assert [ct.check(ctx, 1, GENERAL, 1000 + i, channel_name="off-topic") for i in range(5)] == [ct.ALLOW] * 4 + [ct.REDIRECT]


async def test_handler_in_off_topic_never_limits_and_context_replies_work_there(ctx):
    from navi.handlers.context_reply import in_context_channel

    asha = FakeUser(1, "asha")
    for n in range(8):
        msg = make_message(asha, f"<@{BOT_ID}> question {n}?")
        msg.channel.id, msg.channel.name = 55, "off-topic"
        await handle_mention_qa(ctx, msg)
        assert msg.reply.await_count == 1 and "<#" not in msg.reply.await_args.args[0]
    ctx.settings.set("feature.context_replies", True)
    here = make_message(asha, "hi")
    here.channel.id, here.channel.name = 55, "off-topic"
    other = make_message(asha, "hi")
    other.channel.id, other.channel.name = 56, "general"
    assert in_context_channel(ctx, here) is True and in_context_channel(ctx, other) is False


def test_redirect_note_also_mentions_off_topic(ctx):
    assert "#off-topic" in ct.redirect_text(ctx, FakeUser(1, "asha"))
