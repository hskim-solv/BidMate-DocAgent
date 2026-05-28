#!/usr/bin/env python3
"""Render aggregate-only real100_v2 latency/cost budget envelope."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "reports" / "real100_v2" / "baseline.aggregate.json"
DEFAULT_OUT_JSON = ROOT / "reports" / "real100_v2" / "latency_cost_budget.aggregate.json"
DEFAULT_OUT_MD = ROOT / "docs" / "evaluation" / "real100_v2-latency-cost-budget.md"
STAGE_KEYS: tuple[str, ...] = (
    "query_analysis_ms",
    "context_resolution_ms",
    "retrieve_ms",
    "verify_ms",
    "answer_generation_ms",
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _require_real100_v2(path: Path) -> None:
    parts = set(path.parts)
    if "real100_v2" not in parts:
        raise ValueError(f"input must be under a real100_v2 path: {path}")
    if "real100" in parts:
        raise ValueError(f"legacy real100 input is not allowed: {path}")


def _source(path: Path) -> dict[str, Any]:
    resolved_root = ROOT.resolve()
    resolved_path = path.resolve()
    try:
        label = str(resolved_path.relative_to(resolved_root))
        redacted = False
    except ValueError:
        label = "external_private/real100_v2_baseline_aggregate"
        redacted = True
    return {
        "input_artifact": label,
        "input_location_redacted": redacted,
        "input_sha256_12": hashlib.sha256(path.read_bytes()).hexdigest()[:12],
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), 6)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _ceil_ms(value: float | None) -> float | None:
    if value is None:
        return None
    return float(math.ceil(value))


def _budget_from_p95(p95: float | None) -> dict[str, float | None]:
    if p95 is None:
        return {"soft_ceiling_ms": None, "hard_ceiling_ms": None}
    return {
        "soft_ceiling_ms": _ceil_ms(p95 * 1.25),
        "hard_ceiling_ms": _ceil_ms(p95 * 1.5),
    }


def _latency_block(raw: Mapping[str, Any]) -> dict[str, Any]:
    p95 = _number(raw.get("p95"))
    return {
        "mean_ms": _number(raw.get("mean")),
        "p50_ms": _number(raw.get("p50")),
        "p95_ms": p95,
        "p99_ms": None,
        "p99_status": "not_observed_in_source_aggregate",
        **_budget_from_p95(p95),
    }


def build_budget(payload: Mapping[str, Any], *, source: Mapping[str, Any] | None = None) -> dict[str, Any]:
    latency = _latency_block(_mapping(payload.get("latency")))
    stages: dict[str, Any] = {}
    stage_raw = _mapping(payload.get("stage_latency"))
    for stage in STAGE_KEYS:
        stages[stage] = _latency_block(_mapping(stage_raw.get(stage)))

    cost_raw = payload.get("synthesis_cost")
    token_raw = payload.get("synthesis_tokens")
    cost_observable = isinstance(cost_raw, Mapping)
    token_observable = isinstance(token_raw, Mapping)

    return {
        "schema_version": 1,
        "profile_type": "private_real100_v2_latency_cost_budget",
        "source": dict(source or {}),
        "population": {
            "num_predictions": int(payload.get("num_predictions") or 0),
            "pipeline": str(payload.get("pipeline") or ""),
            "primary_run": str(payload.get("primary_run") or ""),
            "prompt_profile": str(payload.get("prompt_profile") or ""),
        },
        "baseline_latency": latency,
        "stage_latency": stages,
        "budget_rules": {
            "soft_regression": "variant p95 above soft_ceiling_ms requires explicit reviewer justification",
            "hard_no_go": "variant p95 above hard_ceiling_ms cannot be called a winner",
            "quality_only_no_go": "quality gain without latency and cost evidence is not sufficient",
            "p99_rule": "p99 must be added when the source aggregate exposes it; currently not observed",
        },
        "cost_envelope": {
            "status": "not_observable_from_committed_aggregate"
            if not (cost_observable or token_observable)
            else "observable",
            "synthesis_cost_present": cost_observable,
            "synthesis_tokens_present": token_observable,
            "paid_api_rule": "paid or external reranker/synthesis cost must be reported separately before claim",
            "local_cpu_rule": "local reranker latency must be counted even when direct API cost is zero",
        },
        "hardware_caveats": {
            "scope": "local private real100_v2 baseline aggregate",
            "warm_cold_status": "not_split_in_committed_aggregate",
            "production_slo_claim": False,
        },
        "downstream_use": {
            "applies_to": [
                "T-2026-0032 reranker candidate-budget experiment",
                "candidate-pool sweeps",
                "query rewrite experiments",
                "context packing experiments",
            ],
            "winner_requires": [
                "paired real100_v2 quality delta",
                "no hard latency breach",
                "cost evidence present or explicitly not applicable",
                "privacy audit pass",
            ],
        },
        "privacy": {
            "aggregate_only": True,
            "raw_questions_omitted": True,
            "raw_answers_omitted": True,
            "raw_evidence_omitted": True,
            "doc_ids_omitted": True,
            "chunk_ids_omitted": True,
            "filenames_omitted": True,
            "paths_omitted": True,
            "per_case_rows_omitted": True,
        },
        "non_claims": {
            "runtime_behavior_changed": False,
            "performance_improvement_claim": False,
            "paired_delta": False,
            "legacy_real100_evidence_used": False,
        },
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    source = _mapping(report.get("source"))
    population = _mapping(report.get("population"))
    latency = _mapping(report.get("baseline_latency"))
    stages = _mapping(report.get("stage_latency"))
    cost = _mapping(report.get("cost_envelope"))
    caveats = _mapping(report.get("hardware_caveats"))
    rules = _mapping(report.get("budget_rules"))

    lines = [
        "# real100_v2 Latency And Cost Budget",
        "",
        "Issue: [#1626](https://github.com/hskim-solv/BidMate-DocAgent/issues/1626)",
        "",
        "Task: `T-2026-0030`",
        "",
        "Status: aggregate-only budget envelope; no runtime behavior change and no performance-improvement claim.",
        "",
        "## Boundary",
        "",
        "This report uses only committed `real100_v2` aggregate latency fields. It does not include raw questions, answers, evidence, filenames, local paths, document IDs, chunk IDs, or per-case rows. Legacy `real100`/v1/221/kordoc evidence is not used.",
        "",
        "## Source Provenance",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Input artifact | `{source.get('input_artifact') or ''}` |",
        f"| Input redacted | `{source.get('input_location_redacted')}` |",
        f"| Input SHA-256 prefix | `{source.get('input_sha256_12') or ''}` |",
        "",
        "## Baseline Population",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Predictions | {population.get('num_predictions', 0)} |",
        f"| Pipeline | `{population.get('pipeline')}` |",
        f"| Primary run | `{population.get('primary_run')}` |",
        f"| Prompt profile | `{population.get('prompt_profile')}` |",
        "",
        "## Overall Latency Envelope",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Mean ms | {latency.get('mean_ms')} |",
        f"| p50 ms | {latency.get('p50_ms')} |",
        f"| p95 ms | {latency.get('p95_ms')} |",
        f"| p99 ms | {latency.get('p99_ms')} |",
        f"| Soft ceiling ms | {latency.get('soft_ceiling_ms')} |",
        f"| Hard no-go ceiling ms | {latency.get('hard_ceiling_ms')} |",
        "",
        "p99 is named but not observed in the committed source aggregate.",
        "",
        "## Stage Latency Envelope",
        "",
        "| Stage | Mean | p50 | p95 | p99 | Soft ceiling | Hard ceiling |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for stage in STAGE_KEYS:
        row = _mapping(stages.get(stage))
        lines.append(
            f"| `{stage}` | {row.get('mean_ms')} | {row.get('p50_ms')} | "
            f"{row.get('p95_ms')} | {row.get('p99_ms')} | "
            f"{row.get('soft_ceiling_ms')} | {row.get('hard_ceiling_ms')} |"
        )

    lines.extend(
        [
            "",
            "## Cost Envelope",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Status | `{cost.get('status')}` |",
            f"| Synthesis cost present | `{cost.get('synthesis_cost_present')}` |",
            f"| Synthesis tokens present | `{cost.get('synthesis_tokens_present')}` |",
            f"| Paid API rule | {cost.get('paid_api_rule')} |",
            f"| Local CPU rule | {cost.get('local_cpu_rule')} |",
            "",
            "## Guardrail Rules",
            "",
            f"- Soft regression: {rules.get('soft_regression')}",
            f"- Hard no-go: {rules.get('hard_no_go')}",
            f"- Quality-only no-go: {rules.get('quality_only_no_go')}",
            f"- p99 rule: {rules.get('p99_rule')}",
            "",
            "## Caveats",
            "",
            f"- Scope: `{caveats.get('scope')}`",
            f"- Warm/cold status: `{caveats.get('warm_cold_status')}`",
            f"- Production SLO claim: `{caveats.get('production_slo_claim')}`",
            "",
            "## Downstream Use",
            "",
            "`T-2026-0032` and later candidate-pool, query rewrite, and context-packing experiments can cite this envelope. A quality-only gain is no-go unless latency stays under the hard ceiling and cost evidence is present or explicitly not applicable.",
            "",
            "## Non-Claims",
            "",
            "- No runtime retrieval, reranking, verifier, answer, ingestion, chunking, or eval scoring behavior changed.",
            "- No paired delta was produced.",
            "- No performance improvement is claimed.",
            "- No legacy `real100`/v1/221/kordoc evidence is used.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render aggregate-only real100_v2 latency/cost budget envelope.",
    )
    parser.add_argument("--summary", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        _require_real100_v2(args.summary)
        payload = _load_json(args.summary)
        report = build_budget(payload, source=_source(args.summary))
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"Failed to render real100_v2 latency budget: {exc}", file=sys.stderr)
        return 1

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.out_md.write_text(render_markdown(report), encoding="utf-8")
    print(f"[OK] Wrote {args.out_json}")
    print(f"[OK] Wrote {args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
