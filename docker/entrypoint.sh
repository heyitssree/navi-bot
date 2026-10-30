#!/bin/sh
# Container entrypoint: restore the databases from S3 (Litestream), then run the bot under `litestream replicate`.
# Local runs keep working with LITESTREAM_ENABLED=0 (or unset): the bot just starts.
set -eu
DB="${DB_PATH:-/app/data/navi.db}"
PDB="${PRIVACY_DB_PATH:-/app/data/privacy.db}"

if [ "${LITESTREAM_ENABLED:-0}" = "1" ]; then
  # A replaced instance starts with an empty disk: pull the latest replica of each database.
  for f in "$DB" "$PDB"; do
    litestream restore -config /etc/litestream.yml -if-db-not-exists -if-replica-exists "$f"
  done
  # First boot after the migration: no replica exists yet, so use the seeded file from s3://<bucket>/seed/
  for f in "$DB" "$PDB"; do
    [ -f "$f" ] || aws s3 cp "s3://${NAVI_BUCKET}/seed/$(basename "$f")" "$f" || true
  done
  # `litestream replicate -exec` forwards SIGTERM to the bot, waits for it to exit, then does a final sync.
  exec litestream replicate -config /etc/litestream.yml -exec "python -m navi"
fi
exec python -m navi
