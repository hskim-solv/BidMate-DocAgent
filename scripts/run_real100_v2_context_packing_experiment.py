#!/usr/bin/env python3
"""Run an aggregate-only real100_v2 context-packing experiment.

The experiment is opt-in and local-only. It monkeypatches the answer-side
supporting-evidence selector inside this runner, leaving default runtime
retrieval, reranking, verification, and answer schema behavior unchanged.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.run_eval import load_config, normalize_run_config  # noqa: E402
from eval.scorers import derive_gold_evidence, score_case  # noqa: E402
from rag_core import DEFAULT_RAG_PIPELINE_NAME, _run_rag_query_with_plan_overrides, load_index, percentile, rate  # noqa: E402
from rag_verifier import evidence_text_for_verification  # noqa: E402
from scripts.run_private_hybrid_sweep import (  # noqa: E402
    assert_aggregate_privacy_safe,
    assert_rendered_output_privacy_safe,
    render_output_path,
)
from scripts.run_real100_v2_reranker_budget_sweep import _cost_status, _latency_hard_ceiling_ms  # noqa: E402


DEFAULT_CONFIG = ROOT / "data" / "private" / "real100_v2" / "real_config_v2.local.yaml"
DEFAULT_INDEX_DIR = ROOT / "data" / "index" / "real100_v2"
DEFAULT_LATENCY_BUDGET = ROOT / "reports" / "real100_v2" / "latency_cost_budget.aggregate.json"
DEFAULT_OUT_JSON = ROOT / "reports" / "real100_v2" / "context_packing.aggregate.json"
DEFAULT_OUT_MD = ROOT / "docs" / "evaluation" / "real100_v2-context-packing.md"
MATERIAL_METRIC_DELTA = 0.005
REGRESSION_TOLERANCE = 0.001
LATENCY_REGRESSION_RATIO = 0.05
LATENCY_REGRESSION_MS = 10.0


@dataclass(frozen=True)
class VariantSpec:
    name: str
    selector: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Private real100_v2 eval config.")
    parser.add_argument("--index-dir", default=str(DEFAULT_INDEX_DIR), help="Private real100_v2 index directory.")
    parser.add_argument("--latency-budget", default=str(DEFAULT_LATENCY_BUDGET))
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    parser.add_argument("--cases-subset-n", type=int, default=None)
    parser.add_argument("--variant", default="evidence_first", choices=("evidence_first",))
    return parser.parse_args(argv)


def _require_real100_v2(path: Path, *, label: str) -> None:
    if "real100_v2" not in path.as_posix():
        raise ValueError(f"{label} must reference real100_v2")


def _base_run_config(config: dict[str, Any]) -> dict[str, Any]:
    for run in config.get("ablation_runs") or []:
        if isinstance(run, dict) and str(run.get("name") or "") == "full":
            base = normalize_run_config(run)
            break
    else:
        base = normalize_run_config(
            {
                "name": "full",
                "pipeline": DEFAULT_RAG_PIPELINE_NAME,
                "metadata_first": True,
                "rerank": True,
                "rerank_cross_encoder": False,
                "verifier_retry": True,
                "retrieval_mode": "flat",
                "retrieval_backend": "hybrid",
                "query_expansion": "identity",
            }
        )
    base["name"] = "full"
    return base


def _query_kwargs(run_config: dict[str, Any], *, context_entities: list[str] | None = None, conversation_state: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "pipeline": str(run_config.get("pipeline") or DEFAULT_RAG_PIPELINE_NAME),
        "top_k": run_config.get("top_k"),
        "context_entities": context_entities or [],
        "metadata_first": bool(run_config.get("metadata_first", True)),
        "rerank": bool(run_config.get("rerank", True)),
        "rerank_cross_encoder": bool(run_config.get("rerank_cross_encoder", False)),
        "verifier_retry": bool(run_config.get("verifier_retry", True)),
        "retrieval_mode": str(run_config.get("retrieval_mode", "flat")),
        "retrieval_backend": str(run_config.get("retrieval_backend", "hybrid")),
        "prompt_profile": str(run_config.get("prompt_profile") or ""),
        "conversation_state": conversation_state,
        "rrf_k": int(run_config.get("rrf_k") or 60),
        "bm25_stopword_profile": str(run_config.get("bm25_stopword_profile", "shared")),
        "bm25_tokenizer": str(run_config.get("bm25_tokenizer", "regex")),
        "bm25_backend": str(run_config.get("bm25_backend", "okapi")),
    }


def _topics(analysis: dict[str, Any]) -> list[str]:
    raw = analysis.get("topics") or analysis.get("conditions") or []
    return [str(item).strip().lower() for item in raw if str(item).strip()]


def _topic_hits(item: dict[str, Any], topics: list[str]) -> int:
    if not topics:
        return 0
    text = evidence_text_for_verification(item).lower()
    return sum(1 for topic in topics if topic in text)


def _dedupe_key(item: dict[str, Any]) -> tuple[str, str, str]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    span = str(item.get("text_span_hash") or metadata.get("text_span_hash") or "")
    section = str(item.get("section_id") or item.get("section") or "")
    return (str(item.get("doc_id") or ""), section, span)


def evidence_first_selector(analysis: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    topics = _topics(analysis)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in sorted(
        evidence,
        key=lambda row: (
            _topic_hits(row, topics),
            float(row.get("score") or 0.0),
            -int(row.get("rank") or 0),
        ),
        reverse=True,
    ):
        key = _dedupe_key(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    if analysis.get("query_type") == "comparison":
        selected = []
        entities = analysis.get("entities") or analysis.get("context_entities") or []
        for entity in entities:
            match = next((item for item in deduped if item.get("agency") == entity), None)
            if match:
                selected.append(match)
        if selected:
            return selected[:2]
    return deduped[:2]


@contextmanager
def patched_selector(selector: Callable[[dict[str, Any], list[dict[str, Any]]], list[dict[str, Any]]] | None) -> Iterator[None]:
    if selector is None:
        yield
        return
    import rag_core

    original = rag_core.select_supporting_evidence
    rag_core.select_supporting_evidence = selector
    try:
        yield
    finally:
        rag_core.select_supporting_evidence = original


def _run_prediction(index: dict[str, Any], case: dict[str, Any], run_config: dict[str, Any], *, conversation_state: dict[str, Any] | None = None) -> dict[str, Any]:
    return _run_rag_query_with_plan_overrides(
        index,
        str(case["query"]),
        plan_overrides={},
        **_query_kwargs(
            run_config,
            context_entities=case.get("context_entities") or [],
            conversation_state=conversation_state,
        ),
    )


def _mean(values: list[Any]) -> float | None:
    return rate([float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)])


def _count_rate(count: int, denominator: int) -> dict[str, Any]:
    return {"count": count, "rate": (count / denominator) if denominator else None, "denominator": denominator}


def _latency_summary(values: list[float]) -> dict[str, Any]:
    return {"p50": percentile(values, 0.50), "p95": percentile(values, 0.95), "count": len(values)}


def evaluate_variant(index: dict[str, Any], cases: list[dict[str, Any]], run_config: dict[str, Any], spec: VariantSpec, answer_policy: dict[str, Any] | None) -> dict[str, Any]:
    selector = evidence_first_selector if spec.selector == "evidence_first" else None
    results: list[dict[str, Any]] = []
    token_in: list[Any] = []
    token_out: list[Any] = []
    costs: list[Any] = []
    with patched_selector(selector):
        for case in cases:
            conversation_state: dict[str, Any] = {}
            for turn in case.get("prior_turns") or []:
                prior = _run_prediction(
                    index,
                    {"query": turn["query"], "context_entities": turn.get("context_entities") or []},
                    run_config,
                    conversation_state=conversation_state,
                )
                conversation_state = prior.get("conversation_state") or conversation_state
            prediction = _run_prediction(index, case, run_config, conversation_state=conversation_state)
            synthesis = ((prediction.get("diagnostics") or {}).get("synthesis") or {})
            if isinstance(synthesis, dict):
                token_in.append(synthesis.get("input_tokens") or synthesis.get("prompt_tokens"))
                token_out.append(synthesis.get("output_tokens") or synthesis.get("completion_tokens"))
                costs.append(synthesis.get("cost_estimate_usd"))
            gold_evidence = derive_gold_evidence(case, index)
            gold_chunk_ids = [
                str(item.get("chunk_id") or "")
                for item in gold_evidence
                if isinstance(item, dict) and item.get("chunk_id")
            ]
            results.append(
                score_case(
                    case,
                    prediction,
                    answer_policy,
                    gold_chunk_ids=gold_chunk_ids,
                    gold_evidence=gold_evidence,
                )
            )
    latencies = [float(row["latency_ms"]) for row in results if row.get("latency_ms") is not None]
    return {
        "name": spec.name,
        "variant": spec.selector,
        "num_cases": len(results),
        "invariants": {
            "retrieval_behavior": "unchanged",
            "reranker_behavior": "unchanged",
            "answer_schema": "unchanged",
        },
        "metrics": {
            "response_quality": {
                "accuracy": _mean([row.get("accuracy") for row in results]),
                "groundedness": _mean([row.get("groundedness") for row in results]),
                "answer_format_compliance": _mean([row.get("answer_format_compliance") for row in results]),
            },
            "citation": {
                "citation_precision": _mean([row.get("citation_precision") for row in results]),
                "claim_citation_alignment": _mean([row.get("claim_citation_alignment") for row in results]),
            },
            "abstention": {
                "abstention": _mean([row.get("abstention") for row in results]),
                "insufficient_status_count": sum(1 for row in results if row.get("status") == "insufficient"),
            },
            "token_cost": {
                "input_tokens_mean": _mean(token_in),
                "output_tokens_mean": _mean(token_out),
                "cost_estimate_usd_mean": _mean(costs),
                "status": "present" if _mean(token_in + token_out + costs) is not None else "not_observable_from_prediction_diagnostics",
            },
            "latency_ms": _latency_summary(latencies),
        },
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _metric(variant: dict[str, Any], *path: str) -> float | None:
    node: Any = variant
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return _number(node)


def classify_variants(variants: list[dict[str, Any]], latency_budget: dict[str, Any]) -> dict[str, Any]:
    if len(variants) < 2:
        return {"overall_classification": "failed_experiment", "selected_variant": None, "variants": []}
    control = variants[0]
    hard_latency = _latency_hard_ceiling_ms(latency_budget)
    rows: list[dict[str, Any]] = []
    for variant in variants[1:]:
        classifications: list[str] = []
        response_quality_delta = max(
            (_metric(variant, "metrics", "response_quality", "accuracy") or 0.0)
            - (_metric(control, "metrics", "response_quality", "accuracy") or 0.0),
            (_metric(variant, "metrics", "response_quality", "groundedness") or 0.0)
            - (_metric(control, "metrics", "response_quality", "groundedness") or 0.0),
        )
        citation_delta = min(
            (_metric(variant, "metrics", "citation", "citation_precision") or 0.0)
            - (_metric(control, "metrics", "citation", "citation_precision") or 0.0),
            (_metric(variant, "metrics", "citation", "claim_citation_alignment") or 0.0)
            - (_metric(control, "metrics", "citation", "claim_citation_alignment") or 0.0),
        )
        p95 = _metric(variant, "metrics", "latency_ms", "p95") or 0.0
        control_p95 = _metric(control, "metrics", "latency_ms", "p95") or 0.0
        if citation_delta < -REGRESSION_TOLERANCE:
            classifications.append("citation_regression")
        if p95 > control_p95 + max(LATENCY_REGRESSION_MS, control_p95 * LATENCY_REGRESSION_RATIO):
            classifications.append("latency_regression")
        if hard_latency is not None and p95 > hard_latency:
            classifications.append("latency_regression")
        if not classifications and response_quality_delta >= MATERIAL_METRIC_DELTA and citation_delta >= -REGRESSION_TOLERANCE:
            classifications.append("winner")
        if not classifications:
            classifications.append("no_material_change")
        classifications = [item for idx, item in enumerate(classifications) if item not in classifications[:idx]]
        rows.append(
            {
                "name": variant["name"],
                "primary_classification": classifications[0],
                "classifications": classifications,
                "deltas_vs_control": {
                    "response_quality_best": response_quality_delta,
                    "citation_worst": citation_delta,
                    "latency_p95_ms": p95 - control_p95,
                },
            }
        )
    selected = next((row["name"] for row in rows if row["primary_classification"] == "winner"), None)
    return {
        "overall_classification": "winner" if selected else rows[0]["primary_classification"],
        "selected_variant": selected,
        "variants": rows,
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_state() -> dict[str, Any]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip())
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": "unknown", "git_dirty": True}
    return {"git_commit": commit[:12], "git_dirty": dirty}


def _index_fingerprint(index: dict[str, Any]) -> str:
    payload = {
        "build": index.get("build") or {},
        "embedding": index.get("embedding") or {},
        "num_documents": len(index.get("documents") or []),
        "num_chunks": len(index.get("chunks") or []),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def load_latency_budget(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("latency budget must be a JSON object")
    return payload


def build_aggregate(*, config_path: Path, index: dict[str, Any], variants: list[dict[str, Any]], latency_budget: dict[str, Any], cases_requested: int, cases_evaluated: int) -> dict[str, Any]:
    aggregate = {
        "schema_version": 1,
        "profile_type": "private_real100_v2_context_packing",
        "privacy_boundary": "aggregate_only_no_private_payloads_ids_paths_or_filenames",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_scope": {
            "surface": "real100_v2",
            "cases_requested": cases_requested,
            "cases_evaluated": cases_evaluated,
            "subset_run": cases_requested != cases_evaluated,
            "paired_delta_valid": cases_requested == cases_evaluated and cases_evaluated > 0,
        },
        "provenance": {
            **_git_state(),
            "eval_config_sha256": _sha256_file(config_path),
            "index_fingerprint_sha256": _index_fingerprint(index),
            "input_labels": {
                "config": "external_private_real100_v2_config",
                "index": "external_private_real100_v2_index",
                "latency_budget": "reports_real100_v2_latency_cost_budget_aggregate",
            },
        },
        "latency_budget": {
            "present": latency_budget.get("profile_type") == "private_real100_v2_latency_cost_budget",
            "hard_no_go_ceiling_ms": _latency_hard_ceiling_ms(latency_budget),
            "cost_status": _cost_status(latency_budget),
        },
        "decision": classify_variants(variants, latency_budget),
        "variants": variants,
        "known_limits": [
            "This is aggregate-only private-local measurement, not a global response quality improvement claim.",
            "Legacy real100, v1, 221, and kordoc evidence is not used.",
        ],
    }
    assert_aggregate_privacy_safe(aggregate)
    return aggregate


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{float(value):.4f}"
    return str(value)


def render_markdown(aggregate: dict[str, Any]) -> str:
    decision = aggregate["decision"]
    lines = [
        "# real100_v2 Context Packing Experiment",
        "",
        "This report is aggregate-only. It contains no raw case prompts, generated responses, evidence text, filenames, local paths, document identifiers, chunk identifiers, or per-case rows. Legacy `real100`, v1, 221, and kordoc evidence is not used.",
        "",
        "## Decision",
        "",
        f"- Overall classification: `{decision['overall_classification']}`",
        f"- Selected variant: `{decision['selected_variant'] or '-'}`",
        f"- Paired delta valid: `{aggregate['run_scope']['paired_delta_valid']}`",
        f"- Subset run: `{aggregate['run_scope']['subset_run']}`",
        f"- Latency hard ceiling ms: `{_fmt(aggregate['latency_budget']['hard_no_go_ceiling_ms'])}`",
        f"- Cost status: `{aggregate['latency_budget']['cost_status'] or 'not_observable'}`",
        "",
        "## Variants",
        "",
        "| Variant | Accuracy | Groundedness | Citation precision | Claim alignment | Token status | p95 ms | Classification |",
        "|---|---:|---:|---:|---:|---|---:|---|",
    ]
    classifications = {row["name"]: row for row in decision["variants"]}
    for variant in aggregate["variants"]:
        metrics = variant["metrics"]
        row = classifications.get(variant["name"], {"classifications": ["control"]})
        lines.append(
            "| {name} | {acc} | {ground} | {cite} | {align} | {token} | {p95} | {cls} |".format(
                name=variant["name"],
                acc=_fmt(metrics["response_quality"]["accuracy"]),
                ground=_fmt(metrics["response_quality"]["groundedness"]),
                cite=_fmt(metrics["citation"]["citation_precision"]),
                align=_fmt(metrics["citation"]["claim_citation_alignment"]),
                token=metrics["token_cost"]["status"],
                p95=_fmt(metrics["latency_ms"]["p95"]),
                cls=", ".join(row["classifications"]),
            )
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Retrieval behavior, reranker behavior, and answer schema are marked unchanged for every variant.",
            "- Citation regression is a no-go even if answer metrics improve.",
            "- `paired_delta_valid=false` means this artifact is screening evidence only and must not be used as a headline private eval improvement claim.",
            "",
        ]
    )
    rendered = "\n".join(lines)
    assert_rendered_output_privacy_safe(rendered)
    return rendered


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    index_dir = Path(args.index_dir)
    if not index_dir.is_absolute():
        index_dir = ROOT / index_dir
    budget_path = Path(args.latency_budget)
    if not budget_path.is_absolute():
        budget_path = ROOT / budget_path
    out_json = Path(args.out_json)
    if not out_json.is_absolute():
        out_json = ROOT / out_json
    out_md = Path(args.out_md)
    if not out_md.is_absolute():
        out_md = ROOT / out_md
    _require_real100_v2(config_path, label="config")
    _require_real100_v2(index_dir, label="index")
    _require_real100_v2(out_json, label="out-json")
    _require_real100_v2(out_md, label="out-md")

    config = load_config(config_path)
    cases = list(config["cases"])
    cases_requested = len(cases)
    if args.cases_subset_n is not None:
        cases = cases[: args.cases_subset_n]
    index = load_index(index_dir)
    base = _base_run_config(config)
    answer_policy = config.get("answer_policy") if isinstance(config.get("answer_policy"), dict) else {}
    specs = [VariantSpec("control_context_default", "control"), VariantSpec(f"context_{args.variant}", args.variant)]
    variants = []
    for idx, spec in enumerate(specs, start=1):
        print(f"[context] {idx}/{len(specs)} {spec.name}", flush=True)
        variants.append(evaluate_variant(index, cases, base, spec, answer_policy))
    aggregate = build_aggregate(
        config_path=config_path,
        index=index,
        variants=variants,
        latency_budget=load_latency_budget(budget_path),
        cases_requested=cases_requested,
        cases_evaluated=len(cases),
    )
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    out_md.write_text(render_markdown(aggregate), encoding="utf-8")
    message = f"[OK] wrote {render_output_path(out_json)} and {render_output_path(out_md)}"
    assert_rendered_output_privacy_safe(message)
    print(message, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
