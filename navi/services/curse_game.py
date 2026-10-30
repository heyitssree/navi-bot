# navi/services/curse_game.py - ledger side of the curse / bless game.
#
# The rules themselves (tier odds, protection bounce, quotas, potion echo) stay in handlers/curse_commands.py
# exactly as before; these helpers only record the resulting balance changes. Every curse/bless writes a ledger
# row for the person it happened to (even a zero-point one for a protected target), which is what the
# "most cursed" / "most blessed" leaderboards count.

from __future__ import annotations

import sqlite3

from navi.db.repos.users import upsert_user
from navi.services.points import award

TIMEOUT_PENALTY = 3


def _ensure_user(db: sqlite3.Connection, user_id: int, name: str | None) -> None:
    if name is not None and db.execute("SELECT 1 FROM users WHERE user_id = ?", [user_id]).fetchone() is None:
        upsert_user(db, user_id, name)


def _detail(word: str, potion: bool) -> str:
    return f"potion_{word}" if potion else word


def timeout_penalty(db: sqlite3.Connection, invoker_id: int) -> None:
    """Casting while under a Timeout Ticket costs 3 Boli."""
    award(db, invoker_id, -TIMEOUT_PENALTY, reason="curse_timeout")


def land_curse(
    db: sqlite3.Connection, invoker_id: int, target_id: int, damage: int, reward: int, word: str,
    *, protected: bool, potion: bool = False, target_name: str | None = None,
) -> None:
    """Curse lands: the target loses `damage` (nothing if protected/shielded), the invoker gains `reward`.

    target_name creates the target's profile if they have never posted, so the curse is still recorded
    (the old curse_logs table kept such rows too).
    """
    _ensure_user(db, target_id, target_name)
    detail = _detail(word, potion)
    award(db, target_id, 0 if protected else -damage, reason="curse_received", detail=detail,
          counterparty_id=invoker_id, log_only=True)
    award(db, invoker_id, reward, reason="curse_cast", detail=detail, counterparty_id=target_id)


def backfire_curse(
    db: sqlite3.Connection, invoker_id: int, target_id: int, damage: int, word: str, *, potion: bool = False,
    target_name: str | None = None,
) -> None:
    """Symmetric reversal: the invoker loses `damage`, the target gains it."""
    _ensure_user(db, target_id, target_name)
    detail = _detail(word, potion)
    award(db, invoker_id, -damage, reason="curse_backfire", detail=detail, counterparty_id=target_id, log_only=True)
    award(db, target_id, damage, reason="curse_backfire_gain", detail=detail, counterparty_id=invoker_id)


def self_curse(db: sqlite3.Connection, user_id: int, damage: int, word: str) -> None:
    award(db, user_id, -damage, reason="curse_self", detail=word, log_only=True)


def land_bless(
    db: sqlite3.Connection, invoker_id: int, target_id: int, target_pts: int, caster_pts: int, word: str,
    *, target_name: str | None = None,
) -> None:
    """Blessing: the target gains target_pts (+XP); the caster gets caster_pts (+XP) unless blessing themselves."""
    _ensure_user(db, target_id, target_name)
    award(db, target_id, target_pts, target_pts, reason="bless_received", detail=word,
          counterparty_id=invoker_id, log_only=True)
    if invoker_id != target_id:
        award(db, invoker_id, caster_pts, caster_pts, reason="bless_cast", detail=word, counterparty_id=target_id)
