# navi/services/last_seen.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import asyncio
import logging

from navi.db.repos.users import bulk_update_last_seen

logger = logging.getLogger("navi.services.last_seen")


_LAST_SEEN_FLUSH_SECONDS = 600


def flush_last_seen(ctx) -> int:
    """Write pending last_seen values to the DB. Safe to call from any thread."""
    if ctx.db is None or not ctx.state.last_seen_pending:
        return 0
    batch = dict(ctx.state.last_seen_pending)
    count = bulk_update_last_seen(ctx.db, batch)
    for uid, ts in batch.items():  # keep entries that were refreshed while writing
        if ctx.state.last_seen_pending.get(uid) == ts:
            ctx.state.last_seen_pending.pop(uid, None)
    return count


async def last_seen_flush_loop(ctx) -> None:
    while True:
        await asyncio.sleep(_LAST_SEEN_FLUSH_SECONDS)
        try:
            n = await asyncio.get_running_loop().run_in_executor(None, flush_last_seen, ctx)
            logger.debug("Flushed last_seen for %d users", n)
        except Exception as exc:
            logger.error("last_seen flush failed: %s", exc)
