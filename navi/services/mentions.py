# navi/services/mentions.py - AllowedMentions helpers so model output can never ping @everyone, roles or strangers

from __future__ import annotations

import discord

# Bot-wide default: no @everyone, no roles; users are allowed because the bot itself puts the intended
# user's mention into replies (the safety filter rejects any model-written <@id> before that happens).
DEFAULT = discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=True)


def only_user(*users) -> discord.AllowedMentions:
    """Allow pinging exactly these users (Member/User objects or IDs); nothing else."""
    return discord.AllowedMentions(everyone=False, roles=False, users=[getattr(u, "id", u) for u in users], replied_user=bool(users))


def nobody() -> discord.AllowedMentions:
    return discord.AllowedMentions.none()
