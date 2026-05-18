#!/usr/bin/env python3
import argparse
from collections import Counter, defaultdict
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from rag_core import (
    DEFAULT_CLI_PIPELINE_NAME,
    MAX_AGENT_ITERATIONS,
    RRF_K,
    load_index,
    percentile,
    rate,
    redact_trace,
    resolve_pipeline_config,
    run_rag_query,
)
from eval.bootstrap import bootstrap_ci
from eval.scorers import derive_gold_chunk_ids, score_case
from eval.scorers._shared import (
    METADATA_FIELD_KEYS,
    QUERY_TYPE_ALIASES,
    answer_status,
    canonical_query_type,
    hardcase_categories,
    retry_trigger_reasons,
)
from eval.scorers.citation import is_bbox
from scripts._utils import build_provenance


QUERY_TYPES = ("single_doc", "comparison", "follow_up", "abstention")
DEFAULT_ABLATION_RUNS = [
    {
        "name": DEFAULT_CLI_PIPELINE_NAME,
        "pipeline": DEFAULT_CLI_PIPELINE_NAME,
    }
]


def _git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=ROOT_DIR,
            check=False,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def compute_run_manifest(config_path: Path) -> dict[str, Any]:
    """Build the run_manifest block pinned to git commit + config bytes + UTC time.

    Needed for leaderboard time-series (#166) and judge calibration
    reproducibility (#169). Field naming mirrors
    ``scripts._utils.build_provenance`` (``git_commit``, ``git_dirty``,
    ``generated_at``) so the real-eval baseline pipeline and the
    synthetic eval pipeline share one schema.
    """
    commit = _git("rev-parse", "HEAD")[:12] or "unknown"
    dirty = _git("status", "--porcelain") != ""
    try:
        config_sha = hashlib.sha256(config_path.read_bytes()).hexdigest()[:16]
    except (FileNotFoundError, OSError):
        config_sha = "unknown"
    return {
        "git_commit": commit,
        "git_dirty": dirty,
        "config_path": str(config_path),
        "config_sha256": config_sha,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local RAG evaluation over configured cases.")
    parser.add_argument("--input_dir", default="outputs", help="Kept for CLI compatibility; not required.")
    parser.add_argument("--index_dir", default="data/index", help="Directory containing built index.json.")
    parser.add_argument("--output_dir", default="reports", help="Directory to save eval summary.")
    parser.add_argument("--query", default=None, help="Unused in this command; accepted for CLI consistency.")
    parser.add_argument("--config", required=True, help="Path to eval config YAML file.")
    parser.add_argument(
        "--trace_dir",
        default=None,
        help="Directory for local planner/rewrite trace JSON files. Defaults to <output_dir>/traces.",
    )
    parser.add_argument(
        "--redact_trace",
        choices=("doc_ids", "entities", "all"),
        action="append",
        default=None,
        help=(
            "Mask sensitive list fields in written traces. Pass once per category "
            "(doc_ids|entities) or 'all' to mask both. Default: no redaction."
        ),
    )
    return parser.parse_args()


def trace_redact_options(values: list[str] | None) -> dict[str, bool]:
    """Translate CLI --redact_trace selections into redact_trace kwargs."""
    selected = set(values or [])
    if "all" in selected:
        selected.update({"doc_ids", "entities"})
    return {
        "include_doc_ids": "doc_ids" not in selected,
        "include_entities": "entities" not in selected,
    }


def normalize_run_config(run: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(run, dict) or not run.get("name"):
        raise ValueError("Each ablation run must be a mapping with a name")
    config = resolve_pipeline_config(run, default_pipeline=DEFAULT_CLI_PIPELINE_NAME)
    return {
        "name": str(run["name"]),
        "pipeline": config["pipeline"],
        "pipeline_alias": config.get("pipeline_alias"),
        "top_k": config.get("top_k"),
        "metadata_first": bool(config.get("metadata_first")),
        "rerank": bool(config.get("rerank")),
        "rerank_cross_encoder": bool(config.get("rerank_cross_encoder")),
        "verifier_retry": bool(config.get("verifier_retry")),
        "retrieval_mode": str(config.get("retrieval_mode", "flat")),
        "retrieval_backend": str(config.get("retrieval_backend", "dense")),
        "prompt_profile": str(config.get("prompt_profile")),
        "rrf_k": int(config.get("rrf_k", RRF_K)),
        "bm25_stopword_profile": str(config.get("bm25_stopword_profile", "shared")),
        "bm25_tokenizer": str(config.get("bm25_tokenizer", "regex")),
        # Issue #988 / ADR 0057 — bm25_backend metadata for measurement
        # surface. Default `okapi` keeps existing summaries byte-equal.
        "bm25_backend": str(config.get("bm25_backend", "okapi")),
    }


def load_config(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Eval config must be a mapping: {path}")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Eval config must include non-empty cases list")
    for case in cases:
        query_type = canonical_query_type(case.get("query_type"))
        if query_type not in QUERY_TYPES:
            accepted = tuple([*QUERY_TYPES, *QUERY_TYPE_ALIASES])
            raise ValueError(f"Eval case must include query_type in {accepted}: {case.get('id')}")
        case["query_type"] = query_type
        prior_turns = case.get("prior_turns") or []
        if not isinstance(prior_turns, list):
            raise ValueError(f"Eval case prior_turns must be a list: {case.get('id')}")
        for turn in prior_turns:
            if not isinstance(turn, dict) or not str(turn.get("query") or "").strip():
                raise ValueError(f"Each prior turn must include a query: {case.get('id')}")
        categories = case.get("hardcase_categories") or case.get("hardcase_category") or []
        if isinstance(categories, str):
            categories = [categories]
        if not isinstance(categories, list):
            raise ValueError(f"Eval case hardcase_categories must be a list: {case.get('id')}")
        metadata_field_value = case.get("metadata_field")
        if metadata_field_value is not None:
            text = str(metadata_field_value).strip()
            if text and text not in METADATA_FIELD_KEYS:
                raise ValueError(
                    f"Eval case metadata_field must be one of {METADATA_FIELD_KEYS}: "
                    f"{case.get('id')} (got {text!r})"
                )
        citation_pages = case.get("expected_citation_pages") or []
        if not isinstance(citation_pages, list):
            raise ValueError(f"Eval case expected_citation_pages must be a list: {case.get('id')}")
        for expected_page in citation_pages:
            if not isinstance(expected_page, dict) or not str(expected_page.get("doc_id") or "").strip():
                raise ValueError(
                    f"Each expected_citation_pages item must include doc_id: {case.get('id')}"
                )
            pages = expected_page.get("pages") or []
            if (
                not isinstance(pages, list)
                or not pages
                or not all(isinstance(page, int) for page in pages)
            ):
                raise ValueError(
                    f"Each expected_citation_pages item must include non-empty integer pages: {case.get('id')}"
                )
        citation_regions = case.get("expected_citation_regions") or []
        if not isinstance(citation_regions, list):
            raise ValueError(f"Eval case expected_citation_regions must be a list: {case.get('id')}")
        for expected_region in citation_regions:
            if not isinstance(expected_region, dict) or not str(expected_region.get("doc_id") or "").strip():
                raise ValueError(
                    f"Each expected_citation_regions item must include doc_id: {case.get('id')}"
                )
            if not isinstance(expected_region.get("page_number"), int):
                raise ValueError(
                    f"Each expected_citation_regions item must include page_number: {case.get('id')}"
                )
            if not is_bbox(expected_region.get("bbox")):
                raise ValueError(
                    f"Each expected_citation_regions item must include bbox: {case.get('id')}"
                )
            try:
                float(expected_region.get("min_iou", 0.5))
            except (TypeError, ValueError):
                raise ValueError(
                    f"Each expected_citation_regions min_iou must be numeric: {case.get('id')}"
                )
        expected_claim_citations = case.get("expected_claim_citations") or []
        if not isinstance(expected_claim_citations, list):
            raise ValueError(f"Eval case expected_claim_citations must be a list: {case.get('id')}")
        for expected_claim in expected_claim_citations:
            if not isinstance(expected_claim, dict):
                raise ValueError(
                    f"Each expected_claim_citations item must be a mapping: {case.get('id')}"
                )
            if expected_claim.get("target") is not None and not str(expected_claim.get("target")).strip():
                raise ValueError(
                    f"expected_claim_citations target must be non-empty when provided: {case.get('id')}"
                )
            for field in ("expected_terms", "expected_doc_ids"):
                values = expected_claim.get(field) or []
                if not isinstance(values, list):
                    raise ValueError(
                        f"expected_claim_citations {field} must be a list: {case.get('id')}"
                    )

    runs = data.get("ablation_runs", DEFAULT_ABLATION_RUNS)
    if not isinstance(runs, list) or not runs:
        raise ValueError("Eval config ablation_runs must be a non-empty list when provided")
    seen_names: set[str] = set()
    for run in runs:
        normalized_run = normalize_run_config(run)
        if normalized_run["name"] in seen_names:
            raise ValueError(f"Duplicate ablation run name: {normalized_run['name']}")
        seen_names.add(normalized_run["name"])
    return data


_TOP_LEVEL_STAGE_KEYS = ("query_analysis_ms", "context_resolution_ms", "answer_generation_ms")


def _latency_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "mean": rate(values),
        "count": len(values),
    }


def retry_effectiveness_block(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Within-run retry effectiveness metrics (issue #120).

    Reports five signals, all conditional on retry-triggered answerable
    cases (n = cases_with_retry):

    * ``recovery_rate`` — mean accuracy on retry-triggered cases.
    * ``residual_failure_rate`` — mean (1 - accuracy) on the same subset.
    * ``retry_resolution_rate`` — proxy for the verifier's own signal:
      fraction of retry-triggered cases whose final ``filter_stage_attempt``
      was verified. Distinguishes "retry resolved cleanly" from
      "retry exhausted the iteration cap with an unverified result".
    * ``retry_lift_vs_no_retry`` — recovery_rate minus the accuracy on
      non-retried answerable cases in the same run. Honest read of
      "does retry help on hard cases?".

    The true ``retry_precision`` ("would the first attempt have been
    correct without the verifier rejecting it?") requires a cross-run
    comparison against ``no_verifier_retry`` on the same case set —
    computed separately at the main() level. See ADR 0004 / ADR 0001.
    """
    answerable = [r for r in case_results if r.get("accuracy") is not None]
    retried = [r for r in answerable if (r.get("retry_count") or 0) > 0]
    not_retried = [r for r in answerable if (r.get("retry_count") or 0) == 0]

    if not retried:
        return {
            "cases_with_retry": 0,
            "cases_without_retry": len(not_retried),
            "recovery_rate": None,
            "residual_failure_rate": None,
            "retry_resolution_rate": None,
            "retry_lift_vs_no_retry": None,
            "ci": {},
        }

    recovery_scores = [float(r["accuracy"]) for r in retried]
    residual_scores = [1.0 - score for score in recovery_scores]
    recovery_rate = rate(recovery_scores)
    residual_failure_rate = rate(residual_scores)

    resolution_flags = [
        float(bool(r.get("last_attempt_verified")))
        for r in retried
        if r.get("last_attempt_verified") is not None
    ]
    retry_resolution_rate = rate(resolution_flags) if resolution_flags else None

    not_retried_accuracy = [float(r["accuracy"]) for r in not_retried]
    no_retry_baseline = rate(not_retried_accuracy) if not_retried_accuracy else None
    retry_lift = (
        recovery_rate - no_retry_baseline
        if recovery_rate is not None and no_retry_baseline is not None
        else None
    )

    return {
        "cases_with_retry": len(retried),
        "cases_without_retry": len(not_retried),
        "recovery_rate": recovery_rate,
        "residual_failure_rate": residual_failure_rate,
        "retry_resolution_rate": retry_resolution_rate,
        "retry_lift_vs_no_retry": retry_lift,
        "ci": {
            "recovery_rate": bootstrap_ci(recovery_scores),
            "residual_failure_rate": bootstrap_ci(residual_scores),
        },
    }


def cross_ablation_retry_precision(
    full_case_results: list[dict[str, Any]],
    baseline_case_results: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Cross-run retry_precision per issue #120 false-positive trigger spec.

    Compares ``agentic_full`` (verifier-on) to ``no_verifier_retry`` on
    the same case set. A retry trigger is *true-positive* when the
    verifier-off baseline would have produced a wrong answer (= retry
    was warranted), and *false-positive* when the baseline would have
    been correct anyway (= the verifier was over-eager).

    Returns ``None`` if either side is empty or no case has retry_count > 0.
    """
    full_by_id = {c.get("id"): c for c in full_case_results if c.get("id")}
    base_by_id = {c.get("id"): c for c in baseline_case_results if c.get("id")}
    shared_ids = sorted(set(full_by_id) & set(base_by_id))
    triggered = [
        cid
        for cid in shared_ids
        if (full_by_id[cid].get("retry_count") or 0) > 0
        and full_by_id[cid].get("accuracy") is not None
        and base_by_id[cid].get("accuracy") is not None
    ]
    if not triggered:
        return None
    true_positive = sum(
        1 for cid in triggered if float(base_by_id[cid].get("accuracy") or 0.0) < 1.0
    )
    false_positive = sum(
        1 for cid in triggered if float(base_by_id[cid].get("accuracy") or 0.0) >= 1.0
    )
    n = true_positive + false_positive
    return {
        "n_retry_triggered": len(triggered),
        "n_evaluable": n,
        "true_positive_triggers": true_positive,
        "false_positive_triggers": false_positive,
        "retry_precision": (true_positive / n) if n > 0 else None,
        "method": "cross_ablation(agentic_full,no_verifier_retry)",
    }


def _abstention_outcomes(case_results: list[dict[str, Any]]) -> dict[str, int]:
    """Bucket intended-abstention cases into 3 outcome bins.

    Issue #463: the headline ``abstention`` rate is bimodal — correct
    refusals and "wrong answer plus hallucinated evidence" both collapse
    into the same scalar, so a regression that flips a confident
    abstention into a hallucinated answer can land at the same delta as
    a regression that flips one into a partial refusal. The bins:

    * ``correct_refusal`` — model abstained AND returned no evidence.
    * ``incorrect_answer`` — model answered AND attached evidence
      (a hallucination on a topic the corpus does not cover).
    * ``boundary_partial`` — everything else: an abstention with
      stray evidence, or an answer without evidence. These are the
      ambiguous boundary cases worth manual triage.

    Counts only; no per-case payload, no document IDs, no query text.
    """
    correct = incorrect = boundary = 0
    for result in case_results:
        if result.get("answerable") is not False:
            continue
        abstained = bool(result.get("abstained"))
        has_evidence = bool(result.get("evidence_doc_ids"))
        if abstained and not has_evidence:
            correct += 1
        elif not abstained and has_evidence:
            incorrect += 1
        else:
            boundary += 1
    return {
        "correct_refusal": correct,
        "incorrect_answer": incorrect,
        "boundary_partial": boundary,
    }


def _calibration_correctness(result: dict[str, Any]) -> float | None:
    if result.get("answerable") is False:
        if result.get("abstention") is None:
            return None
        return float(result["abstention"] == 1.0)
    if result.get("accuracy") is None:
        return None
    return float(result["accuracy"] == 1.0)


def _abstention_calibration(case_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """ECE (10 fixed-width bins) + Brier score over (confidence, correctness) pairs.

    Returns ``None`` when no case carries a numeric ``confidence`` in
    ``[0, 1]``. ADR 0048 forward-compatibility: existing snapshots
    without confidence emission render the block as ``null`` rather than
    a misleading zeroed dict.
    """
    pairs: list[tuple[float, float]] = []
    for result in case_results:
        conf = result.get("confidence")
        if not isinstance(conf, (int, float)):
            continue
        conf_f = float(conf)
        if not (0.0 <= conf_f <= 1.0):
            continue
        correct = _calibration_correctness(result)
        if correct is None:
            continue
        pairs.append((conf_f, correct))
    if not pairs:
        return None
    num_bins = 10
    bins: list[list[tuple[float, float]]] = [[] for _ in range(num_bins)]
    for conf, correct in pairs:
        idx = min(int(conf * num_bins), num_bins - 1)
        bins[idx].append((conf, correct))
    total = len(pairs)
    ece = 0.0
    for bucket in bins:
        if not bucket:
            continue
        avg_conf = sum(c for c, _ in bucket) / len(bucket)
        avg_acc = sum(corr for _, corr in bucket) / len(bucket)
        ece += (len(bucket) / total) * abs(avg_acc - avg_conf)
    brier = sum((c - corr) ** 2 for c, corr in pairs) / total
    return {
        "ece": ece,
        "brier": brier,
        "n": total,
        "num_bins": num_bins,
    }


def metric_block(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    accuracy_scores = [r["accuracy"] for r in case_results if r["accuracy"] is not None]
    groundedness_scores = [
        r["groundedness"] for r in case_results if r["groundedness"] is not None
    ]
    citation_scores = [
        r["citation_precision"] for r in case_results if r["citation_precision"] is not None
    ]
    citation_page_scores = [
        r["citation_page_precision"]
        for r in case_results
        if r.get("citation_page_precision") is not None
    ]
    citation_region_scores = [
        r["citation_region_precision"]
        for r in case_results
        if r.get("citation_region_precision") is not None
    ]
    citation_grounding_scores = [
        r["citation_grounding"] for r in case_results if r.get("citation_grounding") is not None
    ]
    claim_alignment_scores = [
        r["claim_citation_alignment"]
        for r in case_results
        if r.get("claim_citation_alignment") is not None
    ]
    abstention_scores = [r["abstention"] for r in case_results if r["abstention"] is not None]
    # Issue #463: decompose intended-abstention cases into 3 bins so the
    # bimodal abstention score (0.0 / 1.0) stops collapsing distinct
    # failure modes. Counts only — no per-case text — so the aggregate
    # crosses the ADR 0005 commit boundary intact.
    abstention_outcomes = _abstention_outcomes(case_results)
    abstention_calibration = _abstention_calibration(case_results)
    comparison_recall_scores = [
        r["comparison_target_recall"]
        for r in case_results
        if r.get("comparison_target_recall") is not None
    ]
    comparison_pool_recall_scores = [
        r["comparison_pool_recall"]
        for r in case_results
        if r.get("comparison_pool_recall") is not None
    ]
    format_scores = [
        r["answer_format_compliance"]
        for r in case_results
        if r.get("answer_format_compliance") is not None
    ]
    latencies = [float(r["latency_ms"]) for r in case_results if r["latency_ms"] is not None]
    retry_counts = [int(r.get("retry_count") or 0) for r in case_results]
    retries = [float(count > 0) for count in retry_counts]
    retry_reason_counts = Counter(
        reason for result in case_results for reason in result.get("retry_trigger_reasons") or []
    )
    citation_grounding_error_counts = Counter(
        error["code"]
        for result in case_results
        for error in result.get("citation_grounding_errors") or []
        if isinstance(error, dict) and error.get("code")
    )
    claim_citation_error_counts = Counter(
        error["code"]
        for result in case_results
        for error in result.get("claim_citation_errors") or []
        if isinstance(error, dict) and error.get("code")
    )

    warm_results = [r for r in case_results if not bool(r.get("cold_start"))]
    cold_results = [r for r in case_results if bool(r.get("cold_start"))]

    stage_buckets: dict[str, list[float]] = {key: [] for key in _TOP_LEVEL_STAGE_KEYS}
    retrieve_samples: list[float] = []
    verify_samples: list[float] = []
    for result in warm_results:
        stage_latency = result.get("stage_latency") or {}
        for key in _TOP_LEVEL_STAGE_KEYS:
            value = stage_latency.get(key)
            if value is not None:
                stage_buckets[key].append(float(value))
        for attempt in result.get("attempt_latency") or []:
            retrieve_samples.append(float(attempt.get("retrieve_ms") or 0.0))
            verify_samples.append(float(attempt.get("verify_ms") or 0.0))

    stage_latency_summary: dict[str, dict[str, float | None]] = {
        key: _latency_summary(stage_buckets[key]) for key in _TOP_LEVEL_STAGE_KEYS
    }
    stage_latency_summary["retrieve_ms"] = _latency_summary(retrieve_samples)
    stage_latency_summary["verify_ms"] = _latency_summary(verify_samples)

    latency_by_retry_count: dict[str, dict[str, float | None]] = {}
    grouped_latencies: dict[int, list[float]] = defaultdict(list)
    for result in warm_results:
        if result.get("latency_ms") is None:
            continue
        bucket = int(result.get("retry_count") or 0)
        grouped_latencies[bucket].append(float(result["latency_ms"]))
    for bucket in sorted(grouped_latencies):
        latency_by_retry_count[str(bucket)] = _latency_summary(grouped_latencies[bucket])

    cold_latencies = [
        float(r["latency_ms"]) for r in cold_results if r.get("latency_ms") is not None
    ]
    cold_start_samples = {
        "count": len(cold_results),
        "latency_ms": _latency_summary(cold_latencies) if cold_latencies else None,
    }

    ci_block: dict[str, Any] = {
        "accuracy": bootstrap_ci(accuracy_scores),
        "groundedness": bootstrap_ci(groundedness_scores),
        "citation_precision": bootstrap_ci(citation_scores),
        "citation_page_precision": bootstrap_ci(citation_page_scores),
        "citation_region_precision": bootstrap_ci(citation_region_scores),
        "citation_grounding": bootstrap_ci(citation_grounding_scores),
        "claim_citation_alignment": bootstrap_ci(claim_alignment_scores),
        "abstention": bootstrap_ci(abstention_scores),
        "answer_format_compliance": bootstrap_ci(format_scores),
        "retry": bootstrap_ci(retries),
    }
    block: dict[str, Any] = {
        "num_predictions": len(case_results),
        "accuracy": rate(accuracy_scores),
        "groundedness": rate(groundedness_scores),
        "citation_precision": rate(citation_scores),
        "citation_page_precision": rate(citation_page_scores),
        "citation_region_precision": rate(citation_region_scores),
        "citation_grounding": rate(citation_grounding_scores),
        "claim_citation_alignment": rate(claim_alignment_scores),
        "abstention": rate(abstention_scores),
        "abstention_outcomes": abstention_outcomes,
        "abstention_calibration": abstention_calibration,
        "answer_format_compliance": rate(format_scores),
        "ci": ci_block,
        "latency": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "mean": rate(latencies),
        },
        "stage_latency": stage_latency_summary,
        "latency_by_retry_count": latency_by_retry_count,
        "cold_start_samples": cold_start_samples,
        "retry": rate(retries),
        "retry_cost": {
            "total_retries": sum(retry_counts),
            "mean_retry_count": rate([float(count) for count in retry_counts]),
            "max_retry_count": max(retry_counts) if retry_counts else 0,
            "cases_with_retry": sum(1 for count in retry_counts if count > 0),
        },
        "iterations": {
            "cap": MAX_AGENT_ITERATIONS,
            "mean_used": rate([float(count + 1) for count in retry_counts]),
            "max_used": (max(retry_counts) + 1) if retry_counts else 0,
            "cases_at_cap": sum(
                1 for count in retry_counts if count + 1 >= MAX_AGENT_ITERATIONS
            ),
            "pct_at_cap": rate(
                [float(count + 1 >= MAX_AGENT_ITERATIONS) for count in retry_counts]
            ),
        },
        "retry_reason_counts": dict(sorted(retry_reason_counts.items())),
        "retry_effectiveness": retry_effectiveness_block(case_results),
        "citation_grounding_error_counts": dict(sorted(citation_grounding_error_counts.items())),
        "claim_citation_error_counts": dict(sorted(claim_citation_error_counts.items())),
    }
    if comparison_recall_scores:
        block["comparison_target_recall"] = rate(comparison_recall_scores)
        block["comparison_target_full_coverage_rate"] = rate(
            [1.0 if score >= 1.0 - 1e-9 else 0.0 for score in comparison_recall_scores]
        )
        ci_block["comparison_target_recall"] = bootstrap_ci(comparison_recall_scores)
    if comparison_pool_recall_scores:
        block["comparison_pool_recall"] = rate(comparison_pool_recall_scores)
        block["comparison_pool_full_coverage_rate"] = rate(
            [1.0 if score >= 1.0 - 1e-9 else 0.0 for score in comparison_pool_recall_scores]
        )
        ci_block["comparison_pool_recall"] = bootstrap_ci(comparison_pool_recall_scores)
    return block


def _load_text_source_counts(index_dir: Path | None) -> dict[str, dict[str, int]]:
    """Pass-through read of ``ingestion_report.json`` text_source_counts (issue #769).

    Reads ``<index_dir>/ingestion_report.json`` produced by ``scripts/build_index.py``
    (PR #744, ``INGESTION_REPORT_SCHEMA_VERSION>=3``) and returns the per-format
    text-source histogram.  Returns ``{}`` on any failure — eval must never break
    on a missing or malformed ingestion report, since the report is optional
    (e.g. the ``--input_dir`` ingestion path never writes one).
    """
    if index_dir is None:
        return {}
    report_path = Path(index_dir) / "ingestion_report.json"
    if not report_path.is_file():
        return {}
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"[WARN] Could not read text_source_counts from {report_path}: {exc}",
            file=sys.stderr,
        )
        return {}
    raw = (payload.get("summary") or {}).get("text_source_counts") or {}
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, dict[str, int]] = {}
    for fmt, sources in raw.items():
        if not isinstance(sources, dict):
            continue
        cleaned[str(fmt)] = {
            str(source): int(count)
            for source, count in sources.items()
            if isinstance(count, (int, float))
        }
    return cleaned


def _inject_text_source_rates(
    by_format: dict[str, dict[str, Any]],
    text_source_counts: dict[str, dict[str, int]],
) -> None:
    """Merge per-format text_source data into the ``by_format`` aggregate in-place.

    For every format present in ``by_format``, attach the raw ``text_source_counts``
    sub-dict (for transparency).  For ``hwp`` specifically, derive
    ``kordoc_rate`` and ``hwp_fallback_rate`` as a convenience for operators
    scanning the eval summary at a glance. (Pre-ADR-0049 builds emitted
    ``hwp_native`` from the pyhwp backend; the key was renamed in ADR 0049
    when the backend changed to kordoc — ``hwp_native`` legacy counts are
    folded into the kordoc rate so older snapshots stay readable.)
    """
    for fmt, block in by_format.items():
        sources = text_source_counts.get(fmt)
        if not sources:
            continue
        total = sum(sources.values())
        if total <= 0:
            continue
        block["text_source_counts"] = dict(sources)
        if fmt == "hwp":
            kordoc = int(sources.get("kordoc", 0)) + int(sources.get("hwp_native", 0))
            block["kordoc_rate"] = kordoc / total
            block["hwp_fallback_rate"] = (total - kordoc) / total


def summarize_run(
    name: str,
    run_config: dict[str, Any],
    case_results: list[dict[str, Any]],
    include_cases: bool = False,
    *,
    index_dir: Path | None = None,
) -> dict[str, Any]:
    summary = {
        "name": name,
        "pipeline": str(run_config.get("pipeline") or ""),
        "top_k": run_config.get("top_k"),
        "metadata_first": bool(run_config.get("metadata_first", True)),
        "rerank": bool(run_config.get("rerank", True)),
        "verifier_retry": bool(run_config.get("verifier_retry", True)),
        "retrieval_mode": str(run_config.get("retrieval_mode", "flat")),
        "retrieval_backend": str(run_config.get("retrieval_backend", "dense")),
        "prompt_profile": str(run_config.get("prompt_profile") or ""),
        "rrf_k": int(run_config.get("rrf_k", RRF_K)),
        "bm25_stopword_profile": str(run_config.get("bm25_stopword_profile", "shared")),
        "bm25_tokenizer": str(run_config.get("bm25_tokenizer", "regex")),
        # Issue #988 / ADR 0057 — bm25_backend per-run metadata so
        # `full_bm25s` row's bm25s usage is visible alongside the parity
        # measurements in eval_summary.json.
        "bm25_backend": str(run_config.get("bm25_backend", "okapi")),
        **metric_block(case_results),
        "by_query_type": {},
        "by_slice": {},
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in case_results:
        grouped[canonical_query_type(result["query_type"])].append(result)
    for query_type in QUERY_TYPES:
        if query_type in grouped:
            block = metric_block(grouped[query_type])
            summary["by_query_type"][query_type] = block
            summary["by_slice"][query_type] = block
    hardcase_grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in case_results:
        for category in hardcase_categories(result):
            hardcase_grouped[category].append(result)
    if hardcase_grouped:
        summary["by_hardcase_category"] = {
            category: metric_block(hardcase_grouped[category])
            for category in sorted(hardcase_grouped)
        }
    metadata_field_grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in case_results:
        field = result.get("metadata_field")
        if field:
            metadata_field_grouped[str(field)].append(result)
    if metadata_field_grouped:
        summary["by_metadata_field"] = {
            field: metric_block(metadata_field_grouped[field])
            for field in sorted(metadata_field_grouped)
        }
    format_grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in case_results:
        fmt = result.get("case_source_format")
        if fmt:
            format_grouped[fmt].append(result)
    if format_grouped:
        summary["by_format"] = {
            fmt: metric_block(format_grouped[fmt])
            for fmt in sorted(format_grouped)
        }
        # Issue #769: enrich by_format with the pass-through text_source mix from
        # ingestion_report.json so operators can see "X% of HWP cases parsed via
        # the pyhwp native path" without joining two artifacts by hand.
        text_source_counts = _load_text_source_counts(index_dir)
        if text_source_counts:
            _inject_text_source_rates(summary["by_format"], text_source_counts)
    if include_cases:
        summary["case_results"] = case_results
    return summary


def safe_path_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "unknown"


_TRACE_VERBOSE_ENV = "BIDMATE_TRACE_VERBOSE"
_TRACE_VERBOSE_DIAG_KEYS = (
    "retry_count",
    "verification_topics",
    "verification_reasons",
    "final_relaxation_reason",
    "filter_stage_attempts",
    "answer_status",
)


def _trace_verbose_evidence(evidence: Any, *, text_chars: int = 240) -> list[dict[str, Any]]:
    """Project ``prediction['evidence']`` into a compact form for verbose traces.

    Drops internal-only fields (e.g. ``child_chunk_ids``) and truncates
    ``text`` to ``text_chars`` so trace files stay manageable. Used by
    Phase 1 Step 2.5 verifier-trajectory cataloging; gated by env var so
    default ``make smoke`` dumps stay byte-identical (ADR 0001 safe).
    """
    out: list[dict[str, Any]] = []
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        text = item.get("text") or ""
        out.append(
            {
                "chunk_id": item.get("chunk_id"),
                "doc_id": item.get("doc_id"),
                "score": item.get("score"),
                "agency": item.get("agency"),
                "section": item.get("section"),
                "title": item.get("title"),
                "text_preview": text[:text_chars],
                "text_chars_total": len(text),
            }
        )
    return out


def prediction_trace_payload(
    case: dict[str, Any],
    run_config: dict[str, Any],
    prediction: dict[str, Any],
    *,
    redact_options: dict[str, bool] | None = None,
) -> dict[str, Any]:
    trace = prediction.get("trace") if isinstance(prediction.get("trace"), dict) else {}
    if redact_options and isinstance(trace, dict):
        trace = redact_trace(trace, **redact_options)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "case_id": case.get("id"),
        "run": run_config.get("name"),
        "pipeline": run_config.get("pipeline"),
        "slice": canonical_query_type(case.get("query_type")),
        "query": case.get("query"),
        "answer_status": answer_status(prediction),
        "trace": trace,
    }
    # Env-gated enrichment for Phase 1 Step 2.5 verifier-trajectory dumps.
    # Off by default → existing trace files byte-identical (ADR 0001 invariant
    # preserved; see reports/phase1_step2_5_report.md for rationale).
    if os.environ.get(_TRACE_VERBOSE_ENV) == "1":
        diagnostics = prediction.get("diagnostics") if isinstance(prediction.get("diagnostics"), dict) else {}
        payload["evidence"] = _trace_verbose_evidence(prediction.get("evidence"))
        payload["answer_text"] = prediction.get("answer_text") or ""
        payload["answer"] = prediction.get("answer") if isinstance(prediction.get("answer"), dict) else {}
        payload["diagnostics_subset"] = {
            k: diagnostics.get(k) for k in _TRACE_VERBOSE_DIAG_KEYS if k in diagnostics
        }
    return payload


def write_prediction_trace(
    trace_dir: Path | None,
    case: dict[str, Any],
    run_config: dict[str, Any],
    prediction: dict[str, Any],
    *,
    redact_options: dict[str, bool] | None = None,
) -> str | None:
    if trace_dir is None:
        return None
    run_dir = trace_dir / safe_path_part(str(run_config.get("name") or "run"))
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{safe_path_part(str(case.get('id') or 'case'))}.trace.json"
    path.write_text(
        json.dumps(
            prediction_trace_payload(
                case,
                run_config,
                prediction,
                redact_options=redact_options,
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return str(path)


def _build_doc_format_map(index: dict[str, Any]) -> dict[str, str]:
    """Map doc_id → source_format (fallback: document_type)."""
    result: dict[str, str] = {}
    for doc in index.get("documents") or []:
        doc_id = doc.get("doc_id")
        if not doc_id:
            continue
        metadata = doc.get("metadata") or {}
        fmt = metadata.get("source_format") or metadata.get("document_type") or "unknown"
        result[str(doc_id)] = str(fmt)
    return result


def _case_source_format(
    expected_doc_ids: list[str], doc_format_map: dict[str, str]
) -> str | None:
    """Return the source_format of the first expected doc, or None if unavailable."""
    for doc_id in expected_doc_ids:
        fmt = doc_format_map.get(str(doc_id))
        if fmt:
            return fmt
    return None


def evaluate_run(
    index: dict[str, Any],
    cases: list[dict[str, Any]],
    run_config: dict[str, Any],
    answer_policy: dict[str, Any] | None = None,
    trace_dir: Path | None = None,
    redact_options: dict[str, bool] | None = None,
) -> list[dict[str, Any]]:
    case_results = []
    doc_format_map = _build_doc_format_map(index)
    for case in cases:
        conversation_state: dict[str, Any] = {}
        for turn in case.get("prior_turns") or []:
            prior_prediction = run_rag_query(
                index,
                str(turn["query"]),
                pipeline=str(run_config.get("pipeline") or DEFAULT_CLI_PIPELINE_NAME),
                top_k=run_config.get("top_k"),
                context_entities=turn.get("context_entities") or [],
                metadata_first=bool(run_config.get("metadata_first", True)),
                rerank=bool(run_config.get("rerank", True)),
                verifier_retry=bool(run_config.get("verifier_retry", True)),
                retrieval_mode=str(run_config.get("retrieval_mode", "flat")),
                retrieval_backend=str(run_config.get("retrieval_backend", "dense")),
                prompt_profile=str(run_config.get("prompt_profile") or ""),
                conversation_state=conversation_state,
                rrf_k=int(run_config.get("rrf_k", RRF_K)),
                bm25_stopword_profile=str(run_config.get("bm25_stopword_profile", "shared")),
                bm25_tokenizer=str(run_config.get("bm25_tokenizer", "regex")),
            )
            conversation_state = prior_prediction.get("conversation_state") or conversation_state

        prediction = run_rag_query(
            index,
            str(case["query"]),
            pipeline=str(run_config.get("pipeline") or DEFAULT_CLI_PIPELINE_NAME),
            top_k=run_config.get("top_k"),
            context_entities=case.get("context_entities") or [],
            metadata_first=bool(run_config.get("metadata_first", True)),
            rerank=bool(run_config.get("rerank", True)),
            rerank_cross_encoder=bool(run_config.get("rerank_cross_encoder", False)),
            verifier_retry=bool(run_config.get("verifier_retry", True)),
            retrieval_mode=str(run_config.get("retrieval_mode", "flat")),
            retrieval_backend=str(run_config.get("retrieval_backend", "dense")),
            prompt_profile=str(run_config.get("prompt_profile") or ""),
            conversation_state=conversation_state,
            rrf_k=int(run_config.get("rrf_k", RRF_K)),
            bm25_stopword_profile=str(run_config.get("bm25_stopword_profile", "shared")),
            bm25_tokenizer=str(run_config.get("bm25_tokenizer", "regex")),
        )
        trace_path = write_prediction_trace(
            trace_dir,
            case,
            run_config,
            prediction,
            redact_options=redact_options,
        )
        gold_chunk_ids = derive_gold_chunk_ids(case, index)
        result = score_case(
            case,
            prediction,
            answer_policy,
            gold_chunk_ids=gold_chunk_ids,
        )
        if trace_path:
            result["trace_path"] = trace_path
        synth = (prediction or {}).get("diagnostics", {}).get("synthesis") or {}
        result["tokens_in"] = synth.get("tokens_in")
        result["tokens_out"] = synth.get("tokens_out")
        result["cost_estimate_usd"] = synth.get("cost_estimate_usd")
        result["llm_model"] = synth.get("model")
        result["case_source_format"] = _case_source_format(
            result.get("expected_doc_ids") or [], doc_format_map
        )
        case_results.append(result)
    return case_results


def _torch_version_tuple() -> tuple[int, ...]:
    try:
        import torch

        return tuple(int(x) for x in torch.__version__.split(".")[:2] if x.isdigit())
    except Exception:
        return (0,)


def ablation_runs(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the per-row run-config list, filtering out rows whose
    ``requires_module`` declaration names an unimportable module, or whose
    ``requires_torch_min_version`` exceeds the installed torch.

    Issue #151 — the ``m3_full`` row needs ``FlagEmbedding`` (~2GB
    weights, opt-in via ``pip install -r requirements-m3.txt``). The
    public synthetic CI runs with ``EMBEDDING_BACKEND=hashing`` and
    doesn't install the dep, so the row would otherwise crash the
    smoke target. ``requires_module`` lets the row declare its own
    opt-in gate; missing modules trigger a clear stderr log and the
    row is silently dropped from the ablation set.

    ``requires_torch_min_version`` gates rows that need a specific torch
    version (e.g. ``m3_full`` via FlagEmbedding needs torch >= 2.6 due
    to CVE-2025-32434 — ADR 0019 condition 1). When the installed torch
    is older the row is silently dropped with a stderr log.
    """
    runs = config.get("ablation_runs") or DEFAULT_ABLATION_RUNS
    kept: list[dict[str, Any]] = []
    installed_torch = _torch_version_tuple()
    for run in runs:
        if not isinstance(run, dict):
            kept.append(run)
            continue
        required = run.get("requires_module")
        if required and importlib.util.find_spec(str(required)) is None:
            print(
                f"[skip] ablation row '{run.get('name')}': "
                f"requires_module '{required}' is not importable",
                file=sys.stderr,
            )
            continue
        min_torch = run.get("requires_torch_min_version")
        if min_torch:
            min_tuple = tuple(
                int(x) for x in str(min_torch).split(".")[:2] if x.isdigit()
            )
            if installed_torch < min_tuple:
                print(
                    f"[skip] ablation row '{run.get('name')}': "
                    f"requires torch >= {min_torch} (installed: "
                    f"{'.'.join(str(x) for x in installed_torch)})",
                    file=sys.stderr,
                )
                continue
        kept.append(run)
    return [normalize_run_config(run) for run in kept]


def main() -> int:
    try:
        args = parse_args()
        config_path = Path(args.config)
        if not config_path.exists():
            raise ValueError(f"--config does not exist: {config_path}")
        config = load_config(config_path)
        index = load_index(Path(args.index_dir))
    except Exception as exc:
        print(f"[ERROR] Eval setup failed: {exc}", file=sys.stderr)
        return 2

    run_summaries = []
    primary_summary = None
    primary_run_name = str(config.get("primary_run") or DEFAULT_CLI_PIPELINE_NAME)
    trace_root = Path(args.trace_dir) if args.trace_dir else Path(args.output_dir) / "traces"
    redact_options = trace_redact_options(args.redact_trace)
    all_case_results: dict[str, list[dict[str, Any]]] = {}
    try:
        for run_config in ablation_runs(config):
            case_results = evaluate_run(
                index,
                config["cases"],
                run_config,
                config.get("answer_policy") if isinstance(config.get("answer_policy"), dict) else {},
                trace_dir=trace_root,
                redact_options=redact_options,
            )
            all_case_results[run_config["name"]] = case_results
            is_primary = run_config["name"] == primary_run_name
            run_summary = summarize_run(
                run_config["name"],
                run_config,
                case_results,
                include_cases=is_primary,
                index_dir=Path(args.index_dir),
            )
            run_summaries.append(run_summary)
            if is_primary:
                primary_summary = run_summary
    except Exception as exc:
        print(f"[ERROR] Eval execution failed: {exc}", file=sys.stderr)
        return 2

    if primary_summary is None:
        primary_summary = run_summaries[0]

    retry_effectiveness = dict(primary_summary.get("retry_effectiveness") or {})
    full_cases = all_case_results.get("agentic_full") or all_case_results.get(primary_run_name) or []
    baseline_cases = all_case_results.get("no_verifier_retry") or []
    cross_precision = (
        cross_ablation_retry_precision(full_cases, baseline_cases) if baseline_cases else None
    )
    if cross_precision:
        retry_effectiveness["cross_ablation"] = cross_precision

    summary = {
        "mode": "rag",
        "provenance": build_provenance(),
        "run_manifest": compute_run_manifest(config_path),
        "config": args.config,
        "index_dir": args.index_dir,
        "primary_run": primary_summary["name"],
        "pipeline": primary_summary.get("pipeline"),
        "prompt_profile": primary_summary.get("prompt_profile"),
        "top_k": primary_summary.get("top_k"),
        "num_predictions": primary_summary["num_predictions"],
        "accuracy": primary_summary["accuracy"],
        "groundedness": primary_summary["groundedness"],
        "citation_precision": primary_summary["citation_precision"],
        "citation_page_precision": primary_summary["citation_page_precision"],
        "citation_region_precision": primary_summary["citation_region_precision"],
        "citation_grounding": primary_summary["citation_grounding"],
        "claim_citation_alignment": primary_summary["claim_citation_alignment"],
        "abstention": primary_summary["abstention"],
        "abstention_outcomes": primary_summary.get("abstention_outcomes"),
        "answer_format_compliance": primary_summary["answer_format_compliance"],
        "ci": primary_summary.get("ci", {}),
        "latency": primary_summary["latency"],
        "stage_latency": primary_summary.get("stage_latency", {}),
        "latency_by_retry_count": primary_summary.get("latency_by_retry_count", {}),
        "cold_start_samples": primary_summary.get("cold_start_samples", {}),
        "retry": primary_summary["retry"],
        "by_query_type": primary_summary["by_query_type"],
        "by_slice": primary_summary.get("by_slice", {}),
        "by_hardcase_category": primary_summary.get("by_hardcase_category", {}),
        "by_format": primary_summary.get("by_format", {}),
        "retry_cost": primary_summary["retry_cost"],
        "retry_reason_counts": primary_summary["retry_reason_counts"],
        "retry_effectiveness": retry_effectiveness,
        "citation_grounding_error_counts": primary_summary["citation_grounding_error_counts"],
        "claim_citation_error_counts": primary_summary["claim_citation_error_counts"],
        "trace_dir": str(trace_root),
        "trace_redaction": {
            "include_doc_ids": redact_options["include_doc_ids"],
            "include_entities": redact_options["include_entities"],
        },
        "ablation": {"runs": run_summaries},
        "case_results": primary_summary.get("case_results", []),
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "eval_summary.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Eval summary written: {out_path}")

    if args.query:
        print("[INFO] --query is accepted for interface consistency but unused here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
