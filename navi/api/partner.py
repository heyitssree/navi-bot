# api_server.py — Lightweight FastAPI HTTP endpoint for partner bot score ingestion
#
# Runs as an asyncio task alongside the main Discord bot process.
# POST /score  accepts a JSON payload from trusted partner bots,
# validates the API key, deduplicates on game_id, normalizes the raw score,
# and awards Boli + XP to the target user in the shared SQLite DB.
#
# Setup on GCP VM:
#   1. Add PARTNER_BOT_API_KEY=<secret> to .env
#   2. Open port 8080 in GCP firewall rules (VPC network → Firewall → allow TCP 8080)
#   3. Share the VM's external IP + port + key with the partner bot owner
#
# Deduplication: game_id is stored in partner_score_log with a UNIQUE constraint.
# A duplicate submission returns HTTP 409 without awarding points.

from __future__ import annotations

import logging
import os
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("navi.api_server")

# ---------------------------------------------------------------------------
# Score normalization
# ---------------------------------------------------------------------------

# 1:1 passthrough: raw_points (sent by partner bot) → Boli awarded directly.
# Negative raw_points = player failed → 0 Boli.
# The partner bot is responsible for sending meaningful point values.

# XP awarded equals half the Boli awarded (minimum 5 XP for any valid submission)
_XP_RATIO = 0.5

# Rate limit: max submissions per guild per minute (setting partner.rate_limit_rpm)
_rate_counters: dict[int, list[float]] = defaultdict(list)


def _normalize_score(raw_points: int) -> int:
    """1:1 passthrough. Negative values are kept as deductions (stored in external_boli_points)."""
    return int(raw_points)


def _is_rate_limited(guild_id: int, limit: int = 10) -> bool:
    """Simple fixed-window rate limiter: max `limit` requests per minute per guild."""
    now = time.time()
    window = [t for t in _rate_counters[guild_id] if now - t < 60]
    _rate_counters[guild_id] = window
    if len(window) >= limit:
        return True
    _rate_counters[guild_id].append(now)
    return False


# ---------------------------------------------------------------------------
# FastAPI app factory — called from bot.py on_ready with the shared db_conn
# ---------------------------------------------------------------------------

def create_app(db_conn: sqlite3.Connection, allowed_guild_id: int | None, settings=None) -> Any:
    """Build and return the FastAPI app.

    db_conn:          The shared SQLite connection from the bot process.
    allowed_guild_id: If set, only submissions for this guild are accepted.
                      Pass None to accept any guild_id (less secure).
    """
    try:
        from fastapi import Depends, FastAPI, HTTPException, Request
        from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
        from pydantic import BaseModel
    except ImportError:
        logger.error(
            "FastAPI / pydantic not installed. Run: pip install fastapi uvicorn[standard] pydantic"
        )
        return None

    if settings is None:   # standalone use: registry defaults
        from navi.settings.store import Settings

        settings = Settings()

    from navi.db.repos.points import get_recent_partner_logs, partner_score_exists
    from navi.db.repos.users import upsert_user
    from navi.services.points import add_partner_points

    API_KEY = os.getenv("PARTNER_BOT_API_KEY", "")
    if not API_KEY:
        logger.warning("PARTNER_BOT_API_KEY not set — /score endpoint will reject all requests.")

    app = FastAPI(title="Navi Partner Score API", version="1.0")
    bearer = HTTPBearer()

    class ScorePayload(BaseModel):
        user_id: int
        guild_id: int
        username: str
        points: int               # raw game score (negative = deduction/fail)
        game_id: str | None = None  # match_id for deduplication
        game_type: str = "default"  # e.g. "wordle"

    def _verify_key(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> None:
        if not API_KEY or creds.credentials != API_KEY:
            raise HTTPException(status_code=401, detail="Invalid API key.")

    @app.post("/score", dependencies=[Depends(_verify_key)])
    async def ingest_score(payload: ScorePayload, request: Request) -> dict:
        """Accept a game score from a trusted partner bot and award Boli + XP."""

        # Guild validation
        if allowed_guild_id and payload.guild_id != allowed_guild_id:
            raise HTTPException(status_code=403, detail="Guild not authorised.")

        # Rate limit
        if _is_rate_limited(payload.guild_id, settings.get("partner.rate_limit_rpm")):
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Max 10 req/min per guild.")

        # Deduplication
        game_id = payload.game_id or f"auto:{payload.user_id}:{payload.guild_id}:{int(time.time())}"
        if payload.game_id and partner_score_exists(db_conn, payload.game_id):
            raise HTTPException(status_code=409, detail=f"game_id '{payload.game_id}' already processed.")

        # Check feature toggle — admin can disable partner point awards via the feature.partner_api setting
        if not settings.get("feature.partner_api"):
            raise HTTPException(status_code=503, detail="Partner API awards are currently disabled by admin.")

        # Normalize score → external Boli (1:1, negatives kept as deductions)
        boli = _normalize_score(payload.points)
        xp = max(settings.get("partner.min_xp"), int(boli * _XP_RATIO)) if boli > 0 else 0

        # Ensure user row exists, then record in the partner pool (one ledger row: points + XP, idempotent on game_id)
        upsert_user(db_conn, payload.user_id, payload.username)
        add_partner_points(
            db_conn,
            payload.user_id,
            boli,
            game_id=game_id,
            source_game=payload.game_type,
            xp=xp if boli > 0 else 0,
            extra={"raw_points": payload.points, "guild_id": payload.guild_id},
        )

        logger.info(
            "Partner score: user=%s game_type=%s raw=%d → boli=%d xp=%d",
            payload.username, payload.game_type, payload.points, boli, xp,
        )

        return {
            "status": "ok",
            "boli_awarded": boli,
            "xp_awarded": xp,
            "game_id": game_id,
        }

    @app.get("/score/recent")
    async def recent_scores(
        limit: int = 10,
        creds: HTTPAuthorizationCredentials = Depends(bearer),
    ) -> dict:
        """Return recent partner score submissions (admin audit endpoint)."""
        if not API_KEY or creds.credentials != API_KEY:
            raise HTTPException(status_code=401, detail="Invalid API key.")
        logs = get_recent_partner_logs(db_conn, limit=min(limit, 50))
        return {"logs": logs}

    # -----------------------------------------------------------------------
    # Internal endpoint — called by the Bamboozled Activity backend to award
    # Boli after a game ends.  Authenticated with X-Internal-Secret header,
    # NOT the public bearer token, so the Activity can't issue arbitrary awards.
    # -----------------------------------------------------------------------

    INTERNAL_SECRET = os.getenv("BOT_INTERNAL_SECRET", "")

    class BoliAwardPayload(BaseModel):
        game_id: str
        source_game: str = "bamboozled_activity"
        awards: dict[str, int]  # discord_user_id (str) → boli amount

    @app.post("/internal/boli/award")
    async def internal_boli_award(payload: BoliAwardPayload, request: Request) -> dict:
        """Accept Boli award batch from a trusted internal service (Activity backend)."""
        secret = request.headers.get("X-Internal-Secret", "")
        if not INTERNAL_SECRET or secret != INTERNAL_SECRET:
            raise HTTPException(status_code=401, detail="Invalid internal secret.")

        if partner_score_exists(db_conn, payload.game_id):
            raise HTTPException(
                status_code=409,
                detail=f"game_id '{payload.game_id}' already processed.",
            )

        if not settings.get("feature.partner_api"):
            raise HTTPException(status_code=503, detail="Partner API awards are currently disabled.")

        awarded: dict[str, int] = {}
        for discord_id_str, amount in payload.awards.items():
            try:
                user_id = int(discord_id_str)
            except ValueError:
                logger.warning("internal_boli_award: invalid discord_id %r — skipping", discord_id_str)
                continue

            if amount <= 0:
                continue

            # Best-effort username from the existing user row (may be empty string)
            username = ""
            try:
                row = db_conn.execute("SELECT display_name FROM users WHERE user_id = ?", (user_id,)).fetchone()
                if row:
                    username = row[0] or ""
            except Exception:
                pass

            upsert_user(db_conn, user_id, username)
            xp = max(settings.get("partner.min_xp"), int(amount * _XP_RATIO))
            add_partner_points(
                db_conn,
                user_id,
                amount,
                game_id=f"{payload.game_id}:{discord_id_str}",
                source_game=payload.source_game,
                xp=xp,
                extra={"raw_points": amount},
            )
            awarded[discord_id_str] = amount

        logger.info(
            "Internal boli award: game_id=%s source=%s awards=%s",
            payload.game_id,
            payload.source_game,
            awarded,
        )

        return {"status": "ok", "awarded": awarded}

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

    return app


async def run_api_server(db_conn: sqlite3.Connection, allowed_guild_id: int | None = None, settings=None) -> None:
    """Start the uvicorn server as a coroutine (run with asyncio.create_task).

    Listens on 0.0.0.0:8080 by default. Override with API_SERVER_PORT env var.
    """
    try:
        import uvicorn
    except ImportError:
        logger.error("uvicorn not installed — partner API server will not start. Run: pip install uvicorn[standard]")
        return

    app = create_app(db_conn, allowed_guild_id, settings)
    if app is None:
        return

    port = int(os.getenv("API_SERVER_PORT", "8080"))
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=True,
    )
    server = uvicorn.Server(config)
    logger.info("Partner API server starting on port %d.", port)
    await server.serve()
