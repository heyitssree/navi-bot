# navi/cogs/moderation.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from navi.context import AppContext
from navi.db.repos.users import get_user_strikes
from navi.handlers.strikes import handle_strike
from navi.llm.base import LLMRequest
from navi.llm.prompts import get_audit_prompt, get_mod_tldr_prompt

logger = logging.getLogger("navi.cogs.moderation")





class ModerationCog(commands.Cog):
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._added: list = []

    async def cog_load(self) -> None:
        pass

    async def cog_unload(self) -> None:
        for cmd in self._added:
            self.ctx.bot.tree.remove_command(cmd.name, type=cmd.type)

    @app_commands.command(name="audit", description="Audit a user's messages against server rules (Mods only)")
    @app_commands.describe(
        user="The member to audit",
        channel="Channel to fetch messages from (defaults to current channel)",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def audit_slash(self, interaction: discord.Interaction,
        user: discord.Member,
        channel: discord.TextChannel | None = None,
    ) -> None:
        ctx = self.ctx
        if not ctx.settings.feat("feature_audit"):
            await interaction.response.send_message("Audit feature is currently disabled.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        # Find rules channel dynamically
        rules_ch = discord.utils.find(
            lambda c: "rule" in c.name.lower(),
            interaction.guild.text_channels,
        ) if interaction.guild else None

        rules_text = "No rules channel found on this server."
        if rules_ch:
            try:
                rule_msgs: list[str] = []
                async for msg in rules_ch.history(limit=50):
                    if msg.content.strip():
                        rule_msgs.append(msg.content.strip())
                if rule_msgs:
                    rules_text = "\n".join(reversed(rule_msgs))
            except discord.Forbidden:
                rules_text = "(Could not read rules channel — missing permissions)"

        # Fetch user messages
        target_ch = channel or interaction.channel
        user_lines: list[str] = []
        try:
            async for msg in target_ch.history(limit=200):
                if msg.author.id == user.id and msg.content.strip():
                    user_lines.append(f"[{msg.created_at.strftime('%H:%M')}] {msg.author.display_name}: {msg.content.strip()}")
                if len(user_lines) >= 100:
                    break
        except discord.Forbidden:
            await interaction.followup.send("Cannot read that channel — missing permissions.", ephemeral=True)
            return

        if not user_lines:
            await interaction.followup.send(
                f"No messages found from **{user.display_name}** in that channel.", ephemeral=True
            )
            return

        messages_text = "\n".join(reversed(user_lines))
        user_prompt = get_audit_prompt(rules_text, messages_text)
        system_prompt = "You are a neutral moderation assistant. Be objective and precise."

        _res = await ctx.llm.generate(
            LLMRequest(purpose="mod", system=system_prompt, prompt=user_prompt),
            fallback="Audit failed — Gemini is unavailable. Check logs.",
            name="AuditRequest",
            cache_type="qa",
        )
        report, _ = _res.text, _res.from_cache

        await interaction.followup.send(
            f"**🔍 Audit Report — {user.display_name}** (from #{target_ch.name})\n\n{report}",
            ephemeral=True,
        )
        logger.info("Audit run by %s for %s in #%s", interaction.user.display_name, user.display_name, target_ch.name)
    @app_commands.command(name="mod_tldr", description="Summarise the current thread for moderators (Mods only)")
    @app_commands.default_permissions(manage_messages=True)
    async def mod_tldr_slash(self, interaction: discord.Interaction) -> None:
        ctx = self.ctx
        if not ctx.settings.feat("feature_mod_tldr"):
            await interaction.response.send_message("Mod TL;DR feature is currently disabled.", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "This command only works inside a thread. Run it from within the thread.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        thread: discord.Thread = interaction.channel
        lines: list[str] = []
        _mention_re = re.compile(r"<@!?\d+>|<#\d+>|<@&\d+>")

        async for msg in thread.history(limit=500, oldest_first=True):
            if msg.author.bot:
                continue
            text = _mention_re.sub("[user]", msg.content).strip()
            if text and not text.startswith("/"):
                lines.append(f"{msg.author.display_name}: {text}")

        if not lines:
            await interaction.followup.send("This thread has no readable messages to summarise.", ephemeral=True)
            return

        thread_text = "\n".join(lines)
        user_prompt = get_mod_tldr_prompt(thread_text)
        system_prompt = "You are a neutral moderation assistant. Be concise and factual. Use exact usernames."

        _res = await ctx.llm.generate(
            LLMRequest(purpose="mod", system=system_prompt, prompt=user_prompt),
            fallback="Thread summary failed — Gemini is unavailable.",
            name="ModTldrRequest",
            cache_type="qa",
        )
        summary, _ = _res.text, _res.from_cache

        await interaction.followup.send(
            f"📋 **Thread TL;DR — #{thread.name}**\n\n{summary}",
            ephemeral=True,
        )
        logger.info("mod_tldr run by %s in thread #%s", interaction.user.display_name, thread.name)
    @app_commands.command(name="strike", description="Issue a manual strike to a user (Moderators only)")
    @app_commands.describe(user="The member to strike", reason="Why you're issuing the strike")
    @app_commands.default_permissions(manage_messages=True)
    async def strike_slash(self, interaction: discord.Interaction,
        user: discord.Member,
        reason: str = "Manual mod action",
    ) -> None:
        ctx = self.ctx
        if user.bot:
            await interaction.response.send_message("You can't strike a bot.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await handle_strike(ctx, user, interaction.channel)
        current = get_user_strikes(ctx.db, user.id)
        await interaction.followup.send(
            f"Strike issued to **{user.display_name}**. Reason: *{reason}*. "
            f"They now have **{current} strike(s)**.",
            ephemeral=True,
        )
        logger.info("Manual strike issued to %s by %s — reason: %s", user.display_name, interaction.user.display_name, reason)


async def setup(bot) -> None:
    await bot.add_cog(ModerationCog(bot.ctx))
