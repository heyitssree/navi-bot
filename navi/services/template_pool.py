# navi/services/template_pool.py - reviewed, reusable text (content table): seed, pick, store generated, weekly batches
#
# Passive curse replies and cache-reuse predictions come from this pool; no live LLM call is involved. New text is
# grown by the weekly template_batch job: validated, safety-checked, near-duplicates dropped, and stored as
# 'pending' for /admin review unless safety.template_auto_approve is on.

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import sqlite3
from collections import deque

from navi.data.curse_data import CURSE_BACK_REPLIES, DOOMED_PREDICTIONS
from navi.db.connection import _db_write
from navi.llm import safety
from navi.llm.base import LLMRequest

logger = logging.getLogger("navi.services.template_pool")

BATCH_KINDS = ("curse_back", "prediction")
MAX_WORDS = {"curse_back": 15, "prediction": 25}
SIMILARITY_LIMIT = 85          # rapidfuzz ratio at or above this = near-duplicate
RECENT_PER_USER = 5
BATCH_INTERVAL = 7 * 24 * 3600


def seed_templates(db: sqlite3.Connection) -> int:
    """Insert the hand-written curse replies into the pool (source 'seed'). Idempotent; returns rows added."""
    before = db.execute("SELECT COUNT(*) FROM content WHERE kind = 'curse_back'").fetchone()[0]
    _db_write(lambda: (
        db.executemany(
            "INSERT OR IGNORE INTO content (kind, text, status, source) VALUES ('curse_back', ?, 'active', 'seed')",
            [(t,) for t in (*DOOMED_PREDICTIONS, *CURSE_BACK_REPLIES)],
        ),
        db.commit(),
    ))
    return db.execute("SELECT COUNT(*) FROM content WHERE kind = 'curse_back'").fetchone()[0] - before


def fill(template: str, user: str, curse: str | None = None) -> str:
    """Fill {user}/{curse}. Plain replace (not str.format) so stray braces in generated text are harmless."""
    return template.replace("{user}", user).replace("{curse}", curse or "that")


def pick(ctx, kind: str, user_id: int, user: str, curse: str | None = None) -> str | None:
    """A random active template of this kind, avoiding the last 5 used for that user. None if the pool is empty."""
    rows = ctx.db.execute("SELECT id, text FROM content WHERE kind = ? AND status = 'active'", [kind]).fetchall()
    if not rows:
        return None
    recent = ctx.state.recent_templates.setdefault((user_id, kind), deque(maxlen=RECENT_PER_USER))
    fresh = [r for r in rows if r[0] not in recent] or rows       # a tiny pool may have to repeat
    template_id, text = random.choice(fresh)
    recent.append(template_id)
    return fill(text, user, curse)


def store_generated(ctx, kind: str, text: str, *, source: str = "llm") -> str:
    """Store generated reusable text after the safety filter. Returns 'active', 'pending' or 'rejected'."""
    verdict = safety.check_output(text, "template_batch")
    status = "rejected" if not verdict.ok else "active" if ctx.settings.get("safety.template_auto_approve") else "pending"
    _db_write(lambda: (
        ctx.db.execute("INSERT OR IGNORE INTO content (kind, text, status, source) VALUES (?, ?, ?, ?)", [kind, text, status, source]),
        ctx.db.commit(),
    ))
    return status


def store_rejected(db: sqlite3.Connection, kind: str, text: str, reasons: list[str]) -> None:
    """Keep a rejected LLM reply for the owner (status 'rejected') and log a safety_reject event."""
    _db_write(lambda: (
        db.execute("INSERT OR IGNORE INTO content (kind, text, status, source) VALUES (?, ?, 'rejected', 'llm')", [kind, text]),
        db.execute("INSERT INTO events (kind, name, detail) VALUES ('safety_reject', ?, ?)", [kind, json.dumps({"reasons": reasons})]),
        db.commit(),
    ))


# --------------------------------------------------------------------------- weekly generation

def parse_batch(raw: str) -> list[str]:
    """Pull a JSON array of strings out of a model reply (tolerates code fences and chatter around it)."""
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return []
    return [x.strip() for x in data if isinstance(x, str) and x.strip()] if isinstance(data, list) else []


def validate_candidate(text: str, kind: str, existing: list[str]) -> str | None:
    """Return None if the candidate is acceptable, else the reason it was dropped."""
    from rapidfuzz import fuzz

    if "{user}" not in text:
        return "no_user_placeholder"
    if len(text.replace("{user}", "x").replace("{curse}", "x").split()) > MAX_WORDS.get(kind, 25):
        return "too_long"
    if not safety.check_output(text, "template_batch").ok:
        return "unsafe"
    low = text.lower()
    if any(fuzz.ratio(low, e.lower()) >= SIMILARITY_LIMIT for e in existing):
        return "near_duplicate"
    return None


async def generate_batch(ctx, kind: str) -> dict[str, int]:
    """One template_batch call for a kind. Returns counts: asked / added / dropped by reason."""
    from navi.llm.prompts.templates import get_template_batch_prompt, TEMPLATE_BATCH_SYSTEM

    n = ctx.settings.get("safety.template_batch_size")
    res = await ctx.llm.generate(
        LLMRequest(purpose="template_batch", system=TEMPLATE_BATCH_SYSTEM, prompt=get_template_batch_prompt(kind, n)),
        fallback="", name="template-batch", cache_type="template_batch",
    )
    stats: dict[str, int] = {"asked": n, "added": 0}
    if res.from_cache or not res.text:
        stats["no_reply"] = 1
        return stats
    existing = [r[0] for r in ctx.db.execute("SELECT text FROM content WHERE kind = ? AND status != 'rejected'", [kind])]
    for candidate in parse_batch(res.text)[: n * 2]:
        reason = validate_candidate(candidate, kind, existing)
        if reason:
            stats[reason] = stats.get(reason, 0) + 1
            continue
        store_generated(ctx, kind, candidate)
        existing.append(candidate)
        stats["added"] += 1
    logger.info("Template batch %s: %s", kind, stats)
    return stats


async def template_batch_loop(ctx) -> None:
    """Weekly, lowest priority. Skipped while the LLM is off or the feature is not wanted."""
    await asyncio.sleep(3600)
    while True:
        if ctx.llm is not None and ctx.settings.get("ai.provider") != "off":
            for kind in BATCH_KINDS:
                try:
                    await generate_batch(ctx, kind)
                except Exception as exc:
                    logger.error("Template batch %s failed: %s", kind, exc)
        await asyncio.sleep(BATCH_INTERVAL)
