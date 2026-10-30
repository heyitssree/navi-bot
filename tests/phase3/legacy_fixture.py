"""Builds a populated pre-v2 database (28 tables) for migration tests."""
import sqlite3

from tools.legacy_schema import apply


def build(path):
    c = sqlite3.connect(path)
    apply(c)
    c.executemany(
        "INSERT INTO user_stats (user_id, username, rashi, boli_points, experience, prediction_count, extra_actions, strikes,"
        " daily_action_count, last_action_date, daily_refill_count, last_refill_date, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (1, "asha", "Mesham", 120, 300, 5, 2, 1, 7, "2026-10-29", 1, "2026-10-29", "2026-10-29 10:00:00"),
            (2, "ben", "Edavam", -15, 40, 0, 0, 0, 0, None, 0, None, "2026-10-28 09:00:00"),
            (3, "chitra", None, 800, 900, 12, 0, 0, 0, None, 0, None, "2026-10-29 12:00:00"),
            (4, "dev", "Karkidakam", 0, 0, 0, 0, 0, 0, None, 0, None, "2026-10-01 00:00:00"),
        ],
    )
    # partner points (one user also has a negative deduction); user 99 is not in user_stats
    c.executemany(
        "INSERT INTO external_boli_points (user_id, username, points, source_game, game_id, awarded_at) VALUES (?,?,?,?,?,?)",
        [(1, "asha", 50, "wordle", "g1", "2026-10-20 10:00:00"), (1, "asha", -10, "wordle", "g2", "2026-10-21 10:00:00"),
         (3, "chitra", 30, "bamboozled", "g3:3", "2026-10-22 10:00:00"), (99, "ghost", 5, "wordle", "g4", "2026-10-22 10:00:00")],
    )
    c.executemany(
        "INSERT INTO partner_score_log (game_id, user_id, guild_id, username, raw_points, boli_awarded, xp_awarded, game_type) VALUES (?,?,?,?,?,?,?,?)",
        [("g1", 1, 7, "asha", 50, 50, 5, "wordle"), ("g2", 1, 7, "asha", -10, -10, 0, "wordle"), ("g5", 2, 7, "ben", 0, 0, 0, "wordle")],
    )
    c.executemany("INSERT INTO gift_log (sender_id, recipient_id, amount, gifted_at) VALUES (?,?,?,?)",
                  [(3, 1, 40, "2026-10-25 10:00:00"), (1, 2, 5, "2026-10-26 10:00:00"), (3, 77, 9, "2026-10-26 11:00:00")])
    # 11 and 12 were cursed/blessed but never posted (not in user_stats)
    c.executemany("INSERT INTO curse_logs (user_id, username, curse_used, timestamp) VALUES (?,?,?,?)",
                  [(2, "ben", "madiyan", "2026-10-20 10:00:00"), (2, "ben", "kozhi", "2026-10-21 10:00:00"),
                   (2, "ben", "backfire_vattan", "2026-10-21 10:00:00"), (1, "asha", "proxy_navi_self", "2026-10-22 10:00:00"),
                   (1, "asha", "potion_vazha", "2026-10-22 11:00:00"), (1, "asha", "potion_backfire_oolan", "2026-10-22 12:00:00"),
                   (3, "chitra", "kozhi", "2026-10-23 10:00:00"), (11, "silent", "dushtan", "2026-10-23 11:00:00")])
    c.executemany("INSERT INTO bless_logs (user_id, username, bless_used, timestamp) VALUES (?,?,?,?)",
                  [(1, "asha", "muthe", "2026-10-20 10:00:00"), (1, "asha", "universal_blessing", "2026-10-21 10:00:00"),
                   (3, "chitra", "puli", "2026-10-22 10:00:00"), (12, "quiet", "poli", "2026-10-22 11:00:00")])
    c.executemany("INSERT INTO game_daily_counts (user_id, game_name, play_date, play_count) VALUES (?,?,?,?)",
                  [(1, "flip", "2026-10-29", 3), (1, "slots", "2026-10-29", 2)])
    c.execute("INSERT INTO navi_challenge_attempts (user_id, play_date, play_count) VALUES (1, '2026-10-29', 2)")
    c.execute("INSERT INTO type_race_attempts (user_id, play_date, play_count) VALUES (3, '2026-10-29', 1)")
    c.executemany("INSERT INTO fff_scores (game_id, user_id, guild_id, username, correct_answers, total_questions, avg_response_ms, boli_awarded) VALUES (?,?,?,?,?,?,?,?)",
                  [("f1", 1, 7, "asha", 8, 10, 900, 20), ("f2", 3, 7, "chitra", 8, 10, 700, 20), ("f3", 2, 8, "ben", 5, 10, None, 5)])
    c.executemany("INSERT INTO survival_scores (game_id, user_id, guild_id, username, streak, difficulty, category, boli_awarded) VALUES (?,?,?,?,?,?,?,?)",
                  [("s1", 1, 7, "asha", 12, "hard", None, 30), ("s2", 3, 7, "chitra", 12, "hard", "movies", 30), ("s3", 3, 8, "chitra", 4, "easy", None, 4)])
    c.execute("INSERT INTO user_holdings (user_id, item_id, quantity, purchase_price, purchased_at, expires_at) VALUES (1, 'banana_republic', 3, 40, '2026-10-28 10:00:00', '2026-11-04 10:00:00')")
    c.execute("INSERT INTO user_perks (user_id, perk_type, expires_at) VALUES (1, 'curse_protection', '2026-12-01 00:00:00')")
    c.execute("INSERT INTO market_price_history (item_id, price, recorded_at) VALUES ('banana_republic', 41, '2026-10-28')")
    c.executemany("INSERT INTO local_media (shortcut, user_id, file_path, media_type, source_url, storage_type, discord_id, discord_name, animated) VALUES (?,?,?,?,?,?,?,?,?)",
                  [("lol", 1, "data/local_media/lol.png", "emoji", None, "local", None, None, 0),
                   ("dance", 3, "", "emoji", "http://x", "app_emoji", "123", "dance", 1)])
    c.execute("INSERT INTO app_emojis (emoji_id, name, animated) VALUES ('123', 'dance', 1)")
    c.executemany("INSERT INTO user_prediction_history (user_id, prediction_text) VALUES (?,?)", [(1, f"p{i}") for i in range(25)])
    c.executemany("INSERT INTO predictions_cache (cache_type, user_id, template_text) VALUES (?,?,?)",
                  [("navi", 1, "doom {user}"), ("navi", 1, "gloom {user}"), ("curse", 2, "{user} {curse}")])
    c.execute("INSERT INTO gemini_score_comments (game_type, score_bucket, comment) VALUES ('navi_challenge', 7, 'nice')")
    c.execute("INSERT INTO movie_dialogues (dialogue) VALUES ('some line')")
    c.execute("INSERT INTO command_events (user_id, username, command, subcommand) VALUES (1, 'asha', 'navi', NULL)")
    c.execute("INSERT INTO session_events (event_type, detail) VALUES ('start', NULL)")
    c.execute("INSERT INTO api_call_log (key_used, cache_hit, command) VALUES ('free', 0, 'navi')")
    c.execute("INSERT INTO testing_guilds (guild_id) VALUES (555)")
    c.execute("UPDATE bot_config SET value_float = 0.4 WHERE key = 'curse_reply_chance'")
    c.execute("INSERT OR REPLACE INTO bot_config (key, value_float) VALUES ('backfire_chance_mild', 0.3)")
    c.execute("INSERT OR REPLACE INTO bot_config (key, value_str) VALUES ('lucky_draw_last_date', '2026-10-29')")
    c.execute("INSERT OR REPLACE INTO bot_config (key, value_int) VALUES ('feature_gambling', 0)")
    c.commit()
    c.close()
    return path
