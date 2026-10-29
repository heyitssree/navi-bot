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
