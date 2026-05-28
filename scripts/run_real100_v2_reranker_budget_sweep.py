#!/usr/bin/env python3
"""Run an aggregate-only real100_v2 reranker candidate-budget sweep.

This is a private/local measurement harness. It changes no default runtime
behavior: candidate-pool and reranker ``top_n`` variants are injected only from
this script and the committed outputs are aggregate-only.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.run_eval import load_config, normalize_run_config  # noqa: E402
from eval.scorers import derive_gold_evidence, score_case  # noqa: E402
from eval.scorers.chunk_metrics import chunk_mrr_at_k, chunk_ndcg_at_k, chunk_recall_at_k  # noqa: E402
from eval.scorers.failure_classifier import classify_failure  # noqa: E402
from rag_core import DEFAULT_RAG_PIPELINE_NAME, _run_rag_query_with_plan_overrides, load_index, percentile, rate  # noqa: E402
from scripts.run_private_hybrid_sweep import (  # noqa: E402
    assert_aggregate_privacy_safe,
    assert_rendered_output_privacy_safe,
    render_output_path,
)


DEFAULT_CONFIG = ROOT / "data" / "private" / "real100_v2" / "real_config_v2.local.yaml"
DEFAULT_INDEX_DIR = ROOT / "data" / "index" / "real100_v2"
DEFAULT_LATENCY_BUDGET = ROOT / "reports" / "real100_v2" / "latency_cost_budget.aggregate.json"
DEFAULT_OUT_JSON = ROOT / "reports" / "real100_v2" / "reranker_candidate_budget.aggregate.json"
DEFAULT_OUT_MD = ROOT / "docs" / "evaluation" / "real100_v2-reranker-candidate-budget.md"
ALLOWED_CLASSIFICATIONS = {
    "winner",
    "recall_only_gain",
    "ranking_regression",
    "citation_regression",
    "latency_regression",
    "failed_experiment",
}
MATERIAL_RECALL_DELTA = 0.005
RANKING_REGRESSION_TOLERANCE = 0.001
RERANK_PRECISION_DELTA = 0.001
LATENCY_REGRESSION_RATIO = 0.05
LATENCY_REGRESSION_MS = 10.0


@dataclass(frozen=True)
class VariantSpec:
    name: str
    retrieval_backend: str
    top_k: int
    rerank_cross_encoder: bool
    reranker_top_n: int | None
    dense_pool: int | None = None
    bm25_pool: int | None = None
    rrf_k: int = 60

    @property
    def plan_overrides(self) -> dict[str, Any]:
        if self.retrieval_backend != "hybrid" or self.dense_pool is None or self.bm25_pool is None:
            return {}
        return {
            "rrf_channel_pools": {
                "dense": int(self.dense_pool),
                "bm25": int(self.bm25_pool),
            }
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Private real100_v2 eval config.")
    parser.add_argument("--index-dir", default=str(DEFAULT_INDEX_DIR), help="Private real100_v2 index directory.")
    parser.add_argument("--latency-budget", default=str(DEFAULT_LATENCY_BUDGET))
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    parser.add_argument("--cases-subset-n", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--reranker-top-ns", default="10,20,30")
    parser.add_argument("--candidate-pools", default="30")
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--reranker-backend", default=None, help="Override BIDMATE_RERANK_BACKEND.")
    parser.add_argument("--reranker-model", default=None, help="Override BIDMATE_RERANK_MODEL.")
    return parser.parse_args(argv)


def _csv_ints(value: str) -> tuple[int, ...]:
    out = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    if not out or any(item < 1 for item in out):
        raise ValueError("integer lists must contain positive values")
    return out


def _require_real100_v2(path: Path, *, label: str) -> None:
    path_text = path.as_posix()
    if "real100_v2" not in path_text:
        raise ValueError(f"{label} must be under a real100_v2 path")
    lowered = {part.lower() for part in path.parts}
    if "real100" in lowered and "real100_v2" not in lowered:
        raise ValueError(f"{label} must not use legacy real100 paths")


def _base_run_config(config: dict[str, Any], *, top_k: int) -> dict[str, Any]:
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
    base["top_k"] = int(top_k)
    base["rerank"] = True
    base["rerank_cross_encoder"] = False
    return base


def resolve_specs(*, top_k: int, reranker_top_ns: tuple[int, ...], candidate_pools: tuple[int, ...], rrf_k: int) -> list[VariantSpec]:
    specs = [
        VariantSpec(
            name=f"control_no_cross_encoder_top{top_k}",
            retrieval_backend="hybrid",
            top_k=top_k,
            rerank_cross_encoder=False,
            reranker_top_n=None,
            dense_pool=None,
            bm25_pool=None,
            rrf_k=rrf_k,
        )
    ]
    for pool in candidate_pools:
        for top_n in reranker_top_ns:
            specs.append(
                VariantSpec(
                    name=f"reranker_budget_pool{pool}_topn{top_n}_top{top_k}",
                    retrieval_backend="hybrid",
                    top_k=top_k,
                    rerank_cross_encoder=True,
                    reranker_top_n=top_n,
                    dense_pool=pool,
                    bm25_pool=pool,
                    rrf_k=rrf_k,
                )
            )
    return specs


def _config_for_variant(base: dict[str, Any], spec: VariantSpec) -> dict[str, Any]:
    run_config = dict(base)
    run_config["name"] = spec.name
    run_config["top_k"] = spec.top_k
    run_config["retrieval_backend"] = spec.retrieval_backend
    run_config["rerank_cross_encoder"] = spec.rerank_cross_encoder
    run_config["rrf_k"] = spec.rrf_k
    return run_config


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


class _TopNForcingReranker:
    def __init__(self, delegate: Any, forced_top_n: int) -> None:
        self.delegate = delegate
        self.forced_top_n = int(forced_top_n)

    def rerank(self, query: str, candidates: list[dict[str, Any]], *, top_n: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        forced = min(self.forced_top_n, len(candidates))
        pre_topn = [str(item.get("chunk_id") or "") for item in candidates[:forced]]
        reordered, meta = self.delegate.rerank(query, candidates, top_n=forced)
        meta = dict(meta)
        meta["requested_top_n"] = int(top_n)
        meta["forced_top_n"] = forced
        meta["pre_rerank_topn"] = pre_topn
        meta["post_rerank_topn"] = [str(item.get("chunk_id") or "") for item in reordered[:forced]]
        return reordered, meta


@contextmanager
def force_reranker_top_n(top_n: int | None) -> Iterator[None]:
    if top_n is None:
        yield
        return
    import rag_reranker

    original = rag_reranker.default_reranker
    delegate = original()

    def replacement() -> _TopNForcingReranker:
        return _TopNForcingReranker(delegate, int(top_n))

    rag_reranker.default_reranker = replacement
    try:
        yield
    finally:
        rag_reranker.default_reranker = original


def _run_prediction(index: dict[str, Any], query_text: str, run_config: dict[str, Any], plan_overrides: dict[str, Any], *, context_entities: list[str] | None = None, conversation_state: dict[str, Any] | None = None) -> dict[str, Any]:
    return _run_rag_query_with_plan_overrides(
        index,
        query_text,
        plan_overrides=plan_overrides,
        **_query_kwargs(run_config, context_entities=context_entities, conversation_state=conversation_state),
    )


def _mean(values: list[float | None]) -> float | None:
    return rate([float(value) for value in values if value is not None])


def _count_rate(count: int, denominator: int) -> dict[str, Any]:
    return {"count": count, "rate": (count / denominator) if denominator else None, "denominator": denominator}


def _latency_summary(values: list[float]) -> dict[str, Any]:
    return {"p50": percentile(values, 0.50), "p95": percentile(values, 0.95), "count": len(values)}


def _safe_label(value: str | None) -> str | None:
    if not value:
        return value
    return str(value).replace("/", "__").replace("\\", "__")


def _citation_issue_rate(results: list[dict[str, Any]]) -> dict[str, Any]:
    categories = [classify_failure(row) for row in results]
    count = sum(1 for category in categories if category == "citation_or_page_metadata_issue")
    return _count_rate(count, len(results))


def evaluate_variant(index: dict[str, Any], cases: list[dict[str, Any]], run_config: dict[str, Any], spec: VariantSpec, answer_policy: dict[str, Any] | None) -> dict[str, Any]:
    scored_results: list[dict[str, Any]] = []
    pre_topn_recall: list[float | None] = []
    post_topn_recall: list[float | None] = []
    pre_topn_mrr: list[float | None] = []
    post_topn_mrr: list[float | None] = []
    pre_topn_ndcg: list[float | None] = []
    post_topn_ndcg: list[float | None] = []
    fallback_count = 0
    candidates_scored: list[int] = []
    reranker_latencies: list[float] = []
    reranker_backend: str | None = None
    reranker_model: str | None = None

    with force_reranker_top_n(spec.reranker_top_n):
        for case in cases:
            conversation_state: dict[str, Any] = {}
            for turn in case.get("prior_turns") or []:
                prior = _run_prediction(
                    index,
                    str(turn["query"]),
                    run_config,
                    spec.plan_overrides,
                    context_entities=turn.get("context_entities") or [],
                    conversation_state=conversation_state,
                )
                conversation_state = prior.get("conversation_state") or conversation_state
            prediction = _run_prediction(
                index,
                str(case["query"]),
                run_config,
                spec.plan_overrides,
                context_entities=case.get("context_entities") or [],
                conversation_state=conversation_state,
            )
            gold_evidence = derive_gold_evidence(case, index)
            gold_chunk_ids = [
                str(item.get("chunk_id") or "")
                for item in gold_evidence
                if isinstance(item, dict) and item.get("chunk_id")
            ]
            result = score_case(
                case,
                prediction,
                answer_policy,
                gold_chunk_ids=gold_chunk_ids,
                gold_evidence=gold_evidence,
            )
            scored_results.append(result)
            meta = (prediction.get("plan") or {}).get("rerank_cross_encoder_meta") or {}
            if isinstance(meta, dict) and meta:
                reranker_backend = str(meta.get("backend") or reranker_backend or "")
                reranker_model = str(meta.get("model") or reranker_model or "")
                fallback_count += 1 if meta.get("fell_back") else 0
                if isinstance(meta.get("candidates_scored"), int):
                    candidates_scored.append(int(meta["candidates_scored"]))
                if isinstance(meta.get("latency_ms"), (int, float)) and not isinstance(meta.get("latency_ms"), bool):
                    reranker_latencies.append(float(meta["latency_ms"]))
                pre_ids = [str(item) for item in meta.get("pre_rerank_topn") or [] if item]
                post_ids = [str(item) for item in meta.get("post_rerank_topn") or [] if item]
                if gold_chunk_ids and pre_ids and post_ids:
                    k = len(pre_ids)
                    pre_topn_recall.append(chunk_recall_at_k(pre_ids, gold_chunk_ids, k))
                    post_topn_recall.append(chunk_recall_at_k(post_ids, gold_chunk_ids, k))
                    pre_topn_mrr.append(chunk_mrr_at_k(pre_ids, gold_chunk_ids, k))
                    post_topn_mrr.append(chunk_mrr_at_k(post_ids, gold_chunk_ids, k))
                    pre_topn_ndcg.append(chunk_ndcg_at_k(pre_ids, gold_chunk_ids, k))
                    post_topn_ndcg.append(chunk_ndcg_at_k(post_ids, gold_chunk_ids, k))

    latencies = [float(row["latency_ms"]) for row in scored_results if row.get("latency_ms") is not None]
    return {
        "name": spec.name,
        "parameters": {
            "retrieval_backend": spec.retrieval_backend,
            "top_k": spec.top_k,
            "rrf_k": spec.rrf_k,
            "dense_pool": spec.dense_pool,
            "bm25_pool": spec.bm25_pool,
            "rerank_cross_encoder": spec.rerank_cross_encoder,
            "reranker_top_n": spec.reranker_top_n,
        },
        "num_cases": len(scored_results),
        "reranker_provenance": {
            "backend": reranker_backend if spec.rerank_cross_encoder else "disabled",
            "model": _safe_label(reranker_model) if spec.rerank_cross_encoder else "disabled",
            "fallback": _count_rate(fallback_count, len(scored_results)),
            "candidates_scored_mean": _mean([float(value) for value in candidates_scored]),
            "latency_ms": _latency_summary(reranker_latencies) if reranker_latencies else {"p50": None, "p95": None, "count": 0},
        },
        "metrics": {
            "candidate_pool": {
                "pre_rerank_recall_at_topn": _mean(pre_topn_recall),
                "post_rerank_recall_at_topn": _mean(post_topn_recall),
                "pre_rerank_mrr_at_topn": _mean(pre_topn_mrr),
                "post_rerank_mrr_at_topn": _mean(post_topn_mrr),
                "pre_rerank_ndcg_at_topn": _mean(pre_topn_ndcg),
                "post_rerank_ndcg_at_topn": _mean(post_topn_ndcg),
            },
            "reranker_precision": {
                "rerank_delta_mrr": _mean([row.get("rerank_delta_mrr") for row in scored_results]),
                "rerank_delta_ndcg_at_10": _mean([row.get("rerank_delta_ndcg_at_10") for row in scored_results]),
            },
            "final_retrieval": {
                "recall_at_5": _mean([row.get("chunk_recall_at_5") for row in scored_results]),
                "recall_at_10": _mean([row.get("chunk_recall_at_10") for row in scored_results]),
                "mrr_at_5": _mean([row.get("chunk_mrr_at_5") for row in scored_results]),
                "ndcg_at_5": _mean([row.get("chunk_ndcg_at_5") for row in scored_results]),
            },
            "citation_guardrail": {
                "citation_or_page_metadata_issue": _citation_issue_rate(scored_results),
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


def _latency_hard_ceiling_ms(latency_budget: dict[str, Any] | None) -> float | None:
    if not isinstance(latency_budget, dict):
        return None
    baseline = latency_budget.get("baseline_latency")
    if isinstance(baseline, dict):
        value = _number(baseline.get("hard_ceiling_ms"))
        if value is not None:
            return value
    overall = latency_budget.get("overall_budget")
    if not isinstance(overall, dict):
        return None
    return _number(overall.get("hard_no_go_ceiling_ms"))


def _cost_status(latency_budget: dict[str, Any] | None) -> str | None:
    if not isinstance(latency_budget, dict):
        return None
    envelope = latency_budget.get("cost_envelope")
    if isinstance(envelope, dict) and envelope.get("status"):
        return str(envelope["status"])
    budget = latency_budget.get("cost_budget")
    if isinstance(budget, dict) and budget.get("status"):
        return str(budget["status"])
    return None


def classify_variants(variants: list[dict[str, Any]], latency_budget: dict[str, Any] | None) -> dict[str, Any]:
    if not variants:
        return {"overall_classification": "failed_experiment", "selected_variant": None, "variants": []}
    baseline = variants[0]
    hard_latency = _latency_hard_ceiling_ms(latency_budget)
    classified: list[dict[str, Any]] = []
    for variant in variants[1:]:
        missing = []
        for label, value in [
            ("recall_at_5", _metric(variant, "metrics", "final_retrieval", "recall_at_5")),
            ("recall_at_10", _metric(variant, "metrics", "final_retrieval", "recall_at_10")),
            ("mrr_at_5", _metric(variant, "metrics", "final_retrieval", "mrr_at_5")),
            ("ndcg_at_5", _metric(variant, "metrics", "final_retrieval", "ndcg_at_5")),
            ("latency_p95_ms", _metric(variant, "metrics", "latency_ms", "p95")),
            ("baseline_recall_at_10", _metric(baseline, "metrics", "final_retrieval", "recall_at_10")),
            ("baseline_mrr_at_5", _metric(baseline, "metrics", "final_retrieval", "mrr_at_5")),
            ("baseline_ndcg_at_5", _metric(baseline, "metrics", "final_retrieval", "ndcg_at_5")),
        ]:
            if value is None:
                missing.append(label)
        classifications: list[str] = []
        if missing:
            classifications = ["failed_experiment"]
        else:
            recall_delta = max(
                (_metric(variant, "metrics", "final_retrieval", "recall_at_5") or 0.0)
                - (_metric(baseline, "metrics", "final_retrieval", "recall_at_5") or 0.0),
                (_metric(variant, "metrics", "final_retrieval", "recall_at_10") or 0.0)
                - (_metric(baseline, "metrics", "final_retrieval", "recall_at_10") or 0.0),
            )
            mrr_delta = (_metric(variant, "metrics", "final_retrieval", "mrr_at_5") or 0.0) - (
                _metric(baseline, "metrics", "final_retrieval", "mrr_at_5") or 0.0
            )
            ndcg_delta = (_metric(variant, "metrics", "final_retrieval", "ndcg_at_5") or 0.0) - (
                _metric(baseline, "metrics", "final_retrieval", "ndcg_at_5") or 0.0
            )
            rerank_delta = max(
                _metric(variant, "metrics", "reranker_precision", "rerank_delta_mrr") or 0.0,
                _metric(variant, "metrics", "reranker_precision", "rerank_delta_ndcg_at_10") or 0.0,
            )
            citation_delta = (
                _metric(variant, "metrics", "citation_guardrail", "citation_or_page_metadata_issue", "rate")
                or 0.0
            ) - (
                _metric(baseline, "metrics", "citation_guardrail", "citation_or_page_metadata_issue", "rate")
                or 0.0
            )
            p95 = _metric(variant, "metrics", "latency_ms", "p95") or 0.0
            baseline_p95 = _metric(baseline, "metrics", "latency_ms", "p95") or 0.0
            latency_regressed = p95 > baseline_p95 + max(LATENCY_REGRESSION_MS, baseline_p95 * LATENCY_REGRESSION_RATIO)
            if hard_latency is not None and p95 > hard_latency:
                latency_regressed = True
            fallback_rate = _metric(variant, "reranker_provenance", "fallback", "rate") or 0.0
            if fallback_rate > 0:
                classifications.append("failed_experiment")
            if mrr_delta < -RANKING_REGRESSION_TOLERANCE or ndcg_delta < -RANKING_REGRESSION_TOLERANCE:
                classifications.append("ranking_regression")
            if citation_delta > RANKING_REGRESSION_TOLERANCE:
                classifications.append("citation_regression")
            if latency_regressed:
                classifications.append("latency_regression")
            if not classifications and (recall_delta >= MATERIAL_RECALL_DELTA or rerank_delta >= RERANK_PRECISION_DELTA):
                classifications.append("winner")
            elif recall_delta >= MATERIAL_RECALL_DELTA and classifications:
                classifications.insert(0, "recall_only_gain")
            if not classifications:
                classifications.append("failed_experiment")
        deduped = [item for idx, item in enumerate(classifications) if item in ALLOWED_CLASSIFICATIONS and item not in classifications[:idx]]
        if not deduped:
            deduped = ["failed_experiment"]
        row = {
            "name": str(variant.get("name") or ""),
            "classifications": deduped,
            "primary_classification": deduped[0],
            "missing_metrics": missing,
            "deltas_vs_control": {
                "recall_at_5": (_metric(variant, "metrics", "final_retrieval", "recall_at_5") or 0.0)
                - (_metric(baseline, "metrics", "final_retrieval", "recall_at_5") or 0.0),
                "recall_at_10": (_metric(variant, "metrics", "final_retrieval", "recall_at_10") or 0.0)
                - (_metric(baseline, "metrics", "final_retrieval", "recall_at_10") or 0.0),
                "mrr_at_5": (_metric(variant, "metrics", "final_retrieval", "mrr_at_5") or 0.0)
                - (_metric(baseline, "metrics", "final_retrieval", "mrr_at_5") or 0.0),
                "ndcg_at_5": (_metric(variant, "metrics", "final_retrieval", "ndcg_at_5") or 0.0)
                - (_metric(baseline, "metrics", "final_retrieval", "ndcg_at_5") or 0.0),
                "latency_p95_ms": (_metric(variant, "metrics", "latency_ms", "p95") or 0.0)
                - (_metric(baseline, "metrics", "latency_ms", "p95") or 0.0),
            },
        }
        classified.append(row)
    winners = [row for row in classified if row["primary_classification"] == "winner"]
    selected = winners[0]["name"] if winners else None
    overall = "winner" if selected else (classified[0]["primary_classification"] if classified else "failed_experiment")
    return {"overall_classification": overall, "selected_variant": selected, "variants": classified}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_state() -> dict[str, Any]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip())
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": "unknown", "git_dirty": True}
    return {"git_commit": commit[:12], "git_dirty": dirty}


def load_latency_budget(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("latency budget must be a JSON object")
    return payload


def build_aggregate(*, config_path: Path, index: dict[str, Any], specs: list[VariantSpec], variants: list[dict[str, Any]], latency_budget: dict[str, Any], cases_requested: int, cases_evaluated: int) -> dict[str, Any]:
    decision = classify_variants(variants, latency_budget)
    aggregate = {
        "schema_version": 1,
        "profile_type": "private_real100_v2_reranker_candidate_budget",
        "privacy_boundary": "aggregate_only_no_raw_questions_answers_evidence_ids_paths_or_filenames",
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
        "sweep": {
            "control": specs[0].name if specs else "control_no_cross_encoder",
            "candidate_count": max(0, len(specs) - 1),
            "reranker_top_n_values": sorted({spec.reranker_top_n for spec in specs if spec.reranker_top_n is not None}),
            "candidate_pool_values": sorted({spec.dense_pool for spec in specs if spec.dense_pool is not None}),
            "classification_policy": sorted(ALLOWED_CLASSIFICATIONS),
        },
        "latency_budget": {
            "present": latency_budget.get("profile_type") == "private_real100_v2_latency_cost_budget",
            "hard_no_go_ceiling_ms": _latency_hard_ceiling_ms(latency_budget),
            "cost_status": _cost_status(latency_budget),
        },
        "decision": decision,
        "variants": variants,
        "known_limits": [
            "This is aggregate-only private-local measurement, not a global reranker improvement claim.",
            "Legacy real100, v1, 221, and kordoc evidence is not used.",
            "BGE or other local reranker model availability is environment-dependent.",
        ],
    }
    assert_aggregate_privacy_safe(aggregate)
    return aggregate


def _index_fingerprint(index: dict[str, Any]) -> str:
    payload = {
        "build": index.get("build") or {},
        "embedding": index.get("embedding") or {},
        "num_documents": len(index.get("documents") or []),
        "num_chunks": len(index.get("chunks") or []),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{float(value):.4f}"
    return str(value)


def render_markdown(aggregate: dict[str, Any]) -> str:
    decision = aggregate["decision"]
    lines = [
        "# real100_v2 Reranker Candidate-Budget Sweep",
        "",
        "This report is aggregate-only. It contains no raw questions, answers, evidence text, filenames, local paths, document identifiers, chunk identifiers, or per-case rows. Legacy `real100`, v1, 221, and kordoc evidence is not used.",
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
        "## Control",
        "",
        "| Variant | Recall@5 | Recall@10 | MRR@5 | nDCG@5 | p50 ms | p95 ms |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    control = aggregate["variants"][0]
    control_metrics = control["metrics"]
    lines.append(
        "| {name} | {r5} | {r10} | {mrr} | {ndcg} | {p50} | {p95} |".format(
            name=control["name"],
            r5=_fmt(control_metrics["final_retrieval"]["recall_at_5"]),
            r10=_fmt(control_metrics["final_retrieval"]["recall_at_10"]),
            mrr=_fmt(control_metrics["final_retrieval"]["mrr_at_5"]),
            ndcg=_fmt(control_metrics["final_retrieval"]["ndcg_at_5"]),
            p50=_fmt(control_metrics["latency_ms"]["p50"]),
            p95=_fmt(control_metrics["latency_ms"]["p95"]),
        )
    )
    lines.extend(
        [
            "",
            "## Candidate Variants",
            "",
            "| Variant | Pool | top_n | preR@N | postR@N | dMRR | dNDCG@10 | fallback | p95 ms | Classification |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    classification_by_name = {row["name"]: row for row in decision["variants"]}
    for variant in aggregate["variants"][1:]:
        params = variant["parameters"]
        metrics = variant["metrics"]
        provenance = variant["reranker_provenance"]
        row = classification_by_name.get(variant["name"], {})
        lines.append(
            "| {name} | {pool} | {topn} | {pre_r} | {post_r} | {dmrr} | {dndcg} | {fallback} | {p95} | {cls} |".format(
                name=variant["name"],
                pool=_fmt(params.get("dense_pool")),
                topn=_fmt(params.get("reranker_top_n")),
                pre_r=_fmt(metrics["candidate_pool"]["pre_rerank_recall_at_topn"]),
                post_r=_fmt(metrics["candidate_pool"]["post_rerank_recall_at_topn"]),
                dmrr=_fmt(metrics["reranker_precision"]["rerank_delta_mrr"]),
                dndcg=_fmt(metrics["reranker_precision"]["rerank_delta_ndcg_at_10"]),
                fallback=_fmt((provenance.get("fallback") or {}).get("rate")),
                p95=_fmt(metrics["latency_ms"]["p95"]),
                cls=", ".join(row.get("classifications") or ["failed_experiment"]),
            )
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Candidate-pool recall is measured before cross-encoder reranking; reranker precision is measured as MRR/nDCG movement after reranking.",
            "- `winner` requires material retrieval or reranker-precision gain with no ranking, citation, latency, or fallback regression.",
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

    if args.reranker_backend:
        os.environ["BIDMATE_RERANK_BACKEND"] = str(args.reranker_backend)
    if args.reranker_model:
        os.environ["BIDMATE_RERANK_MODEL"] = str(args.reranker_model)

    config = load_config(config_path)
    cases = list(config["cases"])
    cases_requested = len(cases)
    if args.cases_subset_n is not None:
        cases = cases[: args.cases_subset_n]
    index = load_index(index_dir)
    specs = resolve_specs(
        top_k=int(args.top_k),
        reranker_top_ns=_csv_ints(args.reranker_top_ns),
        candidate_pools=_csv_ints(args.candidate_pools),
        rrf_k=int(args.rrf_k),
    )
    base = _base_run_config(config, top_k=int(args.top_k))
    answer_policy = config.get("answer_policy") if isinstance(config.get("answer_policy"), dict) else {}
    variants = []
    for idx, spec in enumerate(specs, start=1):
        print(f"[sweep] {idx}/{len(specs)} {spec.name}", flush=True)
        run_config = _config_for_variant(base, spec)
        variants.append(evaluate_variant(index, cases, run_config, spec, answer_policy))
    aggregate = build_aggregate(
        config_path=config_path,
        index=index,
        specs=specs,
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
