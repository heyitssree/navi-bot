# navi/llm/safety.py - output filter. Phase 5 adds the blocklist/allowlist checks; until then everything passes.

from __future__ import annotations


def check_output(text: str, purpose: str) -> tuple[bool, str | None]:
    """Return (ok, reason). A rejected reply makes the router use the caller's fallback text."""
    return True, None
