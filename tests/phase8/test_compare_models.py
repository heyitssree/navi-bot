"""tools/compare_models: recording wrapper, percentile helper and report rendering (no AWS calls)."""
from navi.llm.base import LLMRequest, LLMResponse
from tools.compare_models import KNOWLEDGE, Recording, pct, render


class Fake:
    model = "fake.model"

    async def generate(self, req, key=None):
        return LLMResponse(text="ok", input_tokens=10, output_tokens=3, provider="bedrock", model=self.model, latency_ms=120)


async def test_recording_keeps_latency_and_tokens():
    rec = Recording(Fake())
    await rec.generate(LLMRequest(purpose="qa", system="s", prompt="p"))
    assert rec.calls == [(120, 10, 3)] and rec.model == "fake.model"


def test_percentile_handles_empty_and_small_lists():
    assert pct([], 0.95) == 0.0 and pct([5], 0.95) == 5 and pct(list(range(100)), 0.95) == 95


def test_report_lists_every_model_and_every_knowledge_question():
    row = {"model": "fake.model", "generations": 64, "errors": 0, "pre_violation_rate": 0.0, "post_violations": 0, "deflection_misses": 2,
           "over_length": 3, "unapproved_manglish": 0, "p50_ms": 900, "p95_ms": 1800, "avg_in": 700, "avg_out": 40,
           "answers": [(q, "an answer") for q in KNOWLEDGE]}
    text = render([row], "ap-southeast-2")
    assert "`fake.model`" in text and all(q in text for q in KNOWLEDGE) and "| 900 | 1800 | 700 / 40 |" in text
