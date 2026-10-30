#!/usr/bin/env bash
# One-off, at cutover: upload the migrated databases so the first boot has something to start from.
# Usage: scripts/seed-db.sh [dir]   (default dir: data/v2, containing navi.db and privacy.db)
source "$(dirname "$0")/lib.sh"
DIR="${1:-data/v2}"
BUCKET="$(aws ssm get-parameter --name "${PREFIX}/bucket" --query Parameter.Value --output text)"
for f in navi.db privacy.db; do
  [ -f "$DIR/$f" ] || { echo "missing $DIR/$f (run tools/migrate_v2.py first)" >&2; exit 1; }
done
aws s3 cp "$DIR/navi.db"    "s3://${BUCKET}/seed/navi.db"
aws s3 cp "$DIR/privacy.db" "s3://${BUCKET}/seed/privacy.db"
[ -d data/local_media ] && echo "Media: aws s3 sync data/local_media s3://${BUCKET}/media/ (then register them as storage_type 's3' during the cutover)"
