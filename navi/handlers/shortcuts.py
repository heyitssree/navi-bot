# navi/handlers/shortcuts.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import io
import logging
import re

import discord

from navi.db.repos.media import get_local_media, update_app_emoji_last_used

logger = logging.getLogger("navi.handlers.shortcuts")


# Local media shortcut trigger (;;name)
_LOCAL_SHORTCUT_RE = re.compile(r"^;;(\w+)", re.IGNORECASE)


async def handle_shortcut(ctx, message: discord.Message) -> bool:
    """Local media shortcut trigger (;;name). Consumes the message when a shortcut matched."""
    # ---- Local media shortcut trigger (;;name) ----
    shortcut_match = _LOCAL_SHORTCUT_RE.match(message.content.strip())
    if shortcut_match and ctx.settings.get("feature.local_media"):
        shortcut_key = shortcut_match.group(1).lower()
        media_entry = get_local_media(ctx.db, shortcut_key)
        if media_entry:
            storage_type = media_entry.get("storage_type", "local")
            # Mirror reply chain if the ;;shortcut message is itself a reply
            reply_target = (
                message.reference.resolved
                if message.reference and isinstance(message.reference.resolved, discord.Message)
                else None
            )

            if storage_type in ("native_emoji", "app_emoji"):
                animated = media_entry.get("animated", False)
                dname = media_entry.get("discord_name") or shortcut_key
                did = media_entry.get("discord_id")
                emoji_str = f"<{'a' if animated else ''}:{dname}:{did}>"
                if storage_type == "app_emoji" and did:
                    update_app_emoji_last_used(ctx.db, did)
                if reply_target:
                    await reply_target.reply(content=emoji_str)
                else:
                    await message.channel.send(content=emoji_str)

            elif storage_type == "app_emoji_sticker":
                animated = media_entry.get("animated", False)
                dname = media_entry.get("discord_name") or shortcut_key
                did = media_entry.get("discord_id")
                emoji_str = f"<{'a' if animated else ''}:{dname}:{did}>"
                if did:
                    update_app_emoji_last_used(ctx.db, did)
                if reply_target:
                    await reply_target.reply(content=emoji_str)
                else:
                    await message.channel.send(content=emoji_str)

            elif storage_type == "native_sticker":
                sticker_url = media_entry.get("source_url")
                if sticker_url:
                    import aiohttp as _aiohttp
                    try:
                        async with _aiohttp.ClientSession() as session:
                            async with session.get(sticker_url) as resp:
                                if resp.status == 200:
                                    data = await resp.read()
                                    ext = sticker_url.rsplit(".", 1)[-1].split("?")[0] or "png"
                                    f = discord.File(
                                        io.BytesIO(data),
                                        filename=f"{shortcut_key}.{ext}",
                                    )
                                    if reply_target:
                                        await reply_target.reply(file=f)
                                    else:
                                        await message.channel.send(file=f)
                    except Exception as exc:
                        logger.warning(";;%s sticker fetch failed: %s", shortcut_key, exc)
                        await message.reply(f"Could not fetch sticker for `;;{shortcut_key}`.")
                else:
                    await message.reply(f"Sticker URL for `;;{shortcut_key}` is missing.")

            else:
                # local file (original behavior)
                import os as _os
                if _os.path.isfile(media_entry["file_path"]):
                    if reply_target:
                        await reply_target.reply(file=discord.File(media_entry["file_path"]))
                    else:
                        await message.channel.send(file=discord.File(media_entry["file_path"]))
                else:
                    await message.reply(f"Media file for `;;{shortcut_key}` is missing from disk.")

        return True  # shortcut messages don't trigger any other processing
    return False

