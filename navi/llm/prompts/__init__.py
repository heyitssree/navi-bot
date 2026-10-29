"""Gemini / LLM prompt templates, split by purpose. Wording is unchanged from the old prompts.py.

EDITING GUIDE
  persona.py      bot persona and time-aware system prompt
  predictions.py  /navi predictions, passive curse reply
  qa.py           Q&A (bot mentions)
  summary.py      conversation summary, link summary
  community.py    vibe check, missing-member notice
  moderation.py   mod audit, mod thread TL;DR
Canned (non-LLM) messages live in navi/data/messages.py.
"""
from navi.llm.prompts.community import *  # noqa: F401,F403
from navi.llm.prompts.moderation import *  # noqa: F401,F403
from navi.llm.prompts.persona import *  # noqa: F401,F403
from navi.llm.prompts.persona import _DEFAULT_SYSTEM_PROMPT, _LINK_SYSTEM_PROMPT  # noqa: F401
from navi.llm.prompts.predictions import *  # noqa: F401,F403
from navi.llm.prompts.qa import *  # noqa: F401,F403
from navi.llm.prompts.summary import *  # noqa: F401,F403
