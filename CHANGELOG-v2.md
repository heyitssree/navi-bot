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
