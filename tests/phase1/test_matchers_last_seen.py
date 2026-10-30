import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from navi.cogs.summaries import SummariesCog
from navi.data import curse_data as cd
from navi.db.repos.users import get_last_seen, upsert_user
from navi.handlers import pipeline
from navi.services.last_seen import flush_last_seen
from tests.legacy.harness import FakeLLM, FakeUser, make_ctx, make_message

# ---- precompiled matchers must equal the old per-word loops ----

def old_curse(text):
    lower = text.lower()
    for e in cd.CURSE_WORDS:
        if re.search(rf"\b{re.escape(e['word'])}\b", lower):
            return True, e["word"]
    return False, None


def old_boli(content):
    out = []
    for w in cd.BOLI_TRIGGER_WORDS:
        pat = r"\b" + r"\s+".join(re.escape(p) for p in w.split()) + r"\b"
        if re.search(pat, content, re.IGNORECASE):
            out.append(w)
    return out


def old_kochi(content):
    for s in cd.KOCHI_SLANG:
        pat = r"\b" + r"\s+".join(re.escape(p) for p in s.split()) + r"\b"
        if re.search(pat, content, re.IGNORECASE):
            return True
    return False


def samples():
    words = [e["word"] for e in cd.CURSE_WORDS] + cd.BOLI_TRIGGER_WORDS + list(cd.KOCHI_SLANG)
    out = ["", "hello there", "mandarin akidilam xkozhi", "KIDILAM Boli  paal   payasam", "kili poyi chetta"]
    for w in words:
        out += [w, w.upper(), f"hey {w}, ok", f"x{w}", f"{w}y", f"{w} {words[0]} {words[-1]}"]
    for i in range(0, len(words) - 1, 3):
        out.append(f"{words[i]} and {words[i + 1]}")
    return out


@pytest.mark.parametrize("text", samples())
def test_matchers_equal_old_behaviour(text):
    assert cd.contains_curse_word(text) == old_curse(text)
    assert cd.contains_boli_trigger(text) == old_boli(text)
    assert cd.contains_kochi_slang(text) == old_kochi(text)


def test_alternation_is_longest_first():
    pat = cd.CURSE_RE.pattern
    assert cd.BOLI_TRIGGER_RE.search("paal payasam").group(0).lower() == "paal payasam"


def test_severe_regex_matches_only_severe():
    severe = cd.SEVERE_CURSE_WORDS[0]
    assert cd.SEVERE_CURSE_RE.search(f"you {severe}")
    assert not cd.SEVERE_CURSE_RE.search(cd.CURSE_WORDS[0]["word"])


# ---- last_seen tracking ----

async def test_every_message_tracks_last_seen_and_flush_is_one_executemany(db):
    ctx = make_ctx(db)
    a, b = FakeUser(1, "a"), FakeUser(2, "b")
    for u in (a, b):
        upsert_user(db, u.id, u.display_name)
    db.execute("UPDATE users SET last_seen='2020-01-01 00:00:00'")
    db.commit()
    ctx.state.seen_users.update({1, 2})  # the first-message-per-session upsert already wrote last_seen
    for _ in range(3):
        await pipeline.on_message(ctx, make_message(a, "hello"))
    await pipeline.on_message(ctx, make_message(b, "hi"))
    assert set(ctx.state.last_seen_pending) == {1, 2}
    assert get_last_seen(db, 1) == "2020-01-01 00:00:00"  # not written per message

    calls = []
    real = db
    ctx.db = SimpleNamespace(executemany=lambda *a_, **k: (calls.append(a_), real.executemany(*a_, **k))[1],
                             commit=real.commit, execute=real.execute)
    assert flush_last_seen(ctx) == 2
    assert len(calls) == 1
    assert ctx.state.last_seen_pending == {}
    assert get_last_seen(db, 1) > "2020-01-01 00:00:00"


# ---- /kanmanilla reads the DB first ----

class _Guild:
    def __init__(self):
        self.text_channels = [MagicMock()]


async def _kan(db, target, pending=None):
    llm = FakeLLM(text="POSTER")
    ctx = make_ctx(db, llm=llm)
    ctx.state.last_seen_pending.update(pending or {})
    inter = MagicMock()
    inter.client = ctx.bot
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.guild = _Guild()
    scanned = []

    def hist(limit):
        scanned.append(1)

        async def g():
            if False:
                yield
        return g()
    inter.guild.text_channels[0].history = hist
    target.joined_at = datetime.now(timezone.utc) - timedelta(days=40)
    cog = SummariesCog(ctx)
    await cog.kanmanilla_slash.callback(cog, inter, target)
    return llm, inter, scanned


async def test_kanmanilla_uses_db_no_channel_scan(db):
    t = FakeUser(7, "gone")
    upsert_user(db, 7, "gone")
    old = (datetime.now(timezone.utc) - timedelta(days=9)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("UPDATE users SET last_seen=? WHERE user_id=7", [old]); db.commit()
    llm, inter, scanned = await _kan(db, t)
    assert scanned == []
    assert "9" in llm.requests[0]["req"].prompt


async def test_kanmanilla_scans_when_no_record(db):
    t = FakeUser(8, "new")
    llm, inter, scanned = await _kan(db, t)
    assert scanned == [1]
    assert "40" in llm.requests[0]["req"].prompt  # falls back to joined_at


async def test_kanmanilla_prefers_pending_in_memory(db):
    t = FakeUser(9, "recent")
    upsert_user(db, 9, "recent")
    db.execute("UPDATE users SET last_seen='2020-01-01 00:00:00' WHERE user_id=9"); db.commit()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    llm, inter, scanned = await _kan(db, t, pending={9: now})
    assert llm.requests == []  # seen <2 days ago -> short-circuit message
    assert "recently" in inter.followup.send.await_args.args[0]


def test_navi_prediction_is_the_only_cacheable_call_site():
    """Only the /navi prediction purpose may use the template pool."""
    from navi.llm.router import CACHEABLE

    assert CACHEABLE == {"prediction"}
