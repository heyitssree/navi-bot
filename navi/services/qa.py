# navi/services/qa.py - answering questions cheaply: knowledge lookup, answer cache, then the LLM
#
# 1. "what is / meaning of / where is X" where X matches a knowledge term (rapidfuzz token_set_ratio >= 90): answer from the
#    description, no LLM.
# 2. A cached answer for a near-identical question (similarity >= 92) newer than ai.qa_cache_ttl_days, skipped for
#    time-sensitive questions.
# 3. The LLM (per-user cooldown and daily cap are enforced by the router, so steps 1 and 2 never use up a user's allowance).

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass

from navi.data.messages import FALLBACK_MESSAGES
from navi.db.connection import _db_write
from navi.llm.base import LLMRequest
from navi.llm.prompts import LINK_USERNAME, get_qa_prompt, get_time_aware_system_prompt
from navi.llm.prompts.qa import get_context_prompt
from navi.services.predictions import templatize

KNOWLEDGE_THRESHOLD = 90
CACHE_THRESHOLD = 92
TIME_SENSITIVE = re.compile(r"\b(today|now|latest|score|scores|weather|time|tonight|tomorrow|yesterday|current|currently|recent|news)\b", re.I)
_SUBJECT_PATTERNS = (
    re.compile(r"^(?:what\s+does)\s+(?P<s>.+?)\s+mean$", re.I),
    re.compile(r"^(?:what\s*(?:'s|s|is|are)|where\s*(?:'s|s|is|are)|who\s*(?:'s|s|is))\s+(?:the\s+)?(?:meaning\s+of\s+)?(?P<s>.+)$", re.I),
    re.compile(r"^(?:meaning\s+of|define|explain)\s+(?P<s>.+)$", re.I),
)
LIMIT_OUTCOMES = {"user_cooldown", "user_daily_cap"}


@dataclass
class Answer:
    text: str
    source: str            # knowledge | cache | llm | fallback | limit
    from_cache: bool = False
    outcome: str = ""


def normalise_question(question: str) -> str:
    q = re.sub(r"<@[!&]?\d+>", " ", question.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", q)).strip()


def is_time_sensitive(question: str) -> bool:
    return bool(TIME_SENSITIVE.search(question))


def extract_subject(question: str) -> str | None:
    q = re.sub(r"\s+", " ", re.sub(r"<@[!&]?\d+>", " ", question)).strip().rstrip("?.! ").strip()
    for pat in _SUBJECT_PATTERNS:
        m = pat.match(q)
        if m and m.group("s").strip():
            return m.group("s").strip(" \"'")
    return None


def knowledge_answer(db, question: str) -> str | None:
    from rapidfuzz import fuzz, process

    subject = extract_subject(question)
    if not subject:
        return None
    rows = db.execute("SELECT term, description FROM knowledge WHERE status = 'active'").fetchall()
    if not rows:
        return None
    terms = [r[0] for r in rows]
    match = process.extractOne(subject, terms, scorer=fuzz.token_set_ratio, processor=str.lower, score_cutoff=KNOWLEDGE_THRESHOLD)
    if not match:
        return None
    _, _, index = match
    return f"{rows[index][0]}: {rows[index][1]}"


def cached_answer(db, question: str, name: str, ttl_days: int) -> str | None:
    from rapidfuzz import fuzz, process

    if is_time_sensitive(question):
        return None
    key = normalise_question(question)
    rows = db.execute(
        "SELECT key, text FROM content WHERE kind = 'qa_answer' AND status = 'active' AND key IS NOT NULL"
        " AND created_at >= datetime('now', ?)", [f"-{int(ttl_days)} days"],
    ).fetchall()
    if not rows or not key:
        return None
    match = process.extractOne(key, [r[0] for r in rows], scorer=fuzz.ratio, score_cutoff=CACHE_THRESHOLD)
    if not match:
        return None
    return rows[match[2]][1].replace("{user}", name)


def store_answer(db, question: str, answer: str, name: str) -> None:
    if is_time_sensitive(question):
        return
    key = normalise_question(question)
    if not key:
        return
    text = templatize(answer, name)

    def _write() -> None:
        db.execute("DELETE FROM content WHERE kind = 'qa_answer' AND key = ?", [key])
        db.execute("INSERT OR IGNORE INTO content (kind, key, text, status, source) VALUES ('qa_answer', ?, ?, 'active', 'llm')", [key, text])
        db.commit()
    _db_write(_write)


async def answer_question(ctx, message, question: str, *, history: list[tuple[str, str]] | None = None, purpose: str = "qa") -> Answer:
    """Answer one question for message.author. history (the reply chain) disables the knowledge and cache shortcuts."""
    name = message.author.display_name
    if not history:
        hit = knowledge_answer(ctx.db, question)
        if hit:
            return Answer(hit, "knowledge", True, "knowledge")
        hit = cached_answer(ctx.db, question, name, ctx.settings.get("ai.qa_cache_ttl_days"))
        if hit:
            return Answer(hit, "cache", True, "cache")
    is_link = name == LINK_USERNAME
    system = get_time_aware_system_prompt(ctx.db, username=name)
    prompt = get_context_prompt(name, history, question, is_link) if history else get_qa_prompt(name, question, is_link=is_link)
    res = await ctx.llm.generate(
        LLMRequest(purpose=purpose, system=system, prompt=prompt),
        fallback=random.choice(FALLBACK_MESSAGES), name=name, user_id=message.author.id, cache_type="qa",
    )
    if res.outcome in LIMIT_OUTCOMES:
        return Answer(res.text, "limit", True, res.outcome)
    if res.outcome == "ok" and not history:
        store_answer(ctx.db, question, res.text, name)
    return Answer(res.text, "llm" if not res.from_cache else "fallback", res.from_cache, res.outcome)


def limit_notice_due(ctx, user_id: int, window: float | None = None) -> bool:
    """True the first time a user hits a Q&A limit in a window (they get one in-character note, then silence)."""
    window = window if window is not None else max(60.0, float(ctx.settings.get("ai.qa_cooldown_seconds")))
    now = time.monotonic()
    if now - ctx.state.limit_notice.get(user_id, -1e12) < window:
        return False
    ctx.state.limit_notice[user_id] = now
    return True
