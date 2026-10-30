# navi/app.py - build the bot, create the AppContext, load cogs, start and stop background jobs

from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

from navi.api.partner import run_api_server
from navi.config import Config
from navi.context import AppContext
from pathlib import Path

from navi.db import connection as db_connection
from navi.db.connection import init_db
from navi.db.repos.privacy import connect_privacy
from navi.db.repos.events import count_llm_calls_today, log_command_event, log_llm_call, log_session_event
from navi.db.repos.knowledge import seed_local_knowledge
from navi.handlers import pipeline
from navi.llm.gemini import GeminiProvider
from navi.llm.router import LLMRouter
from navi.services.backup import backup_loop, do_backup
from navi.services.last_seen import flush_last_seen, last_seen_flush_loop
from navi.services.lucky_draw import lucky_draw_loop
from navi.services.market_loop import market_hourly_loop
from navi.services.owner import dm_owner
from navi.llm import safety
from navi.llm.policy import build_policy, write_allowlist
from navi.services.mentions import DEFAULT as DEFAULT_MENTIONS
from navi.services.predictions import make_cache_lookup
from navi.services.template_pool import seed_templates, store_rejected, template_batch_loop
from navi.services.retention import retention_loop
from navi.services.slang_scorer import load_slang_data
from navi.services.templates import load_templates
from navi.services.privacy import OPTED_OUT_MESSAGE, Privacy
from navi.settings.store import Settings

logger = logging.getLogger("navi")

COGS = [
    "navi.cogs.predictions",
    "navi.cogs.economy",
    "navi.cogs.market",
    "navi.cogs.shop",
    "navi.cogs.games",
    "navi.cogs.summaries",
    "navi.cogs.moderation",
    "navi.cogs.community",
    "navi.cogs.media",
    "navi.cogs.help",
    "navi.cogs.privacy",
    "navi.cogs.teach",
    "navi.cogs.admin",
]

LOCAL_MEDIA_DIR = "data/local_media"


class NaviTree(app_commands.CommandTree):
    """CommandTree subclass that enforces the master kill switch globally."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        ctx: AppContext = interaction.client.ctx

        # Opted-out users may only use /privacy (the owner keeps /admin so they can never be locked out)
        if ctx.privacy.is_opted_out(interaction.user.id):
            name = interaction.command.qualified_name if interaction.command else ""
            is_admin = name.startswith("admin") and interaction.user.id == ctx.config.owner_id
            if not name.startswith("privacy") and not is_admin:
                await interaction.response.send_message(OPTED_OUT_MESSAGE, ephemeral=True)
                return False

        if not ctx.settings.get("system.killswitch"):
            return True  # bot alive - allow all

        # Bot is dead - only owner can reach /admin commands
        is_owner = bool(ctx.config.owner_id and interaction.user.id == ctx.config.owner_id)
        if not is_owner:
            try:
                app_info = await ctx.bot.application_info()
                is_owner = interaction.user.id == app_info.owner.id
            except Exception:
                pass

        if is_owner and interaction.command and interaction.command.qualified_name.startswith("admin"):
            return True

        await interaction.response.send_message(
            "Bot is currently disabled. Only the owner can re-enable it.",
            ephemeral=True,
        )
        return False


class NaviBot(commands.Bot):
    ctx: AppContext

    async def setup_hook(self) -> None:
        for ext in COGS:
            await self.load_extension(ext)

    async def close(self) -> None:
        await shutdown(self.ctx)
        await super().close()


def start_task(ctx: AppContext, name: str, coro) -> None:
    """Start a named background task; it is cancelled on shutdown."""
    ctx.tasks[name] = asyncio.create_task(coro, name=name)


async def shutdown(ctx: AppContext) -> None:
    """Cancel background tasks, flush pending state, write the stop event, back up and close the DB."""
    for task in list(ctx.tasks.values()):
        task.cancel()
    ctx.tasks.clear()
    if ctx.db is None:
        return
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, flush_last_seen, ctx)
    except Exception:
        pass
    try:
        log_session_event(ctx.db, "stop")
    except Exception:
        pass
    try:
        path = await loop.run_in_executor(None, do_backup)
        logger.info("Shutdown DB backup written to %s", path)
    except Exception as exc:
        logger.warning("Shutdown backup failed: %s", exc)
    try:
        ctx.db.close()
        logger.info("SQLite connection closed cleanly.")
    except Exception as exc:
        logger.warning("Error closing SQLite on shutdown: %s", exc)


def build(config: Config) -> tuple[NaviBot, AppContext]:
    intents = discord.Intents.all()
    intents.message_content = True
    bot = NaviBot(command_prefix=commands.when_mentioned, intents=intents, tree_cls=NaviTree, help_command=None,
                  allowed_mentions=DEFAULT_MENTIONS)
    ctx = AppContext(bot=bot, config=config, settings=Settings(), privacy=Privacy())
    bot.ctx = ctx
    register_events(bot, ctx)
    return bot, ctx


def register_events(bot: NaviBot, ctx: AppContext) -> None:
    @bot.event
    async def on_ready() -> None:
        logger.info("Logged in as %s", bot.user)

        # Initialise database
        ctx.db = init_db()
        ctx.settings.bind(ctx.db)
        ctx.privacy = Privacy(connect_privacy(ctx.config.privacy_db_path or Path(db_connection.DB_PATH).parent / "privacy.db"))
        seed_local_knowledge(ctx.db)
        seed_templates(ctx.db)
        log_session_event(ctx.db, "start")

        # LLM provider (free key first, paid as fallback) behind the router
        provider = GeminiProvider(ctx.config.free_api_key, ctx.config.paid_api_key, ctx.config.llm_model)
        ctx.llm = LLMRouter(
            provider,
            cache_lookup=make_cache_lookup(lambda: ctx.db),
            rpm_limit=10,
            settings=ctx.settings,
            free_tier_mode=ctx.config.free_tier_mode,
        )
        ctx.llm.on_event = lambda e: log_llm_call(
            ctx.db, e["provider"], e["model"], e["purpose"], e["outcome"], e["input_tokens"], e["output_tokens"],
            e["latency_ms"],
        )
        loop = asyncio.get_running_loop()
        ctx.llm.on_config_error = lambda text: loop.create_task(dm_owner(ctx, text))
        ctx.llm.seed_daily_calls(count_llm_calls_today(ctx.db))
        # Safety: owner's blocklist, generated allow-list (approved + curse terms), prompt policy, rejection log
        allowed = write_allowlist("data/safety/allowlist.txt", ctx.db)
        safety.configure(settings=ctx.settings, blocklist=safety.load_blocklist(), allowed_terms=allowed)
        ctx.llm.policy = build_policy(ctx.db)
        ctx.llm.on_reject = lambda req, text, reasons: store_rejected(ctx.db, {"prediction": "prediction"}.get(req.purpose, req.purpose), text, reasons)
        logger.info("Safety filter active: %d blocklist entries, %d allow-listed terms", safety._filter.entry_count, len(allowed))
        await ctx.llm.verify()

        # Load feature toggles and testing guild IDs into memory
        ctx.settings.load()

        # Load local slang dictionary and response templates into memory
        load_slang_data()
        load_templates()

        # Ensure local media storage directory exists
        os.makedirs(LOCAL_MEDIA_DIR, exist_ok=True)

        start_task(ctx, "backup", backup_loop())
        start_task(ctx, "last_seen_flush", last_seen_flush_loop(ctx))
        start_task(ctx, "lucky_draw", lucky_draw_loop(ctx))
        start_task(ctx, "market_hourly", market_hourly_loop(ctx))
        start_task(ctx, "retention", retention_loop(ctx))
        start_task(ctx, "template_batches", template_batch_loop(ctx))
        start_task(ctx, "partner_api", run_api_server(ctx.db, allowed_guild_id=ctx.config.guild_id, settings=ctx.settings, privacy=ctx.privacy))

        await bot.tree.sync()
        logger.info("Slash commands synced. Navi is live. Hey! Listen!")

    @bot.event
    async def on_interaction(interaction: discord.Interaction) -> None:
        """Log every slash command invocation to command_events for analytics."""
        if interaction.type != discord.InteractionType.application_command:
            return
        if ctx.db is None or not interaction.data:
            return
        try:
            log_command_event(
                ctx.db,
                interaction.user.id,
                str(interaction.user),
                interaction.data.get("name", "unknown"),
                channel_id=interaction.channel_id,
                guild_id=interaction.guild_id,
            )
        except Exception:
            pass

    @bot.event
    async def on_message(message: discord.Message) -> None:
        await pipeline.on_message(ctx, message)


def configure_logging() -> None:
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("logs/bot.log", encoding="utf-8"),
        ],
    )


def main() -> None:
    configure_logging()
    config = Config.from_env()
    if not config.discord_token:
        logger.critical("DISCORD_TOKEN not found in .env. Stopping.")
        raise SystemExit(1)

    if not config.free_api_key and not config.paid_api_key:
        logger.critical("No Gemini API key found. Set GEMINI_API_KEY_FREE or GEMINI_API_KEY_PAID in .env.")
        raise SystemExit(1)

    logger.info(
        "Starting Navi... Free key: %s | Paid key: %s | Free tier mode: %s",
        "✓" if config.free_api_key else "✗",
        "✓" if config.paid_api_key else "✗",
        config.free_tier_mode,
    )
    bot, _ = build(config)
    bot.run(config.discord_token)
