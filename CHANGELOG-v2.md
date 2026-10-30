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

## Phase 4 - Settings registry and admin panel (branch `v2/phase-4-settings`)

One registry, one control surface. 692 tests pass (stable over repeated runs).

### Done
- `settings/registry.py` holds all 77 settings from the spec inventory (System, AI, Safety, Features, Chances, Limits, Channels, Privacy;
  kinds bool/int/float/str/choice/channel/role/id_list; min/max/choices/legacy_keys/hidden/restart). `settings/store.py` (`ctx.settings`) parses,
  validates (clear error text), caches, persists with `updated_by` + a `setting_change` event, resets, exports/imports and notifies observers.
- Every `get_config_*` / `set_config_*` / `feat()` / `set_feature()` call site was replaced by `ctx.settings.get("<registered key>")` (a test greps the
  tree for leftovers and checks every literal key is registered; another test requires every registry entry to have a consumer, except the ones
  whose features arrive in Phases 5-7, listed in the test).
- Constants moved into settings and read at use time: cosmic-action quota, gambling and LLM-game daily limits, market holding expiry, temp VC lifetime,
  lucky-draw prize, slang spam (5 values), vibe check (4), partner rate limit and minimum XP, mod-alerts channel (falls back to MOD_CHANNEL_NAME),
  link-summary emoji. Help texts that quoted "20" or "30" now show the live values.
- New switches: `feature.mention_qa`, `.market`, `.shop`, `.gift`, `.lucky_draw` (the market and shop groups answer "switched off" through
  `interaction_check`); `limit.gift_daily`; `system.panel_role`.
- LLM router reads the `ai.*` settings live: provider on/off, free-only keys, RPM budget, daily call cap (seeded from today's `events` after a restart),
  temperature, max output tokens (4x for summaries and audits), model override, and a per-user cooldown + daily cap for Q&A with in-character replies.
- `/admin` rebuilt: `panel`, `set|get|reset` (with autocomplete), `killswitch`, `testing`, `status`, `user points|strikes_reset|game_attempts_reset`,
  `teach allow|revoke|list`, `review` (5 at a time, approve/reject, loads the next batch), `export`/`import`. Gated by `default_permissions(administrator)` plus
  an owner / panel-role check in code. Panel: ephemeral, 10-minute timeout, invoker only, category -> setting views with toggle / edit modal with
  validation / choice select / channel and role pickers / reset / back, paginated at 25, a confirmation or error line after each change.
- Removed: `toggle_killswitch`, `toggle_feature`, `set_chance`, `set_cooldown`, `set_summary_emoji`, `partner_toggle`, `config_view`, `reset_all_strikes`,
  `set_points`, `adjust_points`, `reset_game_attempts`, `/health`, and the `navi syros stop|start` text command (the owner-text handler is gone from the pipeline).
- Migration `0002_settings_keys.sql` renames four Phase 3 keys (`feature.curse_replies`, `feature.link_summary_emoji`, `limit.local_media_max_*`);
  `data/v2/navi.db` is already on version 2.

### Behaviour changes (all from the spec's inventory; please confirm)
- `ai.temperature` defaults to 0.6 (was 0.8). `ai.qa_cooldown_seconds` (30) and `ai.qa_daily_cap` (25) now apply to mention Q&A, which had no limit
  before; the counters live in memory, so a restart resets them.
- `/admin killswitch` replaces both the old master switch command and the Free-Only toggle; the Free-Only mode is now the `ai.gemini_keys` setting.

### Findings and deviations
- `navi_cooldown_seconds` was editable via `/admin set_cooldown` but nothing ever read it. It now sets the window of the existing /navi
  "2nd/3rd use within a minute" tiering (default 60 s = identical behaviour).
- `/gift` had no daily cap; its only inline limit is the per-gift range 1-10000 in the command signature (kept, since it is part of the command surface).
  `limit.gift_daily` defaults to 0 (no limit) and uses the previously dead `get_gift_daily_total`.
- `ai.provider` offers `gemini` and `off` only; `bedrock` is added with the provider in Phase 7. `ai.max_output_tokens` is applied to requests but still not
  sent to Gemini (it would truncate answers); Bedrock will use it. For choice settings the panel uses a select menu instead of a modal.
- `ai.bedrock_model_id` is marked `restart`; nothing reads it until Phase 7. Q&A cache TTL, safety, context-reply, /teach, bot-commands channel and privacy
  settings are registered and editable now; their consumers land in Phases 5 and 6.
- Python 3.11 compatibility: the Dockerfile image is 3.11, so f-strings must not reuse their quote character (ruff `target-version` catches it).

### Not run
- The panel and commands were exercised with fake interaction objects (every visible setting renders a panel page; every setting round-trips
  parse -> set -> export -> reset). A manual pass in the test server (two accounts, panel role) still needs a Discord token.

## Phase 5 - Content safety and template pools (branch `v2/phase-5-safety`)

754 tests pass. **Not done: the live Gemini eval** (you asked to skip Gemini verification; the suite and tool are ready and run against any provider).

### Done
- `llm/safety.py`: NFKC + lower-case, zero-width removal, leetspeak undo, repeated-letter shortening, plus a stretched-spelling fold
  ("zorgblaaaat"); whole-word blocklist match, "squashed" match for entries of 5+ characters, Malayalam-script entries match anywhere;
  Malayalam script rejected unless `safety.allow_malayalam_script`; `@everyone`/`@here`/`<@id>`/`<@&id>` rejected; per-purpose length limit.
  Returns a `Verdict(ok, reasons)`. The allow-list (approved + curse terms, written to `data/safety/allowlist.txt` at startup) is removed
  from the text before matching, so Navi's own curse words can never trip the filter.
- `data/safety/blocklist.txt` ships **empty** with a format header (path overridable with `SAFETY_BLOCKLIST`). No entries were generated.
- `llm/policy.py`: the CONTENT RULES prompt policy built from knowledge expression terms + Boli trigger words + Kochi slang (approved) and the 17
  curse words; the router appends it to every system prompt (qa, summary, mod, prediction, vibe, template_batch).
- Rejection path: router returns the caller's fallback, logs an `events` row (`safety_reject`, reasons) and keeps the text as `content`
  with `status='rejected'`. Generated templates are checked before storage (`store_generated`), and live `/navi` predictions saved to the pool now
  wait as `pending` unless `safety.template_auto_approve` is on (so reusable text is reviewed first).
- Passive curse reply is template-only: trigger, `chance.passive_curse_reply`, the +1 Boli/XP award and the ledger log are unchanged; the reply
  is `template_pool.pick('curse_back', ...)` avoiding the user's last 5. `get_curse_prompt` and the `cache_type="curse"` path are removed.
  A test with an LLM that raises if touched proves no call happens. The pool is seeded from `DOOMED_PREDICTIONS` + `CURSE_BACK_REPLIES`
  (source `seed`) at startup and by `tools/migrate_v2.py`.
- Weekly `template_batches` job (purpose `template_batch`, `llm/prompts/templates.py`) for `curse_back` and `prediction`: parses the JSON array,
  requires `{user}`, enforces 15/25 words, runs the safety check, drops near-duplicates (rapidfuzz ratio >= 85), stores `pending`
  (or `active` with auto-approve); `/admin review` handles the queue.
- Mentions: the bot is created with `AllowedMentions(everyone=False, roles=False, users=True)`; LLM-text sends (mention Q&A, link summary, vibe,
  /navi, kanmanilla, passive curse) are further limited to the intended user or nobody.
- `tools/eval_llm.py` + `tests/eval/navi_eval.yaml` (suite `navi-safety-v1`, repeats 10): 23 qa, 21 context_reply and 20 prediction cases
  (>= 200 generations per purpose) over the categories direct insult, sexual innuendo, caste/religion bait, translate and role-play jailbreaks,
  repeat-after-me, obfuscation and normal style. The prompts ask for bad output but contain no slurs. It reports the pre-filter violation rate per
  purpose, post-filter violations (must be 0, exit code 1 otherwise), length and approved-terms compliance, missed deflections, and 30 random samples per
  purpose to `reports/eval-<provider>-<date>.md`.

### What I need from you
1. **`navi/data/safety/blocklist.txt`** - your list (Manglish spellings and Malayalam script, one per line). Until it is filled the filter still
   enforces script, mentions and length, and the eval prints a warning that `no_block_hits` cannot fail.
2. The phrase for the "repeat after me" cases, passed at run time (`--phrase` or `EVAL_BLOCKLISTED_PHRASE`); without it those two cases are skipped.
3. Run `python -m tools.eval_llm --provider gemini` (or bedrock after Phase 7) and read the 30 samples per purpose.

### Notes and limits
- `approved_terms_only` is heuristic: it flags words from the slang dictionary (`slang_data.json`) that are not approved terms. It cannot detect a
  Malayalam word that is in neither list, which is why the report shows samples for you to read.
- The "deflects" check is a keyword heuristic on the raw reply; it is reported, not gated. The gate is post-filter violations of the hard checks.
- Rejected text is stored verbatim in `content` for review (as the spec asks), so a blocked reply can contain the offending words in the database.
- `/teach` submissions and context-reply history (Phase 6) will call `safety.check_output` as well.

## Phase 6 - Features (branch `v2/phase-6-features`)

824 tests pass. The manual two-account run in the test server (gate) is not done.

### 10.4 /privacy
- `Privacy` service (`ctx.privacy`) with the single `is_opted_out()` helper, backed by `privacy.db` (only user id, status, time; created next to the main
  DB, overridable with `PRIVACY_DB_PATH`) and an in-memory set loaded at startup.
- `/privacy status | opt_out | opt_in`, all ephemeral. Opt-out shows what will be deleted and what it means (fresh profile later, backups 72 h, logs 14 days),
  needs a Confirm press within 60 s, and is refused while the user has strikes (`privacy.block_optout_with_strikes`). The opt-out is written to `privacy.db`
  and the memory set FIRST (tested with a forced purge failure), then one transaction deletes the user from users, daily_counters, points_ledger, holdings,
  perks, media, game_results, prediction_history, events and permissions, clears `counterparty_id` / `submitted_by` / `approved_by` / `reviewed_by` /
  `updated_by` (and `granted_by` -> 0) on other people's rows, removes local media files and application emojis only they used, clears every in-memory trace
  (seen set, level cache, last-seen buffer, cooldown and spam maps, template history, Q&A limits) and writes an `events` row with no user id.
  A test checks every user-reference column of every table for zero rows.
- Opt-in respects `privacy.optin_cooldown_days` (shows the date it opens) and brings back nothing: the profile is recreated on the next interaction.
- Enforcement, each with a test: pipeline drops their messages right after the killswitch (no points, logs, replies, counters); every slash command except
  `/privacy` answers "You've opted out of Navi..." (the owner keeps `/admin`); `navi @user`, reply-curse, `chunk @user` and reply-bless are refused before the
  quota is touched; `/gift` (explicit recipient and the random picker), `/kanmanilla`, `/navi <name>`; welcome and level-up messages; lucky-draw candidates;
  `/summ` and `/mod_tldr` drop their messages; `/audit` follows `privacy.audit_includes_optouts`; link-summary reactions by or on their messages are ignored;
  partner API awards no longer recreate their profile.
- Limitation: the vibe-check tracker stores message text per channel without user ids, so there is nothing to clear per user (it expires in 15 s).
  S3 objects for media arrive with the AWS storage layer in Phase 8; local files are removed now.

### 10.1 Context-aware replies
- `handlers/context_reply.py`, pipeline position 6 (before mention Q&A). Active only with `feature.context_replies`, `channel.bot_commands` and the
  message in that channel replying to Navi or mentioning Navi. Context = the reply chain only (4 hops, 1,200 characters, never channel history): Navi's own
  messages and the asker's, opted-out users and other people skipped, mentions scrubbed, each line run through the safety filter. The same chain elsewhere is
  still ignored. Shares `ai.qa_cooldown_seconds` and `ai.qa_daily_cap` with mention Q&A; going over gets one in-character note per window, then silence.

### 10.2 Q&A cost levers (`services/qa.py`, also used by mention Q&A)
- "what is / meaning of / where is X" answered from knowledge when `token_set_ratio >= 90`; answer cache in `content` (`qa_answer`, similarity >= 92,
  within `ai.qa_cache_ttl_days`, never for today/now/latest/score/weather/time questions, asker's name stored as `{user}`); then the LLM. Shortcuts do not use up a
  user's allowance. Context replies skip both shortcuts.

### 10.3 /teach
- `/teach add category term description [tags]` (landmark, food, culture, expression; term 2-60, description 10-200), `/teach list [status]`,
  `/teach remove <term>`. Owner and `manage_messages` members publish at once; users approved with `/admin teach allow` go to `/admin review`; everyone else
  gets an ephemeral refusal. Input is stripped of mentions and URLs, run through the safety filter, checked for exact (refused) and fuzzy >= 90 duplicates
  (asks "similar to X, add anyway?"; pending and rejected entries count). Active `expression` entries become approved Manglish terms: the prompt policy and
  allow-list are rebuilt after add, remove and approval.

### Found and fixed
- **The partner API rejected every request with 422.** `navi/api/partner.py` (and the original `api_server.py`, checked at `a0b480d` with the same installed
  FastAPI) used `from __future__ import annotations` with request models defined inside `create_app`, so FastAPI could not resolve them and treated them as
  required query parameters. Removed the future import; `tests/phase6/test_partner_api.py` now covers `/score`, dedupe, the feature switch and `/internal/boli/award`.

### Notes
- Live `/navi` predictions and generated templates still go through review (Phase 5); `/teach` entries from approved users use the same `/admin review` queue.
- `rapidfuzz` and `pyyaml` are now in `requirements.txt`.

## Phase 7 - Bedrock provider (branch `v2/phase-7-bedrock`)

859 tests pass (botocore `Stubber`). **Not done: the live Bedrock call and the eval with Bedrock** - see "Live check".

### Done
- `llm/bedrock.py`: `BedrockProvider` on the Converse API (system + user message, `maxTokens`, `temperature`; token usage from `usage`; 2 retries, 5 s connect /
  30 s read timeouts). Errors: Throttling / TooManyRequests / ServiceQuotaExceeded -> `rate_limited` (10 s), AccessDenied / Validation / ResourceNotFound /
  UnrecognizedClient / expired credentials -> `config`, everything else including connection and read timeouts -> `server`. The model id is never hardcoded:
  `ai.bedrock_model_id` setting, else `BEDROCK_MODEL_ID`. A startup check calls `GetInferenceProfile` (a missing permission only logs a warning).
- The router now holds several providers (`add_provider`), with a **breaker per provider** and per-key cooldowns. `ai.provider` (gemini | bedrock | off) picks the
  active one at use time. `ai.fallback_provider` (off by default) is tried when the active provider fails (server errors, cooldown, open breaker, configuration
  error) but not for budget/cap/user limits or safety rejections; a fallback attempt counts as one budget unit. An unconfigured provider degrades to the
  fallback texts, and `/admin set` / the panel warn when you pick one that is not configured on the server.
- Config: `BEDROCK_MODEL_ID`, `AWS_REGION` (default `ap-south-1`); `llm/factory.py` builds Gemini and/or Bedrock from what is configured (startup only
  requires one of them). `boto3` added to `requirements.txt`. `tools/eval_llm.py --provider bedrock` works (needs `BEDROCK_MODEL_ID`).
- Tokens per call were already logged to `events` (`llm_call`); `/admin status` now shows calls and tokens per provider and an **estimated Bedrock cost today**,
  using `ai.price_input_per_mtok` (0.10) and `ai.price_output_per_mtok` (0.50), kept in settings.
- Tests: Stubber success / throttling / access denied / 5xx / timeouts, router behaviour with Bedrock errors (cooldown without breaker failure, config alert once,
  3 server errors open the breaker), provider switching, fallback chain, per-provider breakers, cost estimate, status, configuration.

### What I found in your AWS account (read-only calls via the AWS MCP server; an earlier account, ap-south-1)
- The profile is **`global.anthropic.claude-haiku-5-5`** ("Global Anthropic Claude Haiku 5.5", ACTIVE, SYSTEM_DEFINED; foundation models
  `anthropic.claude-haiku-5-5` in ap-south-1 and global). Older Haiku 4.5 global/IN profiles also exist.
- A test `Converse` call (20 tokens) returned **AccessDeniedException: "Your account is currently being verified"**. That is the new-account hold (normally under
  2 hours); until it clears no model call works. Nothing else is wrong that I could see.

### Live check (yours, once the account is verified)
1. `aws bedrock-runtime converse --region ap-south-1 --model-id global.anthropic.claude-haiku-5-5 --messages '[{"role":"user","content":[{"text":"hi"}]}]' --inference-config maxTokens=20`
2. `python -m tools.eval_llm --provider bedrock --phrase "<blocklisted phrase>"` and read `reports/eval-bedrock-<date>.md`; commit it under `reports/`.
3. Only then `/admin set ai.provider bedrock` (optionally `ai.fallback_provider gemini`). SETUP.md has the exact steps and the IAM policy.

### Notes
- `ai.model` (the Gemini override) is ignored while Bedrock is active; `ai.max_output_tokens` now reaches Bedrock as `maxTokens`.
- Haiku 5.5 prices in settings are the October 2026 list prices from the spec; update them if AWS changes them.

## Phase 8 - AWS infrastructure (CDK Python)  [branch v2/phase-8-infra]

### Done
- `infra/`: CDK v2 app with Network, Data, Compute and Monitoring stacks (typed config from `cdk.json`, Makefile, cfn-lint, 46 stack tests). Single Graviton
  instance in an ASG of exactly one, IMDSv2, no inbound rules, no NAT, encrypted gp3 root, least-privilege role (SSM path, bucket, ECR pull, logs, heartbeat metric,
  Bedrock global inference profile). Offline synth (explicit AZ, context file).
- Container: `Dockerfile` (arm64/amd64, non-root, Litestream pinned), `docker/entrypoint.sh` (restore, seed fallback, replicate), `docker/litestream.yml`.
- Operator scripts: `put-secrets.sh` (values read silently, never in arguments), `put-config.sh`, `seed-db.sh`, `deploy.sh`, `enable.sh`, `disable.sh`.
- App: SSM config loading (environment wins), S3-backed media (`services/media_store.py`, opt-out also deletes S3 objects), CloudWatch heartbeat, SIGTERM clean
  shutdown, `LOG_TO_FILE=0`. `tools/media_to_s3.py` for the cutover.
- Tests: 882 pass (19 new in `tests/phase8`).

### Not done / needs you
- `cdk bootstrap`, `cdk diff` and `cdk deploy` have NOT been run (they cost money and change the account). Commands are in `infra/README.md`.
- The account's SCP denies most services this phase needs, and Bedrock is still on the new-account verification hold. Resolve both before the gate.
- Docker image build and the Litestream config against the real binary are not yet verified.
- Phase 8b (partner ingest) is skipped; the partner bot is not in use.

### Phase 8 follow-up: Gemma instead of Claude
- Bedrock model is now `google.gemma-3-12b-it` (on-demand). `cdk.json` points at it; the Compute stack adds one `BedrockModelOnDemand` statement for a plain model id and
  keeps the three-statement profile policy for geography-prefixed ids. `BedrockProvider` folds the system prompt into the user message if a model rejects it, and skips the
  inference-profile check for plain model ids. Tests: 885 app and 47 infra pass.
- Not verified live: one 20-token Gemma 3 12B call worked on a new account, the next ones hit that account's verification hold, so the system-prompt behaviour and output quality
  are untested. Prices in settings are still the Haiku placeholders: set Gemma's real prices before relying on `/admin status` cost.
- A second account was in an AWS-managed organization whose SCP denies CloudFormation and EC2, like the first. Deployment is blocked until an account outside such an organization is used.

### Phase 8 deployed (ap-southeast-2)
- `cdk bootstrap` and `cdk deploy --all` ran against the new account (values from `infra/navi.env`, git-ignored). Network, Data, Compute and Monitoring are up; the instance is
  InService on IMDSv2, registered with SSM, pulled the image from ECR, and `navi.service` is idle because `/navi/prod/run_enabled` does not exist yet.
- Found and fixed on the way: `requirements.txt` had `matplotlib` and `rapidfuzz` glued together (from Phase 7), which broke the image build; a test now guards it.
- Heartbeat alarm shows ALARM while the bot is idle (no heartbeat); the SNS email subscription still needs to be confirmed.
- Still to do by the owner: `scripts/put-secrets.sh`, `scripts/put-config.sh`, confirm the SNS email, seed the database, `scripts/enable.sh`.
