# Navi - Trivandrum's Own Astrologer Bot

A Discord bot for a Trivandrum / Kerala community server. Navi is a dramatic, self-important astrologer who speaks
Trivandrum Manglish, runs a points-and-curses game, a stock market and a shop, and a few mini-games. Powered by Google
Gemini for the chatty parts; the curse/bless game itself uses no AI.

## Features

**Predictions and chat**
- `/navi` - daily astrology reading with a Rashi per user. Repeat calls within a minute are served from cache.
- @mention Navi to ask a question (Q&A in persona).
- Passive curse reply: when a message contains a curse-list word there is a chance (default 25%) Navi answers and awards +1 Boli.
- Kochi-slang detection: a chance (default 28%) of a condescending Thirontharam reply.
- Vibe check: if a channel turns heated (all-caps, severe words) Navi posts a calming message.
- Link summaries (react with the summary emoji, default 📰), `/summ` (chat summary), `/kanmanilla` (missing-member notice).
- Moderation: `/audit`, `/mod_tldr`, `/strike`, and a 3-strike system for severe curse words.
- Welcome messages for new members and `/temp_vc` temporary voice channels.

**Curse and bless game (no AI)**
- `navi @user`, `navi` as a reply, or bare `navi` (self-curse) pick a random curse from three tiers (Mild / Moderate / Severe)
  with a tier backfire chance (default 10 / 15 / 20%). Curse Protection and Deflector Shield always bounce it back.
- `chunk @user` (or as a reply / alone) blesses with a random compliment, a caster share and a 5% universal blessing.
- 20 cosmic actions per day (refills via the shop).

**Economy**
- Boli Points and XP for local slang (TVM words add, Kochi words subtract), levels with titles, `/mypoints`, `/rank`, `/leaderboard`.
- `/market` - the Boli Stock Market (`view`, `buy`, `sell`, `holdings`, `history`); prices move hourly.
- `/shop` - perks and refills; `/gift` - gift Boli; daily lucky draw (7:00 AM IST, `/lucky_draw` for admins).
- Gambling: `/flip`, `/roll_dice`, `/roulette`, `/slots`.
- Local media shortcuts: save an emoji or sticker and post it with `;;name` (`/my_media`).
- `/navi_challenge` and `/type_race` exist but are disabled by default.

**Admin** (`/admin ...`): kill switch, feature toggles, probabilities, cooldowns, testing mode, point adjustments, config view.
`/health` (owner) shows uptime, active model and key, circuit state and table counts.

**Partner API**: a small FastAPI server (port `API_SERVER_PORT`, default 8080) lets a partner bot award Boli points.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # then fill it in; see SETUP.md
python bot.py
```

Invite the bot with the `bot` and `applications.commands` scopes and enable the Message Content, Server Members and
Presence intents in the Discord Developer Portal.

## Environment variables

| Variable | Purpose |
|---|---|
| `DISCORD_TOKEN` | Discord bot token (required) |
| `GEMINI_API_KEY_FREE` | Gemini key tried first (free tier) |
| `GEMINI_API_KEY_PAID` | Gemini key used when the free key fails or is rate limited. At least one key is required |
| `LLM_MODEL` | Gemini model, default `gemini-3.5-flash-lite` (falls back to `gemini-3.8-flash` if the key cannot use it) |
| `DB_PATH` | SQLite file, default `data/navi.db` |
| `OWNER_ID`, `GUILD_ID` | Owner and server IDs |
| `FREE_TIER_MODE` | `true` to be frugal with API calls |
| `GENERAL_CHANNEL`, `MOD_CHANNEL_NAME` | Channel names the bot uses |
| `PARTNER_BOT_API_KEY`, `API_SERVER_PORT` | Partner API bearer key and port |
| `BOT_INTERNAL_SECRET` | Shared secret for `/internal/boli/award` |

## How AI errors are handled

- Rate limited (429): that key cools down for the server's suggested delay (20 s if none). This never trips the circuit breaker.
- Configuration (400/401/403/404, e.g. bad key or missing model): logged at most every 10 minutes, the owner gets at most one DM an hour, and the breaker opens immediately.
- Server errors and timeouts: 3 in a row open the breaker for 5 minutes, then one probe call decides whether it closes.
- Only `/navi` predictions fall back to the cached template pool; every other feature uses its own fallback text.

## Layout

```
bot.py                 # commands, events, background loops
schema.py              # SQLite schema, migrations and queries
prompts.py             # Gemini prompts
curse_data.py          # curse / compliment / Boli / Kochi word lists and matchers
glossary.py            # Trivandrum slang, landmarks, food, culture
slang_scorer.py  template_resolver.py  market_engine.py  api_server.py
services/              # gemini_service.py (keys, errors, breaker), api_manager.py (rate limit, cache)
data/                  # slang_data.json, templates.json (database and media are not committed)
tools/                 # maintenance scripts (db_report.py, recovery and import helpers)
tests/legacy/          # characterisation tests: pytest
```

## Development

```bash
pip install -r requirements-dev.txt
pytest
python -m tools.db_report         # row counts for $DB_PATH
```

Point `DB_PATH` at a copy of the database, never the live file. See `SETUP.md` and `DEPLOYMENT.md` for hosting.

## Troubleshooting

- **"DISCORD_TOKEN not found"**: create `.env` from `.env.example`.
- **"No Gemini API key found"**: set `GEMINI_API_KEY_FREE` or `GEMINI_API_KEY_PAID`.
- **Replies are all fallback text**: check the log for a `Gemini configuration error` line (bad key or `LLM_MODEL`); the owner also gets a DM.
- **Bot does not react to messages**: enable the Message Content intent and check channel permissions.
