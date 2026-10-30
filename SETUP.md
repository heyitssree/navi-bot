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

For AWS (EC2 + Litestream + CDK), see [infra/README.md](infra/README.md).

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


## Amazon Bedrock (Claude Haiku 5.5)

Navi can answer through Bedrock instead of Gemini. Gemini stays the default until you switch (`/admin set ai.provider bedrock`).

### 1. Find the model id (never hardcoded)
```bash
aws bedrock list-inference-profiles --region ap-south-1 --type-equals SYSTEM_DEFINED \
  --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'haiku')].[inferenceProfileId,status]" --output table
```
For this account the profile is **`global.anthropic.claude-haiku-5-5`** (global cross-Region profile, ACTIVE in ap-south-1).
Its two foundation-model ARNs (from `aws bedrock get-inference-profile --inference-profile-identifier <id>`):
`arn:aws:bedrock:::foundation-model/anthropic.claude-haiku-5-5` and `arn:aws:bedrock:ap-south-1::foundation-model/anthropic.claude-haiku-5-5`.

### 2. Configure
```
BEDROCK_MODEL_ID=global.anthropic.claude-haiku-5-5   # or /admin set ai.bedrock_model_id (restart to apply)
AWS_REGION=ap-south-1
AWS_PROFILE=navi                                     # local only; on EC2 the instance role is used
```
Check the profile works locally with `aws sts get-caller-identity --profile navi`.

### 3. Permissions the bot's role needs
The global profile needs three statements (profile in your region, the in-region model, the global model resource):
```json
{"Version": "2012-10-17", "Statement": [
 {"Sid": "ProfileInRegion", "Effect": "Allow", "Action": "bedrock:InvokeModel",
  "Resource": "arn:aws:bedrock:ap-south-1:<ACCOUNT_ID>:inference-profile/global.anthropic.claude-haiku-5-5"},
 {"Sid": "ModelInRegion", "Effect": "Allow", "Action": "bedrock:InvokeModel",
  "Resource": "arn:aws:bedrock:ap-south-1::foundation-model/anthropic.claude-haiku-5-5",
  "Condition": {"StringEquals": {"bedrock:InferenceProfileArn": "arn:aws:bedrock:ap-south-1:<ACCOUNT_ID>:inference-profile/global.anthropic.claude-haiku-5-5"}}},
 {"Sid": "ModelGlobal", "Effect": "Allow", "Action": "bedrock:InvokeModel",
  "Resource": "arn:aws:bedrock:::foundation-model/anthropic.claude-haiku-5-5",
  "Condition": {"StringEquals": {"aws:RequestedRegion": "unspecified",
                                 "bedrock:InferenceProfileArn": "arn:aws:bedrock:ap-south-1:<ACCOUNT_ID>:inference-profile/global.anthropic.claude-haiku-5-5"}}},
 {"Sid": "OptionalStartupCheck", "Effect": "Allow", "Action": "bedrock:GetInferenceProfile",
  "Resource": "arn:aws:bedrock:ap-south-1:<ACCOUNT_ID>:inference-profile/global.anthropic.claude-haiku-5-5"}]}
```
(`Converse` is authorised by `bedrock:InvokeModel`.) If your account is in an AWS Organization, a Region-deny SCP must allow
`aws:RequestedRegion = unspecified` for Bedrock or global profiles fail with AccessDeniedException. Phase 8's CDK stack will contain this policy.

### 4. First live check
```bash
AWS_PROFILE=navi BEDROCK_MODEL_ID=global.anthropic.claude-haiku-5-5 python -m tools.eval_llm --provider bedrock --phrase "<a phrase from your blocklist>"
```
A new AWS account may answer every call with *"Your account is currently being verified"* (AccessDeniedException) for up to ~2 hours; if it lasts longer,
write to aws-verification@amazon.com. Navi treats that as a configuration error: one owner DM, breaker open, fallbacks until it clears.
Only switch with `/admin set ai.provider bedrock` after the report in `reports/` shows 0 post-filter violations. Optional: `/admin set ai.fallback_provider gemini`.
