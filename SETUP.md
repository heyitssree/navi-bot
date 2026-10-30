# Navi - Setup Guide

Navi is a Trivandrum-Manglish astrologer Discord bot with Boli Points, a market, games and Gemini-written replies. It is self-contained: one Python process, one SQLite file.

## 1. Use your existing Discord application

This guide assumes the Navi application already exists in the [Developer Portal](https://discord.com/developers/applications) and the bot is already in your server. Open that application and:

1. **Bot** tab: click **Reset Token** and copy it into `DISCORD_TOKEN` (the old token stops working).
2. Same tab, **Privileged Gateway Intents**: check that **Presence Intent**, **Server Members Intent** and **Message Content Intent** are on. Navi requests all intents and will not start without them.
3. If the bot was invited without the `applications.commands` scope, re-invite it from **OAuth2 > URL Generator**.

## 2. Collect the other values

| Variable | How to get it |
|---|---|
| `GUILD_ID` | Discord > User Settings > Advanced > enable **Developer Mode**. Right-click your server icon > **Copy Server ID** |
| `OWNER_ID` | With Developer Mode on, right-click your own name > **Copy User ID** |
| `GEMINI_API_KEY_FREE` | [Google AI Studio](https://aistudio.google.com/app/apikey) > **Create API key** |
| `GEMINI_API_KEY_PAID` (optional) | Same page, a key from a billing-enabled project, used as fallback |
| `PARTNER_BOT_API_KEY`, `BOT_INTERNAL_SECRET` | Make up long random strings: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |

Channel names (`GENERAL_CHANNEL`, `MOD_CHANNEL_NAME`) are plain channel names such as `general`, not IDs. The full list with comments is in `.env.example`.

## 3. Run locally

Requires Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # edit .env and fill in the values above
python -m navi
```

The database (`data/navi.db`) and tables are created on first start. Set `DB_PATH` to keep it outside the repo.

Try `/navi`, `/mypoints`, `/rank` and, as the owner, `/admin status`.

## 4. Run on a server

Follow [DEPLOYMENT.md](DEPLOYMENT.md) (tmux on a VM), use `navi.service` as a systemd unit (edit the user and paths first), or deploy with the included `Dockerfile` / `Procfile`.

## 5. HTTP API for other bots (optional)

Navi starts a small FastAPI server on `API_SERVER_PORT` (default 8080):

- `POST /score` takes `Authorization: Bearer <PARTNER_BOT_API_KEY>` and awards Boli for a score from another bot.
- `POST /internal/boli/award` takes `X-Internal-Secret: <BOT_INTERNAL_SECRET>`. The Bamboozled Activity backend uses it.

Open the port in your firewall only if a caller on another machine needs it. If you do not use partner bots, you can leave the secrets as they are; unauthenticated calls are rejected.

## Troubleshooting

| Problem | Fix |
|---|---|
| `DISCORD_TOKEN not found in .env` | `.env` is missing or you are not running from this folder |
| `No Gemini API key found` | Set `GEMINI_API_KEY_FREE` or `GEMINI_API_KEY_PAID` |
| `PrivilegedIntentsRequired` | Enable the three privileged intents in step 1 |
| Slash commands missing | Global sync can take up to an hour; re-invite with `applications.commands` |
