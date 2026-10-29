# navi/db/migrations/m0001_baseline.py - the pre-v2 schema (was schema._create_tables).
#
# Kept as Python rather than .sql: it is idempotent (CREATE IF NOT EXISTS), contains conditional ALTERs for
# databases created by older versions, and seeds default config rows. Converting it to plain SQL would risk
# changing behaviour on existing databases. Phase 3 adds 0002_v2.sql on top of it.
from __future__ import annotations

import logging
import sqlite3

from navi.db.repos.market import _seed_market_items

logger = logging.getLogger("navi.db.migrations")


def apply(conn: sqlite3.Connection) -> None:
    """Create every legacy table, run the in-place ALTERs and seed defaults. Idempotent."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions_cache (
            id          INTEGER PRIMARY KEY,
            cache_type  TEXT NOT NULL,
            user_id     INTEGER,
            original_prompt TEXT,
            template_text   TEXT NOT NULL,
            timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id         INTEGER PRIMARY KEY,
            username        TEXT NOT NULL,
            rashi           TEXT,
            boli_points     INTEGER DEFAULT 0,
            experience      INTEGER DEFAULT 0,
            last_seen       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            prediction_count INTEGER DEFAULT 0,
            extra_actions   INTEGER DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS gift_log (
            id          INTEGER PRIMARY KEY,
            sender_id   INTEGER NOT NULL,
            recipient_id INTEGER NOT NULL,
            amount      INTEGER NOT NULL,
            gifted_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS partner_score_log (
            id              INTEGER PRIMARY KEY,
            game_id         TEXT NOT NULL UNIQUE,
            user_id         INTEGER NOT NULL,
            guild_id        INTEGER NOT NULL,
            username        TEXT NOT NULL,
            raw_points      INTEGER NOT NULL,
            boli_awarded    INTEGER NOT NULL,
            xp_awarded      INTEGER NOT NULL,
            game_type       TEXT DEFAULT 'default',
            received_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS external_boli_points (
            id          INTEGER PRIMARY KEY,
            user_id     INTEGER NOT NULL,
            username    TEXT NOT NULL,
            points      INTEGER NOT NULL,
            source_game TEXT DEFAULT 'partner',
            game_id     TEXT,
            awarded_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_ext_boli_user ON external_boli_points (user_id)")

    # View: combined native + external boli for leaderboard / profile display.
    # Drop-and-recreate so schema changes take effect on restart.
    conn.execute("DROP VIEW IF EXISTS boli_totals_view")
    conn.execute("""
        CREATE VIEW boli_totals_view AS
        SELECT
            u.user_id,
            u.username,
            u.rashi,
            u.prediction_count,
            u.experience,
            u.boli_points                                              AS native_boli_points,
            COALESCE((
                SELECT SUM(e.points) FROM external_boli_points e WHERE e.user_id = u.user_id
            ), 0)                                                      AS external_boli_points,
            u.boli_points + COALESCE((
                SELECT SUM(e.points) FROM external_boli_points e WHERE e.user_id = u.user_id
            ), 0)                                                      AS total_boli_points
        FROM user_stats u
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_items (
            item_id       TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            emoji         TEXT NOT NULL,
            base_price    INTEGER NOT NULL,
            current_price INTEGER NOT NULL,
            volatility    TEXT DEFAULT 'medium',
            description   TEXT,
            last_updated  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_holdings (
            id             INTEGER PRIMARY KEY,
            user_id        INTEGER NOT NULL,
            item_id        TEXT NOT NULL,
            quantity       INTEGER NOT NULL DEFAULT 1,
            purchase_price INTEGER NOT NULL,
            purchased_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at     TIMESTAMP NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_price_history (
            id          INTEGER PRIMARY KEY,
            item_id     TEXT NOT NULL,
            price       INTEGER NOT NULL,
            recorded_at DATE NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_prediction_history (
            id          INTEGER PRIMARY KEY,
            user_id     INTEGER NOT NULL,
            prediction_text TEXT NOT NULL,
            timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS curse_logs (
            id          INTEGER PRIMARY KEY,
            user_id     INTEGER NOT NULL,
            username    TEXT NOT NULL,
            curse_used  TEXT NOT NULL,
            timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_omens (
            id              INTEGER PRIMARY KEY,
            generated_text  TEXT NOT NULL,
            landmark        TEXT NOT NULL,
            omen_date       DATE NOT NULL UNIQUE
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_config (
            key TEXT PRIMARY KEY,
            value_str TEXT,
            value_float REAL,
            value_int INTEGER
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_perks (
            user_id     INTEGER NOT NULL,
            perk_type   TEXT NOT NULL,
            expires_at  TIMESTAMP NOT NULL,
            PRIMARY KEY (user_id, perk_type)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS local_knowledge (
            id          INTEGER PRIMARY KEY,
            category    TEXT NOT NULL,
            term        TEXT NOT NULL,
            description TEXT NOT NULL,
            tags        TEXT DEFAULT ''
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_emojis (
            emoji_id    TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            last_used   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            original_id TEXT,
            animated    INTEGER DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS local_media (
            shortcut    TEXT PRIMARY KEY,
            user_id     INTEGER NOT NULL,
            file_path   TEXT NOT NULL,
            media_type  TEXT NOT NULL,
            source_url  TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS bless_logs (
            id          INTEGER PRIMARY KEY,
            user_id     INTEGER NOT NULL,
            username    TEXT NOT NULL,
            bless_used  TEXT NOT NULL,
            timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Per-game daily play counts (Feature: gambling decoupled from cosmic actions)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS game_daily_counts (
            user_id     INTEGER NOT NULL,
            game_name   TEXT NOT NULL,
            play_date   DATE NOT NULL,
            play_count  INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, game_name, play_date)
        )
    """)

    # Gemini-powered mini-games (2 attempts per user per day each)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS navi_challenge_attempts (
            user_id    INTEGER NOT NULL,
            play_date  DATE NOT NULL,
            play_count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, play_date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS type_race_attempts (
            user_id    INTEGER NOT NULL,
            play_date  DATE NOT NULL,
            play_count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, play_date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gemini_score_comments (
            id           INTEGER PRIMARY KEY,
            game_type    TEXT NOT NULL,
            score_bucket INTEGER NOT NULL,
            comment      TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS testing_guilds (
            guild_id INTEGER PRIMARY KEY
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS movie_dialogues (
            id       INTEGER PRIMARY KEY,
            dialogue TEXT NOT NULL UNIQUE
        )
    """)

    # Analytics tables
    conn.execute("""
        CREATE TABLE IF NOT EXISTS command_events (
            id          INTEGER PRIMARY KEY,
            user_id     INTEGER NOT NULL,
            username    TEXT NOT NULL,
            command     TEXT NOT NULL,
            subcommand  TEXT,
            channel_id  INTEGER,
            guild_id    INTEGER,
            latency_ms  INTEGER,
            used_cache  INTEGER DEFAULT 0,
            timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_events (
            id          INTEGER PRIMARY KEY,
            event_type  TEXT NOT NULL,
            detail      TEXT,
            timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_call_log (
            id          INTEGER PRIMARY KEY,
            key_used    TEXT NOT NULL,
            cache_hit   INTEGER DEFAULT 0,
            command     TEXT,
            latency_ms  INTEGER,
            error       TEXT,
            timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Carry over the cooldown setting stored under its pre-rename key
    conn.execute("UPDATE bot_config SET key = 'navi_cooldown_seconds' WHERE key = ? AND NOT EXISTS (SELECT 1 FROM bot_config WHERE key = 'navi_cooldown_seconds')", ("astro" + "_cooldown_seconds",))

    # Insert default config if empty
    conn.execute("""
        INSERT INTO bot_config (key, value_float, value_int)
        SELECT 'navi_cooldown_seconds', NULL, 60
        WHERE NOT EXISTS (SELECT 1 FROM bot_config WHERE key = 'navi_cooldown_seconds');
    """)
    conn.execute("""
        INSERT INTO bot_config (key, value_float)
        SELECT 'cache_reuse_chance', 0.50
        WHERE NOT EXISTS (SELECT 1 FROM bot_config WHERE key = 'cache_reuse_chance');
    """)
    conn.execute("""
        INSERT INTO bot_config (key, value_float)
        SELECT 'kochi_reply_chance', 0.28
        WHERE NOT EXISTS (SELECT 1 FROM bot_config WHERE key = 'kochi_reply_chance');
    """)
    conn.execute("""
        INSERT INTO bot_config (key, value_float)
        SELECT 'curse_reply_chance', 0.25
        WHERE NOT EXISTS (SELECT 1 FROM bot_config WHERE key = 'curse_reply_chance');
    """)
    # Feature on/off flags (1 = enabled, 0 = disabled)
    for flag in (
        "feature_kochi_replies", "feature_curse_replies", "feature_boli_points",
        "feature_welcome", "feature_navi", "feature_vibe_check", "feature_kanmanilla",
        "feature_audit", "feature_mod_tldr", "feature_link_summary", "feature_strikes",
        "feature_navi_challenge", "feature_type_race",
    ):
        conn.execute(f"""
            INSERT INTO bot_config (key, value_int)
            SELECT '{flag}', 1
            WHERE NOT EXISTS (SELECT 1 FROM bot_config WHERE key = '{flag}');
        """)
    # Master kill switch — default OFF (0 = bot is alive)
    conn.execute("""
        INSERT INTO bot_config (key, value_int)
        SELECT 'master_killswitch', 0
        WHERE NOT EXISTS (SELECT 1 FROM bot_config WHERE key = 'master_killswitch');
    """)

    conn.execute("""
        INSERT INTO bot_config (key, value_int)
        SELECT 'local_media_max_per_user', 20
        WHERE NOT EXISTS (SELECT 1 FROM bot_config WHERE key = 'local_media_max_per_user');
    """)
    conn.execute("""
        INSERT INTO bot_config (key, value_int)
        SELECT 'local_media_max_global', 200
        WHERE NOT EXISTS (SELECT 1 FROM bot_config WHERE key = 'local_media_max_global');
    """)

    # Emoji for link-summary reaction (Feature 3)
    conn.execute("""
        INSERT INTO bot_config (key, value_str)
        SELECT 'link_summary_emoji', '📰'
        WHERE NOT EXISTS (SELECT 1 FROM bot_config WHERE key = 'link_summary_emoji');
    """)

    # Safe ALTER TABLE migrations — SQLite does not support IF NOT EXISTS on ALTER TABLE
    for col_sql in (
        "ALTER TABLE user_stats ADD COLUMN strikes INTEGER DEFAULT 0",
        "ALTER TABLE user_stats ADD COLUMN daily_action_count INTEGER DEFAULT 0",
        "ALTER TABLE user_stats ADD COLUMN last_action_date DATE",
        "ALTER TABLE user_stats ADD COLUMN extra_actions INTEGER DEFAULT 0",
        # Tiered action refill tracking (Feature: tiered shop pricing)
        "ALTER TABLE user_stats ADD COLUMN daily_refill_count INTEGER DEFAULT 0",
        "ALTER TABLE user_stats ADD COLUMN last_refill_date DATE",
        # local_media: extended storage type support
        "ALTER TABLE local_media ADD COLUMN storage_type TEXT DEFAULT 'local'",
        "ALTER TABLE local_media ADD COLUMN discord_id TEXT",
        "ALTER TABLE local_media ADD COLUMN discord_name TEXT",
        "ALTER TABLE local_media ADD COLUMN animated INTEGER DEFAULT 0",
        # Feature 2: decouple XP from Boli Points
        "ALTER TABLE user_stats ADD COLUMN experience INTEGER DEFAULT 0",
    ):
        try:
            conn.execute(col_sql)
        except Exception:
            pass  # column already exists

    # Seed experience from existing boli_points for all users who haven't been migrated yet
    conn.execute("""
        UPDATE user_stats SET experience = boli_points
        WHERE experience = 0 AND boli_points > 0
    """)

    # Fastest Fingers First results
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fff_scores (
            id INTEGER PRIMARY KEY,
            game_id TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            correct_answers INTEGER NOT NULL,
            total_questions INTEGER NOT NULL,
            avg_response_ms INTEGER,
            boli_awarded INTEGER NOT NULL,
            played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fff_user ON fff_scores (user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fff_guild ON fff_scores (guild_id)")

    # Survival Mode results
    conn.execute("""
        CREATE TABLE IF NOT EXISTS survival_scores (
            id INTEGER PRIMARY KEY,
            game_id TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            streak INTEGER NOT NULL,
            difficulty TEXT NOT NULL,
            category TEXT,
            boli_awarded INTEGER NOT NULL,
            played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_surv_user ON survival_scores (user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_surv_guild ON survival_scores (guild_id)")

    # Seed market items if table is empty
    _seed_market_items(conn)

    conn.commit()
