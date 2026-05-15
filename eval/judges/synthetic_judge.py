#!/usr/bin/env python3
"""LLM-as-judge for the public synthetic eval surface (ADR 0012).

Reads ``reports/eval_summary.json`` (produced by ``eval/run_eval.py``),
asks a configured LLM backend whether each case's answer is supported
by its evidence, and emits two artifacts:

* ``reports/synthetic_judge.aggregate.json`` (committable, ADR 0005
  aggregate-only boundary) — RAGAS-style means + agreement-with-verifier.
* ``reports/synthetic_judge.local.json`` (git-ignored) — per-case
  judge text.

This is the public-synthetic sibling of ``scripts/llm_judge.py``
(real-data judge, ADR 0006). ADR 0012 explains why the synthetic
surface gets a stub-default judge while ADR 0006's real-data
restriction is preserved for the live-API path.

Backends:

* ``stub`` (default) — deterministic; mirrors the deterministic
  verifier so ``agreement_with_verifier`` is 1.0 on stub runs. Used
  by ``make smoke`` / ``pr-eval.yml`` (toklen cost 0, fully
  reproducible). Faithfulness / answer-relevance scores are
  status-derived fixtures — schema-stable but not a real signal.
* ``openai_compatible`` — generic OpenAI-compatible endpoint
  (Anthropic-Compat, OpenAI, vLLM, llama.cpp server, etc.). Reads
  ``BIDMATE_JUDGE_API_KEY`` / ``BIDMATE_JUDGE_MODEL`` /
  ``BIDMATE_JUDGE_BASE_URL`` (shared with the real-data judge).

Per-case schema (never committed):

    {
      "id": "...",
      "judge_status": "supported" | "partial" | "insufficient",
      "judge_grounded": bool,
      "faithfulness": 0.0–1.0,
      "answer_relevance": 0.0–1.0,
      "judge_reason_short": "≤ 200 chars",
      "verifier_status": "...",
      "agrees": bool
    }

Committable aggregate:

    {
      "schema_version": 1,
      "generated_at": "ISO8601Z",
      "backend": "stub" | "openai_compatible",
      "model": "string",
      "n": int,
      "faithfulness_mean": float | null,
      "answer_relevance_mean": float | null,
      "grounded_rate": float | null,
      "agreement_with_verifier": float | null,
      "status_distribution": {"supported": int, "partial": int, ...},
      "by_query_type": {"single_doc": {...}, "comparison": {...}, ...}
    }
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.judges.judge_common import (  # noqa: E402
    EVIDENCE_BOUNDARY,
    JUDGE_STATUSES,
    build_evidence_block,
    build_openai_client,
    call_openai_json,
    clamp_score,
    extract_summary,
    get_judge_model,
    normalize_status_verdict,
)
from rag_core import neutralize_instruction_patterns  # noqa: E402

DEFAULT_SUMMARY_PATH = ROOT / "reports" / "eval_summary.json"
DEFAULT_AGGREGATE_PATH = ROOT / "reports" / "synthetic_judge.aggregate.json"
DEFAULT_LOCAL_PATH = ROOT / "reports" / "synthetic_judge.local.json"

# Status-derived fixture scores for the stub backend. Not a real
# signal; schema-stable so downstream metric blocks don't crash.
_STUB_SCORES: dict[str, dict[str, float]] = {
    "supported": {"faithfulness": 0.85, "answer_relevance": 0.80},
    "partial": {"faithfulness": 0.50, "answer_relevance": 0.50},
    "insufficient": {"faithfulness": 0.10, "answer_relevance": 0.30},
}

PROMPT_TEMPLATE = """You are reviewing one answer from a retrieval-augmented QA
system on a procurement (RFP) document. Judge whether the answer is
supported by the evidence chunks, and assign RAGAS-style continuous
scores.

Query:
{query}

Answer summary:
{summary}

Top evidence chunks:
{evidence}

Reply ONLY with valid JSON of the form:
{{"judge_status": "supported" | "partial" | "insufficient",
  "judge_grounded": true | false,
  "faithfulness": 0.0-1.0,
  "answer_relevance": 0.0-1.0,
  "judge_reason_short": "short reason, <= 200 chars"}}

Definitions:
- faithfulness: 1.0 if every claim in the answer is directly supported
  by the evidence; 0.0 if the answer contradicts or fabricates beyond
  evidence.
- answer_relevance: 1.0 if the answer directly addresses the query;
  0.0 if the answer is off-topic.
"""


# -----------------------------------------------------------------------------
# Backends
# -----------------------------------------------------------------------------


def _stub_backend(_prompt: str, *, verifier_status: str) -> dict[str, Any]:
    """Deterministic stub.

    Mirrors the verifier's status (so ``agreement_with_verifier == 1.0``)
    and emits status-derived fixture scores for plumbing tests. Not a
    real RAGAS signal — that requires ``--backend openai_compatible``.
    """
    status = verifier_status if verifier_status in JUDGE_STATUSES else "insufficient"
    scores = _STUB_SCORES.get(status, _STUB_SCORES["insufficient"])
    return {
        "judge_status": status,
        "judge_grounded": status == "supported",
        "faithfulness": scores["faithfulness"],
        "answer_relevance": scores["answer_relevance"],
        "judge_reason_short": "stub backend: verifier status echoed",
    }


def _openai_compatible_backend(  # pragma: no cover - network
    prompt: str, *, verifier_status: str
) -> dict[str, Any]:
    """Generic OpenAI-compatible endpoint.

    Delegates client construction and JSON calling to :mod:`eval.judges.judge_common`
    so the stub-only path has no network / SDK dependency.  Returns an
    ``insufficient`` marker on JSON decode error (PR #218 fault tolerance).
    """
    client = build_openai_client()
    model = get_judge_model()
    payload = call_openai_json(client, model, prompt)
    if payload is None:
        return {
            "judge_status": "insufficient",
            "judge_grounded": False,
            "judge_reason_short": "malformed_json: judge backend returned non-JSON content",
        }
    return normalize_status_verdict(payload, fallback_status=verifier_status)


_BACKENDS = {
    "stub": _stub_backend,
    "openai_compatible": _openai_compatible_backend,
}


# -----------------------------------------------------------------------------
# Pipeline
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


def _verifier_status(case: dict[str, Any]) -> str:
    status = str(case.get("answer_status") or "").strip().lower()
    return status if status in JUDGE_STATUSES else "insufficient"


def _slice_aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    faithfulness = [c["faithfulness"] for c in cases]
    relevance = [c["answer_relevance"] for c in cases]
    grounded = [bool(c.get("judge_grounded")) for c in cases]
    agreements = [bool(c.get("agrees")) for c in cases if c.get("agrees") is not None]
    statuses = [c["judge_status"] for c in cases if c.get("judge_status")]
    return {
        "n": len(cases),
        "faithfulness_mean": statistics.fmean(faithfulness) if faithfulness else None,
        "answer_relevance_mean": statistics.fmean(relevance) if relevance else None,
        "grounded_rate": (sum(grounded) / len(grounded)) if grounded else None,
        "agreement_with_verifier": (
            sum(agreements) / len(agreements) if agreements else None
        ),
        "status_distribution": dict(Counter(statuses)),
    }


def _aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        by_type[str(case.get("query_type") or "unknown")].append(case)
    overall = _slice_aggregate(cases)
    overall["by_query_type"] = {
        qtype: _slice_aggregate(rows) for qtype, rows in sorted(by_type.items())
    }
    return overall


def judge_synthetic_summary(
    summary: dict[str, Any],
    backend: str = "stub",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the synthetic judge over an ``eval_summary`` dict.

    Returns ``(local_payload, aggregate)`` — the caller decides where
    to write each. ``local_payload`` contains per-case judge text and
    stays under the ADR 0005 boundary; ``aggregate`` is safe to commit.
    """
    if backend not in _BACKENDS:
        raise ValueError(
            f"Unknown synthetic judge backend {backend!r}; "
            f"choose one of {sorted(_BACKENDS)}."
        )
    backend_fn = _BACKENDS[backend]

    case_results = summary.get("case_results") or []
    judged: list[dict[str, Any]] = []
    for case in case_results:
        if not isinstance(case, dict):
            continue
        prompt = _build_prompt(case)
        verifier_status = _verifier_status(case)
        verdict = backend_fn(prompt, verifier_status=verifier_status)
        judged.append(
            {
                "id": case.get("id"),
                "query_type": case.get("query_type"),
                "judge_status": verdict["judge_status"],
                "judge_grounded": verdict["judge_grounded"],
                "faithfulness": clamp_score(verdict["faithfulness"]),
                "answer_relevance": clamp_score(verdict["answer_relevance"]),
                "judge_reason_short": verdict["judge_reason_short"],
                "verifier_status": verifier_status,
                "agrees": verdict["judge_status"] == verifier_status,
            }
        )

    aggregate = {
        "schema_version": 1,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "backend": backend,
        "model": os.environ.get("BIDMATE_JUDGE_MODEL", "stub"),
        **_aggregate(judged),
    }
    local_payload = {
        "schema_version": 1,
        "generated_at": aggregate["generated_at"],
        "backend": backend,
        "model": aggregate["model"],
        "cases": judged,
    }
    return local_payload, aggregate


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--summary",
        default=str(DEFAULT_SUMMARY_PATH),
        help="Path to reports/eval_summary.json (the public synthetic eval output).",
    )
    ap.add_argument(
        "--aggregate",
        default=str(DEFAULT_AGGREGATE_PATH),
        help="Where to write the committable aggregate (ADR 0005 boundary).",
    )
    ap.add_argument(
        "--local",
        default=str(DEFAULT_LOCAL_PATH),
        help="Where to write per-case verdicts (git-ignored).",
    )
    ap.add_argument(
        "--backend",
        default=os.environ.get("BIDMATE_SYNTHETIC_JUDGE_BACKEND", "stub"),
        choices=sorted(_BACKENDS),
        help=(
            "Judge backend (defaults to BIDMATE_SYNTHETIC_JUDGE_BACKEND or 'stub'). "
            "Public CI must stay on 'stub' per ADR 0012."
        ),
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    summary_path = Path(args.summary)
    if not summary_path.exists():
        print(
            f"[ERROR] Eval summary not found: {summary_path}\n"
            "Run `make eval` (or `python eval/run_eval.py`) first.",
            file=sys.stderr,
        )
        return 2
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    local_payload, aggregate = judge_synthetic_summary(summary, backend=args.backend)

    local_path = Path(args.local)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(
        json.dumps(local_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    aggregate_path = Path(args.aggregate)
    aggregate_path.parent.mkdir(parents=True, exist_ok=True)
    aggregate_path.write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] Per-case verdicts written: {local_path}")
    print(f"[OK] Aggregate written: {aggregate_path}")
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
