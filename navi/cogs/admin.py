# navi/cogs/admin.py - /admin: panel, direct setting edits, status, user tools, /teach approvals, review, export/import
#
# Every command is ephemeral and owner-only (or system.panel_role). The old toggle_* / set_* / config_view /
# partner_toggle / reset_* commands, /health and the "navi syros" text command are gone: the panel and
# /admin set|get|reset cover every setting, /admin status replaces /health and config_view.

from __future__ import annotations

import io
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from navi.cogs.admin_panel import PanelView
from navi.cogs.admin_review import ReviewView
from navi.context import AppContext
from navi.db.connection import DB_PATH
from navi.db.repos.counters import reset_gambling_count, reset_gemini_game_count
from navi.db.repos.events import estimate_cost, get_table_counts, llm_usage_by_provider_today
from navi.db.repos.permissions import grant, list_permission, revoke
from navi.db.repos.users import get_user_profile, reset_all_strikes, reset_user_strikes, upsert_user
from navi.services.permissions import can_use_admin
from navi.services.points import award
from navi.settings.registry import SETTINGS, resolve
from navi.settings.store import SettingError, format_value

logger = logging.getLogger("navi.cogs.admin")

BACKUP_DIR = Path("data/backups")


async def key_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    needle = current.lower()
    hits = [s for s in SETTINGS if not s.hidden and (needle in s.key.lower() or needle in s.label.lower())]
    return [app_commands.Choice(name=f"{s.key} - {s.label}"[:100], value=s.key) for s in hits[:25]]


def _public_setting(key: str):
    setting = resolve(key)
    if setting.hidden:
        raise SettingError("That setting is internal state and cannot be edited.")
    return setting


class AdminGroup(app_commands.Group):
    """Admin controls - owner (or the panel role) only."""

    def __init__(self) -> None:
        super().__init__(
            name="admin",
            description="Navi owner configuration controls",
            default_permissions=discord.Permissions(administrator=True),
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if await can_use_admin(interaction.client.ctx, interaction.user):
            return True
        await interaction.response.send_message("Admin commands are owner-only.", ephemeral=True)
        return False

    # ------------------------------------------------------------------ panel and settings
    @app_commands.command(name="panel", description="Open the settings panel")
    async def panel(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        view = PanelView(ctx, interaction.user.id)
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @app_commands.command(name="set", description="Change a setting")
    @app_commands.describe(key="Setting key", value="New value (on/off, a number, text, a channel or role mention, or 'none')")
    @app_commands.autocomplete(key=key_autocomplete)
    async def set_cmd(self, interaction: discord.Interaction, key: str, value: str) -> None:
        ctx = interaction.client.ctx
        try:
            setting = _public_setting(key)
            stored = ctx.settings.set_text(setting.key, value, by=interaction.user.id)
        except KeyError:
            await interaction.response.send_message(f"Unknown setting `{key}`. Start typing to see the list.", ephemeral=True)
            return
        except SettingError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        note = " (takes effect after a restart)" if setting.restart else ""
        if setting.key in ("ai.provider", "ai.fallback_provider") and stored not in ("off", *(ctx.llm.providers if ctx.llm else ())):
            note += f"\n⚠️ The **{stored}** provider is not configured on this server (credentials / model id missing), so replies will use fallbacks."
        await interaction.response.send_message(f"✅ **{setting.label}** (`{setting.key}`) is now **{format_value(setting, stored)}**.{note}", ephemeral=True)

    @app_commands.command(name="get", description="Show a setting")
    @app_commands.autocomplete(key=key_autocomplete)
    async def get_cmd(self, interaction: discord.Interaction, key: str) -> None:
        ctx = interaction.client.ctx
        try:
            setting = resolve(key)
        except KeyError:
            await interaction.response.send_message(f"Unknown setting `{key}`.", ephemeral=True)
            return
        changed = "" if ctx.settings.is_default(setting.key) else " ✏️ changed"
        await interaction.response.send_message(
            f"**{setting.label}** (`{setting.key}`){changed}\n{setting.help}\n"
            f"Current: **{format_value(setting, ctx.settings.get(setting.key))}** · Default: {format_value(setting, setting.default)}",
            ephemeral=True,
        )

    @app_commands.command(name="reset", description="Reset a setting to its default")
    @app_commands.autocomplete(key=key_autocomplete)
    async def reset_cmd(self, interaction: discord.Interaction, key: str) -> None:
        ctx = interaction.client.ctx
        try:
            setting = _public_setting(key)
        except (KeyError, SettingError) as exc:
            await interaction.response.send_message(f"❌ {exc.args[0] if exc.args else exc}", ephemeral=True)
            return
        ctx.settings.reset(setting.key, by=interaction.user.id)
        await interaction.response.send_message(f"↩️ **{setting.label}** reset to **{format_value(setting, setting.default)}**.", ephemeral=True)

    @app_commands.command(name="killswitch", description="Emergency stop: silence Navi everywhere except /admin")
    @app_commands.choices(state=[app_commands.Choice(name="on (silence the bot)", value="on"), app_commands.Choice(name="off (bring it back)", value="off")])
    async def killswitch(self, interaction: discord.Interaction, state: str) -> None:
        ctx = interaction.client.ctx
        ctx.settings.set("system.killswitch", state == "on", by=interaction.user.id)
        text = "💀 Master kill switch is **ON**. Navi is silent." if state == "on" else "✅ Kill switch is **OFF**. Navi is back."
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="testing", description="Toggle testing mode (no limits, no rewards) for this server")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def testing(self, interaction: discord.Interaction, state: str) -> None:
        ctx = interaction.client.ctx
        if interaction.guild_id is None:
            await interaction.response.send_message("Run this inside a server.", ephemeral=True)
            return
        guilds = set(ctx.settings.get("system.testing_guilds"))
        (guilds.add if state == "on" else guilds.discard)(interaction.guild_id)
        ctx.settings.set("system.testing_guilds", sorted(guilds), by=interaction.user.id)
        await interaction.response.send_message(
            f"🧪 Testing mode is **{state.upper()}** for this server." + (" No rate limits, no rewards." if state == "on" else ""), ephemeral=True)

    # ------------------------------------------------------------------ status
    @app_commands.command(name="status", description="Uptime, AI provider, breaker, today's calls, DB size and last backup")
    async def status(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        await interaction.response.defer(ephemeral=True)
        up = int((datetime.now(timezone.utc) - ctx.state.start_time).total_seconds())
        info = ctx.llm.status_dict() if ctx.llm else {}
        usage = llm_usage_by_provider_today(ctx.db)
        calls = sum(u[0] for u in usage.values())
        bedrock_in, bedrock_out = usage.get('bedrock', (0, 0, 0))[1:]
        cost = estimate_cost(bedrock_in, bedrock_out, ctx.settings.get('ai.price_input_per_mtok'), ctx.settings.get('ai.price_output_per_mtok'))
        per_provider = ' · '.join(f'{n}: {c} calls, {i:,} in / {o:,} out' for n, (c, i, o) in sorted(usage.items())) or 'no calls yet'
        cap = ctx.settings.get("ai.daily_call_cap")
        try:
            db_size = f"{Path(DB_PATH).stat().st_size / (1024 * 1024):.2f} MB"
        except OSError:
            db_size = "n/a"
        backups = sorted(BACKUP_DIR.glob("navi_backup_*.db")) if BACKUP_DIR.exists() else []
        last_backup = datetime.fromtimestamp(os.path.getmtime(backups[-1]), timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if backups else "none yet"
        breaker = "OPEN 🔴" if info.get("circuit_open") else "closed 🟢"
        emb = discord.Embed(title="🔧 Navi status", color=discord.Color.red() if info.get("circuit_open") else discord.Color.green())
        emb.add_field(name="⏱️ Uptime", value=f"{up // 3600}h {(up % 3600) // 60}m {up % 60}s", inline=True)
        emb.add_field(name="🧠 AI", value=f"Provider: **{ctx.settings.get('ai.provider')}** (fallback: {ctx.settings.get('ai.fallback_provider')})\nModel: `{info.get('model', 'n/a')}`\nConfigured: {', '.join(info.get('providers', [])) or 'none'}\nGemini keys: {ctx.settings.get('ai.gemini_keys')}\nBreaker: {breaker}"
                      + (f" ({info.get('circuit_seconds_left')}s left)" if info.get("circuit_open") else ""), inline=True)
        emb.add_field(name="📊 Today", value=f"Calls: **{calls}** / {cap} (**{max(0, cap - calls)}** left)\n{per_provider}\nEstimated Bedrock cost today: **${cost:.4f}**\nRPM: {info.get('rpm_used', 0)}/{info.get('rpm_limit', '?')}", inline=False)
        emb.add_field(name="🗄️ Database", value=f"Size: {db_size}\nLast backup: {last_backup}\nReplication: n/a (AWS phase)\n" + " · ".join(f"{t} {n:,}" for t, n in get_table_counts(ctx.db).items()), inline=False)
        emb.add_field(name="🛡️ Switches", value=f"Kill switch: {'ON' if ctx.settings.get('system.killswitch') else 'off'}\nTesting guilds: {len(ctx.settings.get('system.testing_guilds'))}", inline=True)
        await interaction.followup.send(embed=emb, ephemeral=True)

    # ------------------------------------------------------------------ review, export, import
    @app_commands.command(name="review", description="Approve or reject pending templates and /teach entries")
    async def review(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        view = ReviewView(ctx, interaction.user.id)
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)

    @app_commands.command(name="export", description="Download the changed settings as a JSON file")
    async def export(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        data = io.BytesIO(ctx.settings.export_json().encode("utf-8"))
        await interaction.response.send_message("Settings export (only values that differ from the defaults):", file=discord.File(data, "navi-settings.json"), ephemeral=True)

    @app_commands.command(name="import", description="Load settings from a JSON export")
    @app_commands.describe(file="A file produced by /admin export")
    async def import_cmd(self, interaction: discord.Interaction, file: discord.Attachment) -> None:
        ctx = interaction.client.ctx
        if file.size > 200_000:
            await interaction.response.send_message("That file is too large for a settings export.", ephemeral=True)
            return
        text = (await file.read()).decode("utf-8", errors="replace")
        applied, errors = ctx.settings.import_json(text, by=interaction.user.id)
        lines = [f"Imported **{len(applied)}** setting(s)."] + [f"❌ {e}" for e in errors[:15]]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # ------------------------------------------------------------------ users
    user = app_commands.Group(name="user", description="Per-user tools")

    @user.command(name="points", description="Set, add or subtract a user's Boli (recorded in the ledger as 'admin')")
    @app_commands.choices(operation=[app_commands.Choice(name="set", value="set"), app_commands.Choice(name="add", value="add"), app_commands.Choice(name="subtract", value="subtract")])
    async def user_points(self, interaction: discord.Interaction, user: discord.Member, operation: str, amount: int) -> None:
        ctx = interaction.client.ctx
        if get_user_profile(ctx.db, user.id) is None:
            upsert_user(ctx.db, user.id, user.display_name)
        old = get_user_profile(ctx.db, user.id)["boli_points"]
        new = amount if operation == "set" else old + amount if operation == "add" else old - amount
        award(ctx.db, user.id, new - old, reason="admin", detail=json.dumps({"op": operation, "by": interaction.user.id}), log_only=True)
        await interaction.response.send_message(f"**{user.display_name}**: {old} → **{new}** Boli ({operation} {amount}).", ephemeral=True)

    @user.command(name="strikes_reset", description="Reset strikes for one user, or for everyone if no user is given")
    async def user_strikes_reset(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        ctx = interaction.client.ctx
        if user is not None:
            reset_user_strikes(ctx.db, user.id)
            text = f"Strikes reset for **{user.display_name}**."
        else:
            text = f"Strikes reset for **{reset_all_strikes(ctx.db)}** user(s)."
        await interaction.response.send_message(text, ephemeral=True)

    @user.command(name="game_attempts_reset", description="Clear today's play counts for a user")
    @app_commands.choices(game=[app_commands.Choice(name="Gambling (all)", value="gambling"), app_commands.Choice(name="All games", value="all")])
    async def user_game_attempts_reset(self, interaction: discord.Interaction, user: discord.Member, game: str) -> None:
        ctx = interaction.client.ctx
        reset_gambling_count(ctx.db, user.id)
        if game == "all":
            for name in ("type_race", "navi_challenge"):
                reset_gemini_game_count(ctx.db, user.id, name)
        await interaction.response.send_message(f"Today's **{game}** attempts cleared for **{user.display_name}**.", ephemeral=True)

    # ------------------------------------------------------------------ /teach approvals
    teach = app_commands.Group(name="teach", description="Who may use /teach")

    @teach.command(name="allow", description="Let a user add knowledge with /teach (entries wait for review)")
    async def teach_allow(self, interaction: discord.Interaction, user: discord.Member) -> None:
        ctx = interaction.client.ctx
        grant(ctx.db, user.id, "teach", interaction.user.id)
        await interaction.response.send_message(f"✅ **{user.display_name}** may now use /teach.", ephemeral=True)

    @teach.command(name="revoke", description="Remove a user's /teach permission")
    async def teach_revoke(self, interaction: discord.Interaction, user: discord.Member) -> None:
        ctx = interaction.client.ctx
        removed = revoke(ctx.db, user.id, "teach")
        await interaction.response.send_message(f"{'Removed' if removed else 'No /teach permission found for'} **{user.display_name}**.", ephemeral=True)

    @teach.command(name="list", description="List users who may use /teach")
    async def teach_list(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        ids = list_permission(ctx.db, "teach")
        await interaction.response.send_message("Approved teachers: " + (", ".join(f"<@{i}>" for i in ids) if ids else "none"), ephemeral=True)


class AdminCog(commands.Cog):
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._added: list = []

    async def cog_load(self) -> None:
        group = AdminGroup()
        self.ctx.bot.tree.add_command(group)
        self._added.append(group)

    async def cog_unload(self) -> None:
        for cmd in self._added:
            self.ctx.bot.tree.remove_command(cmd.name, type=cmd.type)


async def setup(bot) -> None:
    await bot.add_cog(AdminCog(bot.ctx))
