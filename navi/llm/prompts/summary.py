# navi/llm/prompts/summary.py - moved from prompts.py (wording unchanged)

from __future__ import annotations

SUMM_SYSTEM_PROMPT = """You are a neutral summarisation assistant. Your only job is to produce concise, factual English summaries of conversations. You have no persona, no opinions, and no style. Output plain, clear English only.

CRITICAL INSTRUCTION: You MUST use the exact usernames provided in the chat log. Do not use generic terms like 'one user' or 'someone'. Attribute quotes and actions directly to the specific usernames."""


LINK_SUMMARY_SYSTEM_PROMPT = """You are a neutral content assistant. Your only job is to summarise web page content into concise, factual bullet points in plain English. No persona, no opinions, no filler."""


def get_summ_prompt(conversation: str) -> str:
    """Prompt for a factual, no-persona summary of a conversation."""
    return f"""Below is a Discord conversation in the format "Username: message". The messages may be in English, Malayalam, Manglish (Malayalam-English mix), or a combination. Translate and summarise everything into plain English.

CONVERSATION:
{conversation}

Requirements:
- 2–4 sentences maximum.
- Output in English only — clear, direct, factual summary regardless of the input language.
- CRITICAL: Use the exact usernames from the chat log. Attribute what each person said or did directly to their username (e.g. "Rahul said...", "Priya asked..."). Never say 'one user' or 'someone'.
- Never mention religion or politics.
- Focus on: what happened, what was discussed, what decisions were made, if any."""


def get_link_summary_prompt(page_text: str, url: str) -> str:
    """Prompt for a 3-bullet-point summary of a webpage."""
    return f"""Below is the text content scraped from this URL: {url}

PAGE CONTENT:
{page_text}

Summarise this page in exactly 3 concise bullet points in plain English. Each bullet should capture a key fact or takeaway.

Requirements:
- Exactly 3 bullet points, each starting with "•"
- Plain English only — no jargon, no filler, no persona
- Each bullet: 1–2 sentences maximum
- If the content is too thin or unreadable, say so in one line"""
