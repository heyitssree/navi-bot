# Navi Bot v2 changelog

## Phase 0 - Baseline and safety net (branch `v2/phase-0-baseline`)

Base: `a0b480d` on `main`. The working folder was not a git repo; it was initialised with `origin` set to
github.com/heyitssree/navi-bot, and `git reset origin/main` showed zero differences in tracked files.

### Added
- `requirements-dev.txt`, `pyproject.toml` (pytest-asyncio + ruff config; no reformatting done).
- `tests/legacy/` characterisation tests (76 passing on unchanged code):
  curse maths per tier, protected/shielded bounce, self/reply curse, quota and extra-actions accounting, potion echo sign,
  bless caster share (min 1) and universal blessing, slang scorer, `_templatize`/`_personalise`, template variants,
  `points_for_level`/`get_level_from_points`, `get_navi_prediction` routing (1st/2nd/3rd+), `/summ` filtering,
  market price bounds, and an import smoke test (no network, no Discord login, no LLM call).
- `tools/db_report.py` (read-only row counts and aggregates).
- Dev setup: `data/dev/navi_dev.db` (SQLite backup of `data/navi.db`) and `DB_PATH=data/dev/navi_dev.db` set in the (uncommitted) `.env` itself.
  `.gitignore` now also covers `.env.*`, `*.db`, `data/dev/`, `data/local_media/`, `data/backups/`.

### Baseline report (`python -m tools.db_report`, dev copy)
28 tables. Row counts: user_stats 4, local_knowledge 85, bot_config 23, market_items 6, command_events 4,
curse_logs 2, bless_logs 1, session_events 1, all other tables 0.
Aggregates: users 4, native Boli sum -12, external Boli sum 0, experience sum 4, extra_actions 0, media 0.
Note: the copy of the database is small, so these are not production-scale numbers.

### Found, not fixed
- `set_config_float` / `set_config_int` only `UPDATE`. `backfire_chance_mild|moderate|severe` are never seeded in
  `bot_config`, so `/admin` edits to them are silent no-ops (the hardcoded tier defaults keep applying). (Phase 4 registry.)
- Confirmed spec 2.3: DB seed sets `feature_navi_challenge` and `feature_type_race` to 1 while `bot.py` defaults to 0.
- `/summ` passes `cache_type="qa"` (Phase 1 cacheable flag).
- Importing `bot.py` creates `logs/bot.log` and configures logging (side effect, not a network call).
- Python 3.14 emits sqlite3 default datetime adapter DeprecationWarnings from `schema.py` (cosmetic).

### Owner decision needed
- `pottan` is both a curse trigger and a Boli trigger word (unchanged, per spec).

### Not verified in this phase
- "Confirm the bot starts against the copy in the test server": needs a Discord token for the test bot in `.env`;
  not done here. Everything else in the gate was run locally.

## Phase 1 - Quick fixes (branch `v2/phase-1-fixes`)

### Done
- `curses.py` renamed to `curse_data.py` (imports in `bot.py`, `prompts.py`, tests updated).
- `duckdb` removed from `requirements.txt`; Dockerfile comment, README, `.env.example`, DEPLOYMENT/USAGE_GUIDE updated
  (README rewritten to match actual features; documents `LLM_MODEL`, `GEMINI_API_KEY_FREE/PAID`, `DB_PATH`, `PARTNER_BOT_API_KEY`, `API_SERVER_PORT`).
- Gemini model read from `LLM_MODEL` (default `gemini-3.5-flash-lite`); `GeminiService.verify_model()` runs at startup
  (`client.models.list()`), falls back to `gemini-3.8-flash`, logs the active model; `/health` data includes the model.
- Error classes replace the single circuit breaker (`services/gemini_service.py`, moves to `llm/router.py` in Phase 2):
  429 = per-key cooldown (server delay, else 20 s), not a breaker failure; 400/401/403/404 = config (ERROR log at most every 10 min,
  owner DM at most hourly, breaker opens at once); 5xx/timeouts/network = 3 in a row open it for 5 min, then one half-open probe.
- `cacheable` flag on `ApiManager.call`: only `/navi` predictions fall back to the template pool; all other calls return their own fallback.
- Word lists compiled once into single alternation regexes (longest first); results are identical to the old per-word loops
  (checked against the old implementation in tests, including list-order result for `contains_curse_word`).
- `last_seen` tracked in memory on every message, flushed with one `executemany` every 10 min and on shutdown;
  `/kanmanilla` reads the database first and only scans channels when there is no record.
- Dead code removed: `DAILY_OMEN_PROMPT_TEMPLATE`, `get_daily_omen_prompt`, `get_todays_omen`, `save_daily_omen`, and the seeds for
  `WEATHER_ALERT_TIME` / `reversal_chance_owner` (existing rows in live DBs are left; the `daily_omens` table drops in Phase 3).
  Grep confirmed no callers. The stale "daily omen" sections in USAGE_GUIDE/DEPLOYMENT were removed.
- `pottan` dual membership untouched.

### Tests
342 passing (`tests/legacy` unchanged + `tests/phase1`: classification, 429 cooldown, 404 single DM, breaker open/half-open/close,
model fallback, cacheable, matcher equivalence, last_seen flush, kanmanilla DB-first).

### Live check (Gemini, local)
`LLM_MODEL` default was found by `models.list()` for this key, but a real `generateContent` call returned
**403 PERMISSION_DENIED: "Your billing account has an outstanding balance"** on the free key. The new config path handled it as designed
(one ERROR log, breaker open, fallback text). Q&A therefore could not be confirmed end-to-end; settle the Google AI Studio billing and re-run.

### Design notes / found, not fixed
- Per the spec a config error opens the breaker immediately, so a failing free key also stops the (possibly healthy) paid key from being tried
  until the probe 5 minutes later. Say so if you would rather fall through to the paid key first.
- `discord.Client` never dispatches `on_close`; the existing shutdown backup in that handler never runs. The last_seen flush therefore also
  runs in a `finally` around `bot.run()`. Wiring the backup the same way is left for Phase 2.
- `user_stats.last_seen` is a TIMESTAMP column, so `sqlite3` returns `datetime` objects (PARSE_DECLTYPES); `get_last_seen` normalises to text.
- Not exercised here: Discord-side checks (a fake 404 sending one DM is covered by a unit test; the DM path itself needs the test server).

## Phase 2 - Package refactor, no behaviour change (branch `v2/phase-2-refactor`)

`bot.py` (5,200 lines), `schema.py` (2,570), `prompts.py`, `curses.py`, `api_server.py`, `services/` are gone.
Entry point is `python -m navi` (Dockerfile, Procfile, `navi.service`, README and docs updated). No file in `navi/` is over 600 lines
(largest: `cogs/llm_games.py` 582, the disabled Navi Challenge / Type Race code).

### Layout (as in spec section 6.1, with the differences listed below)
`navi/app.py` (build, events, named background tasks, shutdown), `context.py` (AppContext + RuntimeState), `config.py` (env + optional
SSM via `NAVI_SSM_PREFIX`), `settings/store.py`, `db/{connection,migrate}.py`, `db/migrations/`, `db/repos/{users,points,counters,content,
knowledge,market,media,games,events,perks,settings}.py`, `llm/{base,gemini,router,safety}.py` + `llm/prompts/`, `services/`, `handlers/`
(`pipeline.py` + 10 handlers), 11 cogs, `data/`, `api/partner.py`.

### How it was verified
- The Phase 0 characterisation tests were kept; only imports and the harness changed (`FakeUser`/`make_ctx` build an `AppContext` instead of
  monkeypatching module globals). The curse/bless/slang/prediction/summ assertions are unchanged and pass.
- `tests/fixtures/command_tree_baseline.json` is a snapshot of all 26 top-level slash commands/groups/context menus taken from the old
  `bot.py` (names, descriptions, options, choices, default permissions). The new tree is byte-identical (`test_slash_command_surface_is_unchanged`).
- `tests/fixtures/baseline_schema.json` is the DDL produced by the old `schema.py`; the new migration runner produces the identical schema and seeds.
  A copy of `data/dev/navi_dev.db` also migrates with no row loss.
- Architecture tests: no file over 600 lines, old monoliths gone, only `services/points.py` may call the balance-changing repo functions,
  no module-level mutable state in cogs/handlers/services (two read-only JSON caches allow-listed), every cog has `setup()`, pipeline order is fixed.
- `on_ready` wiring, message flow and shutdown are exercised against fakes (`tests/phase2/test_app_startup.py`).
- 509 tests pass. **Not done:** the manual smoke run of every slash command in the test server (needs a Discord token and server),
  and the live Gemini call (the billing 403 from Phase 1 was still returned when re-checked at the start of this phase).

### What changed beyond a pure move (all small, listed so nothing is silent)
- `LLMRouter` (+ `GeminiProvider`, `LLMRequest/Response/Error`) replaces `ApiManager` + `GeminiService`; the Phase 1 error-class rules and
  their tests moved over unchanged. 12 call sites now `await ctx.llm.generate(...)` (no more executor + lambda). Purposes: qa, vibe, summary,
  mod, prediction, template_batch. The RPM budget stays the old fixed 10/min window; the priority-yield rule exists but is off
  (`yield_below_fraction=0`) so behaviour is identical until Phase 4 exposes it. `safety.check_output` is a pass-through until Phase 5.
  `max_tokens` is not sent to Gemini (it would truncate replies); `LLMRequest.temperature` defaults to 0.8 (today's value) instead of the spec's 0.6.
- The router's `on_event` hook exists but is not wired (the `events` table arrives in Phase 3), so `api_call_log` is still unused as before.
- Shutdown now really runs: `NaviBot.close()` cancels the named tasks, flushes `last_seen`, writes the stop event, takes the backup and closes SQLite.
  `discord.Client` never dispatched the old `on_close`, so the shutdown backup never ran before (recorded in Phase 1; fixed here as promised).
- `bot` is a `commands.Bot` (needed for `load_extension`) with `NaviTree`; prefix commands are not processed, `on_message` is the pipeline.
- `0001_baseline` is a Python migration (`m0001_baseline.py`) wrapping the old idempotent `_create_tables`, not `0001_baseline.sql` as in the spec:
  it contains conditional ALTERs and seeds that cannot be expressed safely as plain SQL on already-migrated databases.
  The runner supports both `.py` and `.sql`, and creates `schema_version` itself, so Phase 3's `0002_v2.sql` must use `CREATE TABLE IF NOT EXISTS schema_version` (or omit it).
- Private helpers used across modules lost their leading underscore (e.g. `check_cosmic_quota`, `DAILY_QUOTA`, `templatize`, `do_backup`).
- Cross-cutting state moved to `ctx.state`; `FeatureFlags` (`ctx.settings`) holds the toggle cache and testing guilds.
- Views/Modals/Groups get the context from `interaction.client.ctx`; cogs use `self.ctx`.

### Deferred / differences from the spec layout
- `services/curse_game.py` (curse maths as pure functions) is not extracted: the curse and bless rules were moved verbatim into
  `handlers/curse_commands.py` because the spec says not to change them and the 24 characterisation tests pin the behaviour. Extract in Phase 3 when the ledger lands.
- `handlers/{context_reply,...}`, `services/{knowledge,privacy,weather}.py`, `db/repos/{permissions,privacy}.py`, `cogs/{privacy,teach}.py`,
  `settings/registry.py` arrive in the phases that need them. `db/legacy.py` was never created (imports were rewritten directly), so there is nothing to delete.
- `cogs/llm_games.py` holds the disabled Navi Challenge / Type Race code; it is not loaded as a cog (its command decorators were already commented out).
- Config (SSM loader) is unit-tested with a fake SSM client only.

### Found, not fixed
- `on_ready` re-runs everything on every gateway reconnect (new DB connection, duplicate background tasks). Unchanged.
- On a fresh database `feature_type_race` / `feature_navi_challenge` load as enabled (seed = 1); harmless today because their commands are not registered.

### Manual smoke checklist for the test server (not run)
`/navi /ping /rank /leaderboard /mypoints /gift /lucky_draw /summ /kanmanilla /audit /mod_tldr /strike /help /health /temp_vc /my_media`,
`/market view|buy|sell|holdings|history`, `/shop view|buy`, `/flip /roll_dice /roulette /slots`, `/admin ...`, the three message context menus,
`navi @user`, reply-`navi`, `navi`, `chunk`, `;;shortcut`, an @mention, a curse word, the 📰 link-summary reaction, member join, voice-state temp-VC cleanup.

## Phase 3 - Data model v2 (branch `v2/phase-3-data-model`)

28 tables become 16 (plus `schema_version`) in `navi.db`, and a separate `privacy.db`. The bot now runs only on the v2 layout and
refuses to start on a pre-v2 file (`LegacyDatabaseError` with the exact migration command). Gemini verification was skipped as agreed.

### Done
- `navi/db/migrations/0001_v2.sql` is the v2 DDL (users, daily_counters, points_ledger, holdings, perks, media, app_emojis, game_results,
  prediction_history, events, content, knowledge, market_items, market_prices, settings, permissions). The old 28-table DDL moved to
  `tools/legacy_schema.py` (tests and the migration tool use it; the bot does not). PRAGMAs now include `busy_timeout=5000`.
- `services/points.py` is the only writer: `award()` updates the balance/XP and appends a `points_ledger` row in ONE transaction
  (rollback on any failure; duplicate `(reason, ref)` is a no-op, which makes partner awards idempotent). Every call site (about 60) now
  states a reason: slang, game, market, shop, gift_sent/received, lucky_draw, admin, prediction, partner_award, curse_*/bless_*, curse_word_said.
- `services/curse_game.py` records the curse/bless outcomes in the ledger; the odds, protection bounce, quotas and potion echo are untouched.
- Leaderboards: overall from `users` (native + partner), most cursed/blessed from ledger counts by reason, FFF/Survival from `game_results`;
  all with a deterministic `user_id` tiebreak.
- `services/retention.py` (daily task `retention`): events > 90 days, prediction_history beyond 20 per user, daily_counters > 14 days,
  ledger `slang`/`game` rows > 180 days compacted to one rollup row per user, pool and reason (sums and balances still reconcile).
- Settings: `settings/registry.py` (every existing knob, `legacy_keys`, `INTENTIONALLY_DROPPED`) + `settings` table (JSON overrides, `updated_by`,
  an `events` row `setting_change` with old/new on every write). Existing `get_config_*`/`feat()` call sites keep working through the registry
  (old names and registry keys are interchangeable; unknown keys raise). A test checks that every key used in the code is registered.
  The full inventory and the /admin panel are Phase 4.
- LLM router calls are recorded as `events` (`llm_call`) through the (now wired) `on_event` hook.
- `tools/migrate_v2.py --src --dst --privacy`: reads the source via the SQLite backup API (never modifies it), refuses to overwrite,
  migrates history (gifts with real amounts, curse/bless logs at delta 0 with the word in `detail`, partner awards with `ref` = game_id),
  inserts one `opening_balance` row per user and pool, creates `privacy.db`, and verifies the invariants below (exit code 1 on any failure).
- `data/v2/navi.db` was produced from the dev copy and `.env` now points `DB_PATH` at it (the dev copy and the live DB are untouched).

### Invariants verified by the tool (all hold on the dev copy; also covered by `tests/phase3` on a populated synthetic legacy DB)
user count; native balance, partner balance, XP, strikes and prediction count per user; per user and pool `SUM(ledger.delta) = balance`
(and XP); equal counts for holdings, perks, media, knowledge, market items, price rows, app emojis, prediction history; `game_results` = fff + survival;
events = command + session + api_call rows; top 10 of the overall, most-cursed, most-blessed, FFF (global and per guild) and Survival leaderboards;
every `bot_config` key is mapped or intentionally dropped (the tool raises on an unknown key).

### Decisions and deviations (please review)
- **Migration file is `0001_v2.sql`, not `0001_baseline.sql` + `0002_v2.sql`.** Fresh databases get v2 directly; legacy files are converted into a new
  file by the tool. The Phase 2 `m0001_baseline.py` is gone (kept as `tools/legacy_schema.py`).
- `media` got a `media_type` column (emoji/sticker): the context menus and `/my_media` filter on it and the spec DDL had no place for it.
- The unique content-key index excludes `score_comment` rows, because the game keeps several comments per score bucket and picks one at random.
- Log-only users: people who were cursed or blessed but never posted had log rows and no `user_stats` row. They get a zero-balance `users` row
  (so their history and leaderboard place survive), so "same user count" is checked as `user_stats + log-only users` (2 on the dev copy).
  Going forward the curse/bless flow creates the target's profile, so such curses still count (a curse on a never-posted target now also deducts
  its points; before it was a silent no-op for the balance). Partner points of users without a profile were never visible and are skipped (noted in the report).
- Legacy "most cursed" counted every `curse_logs` word that did not start with `backfire_`/`proxy_` (so also `potion_backfire_*`, and words people merely
  said). The migration keeps that rule; new events are cleaner: `potion` backfires are `curse_backfire`, said words are `curse_word_said`, and the board
  counts `curse_received` + `curse_word_said`. Legacy grouped by (user_id, username), so a renamed user appeared twice; v2 groups by user_id.
- `feature_navi_challenge` / `feature_type_race` are not migrated (the old seed said 1, the code default said 0): the registry default (off) wins.
  `WEATHER_ALERT_TIME` and `reversal_chance_owner` are intentionally dropped.
- **Fixed by design:** `set_config_float` was an UPDATE-only no-op for never-seeded rows (Phase 0 finding); settings are now upserts.
- Not migrated (not in the spec's table list): `user_stats.last_*`/daily columns are folded into `daily_counters`; `gift_log` rows to users with no profile are skipped.
- Old `username` columns are gone (`users.display_name` is the single source); game leaderboards join `users`.

### Not done / for the next phases
- Phase 3 gate item "point the dev bot at v2 and repeat the Phase 2 smoke checklist" needs a Discord token and test server: not run here
  (the command surface test, startup test against a fresh v2 DB, and 560+ tests pass).
- Settings reads still use the legacy call-site names; Phase 4 replaces them with registry keys and builds the panel.
- `AppContext.privacy_db` and the privacy gate arrive in Phase 6 (the file and table exist and are created by the migration).
