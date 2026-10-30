"""Convert a pre-v2 Navi database (28 tables) into the v2 layout.

    python -m tools.migrate_v2 --src data/dev/navi_dev.db --dst data/v2/navi.db --privacy data/v2/privacy.db

* The source is only read (copied into memory with the SQLite backup API); its main file is never modified.
  Reading a WAL-mode file can create empty -wal/-shm sidecar files next to it; they are harmless.
* --dst and --privacy must not exist yet; nothing is overwritten.
* History is migrated (gifts with real amounts, curse/bless logs with delta 0, partner awards with ref = game_id),
  then one opening_balance row per user and pool makes SUM(points_ledger.delta) equal the balance exactly.
* verify() re-reads both databases and fails loudly (exit code 1) if any invariant breaks.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

from navi.db.connection import connect
from navi.db.migrate import migrate
from navi.db.repos import games as games_repo
from navi.db.repos import points as points_repo
from navi.db.repos.privacy import connect_privacy
from navi.services.template_pool import seed_templates
from navi.settings.registry import BY_LEGACY, INTENTIONALLY_DROPPED, RESET_ON_MIGRATE

OPENING_TS = "1970-01-01 00:00:00"
CONTENT_KIND = {"navi": "prediction", "curse": "curse_back", "qa": "qa_answer"}


class MigrationError(RuntimeError):
    pass


@dataclass
class Report:
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = ["Migration report", "----------------"]
        lines += [f"  {k:<28} {v:>8}" for k, v in sorted(self.counts.items())]
        lines += [f"  note: {n}" for n in self.notes]
        lines += [f"  FAIL: {f}" for f in self.failures]
        return "\n".join(lines)


# ----------------------------------------------------------------------------- helpers

def open_source(path: Path) -> sqlite3.Connection:
    """Copy the source into memory with the SQLite backup API (works with WAL files, never writes to the source)."""
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    mem = sqlite3.connect(":memory:")
    ro.backup(mem)
    ro.close()
    return mem


def tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def col(conn: sqlite3.Connection, table: str, name: str, default: str = "NULL") -> str:
    """SQL expression for a column that may be missing in older databases."""
    return name if name in columns(conn, table) else default


def rows(conn: sqlite3.Connection, table: str, sql: str, params: list | None = None) -> list[tuple]:
    return conn.execute(sql, params or []).fetchall() if table in tables(conn) else []


def count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] if table in tables(conn) else 0


# ----------------------------------------------------------------------------- migration

def migrate_database(src: sqlite3.Connection, dst: sqlite3.Connection, report: Report) -> None:
    users = _users(src, dst, report)
    _daily_counters(src, dst, users, report)
    _ledger(src, dst, users, report)
    _holdings_perks_market(src, dst, report)
    _media(src, dst, report)
    _games(src, dst, report)
    _history_events(src, dst, report)
    _content_knowledge(src, dst, report)
    seeded = seed_templates(dst)     # reviewed curse_back pool for the template-only passive curse reply
    report.notes.append(f"seeded {seeded} curse_back templates")
    _settings(src, dst, report)
    dst.commit()


def log_only_users(src: sqlite3.Connection) -> dict[int, str]:
    """user_id -> username for users that appear in curse_logs/bless_logs but not in user_stats."""
    known = {r[0] for r in src.execute("SELECT user_id FROM user_stats")}
    found: dict[int, str] = {}
    for table in ("curse_logs", "bless_logs"):
        for uid, name in rows(src, table, f"SELECT user_id, username FROM {table} ORDER BY id"):
            if uid not in known:
                found[uid] = name   # latest name wins
    return found


def _users(src, dst, report) -> set[int]:
    if "user_stats" not in tables(src):
        raise MigrationError("source has no user_stats table: not a pre-v2 Navi database")
    ext = {r[0]: r[1] for r in rows(src, "external_boli_points", "SELECT user_id, SUM(points) FROM external_boli_points GROUP BY user_id")}
    sql = f"""
        SELECT user_id, username, rashi, COALESCE(boli_points,0), COALESCE(experience,0),
               {col(src, 'user_stats', 'strikes', '0')}, COALESCE(prediction_count,0),
               {col(src, 'user_stats', 'extra_actions', '0')}, COALESCE(last_seen, CURRENT_TIMESTAMP)
        FROM user_stats ORDER BY user_id"""
    ids = set()
    for uid, name, rashi, boli, xp, strikes, preds, extra, last_seen in src.execute(sql):
        dst.execute(
            """INSERT INTO users (user_id, display_name, rashi, boli_points, partner_points, experience, strikes,
                                  prediction_count, extra_actions, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [uid, name, rashi, boli, ext.get(uid, 0) or 0, xp, strikes or 0, preds, extra or 0, str(last_seen), str(last_seen)],
        )
        ids.add(uid)
    orphan = set(ext) - ids
    if orphan:
        report.notes.append(f"{len(orphan)} users have partner points but no user_stats row; their partner rows were skipped")
    # People who were cursed or blessed but never posted have log rows and no user_stats row. Keep their history
    # (and their place on the leaderboards) by giving them a zero-balance user row.
    for uid, name in log_only_users(src).items():
        dst.execute("INSERT INTO users (user_id, display_name) VALUES (?, ?)", [uid, name])
        ids.add(uid)
    report.counts["users"] = len(ids)
    report.counts["  of which log-only"] = len(ids) - count(src, "user_stats")
    return ids


def _daily_counters(src, dst, users, report) -> None:
    n = 0

    def put(uid, day, counter, value):
        nonlocal n
        if uid in users and day and value:
            dst.execute(
                "INSERT INTO daily_counters (user_id, day, counter, value) VALUES (?, ?, ?, ?)"
                " ON CONFLICT (user_id, day, counter) DO UPDATE SET value = value + excluded.value",
                [uid, str(day), counter, value])
            n += 1

    if "daily_action_count" in columns(src, "user_stats"):
        for uid, c, d in src.execute("SELECT user_id, daily_action_count, last_action_date FROM user_stats"):
            put(uid, d, "cosmic_action", c)
    if "daily_refill_count" in columns(src, "user_stats"):
        for uid, c, d in src.execute("SELECT user_id, daily_refill_count, last_refill_date FROM user_stats"):
            put(uid, d, "refill", c)
    for uid, game, day, c in rows(src, "game_daily_counts", "SELECT user_id, game_name, play_date, play_count FROM game_daily_counts"):
        put(uid, day, f"game:{game}", c)
    for table, name in (("navi_challenge_attempts", "navi_challenge"), ("type_race_attempts", "type_race")):
        for uid, day, c in rows(src, table, f"SELECT user_id, play_date, play_count FROM {table}"):
            put(uid, day, f"llm_game:{name}", c)
    report.counts["daily_counters"] = n


def _curse_reason(word: str) -> str:
    # Same rule the old "most cursed" query used: backfire_* and proxy_* were excluded, everything else counted.
    if word.startswith("backfire_"):
        return "curse_backfire"
    if word.startswith("proxy_"):
        return "curse_self"
    return "curse_received"


def _ledger(src, dst, users, report) -> None:
    def add(uid, pool, delta, reason, ts, counterparty=None, detail=None, ref=None, xp=0):
        dst.execute(
            """INSERT INTO points_ledger (user_id, pool, delta, xp_delta, reason, counterparty_id, detail, ref, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [uid, pool, delta, xp, reason, counterparty, detail, ref, str(ts) if ts else OPENING_TS])

    skipped = 0
    # gifts, with their real amounts
    for sender, recipient, amount, ts in rows(src, "gift_log", "SELECT sender_id, recipient_id, amount, gifted_at FROM gift_log ORDER BY id"):
        if sender in users:
            add(sender, "native", -amount, "gift_sent", ts, recipient)
        else:
            skipped += 1
        if recipient in users:
            add(recipient, "native", amount, "gift_received", ts, sender)
        else:
            skipped += 1
    # partner awards: external_boli_points rows (ref = game_id), enriched from partner_score_log
    info = {r[0]: r for r in rows(src, "partner_score_log", "SELECT game_id, user_id, guild_id, raw_points, boli_awarded, xp_awarded, game_type FROM partner_score_log")}
    seen_games = set()
    for uid, points, source, game_id, ts in rows(src, "external_boli_points", "SELECT user_id, points, source_game, game_id, awarded_at FROM external_boli_points ORDER BY id"):
        if uid not in users:
            skipped += 1
            continue
        extra = info.get(game_id)
        detail = json.dumps({"game_type": source, "raw_points": extra[3] if extra else points,
                             "guild_id": extra[2] if extra else None})
        add(uid, "partner", points, "partner_award", ts, detail=detail, ref=game_id)
        seen_games.add(game_id)
    for game_id, row in info.items():   # score log rows that never reached the points table: keep as history-only
        if game_id not in seen_games and row[1] in users:
            add(row[1], "partner", 0, "partner_award", None, detail=json.dumps({"game_type": row[6], "raw_points": row[3]}), ref=game_id)
    # curse and bless logs: delta 0, the word in detail
    for uid, word, ts in rows(src, "curse_logs", "SELECT user_id, curse_used, timestamp FROM curse_logs ORDER BY id"):
        if uid in users:
            add(uid, "native", 0, _curse_reason(word), ts, detail=word)
        else:
            skipped += 1
    for uid, word, ts in rows(src, "bless_logs", "SELECT user_id, bless_used, timestamp FROM bless_logs ORDER BY id"):
        if uid in users:
            add(uid, "native", 0, "bless_received", ts, detail=word)
        else:
            skipped += 1
    # opening balances close the gap so that SUM(delta) == balance
    n_opening = 0
    hist = {(u, p): d for u, p, d in dst.execute("SELECT user_id, pool, SUM(delta) FROM points_ledger GROUP BY user_id, pool")}
    xp_hist = {u: x for u, x in dst.execute("SELECT user_id, SUM(xp_delta) FROM points_ledger GROUP BY user_id")}
    for uid, boli, partner, xp in dst.execute("SELECT user_id, boli_points, partner_points, experience FROM users").fetchall():
        add(uid, "native", boli - hist.get((uid, "native"), 0), "opening_balance", None, xp=xp - (xp_hist.get(uid) or 0))
        add(uid, "partner", partner - hist.get((uid, "partner"), 0), "opening_balance", None)
        n_opening += 2
    report.counts["points_ledger"] = dst.execute("SELECT COUNT(*) FROM points_ledger").fetchone()[0]
    report.counts["  opening_balance rows"] = n_opening
    if skipped:
        report.notes.append(f"{skipped} history rows referenced users that are not in user_stats and were skipped")


def _holdings_perks_market(src, dst, report) -> None:
    for (item_id, name, emoji, base, cur, vol, desc, upd) in rows(src, "market_items", f"SELECT item_id, name, emoji, base_price, current_price, volatility, description, {col(src, 'market_items', 'last_updated', 'CURRENT_TIMESTAMP')} FROM market_items"):
        dst.execute("INSERT INTO market_items (item_id, name, emoji, base_price, current_price, volatility, description, last_updated) VALUES (?,?,?,?,?,?,?,?)",
                    [item_id, name, emoji, base, cur, vol, desc, str(upd)])
    dst.execute("DELETE FROM market_items WHERE 0")   # (no-op; keeps the statement list explicit)
    for r in rows(src, "market_price_history", "SELECT item_id, price, CAST(recorded_at AS TEXT) FROM market_price_history ORDER BY id"):
        dst.execute("INSERT INTO market_prices (item_id, price, recorded_at) VALUES (?,?,?)", list(r))
    for r in rows(src, "user_holdings", "SELECT id, user_id, item_id, quantity, purchase_price, CAST(purchased_at AS TEXT), CAST(expires_at AS TEXT) FROM user_holdings ORDER BY id"):
        dst.execute("INSERT INTO holdings (id, user_id, item_id, quantity, purchase_price, purchased_at, expires_at) VALUES (?,?,?,?,?,?,?)", list(r))
    for r in rows(src, "user_perks", "SELECT user_id, perk_type, CAST(expires_at AS TEXT) FROM user_perks"):
        dst.execute("INSERT INTO perks (user_id, perk, expires_at) VALUES (?,?,?)", list(r))
    for t, d in (("market_items", "market_items"), ("market_price_history", "market_prices"), ("user_holdings", "holdings"), ("user_perks", "perks")):
        report.counts[d] = count(dst, d)


def _media(src, dst, report) -> None:
    sql = f"""SELECT shortcut, user_id, {col(src, 'local_media', 'storage_type', "'local'")}, media_type, file_path,
                     {col(src, 'local_media', 'discord_id')}, {col(src, 'local_media', 'discord_name')},
                     COALESCE({col(src, 'local_media', 'animated', '0')}, 0), source_url, CAST(created_at AS TEXT)
              FROM local_media"""
    for r in rows(src, "local_media", sql):
        dst.execute("""INSERT INTO media (shortcut, owner_id, storage_type, media_type, location, discord_id, discord_name,
                                          animated, source_url, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    [r[0], r[1], r[2] or "local", r[3], r[4], r[5], r[6], r[7], r[8], r[9]])
    for r in rows(src, "app_emojis", "SELECT emoji_id, name, original_id, COALESCE(animated,0), CAST(last_used AS TEXT) FROM app_emojis"):
        dst.execute("INSERT INTO app_emojis (emoji_id, name, original_id, animated, last_used) VALUES (?,?,?,?,?)", list(r))
    report.counts["media"] = count(dst, "media")
    report.counts["app_emojis"] = count(dst, "app_emojis")


def _games(src, dst, report) -> None:
    for gid, uid, guild, correct, total, avg, boli, ts in rows(src, "fff_scores", "SELECT game_id, user_id, guild_id, correct_answers, total_questions, avg_response_ms, boli_awarded, CAST(played_at AS TEXT) FROM fff_scores ORDER BY id"):
        dst.execute("INSERT INTO game_results (game, user_id, guild_id, game_id, score, details, played_at) VALUES ('fff',?,?,?,?,?,?)",
                    [uid, guild, gid, correct, json.dumps({"total_questions": total, "avg_response_ms": avg, "boli_awarded": boli}), ts])
    for gid, uid, guild, streak, diff, cat, boli, ts in rows(src, "survival_scores", "SELECT game_id, user_id, guild_id, streak, difficulty, category, boli_awarded, CAST(played_at AS TEXT) FROM survival_scores ORDER BY id"):
        dst.execute("INSERT INTO game_results (game, user_id, guild_id, game_id, score, details, played_at) VALUES ('survival',?,?,?,?,?,?)",
                    [uid, guild, gid, streak, json.dumps({"difficulty": diff, "category": cat, "boli_awarded": boli}), ts])
    report.counts["game_results"] = count(dst, "game_results")


def _history_events(src, dst, report) -> None:
    for uid, text, ts in rows(src, "user_prediction_history", "SELECT user_id, prediction_text, CAST(timestamp AS TEXT) FROM user_prediction_history ORDER BY id"):
        dst.execute("INSERT INTO prediction_history (user_id, text, created_at) VALUES (?,?,?)", [uid, text, ts])
    for uid, cmd, sub, ch, guild, lat, cache, ts in rows(src, "command_events", "SELECT user_id, command, subcommand, channel_id, guild_id, latency_ms, used_cache, CAST(timestamp AS TEXT) FROM command_events ORDER BY id"):
        info = {k: v for k, v in (("sub", sub), ("cache", cache or None)) if v}
        dst.execute("INSERT INTO events (kind, user_id, guild_id, channel_id, name, detail, latency_ms, created_at) VALUES ('command',?,?,?,?,?,?,?)",
                    [uid, guild, ch, cmd, json.dumps(info) if info else None, lat, ts])
    for etype, detail, ts in rows(src, "session_events", "SELECT event_type, detail, CAST(timestamp AS TEXT) FROM session_events ORDER BY id"):
        dst.execute("INSERT INTO events (kind, name, detail, created_at) VALUES ('session',?,?,?)", [etype, detail, ts])
    for key, hit, cmd, lat, err, ts in rows(src, "api_call_log", "SELECT key_used, cache_hit, command, latency_ms, error, CAST(timestamp AS TEXT) FROM api_call_log ORDER BY id"):
        dst.execute("INSERT INTO events (kind, name, detail, latency_ms, created_at) VALUES ('llm_call',?,?,?,?)",
                    [cmd, json.dumps({"key": key, "cache_hit": bool(hit), "error": err}), lat, ts])
    report.counts["prediction_history"] = count(dst, "prediction_history")
    report.counts["events"] = count(dst, "events")


def _content_knowledge(src, dst, report) -> None:
    for ctype, text, ts in rows(src, "predictions_cache", "SELECT cache_type, template_text, CAST(timestamp AS TEXT) FROM predictions_cache ORDER BY id"):
        dst.execute("INSERT OR IGNORE INTO content (kind, text, status, source, created_at) VALUES (?,?, 'active', 'migrated', ?)",
                    [CONTENT_KIND.get(ctype, ctype), text, ts])
    for game, bucket, comment in rows(src, "gemini_score_comments", "SELECT game_type, score_bucket, comment FROM gemini_score_comments ORDER BY id"):
        dst.execute("INSERT OR IGNORE INTO content (kind, key, text, status, source) VALUES ('score_comment',?,?, 'active', 'migrated')",
                    [f"{game}:{bucket * 10}", comment])
    for (text,) in rows(src, "movie_dialogues", "SELECT dialogue FROM movie_dialogues ORDER BY id"):
        dst.execute("INSERT OR IGNORE INTO content (kind, text, status, source) VALUES ('movie_dialogue',?, 'active', 'migrated')", [text])
    for r in rows(src, "local_knowledge", "SELECT id, category, term, description, COALESCE(tags,'') FROM local_knowledge ORDER BY id"):
        dst.execute("INSERT OR IGNORE INTO knowledge (id, category, term, description, tags, status) VALUES (?,?,?,?,?, 'active')", list(r))
    report.counts["content"] = count(dst, "content")
    report.counts["knowledge"] = count(dst, "knowledge")


def _settings(src, dst, report) -> None:
    mapped, dropped, reset = 0, 0, 0
    for key, vstr, vfloat, vint in rows(src, "bot_config", "SELECT key, value_str, value_float, value_int FROM bot_config"):
        if key in INTENTIONALLY_DROPPED:
            dropped += 1
            continue
        setting = BY_LEGACY.get(key)
        if setting is None:
            raise MigrationError(f"bot_config key {key!r} is neither mapped to a setting nor listed as intentionally dropped")
        if key in RESET_ON_MIGRATE:
            reset += 1
            continue
        raw = vfloat if vfloat is not None else vint if vint is not None else vstr
        if raw is None:
            continue
        value = bool(raw) if setting.kind == "bool" else float(raw) if setting.kind == "float" else int(raw) if setting.kind == "int" else raw
        dst.execute("INSERT INTO settings (key, value) VALUES (?, ?)", [setting.key, json.dumps(value)])
        mapped += 1
    guilds = [r[0] for r in rows(src, "testing_guilds", "SELECT guild_id FROM testing_guilds ORDER BY guild_id")]
    if guilds:
        dst.execute("INSERT INTO settings (key, value) VALUES ('system.testing_guilds', ?)", [json.dumps(guilds)])
    report.counts["settings"] = count(dst, "settings")
    report.notes.append(f"settings: {mapped} mapped, {dropped} intentionally dropped, {reset} reset to default (seed drift)")


# ----------------------------------------------------------------------------- verification

def legacy_top(src: sqlite3.Connection, limit: int = 10) -> dict[str, list]:
    """The old leaderboard queries (with a user_id tiebreak so ties are comparable)."""
    out = {}
    out["overall"] = [
        (r[0], r[1]) for r in src.execute(
            """SELECT u.username, u.boli_points + COALESCE((SELECT SUM(points) FROM external_boli_points e WHERE e.user_id = u.user_id), 0) AS t
               FROM user_stats u ORDER BY t DESC, u.user_id ASC LIMIT ?""" if "external_boli_points" in tables(src) else
            "SELECT username, boli_points AS t FROM user_stats ORDER BY t DESC, user_id ASC LIMIT ?", [limit])]
    names = {r[0]: r[1] for r in src.execute("SELECT user_id, username FROM user_stats")}
    names.update(log_only_users(src))
    for key, table, col_, extra in (("cursed", "curse_logs", "curse_used", "WHERE curse_used NOT LIKE 'backfire_%' AND curse_used NOT LIKE 'proxy_%'"),
                                    ("blessed", "bless_logs", "bless_used", "")):
        out[key] = ([(names.get(r[0], ""), r[1]) for r in src.execute(
            f"SELECT user_id, COUNT(*) h FROM {table} {extra} GROUP BY user_id ORDER BY h DESC, user_id ASC LIMIT ?", [limit])]
            if table in tables(src) else [])
    guilds = {r[0] for r in rows(src, "fff_scores", "SELECT DISTINCT guild_id FROM fff_scores")} | {None}
    out["fff"] = {g: [(r[0], r[1], r[2]) for r in rows(src, "fff_scores",
        f"""SELECT username, correct_answers, avg_response_ms FROM fff_scores {'WHERE guild_id = ?' if g is not None else ''}
            ORDER BY correct_answers DESC, avg_response_ms ASC NULLS LAST, user_id ASC, id ASC LIMIT ?""",
        ([g] if g is not None else []) + [limit])] for g in guilds}
    guilds = {r[0] for r in rows(src, "survival_scores", "SELECT DISTINCT guild_id FROM survival_scores")} | {None}
    out["survival"] = {g: [(r[0], r[1]) for r in rows(src, "survival_scores",
        f"""SELECT username, streak FROM survival_scores {'WHERE guild_id = ?' if g is not None else ''}
            ORDER BY streak DESC, user_id ASC, id ASC LIMIT ?""",
        ([g] if g is not None else []) + [limit])] for g in guilds}
    return out


def verify(src: sqlite3.Connection, dst: sqlite3.Connection) -> list[str]:
    """Return a list of broken invariants (empty = all good)."""
    bad: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            bad.append(msg)

    # 1. users and per-user numbers
    want_users = count(src, "user_stats") + len(log_only_users(src))
    check(want_users == count(dst, "users"), f"user count {want_users} != {count(dst, 'users')}")
    ext = {r[0]: r[1] for r in rows(src, "external_boli_points", "SELECT user_id, SUM(points) FROM external_boli_points GROUP BY user_id")}
    strikes = col(src, "user_stats", "strikes", "0")
    new = {r[0]: r[1:] for r in dst.execute("SELECT user_id, boli_points, partner_points, experience, strikes, prediction_count FROM users")}
    for uid, boli, xp, st, preds in src.execute(f"SELECT user_id, COALESCE(boli_points,0), COALESCE(experience,0), COALESCE({strikes},0), COALESCE(prediction_count,0) FROM user_stats"):
        want = (boli, ext.get(uid, 0) or 0, xp, st, preds)
        if new.get(uid) != want:
            bad.append(f"user {uid}: (native, partner, xp, strikes, predictions) {want} != {new.get(uid)}")
    # 2. ledger reconciles with balances, per user and pool
    for uid, boli, partner in dst.execute("SELECT user_id, boli_points, partner_points FROM users").fetchall():
        sums = {p: d for p, d in dst.execute("SELECT pool, COALESCE(SUM(delta),0) FROM points_ledger WHERE user_id = ? GROUP BY pool", [uid])}
        if sums.get("native", 0) != boli:
            bad.append(f"user {uid}: native ledger sum {sums.get('native', 0)} != balance {boli}")
        if sums.get("partner", 0) != partner:
            bad.append(f"user {uid}: partner ledger sum {sums.get('partner', 0)} != balance {partner}")
        xp_sum = dst.execute("SELECT COALESCE(SUM(xp_delta),0) FROM points_ledger WHERE user_id = ?", [uid]).fetchone()[0]
        xp = dst.execute("SELECT experience FROM users WHERE user_id = ?", [uid]).fetchone()[0]
        if xp_sum != xp:
            bad.append(f"user {uid}: xp ledger sum {xp_sum} != experience {xp}")
    # 3. equal counts
    for old, new_ in (("user_holdings", "holdings"), ("user_perks", "perks"), ("local_media", "media"), ("local_knowledge", "knowledge"),
                      ("market_items", "market_items"), ("market_price_history", "market_prices"), ("app_emojis", "app_emojis"),
                      ("user_prediction_history", "prediction_history")):
        check(count(src, old) == count(dst, new_), f"{old} {count(src, old)} != {new_} {count(dst, new_)}")
    # 4. game results
    want = count(src, "fff_scores") + count(src, "survival_scores")
    check(count(dst, "game_results") == want, f"game_results {count(dst, 'game_results')} != fff+survival {want}")
    # events and content (content can only shrink through exact-duplicate text)
    want = count(src, "command_events") + count(src, "session_events") + count(src, "api_call_log")
    check(count(dst, "events") == want, f"events {count(dst, 'events')} != {want}")
    max_content = count(src, "predictions_cache") + count(src, "gemini_score_comments") + count(src, "movie_dialogues")
    seeds = dst.execute("SELECT COUNT(*) FROM content WHERE source = 'seed'").fetchone()[0]
    check(count(dst, "content") - seeds <= max_content, f"content {count(dst, 'content') - seeds} vs {max_content}")
    # curse / bless history rows
    want = count(src, "curse_logs")
    got = dst.execute("SELECT COUNT(*) FROM points_ledger WHERE reason IN ('curse_received','curse_backfire','curse_self')").fetchone()[0]
    check(got == want, f"curse history rows {got} != {want}")
    check(dst.execute("SELECT COUNT(*) FROM points_ledger WHERE reason = 'bless_received'").fetchone()[0] == count(src, "bless_logs"), "bless history rows differ")
    # 5. leaderboards (top 10)
    old_top = legacy_top(src)
    legacy_ids = [r[0] for r in src.execute("SELECT user_id FROM user_stats")]
    marks = ",".join("?" * len(legacy_ids))
    new_overall = [(r[0], r[1]) for r in dst.execute(   # log-only users are excluded: they never appeared on this board
        f"SELECT display_name, boli_points + partner_points AS t FROM users WHERE user_id IN ({marks}) "
        "ORDER BY t DESC, user_id ASC LIMIT 10", legacy_ids)] if legacy_ids else []
    check(old_top["overall"] == new_overall, "overall leaderboard differs")
    check(old_top["cursed"] == [(r["username"], r["hits"]) for r in points_repo.get_curse_leaderboard(dst, 10)], "most-cursed leaderboard differs")
    check(old_top["blessed"] == [(r["username"], r["hits"]) for r in points_repo.get_bless_leaderboard(dst, 10)], "most-blessed leaderboard differs")
    for g, want_rows in old_top["fff"].items():
        got_rows = [(r["username"], r["correct_answers"], r["avg_response_ms"]) for r in games_repo.get_fff_leaderboard(dst, g or 0, 10, global_scope=g is None)]
        check([x[1:] for x in want_rows] == [x[1:] for x in got_rows], f"FFF leaderboard differs (guild {g})")
    for g, want_rows in old_top["survival"].items():
        got_rows = [(r["username"], r["streak"]) for r in games_repo.get_survival_leaderboard(dst, g or 0, 10, global_scope=g is None)]
        check([x[1:] for x in want_rows] == [x[1:] for x in got_rows], f"Survival leaderboard differs (guild {g})")
    # 6. every bot_config key is mapped or intentionally dropped
    for (key,) in rows(src, "bot_config", "SELECT key FROM bot_config"):
        check(key in INTENTIONALLY_DROPPED or key in BY_LEGACY, f"bot_config key {key!r} unaccounted for")
    return bad


# ----------------------------------------------------------------------------- CLI

def run(src_path: Path, dst_path: Path, privacy_path: Path) -> Report:
    for p in (dst_path, privacy_path):
        if p.exists():
            raise MigrationError(f"{p} already exists; refusing to overwrite (delete it yourself if you mean to redo the migration)")
    src = open_source(src_path)
    report = Report()
    dst = connect(dst_path)
    migrate(dst)
    try:
        migrate_database(src, dst, report)
    except Exception:
        dst.close()
        dst_path.unlink(missing_ok=True)
        raise
    connect_privacy(privacy_path).close()
    report.failures = verify(src, dst)
    dst.close()
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--dst", required=True, type=Path)
    ap.add_argument("--privacy", required=True, type=Path)
    args = ap.parse_args(argv)
    try:
        report = run(args.src, args.dst, args.privacy)
    except MigrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(report.render())
    if report.failures:
        print(f"\n{len(report.failures)} invariant(s) FAILED - do not use {args.dst}", file=sys.stderr)
        return 1
    print("\nAll invariants hold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
