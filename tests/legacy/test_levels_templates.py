import json

import pytest

import bot as navi
import schema
import template_resolver


@pytest.mark.parametrize("level,expected", [(0, 0), (-3, 0), (1, 20), (10, 650), (50, 13250), (100, 51500), (150, 51500)])
def test_points_for_level(level, expected):
    assert schema.points_for_level(level) == expected


def test_level_roundtrip_is_inverse():
    for level in range(0, 101):
        need = schema.points_for_level(level)
        assert schema.get_level_from_points(need) == level
        if level < 100 and need > 0:
            assert schema.get_level_from_points(need - 1) == level - 1


def test_get_level_bounds():
    assert schema.get_level_from_points(0) == 0
    assert schema.get_level_from_points(-50) == 0
    assert schema.get_level_from_points(10**9) == 100


def test_templatize_personalise_roundtrip():
    text = "Ravi, you are doomed by madiyan today"
    tpl = navi._templatize(text, "Ravi", "madiyan")
    assert tpl == "{user}, you are doomed by {curse} today"
    assert navi._personalise(tpl, "Asha", "kozhi") == "Asha, you are doomed by kozhi today"


def test_templatize_without_curse_leaves_curse_text():
    assert navi._templatize("Ravi hi madiyan", "Ravi") == "{user} hi madiyan"
    assert navi._personalise("{user} {curse}", "A") == "A {curse}"


@pytest.fixture()
def tpl_file(tmp_path):
    p = tmp_path / "templates.json"
    p.write_text(json.dumps({"commands": {"hello": {
        "en": "hi {name}", "en_penalty": "bad {name}", "ml_reward": "great {name}"}}}))
    template_resolver.load_templates(p)
    yield
    template_resolver.load_templates()


def test_template_variant_selection(tpl_file):
    g = template_resolver.get_template
    assert g("hello", -1, name="X") == "bad X"
    assert g("hello", 0, name="X") == "hi X"
    assert g("hello", 499, name="X") == "hi X"
    assert g("hello", 500, name="X") == "great X"


def test_template_missing_command_and_key(tpl_file):
    assert template_resolver.get_template("nope", 10) == ""
    assert template_resolver.get_template("hello", 10) == "hi {name}"  # missing kwarg returns raw template
