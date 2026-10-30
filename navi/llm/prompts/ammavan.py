# navi/llm/prompts/ammavan.py - the rare witty remark on another bot's (Ammavan's) AI answer

from __future__ import annotations


def get_ammavan_witty_prompt(text: str) -> str:
    """One short, kind remark about what another bot said. Never about a person or a community."""
    return f"""Another Discord bot called Ammavan just said this in a chat: "{text}"

Write ONE short, witty, good-natured remark in reply, as a dry-humoured astrologer.
- English only, at most 20 words, one sentence.
- Tease the situation or the bot's answer, never any person, family, group, region, religion, caste or community.
- No insults, no @mentions, do not address anyone by name, no hashtags.
- Do not start with a dot or with the word "ammava"."""
