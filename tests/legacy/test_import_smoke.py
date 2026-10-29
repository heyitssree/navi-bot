"""Importing any module must not connect to Discord or call an LLM."""
import importlib
import pkgutil

import pytest

import navi

MODULES = sorted(m.name for m in pkgutil.walk_packages(navi.__path__, "navi.") if m.name != "navi.__main__")


@pytest.mark.parametrize("name", MODULES)
def test_import_has_no_side_effects(name, monkeypatch):
    import socket

    def _no_net(*a, **k):
        raise AssertionError("network access during import of " + name)

    monkeypatch.setattr(socket.socket, "connect", _no_net)
    importlib.import_module(name)


def test_build_does_not_connect_or_open_db():
    from navi.app import build
    from tests.legacy.harness import make_config

    bot, ctx = build(make_config())
    assert ctx.db is None and ctx.llm is None
    assert bot.user is None  # never logged in
    assert bot.ctx is ctx
