# navi/services/quota.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import asyncio
import random

import discord

from navi.db.repos.counters import get_daily_action_count, get_extra_actions



_OVER_QUOTA_MESSAGES: list[str] = [
    "🌌 {invoker}, you've used all {quota} cosmic actions for today. Head to `/shop buy` to grab a refill (up to 2×10 more).",
    "⭐ Daily quota hit, {invoker}. The cosmos offers refills — `/shop buy` for up to 20 extra actions today.",
    "🌠 {quota} cosmic actions used, {invoker}. Buy a refill from `/shop buy` to keep going.",
    "✨ {invoker}, you're out of free actions for today. Pick up extras in `/shop buy` if you need more.",
    "🔮 {invoker}, the daily {quota}-action limit is reached. `/shop buy` has refills waiting.",
]


UNIVERSAL_BLESSING_MESSAGES: list[str] = [
    "✨ The cosmos just smiled. {caster} blessed {receiver} so hard the universe joined in — **both get 100 Boli** each!",
    "🌸 A rare cosmic alignment! {caster}'s blessing for {receiver} echoed through the stars. **+100 Boli** to both of you, mwah!",
    "💫 Oh wow. {caster} sent love to {receiver} and the universe sent it back tenfold. **100 Boli** each, as a treat!",
    "🌟 Universal Blessing activated! {caster} and {receiver} are bathed in cosmic light. **+100 Boli** each — the stars are happy today!",
    "🎀 The heavens noticed! {caster} blessed {receiver} with such sincerity that the cosmos rewarded them both. **100 Boli** each!",
]


# Messages shown when a user can't buy because they have unused purchased actions
HAS_EXTRAS_MESSAGES: list[str] = [
    "🔋 {invoker}, you still have **{extra}** purchased action(s) left. Spend those first before buying more.",
    "You haven't used your purchased actions yet, {invoker}. You have **{extra}** remaining. Use them first!",
    "⚡ {invoker}, **{extra}** extra cosmic action(s) left in your tank. Burn through them before refilling.",
]


# Over-quota game messages (combined plays/day across all games; the limit is the setting limit.game_daily)
OVER_QUOTA_GAME_MESSAGES: list[str] = [
    "{user}, you've hit the **{limit} combined game plays** limit for today. Resets at midnight IST!",
    "The cosmic casino is done with you for today, {user}. 30 plays across all games max. See you at midnight IST.",
    "{user}, {limit} combined gambling plays per day is the rule. The cosmos has spoken. Midnight IST resets it.",
    "Out of plays, {user}. You've burned through all **{limit} combined chances** today. Try again after midnight IST.",
    "The dealer's cut you off, {user}. 30 plays (any game) per day. Midnight IST is your reset.",
]


async def check_cosmic_quota(ctx, invoker: discord.Member | discord.User,
    reply_target: discord.Message,
    action_type: str = "curse",  # for log labelling only
) -> bool:
    """Check if the invoker can perform a cosmic action (curse or bless).

    Returns True if the action is BLOCKED (caller should return early).
    Returns False if the action is ALLOWED (caller may proceed).

    All DB reads are offloaded to a thread executor to avoid blocking the event loop.
    """
    loop = asyncio.get_running_loop()

    def _db_reads():
        daily = get_daily_action_count(ctx.db, invoker.id)
        extras = get_extra_actions(ctx.db, invoker.id)
        return daily, extras

    daily_count, extra_actions = await loop.run_in_executor(None, _db_reads)

    if daily_count < ctx.settings.get("limit.daily_cosmic_actions") or extra_actions > 0:
        return False

    # Quota exhausted and no extras — direct to shop.
    msg = random.choice(_OVER_QUOTA_MESSAGES).format(
        invoker=invoker.display_name, quota=ctx.settings.get("limit.daily_cosmic_actions")
    )
    await reply_target.reply(msg)
    return True
