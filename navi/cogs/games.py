# navi/cogs/games.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import asyncio
import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

from navi.context import AppContext
from navi.db.repos.counters import _GAME_DAILY_LIMIT, get_total_game_daily_count, increment_game_daily_count
from navi.db.repos.users import get_user_profile
from navi.services.points import update_boli_points
from navi.services.quota import OVER_QUOTA_GAME_MESSAGES

logger = logging.getLogger("navi.cogs.games")


_ROULETTE_RED: frozenset[int] = frozenset({1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36})


# Dice exact-number payout multipliers (total return including stake)
# Probability: 1/36 for 2&12, 2/36 for 3&11, 3/36 for 4&10, 4/36 for 5&9, 5/36 for 6&8
_DICE_EXACT_PAYOUT: dict[int, int] = {
    2: 36, 3: 18, 4: 12, 5: 9, 6: 7,
    8: 7, 9: 9, 10: 12, 11: 18, 12: 36,
}


def _gambling_guard(
    profile: dict | None,
    bet: int,
) -> str | None:
    """Return an error string if the bet is invalid, else None."""
    if profile is None:
        return "No profile found. Use /navi first to get started."
    if bet < 1:
        return "Bet must be at least 1 Boli."
    if profile["boli_points"] < bet:
        return f"Not enough Boli. You have 🍮 **{profile['boli_points']}** but bet **{bet}**."
    return None


_ROULETTE_DOZENS: dict[str, tuple[int, int]] = {
    "dozen1": (1, 12), "dozen2": (13, 24), "dozen3": (25, 36)
}


_ROULETTE_STANDARD_CHOICES: list[app_commands.Choice[str]] = [
    app_commands.Choice(name="Red (1:1)", value="red"),
    app_commands.Choice(name="Black (1:1)", value="black"),
    app_commands.Choice(name="Odd (1:1)", value="odd"),
    app_commands.Choice(name="Even (1:1)", value="even"),
    app_commands.Choice(name="Dozen 1 — 1 to 12 (2:1)", value="dozen1"),
    app_commands.Choice(name="Dozen 2 — 13 to 24 (2:1)", value="dozen2"),
    app_commands.Choice(name="Dozen 3 — 25 to 36 (2:1)", value="dozen3"),
]


async def _roulette_choice_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    if current and current.isdigit():
        number_choices = [
            app_commands.Choice(name=f"Number {i} (35:1)", value=str(i))
            for i in range(1, 37)
            if str(i).startswith(current)
        ]
        return (number_choices + _ROULETTE_STANDARD_CHOICES)[:25]
    elif current:
        filtered = [c for c in _ROULETTE_STANDARD_CHOICES if current.lower() in c.name.lower()]
        return filtered or _ROULETTE_STANDARD_CHOICES
    return _ROULETTE_STANDARD_CHOICES


_SLOTS_SYMBOLS: list[str] = ["🍎", "🍒", "🍋", "🔔", "⭐", "💎", "7️⃣"]


_SLOTS_WEIGHTS: list[int]  = [ 30,   25,   20,   15,   7,    5,    3  ]


class GamesCog(commands.Cog):
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._added: list = []

    async def cog_load(self) -> None:
        pass

    async def cog_unload(self) -> None:
        for cmd in self._added:
            self.ctx.bot.tree.remove_command(cmd.name, type=cmd.type)

    @app_commands.command(name="flip", description="Coin flip — bet Boli on heads or tails (1:1 payout)")
    @app_commands.describe(choice="heads or tails", bet="How many Boli to wager")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Heads", value="heads"),
        app_commands.Choice(name="Tails", value="tails"),
    ])
    async def flip_slash(self, interaction: discord.Interaction,
        choice: str,
        bet: app_commands.Range[int, 1, 50000],
    ) -> None:
        ctx = self.ctx
        if not ctx.settings.feat("feature_gambling"):
            await interaction.response.send_message("Gambling is currently disabled.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        loop = asyncio.get_running_loop()
        profile, total_count = await loop.run_in_executor(
            None,
            lambda: (get_user_profile(ctx.db, interaction.user.id),
                     get_total_game_daily_count(ctx.db, interaction.user.id)),
        )
        err = _gambling_guard(profile, bet)
        if err:
            await interaction.followup.send(err, ephemeral=True)
            return

        if total_count >= _GAME_DAILY_LIMIT:
            msg = random.choice(OVER_QUOTA_GAME_MESSAGES).format(user=interaction.user.display_name, game="Coin Flip")
            await interaction.followup.send(msg, ephemeral=True)
            return

        await loop.run_in_executor(None, lambda: increment_game_daily_count(ctx.db, interaction.user.id, "flip"))
        update_boli_points(ctx.db, interaction.user.id, -bet)
        await asyncio.sleep(1.5)

        result = random.choice(["heads", "tails"])
        coin_emoji = "🪙"
        if result == choice:
            update_boli_points(ctx.db, interaction.user.id, bet * 2)
            outcome = f"✅ **{result.capitalize()}!** You win **{bet} Boli**! {coin_emoji}"
        else:
            outcome = f"❌ **{result.capitalize()}.** You lose **{bet} Boli**. {coin_emoji}"

        embed = discord.Embed(
            title=f"{coin_emoji} Cosmic Coin Flip",
            description=f"{interaction.user.mention} bet **{bet} Boli** on **{choice}**.\n\n{outcome}",
            color=discord.Color.green() if result == choice else discord.Color.red(),
        )
        new_pts = (profile["boli_points"] - bet) + (bet * 2 if result == choice else 0)
        embed.set_footer(text=f"Balance: 🍮 {new_pts} Boli")
        await interaction.followup.send(embed=embed)
        logger.info(
            "%s flipped %s on %s, result=%s → %s",
            interaction.user.display_name, bet, choice, result, "win" if result == choice else "lose",
        )
    @app_commands.command(name="roll_dice", description="Roll two dice — bet on over/under/exact 7, or call a specific sum")
    @app_commands.describe(bet_type="Your prediction", bet="How many Boli to wager")
    @app_commands.choices(bet_type=[
        app_commands.Choice(name="Over 7 (1:1 payout)", value="over7"),
        app_commands.Choice(name="Under 7 (1:1 payout)", value="under7"),
        app_commands.Choice(name="Exact 7 (4:1 payout)", value="exact7"),
        app_commands.Choice(name="Exact 2 — 35:1 payout", value="2"),
        app_commands.Choice(name="Exact 3 — 17:1 payout", value="3"),
        app_commands.Choice(name="Exact 4 — 11:1 payout", value="4"),
        app_commands.Choice(name="Exact 5 — 8:1 payout", value="5"),
        app_commands.Choice(name="Exact 6 — 6:1 payout", value="6"),
        app_commands.Choice(name="Exact 8 — 6:1 payout", value="8"),
        app_commands.Choice(name="Exact 9 — 8:1 payout", value="9"),
        app_commands.Choice(name="Exact 10 — 11:1 payout", value="10"),
        app_commands.Choice(name="Exact 11 — 17:1 payout", value="11"),
        app_commands.Choice(name="Exact 12 — 35:1 payout", value="12"),
    ])
    async def roll_dice_slash(self, interaction: discord.Interaction,
        bet_type: str,
        bet: app_commands.Range[int, 1, 50000],
    ) -> None:
        ctx = self.ctx
        if not ctx.settings.feat("feature_gambling"):
            await interaction.response.send_message("Gambling is currently disabled.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        loop = asyncio.get_running_loop()
        profile, total_count = await loop.run_in_executor(
            None,
            lambda: (get_user_profile(ctx.db, interaction.user.id),
                     get_total_game_daily_count(ctx.db, interaction.user.id)),
        )
        err = _gambling_guard(profile, bet)
        if err:
            await interaction.followup.send(err, ephemeral=True)
            return

        if total_count >= _GAME_DAILY_LIMIT:
            msg = random.choice(OVER_QUOTA_GAME_MESSAGES).format(user=interaction.user.display_name, game="Dice")
            await interaction.followup.send(msg, ephemeral=True)
            return

        await loop.run_in_executor(None, lambda: increment_game_daily_count(ctx.db, interaction.user.id, "roll_dice"))
        update_boli_points(ctx.db, interaction.user.id, -bet)
        await asyncio.sleep(1.5)

        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        total = d1 + d2

        if bet_type == "over7":
            won = total > 7
            payout_mult = 2
            bet_label = "Over 7"
        elif bet_type == "under7":
            won = total < 7
            payout_mult = 2
            bet_label = "Under 7"
        elif bet_type == "exact7":
            won = total == 7
            payout_mult = 5
            bet_label = "Exact 7"
        else:
            target = int(bet_type)
            won = total == target
            payout_mult = _DICE_EXACT_PAYOUT[target]
            bet_label = f"Exact {target}"

        winnings = bet * payout_mult if won else 0
        if won:
            update_boli_points(ctx.db, interaction.user.id, winnings)

        dice_display = f"🎲 **{d1}** + **{d2}** = **{total}**"
        outcome_str = f"✅ **Win!** +**{winnings - bet} Boli**" if won else f"❌ **Loss.** -{bet} Boli"
        embed = discord.Embed(
            title="🎲 Cosmic Dice",
            description=(
                f"{interaction.user.mention} bet **{bet} Boli** on **{bet_label}**.\n\n"
                f"{dice_display}\n\n{outcome_str}"
            ),
            color=discord.Color.green() if won else discord.Color.red(),
        )
        new_pts = (profile["boli_points"] - bet) + winnings
        embed.set_footer(text=f"Balance: 🍮 {new_pts} Boli")
        await interaction.followup.send(embed=embed)
        logger.info(
            "%s rolled dice (%d+%d=%d) on %s, bet=%d → %s",
            interaction.user.display_name, d1, d2, total, bet_type, bet, "win" if won else "lose",
        )
    @app_commands.command(name="roulette", description="Space roulette — color (1:1), dozen (2:1), odd/even (1:1), or number 1-36 (35:1)")
    @app_commands.describe(
        choice="Pick a bet type or type a number 1-36",
        bet="How many Boli to wager",
    )
    @app_commands.autocomplete(choice=_roulette_choice_autocomplete)
    async def roulette_slash(self, interaction: discord.Interaction,
        choice: str,
        bet: app_commands.Range[int, 1, 50000],
    ) -> None:
        ctx = self.ctx
        if not ctx.settings.feat("feature_gambling"):
            await interaction.response.send_message("Gambling is currently disabled.", ephemeral=True)
            return
        choice = choice.strip().lower()
        valid_colors = {"red", "black"}
        valid_evenodd = {"odd", "even"}
        is_color = choice in valid_colors
        is_evenodd = choice in valid_evenodd
        is_dozen = choice in _ROULETTE_DOZENS
        is_number = choice.isdigit() and 1 <= int(choice) <= 36
        if not (is_color or is_evenodd or is_dozen or is_number):
            await interaction.response.send_message(
                "Invalid choice. Use `red`/`black`, `odd`/`even`, `dozen1`/`dozen2`/`dozen3`, or a number `1`–`36`.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        loop = asyncio.get_running_loop()
        profile, total_count = await loop.run_in_executor(
            None,
            lambda: (get_user_profile(ctx.db, interaction.user.id),
                     get_total_game_daily_count(ctx.db, interaction.user.id)),
        )
        err = _gambling_guard(profile, bet)
        if err:
            await interaction.followup.send(err, ephemeral=True)
            return

        if total_count >= _GAME_DAILY_LIMIT:
            msg = random.choice(OVER_QUOTA_GAME_MESSAGES).format(user=interaction.user.display_name, game="Roulette")
            await interaction.followup.send(msg, ephemeral=True)
            return

        await loop.run_in_executor(None, lambda: increment_game_daily_count(ctx.db, interaction.user.id, "roulette"))
        update_boli_points(ctx.db, interaction.user.id, -bet)

        await interaction.followup.send(
            f"🌀 The cosmic wheel is spinning for {interaction.user.mention}…", silent=True
        )
        await asyncio.sleep(2)

        # 39-pocket wheel: 1-36 playable + 0/37/38 green → ~7.7% house edge on all bet types
        landed = random.randint(0, 38)
        _green_pockets = {0, 37, 38}

        if landed in _green_pockets:
            landed_color = "green"
            color_emoji = "🟢"
        else:
            landed_color = "red" if landed in _ROULETTE_RED else "black"
            color_emoji = "🔴" if landed_color == "red" else "⚫"

        if is_color:
            won = landed not in _green_pockets and landed_color == choice
            payout_mult = 2
        elif is_evenodd:
            won = landed not in _green_pockets and (
                landed % 2 == 0 if choice == "even" else landed % 2 == 1
            )
            payout_mult = 2
        elif is_dozen:
            lo, hi = _ROULETTE_DOZENS[choice]
            won = landed not in _green_pockets and lo <= landed <= hi
            payout_mult = 3
        else:
            won = landed == int(choice)
            payout_mult = 36

        winnings = bet * payout_mult if won else 0
        if won:
            update_boli_points(ctx.db, interaction.user.id, winnings)

        outcome_str = f"✅ **Win!** +**{winnings - bet} Boli**" if won else f"❌ **Loss.** -{bet} Boli"
        landed_display = f"{landed} (green)" if landed in _green_pockets else f"{landed} ({landed_color})"
        embed = discord.Embed(
            title="🌀 Space Roulette",
            description=(
                f"{interaction.user.mention} bet **{bet} Boli** on **{choice}**.\n\n"
                f"The wheel landed on: {color_emoji} **{landed_display}**\n\n{outcome_str}"
            ),
            color=discord.Color.green() if won else discord.Color.red(),
        )
        new_pts = (profile["boli_points"] - bet) + winnings
        embed.set_footer(text=f"Balance: 🍮 {new_pts} Boli")
        await interaction.followup.send(embed=embed)
        logger.info(
            "%s roulette: bet %d on '%s', landed %d (%s) → %s",
            interaction.user.display_name, bet, choice, landed, landed_color, "win" if won else "lose",
        )
    @app_commands.command(name="slots", description="Spin the cosmic slot machine — first 2 match 2:1, 3-match 10:1, jackpot 50:1")
    @app_commands.describe(bet="How many Boli to wager")
    async def slots_slash(self, interaction: discord.Interaction,
        bet: app_commands.Range[int, 1, 50000],
    ) -> None:
        ctx = self.ctx
        if not ctx.settings.feat("feature_gambling"):
            await interaction.response.send_message("Gambling is currently disabled.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        loop = asyncio.get_running_loop()
        profile, total_count = await loop.run_in_executor(
            None,
            lambda: (get_user_profile(ctx.db, interaction.user.id),
                     get_total_game_daily_count(ctx.db, interaction.user.id)),
        )
        err = _gambling_guard(profile, bet)
        if err:
            await interaction.followup.send(err, ephemeral=True)
            return

        if total_count >= _GAME_DAILY_LIMIT:
            msg = random.choice(OVER_QUOTA_GAME_MESSAGES).format(user=interaction.user.display_name, game="Slots")
            await interaction.followup.send(msg, ephemeral=True)
            return

        await loop.run_in_executor(None, lambda: increment_game_daily_count(ctx.db, interaction.user.id, "slots"))
        update_boli_points(ctx.db, interaction.user.id, -bet)
        await asyncio.sleep(1.5)

        reels = random.choices(_SLOTS_SYMBOLS, weights=_SLOTS_WEIGHTS, k=3)
        r1, r2, r3 = reels
        reel_display = f"[ {r1} | {r2} | {r3} ]"

        jackpot = r1 == r2 == r3 == "7️⃣"
        three_match = r1 == r2 == r3
        two_match = r1 == r2

        if jackpot:
            payout_mult = 51  # 50:1 → 51x return
            outcome_str = f"🎰 **JACKPOT!!!** +**{bet * payout_mult - bet} Boli**"
        elif three_match:
            payout_mult = 11  # 10:1 → 11x return
            outcome_str = f"✅ **Three of a kind!** +**{bet * payout_mult - bet} Boli**"
        elif two_match:
            payout_mult = 3   # 2:1 → 3x return
            outcome_str = f"✅ **Two of a kind (first two)!** +**{bet * payout_mult - bet} Boli**"
        else:
            payout_mult = 0
            outcome_str = f"❌ **No match.** -{bet} Boli"

        winnings = bet * payout_mult
        if winnings:
            update_boli_points(ctx.db, interaction.user.id, winnings)

        embed = discord.Embed(
            title="🎰 Cosmic Slots",
            description=(
                f"{interaction.user.mention} bet **{bet} Boli**.\n\n"
                f"## {reel_display}\n\n{outcome_str}"
            ),
            color=discord.Color.gold() if jackpot else (discord.Color.green() if payout_mult else discord.Color.red()),
        )
        new_pts = (profile["boli_points"] - bet) + winnings
        embed.set_footer(text=f"Balance: 🍮 {new_pts} Boli")
        await interaction.followup.send(embed=embed)
        logger.info(
            "%s slots: bet=%d reels=[%s|%s|%s] → %s",
            interaction.user.display_name, bet, r1, r2, r3,
            "jackpot" if jackpot else ("3match" if three_match else ("2match" if two_match else "lose")),
        )


async def setup(bot) -> None:
    await bot.add_cog(GamesCog(bot.ctx))
