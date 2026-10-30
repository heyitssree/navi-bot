# navi/cogs/media.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import io
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from navi.context import AppContext
from navi.db.repos.media import (
    _APP_EMOJI_EVICT_THRESHOLD,
    count_app_emojis,
    delete_app_emoji_record,
    get_global_local_media_count,
    get_local_media,
    get_oldest_app_emoji,
    get_user_local_media_count,
    list_user_local_media,
    save_app_emoji,
    save_local_media,
    update_app_emoji_last_used,
)

logger = logging.getLogger("navi.cogs.media")


_APP_EMOJI_RE = re.compile(r"<a?:\w+:(\d+)>")


# Matches custom emojis: <:name:id> or <a:name:id>
_CUSTOM_EMOJI_RE = re.compile(r"<(a?):(\w+):(\d+)>")


_LOCAL_MEDIA_DIR = "data/local_media"


def _sanitize_shortcut(raw: str) -> str | None:
    """Lowercase, replace spaces/hyphens with underscores, strip non-word chars.
    Returns None if the result is too short to be useful."""
    cleaned = re.sub(r"[\s\-]+", "_", raw.lower())
    cleaned = re.sub(r"[^\w]", "", cleaned).strip("_")
    return cleaned if len(cleaned) >= 2 else None


async def _evict_and_upload_app_emoji(ctx, name: str,
    image_bytes: bytes,
    animated: bool = False,
) -> tuple[str, str] | None:
    """Upload image_bytes as a Discord Application Emoji, evicting LRU if at limit.

    Returns (emoji_id, emoji_name) on success, or None on failure.
    The name is sanitized to comply with Discord's emoji name rules.
    """
    # Sanitize: only word chars, 2-32 length
    safe_name = re.sub(r"[^\w]", "_", name)[:32]
    if len(safe_name) < 2:
        safe_name = "emoji_" + safe_name

    # Evict if at limit
    if count_app_emojis(ctx.db) >= _APP_EMOJI_EVICT_THRESHOLD:
        oldest = get_oldest_app_emoji(ctx.db)
        if oldest:
            try:
                await ctx.bot.delete_application_emoji(int(oldest["emoji_id"]))
                logger.info("Evicted LRU app emoji %s (%s)", oldest["emoji_id"], oldest["name"])
            except Exception as exc:
                logger.warning("Could not delete app emoji %s: %s", oldest["emoji_id"], exc)
            delete_app_emoji_record(ctx.db, oldest["emoji_id"])

    try:
        new_emoji = await ctx.bot.create_application_emoji(name=safe_name, image=image_bytes)
        save_app_emoji(ctx.db, str(new_emoji.id), new_emoji.name, animated=animated)
        return str(new_emoji.id), new_emoji.name
    except Exception as exc:
        logger.error("Failed to create application emoji '%s': %s", safe_name, exc)
        return None


async def _auto_save_media(
    interaction: discord.Interaction,
    storage_type: str,
    media_type: str,
    suggested_name: str,
    download_url: str,
    file_ext: str = "png",
) -> None:
    """Fully-automated save: defer → resolve name → download → upload → confirm.

    No modal is shown. The name is taken from the source (emoji/sticker name) and
    a numeric suffix is appended automatically if the shortcut is already taken.
    Users type ;;name in chat to replay the saved media; the ;; is just the chat
    trigger prefix and is never entered by the user during saving.
    """
    ctx = interaction.client.ctx
    user_id = interaction.user.id

    # ---- Limits ----
    user_count = get_user_local_media_count(ctx.db, user_id)
    max_per_user = ctx.settings.get("limit.media_per_user")
    if user_count >= max_per_user:
        await interaction.followup.send(
            f"⚠️ You’ve hit your media limit ({max_per_user} items). "
            f"Delete some with `/my_media` first.",
            ephemeral=True,
        )
        return

    global_count = get_global_local_media_count(ctx.db)
    max_global = ctx.settings.get("limit.media_global")
    if global_count >= max_global:
        await interaction.followup.send(
            f"⚠️ The global media storage is full ({max_global} items). Contact an admin.",
            ephemeral=True,
        )
        return

    # ---- Resolve unique name (auto-suffix on collision) ----
    base = _sanitize_shortcut(suggested_name) or "saved_emoji"
    name = base
    suffix = 1
    while get_local_media(ctx.db, name):  # name taken by anyone
        name = f"{base}_{suffix}"
        suffix += 1
        if suffix > 99:
            await interaction.followup.send(
                "⚠️ Couldn’t find a free shortcut name. "
                f"Try deleting an old `;;{base}*` entry with `/my_media`.",
                ephemeral=True,
            )
            return

    # ---- Download ----
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(download_url) as resp:
                if resp.status != 200:
                    await interaction.followup.send(
                        f"⚠️ Couldn’t download the media (CDN returned {resp.status}).",
                        ephemeral=True,
                    )
                    return
                data = await resp.read()
    except Exception as exc:
        logger.error("_auto_save_media: download failed for %s: %s", download_url, exc)
        await interaction.followup.send("⚠️ Download failed. Check the logs.", ephemeral=True)
        return

    # ---- Upload as Application Emoji ----
    result = await _evict_and_upload_app_emoji(ctx, name, data, animated=(file_ext == "gif"))
    if result is None:
        await interaction.followup.send(
            "⚠️ Failed to upload as a Discord emoji. "
            "The image may be too large (max 256 KB) or an unsupported format.",
            ephemeral=True,
        )
        return

    emoji_id, emoji_name = result
    save_local_media(
        ctx.db,
        user_id=user_id,
        shortcut=name,
        file_path="",
        media_type=media_type,
        source_url=download_url,
        storage_type=storage_type,
        discord_id=emoji_id,
        discord_name=emoji_name,
        animated=(file_ext == "gif"),
    )

    animated = file_ext == "gif"
    emoji_str = f"<{'a' if animated else ''}:{emoji_name}:{emoji_id}>"
    await interaction.followup.send(
        f"✅ Saved {emoji_str} as `;;{name}` — "
        f"type `;;{name}` in any channel and I’ll post it!",
        ephemeral=True,
    )
    logger.info(
        "User %d auto-saved %s ';;%s' (emoji_id=%s)",
        user_id, media_type, name, emoji_id,
    )


class LocalMediaPickerView(discord.ui.View):
    """Select menu for 'Reply with Media' — lets user pick one of their saved ;;shortcuts."""

    def __init__(self, target_message: discord.Message, entries: list[dict]) -> None:
        super().__init__(timeout=60)
        self._target = target_message

        options = []
        for e in entries[:25]:  # Discord select cap
            # entries now include storage_type, discord_id, discord_name, animated
            st = e.get("storage_type", "local")
            picker_emoji: discord.PartialEmoji | None = None
            if st in ("app_emoji", "app_emoji_sticker", "native_emoji"):
                did = e.get("discord_id")
                dname = e.get("discord_name") or e["shortcut"]
                animated = e.get("animated", False)
                if did:
                    try:
                        picker_emoji = discord.PartialEmoji(
                            name=dname, id=int(did), animated=animated
                        )
                    except Exception:
                        picker_emoji = None
            type_label = e["media_type"].capitalize()  # "Emoji" or "Sticker"
            options.append(
                discord.SelectOption(
                    label=f";;{e['shortcut']}",
                    value=e["shortcut"],
                    description=type_label,
                    emoji=picker_emoji,
                )
            )
        select = discord.ui.Select(placeholder="Pick a saved shortcut to reply with…", options=options)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        shortcut_key = interaction.data["values"][0]
        media_entry = get_local_media(ctx.db, shortcut_key)
        if media_entry is None:
            await interaction.response.edit_message(content="That shortcut no longer exists.", view=None)
            return

        storage_type = media_entry.get("storage_type", "local")
        attribution = f"-# Sent by {interaction.user.display_name}"

        try:
            if storage_type in ("native_emoji", "app_emoji"):
                animated = media_entry.get("animated", False)
                dname = media_entry.get("discord_name") or shortcut_key
                did = media_entry.get("discord_id")
                emoji_str = f"<{'a' if animated else ''}:{dname}:{did}>"
                if storage_type == "app_emoji" and did:
                    update_app_emoji_last_used(ctx.db, did)
                await self._target.reply(content=f"{emoji_str}\n{attribution}")
            elif storage_type == "app_emoji_sticker":
                animated = media_entry.get("animated", False)
                dname = media_entry.get("discord_name") or shortcut_key
                did = media_entry.get("discord_id")
                emoji_str = f"<{'a' if animated else ''}:{dname}:{did}>"
                if did:
                    update_app_emoji_last_used(ctx.db, did)
                # Send emoji alone first so Discord enlarges it, then attribution
                await self._target.reply(content=emoji_str)
                await self._target.channel.send(attribution)
            elif storage_type == "native_sticker":
                sticker_url = media_entry.get("source_url")
                if sticker_url:
                    import aiohttp as _aiohttp
                    async with _aiohttp.ClientSession() as session:
                        async with session.get(sticker_url) as resp:
                            if resp.status == 200:
                                data = await resp.read()
                                ext = sticker_url.rsplit(".", 1)[-1].split("?")[0] or "png"
                                await self._target.reply(
                                    content=attribution,
                                    file=discord.File(
                                        io.BytesIO(data),
                                        filename=f"{shortcut_key}.{ext}",
                                    ),
                                )
                            else:
                                await self._target.reply(content=f"Sticker CDN unavailable ({resp.status}).")
                else:
                    await interaction.response.edit_message(
                        content=f"Sticker URL for `;;{shortcut_key}` is missing.", view=None
                    )
                    return
            else:
                # local file
                import os as _os
                if not _os.path.isfile(media_entry["file_path"]):
                    await interaction.response.edit_message(
                        content=f"File for `;;{shortcut_key}` is missing from disk.", view=None
                    )
                    return
                await self._target.reply(
                    content=attribution,
                    file=discord.File(media_entry["file_path"]),
                )
            await interaction.response.edit_message(content=f"Replied with `;;{shortcut_key}`!", view=None)
        except Exception as exc:
            err_text = getattr(exc, "text", None) or str(exc)
            await interaction.response.edit_message(content=f"Could not send: {err_text}", view=None)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


class MediaCog(commands.Cog):
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._added: list = []

    async def cog_load(self) -> None:
        menu = app_commands.ContextMenu(name="Save Emoji/Sticker", callback=self.save_emoji_sticker_context)
        self.ctx.bot.tree.add_command(menu)
        self._added.append(menu)
        menu = app_commands.ContextMenu(name="Reply with Emoji", callback=self.reply_with_emoji_context)
        self.ctx.bot.tree.add_command(menu)
        self._added.append(menu)
        menu = app_commands.ContextMenu(name="Reply with Sticker", callback=self.reply_with_sticker_context)
        self.ctx.bot.tree.add_command(menu)
        self._added.append(menu)

    async def cog_unload(self) -> None:
        for cmd in self._added:
            self.ctx.bot.tree.remove_command(cmd.name, type=cmd.type)

    @app_commands.command(name="my_media", description="List your saved local media shortcuts")
    async def my_media_slash(self, interaction: discord.Interaction) -> None:
        """Show the caller's saved ;;shortcut entries."""
        ctx = self.ctx
        if not ctx.settings.get("feature.local_media"):
            await interaction.response.send_message("Local media shortcuts are currently disabled.", ephemeral=True)
            return
        entries = list_user_local_media(ctx.db, interaction.user.id)
        if not entries:
            await interaction.response.send_message(
                "You have no saved media. Right-click a message → **Apps** → **Save Emoji/Sticker**.",
                ephemeral=True,
            )
            return

        max_per_user = ctx.settings.get("limit.media_per_user")
        lines = []
        for e in entries:
            st = e.get("storage_type", "local")
            preview = ""
            if st in ("app_emoji", "app_emoji_sticker"):
                did = e.get("discord_id")
                dname = e.get("discord_name") or e["shortcut"]
                animated = e.get("animated", False)
                if did:
                    preview = f"<{'a' if animated else ''}:{dname}:{did}> "
            type_label = e["media_type"].capitalize()
            lines.append(f"{preview}`;;{e['shortcut']}` — {type_label}")

        embed = discord.Embed(
            title="Your Saved Media",
            description="\n".join(lines),
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"{len(entries)}/{max_per_user} slots used")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    async def save_emoji_sticker_context(self, interaction: discord.Interaction, message: discord.Message) -> None:
        """Right-click → Apps → Save Emoji/Sticker.

        Auto-detects emoji or sticker from the message, downloads it, uploads it as
        a Discord Application Emoji, and saves it under an auto-generated shortcut
        name — no modal, no user input required. Users type ;;name in chat to replay.
        """
        ctx = self.ctx
        if not ctx.settings.get("feature.local_media"):
            await interaction.response.send_message("Local media shortcuts are currently disabled.", ephemeral=True)
            return

        # Defer immediately — download + upload can take a second
        await interaction.response.defer(ephemeral=True, thinking=True)

        # --- Detect: custom emoji in message content ---
        matches = _CUSTOM_EMOJI_RE.findall(message.content)
        if matches:
            if len(matches) > 1:
                await interaction.followup.send(
                    f"That message has **{len(matches)}** custom emojis — pick a message with exactly one.",
                    ephemeral=True,
                )
                return
            animated_flag, emoji_name, emoji_id = matches[0]
            ext = "gif" if animated_flag else "png"
            emoji_url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}?size=128"
            await _auto_save_media(
                interaction,
                storage_type="app_emoji",
                media_type="emoji",
                suggested_name=emoji_name,
                download_url=emoji_url,
                file_ext=ext,
            )
            return

        # --- Detect: sticker on the message ---
        if message.stickers:
            sticker = message.stickers[0]
            sticker_url = str(sticker.url)
            ext_part = sticker_url.rsplit(".", 1)[-1].split("?")[0].lower()
            if ext_part == "json":
                await interaction.followup.send(
                    "⚠️ That sticker uses an animated Lottie format which can’t be saved as a bot emoji. "
                    "Try a standard PNG or GIF sticker.",
                    ephemeral=True,
                )
                return
            await _auto_save_media(
                interaction,
                storage_type="app_emoji_sticker",
                media_type="sticker",
                suggested_name=sticker.name,
                download_url=sticker_url,
                file_ext="png",
            )
            return

        await interaction.followup.send(
            "No custom emoji or sticker found in that message.\n"
            "*Tip: The emoji must be a **custom** emoji (not a standard Unicode one).*",
            ephemeral=True,
        )
    async def reply_with_emoji_context(self, interaction: discord.Interaction, message: discord.Message) -> None:
        """Right-click → Apps → Reply with Emoji: pick a saved emoji shortcut and reply to this message with it."""
        ctx = self.ctx
        if not ctx.settings.get("feature.local_media"):
            await interaction.response.send_message("Local media shortcuts are currently disabled.", ephemeral=True)
            return
        entries = list_user_local_media(ctx.db, interaction.user.id, media_type="emoji")
        if not entries:
            await interaction.response.send_message(
                "You have no saved emojis. Right-click a message → **Apps** → **Save Emoji/Sticker** first.",
                ephemeral=True,
            )
            return

        view = LocalMediaPickerView(target_message=message, entries=entries)
        await interaction.response.send_message(
            "Which saved emoji should I reply with?", view=view, ephemeral=True
        )
    async def reply_with_sticker_context(self, interaction: discord.Interaction, message: discord.Message) -> None:
        """Right-click → Apps → Reply with Sticker: pick a saved sticker shortcut and reply to this message with it."""
        ctx = self.ctx
        if not ctx.settings.get("feature.local_media"):
            await interaction.response.send_message("Local media shortcuts are currently disabled.", ephemeral=True)
            return
        entries = list_user_local_media(ctx.db, interaction.user.id, media_type="sticker")
        if not entries:
            await interaction.response.send_message(
                "You have no saved stickers. Right-click a message → **Apps** → **Save Emoji/Sticker** first.",
                ephemeral=True,
            )
            return

        view = LocalMediaPickerView(target_message=message, entries=entries)
        await interaction.response.send_message(
            "Which saved sticker should I reply with?", view=view, ephemeral=True
        )


async def setup(bot) -> None:
    await bot.add_cog(MediaCog(bot.ctx))
