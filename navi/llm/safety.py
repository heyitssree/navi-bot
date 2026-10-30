# navi/llm/safety.py - deterministic output filter applied to every LLM reply, generated template, /teach entry
# and context-reply history before it is sent, stored or put into a prompt.

from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("navi.llm.safety")

MALAYALAM_SCRIPT = re.compile(r"[ഀ-ൿ]")
ZERO_WIDTH = re.compile(r"[​-‏⁠﻿]")
LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
MENTION = re.compile(r"<@[!&]?\d+>")
SQUASH_MIN_LEN = 5
DEFAULT_BLOCKLIST = Path(__file__).resolve().parent.parent / "data" / "safety" / "blocklist.txt"

# Longest acceptable reply per purpose (Discord's own limit is 2000 characters).
MAX_LEN = {"qa": 1000, "context_reply": 1000, "prediction": 1000, "vibe": 500, "summary": 1900, "mod": 1900,
           "template_batch": 4000, "teach": 400}
DEFAULT_MAX_LEN = 1000


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    t = ZERO_WIDTH.sub("", t).translate(LEET)
    return re.sub(r"(.)\1{2,}", r"\1\1", t)          # "pottaaaan" -> "pottaan"


def _fold(text: str) -> str:
    """Collapse every repeated letter to one ("zorgblaaat" and "zorgblat" both become "zorgblat")."""
    return re.sub(r"(.)\1+", r"\1", text)


def _squash(text: str) -> str:
    return re.sub(r"[\W_]+", "", text)


@dataclass
class Verdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


def load_blocklist(path: Path | str | None = None) -> list[str]:
    """Read the owner's blocklist (missing or empty file = no entries)."""
    path = Path(path or os.getenv("SAFETY_BLOCKLIST") or DEFAULT_BLOCKLIST)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        logger.warning("Safety blocklist %s not found; only the built-in checks are active.", path)
        return []
    return [l.strip() for l in lines if l.strip() and not l.lstrip().startswith("#")]


class SafetyFilter:
    def __init__(self, blocklist: list[str] | None = None, allowed_terms: list[str] | None = None, settings=None) -> None:
        self.settings = settings
        self.set_blocklist(blocklist or [])
        self.set_allowed(allowed_terms or [])

    # -- configuration
    def set_blocklist(self, entries: list[str]) -> None:
        latin, script = [], []
        for raw in entries:
            e = normalise(raw).strip()
            if not e:
                continue
            (script if MALAYALAM_SCRIPT.search(e) else latin).append(e)
        self.script_entries = sorted(set(script))
        self.word_re = re.compile(r"(?<![a-z0-9])(?:%s)(?![a-z0-9])" % "|".join(
            r"\s+".join(re.escape(p) for p in e.split()) for e in sorted(set(latin), key=lambda x: -len(x)))) if latin else None
        self.squash_entries = sorted({_squash(e) for e in latin if len(_squash(e)) >= SQUASH_MIN_LEN})
        folded = sorted({_fold(e) for e in latin if len(_fold(e)) >= 4}, key=lambda x: -len(x))
        self.folded_re = re.compile(r"(?<![a-z0-9])(?:%s)(?![a-z0-9])" % "|".join(
            r"\s+".join(re.escape(p) for p in e.split()) for e in folded)) if folded else None
        self.entry_count = len(set(latin)) + len(self.script_entries)

    def set_allowed(self, terms: list[str]) -> None:
        cleaned = sorted({normalise(t).strip() for t in terms if t and t.strip()}, key=lambda x: -len(x))
        self.allowed_re = re.compile(r"(?<![a-z0-9])(?:%s)(?![a-z0-9])" % "|".join(
            r"\s+".join(re.escape(p) for p in t.split()) for t in cleaned)) if cleaned else None
        self.allowed_terms = cleaned

    # -- matching
    def blocklist_hits(self, text: str) -> list[str]:
        n = normalise(text)
        if self.allowed_re:
            n = self.allowed_re.sub(" ", n)          # Navi's own words never count
        hits = []
        if self.word_re:
            hits += [m.group(0) for m in self.word_re.finditer(n)]
        hits += [e for e in self.script_entries if e in n]
        if self.folded_re:                           # stretched spellings: "zorgblaaaat"
            hits += [m.group(0) for m in self.folded_re.finditer(_fold(n))]
        squashed = _squash(n)
        hits += [e for e in self.squash_entries if e in squashed]
        return hits

    def check(self, text: str, purpose: str = "") -> Verdict:
        reasons: list[str] = []
        allow_script = bool(self.settings.get("safety.allow_malayalam_script")) if self.settings is not None else False
        if MALAYALAM_SCRIPT.search(text) and not allow_script:
            reasons.append("malayalam_script")
        if self.blocklist_hits(text):
            reasons.append("blocklist")
        if "@everyone" in text or "@here" in text or MENTION.search(text):
            reasons.append("mention")
        if len(text) > MAX_LEN.get(purpose, DEFAULT_MAX_LEN):
            reasons.append("too_long")
        return Verdict(ok=not reasons, reasons=reasons)


_filter = SafetyFilter()


def configure(*, settings=None, blocklist: list[str] | None = None, allowed_terms: list[str] | None = None) -> SafetyFilter:
    """Set up the process-wide filter at startup (the app passes the settings, the owner's blocklist and the allow-list)."""
    if settings is not None:
        _filter.settings = settings
    if blocklist is not None:
        _filter.set_blocklist(blocklist)
    if allowed_terms is not None:
        _filter.set_allowed(allowed_terms)
    return _filter


def check_output(text: str, purpose: str = "") -> Verdict:
    """Check a piece of text. The result is truthy when it is safe to use; .reasons says why not."""
    return _filter.check(text, purpose)
