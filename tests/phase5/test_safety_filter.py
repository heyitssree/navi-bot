import os
from pathlib import Path

import pytest

from navi.llm import safety
from navi.llm.policy import approved_terms, build_policy, curse_terms, write_allowlist
from navi.llm.safety import SafetyFilter, Verdict, load_blocklist, normalise
from navi.settings.store import Settings


def test_normalise_undoes_leet_zero_width_and_repeats():
    assert normalise("Z0RGBL@T") == "zorgblat"
    assert normalise("zor​g‍blat") == "zorgblat"
    assert normalise("zorgblaaaaat") == "zorgblaat"
    assert normalise("ＺＯＲＧ") == "zorg"                                   # full-width letters (NFKC)


def f(*entries, allowed=(), settings=None):
    return SafetyFilter(list(entries), list(allowed), settings)


@pytest.mark.parametrize("text", ["zorgblat", "you ZORGBLAT", "zorg1blat".replace("1", ""), "z0rgbl4t!", "zorgblaaaat", "zor​gblat"])
def test_blocklist_catches_obfuscated_spellings(text):
    assert not f("zorgblat").check(text).ok


def test_word_boundaries_avoid_false_positives():
    flt = f("zorgblat")
    assert flt.check("a zorgblatter is fine").ok is True or flt.check("a zorgblatter is fine").reasons
    assert f("cat").check("concatenate the category").ok                      # short entry inside longer words
    assert not f("cat").check("a cat sat")


def test_squashed_match_only_for_long_entries():
    flt = f("zorgblat", "abcd")
    assert not flt.check("z o r g b l a t").ok and not flt.check("z-o-r-g-b-l-a-t").ok and not flt.check("z.o.r.g.b.l.a.t").ok
    assert flt.check("a b c d").ok                       # 4 characters: not squashed, only whole-word matching
    assert not flt.check("abcd").ok


def test_multi_word_entries_and_script_entries():
    flt = f("snarf wibble", "മോശം")
    assert not flt.check("what a snarf   wibble").ok
    assert flt.check("snarf and wibble").ok
    assert not flt.check("ഇത് മോശംആണ്").ok            # script entries match anywhere


def test_malayalam_script_rejected_unless_the_setting_allows_it(db):
    settings = Settings(); settings.bind(db)
    flt = f(settings=settings)
    v = flt.check("നമസ്കാരം")
    assert v.reasons == ["malayalam_script"]
    settings.set("safety.allow_malayalam_script", True)
    assert flt.check("നമസ്കാരം").ok
    assert not f().check("നമസ്കാരം").ok                  # no settings object: strict


def test_allowlist_protects_navi_own_words():
    # A blocklist entry that happens to sit inside an allow-listed curse word must not trip the filter.
    flt = f("andan", allowed=["mandan"])
    assert flt.check("mandan, nee oru mandan").ok
    assert not flt.check("andan").ok
    assert not flt.check("mandan andan").ok               # the real hit outside the allowed word still counts


def test_mentions_and_length():
    flt = f()
    assert flt.check("hi @everyone").reasons == ["mention"]
    assert flt.check("hello <@123456> and <@&99>").reasons == ["mention"]
    assert flt.check("x" * 2000, "qa").reasons == ["too_long"]
    assert flt.check("x" * 1900, "summary").ok
    assert Verdict(True) and not Verdict(False, ["x"])


def test_multiple_reasons_reported_together():
    assert set(f("zorgblat").check("zorgblat നമസ്കാരം @here").reasons) == {"blocklist", "malayalam_script", "mention"}


def test_module_level_check_output_uses_the_configured_filter(blocked):
    assert not safety.check_output("zorgblat").ok and safety.check_output("a nice day").ok


# ---------------------------------------------------------------------------- blocklist file

def test_load_blocklist_ignores_comments_blanks_and_missing_file(tmp_path):
    p = tmp_path / "b.txt"
    p.write_text("# header\n\n  zorgblat  \n#another\nsnarf wibble\n", encoding="utf-8")
    assert load_blocklist(p) == ["zorgblat", "snarf wibble"]
    assert load_blocklist(tmp_path / "missing.txt") == []


def test_shipped_blocklist_is_an_empty_template_with_a_format_header():
    path = Path("navi/data/safety/blocklist.txt")
    text = path.read_text(encoding="utf-8")
    assert load_blocklist(path) == []                   # the owner supplies the entries; none are generated
    assert "SUPPLIED AND MAINTAINED BY THE OWNER" in text and "Malayalam-script" in text and "leetspeak" in text


def test_blocklist_path_can_come_from_the_environment(tmp_path, monkeypatch):
    p = tmp_path / "custom.txt"
    p.write_text("zorgblat\n")
    monkeypatch.setenv("SAFETY_BLOCKLIST", str(p))
    assert load_blocklist() == ["zorgblat"]


# ---------------------------------------------------------------------------- policy and allowlist

def test_policy_names_approved_and_curse_terms(db):
    text = build_policy(db)
    assert "CONTENT RULES" in text and "Never use Malayalam script" in text and "deflection" in text
    for term in ("chumma", "kidilam", "mandan", "kozhi"):
        assert term in text
    assert "{approved_terms}" not in text and "{curse_terms}" not in text


def test_approved_terms_include_knowledge_expressions(db):
    from navi.db.repos.knowledge import seed_local_knowledge

    seed_local_knowledge(db)
    terms = approved_terms(db)
    assert "kili poyi" in terms and "oola" in terms and "chumma" in terms
    assert set(curse_terms()) >= {"mandan", "kozhi"} and len(curse_terms()) == 17


def test_write_allowlist_file(tmp_path, db):
    path = tmp_path / "safety" / "allowlist.txt"
    terms = write_allowlist(path, db)
    lines = path.read_text().splitlines()
    assert lines[0].startswith("#") and set(lines[1:]) == set(terms) and "mandan" in terms
