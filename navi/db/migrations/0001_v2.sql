-- navi/db/migrations/0001_v2.sql - the v2 data model (16 tables + schema_version).
-- Fresh databases get exactly this. Databases in the pre-v2 layout are converted by tools/migrate_v2.py
-- into a NEW file; the bot refuses to start on a pre-v2 file.
--
-- Differences from the spec DDL: media has a media_type column (emoji | sticker, used by the pickers);
-- the unique content key index excludes score_comment rows (several comments per score bucket are allowed).

CREATE TABLE IF NOT EXISTS users (
  user_id          INTEGER PRIMARY KEY,
  display_name     TEXT    NOT NULL,
  rashi            TEXT,
  boli_points      INTEGER NOT NULL DEFAULT 0,   -- native balance
  partner_points   INTEGER NOT NULL DEFAULT 0,   -- partner pool balance
  experience       INTEGER NOT NULL DEFAULT 0,
  strikes          INTEGER NOT NULL DEFAULT 0,
  prediction_count INTEGER NOT NULL DEFAULT 0,
  extra_actions    INTEGER NOT NULL DEFAULT 0,
  first_seen       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS daily_counters (
  user_id INTEGER NOT NULL,
  day     TEXT    NOT NULL,          -- IST date YYYY-MM-DD
  counter TEXT    NOT NULL,          -- cosmic_action | refill | game:<name> | llm_game:<name> | qa ...
  value   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, day, counter)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS points_ledger (
  id              INTEGER PRIMARY KEY,
  user_id         INTEGER NOT NULL,
  pool            TEXT    NOT NULL DEFAULT 'native',   -- native | partner
  delta           INTEGER NOT NULL,                    -- 0 allowed (history-only rows)
  xp_delta        INTEGER NOT NULL DEFAULT 0,
  reason          TEXT    NOT NULL,
  counterparty_id INTEGER,
  detail          TEXT,
  ref             TEXT,               -- idempotency key (partner game_id)
  created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_ledger_user_time   ON points_ledger(user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_ledger_reason_time ON points_ledger(reason, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ledger_ref  ON points_ledger(reason, ref) WHERE ref IS NOT NULL;

CREATE TABLE IF NOT EXISTS market_items (
  item_id TEXT PRIMARY KEY, name TEXT NOT NULL, emoji TEXT NOT NULL,
  base_price INTEGER NOT NULL, current_price INTEGER NOT NULL,
  volatility TEXT NOT NULL DEFAULT 'medium', description TEXT,
  last_updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS holdings (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
  item_id TEXT NOT NULL REFERENCES market_items(item_id),
  quantity INTEGER NOT NULL DEFAULT 1, purchase_price INTEGER NOT NULL,
  purchased_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, expires_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_holdings_user ON holdings(user_id);

CREATE TABLE IF NOT EXISTS market_prices (
  id INTEGER PRIMARY KEY, item_id TEXT NOT NULL REFERENCES market_items(item_id),
  price INTEGER NOT NULL, recorded_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_prices_item_time ON market_prices(item_id, recorded_at);

CREATE TABLE IF NOT EXISTS perks (
  user_id INTEGER NOT NULL, perk TEXT NOT NULL, expires_at TEXT NOT NULL,
  PRIMARY KEY (user_id, perk)) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS media (
  shortcut TEXT PRIMARY KEY, owner_id INTEGER NOT NULL,
  storage_type TEXT NOT NULL,       -- local | s3 | native_emoji | app_emoji | app_emoji_sticker | native_sticker
  media_type TEXT NOT NULL DEFAULT 'emoji',     -- emoji | sticker
  location TEXT, discord_id TEXT, discord_name TEXT,
  animated INTEGER NOT NULL DEFAULT 0, source_url TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS app_emojis (
  emoji_id TEXT PRIMARY KEY, name TEXT NOT NULL, original_id TEXT,
  animated INTEGER NOT NULL DEFAULT 0, last_used TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS game_results (
  id INTEGER PRIMARY KEY, game TEXT NOT NULL, user_id INTEGER NOT NULL,
  guild_id INTEGER, game_id TEXT, score INTEGER NOT NULL,
  details TEXT,                     -- JSON: total_questions, avg_response_ms, difficulty, category, boli_awarded
  played_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (game, game_id));
CREATE INDEX IF NOT EXISTS ix_results_board ON game_results(game, guild_id, score DESC);
CREATE INDEX IF NOT EXISTS ix_results_user  ON game_results(user_id);

CREATE TABLE IF NOT EXISTS prediction_history (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, text TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_predhist_user ON prediction_history(user_id, created_at);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL,   -- command | session | llm_call | safety_reject | setting_change
  user_id INTEGER, guild_id INTEGER, channel_id INTEGER,
  name TEXT, detail TEXT, latency_ms INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_events_kind_time ON events(kind, created_at);
CREATE INDEX IF NOT EXISTS ix_events_user      ON events(user_id);

CREATE TABLE IF NOT EXISTS content (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,               -- prediction | curse_back | score_comment | movie_dialogue | qa_answer
  key  TEXT,                        -- score comments: '<game>:<bucket>'; qa_answer: normalised question
  text TEXT NOT NULL,               -- templates keep {user} / {curse} placeholders
  status TEXT NOT NULL DEFAULT 'active',   -- active | pending | rejected
  source TEXT NOT NULL,             -- seed | llm | admin | migrated
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_by INTEGER, reviewed_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ux_content_kind_key  ON content(kind, key) WHERE key IS NOT NULL AND kind != 'score_comment';
CREATE UNIQUE INDEX IF NOT EXISTS ux_content_kind_text ON content(kind, text);
CREATE INDEX IF NOT EXISTS ix_content_kind_status      ON content(kind, status);

CREATE TABLE IF NOT EXISTS knowledge (
  id INTEGER PRIMARY KEY, category TEXT NOT NULL, term TEXT NOT NULL,
  description TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',  -- active | pending | rejected
  submitted_by INTEGER, approved_by INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (category, term));

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY, value TEXT NOT NULL,   -- JSON-encoded
  updated_by INTEGER, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS permissions (
  user_id INTEGER NOT NULL, permission TEXT NOT NULL,
  granted_by INTEGER NOT NULL, granted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, permission)) WITHOUT ROWID;
