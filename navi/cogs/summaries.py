# navi/cogs/summaries.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import logging
import random
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from navi.context import AppContext
from navi.data.messages import FALLBACK_MESSAGES
from navi.db.repos.settings import get_config_str
from navi.db.repos.users import get_last_seen
from navi.llm.base import LLMRequest
from navi.llm.prompts import (
    LINK_SUMMARY_SYSTEM_PROMPT,
    SUMM_SYSTEM_PROMPT,
    get_kanmanilla_prompt,
    get_link_summary_prompt,
    get_summ_prompt,
    get_time_aware_system_prompt,
)

logger = logging.getLogger("navi.cogs.summaries")


# Strips trailing punctuation that gets swept into a URL match (e.g. "url.")
_URL_RE = re.compile(r"https?://[^\s]+")


_URL_TRAIL_RE = re.compile(r"[)\].,;!?\"'>]+$")


_SUMMARIZED_MAX = 500  # cap so it never grows unbounded


_SCRAPE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _extract_article_text(html: str) -> str:
    """Return the most article-like text content from raw HTML, capped at 4 000 chars."""
    import importlib
    bs4 = importlib.import_module("bs4")
    BeautifulSoup = bs4.BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    # Strip noise nodes that add no article content
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    # Prefer a semantic article container; fall back to <main>, then whole body
    container = soup.find("article") or soup.find("main") or soup

    paragraphs = [
        p.get_text(separator=" ", strip=True)
        for p in container.find_all("p")
        if len(p.get_text(strip=True)) > 40  # drop nav labels / button text
    ]

    # If the article container had too little text, widen to the whole document
    if len(" ".join(paragraphs)) < 300:
        paragraphs = [
            p.get_text(separator=" ", strip=True)
            for p in soup.find_all("p")
            if len(p.get_text(strip=True)) > 40
        ]

    return " ".join(paragraphs)[:4000]


class SummariesCog(commands.Cog):
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._added: list = []

    async def cog_load(self) -> None:
        pass

    async def cog_unload(self) -> None:
        for cmd in self._added:
            self.ctx.bot.tree.remove_command(cmd.name, type=cmd.type)

    @app_commands.command(name="summ", description="Get a factual summary of recent chat")
    @app_commands.describe(
        limit="Number of messages to summarise (1–100)",
        user1="Only include messages from this user (optional)",
        user2="Also include messages from this user (optional)",
        public="Show summary to everyone? (default: only me)",
    )
    async def summ_slash(self, interaction: discord.Interaction,
        limit: app_commands.Range[int, 1, 100] = 30,
        user1: discord.Member | None = None,
        user2: discord.Member | None = None,
        public: bool = False,
    ) -> None:
        ctx = interaction.client.ctx
        await interaction.response.defer(ephemeral=not public, thinking=True)

        # Collect history
        raw_messages: list[discord.Message] = []
        async for msg in interaction.channel.history(limit=limit):
            raw_messages.append(msg)
        raw_messages.reverse()  # chronological order

        # Filter by selected users if provided
        filter_ids: set[int] = set()
        if user1:
            filter_ids.add(user1.id)
        if user2:
            filter_ids.add(user2.id)
        if filter_ids:
            raw_messages = [m for m in raw_messages if m.author.id in filter_ids]

        if not raw_messages:
            await interaction.followup.send(
                "No messages found to summarise. Try a larger limit or different user filters.",
                ephemeral=not public,
            )
            return

        # Strip bot messages, commands (starting with /), and mention IDs — keep username prefix
        _mention_re = re.compile(r"<@!?\d+>|<#\d+>|<@&\d+>")
        lines: list[str] = []
        for msg in raw_messages:
            if msg.author.bot:
                continue
            text = _mention_re.sub("[mentioned-user]", msg.content).strip()
            if not text or text.startswith("/"):
                continue
            lines.append(f"{msg.author.display_name}: {text}")

        if not lines:
            await interaction.followup.send(
                "Nothing to summarise — all messages were commands or from bots.",
                ephemeral=not public,
            )
            return

        conversation_text = "\n".join(lines)
        user_prompt = get_summ_prompt(conversation_text)

        _res = await ctx.llm.generate(
            LLMRequest(purpose="summary", system=SUMM_SYSTEM_PROMPT, prompt=user_prompt),
            fallback=random.choice(FALLBACK_MESSAGES),
            name="SummaryRequest",
            cache_type="qa",
        )
        summary, _ = _res.text, _res.from_cache

        filter_note = ""
        if filter_ids:
            names = [u.display_name for u in [user1, user2] if u]
            filter_note = f" (filtered to {', '.join(names)})"

        await interaction.followup.send(
            f"📜 **Chat Summary — last {len(lines)} messages{filter_note}:**\n{summary}",
            ephemeral=not public,
        )
    @app_commands.command(name="kanmanilla", description="Ping a missing member with a dramatic Missing Person notice")
    @app_commands.describe(user="The member you're looking for")
    async def kanmanilla_slash(self, interaction: discord.Interaction, user: discord.Member) -> None:
        ctx = self.ctx
        if not ctx.settings.feat("feature_kanmanilla"):
            await interaction.response.send_message(
                "Kanmanilla feature is currently disabled.", ephemeral=True
            )
            return

        if user.bot:
            await interaction.response.send_message(
                "Bots don't go missing — they just get turned off.", ephemeral=True
            )
            return

        # Defer early — channel history search can take a moment
        await interaction.response.defer(thinking=True)

        # Database first (last_seen is tracked on every message); only scan channels when no record exists.
        last_message_time: datetime | None = None
        seen_raw = ctx.state.last_seen_pending.get(user.id) or get_last_seen(ctx.db, user.id)
        if seen_raw:
            try:
                last_message_time = datetime.strptime(seen_raw[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                last_message_time = None
        if last_message_time is None:
            for ch in interaction.guild.text_channels:
                try:
                    async for msg in ch.history(limit=50):
                        if msg.author.id == user.id:
                            msg_time = msg.created_at if msg.created_at.tzinfo else msg.created_at.replace(tzinfo=timezone.utc)
                            if last_message_time is None or msg_time > last_message_time:
                                last_message_time = msg_time
                            break  # only the most recent message per channel matters
                except (discord.Forbidden, discord.HTTPException):
                    continue

        now = datetime.now(timezone.utc)
        if last_message_time is not None:
            days_ago = max(0, (now - last_message_time).days)
        elif user.joined_at is not None:
            days_ago = max(0, (now - user.joined_at).days)
        else:
            days_ago = 999

        if days_ago < 2:
            await interaction.followup.send(
                f"{user.display_name} was just here recently. Don't ping people for no reason.",
            )
            return

        system_prompt = get_time_aware_system_prompt(ctx.db, username=None)
        user_prompt = get_kanmanilla_prompt(user.display_name, days_ago)

        _res = await ctx.llm.generate(
            LLMRequest(purpose="summary", system=system_prompt, prompt=user_prompt),
            fallback=f"🚨 MISSING: {user.display_name}. Last seen {days_ago} days ago. {user.mention} — are you still out there? Reply here.",
            name="KanmanillaRequest",
            cache_type="qa",
        )
        poster, _ = _res.text, _res.from_cache
        await interaction.followup.send(f"{poster}\n{user.mention}")
        logger.info("Kanmanilla posted for %s (last seen %d days ago)", user.display_name, days_ago)
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """Summarise a linked article when a user reacts with the configured emoji."""
        ctx = self.ctx
        if ctx.db is None or payload.user_id == ctx.bot.user.id:
            return

        if not ctx.settings.feat("feature_link_summary"):
            return

        summary_emoji = get_config_str(ctx.db, "link_summary_emoji", "📰")
        if str(payload.emoji) != summary_emoji:
            return

        # Deduplicate: ignore if another reaction already triggered a summary
        if payload.message_id in ctx.state.summarized_messages:
            return

        # get_channel misses uncached channels (threads, recently created channels)
        channel = ctx.bot.get_channel(payload.channel_id)
        if channel is None:
            try:
                channel = await ctx.bot.fetch_channel(payload.channel_id)
            except (discord.NotFound, discord.Forbidden):
                return

        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden):
            return

        raw_urls = _URL_RE.findall(message.content)
        if not raw_urls:
            return

        # Strip trailing punctuation that the regex sweeps up (e.g. "https://x.com.")
        url = _URL_TRAIL_RE.sub("", raw_urls[0])

        # Mark as in-progress before the async fetch so concurrent reactions are dropped
        ctx.state.summarized_messages.add(payload.message_id)
        if len(ctx.state.summarized_messages) > _SUMMARIZED_MAX:
            try:
                ctx.state.summarized_messages.pop()
            except KeyError:
                pass

        try:
            import aiohttp

            async with aiohttp.ClientSession(
                headers={"User-Agent": _SCRAPE_UA}
            ) as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(connect=5, total=15),
                    allow_redirects=True,
                ) as resp:
                    if resp.status != 200:
                        await message.reply(
                            f"Couldn't fetch that link (HTTP {resp.status}). Try again later."
                        )
                        return
                    html = await resp.text(errors="replace")

            page_text = _extract_article_text(html)

            if not page_text.strip():
                await message.reply(
                    "That page has no readable text — probably a paywall or JS-only site."
                )
                return

            user_prompt = get_link_summary_prompt(page_text, url)

            _res = await ctx.llm.generate(
                LLMRequest(purpose="summary", system=LINK_SUMMARY_SYSTEM_PROMPT, prompt=user_prompt),
                fallback=random.choice(FALLBACK_MESSAGES),
                name="LinkSummary",
                cache_type="qa",
            )
            summary, _ = _res.text, _res.from_cache
            await message.reply(f"📰 **Link Summary:**\n{summary}")
            logger.info("Link summary sent for %s", url)

        except Exception as exc:
            logger.warning("Link summary failed for %s: %s", url, exc)
            await message.reply("Something went wrong reading that link. Try again.")


async def setup(bot) -> None:
    await bot.add_cog(SummariesCog(bot.ctx))
