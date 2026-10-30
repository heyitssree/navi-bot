"""Phase 2 gate checks: layout rules from the spec."""
import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NAVI = ROOT / "navi"
PY_FILES = sorted(p for p in NAVI.rglob("*.py"))

# Files over ~600 lines need a note here explaining why (none at the moment).
SIZE_NOTES: dict[str, str] = {}
POINT_WRITERS = {"update_boli_points", "add_experience", "set_user_points", "add_external_boli"}


def test_old_monoliths_are_gone():
    for name in ("bot.py", "schema.py", "prompts.py", "curses.py", "api_server.py", "services"):
        assert not (ROOT / name).exists(), name


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_file_over_600_lines(path):
    n = len(path.read_text().splitlines())
    rel = str(path.relative_to(ROOT))
    assert n <= 600 or rel in SIZE_NOTES, f"{rel} has {n} lines"


def test_main_is_tiny_bootstrap():
    assert len((NAVI / "__main__.py").read_text().splitlines()) < 50


def test_only_points_service_changes_balances():
    """Cogs/handlers/services must go through navi.services.points, never the repo functions."""
    offenders = []
    for path in PY_FILES:
        rel = path.relative_to(NAVI)
        if rel.parts[:2] in (("services", "points.py"),) or rel.parts[:2] == ("db", "repos"):
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "navi.db.repos.points":
                bad = {a.name for a in node.names} & POINT_WRITERS
                if bad:
                    offenders.append((str(rel), sorted(bad)))
    assert not offenders, offenders


# Read-only lookup tables filled once from JSON files at startup (not runtime state).
STATIC_DATA_CACHES = {"services/slang_scorer.py", "services/templates.py"}


def test_no_module_level_state_in_app_code():
    """Mutable state lives on AppContext, not in module globals."""
    offenders = []
    for path in PY_FILES:
        rel = path.relative_to(NAVI)
        if rel.parts[0] not in ("cogs", "handlers", "services") or str(rel) in STATIC_DATA_CACHES:
            continue
        tree = ast.parse(path.read_text())
        for node in tree.body:
            value = getattr(node, "value", None)
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and value is not None:
                empty_literal = (isinstance(value, (ast.Dict, ast.List, ast.Set)) and not getattr(value, "keys", getattr(value, "elts", [1])))
                empty_call = (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                              and value.func.id in {"dict", "set", "list", "deque", "defaultdict"} and not value.args)
                if empty_literal or empty_call:
                    offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, offenders


def _command_tree():
    import asyncio

    from navi.app import build
    from tests.legacy.harness import make_config

    bot, _ = build(make_config())

    async def load():
        await bot.setup_hook()
        return sorted((c.to_dict(bot.tree) for c in bot.tree.get_commands()), key=lambda x: (x.get("type", 1), x["name"]))

    return json.loads(json.dumps(asyncio.run(load()), default=str, sort_keys=True))


REMOVED_IN_PHASE_4 = {"health"}
ADMIN_SURFACE = {"panel", "set", "get", "reset", "killswitch", "testing", "status", "review", "export", "import", "user", "teach"}


def test_slash_command_surface_outside_admin_is_unchanged():
    """Everything except /admin (rebuilt in Phase 4) and the removed /health matches the pre-refactor snapshot."""
    new = [c for c in _command_tree() if c["name"] != "admin"]
    base = [c for c in json.loads((ROOT / "tests/fixtures/command_tree_baseline.json").read_text())
            if c["name"] not in {"admin"} | REMOVED_IN_PHASE_4]
    assert new == base


def test_admin_command_surface_matches_the_spec():
    admin = next(c for c in _command_tree() if c["name"] == "admin")
    assert {o["name"] for o in admin["options"]} == ADMIN_SURFACE
    groups = {o["name"]: {x["name"] for x in o["options"]} for o in admin["options"] if o.get("options") and o["type"] == 2}
    assert groups == {"user": {"points", "strikes_reset", "game_attempts_reset"}, "teach": {"allow", "revoke", "list"}}
    assert admin["default_member_permissions"] == 1 << 3        # administrator
    removed = {"toggle_killswitch", "toggle_feature", "set_chance", "set_cooldown", "set_summary_emoji", "partner_toggle",
               "config_view", "reset_all_strikes", "set_points", "adjust_points", "reset_game_attempts"}
    assert not removed & {o["name"] for o in admin["options"]}
    assert "health" not in {c["name"] for c in _command_tree()}


def test_every_cog_has_a_setup_function():
    import importlib

    from navi.app import COGS

    for name in COGS:
        assert hasattr(importlib.import_module(name), "setup"), name
