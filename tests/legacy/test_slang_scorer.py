import pytest

import slang_scorer


@pytest.fixture()
def fake_map(monkeypatch):
    monkeypatch.setattr(slang_scorer, "_variation_map", {
        "tvmword": {"points": 5, "region": "TVM", "word_ml": ""},
        "tvmtwo": {"points": 3, "region": "TVM", "word_ml": ""},
        "kochiword": {"points": -4, "region": "Kochi", "word_ml": ""},
    })


def test_tvm_adds_kochi_subtracts(fake_map):
    assert slang_scorer.score_message("tvmword") == 5
    assert slang_scorer.score_message("kochiword") == -4
    assert slang_scorer.score_message("tvmword kochiword tvmtwo") == 4


def test_each_token_counted_once_per_message(fake_map):
    assert slang_scorer.score_message("tvmword TVMWORD tvmword!!") == 5
    assert len(slang_scorer.get_slang_matches("tvmword tvmword")) == 1


def test_punctuation_and_case(fake_map):
    assert slang_scorer.score_message("Hey,TvmWord.") == 5 or slang_scorer.score_message("Hey, TvmWord.") == 5


def test_unknown_and_empty(fake_map):
    assert slang_scorer.score_message("nothing here") == 0
    assert slang_scorer.score_message("") == 0


def test_not_loaded_returns_zero(monkeypatch):
    monkeypatch.setattr(slang_scorer, "_variation_map", {})
    assert slang_scorer.score_message("anything") == 0
    assert slang_scorer.get_slang_matches("anything") == []


def test_real_data_loads_and_has_both_regions():
    slang_scorer.load_slang_data()
    assert slang_scorer._variation_map
    regions = {m["region"] for m in slang_scorer._variation_map.values()}
    assert len(regions) >= 2
    pts = [m["points"] for m in slang_scorer._variation_map.values()]
    assert any(p > 0 for p in pts) and any(p < 0 for p in pts)
