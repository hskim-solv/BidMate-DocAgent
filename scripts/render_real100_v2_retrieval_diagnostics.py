#!/usr/bin/env python3
"""Render aggregate-only real100_v2 retrieval diagnostics.

This script reads the ignored local ``real100_v2`` eval summary and writes
commit-safe aggregate JSON/Markdown. It does not import or change retrieval,
reranking, verifier, answer, ingestion, chunking, or eval scoring behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
K_VALUES: tuple[int, ...] = (5, 10, 20)
SAFE_QUERY_TYPES: tuple[str, ...] = ("single_doc", "comparison", "abstention", "unknown")
SAFE_FAILURE_CATEGORIES: tuple[str, ...] = (
    "retrieval_miss",
    "citation_or_page_metadata_issue",
    "verifier_false_negative",
    "verifier_false_positive",
    "answer_synthesis_issue",
    "abstention_failure",
    "evaluation_label_issue",
    "parse_or_metadata_issue",
    "unknown",
    "none",
)
EXCLUSIVE_STATUS: tuple[str, ...] = (
    "unanswerable_no_gold",
    "no_gold_evidence",
    "all_gold_top5",
    "all_gold_top10_not_top5",
    "all_gold_observed_after_top10",
    "partial_candidate_pool",
    "not_in_candidate_pool",
    "not_observable_limited_depth",
)


def _default_summary() -> Path:
    root = Path(os.environ.get("REAL_EVAL_ROOT") or ROOT)
    return root / "reports" / "real100_v2" / "eval_summary.json"


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


def _source_provenance(path: Path) -> dict[str, Any]:
    resolved_root = ROOT.resolve()
    resolved_path = path.resolve()
    try:
        location = str(resolved_path.relative_to(resolved_root))
        redacted = False
    except ValueError:
        location = "external_private/real100_v2_eval_summary"
        redacted = True
    return {
        "input_artifact": location,
        "input_location_redacted": redacted,
        "input_sha256_12": hashlib.sha256(path.read_bytes()).hexdigest()[:12],
    }


def _case_results(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = summary.get("case_results")
    if not isinstance(raw, list):
        raise ValueError("real100_v2 eval_summary.json must include case_results")
    return [case for case in raw if isinstance(case, dict)]


def _safe_query_type(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in SAFE_QUERY_TYPES else "unknown"


def _safe_failure_category(value: Any) -> str:
    if value is None or value == "":
        return "none"
    text = str(value)
    return text if text in SAFE_FAILURE_CATEGORIES else "unknown"


def _bool(value: Any) -> bool:
    return bool(value) if isinstance(value, bool) else False


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _mean(values: Iterable[float]) -> float | None:
    clean = list(values)
    if not clean:
        return None
    return round(sum(clean) / len(clean), 6)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _gold_chunk_ids(case: Mapping[str, Any]) -> list[str]:
    explicit = [str(item) for item in case.get("gold_chunk_ids") or [] if item]
    evidence_ids = [
        str(item.get("chunk_id") or "")
        for item in case.get("gold_evidence") or []
        if isinstance(item, Mapping) and item.get("chunk_id")
    ]
    return _unique([*explicit, *evidence_ids])


def _gold_doc_split(case: Mapping[str, Any], gold_ids: list[str]) -> str:
    gold_set = set(gold_ids)
    docs: set[str] = set()
    for item in case.get("gold_evidence") or []:
        if not isinstance(item, Mapping):
            continue
        chunk_id = str(item.get("chunk_id") or "")
        doc_id = str(item.get("doc_id") or "")
        if chunk_id in gold_set and doc_id:
            docs.add(doc_id)
    if len(docs) == 1:
        return "same_doc"
    if len(docs) > 1:
        return "multi_doc"
    return "unknown"


def _retrieved_rows(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = case.get("retrieved_chunks")
    if isinstance(rows, list):
        clean: list[tuple[int, int, dict[str, Any]]] = []
        for ordinal, item in enumerate(rows):
            if not isinstance(item, dict):
                continue
            chunk_id = str(item.get("chunk_id") or "")
            if not chunk_id:
                continue
            try:
                rank = int(item.get("rank") or ordinal + 1)
            except (TypeError, ValueError):
                rank = ordinal + 1
            clean.append((rank, ordinal, item))
        return [item for _, _, item in sorted(clean)]

    ids = case.get("retrieved_chunk_ids")
    if isinstance(ids, list):
        return [
            {"rank": rank, "chunk_id": str(chunk_id)}
            for rank, chunk_id in enumerate(ids, start=1)
            if chunk_id
        ]
    return []


def _retrieved_chunk_ids(case: Mapping[str, Any]) -> list[str]:
    return _unique(str(item.get("chunk_id") or "") for item in _retrieved_rows(case))


def _doc_ids(rows: list[dict[str, Any]], k: int) -> list[str]:
    return [str(item.get("doc_id") or "") for item in rows[:k] if item.get("doc_id")]


def _topk_hit(gold: set[str], retrieved: list[str], k: int) -> bool:
    return bool(gold & set(retrieved[:k]))


def _topk_all(gold: set[str], retrieved: list[str], k: int) -> bool:
    return bool(gold) and gold.issubset(set(retrieved[:k]))


def _exclusive_status(case: Mapping[str, Any], gold: list[str], retrieved: list[str]) -> str:
    if case.get("answerable") is False:
        return "unanswerable_no_gold"
    if not gold:
        return "no_gold_evidence"

    gold_set = set(gold)
    observed = set(retrieved)
    if _topk_all(gold_set, retrieved, 5):
        return "all_gold_top5"
    if _topk_all(gold_set, retrieved, 10):
        return "all_gold_top10_not_top5"
    if gold_set.issubset(observed):
        return "all_gold_observed_after_top10"
    if gold_set & observed:
        return "partial_candidate_pool"
    if len(retrieved) >= 10:
        return "not_in_candidate_pool"
    return "not_observable_limited_depth"


def _empty_slice() -> dict[str, Any]:
    return {
        "cases": 0,
        "answerable": 0,
        "chunk_recall_at_5": None,
        "chunk_recall_at_10": None,
        "chunk_recall_at_20": None,
        "hit_at_5": 0.0,
        "hit_at_10": 0.0,
        "mrr_at_5": None,
        "ndcg_at_5": None,
        "ndcg_at_10": None,
        "dominant_exclusive_status": "none",
    }


def _metric_block(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    answerable = [
        case
        for case in cases
        if case.get("answerable") is True and _gold_chunk_ids(case)
    ]
    hits = {str(k): 0 for k in K_VALUES}
    all_hits = {str(k): 0 for k in K_VALUES}
    for case in answerable:
        gold = set(_gold_chunk_ids(case))
        retrieved = _retrieved_chunk_ids(case)
        for k in K_VALUES:
            if _topk_hit(gold, retrieved, k):
                hits[str(k)] += 1
            if _topk_all(gold, retrieved, k):
                all_hits[str(k)] += 1

    return {
        "coverage_cases": len(answerable),
        "chunk_recall_at_5": _mean(
            value
            for case in answerable
            if (value := _number(case.get("chunk_recall_at_5"))) is not None
        ),
        "chunk_recall_at_10": _mean(
            value
            for case in answerable
            if (value := _number(case.get("chunk_recall_at_10"))) is not None
        ),
        "chunk_recall_at_20": _mean(
            value
            for case in answerable
            if (value := _number(case.get("chunk_recall_at_20"))) is not None
        ),
        "hit_at_k": {k: _rate(v, len(answerable)) for k, v in hits.items()},
        "all_gold_at_k": {k: _rate(v, len(answerable)) for k, v in all_hits.items()},
        "mrr_at_5": _mean(
            value
            for case in answerable
            if (value := _number(case.get("chunk_mrr_at_5"))) is not None
        ),
        "mrr": _mean(
            value
            for case in answerable
            if (value := _number(case.get("chunk_mrr"))) is not None
        ),
        "ndcg_at_5": _mean(
            value
            for case in answerable
            if (value := _number(case.get("chunk_ndcg_at_5"))) is not None
        ),
        "ndcg_at_10": _mean(
            value
            for case in answerable
            if (value := _number(case.get("chunk_ndcg_at_10"))) is not None
        ),
        "context_precision_at_5": _mean(
            value
            for case in answerable
            if (value := _number(case.get("context_precision_at_5"))) is not None
        ),
        "context_recall_at_5": _mean(
            value
            for case in answerable
            if (value := _number(case.get("context_recall_at_5"))) is not None
        ),
    }


def _dominant(counter: Mapping[str, int]) -> str:
    if not counter:
        return "none"
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0][0]


CANDIDATE_POOL_COLLAPSE_ALL_GOLD_RATE = 0.05
# Upper bound on any-gold observation: above ~20%, gold is frequently in the
# candidate pool (a ranked-too-low / reranker situation -> T-2026-0032), so this
# guard keeps the collapse signal from firing on a merely low-ranking run.
CANDIDATE_POOL_COLLAPSE_ANY_GOLD_RATE = 0.20
CANDIDATE_POOL_COLLAPSE_MIN_CASES = 20


def _recommend_next_task(
    *,
    page_span_coverage: float | None,
    failure_buckets: Mapping[str, int],
    all_gold_observed_rate: float,
    any_gold_observed_rate: float,
    coverage_cases: int,
) -> dict[str, Any]:
    if page_span_coverage == 0.0:
        page_blocker = "claim_bearing_page_or_window_work_blocked"
    else:
        page_blocker = "page_metadata_available"

    # Candidate-pool-collapse gate (checked first). A reranker (T-2026-0032) only
    # helps when gold IS in the candidate pool but ranked too low; when gold is
    # observed in fewer than ~5% of answerable cases the pool itself collapsed, so
    # reranking is meaningless and the actionable next step is embedding/index
    # integrity verification (T-2026-0076). The coverage_cases >= 20 guard keeps
    # tiny synthetic fixtures (e.g. the existing 5-case test) on the legacy path so
    # they never trip the production-scale collapse signal. Note: we deliberately do
    # NOT gate on not_in_candidate_pool >= ranked_too_low_after_top5 — on the real
    # page-aware run retrieval returns < 10 candidates per case, so those misses are
    # classified as not_observable_limited_depth (not not_in_candidate_pool), leaving
    # not_in_candidate_pool == 0 while ranked_too_low_after_top5 == 1; that clause
    # would suppress the collapse signal exactly when it matters most.
    if (
        coverage_cases >= CANDIDATE_POOL_COLLAPSE_MIN_CASES
        and all_gold_observed_rate <= CANDIDATE_POOL_COLLAPSE_ALL_GOLD_RATE
        and any_gold_observed_rate <= CANDIDATE_POOL_COLLAPSE_ANY_GOLD_RATE
    ):
        return {
            "preferred_next_task": "T-2026-0076",
            "reason": "candidate_pool_collapse_gold_rarely_observed_retrieval_integrity_suspect",
            "blocked_task": None,
            "blocker": page_blocker,
            "signal": "retrieval_integrity_suspect",
        }

    if failure_buckets.get("ranked_too_low_after_top5", 0) >= failure_buckets.get(
        "not_in_candidate_pool", 0
    ):
        preferred = "T-2026-0032"
        reason = "ranked_too_low_signal_points_to_candidate_budget_or_reranker_measurement"
    else:
        preferred = "T-2026-0031"
        reason = "not_in_candidate_pool_signal_points_to_parent_or_section_window_experiment"

    if page_span_coverage == 0.0 and preferred == "T-2026-0031":
        return {
            "preferred_next_task": "T-2026-0032",
            "reason": "T-2026-0031 depends on page/window evidence; v2 page metadata is still absent",
            "blocked_task": "T-2026-0031",
            "blocker": page_blocker,
            "signal": "candidate_budget_or_window",
        }
    return {
        "preferred_next_task": preferred,
        "reason": reason,
        "blocked_task": "T-2026-0031" if page_span_coverage == 0.0 else None,
        "blocker": page_blocker,
        "signal": "candidate_budget_or_window",
    }


def build_diagnostics(summary: Mapping[str, Any], *, source: Mapping[str, Any] | None = None) -> dict[str, Any]:
    cases = _case_results(summary)
    exclusive = Counter({key: 0 for key in EXCLUSIVE_STATUS})
    query_types = Counter({key: 0 for key in SAFE_QUERY_TYPES})
    failure_categories = Counter({key: 0 for key in SAFE_FAILURE_CATEGORIES})
    evidence_split = Counter({"single_chunk": 0, "multi_chunk": 0, "no_gold": 0})
    multi_doc_split = Counter({"same_doc": 0, "multi_doc": 0, "unknown": 0})
    failure_buckets = Counter(
        {
            "not_in_candidate_pool": 0,
            "ranked_too_low_after_top5": 0,
            "boundary_or_window_candidate": 0,
            "duplicate_or_near_duplicate_candidate": 0,
            "metadata_filter_candidate": 0,
            "multi_evidence_failure": 0,
            "verifier_false_negative": 0,
            "verifier_false_positive": 0,
            "evaluation_label_gap": 0,
            "answer_generation_or_abstention": 0,
            "page_metadata_blocked": 0,
        }
    )
    candidate_pool = {
        "any_gold_observed": 0,
        "all_gold_observed": 0,
        "no_gold_observed": 0,
        "partial_gold_observed": 0,
        "retrieval_depth_lt_10": 0,
    }
    duplicate_counts = {
        "duplicate_chunk_id_cases": 0,
        "repeated_doc_top5_cases": 0,
        "repeated_doc_top10_cases": 0,
    }
    metadata_filter = {
        "metadata_candidate_cases": 0,
        "metadata_candidate_doc_miss_cases": 0,
        "metadata_ambiguous_cases": 0,
        "reduced_or_relaxed_filter_stage_cases": 0,
    }
    slice_cases: dict[str, list[Mapping[str, Any]]] = {key: [] for key in SAFE_QUERY_TYPES}

    for case in cases:
        query_type = _safe_query_type(case.get("query_type") or case.get("slice"))
        query_types[query_type] += 1
        slice_cases[query_type].append(case)
        failure_category = _safe_failure_category(case.get("failure_category"))
        failure_categories[failure_category] += 1

        gold = _gold_chunk_ids(case)
        gold_set = set(gold)
        rows = _retrieved_rows(case)
        retrieved = _retrieved_chunk_ids(case)
        observed = gold_set & set(retrieved)
        status = _exclusive_status(case, gold, retrieved)
        exclusive[status] += 1

        if len(gold) == 0:
            evidence_split["no_gold"] += 1
        elif len(gold) == 1:
            evidence_split["single_chunk"] += 1
        else:
            evidence_split["multi_chunk"] += 1
            multi_doc_split[_gold_doc_split(case, gold)] += 1

        if case.get("answerable") is True and gold:
            if observed:
                candidate_pool["any_gold_observed"] += 1
            else:
                candidate_pool["no_gold_observed"] += 1
            if gold_set and gold_set.issubset(set(retrieved)):
                candidate_pool["all_gold_observed"] += 1
            elif observed:
                candidate_pool["partial_gold_observed"] += 1
            if len(retrieved) < 10:
                candidate_pool["retrieval_depth_lt_10"] += 1

            if not observed and len(retrieved) >= 10:
                failure_buckets["not_in_candidate_pool"] += 1
            if not _topk_all(gold_set, retrieved, 5) and observed:
                failure_buckets["ranked_too_low_after_top5"] += 1
            if len(gold) > 1 and not _topk_all(gold_set, retrieved, 5):
                failure_buckets["multi_evidence_failure"] += 1
                if _gold_doc_split(case, gold) == "same_doc" and observed:
                    failure_buckets["boundary_or_window_candidate"] += 1

        if len(retrieved) != len(set(retrieved)):
            duplicate_counts["duplicate_chunk_id_cases"] += 1
            failure_buckets["duplicate_or_near_duplicate_candidate"] += 1
        for k, key in ((5, "repeated_doc_top5_cases"), (10, "repeated_doc_top10_cases")):
            docs = _doc_ids(rows, k)
            if docs and len(docs) != len(set(docs)):
                duplicate_counts[key] += 1
                failure_buckets["duplicate_or_near_duplicate_candidate"] += 1
                break

        metadata_count = _number(case.get("metadata_candidate_count")) or 0
        if metadata_count > 0:
            metadata_filter["metadata_candidate_cases"] += 1
            if not _bool(case.get("doc_match")):
                metadata_filter["metadata_candidate_doc_miss_cases"] += 1
                failure_buckets["metadata_filter_candidate"] += 1
        if _bool(case.get("metadata_ambiguous")):
            metadata_filter["metadata_ambiguous_cases"] += 1
            failure_buckets["metadata_filter_candidate"] += 1
        if str(case.get("filter_stage") or "") in {"reduced", "relaxed"}:
            metadata_filter["reduced_or_relaxed_filter_stage_cases"] += 1

        if failure_category == "verifier_false_negative":
            failure_buckets["verifier_false_negative"] += 1
        elif failure_category == "verifier_false_positive":
            failure_buckets["verifier_false_positive"] += 1
        elif failure_category == "evaluation_label_issue":
            failure_buckets["evaluation_label_gap"] += 1
        elif failure_category in {"answer_synthesis_issue", "abstention_failure"}:
            failure_buckets["answer_generation_or_abstention"] += 1

    page_meta = summary.get("index_citation_metadata_coverage")
    page_meta = page_meta if isinstance(page_meta, Mapping) else {}
    page_span_coverage = _number(page_meta.get("page_span_coverage"))
    if page_span_coverage == 0.0:
        failure_buckets["page_metadata_blocked"] = int(summary.get("num_predictions") or len(cases))

    slices: dict[str, Any] = {}
    for query_type, items in slice_cases.items():
        if not items:
            slices[query_type] = _empty_slice()
            continue
        status_counts = Counter(_exclusive_status(case, _gold_chunk_ids(case), _retrieved_chunk_ids(case)) for case in items)
        metrics = _metric_block(list(items))
        slices[query_type] = {
            "cases": len(items),
            "answerable": sum(1 for case in items if case.get("answerable") is True),
            "chunk_recall_at_5": metrics["chunk_recall_at_5"],
            "chunk_recall_at_10": metrics["chunk_recall_at_10"],
            "chunk_recall_at_20": metrics["chunk_recall_at_20"],
            "hit_at_5": metrics["hit_at_k"]["5"],
            "hit_at_10": metrics["hit_at_k"]["10"],
            "mrr_at_5": metrics["mrr_at_5"],
            "ndcg_at_5": metrics["ndcg_at_5"],
            "ndcg_at_10": metrics["ndcg_at_10"],
            "dominant_exclusive_status": _dominant(status_counts),
        }

    metric_block = _metric_block(cases)
    recommendation = _recommend_next_task(
        page_span_coverage=page_span_coverage,
        failure_buckets=failure_buckets,
        all_gold_observed_rate=_rate(
            candidate_pool["all_gold_observed"], metric_block["coverage_cases"]
        ),
        any_gold_observed_rate=_rate(
            candidate_pool["any_gold_observed"], metric_block["coverage_cases"]
        ),
        coverage_cases=metric_block["coverage_cases"],
    )

    return {
        "schema_version": 1,
        "profile_type": "private_real100_v2_retrieval_diagnostics",
        "source": dict(source or {}),
        "population": {
            "num_predictions": int(summary.get("num_predictions") or len(cases)),
            "answerable": sum(1 for case in cases if case.get("answerable") is True),
            "unanswerable": sum(1 for case in cases if case.get("answerable") is False),
            "query_type_counts": dict(query_types),
            "failure_category_counts": dict(failure_categories),
        },
        "retrieval_metrics": metric_block,
        "exclusive_retrieval_status": {
            "counts": dict(exclusive),
            "dominant": _dominant(exclusive),
        },
        "candidate_pool_coverage": {
            **candidate_pool,
            "any_gold_observed_rate": _rate(candidate_pool["any_gold_observed"], metric_block["coverage_cases"]),
            "all_gold_observed_rate": _rate(candidate_pool["all_gold_observed"], metric_block["coverage_cases"]),
            "no_gold_observed_rate": _rate(candidate_pool["no_gold_observed"], metric_block["coverage_cases"]),
        },
        "evidence_shape": {
            "counts": dict(evidence_split),
            "multi_chunk_doc_split": dict(multi_doc_split),
            "multi_chunk_rate": _rate(evidence_split["multi_chunk"], len(cases)),
        },
        "failure_buckets": dict(failure_buckets),
        "duplicate_or_near_duplicate": duplicate_counts,
        "metadata_filter": metadata_filter,
        "query_type_slices": slices,
        "page_metadata_blocker": {
            "status": (
                "blocked_for_page_and_window_claims"
                if page_span_coverage == 0.0
                else "available"
            ),
            "chunks_total": int(page_meta.get("chunks_total") or 0),
            "chunks_with_page_span": int(page_meta.get("chunks_with_page_span") or 0),
            "page_span_coverage": page_span_coverage,
            "coverage_reason": str(page_meta.get("coverage_reason") or "unknown"),
        },
        "next_task_decision": recommendation,
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


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def render_markdown(report: Mapping[str, Any]) -> str:
    source = _mapping(report.get("source"))
    population = _mapping(report.get("population"))
    metrics = _mapping(report.get("retrieval_metrics"))
    status = _mapping(report.get("exclusive_retrieval_status"))
    status_counts = _mapping(status.get("counts"))
    candidate_pool = _mapping(report.get("candidate_pool_coverage"))
    evidence = _mapping(report.get("evidence_shape"))
    evidence_counts = _mapping(evidence.get("counts"))
    doc_split = _mapping(evidence.get("multi_chunk_doc_split"))
    failure_buckets = _mapping(report.get("failure_buckets"))
    duplicate = _mapping(report.get("duplicate_or_near_duplicate"))
    metadata = _mapping(report.get("metadata_filter"))
    blocker = _mapping(report.get("page_metadata_blocker"))
    next_task = _mapping(report.get("next_task_decision"))
    slices = _mapping(report.get("query_type_slices"))

    lines = [
        "# real100_v2 Retrieval Diagnostics",
        "",
        "Issue: [#1622](https://github.com/hskim-solv/BidMate-DocAgent/issues/1622)",
        "",
        "Task: `T-2026-0029`",
        "",
        "Status: aggregate-only diagnostic report; no runtime behavior change and no performance-improvement claim.",
        "",
        "## Boundary",
        "",
        "This report uses only `real100_v2` local private eval diagnostics and emits aggregate counts. It does not include raw questions, answers, evidence text, filenames, local paths, document IDs, chunk IDs, sections, or per-case rows. Legacy `real100`/v1/221/kordoc evidence is not used.",
        "",
        "## Source Provenance",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Input artifact | `{source.get('input_artifact') or ''}` |",
        f"| Input redacted | `{source.get('input_location_redacted')}` |",
        f"| Input SHA-256 prefix | `{source.get('input_sha256_12') or ''}` |",
        "",
        "## Population",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Predictions | {population.get('num_predictions', 0)} |",
        f"| Answerable | {population.get('answerable', 0)} |",
        f"| Unanswerable | {population.get('unanswerable', 0)} |",
        f"| Single-chunk gold | {evidence_counts.get('single_chunk', 0)} |",
        f"| Multi-chunk gold | {evidence_counts.get('multi_chunk', 0)} |",
        f"| No gold evidence | {evidence_counts.get('no_gold', 0)} |",
        "",
        "## Retrieval Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Coverage cases | {metrics.get('coverage_cases', 0)} |",
        f"| Recall@5 | {metrics.get('chunk_recall_at_5')} |",
        f"| Recall@10 | {metrics.get('chunk_recall_at_10')} |",
        f"| Recall@20 | {metrics.get('chunk_recall_at_20')} |",
        f"| Hit@5 | {_mapping(metrics.get('hit_at_k')).get('5')} |",
        f"| Hit@10 | {_mapping(metrics.get('hit_at_k')).get('10')} |",
        f"| All-gold@5 | {_mapping(metrics.get('all_gold_at_k')).get('5')} |",
        f"| All-gold@10 | {_mapping(metrics.get('all_gold_at_k')).get('10')} |",
        f"| MRR@5 | {metrics.get('mrr_at_5')} |",
        f"| nDCG@5 | {metrics.get('ndcg_at_5')} |",
        f"| nDCG@10 | {metrics.get('ndcg_at_10')} |",
        "",
        "## Exclusive Retrieval Status",
        "",
        f"Dominant bucket: `{status.get('dominant')}`",
        "",
        "| Bucket | Count |",
        "|---|---:|",
    ]
    for bucket in EXCLUSIVE_STATUS:
        lines.append(f"| `{bucket}` | {status_counts.get(bucket, 0)} |")

    lines.extend(
        [
            "",
            "## Failure Buckets",
            "",
            "| Bucket | Count |",
            "|---|---:|",
        ]
    )
    for bucket in sorted(failure_buckets):
        lines.append(f"| `{bucket}` | {failure_buckets.get(bucket, 0)} |")

    lines.extend(
        [
            "",
            "## Candidate Pool And Evidence Shape",
            "",
            "| Signal | Count / Rate |",
            "|---|---:|",
            f"| Any gold observed | {candidate_pool.get('any_gold_observed', 0)} |",
            f"| All gold observed | {candidate_pool.get('all_gold_observed', 0)} |",
            f"| No gold observed | {candidate_pool.get('no_gold_observed', 0)} |",
            f"| Partial gold observed | {candidate_pool.get('partial_gold_observed', 0)} |",
            f"| Retrieval depth < 10 | {candidate_pool.get('retrieval_depth_lt_10', 0)} |",
            f"| Any-gold observed rate | {candidate_pool.get('any_gold_observed_rate')} |",
            f"| All-gold observed rate | {candidate_pool.get('all_gold_observed_rate')} |",
            f"| No-gold observed rate | {candidate_pool.get('no_gold_observed_rate')} |",
            f"| Multi-chunk same-doc | {doc_split.get('same_doc', 0)} |",
            f"| Multi-chunk multi-doc | {doc_split.get('multi_doc', 0)} |",
            f"| Multi-chunk unknown-doc | {doc_split.get('unknown', 0)} |",
            "",
            "## Duplicate And Metadata Signals",
            "",
            "| Signal | Count |",
            "|---|---:|",
            f"| Duplicate chunk-id cases | {duplicate.get('duplicate_chunk_id_cases', 0)} |",
            f"| Repeated document in top 5 | {duplicate.get('repeated_doc_top5_cases', 0)} |",
            f"| Repeated document in top 10 | {duplicate.get('repeated_doc_top10_cases', 0)} |",
            f"| Metadata candidate cases | {metadata.get('metadata_candidate_cases', 0)} |",
            f"| Metadata candidate doc misses | {metadata.get('metadata_candidate_doc_miss_cases', 0)} |",
            f"| Metadata ambiguous cases | {metadata.get('metadata_ambiguous_cases', 0)} |",
            f"| Reduced/relaxed filter stage cases | {metadata.get('reduced_or_relaxed_filter_stage_cases', 0)} |",
            "",
            "## Query Type Slices",
            "",
            "| Query type | Cases | Recall@5 | Recall@10 | Hit@5 | MRR@5 | Dominant status |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for query_type in SAFE_QUERY_TYPES:
        row = _mapping(slices.get(query_type))
        lines.append(
            f"| `{query_type}` | {row.get('cases', 0)} | "
            f"{row.get('chunk_recall_at_5')} | {row.get('chunk_recall_at_10')} | "
            f"{row.get('hit_at_5')} | {row.get('mrr_at_5')} | "
            f"`{row.get('dominant_exclusive_status')}` |"
        )

    if blocker.get("status") == "available":
        page_blocker_prose = (
            f"Page-span coverage is now {blocker.get('page_span_coverage')}; "
            "the prior v2 page-metadata blocker is resolved. Claim-bearing "
            "page/citation and section-window work (T-2026-0031) is unblocked for "
            "follow-up. No old evidence is substituted."
        )
    else:
        page_blocker_prose = (
            "Claim-bearing page/citation or section-window work remains blocked "
            "while the v2 page metadata ready rate is 0.0. This report preserves "
            "that blocker instead of substituting old evidence."
        )

    lines.extend(
        [
            "",
            "## Page Metadata Blocker",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Status | `{blocker.get('status')}` |",
            f"| Chunks total | {blocker.get('chunks_total', 0)} |",
            f"| Chunks with page span | {blocker.get('chunks_with_page_span', 0)} |",
            f"| Page-span coverage | {blocker.get('page_span_coverage')} |",
            f"| Coverage reason | `{blocker.get('coverage_reason')}` |",
            "",
            page_blocker_prose,
            "",
            "## Next Task Decision",
            "",
            f"- Preferred next task: `{next_task.get('preferred_next_task')}`",
            f"- Reason: `{next_task.get('reason')}`",
            f"- Blocked task: `{next_task.get('blocked_task')}`",
            f"- Blocker: `{next_task.get('blocker')}`",
            f"- Signal: `{next_task.get('signal')}`",
            "",
            "## Non-Claims",
            "",
            "- No retrieval, reranking, verifier, answer, ingestion, chunking, or eval scoring behavior changed.",
            "- No paired delta was produced.",
            "- No performance improvement is claimed.",
            "- No legacy `real100`/v1/221/kordoc evidence is used.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render aggregate-only real100_v2 retrieval diagnostics.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=_default_summary(),
        help="Path to ignored real100_v2 eval_summary.json.",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=ROOT / "reports" / "real100_v2" / "retrieval_diagnostics.aggregate.json",
        help="Aggregate JSON output path.",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=ROOT / "docs" / "evaluation" / "real100_v2-retrieval-diagnostics.md",
        help="Aggregate Markdown output path.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        _require_real100_v2(args.summary)
        summary = _load_json(args.summary)
        report = build_diagnostics(summary, source=_source_provenance(args.summary))
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"Failed to render real100_v2 retrieval diagnostics: {exc}", file=sys.stderr)
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


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
