# navi/llm/prompts/community.py - moved from prompts.py (wording unchanged)

from __future__ import annotations

import random


def get_vibe_check_prompt(channel_name: str) -> str:
    """Prompt for a witty calming message when chat is overheating."""
    return f"""The #{channel_name} Discord channel is getting out of hand — too many messages in all caps or with aggressive language in a short time.

Generate a single witty, calming message in English that tells everyone to relax. Be funny, not preachy.

Requirements:
- Keep it light — the goal is to make people laugh and calm down
- 1-2 sentences maximum
- In English only. No persona needed — just be dry and funny."""


_KANMANILLA_STYLES: list[tuple[str, str]] = [
    (
        "dramatic 'Missing Person' notice that is funny and affectionate — not mean",
        "- Start with \"🚨 MISSING: {username}\"\n- Mention the number of days ({days_ago} days)\n- Speculate humorously about where they might be (traffic, work deadlines, life choices)\n- End with a call to action tagging them to reply",
    ),
    (
        "faux-police APB (All Points Bulletin) for this missing server member — formal tone, absurd content",
        "- Start with \"🚔 ALL POINTS BULLETIN — {username} IS MISSING\"\n- State the last known sighting ({days_ago} days ago)\n- List humorous 'suspect traits' about their personality\n- End with a hotline number (make it up, keep it silly)",
    ),
    (
        "overly emotional, dramatic soap-opera monologue wondering where they went",
        "- Start with \"🎭 WHERE IS {username}??\"\n- Be theatrical and over-the-top — the narrator is devastated\n- Mention the {days_ago} days of silence dramatically\n- End by begging them to return",
    ),
    (
        "passive-aggressive notice about how quiet and peaceful it's been since they vanished",
        "- Start with \"📋 SERVER UPDATE: {username} has been absent for {days_ago} days\"\n- Note how suspiciously calm things have been\n- Drop backhanded compliments about their absence\n- End with a mild request for their return",
    ),
    (
        "mythic legend about the user who disappeared into the Trivandrum traffic and was never seen again",
        "- Start with \"📜 THE LEGEND OF {username}\"\n- Weave a short myth about how they vanished {days_ago} days ago\n- Reference Trivandrum landmarks, auto-rickshaws, or KSRTC buses as the cause\n- End with a mystical call to action",
    ),
]


def get_kanmanilla_prompt(username: str, days_ago: int) -> str:
    """Prompt for a humorous missing-person notice — randomly picks a style each call."""
    style_desc, requirements = random.choice(_KANMANILLA_STYLES)
    filled_reqs = requirements.format(username=username, days_ago=days_ago)
    return f"""A Discord user named {username} has not been seen in this server for {days_ago} days.

Write a {style_desc}.

Requirements:
{filled_reqs}
- In English only. 3–4 sentences. Keep it funny and dramatic."""
