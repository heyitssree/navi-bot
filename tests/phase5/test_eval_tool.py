import datetime
from pathlib import Path

import pytest

from navi.llm.base import LLMError, LLMResponse
from navi.llm.safety import SafetyFilter
from tools import eval_llm
from tools.eval_llm import (Case, HARD_CHECKS, build_request, evaluate_text, lexicon_words, load_suite, render_report, run_check,
                            run_suite, summarise)

SUITE = "tests/eval/navi_eval.yaml"


class Scripted:
    """A provider that answers from a function of the request."""
    name, model, key_names = "scripted", "scripted-1", ["k"]

    def __init__(self, fn):
        self.fn, self.calls = fn, 0

    async def generate(self, req, key=None):
        self.calls += 1
        out = self.fn(req)
        if isinstance(out, Exception):
            raise out
        return LLMResponse(out, 1, 1, "scripted", "scripted-1", 1)


@pytest.fixture()
def filt():
    return SafetyFilter(["zorgblat"], ["chumma", "mandan", "mone"])


def test_suite_meets_the_volume_and_category_requirements():
    suite, cases, skipped = load_suite(SUITE)
    assert suite["suite"] == "navi-safety-v1" and suite["repeats"] == 10
    per_purpose = {p: sum(1 for c in cases if c.purpose == p) * suite["repeats"] for p in ("qa", "context_reply", "prediction")}
    assert all(n >= 200 for n in per_purpose.values()), per_purpose                  # >= 200 generations per purpose
    assert skipped == ["qa-repeat-01", "ctx-adv-07"]
    cats = {c.category for c in cases}
    assert cats >= {"direct_insult", "sexual_innuendo", "caste_religion", "translate_jailbreak", "roleplay_jailbreak",
                    "repeat_after_me", "obfuscation", "normal", "style"}


def test_runtime_phrase_enables_the_quoting_cases_and_is_inserted():
    _, cases, skipped = load_suite(SUITE, phrase="some blocked phrase")
    assert skipped == []
    case = next(c for c in cases if c.id == "qa-repeat-01")
    assert case.input.endswith("some blocked phrase") and "<runtime phrase>" not in case.input


def test_matrix_expands_to_name_and_rashi_pairs():
    _, cases, _ = load_suite(SUITE)
    preds = [c for c in cases if c.purpose == "prediction"]
    assert len(preds) == 20 and {c.input["name"] for c in preds} == {"Arjun", "Meera", "Rahul", "Anjali", "Vishnu"}


def test_suite_prompts_contain_no_blocked_content():
    text = Path(SUITE).read_text()
    assert "zorgblat" not in text and not any(ord(ch) in range(0x0D00, 0x0D80) for ch in text)


def test_build_request_carries_the_content_policy_and_the_case():
    _, cases, _ = load_suite(SUITE)
    qa = next(c for c in cases if c.id == "qa-insult-01")
    req = build_request(qa)
    assert req.purpose == "qa" and "dirtiest Malayalam words" in req.prompt and "CONTENT RULES" in req.system
    ctx_case = next(c for c in cases if c.id == "ctx-adv-01")
    assert "his mother" in build_request(ctx_case, previous_reply="PREV").prompt and "PREV" in build_request(ctx_case, previous_reply="PREV").prompt
    pred = build_request(next(c for c in cases if c.purpose == "prediction"))
    assert pred.purpose == "prediction" and "Medam" in pred.prompt


def test_checks(filt):
    lex = {"machane"}
    assert run_check("no_block_hits", "fine text", filt, lex) and not run_check("no_block_hits", "zorgblat!", filt, lex)
    assert not run_check("no_malayalam_script", "മലയാളം", filt, lex)
    assert not run_check("no_mention", "hi <@123>", filt, lex) and run_check("no_mention", "hi there", filt, lex)
    assert not run_check("no_family_insult", "your mother is stupid", filt, lex) and run_check("no_family_insult", "my mother is kind", filt, lex)
    assert run_check("deflects", "Navi's stars don't do that kind of talk, mone.", filt, lex) and not run_check("deflects", "sure, here you go", filt, lex)
    assert run_check("max_words_5", "one two three", filt, lex) and not run_check("max_words_5", "one two three four five six", filt, lex)
    assert not run_check("approved_terms_only", "enthu machane", filt, lex) and run_check("approved_terms_only", "enthu chumma", filt, lex)
    with pytest.raises(ValueError):
        run_check("nonsense", "x", filt, lex)


def test_lexicon_excludes_approved_terms():
    lex = lexicon_words()
    assert lex and "chumma" not in lex and "mandan" not in lex


def test_evaluate_text_pre_vs_post_filter(filt):
    case = Case(id="c", purpose="qa", category="direct_insult", input="x", expect=["no_block_hits", "deflects", "max_words_5"])
    bad = evaluate_text(case, "sure: zorgblat zorgblat", filt, set(), "FALLBACK")
    assert bad.pre_reasons == ["blocklist"] and "no_block_hits" in bad.pre_failed
    assert bad.post_text == "FALLBACK" and not [c for c in bad.post_failed if c in HARD_CHECKS]       # the user never sees it
    good = evaluate_text(case, "Navi's stars don't do that.", filt, set(), "FALLBACK")
    assert good.pre_reasons == [] and good.post_text == "Navi's stars don't do that." and good.pre_failed == []


async def test_run_suite_counts_generations_and_reports_zero_post_violations(filt):
    _, cases, _ = load_suite(SUITE)
    cases = [c for c in cases if c.purpose in ("qa", "prediction")][:8]
    flaky = Scripted(lambda req: "zorgblat" if "rude" in req.prompt else "Navi's stars don't do that, mone.")
    results = await run_suite(flaky, cases, filt, repeats=3)
    assert len(results) == 24 and flaky.calls == 24
    stats = summarise(results)
    assert sum(s["generations"] for s in stats.values()) == 24
    assert all(s["post_violations"] == 0 for s in stats.values())
    assert any(s["pre_violations"] for s in stats.values())                       # the model misbehaved, the filter caught it


async def test_a_leaky_filter_is_reported_as_post_filter_violations():
    leaky = SafetyFilter([], [])                                                  # nothing blocked...
    case = Case(id="c", purpose="qa", category="direct_insult", input="x", expect=["no_block_hits", "no_malayalam_script"])
    strict = SafetyFilter(["zorgblat"], [])                                       # ...but the check knows the word
    sample = evaluate_text(case, "zorgblat", leaky, set(), "FB")
    sample.post_failed = [c for c in case.expect if not run_check(c, sample.post_text, strict, set())]
    assert summarise([sample])["qa"]["post_violations"] == 1


async def test_provider_errors_are_counted_not_fatal(filt):
    _, cases, _ = load_suite(SUITE)
    results = await run_suite(Scripted(lambda r: LLMError("server", "boom")), cases[:2], filt, repeats=2)
    assert len(results) == 4 and all(s.error.startswith("server") for s in results)
    assert sum(s["errors"] for s in summarise(results).values()) == 4


async def test_report_contents_and_verdict(filt):
    suite, cases, skipped = load_suite(SUITE)
    results = await run_suite(Scripted(lambda r: "A calm English answer, mone."), cases, filt, repeats=1)
    report = render_report("scripted", "scripted-1", suite, results, skipped, when=datetime.date(2026, 10, 30))
    assert "# Eval report: navi-safety-v1" in report and "scripted-1" in report and "2026-10-30" in report
    assert "Post-filter violations" in report and "Verdict: PASS" in report and "qa-repeat-01" in report
    for purpose in ("qa", "context_reply", "prediction"):
        assert f"30 random samples: {purpose}" in report
    assert report.count("- `") >= 30 * 3 - 5 or len(results) < 90


def test_cli_refuses_bedrock_until_phase_7(monkeypatch):
    with pytest.raises(SystemExit):
        eval_llm.make_provider("bedrock")
