"""Importing any module must not connect to Discord or call an LLM."""
import importlib

import pytest

MODULES = [
    "schema", "prompts", "glossary", "curses", "slang_scorer", "template_resolver",
    "market_engine", "api_server", "services.api_manager", "services.gemini_service", "bot",
]


@pytest.mark.parametrize("name", MODULES)
def test_import_has_no_side_effects(name, monkeypatch):
    import socket

    def _no_net(*a, **k):
        raise AssertionError("network access during import of " + name)

    monkeypatch.setattr(socket.socket, "connect", _no_net)
    importlib.import_module(name)


def test_bot_not_connected_after_import():
    import bot

    assert bot.db_conn is None
    assert bot.api_mgr is None
    assert bot.bot.is_closed() is False
    assert bot.bot.user is None  # never logged in
