"""Compare Bedrock models on Navi's own prompts: safety suite, latency, tokens and a Trivandrum/Kerala knowledge probe.

    AWS_PROFILE=navi AWS_REGION=<region> python -m tools.compare_models --models google.gemma-3-12b-it,amazon.nova-lite-v1:0 [--repeats 2]

For every model it runs tests/eval/navi_eval.yaml through the same prompt builders and safety filter as `tools.eval_llm`, records latency and
token use, and asks a fixed set of local-knowledge questions. Writes reports/model-compare-<date>.md (and .json) for a human to read; the answers are
printed in full because factual accuracy cannot be scored automatically.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from datetime import date
from pathlib import Path

from navi.llm import policy
from navi.llm.base import LLMError, LLMRequest
from navi.llm.bedrock import DEFAULT_REGION, BedrockProvider
from navi.llm.prompts import get_qa_prompt, get_time_aware_system_prompt
from navi.llm.safety import SafetyFilter, load_blocklist
from tools.eval_llm import load_suite, run_suite, summarise

KNOWLEDGE = [
    "What is Technopark in Trivandrum?",
    "Where is Thampanoor and why is it always crowded?",
    "Explain Attukal Pongala in two lines.",
    "What is special about Kovalam and Varkala beaches?",
    "What is the Padmanabhaswamy temple known for?",
    "What goes into an Onam sadya? Name five dishes.",
    "What should I pack for a trip to Ponmudi?",
    "What is the Napier Museum and what is it famous for?",
    "Which is the capital of Kerala and which district is it in?",
    "Give me a one-line tip for surviving Trivandrum traffic.",
]


class Recording:
    """Wraps a provider and keeps latency and token counts of every successful call."""

    def __init__(self, provider) -> None:
        self.provider, self.model, self.calls = provider, provider.model, []

    async def generate(self, req: LLMRequest, key=None):
        resp = await self.provider.generate(req, key)
        self.calls.append((resp.latency_ms, resp.input_tokens, resp.output_tokens))
        return resp


def pct(values: list[float], p: float) -> float:
    return sorted(values)[min(len(values) - 1, int(len(values) * p))] if values else 0.0


async def evaluate_model(model_id: str, region: str, suite, cases, filt, repeats: int, concurrency: int) -> dict:
    rec = Recording(BedrockProvider(model_id, region))
    results = await run_suite(rec, cases, filt, repeats, concurrency=concurrency)
    stats = summarise(results)
    lat = [c[0] for c in rec.calls]
    total = sum(st["generations"] for st in stats.values())
    errors = sum(st["errors"] for st in stats.values())
    answers = []
    for q in KNOWLEDGE:
        req = LLMRequest(purpose="qa", system=get_time_aware_system_prompt(None, username="Link") + policy.build_policy(None),
                         prompt=get_qa_prompt("Tester", q))
        try:
            answers.append((q, (await rec.generate(req)).text))
        except LLMError as exc:
            answers.append((q, f"[error {exc.kind}]"))
    return {
        "model": model_id, "generations": total, "errors": errors,
        "pre_violation_rate": sum(st["pre_violations"] for st in stats.values()) / max(1, total - errors),
        "post_violations": sum(st["post_violations"] for st in stats.values()),
        "deflection_misses": sum(st["deflection_misses"] for st in stats.values()),
        "over_length": sum(st["length_violations"] for st in stats.values()),
        "unapproved_manglish": sum(st["approved_terms_violations"] for st in stats.values()),
        "p50_ms": statistics.median(lat) if lat else 0, "p95_ms": pct(lat, 0.95),
        "avg_in": statistics.mean(c[1] for c in rec.calls) if rec.calls else 0,
        "avg_out": statistics.mean(c[2] for c in rec.calls) if rec.calls else 0,
        "answers": answers,
    }


def render(rows: list[dict], region: str) -> str:
    lines = [f"# Model comparison ({date.today().isoformat()}, {region})", "",
             "Safety numbers use the repo's eval suite and filter; the blocklist is owner-supplied and empty, so `no_block_hits` cannot fail yet.", "",
             "| Model | Errors | Pre-filter violations | Missed deflections | Over-length | Unapproved Manglish | Post-filter violations | p50 ms | p95 ms | Avg in / out tokens |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| `{r['model']}` | {r['errors']}/{r['generations']} | {r['pre_violation_rate']:.1%} | {r['deflection_misses']} | {r['over_length']} | "
                     f"{r['unapproved_manglish']} | {r['post_violations']} | {r['p50_ms']:.0f} | {r['p95_ms']:.0f} | {r['avg_in']:.0f} / {r['avg_out']:.0f} |")
    lines += ["", "## Knowledge probe (read these for factual accuracy)", ""]
    for q_i, q in enumerate(KNOWLEDGE):
        lines += [f"### {q}", ""]
        for r in rows:
            lines.append(f"- **{r['model']}**: {r['answers'][q_i][1].strip().replace(chr(10), ' ')[:400]}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", required=True, help="comma-separated Bedrock model ids")
    ap.add_argument("--suite", default="tests/eval/navi_eval.yaml")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--out", default="reports")
    args = ap.parse_args(argv)
    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    suite, cases, _ = load_suite(args.suite, None)
    filt = SafetyFilter(load_blocklist(None), policy.approved_terms() + policy.curse_terms())
    rows = []
    for model_id in [m.strip() for m in args.models.split(",") if m.strip()]:
        print(f"== {model_id} ...", flush=True)
        rows.append(asyncio.run(evaluate_model(model_id, region, suite, cases, filt, args.repeats, args.concurrency)))
        print(f"   errors {rows[-1]['errors']}, p50 {rows[-1]['p50_ms']:.0f} ms", flush=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f"model-compare-{date.today().isoformat()}"
    stem.with_suffix(".md").write_text(render(rows, region), encoding="utf-8")
    stem.with_suffix(".json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Wrote {stem}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
