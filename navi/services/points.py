# navi/services/points.py - the ONLY module cogs and handlers use to change Boli or XP.
#
# Every change updates the balance and appends a points_ledger row in ONE transaction (see repos.points.apply_entry),
# so SUM(ledger.delta) per user and pool always equals the stored balance. Nothing else may touch boli_points,
# partner_points or experience (tests/phase2 enforces the import rule).

from __future__ import annotations

import json
import sqlite3

from navi.db.repos import points as _repo


def award(
    conn: sqlite3.Connection,
    user_id: int,
    delta: int = 0,
    xp: int = 0,
    *,
    reason: str,
    pool: str = "native",
    counterparty_id: int | None = None,
    detail: str | None = None,
    ref: str | None = None,
    log_only: bool = False,
) -> bool:
    """Change a user's balance (delta, may be negative) and/or XP (never negative) and record why.

    Returns True when a ledger row was written. See repos.points.apply_entry for the False cases.
    """
    return _repo.apply_entry(
        conn, user_id, delta, xp, reason,
        pool=pool, counterparty_id=counterparty_id, detail=detail, ref=ref, log_only=log_only,
    )


def update_boli_points(conn: sqlite3.Connection, user_id: int, delta: int, *, reason: str, **kw) -> bool:
    """Add (or subtract) native Boli Points for a user."""
    return award(conn, user_id, delta, 0, reason=reason, **kw)


def add_experience(conn: sqlite3.Connection, user_id: int, delta: int, *, reason: str, **kw) -> bool:
    """Add XP for a user. XP never decreases - non-positive deltas are ignored."""
    if delta <= 0:
        return False
    return award(conn, user_id, 0, delta, reason=reason, **kw)


def set_user_points(
    conn: sqlite3.Connection,
    user_id: int,
    username: str,
    points: int,
    prediction_count: int = 0,
    rashi: str | None = None,
    *,
    updated_by: int | None = None,
) -> None:
    """Admin restore: set a user's native balance to an absolute value (ledger records the difference)."""
    from navi.db.repos.users import get_user_profile, upsert_user

    existing = get_user_profile(conn, user_id)
    if existing is None:
        upsert_user(conn, user_id, username, rashi)
        current = 0
    else:
        current = existing["boli_points"]
        upsert_user(conn, user_id, username, rashi)
    conn.execute("UPDATE users SET prediction_count = ? WHERE user_id = ?", [prediction_count, user_id])
    conn.commit()
    award(conn, user_id, points - current, 0, reason="admin", detail=json.dumps({"set_to": points, "by": updated_by}),
          log_only=True)


def add_partner_points(
    conn: sqlite3.Connection,
    user_id: int,
    points: int,
    *,
    game_id: str | None = None,
    source_game: str = "partner",
    xp: int = 0,
    extra: dict | None = None,
) -> bool:
    """Partner-pool award. game_id makes it idempotent (a repeated game_id returns False)."""
    detail = json.dumps({"game_type": source_game, **(extra or {})})
    return award(conn, user_id, points, xp, reason="partner_award", pool="partner", ref=game_id, detail=detail,
                 log_only=True)
