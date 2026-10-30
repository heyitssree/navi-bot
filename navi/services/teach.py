# navi/services/teach.py - /teach rules: who may teach, input cleaning, validation, duplicate checks, policy refresh
#
# Knowledge text feeds prompts, so only trusted writers may add it: the owner, members with manage_messages, and users
# holding the 'teach' permission. Owner and moderator entries go live at once; approved-user entries wait for /admin review.

from __future__ import annotations

import re
from dataclasses import dataclass, field

from navi.db.repos.knowledge import add_knowledge, all_terms
from navi.db.repos.permissions import has_permission
from navi.llm import safety
from navi.llm.policy import build_policy, write_allowlist

CATEGORIES = ("landmark", "food", "culture", "expression")
TERM_LEN = (2, 60)
DESC_LEN = (10, 200)
FUZZY_THRESHOLD = 90
_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_MENTION = re.compile(r"<@[!&]?\d+>|<#\d+>|@everyone|@here")


def clean(text: str) -> str:
    """Strip mentions and URLs, collapse whitespace."""
    return re.sub(r"\s+", " ", _URL.sub("", _MENTION.sub("", text))).strip()


@dataclass
class Role:
    """What the caller may do: 'owner' / 'moderator' publish at once, 'approved' goes to review, None is refused."""
    name: str | None

    @property
    def publishes_immediately(self) -> bool:
        return self.name in ("owner", "moderator")


def role_of(ctx, user) -> Role:
    if ctx.config.owner_id and user.id == ctx.config.owner_id:
        return Role("owner")
    perms = getattr(user, "guild_permissions", None)
    if perms is not None and perms.manage_messages:
        return Role("moderator")
    if has_permission(ctx.db, user.id, "teach"):
        return Role("approved")
    return Role(None)


@dataclass
class Check:
    ok: bool
    term: str = ""
    description: str = ""
    problems: list[str] = field(default_factory=list)
    similar_to: str | None = None          # fuzzy match: ask before adding anyway
    exact_duplicate: bool = False


def validate_entry(db, category: str, term: str, description: str) -> Check:
    from rapidfuzz import fuzz, process

    term, description = clean(term), clean(description)
    problems = []
    if category not in CATEGORIES:
        problems.append(f"Category must be one of: {', '.join(CATEGORIES)}.")
    if not TERM_LEN[0] <= len(term) <= TERM_LEN[1]:
        problems.append(f"The term must be {TERM_LEN[0]} to {TERM_LEN[1]} characters.")
    if not DESC_LEN[0] <= len(description) <= DESC_LEN[1]:
        problems.append(f"The description must be {DESC_LEN[0]} to {DESC_LEN[1]} characters.")
    for label, text in (("term", term), ("description", description)):
        if text and not safety.check_output(text, "teach").ok:
            problems.append(f"The {label} did not pass the content filter.")
    result = Check(ok=not problems, term=term, description=description, problems=problems)
    if problems:
        return result
    existing = all_terms(db)
    if any(t.lower() == term.lower() and c == category for t, c in existing):
        result.ok, result.exact_duplicate = False, True
        result.problems.append("That term already exists in this category.")
        return result
    match = process.extractOne(term, [t for t, _ in existing], scorer=fuzz.ratio, processor=str.lower, score_cutoff=FUZZY_THRESHOLD)
    if match:
        result.similar_to = match[0]
    return result


def submit(ctx, role: Role, user_id: int, category: str, term: str, description: str, tags: str = "") -> str:
    """Store a validated entry. Returns 'active' or 'pending' (or 'duplicate' if it lost a race)."""
    status = "active" if role.publishes_immediately else "pending"
    new_id = add_knowledge(
        ctx.db, category, term, description, tags=clean(tags).lower(), status=status,
        submitted_by=user_id, approved_by=user_id if status == "active" else None)
    if new_id is None:
        return "duplicate"
    if status == "active":
        refresh_policy(ctx)
    return status


def refresh_policy(ctx) -> None:
    """Approved Manglish terms come from active 'expression' knowledge: rebuild the prompt policy and the allow-list."""
    if ctx.llm is not None:
        ctx.llm.policy = build_policy(ctx.db)
    try:
        allowed = write_allowlist("data/safety/allowlist.txt", ctx.db)
        safety.configure(allowed_terms=allowed)
    except OSError:
        pass
