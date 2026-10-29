# navi/cogs/help.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from navi.context import AppContext
from navi.services.quota import DAILY_QUOTA


class HelpCog(commands.Cog):
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._added: list = []

    async def cog_load(self) -> None:
        pass

    async def cog_unload(self) -> None:
        for cmd in self._added:
            self.ctx.bot.tree.remove_command(cmd.name, type=cmd.type)

    @app_commands.command(name="help", description="Learn how to interact with Navi")
    async def help_slash(self, interaction: discord.Interaction) -> None:
        """Show the help menu — only lists features that are currently enabled."""
        ctx = self.ctx
        embed = discord.Embed(
            title="Navi — Help & Features",
            description="Fairy from Hyrule. Now stationed in Thirontharam. Speaks Manglish. Has seen things.",
            color=discord.Color.dark_purple(),
        )

        # ── Predictions ──────────────────────────────────────────────────────────
        if ctx.settings.feat("feature_navi"):
            embed.add_field(
                name="🔮 Predictions",
                value=(
                    "`/navi` — Get your daily cosmic prediction\n"
                    "`/navi user:@someone` — Get a prediction for someone else\n"
                    "`navi` *(in chat)* — Same as `/navi`\n"
                    "`@Navi <question>` — Ask anything: news, scores, how-tos"
                ),
                inline=False,
            )

        # ── Curses & Blessings ───────────────────────────────────────────────────
        if ctx.settings.feat("feature_curses"):
            embed.add_field(
                name="⚡ Curses & Blessings",
                value=(
                    "`navi @user` — Curse someone. Lands: **you gain pts, they lose pts**.\n"
                    "Backfire reverses it — they gain, you lose. Higher tier = higher risk:\n"
                    "Mild **10%** · Moderate **15%** · Severe **20%** backfire chance\n\n"
                    "`chunk @user` — Bless someone with Trivandrum slang.\n"
                    "Target earns points; you earn **15–25%** of that as karma.\n"
                    "**5% chance**: Universal Blessing fires — both of you get **+100 pts** 🌟\n\n"
                    "Both commands can also reply to a message or be used alone (self).\n"
                    "Protect yourself from curses via `/shop buy`."
                ),
                inline=False,
            )
            embed.add_field(
                name="🌀 Cosmic Actions (daily quota)",
                value=(
                    f"Curses, blessings, and gambling all share **{DAILY_QUOTA} cosmic actions/day**.\n"
                    "Resets at **midnight IST**. Buy **+10 extra actions** from the shop to go beyond.\n"
                    "Exceed the limit on curses → you get reverse-cursed. On blessings → the cosmos notices."
                ),
                inline=False,
            )

        # ── Boli Economy ─────────────────────────────────────────────────────────
        economy_lines = [
            "`/mypoints` — Your Rashi, Boli Points, level, and cosmic title",
            "`/rank` — Top 10 leaderboard",
            "`/leaderboard` — Most cursed, most blessed, and richest users",
            "`/gift @user amount` — Send Boli Points to someone (omit recipient = random active user)",
            "`/shop view` / `/shop buy` — Boli Marketplace (perks, protection, extra actions)",
        ]
        embed.add_field(name="🍮 Boli Economy", value="\n".join(economy_lines), inline=False)

        # ── Boli Stock Market ────────────────────────────────────────────────────
        embed.add_field(
            name="📈 Boli Stock Market",
            value=(
                "`/market view` — Browse all items with live prices\n"
                "`/market buy <item_id> <qty>` — Buy stocks (up to 10 at once)\n"
                "`/market sell <item_id> <qty>` — Sell from your holdings (FIFO)\n"
                "`/market holdings` — Your portfolio: purchase price, quantity, P&L, expiry\n"
                "`/market history <item_id>` — Price chart (updates **hourly**, history logged daily)\n"
                "Holdings expire in **7 days**. Profit earns XP. Prices vary by hour + day-of-week."
            ),
            inline=False,
        )

        # ── Gambling ─────────────────────────────────────────────────────────────
        if ctx.settings.feat("feature_gambling"):
            embed.add_field(
                name="🎰 Gambling *(uses cosmic actions)*",
                value=(
                    "`/flip heads|tails bet` — Coin flip, 1:1 payout\n"
                    "`/roll_dice bet` — Dice: over/under 1:1, exact 7 pays 4:1, specific sums up to 35:1\n"
                    "`/roulette bet` — 39-pocket wheel: color/odd/even 1:1, dozen 2:1, number 35:1\n"
                    "`/slots bet` — Slot machine: 2-match 3:1, 3-match 10:1, jackpot (7️⃣7️⃣7️⃣) 50:1\n"
                    "Max bet **50,000 Boli** · **30 combined game plays/day** · Resets midnight IST"
                ),
                inline=False,
            )

        # ── Gemini Mini-Games — DISABLED (Gemini outputting inappropriate language) ──
        # gemini_game_lines = []
        # if ctx.settings.feat("feature_navi_challenge"):
        #     gemini_game_lines.append(
        #         "`/navi_challenge` — Get 3 random Trivandrum keywords, write a 2-sentence cosmic prediction, "
        #         "get Gemini-judged score (0–100 Boli + XP). **90 seconds, 2 attempts/day.**"
        #     )
        # if ctx.settings.feat("feature_type_race"):
        #     gemini_game_lines.append(
        #         "`/type_race` — Gemini gives you an iconic **movie dialogue**; translate it into Malayalam script (0–100) "
        #         "or Trivandrum Manglish slang (max 50) within 60 seconds. Gemini scores strictly → Boli + XP. **2 attempts/day.**"
        #     )
        # if gemini_game_lines:
        #     embed.add_field(
        #         name="🧠 Navi Mini-Games *(Gemini-judged)*",
        #         value="\n".join(gemini_game_lines),
        #         inline=False,
        #     )

        # ── Boli Points (passive earning) ────────────────────────────────────────
        if ctx.settings.feat("feature_boli_points"):
            embed.add_field(
                name="🏆 Boli Points — Passive Earning",
                value=(
                    "Use Trivandrum slang naturally in chat for +5 pts per unique word:\n"
                    "*kidilam, shokam, pillacha, chumma, mone, kili poyi, vishayam, thirontharam, boli, paal payasam…*\n"
                    "+2 pts per `/navi` call · Levels: Tourist → Thampanoor Regular → Chalai Veteran → Cosmic Sage"
                ),
                inline=False,
            )

        # ── Media Shortcuts ───────────────────────────────────────────────────────
        if ctx.settings.feat("feature_local_media"):
            embed.add_field(
                name="🖼️ Media Shortcuts",
                value=(
                    "Right-click a message → **Apps** → **Save as Emoji** or **Save as Sticker**\n"
                    "Custom emojis are saved natively. Images are uploaded as **Application Emojis** (auto-managed, up to 2,000).\n"
                    "Saved stickers sent alone appear enlarged — just like a real sticker!\n"
                    "Type `;;name` in any channel to post the saved emoji/sticker.\n"
                    "Right-click → **Apps** → **Reply with Emoji / Reply with Sticker** to reply with one of your saves.\n"
                    "`/my_media` — List all your saved shortcuts (max 20 per user)."
                ),
                inline=False,
            )

        # ── Other Tools ───────────────────────────────────────────────────────────
        other_lines = [
            "`/summ` — Factual summary of recent chat (up to 100 messages)",
            "`/ping` — Check bot latency and your Boli balance",
        ]
        if ctx.settings.feat("feature_kanmanilla"):
            other_lines.append("`/kanmanilla @user` — Dramatic missing-person notice for an absent member")
        if ctx.settings.feat("feature_temp_vc"):
            other_lines.append("`/temp_vc name capacity` — Temp voice channel (self-destructs in 30 min or when empty)")
        embed.add_field(name="🛠️ Other", value="\n".join(other_lines), inline=False)

        # ── Passive Reactions ─────────────────────────────────────────────────────
        passive_lines: list[str] = []
        if ctx.settings.feat("feature_kochi_replies"):
            passive_lines.append("**Kochi slang** *(machane, machi, adipoli…)* → Condescending reply from a true Trivandrumite")
        if ctx.settings.feat("feature_curse_replies"):
            passive_lines.append("**Curse words in chat** → 25% chance of a cosmic doom prediction")
        if ctx.settings.feat("feature_vibe_check"):
            passive_lines.append("**Chat heats up** → Navi de-escalates automatically")
        if ctx.settings.feat("feature_link_summary"):
            passive_lines.append("**React 📰 on a link** → 3-bullet summary of the article")
        if ctx.settings.feat("feature_welcome"):
            passive_lines.append("**New member joins** → Welcome message after 1-minute delay")
        if ctx.settings.feat("feature_strikes"):
            passive_lines.append("**Severe language** → 3-strike system; strike 2 triggers jail role")
        if passive_lines:
            embed.add_field(name="👁️ Passive Reactions (automatic)", value="\n".join(passive_lines), inline=False)

        # ── Mod-only section — only shown to users with manage_messages ───────────
        member = interaction.user
        is_mod = isinstance(member, discord.Member) and member.guild_permissions.manage_messages
        if is_mod:
            mod_lines = []
            if ctx.settings.feat("feature_audit"):
                mod_lines.append("`/audit @user [channel]` — AI audit of a user's messages against server rules")
            if ctx.settings.feat("feature_mod_tldr"):
                mod_lines.append("`/mod_tldr` — TL;DR summary of the current thread")
            if ctx.settings.feat("feature_strikes"):
                mod_lines.append("`/strike @user reason` — Issue a manual strike")
            if mod_lines:
                embed.add_field(name="🛡️ Mod Commands", value="\n".join(mod_lines), inline=False)

        embed.set_footer(text=f"Powered by Gemini · {DAILY_QUOTA} cosmic actions/day · 30 gambling plays/day · Resets midnight IST")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(HelpCog(bot.ctx))
