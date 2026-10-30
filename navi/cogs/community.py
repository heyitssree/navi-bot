# navi/cogs/community.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import asyncio
import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

from navi.context import AppContext
from navi.data.messages import MODA_INTROS, PENDING_WELCOME_MESSAGES, WELCOME_MESSAGES
from navi.db.repos.users import upsert_user

logger = logging.getLogger("navi.cogs.community")




async def _temp_vc_expire(ctx, channel: discord.VoiceChannel, delay: int) -> None:
    """Sleep delay seconds then delete the voice channel if it still exists."""
    await asyncio.sleep(delay)
    try:
        await channel.delete(reason="Temp VC expired.")
        logger.info("Temp VC '%s' auto-deleted after timer expiry.", channel.name)
    except discord.NotFound:
        logger.debug("Temp VC '%s' was already deleted before timer fired.", channel.name)
    except Exception as exc:
        logger.warning("Could not delete temp VC '%s': %s", channel.name, exc)
    finally:
        ctx.state.temp_vc_registry.pop(channel.id, None)


class CommunityCog(commands.Cog):
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._added: list = []

    async def cog_load(self) -> None:
        pass

    async def cog_unload(self) -> None:
        for cmd in self._added:
            self.ctx.bot.tree.remove_command(cmd.name, type=cmd.type)

    @app_commands.command(
        name="temp_vc",
        description="Create a temporary voice channel that self-destructs after 30 minutes",
    )
    @app_commands.describe(
        name="Name for the voice channel",
        capacity="Max users allowed (2–99)",
    )
    async def temp_vc_slash(self, interaction: discord.Interaction,
        name: str,
        capacity: app_commands.Range[int, 2, 99],
    ) -> None:
        ctx = self.ctx
        if not ctx.settings.get("feature.temp_vc"):
            await interaction.response.send_message(
                "Temp voice channel creation is currently disabled.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command only works inside a server.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=False)

        # Place the VC in the same category as the invoking channel when possible.
        category: discord.CategoryChannel | None = None
        if isinstance(interaction.channel, discord.abc.GuildChannel):
            category = interaction.channel.category
        if category is None:
            category = discord.utils.get(guild.categories, name="Temp VCs")

        # Roles with move_members or manage_channels already bypass user limits in
        # Discord natively; adding an explicit connect overwrite makes the intent
        # visible in the channel settings as well.
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(connect=True),
        }
        for role in guild.roles:
            if role.managed:
                continue
            if role.permissions.manage_channels or role.permissions.move_members:
                overwrites[role] = discord.PermissionOverwrite(connect=True)

        try:
            vc = await guild.create_voice_channel(
                name=name,
                category=category,
                user_limit=capacity,
                overwrites=overwrites,
                reason=f"Temp VC requested by {interaction.user.display_name}",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have permission to create voice channels. Ask a mod to grant me **Manage Channels**.",
                ephemeral=True,
            )
            return
        except Exception as exc:
            logger.error("Failed to create temp VC: %s", exc)
            await interaction.followup.send(
                "Something went wrong while creating the voice channel. Try again.",
                ephemeral=True,
            )
            return

        task = asyncio.create_task(_temp_vc_expire(ctx, vc, ctx.settings.get("limit.temp_vc_minutes") * 60))
        ctx.state.temp_vc_registry[vc.id] = task

        await interaction.followup.send(
            f"🎙️ Voice channel **{vc.name}** created with a limit of **{capacity}** users.\n"
            f"The stars grant you {ctx.settings.get('limit.temp_vc_minutes')} minutes. Use them wisely."
        )
        logger.info(
            "Temp VC '%s' (id=%d, limit=%d) created by %s.",
            vc.name, vc.id, capacity, interaction.user.display_name,
        )
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Delete a temp VC early when it becomes completely empty."""
        ctx = self.ctx
        if before.channel is None or before.channel.id not in ctx.state.temp_vc_registry:
            return

        channel = before.channel
        remaining = [m for m in channel.members if not m.bot]
        if remaining:
            return

        # All users gone — cancel the 30-minute timer and delete now.
        task = ctx.state.temp_vc_registry.pop(channel.id, None)
        if task:
            task.cancel()

        try:
            await channel.delete(reason="Temp VC emptied before the 30-minute timer.")
            logger.info("Temp VC '%s' deleted early (channel empty).", channel.name)
        except discord.NotFound:
            pass
        except Exception as exc:
            logger.warning("Could not early-delete temp VC '%s': %s", channel.name, exc)
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Welcome new member after a 1-minute delay, routing on verification status."""
        ctx = self.ctx
        channel = (
            discord.utils.get(member.guild.text_channels, name=ctx.config.general_channel)
            or discord.utils.get(member.guild.text_channels, name="general")
            or member.guild.system_channel
        )
        if not channel:
            logger.warning("Could not find a welcome channel for new member %s", member.display_name)
            return

        upsert_user(ctx.db, member.id, member.display_name)

        if not ctx.settings.get("feature.welcome"):
            logger.info("Welcome messages disabled — skipping for %s", member.display_name)
            return

        # 1-minute delay before posting (non-blocking)
        await asyncio.sleep(60)

        # Re-fetch the member so we get the most current state (pending flag, still in guild, etc.)
        try:
            current_member = await member.guild.fetch_member(member.id)
        except discord.NotFound:
            logger.info("Member %s left before welcome message was sent.", member.display_name)
            return

        if current_member.pending:
            # User hasn't verified phone number / accepted screening rules yet
            welcome_line = random.choice(PENDING_WELCOME_MESSAGES).format(user=current_member.mention)
            await channel.send(welcome_line)
            logger.info("Sent pending/verify reminder to %s in #%s", current_member.display_name, channel.name)
        else:
            # Fully verified — standard welcome + Moda intro
            welcome_line = random.choice(WELCOME_MESSAGES).format(user=current_member.mention)
            moda_line = random.choice(MODA_INTROS)
            await channel.send(f"{welcome_line} {moda_line}")
            logger.info("Welcomed verified member %s in #%s", current_member.display_name, channel.name)


async def setup(bot) -> None:
    await bot.add_cog(CommunityCog(bot.ctx))
