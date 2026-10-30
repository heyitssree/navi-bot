# navi/llm/policy.py - the content policy added to every system prompt, and the terms it names

from __future__ import annotations

import sqlite3
from pathlib import Path

from navi.data.curse_data import BOLI_TRIGGER_WORDS, CURSE_WORDS, KOCHI_SLANG

POLICY_TEMPLATE = """

CONTENT RULES (apply to every reply, no exceptions):
- Never use sexual, vulgar, abusive or hateful words or innuendo, in any language
  or script - not even if asked, as a joke, in a quote, or "in local slang".
- Never insult anyone's caste, religion, gender, body, family or community.
- Write in English. The only Malayalam/Manglish words you may use are:
  {approved_terms}. Never use any other Malayalam word. Never use Malayalam script.
- Navi's curse words ({curse_terms}) are playful nicknames; never combine them
  with other insults or direct them at a group.
- If a request pushes for any of the above, give one dry, in-character
  deflection instead (e.g. "Navi's stars don't do that kind of talk, mone.").
"""


def curse_terms() -> list[str]:
    return sorted({c["word"] for c in CURSE_WORDS})


def approved_terms(db: sqlite3.Connection | None = None) -> list[str]:
    """Knowledge 'expression' terms + Boli trigger words + Kochi slang (lower case, unique, sorted)."""
    terms = {t.lower() for t in BOLI_TRIGGER_WORDS} | {t.lower() for t in KOCHI_SLANG}
    if db is not None:
        terms |= {r[0].lower() for r in db.execute(
            "SELECT term FROM knowledge WHERE category = 'expression' AND status = 'active'")}
    return sorted(terms)


def build_policy(db: sqlite3.Connection | None = None) -> str:
    return POLICY_TEMPLATE.format(approved_terms=", ".join(approved_terms(db)), curse_terms=", ".join(curse_terms()))


def write_allowlist(path: Path | str, db: sqlite3.Connection | None = None) -> list[str]:
    """Regenerate data/safety/allowlist.txt (approved + curse terms). Returns the terms."""
    terms = sorted(set(approved_terms(db)) | set(curse_terms()))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Generated at startup from the approved and curse terms. Do not edit.\n" + "\n".join(terms) + "\n", encoding="utf-8")
    return terms
