#!/usr/bin/env python3
"""LLM-judge for the local real-data eval surface (ADR 0006).

Reads ``reports/real100/eval_summary.json``, asks a configured LLM
backend whether each case's answer is supported by its evidence, and
writes the per-case verdicts to ``reports/real100/judge.local.json``
(git-ignored) plus an aggregate-only summary to stdout.

**Scope discipline.** This script runs on the real-data surface only.
The public CI path must not call it (ADR 0004 + ADR 0006).

Backends:

* ``stub`` (default) — deterministic synthetic verdict. No network.
  Used by tests and by users without an API key. Produces verdicts
  that exactly mirror the deterministic verifier's status so
  ``agreement_with_verifier`` is 1.0 on a clean stub run.
* ``openai_compatible`` — generic OpenAI-compatible endpoint
  (Anthropic-Compat, OpenAI, vLLM, llama.cpp server, etc.). Reads
  ``BIDMATE_JUDGE_API_KEY``, ``BIDMATE_JUDGE_MODEL``,
  ``BIDMATE_JUDGE_BASE_URL``.

Output schema for the local file (per-case, never committed):

    {
      "schema_version": 1,
      "generated_at": "ISO8601Z",
      "backend": "stub" | "openai_compatible" | ...,
      "model": "string",
      "cases": [
        {
          "id": "...",
          "judge_status": "supported" | "partial" | "insufficient",
          "judge_grounded": bool,
          "judge_reason_short": "≤ 200 chars",
          "verifier_status": "...",
          "agrees": bool
        }
      ]
    }

The committable aggregate (merged into baseline.aggregate.json by
``scripts/write_real_eval_baseline.py``) contains only
``judge.status_distribution``, ``judge.grounded_rate``, and
``judge.agreement_with_verifier``.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVAL_PATH = ROOT / "reports" / "real100" / "eval_summary.json"
DEFAULT_OUTPUT_PATH = ROOT / "reports" / "real100" / "judge.local.json"

JUDGE_STATUSES = ("supported", "partial", "insufficient")

PROMPT_TEMPLATE = """You are reviewing one answer from a retrieval-augmented QA
system on a procurement (RFP) document. Judge whether the answer is
supported by the evidence chunks.

Query:
{query}

Answer summary:
{summary}

Top evidence chunks:
{evidence}

Reply ONLY with valid JSON of the form:
{{"judge_status": "supported" | "partial" | "insufficient",
  "judge_grounded": true | false,
  "judge_reason_short": "short reason, <= 200 chars"}}
"""


# -----------------------------------------------------------------------------
# Backends
# -----------------------------------------------------------------------------


def _stub_backend(_prompt: str, *, verifier_status: str) -> dict[str, Any]:
    """Deterministic stub.

    Echoes the verifier's status so a stub-mode run produces
    ``agreement_with_verifier == 1.0`` — useful for plumbing tests
    and for users without an API key who still want to exercise the
    flow.
    """
    return {
        "judge_status": verifier_status if verifier_status in JUDGE_STATUSES else "insufficient",
        "judge_grounded": verifier_status == "supported",
        "judge_reason_short": "stub backend: verifier status echoed",
    }


def _openai_compatible_backend(prompt: str, *, verifier_status: str) -> dict[str, Any]:  # pragma: no cover - network
    """Generic OpenAI-compatible endpoint backend.

    Imported lazily so the stub-only test path has no network / SDK
    dependency.
    """
    try:
        from openai import OpenAI  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError(
            "openai_compatible backend requires the openai SDK. "
            "Install with `pip install openai` or use BIDMATE_JUDGE_BACKEND=stub."
        ) from exc

    api_key = os.environ.get("BIDMATE_JUDGE_API_KEY")
    if not api_key:
        raise RuntimeError("BIDMATE_JUDGE_API_KEY is not set.")
    base_url = os.environ.get("BIDMATE_JUDGE_BASE_URL") or None
    model = os.environ.get("BIDMATE_JUDGE_MODEL")
    if not model:
        raise RuntimeError("BIDMATE_JUDGE_MODEL is not set.")

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    return _normalize_judge_payload(parsed, fallback_status=verifier_status)


def _normalize_judge_payload(
    payload: dict[str, Any], fallback_status: str
) -> dict[str, Any]:
    status = str(payload.get("judge_status") or "").strip().lower()
    if status not in JUDGE_STATUSES:
        status = fallback_status if fallback_status in JUDGE_STATUSES else "insufficient"
    grounded = bool(payload.get("judge_grounded", False))
    reason = str(payload.get("judge_reason_short") or "")[:200]
    return {
        "judge_status": status,
        "judge_grounded": grounded,
        "judge_reason_short": reason,
    }


_BACKENDS = {
    "stub": _stub_backend,
    "openai_compatible": _openai_compatible_backend,
}


# -----------------------------------------------------------------------------
# Pipeline
# -----------------------------------------------------------------------------


def _build_prompt(case: dict[str, Any]) -> str:
    query = case.get("query") or ""
    answer = case.get("answer") or ""
    if isinstance(answer, dict):
        summary = str(answer.get("summary") or "")
    else:
        summary = str(answer)
    evidence_items = case.get("evidence") or []
    evidence_lines = []
    for i, item in enumerate(evidence_items[:3], start=1):
        text = (item.get("text") if isinstance(item, dict) else "") or ""
        evidence_lines.append(f"[{i}] {text[:600]}")
    evidence_block = "\n".join(evidence_lines) or "(no evidence)"
    return PROMPT_TEMPLATE.format(
        query=query, summary=summary, evidence=evidence_block
    )


def _aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the *committable* aggregate from per-case verdicts."""
    statuses = [c["judge_status"] for c in cases if c.get("judge_status")]
    grounded = [bool(c.get("judge_grounded")) for c in cases]
    agreements = [bool(c.get("agrees")) for c in cases if c.get("agrees") is not None]
    return {
        "status_distribution": dict(Counter(statuses)),
        "grounded_rate": (sum(grounded) / len(grounded)) if grounded else None,
        "agreement_with_verifier": (
            sum(agreements) / len(agreements) if agreements else None
        ),
        "n": len(cases),
    }


def judge_summary(
    summary: dict[str, Any],
    backend: str = "stub",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the judge over an eval_summary dict.

    Returns ``(local_payload, aggregate)`` — the caller decides where
    to write each. The aggregate is safe to commit; the local payload
    contains per-case judge text and stays under the ADR 0005 boundary.
    """
    if backend not in _BACKENDS:
        raise ValueError(
            f"Unknown judge backend {backend!r}; "
            f"choose one of {sorted(_BACKENDS)}."
        )
    backend_fn = _BACKENDS[backend]

    case_results = summary.get("case_results") or []
    judged: list[dict[str, Any]] = []
    for case in case_results:
        if not isinstance(case, dict):
            continue
        prompt = _build_prompt(case)
        verifier_status = str(case.get("answer_status") or "insufficient")
        verdict = backend_fn(prompt, verifier_status=verifier_status)
        judged.append(
            {
                "id": case.get("id"),
                "judge_status": verdict["judge_status"],
                "judge_grounded": verdict["judge_grounded"],
                "judge_reason_short": verdict["judge_reason_short"],
                "verifier_status": verifier_status,
                "agrees": verdict["judge_status"] == verifier_status,
            }
        )

    local_payload = {
        "schema_version": 1,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "backend": backend,
        "model": os.environ.get("BIDMATE_JUDGE_MODEL", "stub"),
        "cases": judged,
    }
    return local_payload, _aggregate(judged)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--eval-summary",
        default=str(DEFAULT_EVAL_PATH),
        help="Path to reports/real100/eval_summary.json",
    )
    ap.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Where to write the per-case judge verdicts (git-ignored).",
    )
    ap.add_argument(
        "--backend",
        default=os.environ.get("BIDMATE_JUDGE_BACKEND", "stub"),
        choices=sorted(_BACKENDS),
        help="Judge backend (defaults to BIDMATE_JUDGE_BACKEND or 'stub').",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    summary_path = Path(args.eval_summary)
    if not summary_path.exists():
        print(
            f"[ERROR] Eval summary not found: {summary_path}\n"
            "Run `make real-eval` first.",
            file=sys.stderr,
        )
        return 2
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    local_payload, aggregate = judge_summary(summary, backend=args.backend)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(local_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] Per-case verdicts written: {output_path}")
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
