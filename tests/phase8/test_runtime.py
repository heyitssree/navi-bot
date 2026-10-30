"""Phase 8 runtime pieces: SSM config loading, heartbeat, SIGTERM, S3 media, container files."""
import asyncio
import io
import os
import signal
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import boto3
import pytest
import yaml
from botocore.stub import Stubber

from navi.config import Config, load_ssm_parameters
from navi.services import heartbeat, media_store
from tests.legacy.harness import FakeUser, make_ctx, make_message
from tests.phase6.helpers import interaction

ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------------------ SSM configuration

class FakeSSM:
    def __init__(self, params):
        self.params = params
        self.calls = []

    def get_parameters_by_path(self, **kw):
        self.calls.append(kw)
        return {"Parameters": [{"Name": n, "Value": v} for n, v in self.params.items()]}


def test_ssm_names_are_upper_cased_and_infrastructure_keys_skipped(monkeypatch):
    names = ["DISCORD_TOKEN", "GEMINI_API_KEY_FREE", "OWNER_ID", "IMAGE_URI", "RUN_ENABLED", "BUCKET", "NAVI_SSM_PREFIX"]
    for k in names:
        monkeypatch.delenv(k, raising=False)
    ssm = FakeSSM({"/navi/prod/discord_token": "tok", "/navi/prod/gemini_api_key_free": "g", "/navi/prod/owner_id": "42",
                   "/navi/prod/image_uri": "x.dkr.ecr/y:1", "/navi/prod/run_enabled": "true", "/navi/prod/bucket": "b"})
    assert load_ssm_parameters("/navi/prod", client=ssm) == 3
    assert (os.environ["DISCORD_TOKEN"], os.environ["GEMINI_API_KEY_FREE"], os.environ["OWNER_ID"]) == ("tok", "g", "42")
    assert "IMAGE_URI" not in os.environ and "RUN_ENABLED" not in os.environ and "BUCKET" not in os.environ
    assert ssm.calls[0]["Path"] == "/navi/prod/" and ssm.calls[0]["WithDecryption"] is True
    for k in names:
        monkeypatch.delenv(k, raising=False)


def test_environment_wins_over_ssm_and_config_reads_the_new_variables(monkeypatch):
    monkeypatch.setenv("NAVI_BUCKET", "my-bucket")
    monkeypatch.setenv("DISCORD_TOKEN", "local")
    load_ssm_parameters("/navi/prod", client=FakeSSM({"/navi/prod/discord_token": "from-ssm"}))
    cfg = Config.from_env()
    assert cfg.discord_token == "local" and cfg.bucket == "my-bucket"


def test_ssm_is_only_used_when_a_prefix_is_set(monkeypatch):
    monkeypatch.delenv("NAVI_SSM_PREFIX", raising=False)
    called = []
    monkeypatch.setattr("navi.config.load_ssm_parameters", lambda prefix, client=None: called.append(prefix))
    Config.from_env()
    assert called == []
    monkeypatch.setenv("NAVI_SSM_PREFIX", "/navi/test")
    Config.from_env()
    assert called == ["/navi/test"]


# ------------------------------------------------------------------------------ heartbeat

def test_heartbeat_metric_shape():
    cw = MagicMock()
    heartbeat.put_heartbeat("prod", client=cw)
    cw.put_metric_data.assert_called_once()
    kwargs = cw.put_metric_data.call_args.kwargs
    assert kwargs["Namespace"] == "Navi"
    assert kwargs["MetricData"][0] == {"MetricName": "Heartbeat", "Dimensions": [{"Name": "Env", "Value": "prod"}], "Value": 1.0, "Unit": "Count"}


async def test_heartbeat_loop_publishes_repeatedly_and_survives_failures():
    cw = MagicMock()
    cw.put_metric_data.side_effect = [RuntimeError("throttled"), None, None]
    task = asyncio.create_task(heartbeat.heartbeat_loop("prod", client=cw, interval=0.01))
    await asyncio.sleep(0.15)
    task.cancel()
    assert cw.put_metric_data.call_count >= 3


async def test_heartbeat_loop_is_a_noop_without_navi_env(monkeypatch):
    monkeypatch.delenv("NAVI_ENV", raising=False)
    cw = MagicMock()
    await asyncio.wait_for(heartbeat.heartbeat_loop(None, client=cw), timeout=1)
    assert cw.put_metric_data.call_count == 0


def test_heartbeat_task_is_started_only_on_aws():
    text = (ROOT / "navi/app.py").read_text()
    assert 'if os.getenv("NAVI_ENV"):' in text and 'start_task(ctx, "heartbeat"' in text


# ------------------------------------------------------------------------------ SIGTERM and logging

async def test_sigterm_closes_the_bot_cleanly():
    from navi.app import build
    from tests.legacy.harness import make_config

    bot, ctx = build(make_config())
    loop = asyncio.get_running_loop()
    registered = {}
    original = loop.add_signal_handler
    loop.add_signal_handler = lambda sig, cb, *a: registered.update({sig: cb})
    try:
        await bot.setup_hook()
    finally:
        loop.add_signal_handler = original
    assert signal.SIGTERM in registered
    closed = []

    async def fake_close():
        closed.append(1)

    bot.close = fake_close
    registered[signal.SIGTERM]()
    await asyncio.sleep(0.05)
    assert closed == [1]


def test_log_to_file_can_be_switched_off(tmp_path, monkeypatch):
    import logging

    from navi.app import configure_logging

    root = logging.getLogger()
    saved = root.handlers[:]
    root.handlers.clear()
    monkeypatch.chdir(tmp_path)
    try:
        monkeypatch.setenv("LOG_TO_FILE", "0")
        configure_logging()
        assert not (tmp_path / "logs").exists() and not any(isinstance(h, logging.FileHandler) for h in root.handlers)
        root.handlers.clear()
        monkeypatch.delenv("LOG_TO_FILE")
        configure_logging()
        assert (tmp_path / "logs" / "bot.log").exists()
    finally:
        for h in root.handlers:
            h.close()
        root.handlers[:] = saved


# ------------------------------------------------------------------------------ S3 media

class Bucket:
    def __init__(self, objects=None):
        self.objects = objects or {}
        self.deleted = []

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise RuntimeError("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[Key])}

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)


@pytest.fixture()
def s3(monkeypatch):
    fake = Bucket({"media/lol.png": b"PNGDATA"})
    monkeypatch.setattr(media_store, "_s3", lambda: fake)
    return fake


async def test_load_file_reads_s3_objects_and_local_files(db, tmp_path, s3):
    ctx = make_ctx(db, bucket="bkt")
    f = await media_store.load_file(ctx, {"storage_type": "s3", "file_path": "media/lol.png", "shortcut": "lol"})
    assert f.filename == "lol.png" and f.fp.read() == b"PNGDATA"
    assert await media_store.load_file(ctx, {"storage_type": "s3", "file_path": "media/gone.png", "shortcut": "x"}) is None
    local = tmp_path / "a.png"; local.write_bytes(b"x")
    assert (await media_store.load_file(ctx, {"storage_type": "local", "file_path": str(local)})).filename == "a.png"
    assert await media_store.load_file(ctx, {"storage_type": "local", "file_path": str(tmp_path / "nope.png")}) is None
    no_bucket = make_ctx(db)
    assert await media_store.load_file(no_bucket, {"storage_type": "s3", "file_path": "media/lol.png"}) is None


async def test_shortcut_handler_sends_an_s3_file(db, s3):
    from navi.db.repos.media import save_local_media
    from navi.db.repos.users import upsert_user
    from navi.handlers.shortcuts import handle_shortcut

    ctx = make_ctx(db, bucket="bkt")
    upsert_user(db, 1, "asha")
    save_local_media(db, 1, "lol", "media/lol.png", "emoji", storage_type="s3")
    msg = make_message(FakeUser(1, "asha"), ";;lol")
    assert await handle_shortcut(ctx, msg) is True
    sent = msg.channel.send.await_args.kwargs["file"]
    assert sent.fp.read() == b"PNGDATA"
    save_local_media(db, 1, "gone", "media/gone.png", "emoji", storage_type="s3")
    msg = make_message(FakeUser(1, "asha"), ";;gone")
    await handle_shortcut(ctx, msg)
    assert "missing" in msg.reply.await_args.args[0]


def test_opt_out_deletes_the_users_s3_objects(db, s3):
    from navi.db.repos.media import save_local_media
    from navi.db.repos.users import upsert_user

    ctx = make_ctx(db, bucket="bkt")
    upsert_user(db, 1, "asha"); upsert_user(db, 2, "ben")
    save_local_media(db, 1, "mine", "media/mine.png", "emoji", storage_type="s3")
    save_local_media(db, 2, "theirs", "media/theirs.png", "emoji", storage_type="s3")
    result = ctx.privacy.opt_out(ctx, 1)
    assert result.s3_keys == ["media/mine.png"] and s3.deleted == ["media/mine.png"]
    assert db.execute("SELECT shortcut FROM media").fetchall()[0][0] == "theirs"


def test_media_to_s3_tool_moves_existing_files_and_reports_missing(db, tmp_path):
    from navi.db.repos.media import save_local_media
    from navi.db.repos.users import upsert_user
    from tools.media_to_s3 import move_media

    upsert_user(db, 1, "asha")
    f = tmp_path / "one.png"; f.write_bytes(b"1")
    save_local_media(db, 1, "one", str(f), "emoji")
    save_local_media(db, 1, "ghost", str(tmp_path / "ghost.gif"), "emoji")
    save_local_media(db, 1, "emo", "", "emoji", storage_type="app_emoji", discord_id="9")
    uploads = []
    dry = move_media(db, "bkt", dry_run=True, uploader=lambda *a: uploads.append(a))
    assert dry == {"moved": ["one"], "missing": ["ghost"]} and uploads == []
    done = move_media(db, "bkt", uploader=lambda *a: uploads.append(a))
    assert done["moved"] == ["one"] and uploads == [("bkt", "media/one.png", str(f))]
    row = db.execute("SELECT storage_type, location FROM media WHERE shortcut='one'").fetchone()
    assert tuple(row) == ("s3", "media/one.png")
    assert db.execute("SELECT storage_type FROM media WHERE shortcut='emo'").fetchone()[0] == "app_emoji"       # untouched


# ------------------------------------------------------------------------------ container files

def test_litestream_config_replicates_both_databases_with_72h_retention():
    cfg = yaml.safe_load((ROOT / "docker/litestream.yml").read_text())
    assert cfg["snapshot"] == {"interval": "24h", "retention": "72h"}
    assert [d["path"] for d in cfg["dbs"]] == ["${DB_PATH}", "${PRIVACY_DB_PATH}"]
    assert [d["replica"]["path"] for d in cfg["dbs"]] == ["litestream/navi", "litestream/privacy"]
    assert all(d["replica"]["type"] == "s3" and d["replica"]["bucket"] == "${NAVI_BUCKET}" for d in cfg["dbs"])


def test_entrypoint_restores_then_replicates_and_falls_back_to_the_seed():
    text = (ROOT / "docker/entrypoint.sh").read_text()
    assert subprocess.run(["sh", "-n", str(ROOT / "docker/entrypoint.sh")]).returncode == 0
    assert text.index("litestream restore") < text.index("seed/") < text.index("exec litestream replicate")
    assert "-if-db-not-exists -if-replica-exists" in text and 'exec litestream replicate -config /etc/litestream.yml -exec "python -m navi"' in text
    assert text.strip().splitlines()[-1] == "exec python -m navi"                     # LITESTREAM_ENABLED=0: plain start


def test_entrypoint_runs_the_bot_directly_without_litestream(tmp_path):
    fake_python = tmp_path / "python"
    fake_python.write_text("#!/bin/sh\necho started \"$@\"\n"); fake_python.chmod(0o755)
    r = subprocess.run(["sh", str(ROOT / "docker/entrypoint.sh")], env={"PATH": f"{tmp_path}:/usr/bin:/bin", "LITESTREAM_ENABLED": "0"},
                       capture_output=True, text=True)
    assert r.stdout.strip() == "started -m navi"


def test_dockerfile_pins_litestream_maps_architectures_and_runs_unprivileged():
    text = (ROOT / "Dockerfile").read_text()
    assert "LITESTREAM_VERSION=0.5." in text and "x86_64" in text and "arm64" in text and "TARGETARCH" in text
    assert "useradd -r -u 10001" in text and "USER navi" in text and 'CMD ["/entrypoint.sh"]' in text
    assert "COPY navi/ navi/" in text and ".env" not in text.replace(".env*", "")


def test_dockerignore_keeps_secrets_and_data_out_of_the_image():
    ignored = (ROOT / ".dockerignore").read_text().split()
    for entry in (".env", ".env*", "*.db", "data/", ".git/", "infra/", "logs/"):
        assert entry in ignored, entry


def test_operator_scripts_never_take_secrets_as_arguments_or_print_them():
    text = (ROOT / "scripts/put-secrets.sh").read_text()
    assert "read -rsp" in text and "file:///dev/stdin" in text and "--value \"$v\"" not in text.replace("--value false", "")
    assert "run_enabled" in text and "SecureString" in text
    for name in ("deploy.sh", "enable.sh", "disable.sh", "seed-db.sh", "put-config.sh"):
        assert subprocess.run(["bash", "-n", str(ROOT / "scripts" / name)]).returncode == 0
    assert "--profile" not in (ROOT / "scripts/lib.sh").read_text() and 'AWS_PROFILE="${AWS_PROFILE:-navi}"' in (ROOT / "scripts/lib.sh").read_text()
