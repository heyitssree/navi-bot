"""Print row counts per table plus a few aggregates.

Usage: python -m tools.db_report [path]   (default: $DB_PATH or data/dev/navi_dev.db)
Opens the database read-only, so it is safe to run against any copy.
"""
from __future__ import annotations

import os
import sqlite3
import sys


def report(path: str) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    counts = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}

    def one(sql: str):
        try:
            return conn.execute(sql).fetchone()[0]
        except sqlite3.Error:
            return None

    aggregates = {
        "users": one("SELECT COUNT(*) FROM user_stats"),
        "sum_boli_native": one("SELECT COALESCE(SUM(boli_points),0) FROM user_stats"),
        "sum_boli_external": one("SELECT COALESCE(SUM(points),0) FROM external_boli_points"),
        "sum_experience": one("SELECT COALESCE(SUM(experience),0) FROM user_stats"),
        "sum_extra_actions": one("SELECT COALESCE(SUM(extra_actions),0) FROM user_stats"),
        "media_rows": one("SELECT COUNT(*) FROM local_media"),
        "knowledge_rows": one("SELECT COUNT(*) FROM local_knowledge"),
    }
    conn.close()
    return {"tables": counts, "aggregates": aggregates}


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else os.getenv("DB_PATH", "data/dev/navi_dev.db")
    data = report(path)
    print(f"Database: {path}  ({len(data['tables'])} tables)")
    width = max((len(t) for t in data["tables"]), default=10)
    for name, n in data["tables"].items():
        print(f"  {name:<{width}}  {n:>9,}")
    print("Aggregates:")
    for k, v in data["aggregates"].items():
        print(f"  {k:<20} {v}")


if __name__ == "__main__":
    main()
