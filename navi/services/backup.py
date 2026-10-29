# navi/services/backup.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import datetime

from navi.db.connection import DB_PATH

logger = logging.getLogger("navi.services.backup")


_BACKUP_DIR = "data/backups"


_BACKUP_KEEP = 24  # rolling window — oldest is dropped when limit is hit


_BACKUP_INTERVAL_HOURS = 1


def do_backup() -> str:
    """Copy the DB file. Returns the backup path. Runs in executor.

    SQLite WAL mode makes live file copies safe — no manual checkpoint needed.
    """
    import pathlib
    pathlib.Path(_BACKUP_DIR).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    dest = os.path.join(_BACKUP_DIR, f"navi_backup_{ts}.db")
    shutil.copy2(str(DB_PATH), dest)
    # Prune oldest backups beyond the rolling window
    backups = sorted(
        [f for f in os.listdir(_BACKUP_DIR) if f.startswith("navi_backup_") and f.endswith(".db")]
    )
    for old in backups[:-_BACKUP_KEEP]:
        try:
            os.remove(os.path.join(_BACKUP_DIR, old))
        except OSError:
            pass
    return dest


async def backup_loop() -> None:
    """Background task: backup the database every hour."""
    await asyncio.sleep(60)  # small initial delay so on_ready finishes first
    while True:
        try:
            path = await asyncio.get_running_loop().run_in_executor(None, do_backup)
            logger.info("DB backup written to %s", path)
        except Exception as exc:
            logger.error("DB backup failed: %s", exc)
        await asyncio.sleep(_BACKUP_INTERVAL_HOURS * 3600)
