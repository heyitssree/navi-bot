# navi/cogs/privacy.py - /privacy status | opt_out | opt_in (all ephemeral)

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from navi.context import AppContext
from navi.db.repos.users import get_user_strikes
from navi.services.privacy import _parse

logger = logging.getLogger("navi.cogs.privacy")

WARNING = (
    "**Opting out of Navi**\n\n"
    "This **permanently deletes** everything Navi stores about you: Boli points, partner points, XP, strikes, holdings, perks, "
    "saved media shortcuts, game results, prediction history and activity records.\n"
    "After that Navi ignores your messages and commands, never targets or mentions you (no curses, blessings, gifts, "
    "summaries or welcome messages), and you stay off the leaderboards.\n\n"
    "If you opt back in later you start with a **fresh profile** (new Rashi, zero points), and only after a waiting period.\n"
    "Backups and replicas age out within 72 hours and logs within 14 days.\n\n"
    "Press **Confirm** within 60 seconds to go ahead."
)


class OptOutView(discord.ui.View):
    def __init__(self, ctx: AppContext, user_id: int) -> None:
        super().__init__(timeout=60)
        self.ctx, self.user_id = ctx, user_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your confirmation.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(content="Timed out. Nothing was deleted.", view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Confirm opt-out", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ctx = interaction.client.ctx
        self.stop()
        await interaction.response.edit_message(content="Deleting your data...", view=None)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, ctx.privacy.opt_out, ctx, self.user_id)
        for emoji_id in result.orphan_app_emojis:             # application emojis only this user used
            try:
                await ctx.bot.delete_application_emoji(int(emoji_id))
            except Exception as exc:
                logger.warning("Could not delete app emoji %s: %s", emoji_id, exc)
        logger.info("A user opted out (%d rows deleted).", result.rows_deleted)
        await interaction.edit_original_response(content="Done. You have opted out of Navi and your data is deleted. `/privacy opt_in` brings you back.")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Cancelled. Nothing was deleted.", view=None)


class PrivacyGroup(app_commands.Group):
    def __init__(self) -> None:
        super().__init__(name="privacy", description="Opt out of Navi and delete your data, or come back")

    @app_commands.command(name="status", description="See whether you are opted in")
    async def status(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        state = ctx.privacy.status(interaction.user.id)
        if state and state[0] == "out":
            days = ctx.settings.get("privacy.optin_cooldown_days")
            text = "You are **opted out**. Navi ignores you and holds none of your data."
            if state[1]:
                text += f" Changed on {state[1][:10]}; you can opt back in from {(_parse(state[1]) + timedelta(days=days)).strftime('%Y-%m-%d')}."
        else:
            text = "You are **opted in**. `/privacy opt_out` deletes your data and makes Navi ignore you."
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="opt_out", description="Delete all your data and make Navi ignore you")
    async def opt_out(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        if ctx.privacy.is_opted_out(interaction.user.id):
            await interaction.response.send_message("You are already opted out.", ephemeral=True)
            return
        if ctx.settings.get("privacy.block_optout_with_strikes") and get_user_strikes(ctx.db, interaction.user.id) > 0:
            await interaction.response.send_message(
                "You can't opt out while you have strikes on record: deleting them would let strikes be dodged. "
                "Ask a moderator once they are cleared.", ephemeral=True)
            return
        view = OptOutView(ctx, interaction.user.id)
        await interaction.response.send_message(WARNING, view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @app_commands.command(name="opt_in", description="Come back to Navi with a fresh profile")
    async def opt_in(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        result = ctx.privacy.opt_in(interaction.user.id, ctx.settings.get("privacy.optin_cooldown_days"))
        if not result.ok:
            await interaction.response.send_message(f"{result.message} You can opt back in from **{result.available_on}**.", ephemeral=True)
            return
        await interaction.response.send_message(result.message, ephemeral=True)


class PrivacyCog(commands.Cog):
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._added: list = []

    async def cog_load(self) -> None:
        group = PrivacyGroup()
        self.ctx.bot.tree.add_command(group)
        self._added.append(group)

    async def cog_unload(self) -> None:
        for cmd in self._added:
            self.ctx.bot.tree.remove_command(cmd.name, type=cmd.type)


async def setup(bot) -> None:
    await bot.add_cog(PrivacyCog(bot.ctx))
