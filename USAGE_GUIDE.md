# Navi V2 — Usage Guide

*"The most unnecessarily dramatic astrologer in Thirontharam."*

---

## Slash Commands

### 🔮 `/navi` — Get Your Prediction
The main event. Get a Trivandrum Manglish astrology reading.

```
/navi
/navi user:@someone
```

**What happens:**
- **First time**: Navi assigns you a Rashi (Malayalam star sign) that sticks forever
- **Every time after**: Navi references one of your past doomed predictions and blames it on something specific ("you got stuck at KD Puram because you skipped Boli and Paal Payasam")
- The prediction changes based on **time of day** — evening predictions obsess over chaya and Pazham Pori; late-night ones hint at Museum Campus ghosts
- **+2 Boli Points** awarded to the person who used the command

**Example outputs:**
> *"Eda Sree, your Kumbham Rashi shows kili poyi vibes near Museum Campus tonight — and yes, last week's Chalai Market disaster was because you skipped Boli."*

> *"Aiyo Arun, 4pm star alignment says go get chaya NOW from thattukada or your evening is shokam."*

---

### 🍮 `/mypoints` — Check Your Boli Points
See your personal Navi profile. Only visible to you.

```
/mypoints
```

Shows:
- 🌟 Your Rashi (assigned on first `/navi` use)
- 🍮 Total Boli Points earned
- 🔮 Number of predictions you've received

---

### 🏆 `/rank` — Leaderboard
See the **Top Appis** in the server — ranked by Boli Points.

```
/rank
```

Shows top 10 users with their Rashi, Boli Points, and prediction count.

---

### 🔧 `/admin status` — System Status *(Owner Only)*
Check Navi's internals. Only works if you're the bot owner.

```
/admin status
```

Shows:
- Which Gemini key is active (`free` or `paid`)
- Circuit breaker state (OPEN 🔴 / CLOSED 🟢)
- Rate limiter: how many of the 10 RPM you've used this minute
- SQLite row counts per table
- Bot uptime

---

## Earning Boli Points 🍮

Boli Points are earned passively — no command needed.

| Action | Points |
|---|---|
| Use `/navi` | +2 pts |
| Say a Trivandrum word in chat | +5 pts per word |
| Trigger a curse-word reply | +1 pt |

**Words that earn points** (say these naturally in chat):

| Word | Meaning |
|---|---|
| `kidilam` | Absolutely awesome |
| `kidu` | Same — fantastic |
| `pillacha` | Respectful address for older man |
| `appi` | Term of endearment |
| `shokam` | Sad/boring situation |
| `chumma` | Simply, for no reason |
| `kili poyi` | Bird flew away — shocked/confused |
| `vishayam` | Matter/issue |
| `mone` | Son; affectionate address |
| `chetta` | Elder brother |
| `thirontharam` | Correct local name for Trivandrum |
| `boli` | The sacred sweet |
| `paal payasam` | The sacred dessert |

> **Example**: Saying *"that movie was kidilam mone"* earns +10 pts (2 trigger words × 5).

---

## Passive Bot Reactions

Navi watches every message and reacts automatically.

### 🗣️ Kochi Slang Detection
Say any of these and Navi will condescendingly remind you where you are:

`machane` · `machi` · `sayi` · `da scene` · `yov` · `monae` · `adipoli`

**Example reply:**
> *"Eda Arun, this is Thirontharam. Keep that Kochi talk at Ernakulam South station."*

*85% chance of reply — sometimes Navi ignores you, which is also very on-brand.*

---

### 💢 Curse Word Detection
Use any Malayalam curse word and there's a 25% chance Navi roasts you back.

**Example reply:**
> *"Eda Sree, nee oru pottan aanu. Ninte future darker than KD Puram at 7pm. Shokam."*

---

### ❓ Tagging Navi
Mention `@Navi` with a question and get a sarcastic answer.

```
@Navi will I get a promotion this year?
@Navi what should I eat for lunch?
```

**Example replies:**
> *"Eda Sree, even KD Puram traffic has more potential than your promotion chances."*
> *"Aiyo, go eat Boli. What kind of question is that, mone."*

---

### 🌅 Time-Aware Personality

Navi's mood shifts throughout the day:

| Time | Personality |
|---|---|
| 6–10 AM | Grumpy about the KSRTC bus rush at Thampanoor |
| 11 AM–2 PM | Irritable about the unbearable noon heat |
| 2–4 PM | Sleepy post-lunch sluggishness |
| **4–7 PM** | **Obsessed with evening chaya and Pazham Pori** |
| 7–10 PM | Lamenting Technopark traffic and KD Puram gridlock |
| 10 PM+ | Ominous late-night vibes, Museum Campus ghost energy |

---

## Admin Controls

All admin tools live under `/admin` (owner only, or the role set in `system.panel_role`). Replies are private.

| Command | Effect |
|---|---|
| `/admin panel` | Browse and edit every setting (categories, toggles, edit boxes, channel and role pickers, reset) |
| `/admin set <key> <value>` / `get` / `reset` | Direct edits with autocomplete and validation |
| `/admin killswitch on\|off` | Silences Navi everywhere except `/admin` |
| `/admin status` | Uptime, AI provider/model, breaker, today's calls and tokens, DB size, last backup |
| `/admin user points\|strikes_reset\|game_attempts_reset` | Per-user tools (point changes are recorded in the ledger as `admin`) |
| `/admin teach allow\|revoke\|list` | Who may use `/teach` |
| `/admin review` | Approve or reject pending templates and `/teach` entries, 5 at a time |
| `/admin export` / `import` | Settings as a JSON file |
| `/admin testing on\|off` | Testing mode for the current server (no limits, no rewards) |

---

## How the API Works (Behind the Scenes)

You don't need to manage this, but good to know:

```
Every Gemini call:
  1. Try free API key first
  2. If busy/failed → try paid key
  3. If both fail 3 times → cache-only mode for 30 min
  4. Max 10 API calls per minute (then falls back to saved responses)
```

- The bot **caches all responses** in a local database and reuses them smartly
- `/admin status` shows exactly what's happening at any moment

---

## Tips

- **Check `/mypoints` after chatting** — you'll often have points you didn't notice earning
- **The more people use Trivandrum words, the richer the leaderboard** — `/rank` is more fun with a full server
- **Tag Navi with weird questions** — the more absurd the question, the better the sarcastic answer
