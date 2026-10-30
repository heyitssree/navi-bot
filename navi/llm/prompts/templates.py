# navi/llm/prompts/templates.py - weekly template generator (purpose template_batch)

from __future__ import annotations

TEMPLATE_BATCH_SYSTEM = (
    "You write short, harmless lines for a Discord bot called Navi, a dramatic Trivandrum astrologer. "
    "You never write sexual, vulgar, abusive or hateful content, and you answer only with the JSON array asked for."
)

_CURSE_BACK = """Generate {n} short replies Navi can post when someone uses one of Navi's
playful curse words in chat.
Rules: English only. One sentence, at most 15 words. Each must contain the
literal placeholder {{user}}. Frame it as harmless cosmic bad luck (bus leaves
one minute early, chai goes cold, phone stuck at 2%). No insults, no body,
family, caste or religion references, no other Malayalam words.
Return ONLY a JSON array of strings, nothing else."""

_PREDICTION = """Generate {n} short daily predictions Navi can reuse for any member.
Rules: English only. One or two sentences, at most 25 words. Each must contain the
literal placeholder {{user}}. Light, funny, harmless Trivandrum flavour (traffic at
Kowdiar, a thattukada run, chaya going cold, phone stuck at 2%). No insults, no body,
family, caste or religion references, no Malayalam words except mone and chaya.
Return ONLY a JSON array of strings, nothing else."""


def get_template_batch_prompt(kind: str, n: int) -> str:
    return (_CURSE_BACK if kind == "curse_back" else _PREDICTION).format(n=n)
