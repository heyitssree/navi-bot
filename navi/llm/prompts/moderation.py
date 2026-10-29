# navi/llm/prompts/moderation.py - moved from prompts.py (wording unchanged)

from __future__ import annotations


def get_audit_prompt(rules_text: str, messages_text: str) -> str:
    """Prompt to compare user messages against server rules."""
    return f"""You are a neutral moderation assistant. Compare the user's messages against the server rules below.

SERVER RULES:
{rules_text}

USER'S RECENT MESSAGES:
{messages_text}

Produce a structured moderation report:
1. State clearly whether any rules were broken (Yes / No).
2. If yes, name which rule(s) and quote the exact offending message(s).
3. Give a verdict: Clean / Warn / Ban — with a one-line justification.
4. Keep the report under 300 words. Plain English only. No persona."""


def get_mod_tldr_prompt(thread_text: str) -> str:
    """Prompt for a moderator-focused thread summary."""
    return f"""You are a neutral moderation assistant. Summarise the Discord thread below.

THREAD CONTENT:
{thread_text}

Provide a structured summary:
1. Core topic: What is this thread about?
2. Initiated by: Who started it (use exact username)?
3. Key participants: Who were the main contributors?
4. Final consensus / outcome: Was a decision reached? Was there unresolved conflict?

Keep it under 200 words. Plain English. Use exact usernames from the thread."""
