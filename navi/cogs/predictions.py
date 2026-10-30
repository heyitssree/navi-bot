# navi/cogs/predictions.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import asyncio
import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

from navi.context import AppContext
from navi.data.messages import BOT_LOOP_CURSE_REPLIES
from navi.db.repos.content import get_todays_user_prediction
from navi.db.repos.users import get_user_profile
from navi.services.levels import maybe_announce_levelup
from navi.services.points import award
from navi.services.predictions import format_cached_spam_reply, get_navi_prediction, get_user_minute_count
from navi.services.templates import get_template

logger = logging.getLogger("navi.cogs.predictions")





class PredictionsCog(commands.Cog):
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._added: list = []

    async def cog_load(self) -> None:
        pass

    async def cog_unload(self) -> None:
        for cmd in self._added:
            self.ctx.bot.tree.remove_command(cmd.name, type=cmd.type)

    @app_commands.command(name="navi", description="Get a Navi prediction")
    async def navi_slash(self, interaction: discord.Interaction,
        user: discord.Member | None = None,
    ) -> None:
        ctx = self.ctx
        if not ctx.settings.get("feature.navi"):
            await interaction.response.send_message(
                "Navi predictions are currently disabled.", ephemeral=True
            )
            return

        # Bot-loop protection: reject attempts to get predictions for other bots
        if user is not None and user.bot:
            await interaction.response.send_message(
                f"{interaction.user.mention} {random.choice(BOT_LOOP_CURSE_REPLIES)}"
            )
            return

        # Record usage and get per-minute count BEFORE checking cache
        usage_count = get_user_minute_count(ctx, interaction.user.id, increment=True)

        target = user or interaction.user
        display_name = target.display_name
        mention_str = target.mention

        # Tiered response for 2nd+ use within the minute
        if usage_count > 1:
            cached_pred = get_todays_user_prediction(ctx.db, interaction.user.id)
            if cached_pred:
                if usage_count == 2 and random.random() >= 0.35:
                    # 65% chance: fall through to Gemini (handled below)
                    pass
                else:
                    # 2nd use (35% case): short delay. 3rd+ use: longer delay to feel AI-generated.
                    reply = format_cached_spam_reply(cached_pred, display_name)
                    delay = random.uniform(1.5, 3.5) if usage_count >= 3 else random.uniform(1.0, 2.5)
                    await interaction.response.defer(thinking=True)
                    await asyncio.sleep(delay)
                    await interaction.followup.send(reply)
                    return

        await interaction.response.defer(thinking=True)
        await asyncio.sleep(random.uniform(1.0, 2.0))

        prediction = await get_navi_prediction(ctx, target.id, display_name, usage_count=usage_count)
        final_reply = prediction.replace(display_name, mention_str)
        await interaction.followup.send(final_reply)

        # +2 Boli Points + XP for using /navi (only on first fresh call)
        if usage_count == 1:
            award(ctx.db, interaction.user.id, 2, 2, reason="prediction")
            logger.info("%s used /navi → +2 Boli Points +2 XP", interaction.user.display_name)
            if interaction.channel:
                await maybe_announce_levelup(ctx, 
                    interaction.user.mention, interaction.user.id, interaction.channel
                )
    @app_commands.command(name="ping", description="Check if Navi is awake")
    async def ping_slash(self, interaction: discord.Interaction) -> None:
        ctx = self.ctx
        latency_ms = round(ctx.bot.latency * 1000)
        profile = get_user_profile(ctx.db, interaction.user.id)
        pts = profile["total_boli_points"] if profile else 0
        reply = get_template("ping", pts, latency=latency_ms)
        if not reply:
            reply = f"Pong! Latency is {latency_ms}ms."
        await interaction.response.send_message(reply, ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(PredictionsCog(bot.ctx))
