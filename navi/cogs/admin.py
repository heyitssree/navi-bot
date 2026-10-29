# navi/cogs/admin.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from navi.context import AppContext
from navi.db.connection import DB_PATH
from navi.db.repos.counters import reset_gambling_count, reset_gemini_game_count
from navi.db.repos.events import get_health_stats, get_table_counts
from navi.db.repos.settings import get_all_configs, set_config_float, set_config_int, set_config_str, set_testing_guild
from navi.db.repos.users import get_user_profile, reset_all_strikes
from navi.services.points import set_user_points, update_boli_points

logger = logging.getLogger("navi.cogs.admin")


class AdminGroup(app_commands.Group):
    """Admin controls — visible and usable only by the bot owner."""
    def __init__(self):
        super().__init__(
            name="admin",
            description="Navi owner configuration controls",
            default_permissions=discord.Permissions(administrator=True),
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Primary guard: hardcoded owner ID from .env (fast, no API call)
        ctx = interaction.client.ctx
        if ctx.config.owner_id and interaction.user.id == ctx.config.owner_id:
            return True
        # Fallback: check against Discord's application owner (slower but safe)
        app_info = await ctx.bot.application_info()
        if interaction.user.id == app_info.owner.id:
            return True
        # Deny everyone else — ephemeral so it's not publicly embarrassing
        await interaction.response.send_message(
            "Admin commands are owner-only.", ephemeral=True
        )
        return False

    @app_commands.command(name="set_cooldown", description="Set anti-spam cooldown in seconds")
    async def set_cooldown(self, interaction: discord.Interaction, seconds: int) -> None:
        ctx = interaction.client.ctx
        set_config_int(ctx.db, "navi_cooldown_seconds", seconds)
        await interaction.response.send_message(f"Spam cooldown set to **{seconds} seconds**.", ephemeral=True)

    @app_commands.command(name="toggle_killswitch", description="Toggle Free-Only API mode (circuit breaker bypass)")
    async def toggle_killswitch(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        ctx.llm.free_only = not ctx.llm.free_only
        status = "ON 🔴 (Free API + Cache only)" if ctx.llm.free_only else "OFF 🟢 (Paid Fallback enabled)"
        await interaction.response.send_message(f"Killswitch is now **{status}**.", ephemeral=True)

    @app_commands.command(name="killswitch", description="Toggle the master kill switch — completely silences the bot")
    async def master_killswitch_cmd(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        new_state = 0 if ctx.settings.feat("master_killswitch") else 1
        ctx.settings.set_feature("master_killswitch", new_state)
        if new_state:
            await interaction.response.send_message(
                "☠️ **Master Kill Switch: ON.** Bot is now silent. Use `/admin killswitch` to re-enable.",
                ephemeral=True,
            )
            logger.warning("MASTER KILL SWITCH ACTIVATED by %s", interaction.user.display_name)
        else:
            await interaction.response.send_message(
                "✅ **Master Kill Switch: OFF.** Bot is back online.",
                ephemeral=True,
            )
            logger.info("Master kill switch deactivated by %s", interaction.user.display_name)

    @app_commands.command(name="toggle_feature", description="Enable or disable a bot feature")
    @app_commands.describe(feature="Feature to toggle", enabled="Turn it on (True) or off (False)")
    @app_commands.choices(feature=[
        app_commands.Choice(name="Navi Predictions", value="feature_navi"),
        app_commands.Choice(name="Curses & Blessings (navi/chunk)", value="feature_curses"),
        app_commands.Choice(name="Gambling (/flip, /roll_dice, /roulette, /slots)", value="feature_gambling"),
        app_commands.Choice(name="Local Media Shortcuts (;;name)", value="feature_local_media"),
        app_commands.Choice(name="Boli Points Tracking", value="feature_boli_points"),
        app_commands.Choice(name="Kochi Slang Detection", value="feature_kochi_replies"),
        app_commands.Choice(name="Passive Curse Replies", value="feature_curse_replies"),
        app_commands.Choice(name="Vibe Check (auto de-escalation)", value="feature_vibe_check"),
        app_commands.Choice(name="Link Summary (emoji reaction)", value="feature_link_summary"),
        app_commands.Choice(name="Kanmanilla (missing person)", value="feature_kanmanilla"),
        app_commands.Choice(name="Welcome Messages", value="feature_welcome"),
        app_commands.Choice(name="Temp VC Generator (/temp_vc)", value="feature_temp_vc"),
        app_commands.Choice(name="Mod Audit (/audit)", value="feature_audit"),
        app_commands.Choice(name="Mod TL;DR (/mod_tldr)", value="feature_mod_tldr"),
        app_commands.Choice(name="3-Strike System", value="feature_strikes"),
        # app_commands.Choice(name="Navi Challenge (/navi_challenge)", value="feature_navi_challenge"),  # DISABLED
        # app_commands.Choice(name="Type Race (/type_race)", value="feature_type_race"),  # DISABLED
    ])
    async def toggle_feature(
        self, interaction: discord.Interaction,
        feature: str,
        enabled: bool,
    ) -> None:
        ctx = interaction.client.ctx
        ctx.settings.set_feature(feature, 1 if enabled else 0)
        label = feature.replace("feature_", "").replace("_", " ").title()
        state = "ENABLED ✅" if enabled else "DISABLED ❌"
        await interaction.response.send_message(
            f"**{label}** is now **{state}**.", ephemeral=True
        )

    @app_commands.command(name="testing", description="Toggle testing mode for this server — bypasses rate limits, disables Boli/XP rewards")
    async def testing_cmd(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("Must be used inside a server.", ephemeral=True)
            return
        currently_on = guild_id in ctx.settings.testing_guild_ids
        new_state = not currently_on
        set_testing_guild(ctx.db, guild_id, new_state)
        if new_state:
            ctx.settings.testing_guild_ids.add(guild_id)
        else:
            ctx.settings.testing_guild_ids.discard(guild_id)
        guild_name = interaction.guild.name if interaction.guild else str(guild_id)
        if new_state:
            await interaction.response.send_message(
                f"🧪 **Testing mode ON** for **{guild_name}**.\n"
                f"Rate limits are suspended for `/type_race` and `/navi_challenge`. "
                f"No Boli or XP will be awarded while this is active.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"✅ **Testing mode OFF** for **{guild_name}**.\n"
                f"Normal rate limits and rewards are restored.",
                ephemeral=True,
            )
        logger.info(
            "Testing mode %s for guild %s (%d) by %s",
            "ON" if new_state else "OFF", guild_name, guild_id, interaction.user.display_name,
        )

    @app_commands.command(name="set_chance", description="Set the probability (0.0–1.0) for a specific behaviour")
    @app_commands.describe(feature="Which probability to adjust", value="New value between 0.0 and 1.0")
    @app_commands.choices(feature=[
        app_commands.Choice(name="Cache Reuse (navi predictions)", value="cache_reuse_chance"),
        app_commands.Choice(name="Kochi Slang Reply", value="kochi_reply_chance"),
        app_commands.Choice(name="Passive Curse Reply", value="curse_reply_chance"),
        app_commands.Choice(name="Universal Blessing (5% default)", value="universal_blessing_chance"),
        app_commands.Choice(name="Curse Backfire — Mild tier (10% default)", value="backfire_chance_mild"),
        app_commands.Choice(name="Curse Backfire — Moderate tier (15% default)", value="backfire_chance_moderate"),
        app_commands.Choice(name="Curse Backfire — Severe tier (20% default)", value="backfire_chance_severe"),
    ])
    async def set_chance(
        self, interaction: discord.Interaction,
        feature: str,
        value: float,
    ) -> None:
        ctx = interaction.client.ctx
        if not 0.0 <= value <= 1.0:
            await interaction.response.send_message("Value must be between 0.0 and 1.0.", ephemeral=True)
            return
        set_config_float(ctx.db, feature, value)
        label = feature.replace("_", " ").title()
        await interaction.response.send_message(
            f"**{label}** set to **{value:.0%}**.", ephemeral=True
        )

    @app_commands.command(name="set_summary_emoji", description="Set the emoji that triggers link summarisation (default: 📰)")
    @app_commands.describe(emoji="The emoji to use for link summary reactions")
    async def set_summary_emoji(self, interaction: discord.Interaction, emoji: str) -> None:
        ctx = interaction.client.ctx
        set_config_str(ctx.db, "link_summary_emoji", emoji.strip())
        await interaction.response.send_message(
            f"Link summary emoji set to **{emoji.strip()}**. React with it on any message containing a URL to get a summary.",
            ephemeral=True,
        )

    @app_commands.command(name="set_points", description="Manually set Boli Points for a user (for data restore)")
    @app_commands.describe(user="The member to update", points="Boli Points to set", readings="Prediction count to set", rashi="Rashi to assign (optional)")
    async def set_points_cmd(self, interaction: discord.Interaction, user: discord.Member, points: int, readings: int = 0, rashi: str | None = None) -> None:
        ctx = interaction.client.ctx
        set_user_points(ctx.db, user.id, user.display_name, points, prediction_count=readings, rashi=rashi)
        rashi_str = f" · Rashi: {rashi}" if rashi else ""
        await interaction.response.send_message(
            f"✅ **{user.display_name}** → 🍮 **{points} Boli Points** · {readings} readings{rashi_str}",
            ephemeral=True,
        )
        logger.info("Manual point restore: %s → %d pts, %d readings", user.display_name, points, readings)

    @app_commands.command(name="adjust_points", description="Add or subtract Boli Points for a user")
    @app_commands.describe(
        user="The member to adjust points for",
        operation="Add or subtract points",
        amount="How many points (1–10000)",
    )
    @app_commands.choices(operation=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Subtract", value="subtract"),
    ])
    async def adjust_points_cmd(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        operation: str,
        amount: app_commands.Range[int, 1, 10000],
    ) -> None:
        ctx = interaction.client.ctx
        delta = amount if operation == "add" else -amount
        profile = get_user_profile(ctx.db, user.id)
        old_pts = profile["boli_points"] if profile else 0
        update_boli_points(ctx.db, user.id, delta)
        new_pts = old_pts + delta
        sign = f"+{amount}" if operation == "add" else f"-{amount}"
        await interaction.response.send_message(
            f"✅ **{user.display_name}**: {sign} Boli Points → now 🍮 **{new_pts}** pts",
            ephemeral=True,
        )
        logger.info(
            "Manual point adjustment: %s %s%d pts (was %d, now %d) by %s",
            user.display_name, "+" if operation == "add" else "-", amount,
            old_pts, new_pts, interaction.user.display_name,
        )

    @app_commands.command(name="reset_all_strikes", description="Reset every user's strike count to 0")
    async def reset_all_strikes_cmd(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        affected = reset_all_strikes(ctx.db)
        await interaction.response.send_message(
            f"✅ All strikes cleared. **{affected}** user(s) had their strike count reset to 0.",
            ephemeral=True,
        )
        logger.info("reset_all_strikes executed by %s — %d users affected", interaction.user.display_name, affected)

    @app_commands.command(name="config_view", description="View all active feature flags, probabilities, and cooldowns")
    async def config_view(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        configs = get_all_configs(ctx.db)
        embed = discord.Embed(title="⚙️ Navi Configuration", color=discord.Color.dark_grey())

        # API mode
        embed.add_field(
            name="🔌 API Mode",
            value=f"Free-Only (Killswitch): **{'ON 🔴' if ctx.llm.free_only else 'OFF 🟢'}**",
            inline=False,
        )

        # Feature flags
        flags = {k: v for k, v in configs.items() if k.startswith("feature_")}
        if flags:
            flag_lines = []
            for k, v in sorted(flags.items()):
                label = k.replace("feature_", "").replace("_", " ").title()
                icon = "✅" if v else "❌"
                flag_lines.append(f"{icon} {label}")
            embed.add_field(name="🎛️ Feature Flags", value="\n".join(flag_lines), inline=False)

        # Probabilities — show db value or fallback default
        _PROB_DEFAULTS = {
            "cache_reuse_chance":      ("Cache Reuse (navi)",           None),
            "kochi_reply_chance":      ("Kochi Slang Reply",            0.28),
            "curse_reply_chance":      ("Passive Curse Reply",          0.25),
            "universal_blessing_chance": ("Universal Blessing",         0.05),
            "backfire_chance_mild":    ("Backfire — Mild tier",         0.10),
            "backfire_chance_moderate":("Backfire — Moderate tier",     0.15),
            "backfire_chance_severe":  ("Backfire — Severe tier",       0.20),
        }
        prob_keys = set(_PROB_DEFAULTS.keys())
        prob_lines = []
        for k, (label, default) in _PROB_DEFAULTS.items():
            v = configs.get(k)
            if v is not None:
                prob_lines.append(f"`{label}` → **{float(v):.0%}**")
            elif default is not None:
                prob_lines.append(f"`{label}` → **{default:.0%}** *(default)*")
        if prob_lines:
            embed.add_field(name="🎲 Probabilities", value="\n".join(prob_lines), inline=False)

        # Other settings
        other_keys = set(configs.keys()) - set(flags.keys()) - prob_keys
        other_lines = []
        for k in sorted(other_keys):
            if k.startswith("feature_"):
                continue
            other_lines.append(f"`{k}` → **{configs[k]}**")
        if other_lines:
            embed.add_field(name="⚙️ Other", value="\n".join(other_lines), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="partner_toggle", description="Enable or disable Boli/XP awards from the partner bot API")
    @app_commands.describe(enabled="True = awards ON, False = awards paused")
    async def partner_toggle_cmd(self, interaction: discord.Interaction, enabled: bool) -> None:
        ctx = interaction.client.ctx
        set_config_int(ctx.db, "feature_partner_api", int(enabled))
        status = "✅ **Enabled** — partner bot point awards are active." if enabled else "⛔ **Disabled** — partner bot submissions will be logged but no points awarded."
        await interaction.response.send_message(f"Partner API: {status}", ephemeral=True)
        logger.info("Partner API toggle: %s by %s", "ON" if enabled else "OFF", interaction.user.display_name)

    @app_commands.command(name="reset_game_attempts", description="Reset today's attempt count for a user in a mini-game")
    @app_commands.describe(
        user="The member whose attempts to reset",
        game="Which game's daily count to clear",
    )
    @app_commands.choices(game=[
        # app_commands.Choice(name="Type Race",       value="type_race"),      # DISABLED
        # app_commands.Choice(name="Navi Challenge",  value="navi_challenge"),  # DISABLED
        app_commands.Choice(name="Gambling (all)",  value="gambling"),
        app_commands.Choice(name="All Games",       value="all"),
    ])
    async def reset_game_attempts_cmd(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        game: str,
    ) -> None:
        ctx = interaction.client.ctx
        loop = asyncio.get_running_loop()
        if game in ("type_race", "all"):
            await loop.run_in_executor(
                None, lambda: reset_gemini_game_count(ctx.db, user.id, "type_race")
            )
        if game in ("navi_challenge", "all"):
            await loop.run_in_executor(
                None, lambda: reset_gemini_game_count(ctx.db, user.id, "navi_challenge")
            )
        if game in ("gambling", "all"):
            await loop.run_in_executor(
                None, lambda: reset_gambling_count(ctx.db, user.id)
            )
        game_label = {
            "type_race":       "Type Race",
            "navi_challenge":  "Navi Challenge",
            "gambling":        "Gambling (all games)",
            "all":             "Type Race + Navi Challenge + Gambling",
        }[game]
        await interaction.response.send_message(
            f"✅ **{user.display_name}**'s daily attempts reset for: **{game_label}**",
            ephemeral=True,
        )
        logger.info(
            "reset_game_attempts: %s → %s by %s",
            user.display_name, game, interaction.user.display_name,
        )


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

    @app_commands.command(name="health", description="Navi system health (owner only)")
    @app_commands.default_permissions(administrator=True)
    async def health_slash(self, interaction: discord.Interaction) -> None:
        ctx = self.ctx
        app_info = await ctx.bot.application_info()
        is_owner = bool(ctx.config.owner_id and interaction.user.id == ctx.config.owner_id) or interaction.user.id == app_info.owner.id
        if not is_owner:
            await interaction.response.send_message(
                "This command is owner-only.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        uptime_seconds = int((datetime.now(timezone.utc) - ctx.state.start_time).total_seconds())
        uptime_str = f"{uptime_seconds // 3600}h {(uptime_seconds % 3600) // 60}m {uptime_seconds % 60}s"

        gemini_status = rate_status = ctx.llm.status_dict()
        table_counts = get_table_counts(ctx.db)
        health = get_health_stats(ctx.db)

        # DB file size
        try:
            db_size_mb = DB_PATH.stat().st_size / (1024 * 1024)
            db_size_str = f"{db_size_mb:.2f} MB"
        except Exception:
            db_size_str = "N/A"

        # Unique users active in the in-memory rate-limit window
        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(seconds=60)
        active_in_window = sum(
            1 for timestamps in ctx.state.user_usage.values()
            if any(t > cutoff for t in timestamps)
        )

        embed = discord.Embed(
            title="🔧 Navi — Health Status",
            color=discord.Color.red() if gemini_status["circuit_open"] else discord.Color.green(),
        )

        # ── Uptime ──────────────────────────────────────────────────────────────
        embed.add_field(name="⏱️ Uptime", value=uptime_str, inline=False)

        # ── Gemini API ──────────────────────────────────────────────────────────
        embed.add_field(
            name="🔑 Gemini API Usage",
            value=(
                f"Free key: {'✅' if gemini_status['free_key_available'] else '❌'}\n"
                f"Paid key: {'✅' if gemini_status['paid_key_available'] else '❌'}\n"
                f"Active key: **{gemini_status['active_key']}**\n\n"
                f"**Lifetime Calls (Since Boot)**\n"
                f"Free: **{gemini_status['free_calls']}** ({gemini_status['free_pct']}%)\n"
                f"Paid: **{gemini_status['paid_calls']}** ({gemini_status['paid_pct']}%)\n"
                f"Fails: {gemini_status['failed_calls']}"
            ),
            inline=True,
        )

        # ── Circuit Breaker ─────────────────────────────────────────────────────
        embed.add_field(
            name="⚡ Circuit Breaker",
            value=(
                f"State: **{'OPEN 🔴' if gemini_status['circuit_open'] else 'CLOSED 🟢'}**\n"
                f"Failures: {gemini_status['failure_count']}/3\n"
                f"Opens until: {gemini_status['open_until']}"
            ),
            inline=True,
        )

        # ── Rate Limiter ────────────────────────────────────────────────────────
        embed.add_field(
            name="🚦 Rate Limiter",
            value=(
                f"Used: **{rate_status['rpm_used']}/{rate_status['rpm_limit']} RPM**\n"
                f"Window resets in: {rate_status['window_resets_in_seconds']}s\n"
                f"Users active in last 60s: **{active_in_window}**\n"
                f"Free Tier Mode: {'ON' if rate_status['free_tier_mode'] else 'OFF'}\n"
                f"Free-Only Killswitch: **{'ON 🔴' if ctx.llm.free_only else 'OFF 🟢'}**"
            ),
            inline=False,
        )

        # ── User Activity ───────────────────────────────────────────────────────
        embed.add_field(
            name="👥 User Activity",
            value=(
                f"Total registered: **{health['total_users']}**\n"
                f"Active today: **{health['active_today']}**\n"
                f"Active this week: **{health['active_week']}**\n"
                f"Total Boli Points in circulation: **{health['total_boli_points']:,}**\n"
                f"Top user: {health['top_user']}"
            ),
            inline=True,
        )

        # ── Prediction Activity ─────────────────────────────────────────────────
        cache_breakdown = " · ".join(
            f"{k}: {v}" for k, v in health["cache_by_type"].items()
        ) or "empty"
        embed.add_field(
            name="🔮 Predictions",
            value=(
                f"Generated today: **{health['predictions_today']}**\n"
                f"Cache pool: {cache_breakdown}"
            ),
            inline=True,
        )

        # ── Curse Log ───────────────────────────────────────────────────────────
        embed.add_field(
            name="🤬 Curses",
            value=(
                f"Today: **{health['curses_today']}**  |  All-time: **{health['curses_total']}**\n"
                f"Top word: {health['top_curse']}\n"
                f"Active Curse Protections: **{health['active_perks']}**"
            ),
            inline=False,
        )

        # ── SQLite ──────────────────────────────────────────────────────────────
        counts_str = "\n".join(f"  `{t}`: {n}" for t, n in table_counts.items())
        embed.add_field(
            name=f"🗄️ SQLite  ({db_size_str})",
            value=counts_str,
            inline=False,
        )

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(AdminCog(bot.ctx))
