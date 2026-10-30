# navi/services/permissions.py - who may use /admin

from __future__ import annotations

import discord


async def can_use_admin(ctx, user: discord.abc.User) -> bool:
    """Owner (OWNER_ID or the Discord application owner), or a member holding the system.panel_role role."""
    if ctx.config.owner_id and user.id == ctx.config.owner_id:
        return True
    role_id = ctx.settings.get("system.panel_role")
    if role_id and any(getattr(r, "id", None) == role_id for r in getattr(user, "roles", [])):
        return True
    try:
        app_info = await ctx.bot.application_info()
        return user.id == app_info.owner.id
    except Exception:
        return False
