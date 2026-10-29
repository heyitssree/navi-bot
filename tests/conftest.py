"""Shared fixtures. Tests never touch data/navi.db or a live Discord/LLM connection."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Must be set before schema.py / bot.py are imported (they read these at import time).
_TMP = tempfile.mkdtemp(prefix="navi-tests-")
os.environ["DB_PATH"] = str(Path(_TMP) / "import.db")
for _k in ("DISCORD_TOKEN", "GEMINI_API_KEY_FREE", "GEMINI_API_KEY_PAID", "GEMINI_API_KEY"):
    os.environ[_k] = ""

import pytest  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A fresh, fully-migrated SQLite database per test."""
    import schema

    monkeypatch.setattr(schema, "DB_PATH", tmp_path / "test.db")
    conn = schema.init_db()
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _chdir_root(monkeypatch):
    monkeypatch.chdir(ROOT)
