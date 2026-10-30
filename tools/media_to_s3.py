"""Cutover helper: move saved media files from the local disk to the bot's S3 bucket.

    python -m tools.media_to_s3 --db data/v2/navi.db --bucket <bucket> [--dry-run]

For every media row with storage_type 'local' whose file exists, the file is uploaded to s3://<bucket>/media/<shortcut>.<ext>
and the row becomes storage_type 's3' with location = that key. Rows whose file is missing are reported and left alone.
Run it on the MIGRATED database (data/v2/navi.db) before scripts/seed-db.sh uploads that database.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from navi.services.media_store import object_key, upload_file


def move_media(db: sqlite3.Connection, bucket: str, *, dry_run: bool = False, uploader=upload_file) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {"moved": [], "missing": []}
    rows = db.execute("SELECT shortcut, location FROM media WHERE storage_type = 'local' AND location IS NOT NULL AND location != ''").fetchall()
    for shortcut, location in rows:
        if not Path(location).is_file():
            result["missing"].append(shortcut)
            continue
        key = object_key(shortcut, location)
        if not dry_run:
            uploader(bucket, key, location)
            db.execute("UPDATE media SET storage_type = 's3', location = ? WHERE shortcut = ?", [key, shortcut])
        result["moved"].append(shortcut)
    if not dry_run:
        db.commit()
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    db = sqlite3.connect(args.db)
    result = move_media(db, args.bucket, dry_run=args.dry_run)
    print(f"{'Would move' if args.dry_run else 'Moved'} {len(result['moved'])} file(s); {len(result['missing'])} missing on disk: {result['missing']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
