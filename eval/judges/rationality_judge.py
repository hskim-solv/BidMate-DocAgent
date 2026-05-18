#!/usr/bin/env python3
"""Trajectory-rationality judge (3-axis process measurement, ADR 0056).

Phase 3 audit (PR #961) found that the eval framework had zero LLM-judge
surface scoring **process rationality** — only answer quality (Gate 1
real-data, Gate 2 synthetic, Gate 3 RAGAS).  This module fills that gap
by adding a judge that scores three trajectory axes from the per-case
trace dict (issue #969, Step 3/5 of sequence A; supplies Phase 3 item 3).

Three axes, each a float in ``[0.0, 1.0]``:

* ``planner_decomposition`` — does the planner's selected stage / pipeline
  / retrieval_budget reasonably cover the query intent without obvious
  over-decomposition?  Input: ``trace["planner"]`` subset.
* ``retrieval_recalls`` — are retry recall reasons evidence-driven (e.g.
  ``topic_not_grounded``, ``partial_topic_grounding``, ``low_recall``)
  rather than noise loops?  Input:
  ``trace["planner"]["attempts"][*]["verification_reasons"]``.
* ``answer_reasoning`` — is the synthesis prompt → completion consistent
  with the evidence shown?  Input:
  ``trace["synthesis_llm_call"]["user_prompt_text"]`` +
  ``["completion_text"]`` (issue #967 Step 2 prerequisite — populated
  only when ``BIDMATE_TRACE_FULL=1`` was set during eval).  Returns
  ``None`` for cases without a captured synthesis LLM call.

Backends (same pattern as ``eval/judges/llm_judge.py`` — Gate 3 RAGAS):

* ``stub`` (default) — deterministic SHA-256 hash of the per-axis input
  subset.  Zero cost, byte-identical across platforms, suitable for CI.
* ``openai_compatible`` — generic OpenAI-compatible endpoint
  (Anthropic-Compat, OpenAI, vLLM, etc.).  Re-uses
  ``eval.judges.judge_common.build_openai_client()`` so the same env
  contract applies (``BIDMATE_JUDGE_API_KEY`` / ``BIDMATE_JUDGE_MODEL`` /
  ``BIDMATE_JUDGE_BASE_URL``).  Asks all three axes in one LLM call per
  case.

The aggregate dict reports per-axis mean + 95 % bootstrap CI +
``effective_n`` (axes with all-None scores report ``effective_n=0`` and
``mean=None`` rather than fabricating a band).

This module is a **read-only consumer** of trace JSON — ADR 0001 /
0003 / 0005 invariance preserved (no production code path imports it).
"""
from __future__ import annotations

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
    build_openai_client,
    call_openai_json,
    clamp_score,
    get_judge_model,
)
from rag_core import neutralize_instruction_patterns  # noqa: E402

RATIONALITY_AXES: tuple[str, ...] = (
    "planner_decomposition",
    "retrieval_recalls",
    "answer_reasoning",
)
DEFAULT_CACHE_DIR = ROOT_DIR / "reports" / "rationality_cache"
DEFAULT_TOKEN_BUDGET = 200_000

PROMPT_TEMPLATE = """You are scoring the **process rationality** of a retrieval-augmented QA system on a procurement (RFP) document — not the answer's correctness, but whether the planner / retrieval-retry / synthesis steps were *reasonably justified*.

Query:
{query}

Trace (truncated; JSON):
{trace_json}

Rate three axes on a 0.0-1.0 scale:

- planner_decomposition: did the planner's stage / pipeline / retrieval_budget reasonably cover the query intent without obvious over-decomposition?
- retrieval_recalls: are retry recall reasons (verification_reasons across attempts) evidence-driven (topic-not-grounded, partial-topic-grounding, low-recall) rather than noise loops?
- answer_reasoning: does the synthesis completion stay consistent with the evidence text shown in the prompt? Reply with `null` for this axis if no synthesis LLM call was captured.

Reply ONLY with valid JSON of the form:
{{"planner_decomposition": float,
  "retrieval_recalls": float,
  "answer_reasoning": float or null,
  "reason_short": "short rationale, <= 200 chars"}}
"""


# -----------------------------------------------------------------------------
# Trace loading helpers
# -----------------------------------------------------------------------------


def _load_trace(case: dict[str, Any], traces_dir: Path | None) -> dict[str, Any] | None:
    """Resolve a case's trace JSON.

    Order: ``case["trace"]`` (embedded — rare) → ``case["trace_path"]``
    relative to ``traces_dir`` if absolute lookup fails → ``None`` on
    missing file.  Returns the parsed trace dict.
    """
    embedded = case.get("trace")
    if isinstance(embedded, dict):
        return embedded
    trace_path = case.get("trace_path")
    if not trace_path:
        return None
    path = Path(trace_path)
    if not path.is_absolute() and traces_dir is not None:
        # caller passed an override base — try basename under it first
        candidate = traces_dir / path.name
        if candidate.exists():
            path = candidate
    if not path.exists():
        # also accept paths relative to repo root (the eval writer's default)
        repo_relative = ROOT_DIR / trace_path
        if repo_relative.exists():
            path = repo_relative
        else:
            return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _planner_subset(trace: dict[str, Any]) -> dict[str, Any]:
    """Extract the planner-side input subset for the planner_decomposition axis."""
    inner = trace.get("trace") if isinstance(trace.get("trace"), dict) else trace
    planner = (
        inner.get("planner") if isinstance(inner.get("planner"), dict) else {}
    )
    return {
        "query_type": planner.get("query_type"),
        "pipeline": planner.get("pipeline"),
        "stage_sequence": planner.get("stage_sequence"),
        "selected_top_k": planner.get("selected_top_k"),
        "retrieval_budget_reason": (
            (planner.get("retrieval_budget") or {}).get("reason")
            if isinstance(planner.get("retrieval_budget"), dict)
            else None
        ),
    }


def _retrieval_subset(trace: dict[str, Any]) -> list[list[str]]:
    """Extract per-attempt verification_reasons for the retrieval_recalls axis."""
    inner = trace.get("trace") if isinstance(trace.get("trace"), dict) else trace
    planner = (
        inner.get("planner") if isinstance(inner.get("planner"), dict) else {}
    )
    attempts = planner.get("attempts") if isinstance(planner.get("attempts"), list) else []
    return [
        list(att.get("verification_reasons") or [])
        for att in attempts
        if isinstance(att, dict)
    ]


def _synthesis_subset(trace: dict[str, Any]) -> dict[str, Any] | None:
    """Extract synthesis prompt + completion (issue #967 v2 trace key).

    Returns ``None`` when the case ran without ``BIDMATE_TRACE_FULL=1`` —
    the synthesis_llm_call key is then absent or ``None``.
    """
    inner = trace.get("trace") if isinstance(trace.get("trace"), dict) else trace
    # Step 2 (#968) puts synthesis_llm_call at trace top-level (sibling of
    # planner / answer_schema); some older shapes may nest under "trace".
    call = inner.get("synthesis_llm_call") or trace.get("synthesis_llm_call")
    if not isinstance(call, dict):
        return None
    prompt = call.get("user_prompt_text")
    completion = call.get("completion_text")
    if not prompt or not completion:
        return None
    return {
        "user_prompt_text": str(prompt),
        "completion_text": str(completion),
    }


# -----------------------------------------------------------------------------
# Backends
# -----------------------------------------------------------------------------


def _stub_score(payload: Any, axis: str, case_id: str) -> float:
    """Deterministic SHA-256 → [0,1] mapping for stub backend.

    The same (payload, axis, case_id) always yields the same score, and
    the score is uniformly distributed across cases so distribution
    aggregates remain meaningful for stub-only smoke runs.
    """
    blob = json.dumps(
        {"payload": payload, "axis": axis, "case_id": case_id},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(blob).digest()
    # first 8 bytes → uint64 → [0, 1)
    bucket = int.from_bytes(digest[:8], byteorder="big")
    return bucket / float(1 << 64)


def _stub_backend(case_id: str, trace: dict[str, Any]) -> dict[str, Any]:
    """Return per-axis stub scores. ``answer_reasoning`` is ``None`` when
    no synthesis LLM call was captured — the same skip semantics as the
    LLM backend, so the aggregate matches across backends on env=off cases.
    """
    planner = _planner_subset(trace)
    retrieval = _retrieval_subset(trace)
    synthesis = _synthesis_subset(trace)
    return {
        "planner_decomposition": _stub_score(planner, "planner_decomposition", case_id),
        "retrieval_recalls": _stub_score(retrieval, "retrieval_recalls", case_id),
        "answer_reasoning": (
            _stub_score(synthesis, "answer_reasoning", case_id)
            if synthesis is not None
            else None
        ),
        "reason_short": "stub: SHA-256(trace subset, axis, case_id)",
    }


def _build_llm_prompt(case: dict[str, Any], trace: dict[str, Any]) -> str:
    query = neutralize_instruction_patterns(str(case.get("query") or ""))
    # Truncate trace JSON to keep prompt bounded.  We embed the same
    # subsets the stub backend uses so the two backends see the same
    # surface area.
    payload = {
        "planner": _planner_subset(trace),
        "retrieval_verification_reasons": _retrieval_subset(trace),
        "synthesis_llm_call": _synthesis_subset(trace),
    }
    trace_json = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(trace_json) > 4000:
        trace_json = trace_json[:4000] + "\n... (truncated)"
    return PROMPT_TEMPLATE.format(query=query, trace_json=trace_json)


def _openai_compatible_backend(  # pragma: no cover - network
    case_id: str, trace: dict[str, Any], *, case: dict[str, Any]
) -> dict[str, Any]:
    client = build_openai_client()
    model = get_judge_model()
    prompt = _build_llm_prompt(case, trace)
    payload = call_openai_json(client, model, prompt) or {}
    return _normalize_verdict(payload, has_synthesis=_synthesis_subset(trace) is not None)


_BACKENDS: dict[str, str] = {
    "stub": "_stub_backend",
    "openai_compatible": "_openai_compatible_backend",
}


def _normalize_verdict(payload: dict[str, Any], *, has_synthesis: bool) -> dict[str, Any]:
    """Clamp axis scores; drop ``answer_reasoning`` to ``None`` when env=off."""
    out: dict[str, Any] = {}
    for axis in RATIONALITY_AXES:
        if axis == "answer_reasoning" and not has_synthesis:
            out[axis] = None
            continue
        raw = payload.get(axis)
        if raw is None and axis == "answer_reasoning":
            out[axis] = None
        else:
            out[axis] = clamp_score(raw)
    out["reason_short"] = str(payload.get("reason_short") or "")[:200]
    return out


# -----------------------------------------------------------------------------
# Aggregate
# -----------------------------------------------------------------------------


def _aggregate(judged: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-axis mean + bootstrap CI + effective_n.

    ``None`` scores (e.g. ``answer_reasoning`` for env=off cases) drop
    out of the numerator and denominator — matches ADR 0054
    substantive-only semantics.
    """
    out: dict[str, Any] = {
        "n": len(judged),
        "axis_means": {},
        "axis_cis": {},
        "effective_n": {},
    }
    for axis in RATIONALITY_AXES:
        scores = [
            float(c[axis]) for c in judged if c.get(axis) is not None
        ]
        out["effective_n"][axis] = len(scores)
        if scores:
            out["axis_means"][axis] = sum(scores) / len(scores)
            ci = bootstrap_ci(scores)
            if ci is not None:
                out["axis_cis"][axis] = ci
        else:
            out["axis_means"][axis] = None
    out["cases_with_synthesis_llm_call"] = out["effective_n"].get(
        "answer_reasoning", 0
    )
    return out


# -----------------------------------------------------------------------------
# Pipeline
# -----------------------------------------------------------------------------


def judge_rationality(
    summary: dict[str, Any],
    *,
    backend: str = "stub",
    traces_dir: Path | None = None,
    cache_dir: Path | None = None,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Score 3-axis trajectory rationality over an eval_summary dict.

    Returns ``(local_payload, aggregate)``.  ``local_payload`` carries
    per-case axis scores (gitignored).  ``aggregate`` is committable
    (mean + bootstrap CI + effective_n per axis).

    Backend selection:
        ``stub`` (default) — deterministic SHA-256 hash over per-axis input
        subsets.  Zero cost, byte-identical across platforms, suitable
        for CI.
        ``openai_compatible`` — 1 LLM call per case (3-axis bundled).
        Honours ``token_budget`` (input-token estimate) — raises
        ``RuntimeError`` if exceeded.

    ``cache_dir`` is currently unused (stub is free, LLM backend cache
    will land in a follow-up — the parameter is reserved for API
    compatibility with Gate 3 RAGAS).
    """
    if backend not in _BACKENDS:
        raise ValueError(
            f"Unknown rationality backend {backend!r}; "
            f"choose one of {sorted(_BACKENDS)}."
        )
    if cache_dir is None:
        cache_dir = DEFAULT_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    model = os.environ.get("BIDMATE_JUDGE_MODEL", "stub")

    case_results = summary.get("case_results") or []
    judged: list[dict[str, Any]] = []
    skipped_no_trace = 0
    tokens_estimated = 0

    for case in case_results:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("id") or "")
        trace = _load_trace(case, traces_dir)
        if trace is None:
            skipped_no_trace += 1
            continue
        if backend == "stub":
            verdict = _stub_backend(case_id, trace)
        else:  # pragma: no cover - network
            prompt = _build_llm_prompt(case, trace)
            est = max(1, len(prompt) // 3)
            if tokens_estimated + est > token_budget:
                raise RuntimeError(
                    f"Rationality judge token budget {token_budget} would be "
                    f"exceeded (estimated +{est} on top of {tokens_estimated}). "
                    "Raise --token-budget deliberately or reduce the case set."
                )
            tokens_estimated += est
            verdict = _openai_compatible_backend(case_id, trace, case=case)
        judged.append(
            {
                "id": case_id,
                "slice": case.get("slice"),
                "query_type": case.get("query_type"),
                **verdict,
            }
        )

    aggregate = _aggregate(judged)
    aggregate["skipped_no_trace"] = skipped_no_trace
    local_payload = {
        "schema_version": 1,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "backend": backend,
        "model": model,
        "cases": judged,
        "skipped_no_trace": skipped_no_trace,
        "tokens_estimated": tokens_estimated,
    }
    return local_payload, aggregate


# -----------------------------------------------------------------------------
# Markdown rendering
# -----------------------------------------------------------------------------


def render_markdown(aggregate: dict[str, Any], local_payload: dict[str, Any]) -> str:
    """Render aggregate + bottom-3 cases per weak axis as Markdown.

    The Markdown file lives at ``reports/real100/rationality.md`` and is
    intentionally compact (single-screen) so it fits the existing
    ``rag_pipeline.md`` / ``distinguishing_power.md`` neighbourhood.
    """
    lines: list[str] = []
    lines.append("# Trajectory rationality (ADR 0056)")
    lines.append("")
    lines.append(
        f"- n: {aggregate.get('n', 0)} "
        f"(skipped_no_trace={aggregate.get('skipped_no_trace', 0)}; "
        f"cases_with_synthesis_llm_call="
        f"{aggregate.get('cases_with_synthesis_llm_call', 0)})"
    )
    lines.append(f"- backend: {local_payload.get('backend', '?')}")
    lines.append(f"- model: {local_payload.get('model', '?')}")
    lines.append("")
    lines.append("## Per-axis mean + 95 % CI")
    lines.append("")
    lines.append("| axis | mean | 95 % CI | effective_n |")
    lines.append("|---|---:|---|---:|")
    means = aggregate.get("axis_means", {}) or {}
    cis = aggregate.get("axis_cis", {}) or {}
    eff_n = aggregate.get("effective_n", {}) or {}
    for axis in RATIONALITY_AXES:
        mean = means.get(axis)
        ci = cis.get(axis)
        mean_str = f"{mean:.3f}" if isinstance(mean, (int, float)) else "N/A"
        if ci and isinstance(ci.get("ci_lo"), (int, float)):
            ci_str = f"({ci['ci_lo']:.3f}, {ci['ci_hi']:.3f})"
        else:
            ci_str = "N/A"
        lines.append(f"| `{axis}` | {mean_str} | {ci_str} | {eff_n.get(axis, 0)} |")
    lines.append("")
    lines.append("## Bottom 3 cases per axis (rationale review)")
    cases = local_payload.get("cases", []) or []
    for axis in RATIONALITY_AXES:
        scored = [
            c for c in cases if isinstance(c.get(axis), (int, float))
        ]
        if not scored:
            lines.append("")
            lines.append(f"### `{axis}` — no scored cases")
            continue
        bottom = sorted(scored, key=lambda c: c[axis])[:3]
        lines.append("")
        lines.append(f"### `{axis}` — bottom 3")
        lines.append("")
        for c in bottom:
            lines.append(
                f"- `{c.get('id', '?')}` (slice={c.get('slice')}) "
                f"= {c[axis]:.3f} — {str(c.get('reason_short', ''))[:100]}"
            )
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "RATIONALITY_AXES",
    "DEFAULT_CACHE_DIR",
    "DEFAULT_TOKEN_BUDGET",
    "judge_rationality",
    "render_markdown",
]
