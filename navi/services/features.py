# navi/services/features.py - shared "this feature is switched off" reply for slash commands

from __future__ import annotations

import discord

from navi.settings.registry import resolve


async def deny_if_disabled(interaction: discord.Interaction, key: str) -> bool:
    """If the feature setting is off, tell the user (ephemeral) and return True so the caller can stop."""
    ctx = interaction.client.ctx
    if ctx.settings.get(key):
        return False
    text = f"{resolve(key).label} is currently switched off."
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)
    return True
