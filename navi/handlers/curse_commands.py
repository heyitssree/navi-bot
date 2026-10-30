# navi/handlers/curse_commands.py - moved from bot.py on_message (behaviour unchanged)
from __future__ import annotations

import asyncio
import logging
import random
import re

import discord

from navi.data.curse_data import get_random_compliment, get_random_curse
from navi.data.messages import (
    BOT_LOOP_COMPLIMENT_REPLIES,
    BOT_LOOP_CURSE_REPLIES,
    BOT_SELF_COMPLIMENT_REPLIES,
    BOT_SELF_CURSE_REPLIES,
)
from navi.db.repos.counters import decrement_extra_actions, increment_daily_action_count
from navi.db.repos.events import log_command_event
from navi.db.repos.perks import has_active_perk
from navi.services.curse_game import backfire_curse, land_bless, land_curse, self_curse, timeout_penalty
from navi.services.quota import UNIVERSAL_BLESSING_MESSAGES, check_cosmic_quota

logger = logging.getLogger("navi.handlers.curse_commands")


async def handle_navi_command(ctx, message: discord.Message) -> bool:
    """Legacy prefix "navi" curse command (AI-free). Exact word "navi" only."""
    # ---- Legacy prefix "navi" command — only triggers on the exact word "navi" ----
    if ctx.settings.get("feature.curses") and re.match(r'^navi\b', message.content, re.IGNORECASE):
        invoker = message.author
        try:
            log_command_event(
                ctx.db, invoker.id, str(invoker), "curse",
                channel_id=message.channel.id,
                guild_id=message.guild.id if message.guild else None,
            )
        except Exception:
            pass

        # "navi @username" → curse the mentioned user (tiered points, quota-tracked)
        if message.mentions:
            target = message.mentions[0]
            if target.id == ctx.bot.user.id:
                await message.reply(random.choice(BOT_SELF_CURSE_REPLIES))
                return True
            if target.bot:
                await message.reply(f"{invoker.mention} {random.choice(BOT_LOOP_CURSE_REPLIES)}")
                return True

            # --- Curse Timeout check: invoker may be blocked by a Timeout Ticket ---
            if has_active_perk(ctx.db, invoker.id, "curse_timeout"):
                timeout_penalty(ctx.db, invoker.id)
                await message.reply(
                    f"🚫 {invoker.display_name}, you're under a **Timeout Ticket**! "
                    f"Casting curses is blocked. That stunt cost you **3 Boli**."
                )
                logger.info("%s tried to curse while timed out — -3 Boli penalty", invoker.display_name)
                return True

            # --- Daily quota check ---
            if await check_cosmic_quota(ctx, invoker, message, "curse"):
                return True

            # --- Vampiric Karma Gamble ---
            curse_data = get_random_curse()
            curse_word = curse_data["word"]

            # Check if target has curse protection or deflector shield
            target_protected = has_active_perk(ctx.db, target.id, "curse_protection")
            target_shielded = has_active_perk(ctx.db, target.id, "deflector_shield")

            if target_protected or target_shielded:
                reversal_chance = 1.0  # Protected/shielded targets always bounce the curse back
            else:
                _tier_key = {"Mild": "chance.backfire_mild", "Moderate": "chance.backfire_moderate", "Severe": "chance.backfire_severe"}
                reversal_chance = ctx.settings.get(_tier_key[curse_data["tier"]])

            daily_count = increment_daily_action_count(ctx.db, invoker.id)
            if daily_count > ctx.settings.get("limit.daily_cosmic_actions"):
                decrement_extra_actions(ctx.db, invoker.id)

            first_reversed = random.random() < reversal_chance
            dmg = curse_data["target_damage"]
            if first_reversed:
                # Backfire — symmetric reversal: invoker loses, target gains
                backfire_curse(ctx.db, invoker.id, target.id, dmg, curse_word, target_name=target.display_name)
                if target_protected:
                    perk_label = "Curse Protection"
                elif target_shielded:
                    perk_label = "Deflector Shield"
                else:
                    perk_label = None
                if perk_label:
                    await message.reply(
                        f"The cosmos rejected your negativity, {invoker.display_name}. "
                        f"{target.display_name} has an active **{perk_label}**. "
                        f"The curse reversed — you lose **{dmg} pts**, {target.display_name} gains **{dmg} pts**. {curse_word}!"
                    )
                else:
                    await message.reply(
                        f"The cosmos rejected your negativity, {invoker.display_name}. "
                        f"The curse reversed — you lose **{dmg} pts**, {target.display_name} gains **{dmg} pts**. {curse_word}!"
                    )
                logger.info(
                    "Curse backfired on %s [%s, invoker -%d, target +%d]",
                    invoker.display_name, curse_data["tier"], dmg, dmg,
                )
            else:
                # Curse lands — target loses, invoker gains
                land_curse(ctx.db, invoker.id, target.id, dmg, curse_data["invoker_reward"], curse_word,
                           protected=bool(target_protected or target_shielded), target_name=target.display_name)
                await message.reply(f"{curse_word} {target.display_name}")
                logger.info(
                    "%s cursed %s [%s, %s-%d target, +%d invoker]",
                    invoker.display_name, target.display_name,
                    curse_data["tier"], "protected, no " if (target_protected or target_shielded) else "-",
                    curse_data["target_damage"],
                    curse_data["invoker_reward"],
                )

            # --- Multiplier Potion: fire a second curse after a delay ---
            if has_active_perk(ctx.db, invoker.id, "multiplier_potion"):
                second_curse = get_random_curse()

                async def _fire_second_curse() -> None:
                    delay = random.randint(15, 45)
                    await asyncio.sleep(delay)
                    if first_reversed:
                        potion_dmg = second_curse["target_damage"]
                        backfire_curse(ctx.db, invoker.id, target.id, potion_dmg, second_curse["word"], potion=True, target_name=target.display_name)
                        await message.channel.send(
                            f"⚡ **Potion echo!** `{second_curse['word']}` — the 2nd curse reversed! "
                            f"{invoker.display_name} loses **{potion_dmg} pts**, {target.display_name} gains **{potion_dmg} pts**."
                        )
                    else:
                        land_curse(ctx.db, invoker.id, target.id, second_curse["target_damage"],
                                   second_curse["invoker_reward"], second_curse["word"],
                                   protected=bool(target_protected or target_shielded), potion=True,
                                   target_name=target.display_name)
                        await message.channel.send(
                            f"⚡ **Potion echo!** {second_curse['word']} {target.display_name} "
                            f"(2nd curse landed, +{second_curse['invoker_reward']} Boli)"
                        )

                asyncio.create_task(_fire_second_curse())

            return True

        # "navi" as a reply to someone → curse the replied-to user
        if message.reference:
            resolved = message.reference.resolved or message.reference.cached_message
            if isinstance(resolved, discord.Message) and not resolved.author.bot:
                target = resolved.author
                if await check_cosmic_quota(ctx, invoker, message, "curse"):
                    return True
                curse_data = get_random_curse()
                target_protected = has_active_perk(ctx.db, target.id, "curse_protection")
                target_shielded = has_active_perk(ctx.db, target.id, "deflector_shield")
                if target_protected or target_shielded:
                    reversal_chance = 1.0
                else:
                    _tier_key = {"Mild": "chance.backfire_mild", "Moderate": "chance.backfire_moderate", "Severe": "chance.backfire_severe"}
                    reversal_chance = ctx.settings.get(_tier_key[curse_data["tier"]])
                daily_count = increment_daily_action_count(ctx.db, invoker.id)
                if daily_count > ctx.settings.get("limit.daily_cosmic_actions"):
                    decrement_extra_actions(ctx.db, invoker.id)
                dmg = curse_data["target_damage"]
                if random.random() < reversal_chance:
                    backfire_curse(ctx.db, invoker.id, target.id, dmg, curse_data["word"], target_name=target.display_name)
                    await message.reply(
                        f"The cosmos rejected your negativity, {invoker.display_name}. "
                        f"The curse reversed — you lose **{dmg} pts**, {target.display_name} gains **{dmg} pts**. {curse_data['word']}!"
                    )
                    logger.info("Curse (reply) backfired on %s [-%d / +%d]", invoker.display_name, dmg, dmg)
                else:
                    land_curse(ctx.db, invoker.id, target.id, dmg, curse_data["invoker_reward"], curse_data["word"],
                               protected=bool(target_protected or target_shielded), target_name=target.display_name)
                    await message.reply(f"{curse_data['word']} {target.display_name}")
                    logger.info("%s cursed %s via navi reply [+%d / -%d]", invoker.display_name, target.display_name, curse_data["invoker_reward"], dmg)
                return True

        # "navi" with no mention and no reply → self-curse
        target = invoker
        if await check_cosmic_quota(ctx, invoker, message, "curse"):
            return True
        curse_data = get_random_curse()
        self_curse(ctx.db, target.id, curse_data["target_damage"], curse_data["word"])
        daily_count = increment_daily_action_count(ctx.db, invoker.id)
        if daily_count > ctx.settings.get("limit.daily_cosmic_actions"):
            decrement_extra_actions(ctx.db, invoker.id)
        await message.reply(f"{curse_data['word']} {target.display_name}")
        logger.info("%s got self-cursed via navi prefix", target.display_name)
        return True
    return False



async def handle_chunk_command(ctx, message: discord.Message) -> bool:
    """"chunk" bless command (quota-tracked, AI-free)."""
    # ---- "chunk @user" — bless command (quota-tracked, no target mention) ----
    if ctx.settings.get("feature.curses") and re.match(r'^chunk\b', message.content, re.IGNORECASE):
        invoker = message.author
        try:
            log_command_event(
                ctx.db, invoker.id, str(invoker), "bless",
                channel_id=message.channel.id,
                guild_id=message.guild.id if message.guild else None,
            )
        except Exception:
            pass

        def _bless_target(target: discord.Member | discord.User, award_points: bool) -> tuple[str, int, int, str]:
            """Returns (reply_text, target_pts, caster_pts, word)."""
            compliment = get_random_compliment()
            if award_points:
                target_pts = compliment["points"]
                caster_pts = max(1, round(target_pts * compliment["caster_share_pct"] / 100))
            else:
                target_pts = caster_pts = 0
            return f"{compliment['word']} {target.display_name}", target_pts, caster_pts, compliment["word"]

        async def _do_bless(target: discord.Member | discord.User) -> None:
            """Apply blessing: quota check → universal blessing roll → normal blessing."""
            if await check_cosmic_quota(ctx, invoker, message, "bless"):
                return

            new_daily = increment_daily_action_count(ctx.db, invoker.id)
            if new_daily > ctx.settings.get("limit.daily_cosmic_actions"):
                decrement_extra_actions(ctx.db, invoker.id)

            # Configurable universal blessing chance (default 5%)
            if random.random() < ctx.settings.get("chance.universal_blessing"):
                _UNIVERSAL_BLESSING_BONUS = 100
                land_bless(ctx.db, invoker.id, target.id, _UNIVERSAL_BLESSING_BONUS, _UNIVERSAL_BLESSING_BONUS,
                           "universal_blessing",
                           target_name=target.display_name)
                uni_msg = random.choice(UNIVERSAL_BLESSING_MESSAGES).format(
                    caster=invoker.display_name, receiver=target.display_name
                )
                await message.reply(uni_msg)
                logger.info(
                    "Universal blessing: %s → %s (+%d each)",
                    invoker.display_name, target.display_name, _UNIVERSAL_BLESSING_BONUS,
                )
                return

            reply, target_pts, caster_pts, bless_word = _bless_target(target, award_points=True)
            land_bless(ctx.db, invoker.id, target.id, target_pts, caster_pts, bless_word,
                       target_name=target.display_name)
            await message.reply(reply)
            logger.info(
                "%s blessed %s — target +%d, caster +%d",
                invoker.display_name, target.display_name, target_pts, caster_pts,
            )

        # "chunk @mention" → bless the mentioned user
        if message.mentions:
            target = message.mentions[0]
            if target.id == ctx.bot.user.id:
                await message.reply(random.choice(BOT_SELF_COMPLIMENT_REPLIES))
                return True
            if target.bot:
                await message.reply(f"{invoker.mention} {random.choice(BOT_LOOP_COMPLIMENT_REPLIES)}")
                return True
            await _do_bless(target)
            return True

        # "chunk" as reply → bless the replied-to user
        if message.reference:
            resolved = message.reference.resolved or message.reference.cached_message
            if isinstance(resolved, discord.Message) and not resolved.author.bot:
                await _do_bless(resolved.author)
                return True

        # "chunk" alone → self-bless
        await _do_bless(invoker)
        return True
    return False

