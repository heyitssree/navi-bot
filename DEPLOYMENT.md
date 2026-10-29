# Navi V2 — Deployment Guide (GCP Free Tier VM)

This guide covers deploying Navi V2 to a GCP **e2-micro** Linux VM.

---

## Quick Reference — What Changed in V2

| Change | Action needed on VM |
|---|---|
| New dep: `requests` | `pip install -r requirements.txt` |
| New env vars | Update `.env` (see Step 3) |
| `data/` and `logs/` dirs | Auto-created on first bot startup |
| Old `response_cache.json` | Can be deleted — replaced by the SQLite cache |
| Old `GEMINI_API_KEY` | Rename to `GEMINI_API_KEY_PAID` in `.env` |

---

## Step 1: Push Your Code from Windows

On your **local machine**, commit and push everything:

```bash
git add .
git commit -m "feat: Navi V2 - SQLite, dual-key, rate limiter, gamification"
git push origin main
```

> [!NOTE]
> `.env` and `data/*.db` are git-ignored and will NOT be pushed — that's correct.
> Only the sanitized `.env.example` is tracked.

---

## Step 2: Pull the Code on Your VM

SSH into your GCP VM (click **SSH** in the GCP Console), then:

```bash
# Navigate to your bot folder
cd ~/navi-bot

# Pull the latest changes
git pull origin main

# Activate your virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## Step 3: Update Your `.env` File

Your `.env` needs two new variables. Open it:

```bash
nano .env
```

Update it to look like this (replace values with your real keys):

```env
DISCORD_TOKEN=your-discord-token-here
GUILD_ID=your-guild-id-here

# Gemini API keys — free key tried first, paid is fallback
GEMINI_API_KEY_FREE=your-free-gemini-key-here
GEMINI_API_KEY_PAID=your-paid-gemini-key-here

# Bot behaviour (see .env.example for the full list)
FREE_TIER_MODE=true
```

> [!IMPORTANT]
> If your old `.env` had `GEMINI_API_KEY=...`, that still works as a fallback alias.
> But rename it to `GEMINI_API_KEY_PAID` for clarity.

Press `Ctrl+O` → `Enter` to save, `Ctrl+X` to exit.

---

## Step 4: Run the Bot

Use `tmux` so the bot keeps running after you close the SSH window:

```bash
# If you have an existing tmux session, kill it first
tmux kill-session -t navi 2>/dev/null || true

# Start a fresh session
tmux new -s navi

# Inside tmux — make sure venv is active and you're in the right folder
cd ~/navi-bot
source .venv/bin/activate

# Start the bot
python bot.py
```

You should see startup logs like:

```
2026-04-24 [INFO] navi: Starting Navi V2... Free key: ✓ | Paid key: ✓
2026-04-24 [INFO] navi.schema: SQLite initialised at data/navi.db
2026-04-24 [INFO] navi.gemini: GeminiService initialised. Available keys: ['free', 'paid']
2026-04-24 [INFO] navi: Logged in as Navi#XXXX
2026-04-24 [INFO] navi: Slash commands synced. Navi V2 is live.
```

**Detach from tmux** (bot keeps running): Press `Ctrl+B`, release, then press `D`.

---

## Step 5: Verify It's Working

Back in Discord, test these:

| Command / Action | Expected |
|---|---|
| `/navi` | Prediction + Rashi assigned on first use |
| `/mypoints` | Shows your Boli Points and Rashi |
| `/rank` | Leaderboard embed |
| `/health` (owner only) | Status embed showing active key, RPM, circuit state |
| Say "machane" in chat | Condescending Thirontharam reply |
| Say "kidilam" in chat | +5 Boli Points silently awarded |

---

## Checking Logs / Reattaching

```bash
# Reattach to the running bot
tmux attach -t navi

# Or tail the log file directly (without attaching)
tail -f ~/navi-bot/logs/bot.log

# To stop the bot
tmux attach -t navi
# Then press Ctrl+C
```

---

## Running the Cache Cleaner (Optional, Weekly)

To keep cached responses generic (good for reuse), run the cleaner manually:

```bash
cd ~/navi-bot
source .venv/bin/activate

# Stop the bot first (Ctrl+C in its tmux window), then:
python tools/cache_cleaner.py

# Restart the bot
python bot.py
```

Or set up a weekly cron job (runs Sunday 2:30 AM IST = Sunday 21:00 UTC Saturday):

```bash
crontab -e
```

Add this line:

```
0 21 * * 6 cd ~/navi-bot && source .venv/bin/activate && python tools/cache_cleaner.py >> logs/cleaner.log 2>&1
```

---

## Backing Up Boli Points Data

The SQLite file at `data/navi.db` is not committed to git. To back up user stats:

```bash
cd ~/navi-bot
source .venv/bin/activate
python -c "import schema; conn = schema.init_db(); schema.export_stats_csv(conn, 'data/backup_stats.csv'); print('Done')"
```

Then copy it to your local machine:

```bash
# Run this on your LOCAL machine (Windows PowerShell)
gcloud compute scp navi-server:~/navi-bot/data/backup_stats.csv ./backup_stats.csv
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `DISCORD_TOKEN not found` | Check `.env` is saved correctly with `cat .env` |
| `No Gemini API key found` | Ensure `GEMINI_API_KEY_FREE` or `GEMINI_API_KEY_PAID` is in `.env` |
| Bot shows `active_key: none` in `/health` | Both API keys are failing — check quotas in Google AI Studio |
| `#off-topic channel not found` | Set `HORRIBLESCOPE_CHANNEL=general` in `.env` to match your server |
| Bot crashes on startup | Check `logs/bot.log` for the traceback: `cat logs/bot.log` |

---

## GCP VM Setup (First Time Only)

If you're setting up a brand new VM:

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → Compute Engine → Create Instance
2. **Region**: `us-central1`, `us-east1`, or `us-west1` (free tier only)
3. **Machine type**: `e2-micro`
4. Click **SSH** once it's running, then:

```bash
sudo apt-get update
sudo apt-get install python3 python3-pip python3-venv git tmux -y

git clone https://github.com/YOUR_GITHUB_USER/navi-bot.git
cd navi-bot

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Then follow Steps 3–5 above.
