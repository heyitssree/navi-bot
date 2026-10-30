# navi/cogs/shop.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import logging
import random
from datetime import timezone

import discord
from discord import app_commands
from discord.ext import commands

from navi.context import AppContext
from navi.db.repos.counters import (
    add_extra_actions,
    get_daily_refill_count,
    get_extra_actions,
    increment_daily_refill_count,
)
from navi.db.repos.perks import get_perk_expiry, grant_perk
from navi.db.repos.users import get_user_profile, upsert_user
from navi.services.features import deny_if_disabled
from navi.services.points import award
from navi.services.quota import HAS_EXTRAS_MESSAGES

logger = logging.getLogger("navi.cogs.shop")


_SHOP_ITEMS: dict[str, dict] = {
    "curse_protection": {
        "name": "Curse Protection",
        "cost": 20,
        "description": "100% reversal of proxy curses for 24 hours. Anyone who tries `navi @you` gets it back.",
        "emoji": "🛡️",
        "duration_hours": 24,
    },
    "custom_rashi": {
        "name": "Customize Rashi",
        "cost": 40,
        "description": "Pick your own Rashi from the cosmic menu. Your destiny, your choice. For now.",
        "emoji": "🌟",
        "duration_hours": 0,  # permanent until next purchase
    },
    "action_refill": {
        "name": "10x Cosmic Actions Refill",
        "cost": 30,
        "description": "Instantly adds 10 extra curses/blessings to your quota. Use them wisely.",
        "emoji": "🔋",
        "duration_hours": 0,
    },
    "deflector_shield": {
        "name": "Deflector Shield",
        "cost": 15,
        "description": "For 30 minutes after activation, any curse aimed at you is automatically reversed back to the caster.",
        "emoji": "🔮",
        "duration_hours": 0.5,
    },
    "timeout_ticket": {
        "name": "Timeout Ticket",
        "cost": 25,
        "description": "Block a target user from casting curses for 30 minutes. They lose 3 Boli per attempt. Requires a target.",
        "emoji": "🚫",
        "duration_hours": 0.5,
        "requires_target": True,
    },
    "multiplier_potion": {
        "name": "Multiplier Potion",
        "cost": 35,
        "description": "For 15 minutes, every curse you cast fires twice. The 2nd curse (15–45s later) mirrors the fate of the 1st.",
        "emoji": "⚡",
        "duration_hours": 0.25,
    },
}


class ShopGroup(app_commands.Group):
    """Boli Marketplace — spend your hard-earned points on cosmic perks."""

    def __init__(self):
        super().__init__(name="shop", description="Boli Marketplace — spend Boli Points on cosmic perks")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return not await deny_if_disabled(interaction, "feature.shop")

    @app_commands.command(name="view", description="Browse available items in the Boli Marketplace")
    async def view(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        profile = get_user_profile(ctx.db, interaction.user.id)
        pts = profile["boli_points"] if profile else 0

        embed = discord.Embed(
            title="🏪 Boli Marketplace",
            description=f"Your balance: 🍮 **{pts} Boli Points**\nUse `/shop buy <item>` to purchase.",
            color=discord.Color.dark_gold(),
        )
        _perk_map = {
            "curse_protection": "curse_protection",
            "deflector_shield": "deflector_shield",
            "multiplier_potion": "multiplier_potion",
        }
        for item_id, item in _SHOP_ITEMS.items():
            active_note = ""
            perk_key = _perk_map.get(item_id)
            if perk_key:
                expiry = get_perk_expiry(ctx.db, interaction.user.id, perk_key)
                if expiry:
                    expiry_utc = expiry.replace(tzinfo=timezone.utc)
                    active_note = f"\n*(Active until <t:{int(expiry_utc.timestamp())}:t>)*"

            # Dynamic pricing for action_refill
            if item_id == "action_refill":
                refill_count = get_daily_refill_count(ctx.db, interaction.user.id)
                extra_remaining = get_extra_actions(ctx.db, interaction.user.id)
                if refill_count >= 2:
                    cost_label = "🍮 SOLD OUT (2/2 today)"
                    can_afford = "❌"
                elif extra_remaining > 0:
                    cost_label = f"🍮 Spend your {extra_remaining} remaining first"
                    can_afford = "🔒"
                else:
                    dynamic_cost = 30 if refill_count == 0 else 50
                    can_afford = "✅" if pts >= dynamic_cost else "❌"
                    cost_label = f"🍮 {dynamic_cost} pts {can_afford}"
                embed.add_field(
                    name=f"{item['emoji']} {item['name']} — {cost_label}",
                    value=f"{item['description']} *(1st buy: 30 pts • 2nd buy: 50 pts • max 2/day)*{active_note}",
                    inline=False,
                )
            else:
                can_afford = "✅" if pts >= item["cost"] else "❌"
                embed.add_field(
                    name=f"{item['emoji']} {item['name']} — 🍮 {item['cost']} pts {can_afford}",
                    value=f"{item['description']}{active_note}",
                    inline=False,
                )

        embed.set_footer(text="Earn Boli Points by using /navi and Trivandrum slang.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="buy", description="Purchase an item from the Boli Marketplace")
    @app_commands.describe(
        item="Which item to buy",
        rashi_choice="Your chosen Rashi (only for custom_rashi)",
        target="Target user (only for timeout_ticket)",
    )
    @app_commands.choices(item=[
        app_commands.Choice(name="🛡️ Curse Protection (20 pts)", value="curse_protection"),
        app_commands.Choice(name="🌟 Customize Rashi (40 pts)", value="custom_rashi"),
        app_commands.Choice(name="🔋 10x Cosmic Actions Refill (30 pts)", value="action_refill"),
        app_commands.Choice(name="🔮 Deflector Shield (15 pts)", value="deflector_shield"),
        app_commands.Choice(name="🚫 Timeout Ticket (25 pts)", value="timeout_ticket"),
        app_commands.Choice(name="⚡ Multiplier Potion (35 pts)", value="multiplier_potion"),
    ])
    async def buy(
        self,
        interaction: discord.Interaction,
        item: str,
        rashi_choice: str | None = None,
        target: discord.Member | None = None,
    ) -> None:
        ctx = interaction.client.ctx
        if item not in _SHOP_ITEMS:
            await interaction.response.send_message("That item doesn't exist.", ephemeral=True)
            return

        shop_item = _SHOP_ITEMS[item]
        profile = get_user_profile(ctx.db, interaction.user.id)
        if not profile:
            await interaction.response.send_message(
                "No profile found. Use /navi first to get started.", ephemeral=True
            )
            return

        pts = profile["boli_points"]
        cost = shop_item["cost"]

        if pts < cost:
            await interaction.response.send_message(
                f"Not enough Boli Points. You have 🍮 **{pts}** but need **{cost}**.",
                ephemeral=True,
            )
            return

        # --- Curse Protection ---
        if item == "curse_protection":
            award(ctx.db, interaction.user.id, -cost, reason="shop", detail=item)
            grant_perk(ctx.db, interaction.user.id, "curse_protection", duration_hours=24)
            expiry = get_perk_expiry(ctx.db, interaction.user.id, "curse_protection")
            expiry_utc = expiry.replace(tzinfo=timezone.utc) if expiry else None
            ts = f"<t:{int(expiry_utc.timestamp())}:f>" if expiry_utc else "24 hours"
            await interaction.response.send_message(
                f"🛡️ **Curse Protection activated!** {interaction.user.mention}, you're protected until {ts}. "
                f"Any proxy curse attempt will be reversed back at the sender.\n"
                f"🍮 -{cost} Boli Points (remaining: **{pts - cost}**)",
                ephemeral=True,
            )
            logger.info("%s purchased Curse Protection", interaction.user.display_name)

        # --- Custom Rashi ---
        elif item == "custom_rashi":
            from glossary import RASHIS
            if not rashi_choice:
                rashi_list = "\n".join(f"• `{r}`" for r in RASHIS)
                await interaction.response.send_message(
                    f"🌟 **Pick your Rashi!** Use `/shop buy item:custom_rashi rashi_choice:<name>`\n\n"
                    f"Available Rashis:\n{rashi_list}",
                    ephemeral=True,
                )
                return

            # Validate choice
            matched = next((r for r in RASHIS if r.lower() == rashi_choice.strip().lower()), None)
            if not matched:
                rashi_list = ", ".join(RASHIS)
                await interaction.response.send_message(
                    f"`{rashi_choice}` is not a valid Rashi. Pick from: {rashi_list}",
                    ephemeral=True,
                )
                return

            award(ctx.db, interaction.user.id, -cost, reason="shop", detail=item)
            upsert_user(ctx.db, interaction.user.id, interaction.user.display_name, rashi=matched)
            await interaction.response.send_message(
                f"🌟 **Rashi updated!** {interaction.user.mention}, your sign is now **{matched}**.\n"
                f"🍮 -{cost} Boli Points (remaining: **{pts - cost}**)",
                ephemeral=True,
            )
            logger.info("%s purchased Custom Rashi: %s", interaction.user.display_name, matched)

        # --- Action Refill (tiered pricing: 30 Boli 1st buy, 50 Boli 2nd buy, blocked 3rd+) ---
        elif item == "action_refill":
            refill_count = get_daily_refill_count(ctx.db, interaction.user.id)

            # Max 2 refills per day
            if refill_count >= 2:
                await interaction.response.send_message(
                    "🚫 You've already bought the maximum extra actions for today (2 refills). "
                    "Come back after midnight IST.",
                    ephemeral=True,
                )
                return

            # Must spend existing purchased extras before buying more
            extra_remaining = get_extra_actions(ctx.db, interaction.user.id)
            if extra_remaining > 0:
                msg = random.choice(HAS_EXTRAS_MESSAGES).format(
                    invoker=interaction.user.display_name, extra=extra_remaining
                )
                await interaction.response.send_message(msg, ephemeral=True)
                return

            # Dynamic cost: 30 for 1st purchase, 50 for 2nd
            cost = 30 if refill_count == 0 else 50

            if pts < cost:
                await interaction.response.send_message(
                    f"Not enough Boli Points. You have 🍮 **{pts}** but need **{cost}** for this refill.",
                    ephemeral=True,
                )
                return

            award(ctx.db, interaction.user.id, -cost, reason="shop", detail=item)
            add_extra_actions(ctx.db, interaction.user.id, 10)
            increment_daily_refill_count(ctx.db, interaction.user.id)
            next_cost = 50 if refill_count == 0 else "N/A (max reached)"
            await interaction.response.send_message(
                f"🔋 Refill successful! {interaction.user.mention}, **+10 cosmic actions** added to your quota.\n"
                f"🍮 -{cost} Boli Points (remaining: **{pts - cost}**)\n"
                f"*(Next refill today costs: {next_cost} Boli • Spend these before buying again)*",
                ephemeral=True,
            )
            logger.info(
                "%s purchased Action Refill #%d (+10 extra actions, cost=%d)",
                interaction.user.display_name, refill_count + 1, cost,
            )

        # --- Deflector Shield ---
        elif item == "deflector_shield":
            award(ctx.db, interaction.user.id, -cost, reason="shop", detail=item)
            grant_perk(ctx.db, interaction.user.id, "deflector_shield", duration_hours=0.5)
            expiry = get_perk_expiry(ctx.db, interaction.user.id, "deflector_shield")
            expiry_utc = expiry.replace(tzinfo=timezone.utc) if expiry else None
            ts = f"<t:{int(expiry_utc.timestamp())}:f>" if expiry_utc else "30 minutes"
            await interaction.response.send_message(
                f"🔮 **Deflector Shield active!** {interaction.user.mention}, curses will bounce back to their caster until {ts}.\n"
                f"🍮 -{cost} Boli Points (remaining: **{pts - cost}**)",
                ephemeral=True,
            )
            logger.info("%s purchased Deflector Shield", interaction.user.display_name)

        # --- Timeout Ticket ---
        elif item == "timeout_ticket":
            if target is None:
                await interaction.response.send_message(
                    "🚫 **Timeout Ticket** requires a target. Use `/shop buy item:timeout_ticket target:@user`.",
                    ephemeral=True,
                )
                return
            if target.bot:
                await interaction.response.send_message("You can't timeout a bot.", ephemeral=True)
                return
            if target.id == interaction.user.id:
                await interaction.response.send_message("You can't timeout yourself.", ephemeral=True)
                return
            award(ctx.db, interaction.user.id, -cost, reason="shop", detail=item)
            upsert_user(ctx.db, target.id, target.display_name)
            grant_perk(ctx.db, target.id, "curse_timeout", duration_hours=0.5)
            expiry = get_perk_expiry(ctx.db, target.id, "curse_timeout")
            expiry_utc = expiry.replace(tzinfo=timezone.utc) if expiry else None
            ts = f"<t:{int(expiry_utc.timestamp())}:f>" if expiry_utc else "30 minutes"
            await interaction.response.send_message(
                f"🚫 **Timeout Ticket used!** {target.mention} is barred from casting curses until {ts}. "
                f"Any attempt will cost them 3 Boli.\n"
                f"🍮 -{cost} Boli Points (remaining: **{pts - cost}**)",
            )
            logger.info(
                "%s used Timeout Ticket on %s", interaction.user.display_name, target.display_name
            )

        # --- Multiplier Potion ---
        elif item == "multiplier_potion":
            award(ctx.db, interaction.user.id, -cost, reason="shop", detail=item)
            grant_perk(ctx.db, interaction.user.id, "multiplier_potion", duration_hours=0.25)
            expiry = get_perk_expiry(ctx.db, interaction.user.id, "multiplier_potion")
            expiry_utc = expiry.replace(tzinfo=timezone.utc) if expiry else None
            ts = f"<t:{int(expiry_utc.timestamp())}:f>" if expiry_utc else "15 minutes"
            await interaction.response.send_message(
                f"⚡ **Multiplier Potion active!** {interaction.user.mention}, every curse you cast until {ts} "
                f"will fire twice — the 2nd following 15–45 seconds later, fate-locked to the 1st.\n"
                f"🍮 -{cost} Boli Points (remaining: **{pts - cost}**)",
                ephemeral=True,
            )
            logger.info("%s purchased Multiplier Potion", interaction.user.display_name)


class ShopCog(commands.Cog):
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._added: list = []

    async def cog_load(self) -> None:
        group = ShopGroup()
        self.ctx.bot.tree.add_command(group)
        self._added.append(group)

    async def cog_unload(self) -> None:
        for cmd in self._added:
            self.ctx.bot.tree.remove_command(cmd.name, type=cmd.type)



async def setup(bot) -> None:
    await bot.add_cog(ShopCog(bot.ctx))
