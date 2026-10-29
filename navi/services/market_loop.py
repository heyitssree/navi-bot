# navi/services/market_loop.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from navi.db.repos.market import expire_stale_holdings
from navi.services.market_engine import update_all_prices

logger = logging.getLogger("navi.services.market_loop")


async def market_hourly_loop(ctx) -> None:
    """Background loop that updates market prices every hour (IST :05).

    At midnight IST: also records price history and expires stale holdings.
    """
    _IST = timezone(timedelta(hours=5, minutes=30))

    while True:
        now_ist = datetime.now(_IST)
        # Sleep until :05 of the next hour
        next_hour = now_ist.replace(minute=5, second=0, microsecond=0)
        if now_ist >= next_hour:
            next_hour += timedelta(hours=1)
        wait_seconds = (next_hour - now_ist).total_seconds()
        logger.info("Market hourly loop sleeping %.0f s (until %s IST).", wait_seconds, next_hour.strftime('%H:%M'))
        await asyncio.sleep(wait_seconds)

        _IST2 = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(_IST2)
        is_midnight_run = now_ist.hour == 0

        try:
            await update_all_prices(ctx.db, record_history=is_midnight_run)

            if is_midnight_run:
                expired = expire_stale_holdings(ctx.db)
                if expired:
                    _NAVI_GAMES_ID = 1499827359585665104
                    notify_ch = ctx.bot.get_channel(_NAVI_GAMES_ID)
                    for item in expired:
                        if notify_ch:
                            await notify_ch.send(
                                f"📉 <@{item['user_id']}> — your {item['emoji']} **{item['name']}** "
                                f"(×{item['quantity']}, bought at {item['purchase_price']} Boli each) "
                                f"has **expired** and is now worth nothing. F in chat."
                            )
        except Exception as exc:
            logger.error("Market hourly loop error: %s", exc)


MARKET_EXPIRY_DAYS = 7  # holdings expire after this many days
