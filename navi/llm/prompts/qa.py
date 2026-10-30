# navi/llm/prompts/qa.py - moved from prompts.py (wording unchanged)

from __future__ import annotations


def get_qa_prompt(name: str, question: str, is_link: bool = False) -> str:
    """Prompt for answering a tagged question."""
    if is_link:
        return f"""Link tagged you and asked: "{question}"

Lead with the accurate answer. Add a dry remark only after the answer is clearly stated.
- In English only. 1-2 sentences max."""
    else:
        return f"""A user named {name} tagged you and asked: "{question}"

Your job is to answer this question correctly. Start your response with the actual answer or key fact — not a remark, not the username, not a joke. The answer comes first.
- If you don't know, say so plainly.
- In English only. 1-2 sentences max. One brief comment after the answer is fine if it fits naturally."""


def get_context_prompt(name: str, history: list[tuple[str, str]], question: str, is_link: bool = False) -> str:
    """Q&A prompt that includes the short reply chain so far (oldest first; roles are 'User' and 'Navi')."""
    convo = "\n".join(f"{role}: {text}" for role, text in history)
    return f"Conversation so far (oldest first):\n{convo}\n\nNow the latest message.\n" + get_qa_prompt(name, question, is_link)
