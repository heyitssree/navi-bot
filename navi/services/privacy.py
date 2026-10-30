# navi/services/privacy.py - /privacy: opt-out purge, opt-in cooldown and the single is_opted_out() helper
#
# privacy.db (separate file, never purged) holds only user_id, status and changed_at. The opted-out IDs are loaded into
# memory at startup; every enforcement point asks ctx.privacy.is_opted_out(user_id).

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from navi.db.repos.privacy import get_state, opted_out_ids, set_status

logger = logging.getLogger("navi.services.privacy")

# Every table that carries a user ID, and the column(s) to delete by.
USER_TABLES = (
    ("users", "user_id"), ("daily_counters", "user_id"), ("points_ledger", "user_id"), ("holdings", "user_id"),
    ("perks", "user_id"), ("media", "owner_id"), ("game_results", "user_id"), ("prediction_history", "user_id"),
    ("events", "user_id"), ("permissions", "user_id"),
)
# Rows of OTHER people that point at this user: the reference is cleared, the row stays.
NULLIFY = (
    ("points_ledger", "counterparty_id"), ("knowledge", "submitted_by"), ("knowledge", "approved_by"),
    ("content", "reviewed_by"), ("settings", "updated_by"),
)

OPTED_OUT_MESSAGE = "You've opted out of Navi. Use /privacy opt_in to come back."


@dataclass
class OptInResult:
    ok: bool
    message: str
    available_on: str | None = None


@dataclass
class PurgeResult:
    media_files: list[str]
    s3_keys: list[str]
    orphan_app_emojis: list[str]
    rows_deleted: int


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


class Privacy:
    """In-memory opt-out set backed by privacy.db. conn=None keeps everything in memory (tests, tools)."""

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self.conn = conn
        self._out: set[int] = set()
        self.load()

    def load(self) -> None:
        if self.conn is not None:
            self._out = opted_out_ids(self.conn)
        logger.info("Privacy: %d opted-out users", len(self._out))

    def is_opted_out(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self._out

    @property
    def opted_out(self) -> frozenset[int]:
        return frozenset(self._out)

    def status(self, user_id: int) -> tuple[str, str] | None:
        if self.conn is not None:
            return get_state(self.conn, user_id)
        return ("out", "") if user_id in self._out else None

    # ----------------------------------------------------------------- opt out
    def mark_out(self, user_id: int, now: str | None = None) -> None:
        """Record the opt-out FIRST (file, then memory), so a crash mid-purge still blocks the user."""
        if self.conn is not None:
            set_status(self.conn, user_id, "out", now)
        self._out.add(user_id)

    def opt_out(self, ctx, user_id: int) -> PurgeResult:
        self.mark_out(user_id)
        result = purge_user(ctx.db, user_id)
        clear_memory(ctx, user_id)
        for path in result.media_files:
            try:
                os.remove(path)
            except OSError:
                pass
        if result.s3_keys and ctx.config.bucket:
            from navi.services.media_store import delete_objects

            delete_objects(ctx.config.bucket, result.s3_keys)
        return result

    # ----------------------------------------------------------------- opt in
    def opt_in(self, user_id: int, cooldown_days: int, now: datetime | None = None) -> OptInResult:
        state = self.status(user_id)
        if state is None or state[0] != "out":
            return OptInResult(True, "You're already opted in.")
        now = now or datetime.now(timezone.utc)
        if state[1]:
            available = _parse(state[1]) + timedelta(days=cooldown_days)
            if now < available:
                return OptInResult(False, "You opted out recently.", available.strftime("%Y-%m-%d"))
        if self.conn is not None:
            set_status(self.conn, user_id, "in")
        self._out.discard(user_id)
        return OptInResult(True, "Welcome back! Your profile starts fresh the next time you use Navi.")


def purge_user(db: sqlite3.Connection, user_id: int) -> PurgeResult:
    """Delete everything Navi stores about a user in ONE transaction. Returns files and app emojis to clean up."""
    try:
        media = db.execute("SELECT shortcut, storage_type, location, discord_id FROM media WHERE owner_id = ?", [user_id]).fetchall()
        deleted = 0
        for table, column in NULLIFY:
            db.execute(f"UPDATE {table} SET {column} = NULL WHERE {column} = ?", [user_id])
        db.execute("UPDATE permissions SET granted_by = 0 WHERE granted_by = ?", [user_id])
        for table, column in USER_TABLES:
            deleted += db.execute(f"DELETE FROM {table} WHERE {column} = ?", [user_id]).rowcount
        # application emojis only this user used: nobody else's shortcut points at them
        emoji_ids = {m[3] for m in media if m[1] in ("app_emoji", "app_emoji_sticker") and m[3]}
        orphans = [e for e in emoji_ids if db.execute("SELECT 1 FROM media WHERE discord_id = ?", [e]).fetchone() is None]
        for e in orphans:
            db.execute("DELETE FROM app_emojis WHERE emoji_id = ?", [e])
        db.execute("INSERT INTO events (kind, name) VALUES ('privacy', 'opt_out')")   # no user ID: counting only
        db.commit()
    except Exception:
        db.rollback()
        raise
    return PurgeResult(media_files=[m[2] for m in media if m[1] == "local" and m[2]], s3_keys=[m[2] for m in media if m[1] == "s3" and m[2]],
                       orphan_app_emojis=orphans, rows_deleted=deleted)


def clear_memory(ctx, user_id: int) -> None:
    """Forget everything held in memory about the user."""
    st = ctx.state
    st.seen_users.discard(user_id)
    for mapping in (st.last_seen_pending, st.user_level_cache, st.user_usage, st.slang_spam_tracker, st.slang_cooldown):
        mapping.pop(user_id, None)
    for key in [k for k in st.recent_templates if k[0] == user_id]:
        st.recent_templates.pop(key, None)
    st.limit_notice.pop(user_id, None)
    llm = ctx.llm
    if llm is not None:
        llm._user_last.pop(user_id, None)
        llm._user_day.pop(user_id, None)
