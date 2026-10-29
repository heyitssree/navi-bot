# navi/services/points.py - the ONLY module cogs and handlers use to change Boli or XP.
#
# Phase 2: thin wrappers over the repo functions. Phase 3 makes every change write a points_ledger row here,
# so nothing outside this module may import update_boli_points / add_experience / set_user_points from the repos.

from __future__ import annotations

import sqlite3

from navi.db.repos import points as _repo


def update_boli_points(conn: sqlite3.Connection, user_id: int, delta: int) -> None:
    """Add (or subtract) Boli Points for a user."""
    _repo.update_boli_points(conn, user_id, delta)


def add_experience(conn: sqlite3.Connection, user_id: int, delta: int) -> None:
    """Add XP for a user. XP never decreases - negative deltas are ignored."""
    _repo.add_experience(conn, user_id, delta)


def set_user_points(
    conn: sqlite3.Connection,
    user_id: int,
    username: str,
    points: int,
    prediction_count: int = 0,
    rashi: str | None = None,
) -> None:
    """Upsert a user's Boli Points directly (admin restore)."""
    _repo.set_user_points(conn, user_id, username, points, prediction_count, rashi)


def add_external_boli(conn: sqlite3.Connection, *args, **kwargs):
    """Record partner-pool points (same signature as the repo function)."""
    return _repo.add_external_boli(conn, *args, **kwargs)
