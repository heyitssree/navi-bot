# navi/cogs/economy.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import asyncio
import logging
import math
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from navi.context import AppContext
from navi.db.repos.points import (
    get_bless_leaderboard,
    get_curse_leaderboard,
    get_level_from_points,
    points_for_level,
    record_gift,
)
from navi.db.repos.settings import get_config_str
from navi.db.repos.users import (
    count_leaderboard_entries,
    get_leaderboard,
    get_random_recent_user,
    get_user_profile,
    upsert_user,
)
from navi.services.levels import get_level_title
from navi.services.lucky_draw import run_lucky_draw
from navi.services.points import update_boli_points
from navi.services.templates import get_template

logger = logging.getLogger("navi.cogs.economy")


def _build_rank_embed(page: int, total_pages: int, leaders: list, offset: int) -> discord.Embed:
    """Build the leaderboard embed for a given page."""
    embed = discord.Embed(
        title="🍮 Boli Points Leaderboard",
        description=f"Page {page} of {total_pages}",
        color=discord.Color.gold(),
    )
    medals = ["🥇", "🥈", "🥉"]
    for i, entry in enumerate(leaders):
        global_rank = offset + i + 1
        if page == 1 and i < 3:
            medal = medals[i]
        else:
            medal = f"**{global_rank}.**"
        rashi_str = f" · {entry['rashi']}" if entry.get("rashi") else ""
        # Level is derived from XP; leaderboard query may include experience if present
        xp_val = entry.get("experience") or entry.get("boli_points", 0)
        level = get_level_from_points(xp_val)
        title = get_level_title(level)
        embed.add_field(
            name=f"{medal} {entry['username']}{rashi_str} · Lv.{level}",
            value=f"🍮 **{entry['boli_points']} Boli Points** · {entry['prediction_count']} readings · *{title}*",
            inline=False,
        )
    embed.set_footer(text="Use the buttons below to navigate · Earn points via /navi and Trivandrum slang")
    return embed


_GIFT_TEMPLATES: list[str] = [
    "✨ A cosmic breeze just blew **{amount} Boli** from {sender} into {recipient}'s pocket! Don't spend it all in one dimension.",
    "💖 {sender} just sprinkled **{amount} Boli** points onto {recipient}! Friendship level up!",
    "🚀 Delivery! {sender} fired a care package of **{amount} Boli** straight at {recipient}.",
    "🪄 Poof! {sender} magically transferred **{amount} Boli** to {recipient}. Use it wisely!",
    "🎁 {sender} slipped **{amount} Boli** under {recipient}'s pillow. The Boli fairy has arrived!",
]


class RankView(discord.ui.View):
    """Paginated leaderboard view with Previous / Next buttons."""

    _PAGE_SIZE = 10

    def __init__(self, page: int, total_pages: int) -> None:
        super().__init__(timeout=120)
        self.page = page
        self.total_pages = total_pages
        # Disable buttons that are not applicable
        self.prev_button.disabled = page <= 1
        self.next_button.disabled = page >= total_pages

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = max(1, self.page - 1)
        await self._update(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = min(self.total_pages, self.page + 1)
        await self._update(interaction)

    async def _update(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        offset = (self.page - 1) * self._PAGE_SIZE
        leaders = get_leaderboard(ctx.db, limit=self._PAGE_SIZE, offset=offset)
        embed = _build_rank_embed(self.page, self.total_pages, leaders, offset)
        self.prev_button.disabled = self.page <= 1
        self.next_button.disabled = self.page >= self.total_pages
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


class EconomyCog(commands.Cog):
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._added: list = []

    async def cog_load(self) -> None:
        pass

    async def cog_unload(self) -> None:
        for cmd in self._added:
            self.ctx.bot.tree.remove_command(cmd.name, type=cmd.type)

    @app_commands.command(name="rank", description="See the Boli Points leaderboard")
    @app_commands.describe(page="Page number (10 entries per page, default 1)")
    async def rank_slash(self, interaction: discord.Interaction, page: int = 1) -> None:
        ctx = self.ctx
        _PAGE_SIZE = 10
        total = count_leaderboard_entries(ctx.db)

        if total == 0:
            await interaction.response.send_message(
                "Nobody has Boli Points yet. Use **/navi** and start earning.", ephemeral=True
            )
            return

        total_pages = max(1, math.ceil(total / _PAGE_SIZE))
        page = max(1, min(page, total_pages))
        offset = (page - 1) * _PAGE_SIZE

        await interaction.response.defer(thinking=False)
        leaders = get_leaderboard(ctx.db, limit=_PAGE_SIZE, offset=offset)
        embed = _build_rank_embed(page, total_pages, leaders, offset)
        view = RankView(page=page, total_pages=total_pages)
        await interaction.followup.send(embed=embed, view=view)
    @app_commands.command(name="leaderboard", description="Fun stats leaderboard: most cursed, most blessed, and richest")
    async def leaderboard_slash(self, interaction: discord.Interaction) -> None:
        """Three-section embed: most cursed, most blessed, highest Boli net worth."""
        ctx = self.ctx
        await interaction.response.defer(thinking=False)

        curse_board = get_curse_leaderboard(ctx.db, limit=5)
        bless_board = get_bless_leaderboard(ctx.db, limit=5)
        rich_board = get_leaderboard(ctx.db, limit=5, offset=0)

        embed = discord.Embed(
            title="🌌 Cosmic Leaderboards",
            color=discord.Color.dark_purple(),
        )

        medals = ["🥇", "🥈", "🥉", "4.", "5."]

        def _fmt_board(entries: list[dict], count_key: str) -> str:
            if not entries:
                return "*No data yet.*"
            lines = []
            for i, e in enumerate(entries):
                medal = medals[i] if i < len(medals) else f"{i+1}."
                lines.append(f"{medal} **{e['username']}** — {e[count_key]}")
            return "\n".join(lines)

        curse_lines = _fmt_board(curse_board, "hits")
        bless_lines = _fmt_board(bless_board, "hits")
        rich_lines = "\n".join(
            f"{medals[i] if i < len(medals) else f'{i+1}.'} **{e['username']}** — 🍮 {e['boli_points']} pts"
            for i, e in enumerate(rich_board)
        ) if rich_board else "*No data yet.*"

        embed.add_field(name="💀 Most Cursed", value=curse_lines, inline=False)
        embed.add_field(name="✨ Most Blessed", value=bless_lines, inline=False)
        embed.add_field(name="💰 Highest Boli Net Worth", value=rich_lines, inline=False)
        embed.set_footer(text="Curse & bless counts update in real time · /rank for full points board")

        await interaction.followup.send(embed=embed)
    @app_commands.command(name="lucky_draw", description="Manually trigger the daily lucky draw (admin only)")
    @app_commands.default_permissions(administrator=True)
    async def lucky_draw_slash(self, interaction: discord.Interaction) -> None:
        """Admin-only manual trigger for the daily lucky draw.

        Checks for duplicate runs within the same IST day and announces the winner
        in the current channel.
        """
        ctx = self.ctx
        app_info = await ctx.bot.application_info()
        is_owner = (
            (bool(ctx.config.owner_id) and interaction.user.id == ctx.config.owner_id)
            or interaction.user.id == app_info.owner.id
        )
        is_admin = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator
        if not (is_owner or is_admin):
            await interaction.response.send_message("This command requires Administrator permission.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        _IST = timezone(timedelta(hours=5, minutes=30))
        today_str = datetime.now(_IST).strftime("%Y-%m-%d")
        last_run = get_config_str(ctx.db, "lucky_draw_last_date", "")
        if last_run == today_str:
            await interaction.followup.send(
                f"⚠️ Lucky draw already ran today ({today_str}). "
                "Use `/admin adjust_points` to manually award Boli if needed.",
                ephemeral=True,
            )
            return

        result = await run_lucky_draw(ctx, announce_channel=interaction.channel)
        await interaction.followup.send(f"✅ Lucky draw triggered: {result}", ephemeral=True)
        logger.info("Manual lucky draw triggered by %s: %s", interaction.user.display_name, result)
    @app_commands.command(name="mypoints", description="Check your own Boli Points and Rashi")
    async def mypoints_slash(self, interaction: discord.Interaction) -> None:
        ctx = self.ctx
        profile = get_user_profile(ctx.db, interaction.user.id)
        if not profile:
            await interaction.response.send_message(
                "No profile found. Use **/navi** first to get started.", ephemeral=True
            )
            return

        rashi = profile.get("rashi") or "Not yet assigned"
        pts = profile.get("total_boli_points", 0)
        xp = profile.get("experience", 0)
        count = profile.get("prediction_count", 0)
        level = get_level_from_points(xp)  # level derived from XP, never Boli
        title = get_level_title(level)

        if level < 100:
            next_lvl_pts = points_for_level(level + 1)
            curr_lvl_pts = points_for_level(level)
            progress = xp - curr_lvl_pts
            needed = next_lvl_pts - curr_lvl_pts
            filled = int((progress / needed) * 10) if needed > 0 else 10
            bar = "█" * filled + "░" * (10 - filled)
            progress_line = f"📈 `[{bar}]` {progress}/{needed} XP → Level {level + 1}"
        else:
            progress_line = "🌟 Maximum level reached!"

        stats_intro = get_template("stats", pts)
        profile_text = (
            f"**Your Profile**\n"
            f"🌟 Rashi: **{rashi}**\n"
            f"⚔️ Level: **{level}** — *{title}* *(based on XP, never decreases)*\n"
            f"{progress_line}\n"
            f"✨ Total XP: **{xp}**\n"
            f"🍮 Boli Points: **{pts}** *(spendable balance)*\n"
            f"🔮 Predictions received: **{count}**"
        )
        full_reply = f"{stats_intro}\n\n{profile_text}" if stats_intro else profile_text
        await interaction.response.send_message(full_reply, ephemeral=True)
    @app_commands.command(name="gift", description="Gift Boli points to another user. Omit recipient to surprise a random recent user!")
    @app_commands.describe(
        recipient="Who to gift points to (optional — omit for a random active user)",
        amount="How many Boli points to send",
    )
    async def gift_slash(self, interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 10000],
        recipient: discord.Member | None = None,
    ) -> None:
        ctx = self.ctx
        sender_id = interaction.user.id

        # Resolve recipient
        actual_recipient: discord.Member | None = recipient
        random_pick: dict | None = None
        if actual_recipient is None:
            random_pick = await asyncio.get_running_loop().run_in_executor(
                None, lambda: get_random_recent_user(ctx.db, sender_id)
            )
            if not random_pick:
                await interaction.response.send_message(
                    "No one has used /navi in the last 24 hours — no one to surprise gift!",
                    ephemeral=True,
                )
                return
            # Resolve the Discord Member object — try cache first, then API fetch
            guild = interaction.guild
            if guild:
                actual_recipient = guild.get_member(random_pick["user_id"])
                if actual_recipient is None:
                    try:
                        actual_recipient = await guild.fetch_member(random_pick["user_id"])
                    except (discord.NotFound, discord.HTTPException):
                        actual_recipient = None
            if actual_recipient is None:
                await interaction.response.send_message(
                    "Couldn't resolve the random user — they may have left the server. Try again or tag someone directly.",
                    ephemeral=True,
                )
                return

        if actual_recipient.id == sender_id:
            await interaction.response.send_message("You can't gift points to yourself.", ephemeral=True)
            return
        if actual_recipient.bot:
            await interaction.response.send_message("Bots don't need Boli points.", ephemeral=True)
            return

        profile = get_user_profile(ctx.db, sender_id)
        if not profile:
            await interaction.response.send_message(
                "No profile found. Use /navi first to get started.", ephemeral=True
            )
            return

        actual_amount = amount
        sender_pts = profile["boli_points"]
        if sender_pts < actual_amount:
            await interaction.response.send_message(
                f"Not enough Boli. You have 🍮 **{sender_pts}** but tried to gift **{actual_amount}**.",
                ephemeral=True,
            )
            return

        # Execute transfer (gifts do NOT award XP — anti-farming)
        update_boli_points(ctx.db, sender_id, -actual_amount)
        upsert_user(ctx.db, actual_recipient.id, actual_recipient.display_name)
        update_boli_points(ctx.db, actual_recipient.id, actual_amount)
        record_gift(ctx.db, sender_id, actual_recipient.id, actual_amount)

        surprise_note = " *(random pick — they used /navi recently!)*" if random_pick else ""
        msg = random.choice(_GIFT_TEMPLATES).format(
            sender=interaction.user.mention,
            recipient=actual_recipient.mention,
            amount=actual_amount,
        ) + surprise_note
        await interaction.response.send_message(msg)
        logger.info(
            "%s gifted %d Boli to %s%s",
            interaction.user.display_name, actual_amount, actual_recipient.display_name,
            " (random)" if random_pick else "",
        )


async def setup(bot) -> None:
    await bot.add_cog(EconomyCog(bot.ctx))
