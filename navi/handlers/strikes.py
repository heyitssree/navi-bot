# navi/handlers/strikes.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import logging

import discord

from navi.db.repos.users import increment_user_strikes, reset_user_strikes

logger = logging.getLogger("navi.handlers.strikes")


async def handle_strike(ctx, member: discord.Member, channel: discord.abc.Messageable) -> None:
    """Increment strike counter and issue a public warning. At 3 strikes, alert the mod channel and reset."""
    new_strikes = increment_user_strikes(ctx.db, member.id)

    if new_strikes == 1:
        await channel.send(f"{member.mention} — Strike 1. Two more and the mod team gets notified.")
        logger.info("Strike 1 issued to %s", member.display_name)

    elif new_strikes == 2:
        await channel.send(f"{member.mention} — Strike 2. One more and this escalates.")
        logger.info("Strike 2 issued to %s", member.display_name)

    elif new_strikes >= 3:
        reset_user_strikes(ctx.db, member.id)
        mod_ch = None
        if isinstance(channel, discord.TextChannel):
            configured = ctx.settings.get("channel.mod_alerts")
            mod_ch = channel.guild.get_channel(configured) if configured else None
            if mod_ch is None:   # fall back to the channel named by MOD_CHANNEL_NAME
                mod_ch = discord.utils.get(channel.guild.text_channels, name=ctx.config.mod_channel_name)
        if mod_ch:
            await mod_ch.send(
                f"🚨 **Mod Alert:** {member.mention} has hit **3 strikes**. "
                f"Strikes have been reset to 0 — further action is up to the mod team."
            )
        await channel.send(f"🚨 {member.mention} — 3 strikes. Mod team has been notified.")
        logger.info("Strike 3 — mod channel alerted for %s, strikes reset", member.display_name)
