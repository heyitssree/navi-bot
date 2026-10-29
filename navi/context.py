# navi/context.py - AppContext: everything a cog or handler needs, passed in explicitly (no module-level state)

from __future__ import annotations

import asyncio
import sqlite3
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord

    from navi.config import Config
    from navi.llm.router import LLMRouter
    from navi.settings.store import FeatureFlags


@dataclass
class RuntimeState:
    """In-memory caches and trackers that used to be module globals in bot.py."""

    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    seen_users: set[int] = field(default_factory=set)               # upsert_user only on first message per session
    last_seen_pending: dict[int, str] = field(default_factory=dict)  # flushed to user_stats every 10 minutes
    user_level_cache: dict[int, int] = field(default_factory=dict)
    user_usage: dict[int, list[datetime]] = field(default_factory=dict)  # /navi calls per user (60 s window)
    channel_msg_tracker: dict[int, deque] = field(default_factory=dict)  # vibe check
    vibe_last_fired: dict[int, datetime] = field(default_factory=dict)
    slang_spam_tracker: dict[int, tuple[int, datetime]] = field(default_factory=dict)
    slang_cooldown: dict[int, datetime] = field(default_factory=dict)
    summarized_messages: set[int] = field(default_factory=set)
    temp_vc_registry: dict[int, asyncio.Task] = field(default_factory=dict)


@dataclass
class AppContext:
    bot: "discord.Client"
    config: "Config"
    settings: "FeatureFlags"
    state: RuntimeState = field(default_factory=RuntimeState)
    db: sqlite3.Connection | None = None      # opened in on_ready
    llm: "LLMRouter | None" = None            # created in on_ready (needs the DB for the template pool)
    tasks: dict[str, asyncio.Task] = field(default_factory=dict)  # named background tasks
