#!/usr/bin/env python3
"""RAGAS-style LLM-judge as additive enrichment on the synthetic surface.

Refines [ADR 0006](../docs/adr/0006-llm-judge-on-real-data-only.md)'s
real-data-only restriction by adding an opt-in additive judge on the
public synthetic eval (see [ADR 0014](../docs/adr/0014-ragas-judge-
additive-synthetic.md)). Same backend pluggability as
``scripts/llm_judge.py`` — ``stub`` (deterministic, default) /
``openai_compatible`` — and the same environment variable contract.

Four metrics per case, each a float in [0.0, 1.0]:

* ``faithfulness`` — fraction of answer claims supported by evidence
* ``answer_relevance`` — how directly the answer addresses the query
* ``context_precision`` — fraction of evidence chunks that are on-topic
* ``context_recall`` — how well evidence covers what the answer needs

CI default is ``BIDMATE_JUDGE_BACKEND=stub`` (zero-cost deterministic
echo). Opt-in paid runs use ``openai_compatible``. Token budget is
enforced — the script refuses to continue past
``BIDMATE_JUDGE_TOKEN_BUDGET`` (default 200_000) input tokens
estimated.

Per-case verdicts are cached by SHA256(query, summary, evidence[:3])
under ``reports/judge_cache/`` (gitignored); a re-run with unchanged
inputs is free. The committable aggregate is mean + 95% bootstrap CI
per metric, written to ``reports/eval_summary.json`` under the
top-level ``judge_ragas`` key.

CLI:

    python3 eval/llm_judge.py \\
        --eval-summary reports/eval_summary.json \\
        --output reports/eval_summary.judge.local.json \\
        --backend stub
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from eval.bootstrap import bootstrap_ci  # noqa: E402
from eval.judges.judge_common import (  # noqa: E402
    build_evidence_block,
    build_openai_client,
    call_openai_json,
    clamp_score as clamp_score_common,
    extract_summary,
    get_judge_model,
)
from rag_core import neutralize_instruction_patterns  # noqa: E402

RAGAS_METRICS: tuple[str, ...] = (
    "faithfulness",
    "answer_relevance",
    "context_precision",
    "context_recall",
)
DEFAULT_CACHE_DIR = ROOT_DIR / "reports" / "judge_cache"
DEFAULT_EVAL_SUMMARY = ROOT_DIR / "reports" / "eval_summary.json"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "reports" / "eval_summary.judge.local.json"
DEFAULT_TOKEN_BUDGET = 200_000

PROMPT_TEMPLATE = """You are scoring a retrieval-augmented QA system on a procurement (RFP) document.
Rate four facets of the answer on a 0.0-1.0 scale.

Query:
{query}

Answer summary:
{summary}

Top retrieved evidence chunks:
{evidence}

Definitions:
- faithfulness: fraction of answer claims supported by the evidence
- answer_relevance: how directly the answer addresses the query
- context_precision: fraction of evidence chunks that are actually on-topic
- context_recall: how well the evidence covers what the answer needs

Reply ONLY with valid JSON of the form:
{{"faithfulness": float,
  "answer_relevance": float,
  "context_precision": float,
  "context_recall": float,
  "reason_short": "short reason, <= 200 chars"}}
"""


# -----------------------------------------------------------------------------
# Backends
# -----------------------------------------------------------------------------


def _stub_backend(_prompt: str) -> dict[str, Any]:
    """Deterministic stub.

    Returns a fixed score vector so plumbing tests do not depend on
    network or API keys. The values are crafted to be distinguishable
    from a real-world distribution: faithfulness=1.0 (perfect),
    others=0.95 — useful as a smoke fixture.
    """
    return {
        "faithfulness": 1.0,
        "answer_relevance": 0.95,
        "context_precision": 0.95,
        "context_recall": 0.95,
        "reason_short": "stub backend: synthetic constant scores",
    }


def _openai_compatible_backend(prompt: str) -> dict[str, Any]:  # pragma: no cover - network
    """Generic OpenAI-compatible endpoint (Anthropic-Compat, OpenAI, vLLM, etc.).

    Delegates client construction and JSON calling to :mod:`eval.judges.judge_common`
    so stub-mode tests have no SDK dependency.
    """
    client = build_openai_client()
    model = get_judge_model()
    payload = call_openai_json(client, model, prompt)
    return _normalize_verdict(payload)


_BACKENDS: dict[str, Callable[[str], dict[str, Any]]] = {
    "stub": _stub_backend,
    "openai_compatible": _openai_compatible_backend,
}


def _normalize_verdict(payload: dict[str, Any]) -> dict[str, Any]:
    """Clamp and coerce a raw backend payload to the Gate 3 RAGAS schema."""
    out = {metric: clamp_score_common(payload.get(metric, 0.0)) for metric in RAGAS_METRICS}
    out["reason_short"] = str(payload.get("reason_short") or "")[:200]
    return out


# -----------------------------------------------------------------------------
# Prompt + cache helpers
# -----------------------------------------------------------------------------


def _build_prompt(case: dict[str, Any]) -> str:
    query = neutralize_instruction_patterns(case.get("query") or "")
    summary = neutralize_instruction_patterns(extract_summary(case))
    evidence_block = build_evidence_block(case)
    return PROMPT_TEMPLATE.format(
        query=query,
        summary=summary,
        evidence=evidence_block,
    )


def _cache_key(case: dict[str, Any], backend: str, model: str) -> str:
    """SHA256 over the inputs that determine the verdict.

    Includes backend + model so switching the backend invalidates the
    cache (we want fresh judgments when changing the underlying judge).
    """
    query = str(case.get("query") or "")
    summary = extract_summary(case)
    evidence_items = case.get("evidence") or []
    ev_repr = json.dumps(
        [
            {
                "doc_id": (item.get("doc_id") if isinstance(item, dict) else ""),
                "text": (item.get("text") if isinstance(item, dict) else "")[:300],
            }
            for item in evidence_items[:3]
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    payload = "|".join([backend, model, query, summary, ev_repr])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _estimate_tokens(prompt: str) -> int:
    return max(1, len(prompt) // 3)


# -----------------------------------------------------------------------------
# Pipeline
# -----------------------------------------------------------------------------


def _aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-case verdicts into mean + 95% bootstrap CI per metric."""
    if not cases:
        out: dict[str, Any] = {metric: None for metric in RAGAS_METRICS}
        out["n"] = 0
        out["ci"] = {}
        return out
    out = {"n": len(cases), "ci": {}}
    for metric in RAGAS_METRICS:
        scores = [float(c.get(metric) or 0.0) for c in cases]
        out[metric] = sum(scores) / len(scores)
        ci = bootstrap_ci(scores)
        if ci is not None:
            out["ci"][metric] = ci
    return out


def judge_ragas(
    summary: dict[str, Any],
    *,
    backend: str = "stub",
    cache_dir: Path | None = None,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the RAGAS judge over an eval_summary dict.

    Returns ``(local_payload, aggregate)``. The caller is responsible
    for writing each — local payload contains per-case judge text and
    stays gitignored; aggregate is committable.
    """
    if backend not in _BACKENDS:
        raise ValueError(
            f"Unknown judge backend {backend!r}; "
            f"choose one of {sorted(_BACKENDS)}."
        )
    backend_fn = _BACKENDS[backend]
    if cache_dir is None:
        cache_dir = DEFAULT_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    model = os.environ.get("BIDMATE_JUDGE_MODEL", "stub")

    case_results = summary.get("case_results") or []
    judged: list[dict[str, Any]] = []
    cache_hits = 0
    new_calls = 0
    tokens_estimated = 0

    for case in case_results:
        if not isinstance(case, dict):
            continue
        key = _cache_key(case, backend, model)
        cache_path = cache_dir / f"{key}.json"
        if cache_path.exists():
            try:
                verdict = json.loads(cache_path.read_text(encoding="utf-8"))
                cache_hits += 1
            except json.JSONDecodeError:
                cache_path.unlink(missing_ok=True)
                verdict = None
        else:
            verdict = None
        if verdict is None:
            prompt = _build_prompt(case)
            est = _estimate_tokens(prompt)
            if tokens_estimated + est > token_budget:
                raise RuntimeError(
                    f"Judge token budget {token_budget} would be exceeded "
                    f"(estimated +{est} on top of {tokens_estimated}). "
                    "Raise BIDMATE_JUDGE_TOKEN_BUDGET deliberately or reduce "
                    "the case set."
                )
            tokens_estimated += est
            verdict = _normalize_verdict(backend_fn(prompt))
            cache_path.write_text(
                json.dumps(verdict, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            new_calls += 1
        judged.append({"id": case.get("id"), **verdict})

    aggregate = _aggregate(judged)
    local_payload = {
        "schema_version": 1,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "backend": backend,
        "model": model,
        "cases": judged,
        "cache_hits": cache_hits,
        "new_calls": new_calls,
        "tokens_estimated": tokens_estimated,
    }
    return local_payload, aggregate


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--eval-summary",
        default=str(DEFAULT_EVAL_SUMMARY),
        help="Path to reports/eval_summary.json (default: public synthetic).",
    )
    ap.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help=(
            "Where to write the per-case judge payload (gitignored). "
            "Aggregate is also folded into the eval_summary.json under "
            "top-level 'judge_ragas'."
        ),
    )
    ap.add_argument(
        "--backend",
        default=os.environ.get("BIDMATE_JUDGE_BACKEND", "stub"),
        choices=sorted(_BACKENDS),
        help="Judge backend (defaults to BIDMATE_JUDGE_BACKEND or 'stub').",
    )
    ap.add_argument(
        "--token-budget",
        type=int,
        default=int(
            os.environ.get("BIDMATE_JUDGE_TOKEN_BUDGET", DEFAULT_TOKEN_BUDGET)
        ),
        help=f"Input-token estimate budget per run (default {DEFAULT_TOKEN_BUDGET}).",
    )
    ap.add_argument(
        "--cache-dir",
        default=str(DEFAULT_CACHE_DIR),
        help="Per-case verdict cache directory (gitignored).",
    )
    ap.add_argument(
        "--fold-aggregate",
        action="store_true",
        help=(
            "After scoring, also write the aggregate under the top-level "
            "'judge_ragas' key in the eval_summary.json so 'make smoke' "
            "and downstream readers see the metrics. Off by default to "
            "avoid surprising users running stub mode for sanity."
        ),
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    eval_path = Path(args.eval_summary)
    if not eval_path.exists():
        print(
            f"[ERROR] Eval summary not found: {eval_path}\n"
            "Run `make smoke` or `make eval` first.",
            file=sys.stderr,
        )
        return 2
    summary = json.loads(eval_path.read_text(encoding="utf-8"))
    try:
        local_payload, aggregate = judge_ragas(
            summary,
            backend=args.backend,
            cache_dir=Path(args.cache_dir),
            token_budget=args.token_budget,
        )
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(local_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] Per-case verdicts written: {output_path}")
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))

    if args.fold_aggregate:
        summary["judge_ragas"] = aggregate
        eval_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[OK] Aggregate folded into {eval_path} under 'judge_ragas'.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
