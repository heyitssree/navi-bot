# navi/services/media_store.py - where saved media files live: the local disk (storage_type 'local') or the bot's S3 bucket
# (storage_type 's3', location = object key under media/). On AWS the disk is replaced with the instance, so files that must
# survive are kept in S3; tools/media_to_s3.py moves existing local files there during the cutover.

from __future__ import annotations

import asyncio
import io
import logging
import os

import discord

logger = logging.getLogger("navi.services.media_store")

_client = None


def _s3():
    global _client
    if _client is None:
        import boto3

        _client = boto3.client("s3")
    return _client


def object_key(shortcut: str, filename: str) -> str:
    ext = os.path.splitext(filename)[1] or ".bin"
    return f"media/{shortcut}{ext}"


async def load_file(ctx, entry: dict, filename: str | None = None) -> discord.File | None:
    """The media file as a discord.File, or None when it is missing (local file gone / S3 object or bucket unavailable)."""
    location = entry.get("file_path") or ""
    name = filename or os.path.basename(location) or entry.get("shortcut", "media")
    if entry.get("storage_type") == "s3":
        bucket = ctx.config.bucket
        if not bucket or not location:
            return None
        try:
            obj = await asyncio.get_running_loop().run_in_executor(None, lambda: _s3().get_object(Bucket=bucket, Key=location))
            data = await asyncio.get_running_loop().run_in_executor(None, obj["Body"].read)
        except Exception as exc:
            logger.warning("Could not read s3://%s/%s: %s", bucket, location, exc)
            return None
        return discord.File(io.BytesIO(data), filename=name)
    if location and os.path.isfile(location):
        return discord.File(location)
    return None


def upload_file(bucket: str, key: str, path: str) -> None:
    _s3().upload_file(path, bucket, key)


def delete_objects(bucket: str, keys: list[str]) -> int:
    """Delete S3 objects (used by /privacy opt_out). Returns how many were requested; failures are logged."""
    removed = 0
    for key in keys:
        try:
            _s3().delete_object(Bucket=bucket, Key=key)
            removed += 1
        except Exception as exc:
            logger.warning("Could not delete s3://%s/%s: %s", bucket, key, exc)
    return removed
