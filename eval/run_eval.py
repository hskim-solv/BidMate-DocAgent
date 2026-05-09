#!/usr/bin/env python3
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from rag_core import (
    DEFAULT_CLI_PIPELINE_NAME,
    load_index,
    percentile,
    rate,
    resolve_pipeline_config,
    run_rag_query,
)


QUERY_TYPES = ("single_doc", "multi_doc", "follow_up", "abstention")
DEFAULT_ABLATION_RUNS = [
    {
        "name": DEFAULT_CLI_PIPELINE_NAME,
        "pipeline": DEFAULT_CLI_PIPELINE_NAME,
    }
]


def hardcase_categories(item: dict[str, Any]) -> list[str]:
    categories = item.get("hardcase_categories") or item.get("hardcase_category") or []
    if isinstance(categories, str):
        categories = [categories]
    if not isinstance(categories, list):
        return []
    normalized = []
    seen: set[str] = set()
    for category in categories:
        value = str(category).strip()
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local RAG evaluation over configured cases.")
    parser.add_argument("--input_dir", default="outputs", help="Kept for CLI compatibility; not required.")
    parser.add_argument("--index_dir", default="data/index", help="Directory containing built index.json.")
    parser.add_argument("--output_dir", default="reports", help="Directory to save eval summary.")
    parser.add_argument("--query", default=None, help="Unused in this command; accepted for CLI consistency.")
    parser.add_argument("--config", required=True, help="Path to eval config YAML file.")
    return parser.parse_args()


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
        "verifier_retry": bool(config.get("verifier_retry")),
        "retrieval_mode": str(config.get("retrieval_mode", "flat")),
        "prompt_profile": str(config.get("prompt_profile")),
    }


def load_config(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Eval config must be a mapping: {path}")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Eval config must include non-empty cases list")
    for case in cases:
        query_type = case.get("query_type")
        if query_type not in QUERY_TYPES:
            raise ValueError(f"Eval case must include query_type in {QUERY_TYPES}: {case.get('id')}")
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


def contains_all_terms(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return all(str(term).lower() in lowered for term in terms)


def retry_trigger_reasons(prediction: dict[str, Any]) -> list[str]:
    diagnostics = prediction.get("diagnostics") or {}
    reasons: list[str] = []
    for attempt in diagnostics.get("filter_stage_attempts") or []:
        if attempt.get("verified"):
            continue
        reasons.extend(str(reason) for reason in attempt.get("verification_reasons") or [])
    return reasons


def answer_payload(prediction: dict[str, Any]) -> dict[str, Any]:
    answer = prediction.get("answer")
    return answer if isinstance(answer, dict) else {}


def answer_claims(prediction: dict[str, Any]) -> list[dict[str, Any]]:
    claims = answer_payload(prediction).get("claims") or []
    return [claim for claim in claims if isinstance(claim, dict)]


def answer_to_text(prediction: dict[str, Any]) -> str:
    payload = answer_payload(prediction)
    if not payload:
        return str(prediction.get("answer") or "")
    parts = [
        str(payload.get("summary") or ""),
        str(prediction.get("answer_text") or ""),
    ]
    for claim in answer_claims(prediction):
        parts.extend([str(claim.get("claim") or ""), str(claim.get("support") or "")])
    insufficiency = payload.get("insufficiency")
    if isinstance(insufficiency, dict):
        parts.append(str(insufficiency.get("message") or ""))
    return " ".join(part for part in parts if part)


def answer_status(prediction: dict[str, Any]) -> str:
    payload = answer_payload(prediction)
    diagnostics = prediction.get("diagnostics") or {}
    return str(payload.get("status") or diagnostics.get("answer_status") or "")


def answer_citations(prediction: dict[str, Any]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for claim in answer_claims(prediction):
        for citation in claim.get("citations") or []:
            if isinstance(citation, dict):
                citations.append(citation)
    return citations


def is_bbox(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    try:
        [float(part) for part in value]
    except (TypeError, ValueError):
        return False
    return True


def bbox_iou(left: list[Any], right: list[Any]) -> float:
    l0, t0, l1, b1 = [float(part) for part in left]
    r0, u0, r1, d1 = [float(part) for part in right]
    inter_w = max(0.0, min(l1, r1) - max(l0, r0))
    inter_h = max(0.0, min(b1, d1) - max(t0, u0))
    intersection = inter_w * inter_h
    left_area = max(0.0, l1 - l0) * max(0.0, b1 - t0)
    right_area = max(0.0, r1 - r0) * max(0.0, d1 - u0)
    union = left_area + right_area - intersection
    return 0.0 if union <= 0 else intersection / union


def citation_pages(citation: dict[str, Any]) -> set[int]:
    pages: set[int] = set()
    page_span = citation.get("page_span")
    if (
        isinstance(page_span, list)
        and len(page_span) == 2
        and all(isinstance(page, int) for page in page_span)
    ):
        start, end = page_span
        if start <= end:
            pages.update(range(start, end + 1))
    for region in citation.get("regions") or []:
        if isinstance(region, dict) and isinstance(region.get("page_number"), int):
            pages.add(int(region["page_number"]))
    return pages


def score_citation_pages(
    expected_pages: list[dict[str, Any]],
    citations: list[dict[str, Any]],
) -> tuple[float | None, list[dict[str, Any]]]:
    if not expected_pages:
        return None, []

    matched = 0
    errors: list[dict[str, Any]] = []
    for expected in expected_pages:
        doc_id = str(expected.get("doc_id") or "")
        pages = {int(page) for page in expected.get("pages") or [] if isinstance(page, int)}
        same_doc = [citation for citation in citations if str(citation.get("doc_id") or "") == doc_id]
        page_sets = [citation_pages(citation) for citation in same_doc]
        page_sets = [page_set for page_set in page_sets if page_set]
        if any(page_set & pages for page_set in page_sets):
            matched += 1
            continue
        if not page_sets:
            errors.append(
                {
                    "code": "page_missing",
                    "message": "Expected citation page metadata was unavailable.",
                    "expected": {"doc_id": doc_id, "pages": sorted(pages)},
                }
            )
        else:
            errors.append(
                {
                    "code": "page_mismatch",
                    "message": "Citation page metadata did not overlap expected pages.",
                    "expected": {"doc_id": doc_id, "pages": sorted(pages)},
                    "actual_pages": sorted({page for page_set in page_sets for page in page_set}),
                }
            )
    return matched / len(expected_pages), errors


def citation_regions(citation: dict[str, Any]) -> list[dict[str, Any]]:
    regions = citation.get("regions") or []
    return [region for region in regions if isinstance(region, dict)]


def score_citation_regions(
    expected_regions: list[dict[str, Any]],
    citations: list[dict[str, Any]],
) -> tuple[float | None, list[dict[str, Any]]]:
    if not expected_regions:
        return None, []

    matched = 0
    errors: list[dict[str, Any]] = []
    for expected in expected_regions:
        doc_id = str(expected.get("doc_id") or "")
        page_number = int(expected["page_number"])
        expected_bbox = expected.get("bbox")
        min_iou = float(expected.get("min_iou", 0.5))
        candidate_regions: list[dict[str, Any]] = []
        for citation in citations:
            if str(citation.get("doc_id") or "") != doc_id:
                continue
            for region in citation_regions(citation):
                if region.get("page_number") == page_number and is_bbox(region.get("bbox")):
                    candidate_regions.append(region)
        if not candidate_regions:
            errors.append(
                {
                    "code": "region_unavailable",
                    "message": "Expected citation region metadata was unavailable.",
                    "expected": {
                        "doc_id": doc_id,
                        "page_number": page_number,
                        "bbox": expected_bbox,
                    },
                }
            )
            continue
        best_iou = max(bbox_iou(region["bbox"], expected_bbox) for region in candidate_regions)
        if best_iou >= min_iou:
            matched += 1
            continue
        errors.append(
            {
                "code": "region_misaligned",
                "message": "Citation region bbox did not meet the IoU threshold.",
                "expected": {
                    "doc_id": doc_id,
                    "page_number": page_number,
                    "bbox": expected_bbox,
                    "min_iou": min_iou,
                },
                "actual": {
                    "best_iou": round(best_iou, 3),
                    "regions": [
                        {
                            "page_number": region.get("page_number"),
                            "bbox": region.get("bbox"),
                            "block_id": region.get("block_id"),
                        }
                        for region in candidate_regions
                    ],
                },
            }
        )
    return matched / len(expected_regions), errors


def score_citation_grounding(
    case: dict[str, Any],
    prediction: dict[str, Any],
) -> dict[str, Any]:
    citations = answer_citations(prediction)
    page_score, page_errors = score_citation_pages(case.get("expected_citation_pages") or [], citations)
    region_score, region_errors = score_citation_regions(
        case.get("expected_citation_regions") or [],
        citations,
    )
    present_scores = [
        score for score in (page_score, region_score) if isinstance(score, (int, float))
    ]
    return {
        "citation_page_precision": page_score,
        "citation_region_precision": region_score,
        "citation_grounding": rate([float(score) for score in present_scores]),
        "citation_grounding_errors": page_errors + region_errors,
    }


def score_answer_format(
    case: dict[str, Any],
    prediction: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy or {}
    answerable = bool(case.get("answerable", True))
    expected_status = case.get("expected_answer_status")
    if expected_status is None:
        expected_status = (
            policy.get("answerable_status", "supported")
            if answerable
            else policy.get("unanswerable_status", "insufficient")
        )
    min_claims = case.get("min_claims")
    if min_claims is None:
        min_claims = int(
            policy.get("min_claims_answerable", 1)
            if answerable
            else policy.get("min_claims_unanswerable", 0)
        )
    require_claim_citations = bool(
        case.get("require_claim_citations", policy.get("require_claim_citations", True))
    )
    expected_targets = {str(target) for target in case.get("expected_claim_targets") or []}

    claims = answer_claims(prediction)
    claim_targets = {str(claim.get("target") or "") for claim in claims}
    citation_checks = []
    for claim in claims:
        citations = claim.get("citations") or []
        citation_checks.append(
            bool(citations)
            and all(
                isinstance(citation, dict)
                and bool(citation.get("doc_id"))
                and bool(citation.get("chunk_id"))
                for citation in citations
            )
        )
    citations_ok = True
    if require_claim_citations and claims:
        citations_ok = all(citation_checks)
    elif require_claim_citations and int(min_claims) > 0:
        citations_ok = False

    checks = {
        "status_match": answer_status(prediction) == str(expected_status),
        "min_claims": len(claims) >= int(min_claims),
        "claim_targets": expected_targets.issubset(claim_targets),
        "claim_citations": citations_ok,
    }
    return {
        "expected_answer_status": str(expected_status),
        "answer_status": answer_status(prediction),
        "expected_claim_targets": sorted(expected_targets),
        "claim_targets": sorted(target for target in claim_targets if target),
        "claim_count": len(claims),
        "format_checks": checks,
        "answer_format_compliance": 1.0 if all(checks.values()) else 0.0,
    }


def score_case(
    case: dict[str, Any],
    prediction: dict[str, Any],
    answer_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    answerable = bool(case.get("answerable", True))
    query_type = str(case.get("query_type"))
    expected_doc_ids = set(case.get("expected_doc_ids") or [])
    expected_terms = [str(term) for term in case.get("expected_terms") or []]
    expected_citation_terms = [
        str(term) for term in case.get("expected_citation_terms") or expected_terms
    ]
    evidence = prediction.get("evidence") or []
    evidence_doc_ids = {item.get("doc_id") for item in evidence}
    answer = answer_to_text(prediction)
    evidence_text = " ".join(str(item.get("text") or "") for item in evidence)
    combined_text = " ".join([answer, evidence_text])
    diagnostics = prediction.get("diagnostics") or {}
    plan = prediction.get("plan") or {}
    analysis = prediction.get("analysis") or {}
    context_resolution = diagnostics.get("context_resolution") or {}
    metadata_resolution = diagnostics.get("metadata_resolution") or {}
    ambiguity = metadata_resolution.get("ambiguity") or {}
    abstained = bool(diagnostics.get("abstained"))
    answer_format = score_answer_format(case, prediction, answer_policy)
    citation_grounding = score_citation_grounding(case, prediction)

    citation_doc_precision = 0.0
    if evidence_doc_ids:
        citation_doc_precision = len(evidence_doc_ids & expected_doc_ids) / len(evidence_doc_ids)
    citation_term_match = (
        contains_all_terms(evidence_text, expected_citation_terms)
        if expected_citation_terms
        else bool(evidence)
    )

    comparison_target_recall: float | None = None
    comparison_pool_recall: float | None = None
    if query_type == "multi_doc" and len(expected_doc_ids) >= 2:
        covered = expected_doc_ids & evidence_doc_ids
        comparison_target_recall = len(covered) / len(expected_doc_ids)
        coverage_after = (
            ((prediction.get("plan") or {}).get("comparison_coverage") or {}).get("after") or {}
        )
        pool_doc_ids = {doc_id for doc_id, count in coverage_after.items() if count > 0}
        if pool_doc_ids:
            comparison_pool_recall = (
                len(expected_doc_ids & pool_doc_ids) / len(expected_doc_ids)
            )

    if answerable:
        doc_match = expected_doc_ids.issubset(evidence_doc_ids)
        term_match = contains_all_terms(combined_text, expected_terms)
        accuracy = 1.0 if doc_match and term_match and not abstained else 0.0
        groundedness = 1.0 if term_match and evidence and not abstained else 0.0
        citation_precision = citation_doc_precision if citation_term_match else 0.0
        abstention = None
    else:
        doc_match = not evidence
        term_match = abstained
        accuracy = None
        groundedness = 1.0 if abstained and not evidence else 0.0
        citation_precision = 1.0 if abstained and not evidence else 0.0
        abstention = 1.0 if abstained else 0.0

    return {
        "id": case.get("id"),
        "query_type": query_type,
        "hardcase_categories": hardcase_categories(case),
        "query": case.get("query"),
        "answerable": answerable,
        "expected_doc_ids": sorted(expected_doc_ids),
        "evidence_doc_ids": sorted(doc_id for doc_id in evidence_doc_ids if doc_id),
        "doc_match": doc_match,
        "term_match": term_match,
        "citation_term_match": citation_term_match,
        "citation_doc_precision": citation_doc_precision,
        "accuracy": accuracy,
        "groundedness": groundedness,
        "citation_precision": citation_precision,
        **citation_grounding,
        "abstention": abstention,
        "comparison_target_recall": comparison_target_recall,
        "comparison_pool_recall": comparison_pool_recall,
        "latency_ms": diagnostics.get("latency_ms"),
        "retry_count": diagnostics.get("retry_count", 0),
        "retry_trigger_reasons": retry_trigger_reasons(prediction),
        "filter_stage": plan.get("filter_stage"),
        "selected_top_k": diagnostics.get("selected_top_k"),
        "retrieval_budget": dict(plan.get("retrieval_budget") or {}),
        "metadata_ambiguous": bool(analysis.get("metadata_ambiguous")),
        "ambiguity_decision": ambiguity.get("decision"),
        "ambiguity_reason": ambiguity.get("decision_reason") or ambiguity.get("reason"),
        "metadata_candidate_count": metadata_resolution.get("candidate_count"),
        "metadata_selected_doc_ids": metadata_resolution.get("selected_doc_ids") or [],
        "cold_start": bool(diagnostics.get("cold_start", False)),
        "stage_latency": dict(diagnostics.get("stage_latency") or {}),
        "attempt_latency": [
            {
                "stage": attempt.get("stage"),
                "retrieve_ms": attempt.get("retrieve_ms", 0.0),
                "verify_ms": attempt.get("verify_ms", 0.0),
            }
            for attempt in diagnostics.get("filter_stage_attempts") or []
        ],
        "context_resolution_status": context_resolution.get("status"),
        "context_resolution_source": context_resolution.get("source"),
        "context_resolution_confidence": context_resolution.get("confidence"),
        "context_resolution_reason": context_resolution.get("reason"),
        "resolved_query": prediction.get("resolved_query"),
        "abstained": abstained,
        **answer_format,
        "answer": answer,
    }


_TOP_LEVEL_STAGE_KEYS = ("query_analysis_ms", "context_resolution_ms", "answer_generation_ms")


def _latency_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "mean": rate(values),
        "count": len(values),
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
    abstention_scores = [r["abstention"] for r in case_results if r["abstention"] is not None]
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

    block: dict[str, Any] = {
        "num_predictions": len(case_results),
        "accuracy": rate(accuracy_scores),
        "groundedness": rate(groundedness_scores),
        "citation_precision": rate(citation_scores),
        "citation_page_precision": rate(citation_page_scores),
        "citation_region_precision": rate(citation_region_scores),
        "citation_grounding": rate(citation_grounding_scores),
        "abstention": rate(abstention_scores),
        "answer_format_compliance": rate(format_scores),
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
        "retry_reason_counts": dict(sorted(retry_reason_counts.items())),
        "citation_grounding_error_counts": dict(sorted(citation_grounding_error_counts.items())),
    }
    if comparison_recall_scores:
        block["comparison_target_recall"] = rate(comparison_recall_scores)
        block["comparison_target_full_coverage_rate"] = rate(
            [1.0 if score >= 1.0 - 1e-9 else 0.0 for score in comparison_recall_scores]
        )
    if comparison_pool_recall_scores:
        block["comparison_pool_recall"] = rate(comparison_pool_recall_scores)
        block["comparison_pool_full_coverage_rate"] = rate(
            [1.0 if score >= 1.0 - 1e-9 else 0.0 for score in comparison_pool_recall_scores]
        )
    return block


def summarize_run(
    name: str,
    run_config: dict[str, Any],
    case_results: list[dict[str, Any]],
    include_cases: bool = False,
) -> dict[str, Any]:
    summary = {
        "name": name,
        "pipeline": str(run_config.get("pipeline") or ""),
        "top_k": run_config.get("top_k"),
        "metadata_first": bool(run_config.get("metadata_first", True)),
        "rerank": bool(run_config.get("rerank", True)),
        "verifier_retry": bool(run_config.get("verifier_retry", True)),
        "retrieval_mode": str(run_config.get("retrieval_mode", "flat")),
        "prompt_profile": str(run_config.get("prompt_profile") or ""),
        **metric_block(case_results),
        "by_query_type": {},
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in case_results:
        grouped[str(result["query_type"])].append(result)
    for query_type in QUERY_TYPES:
        if query_type in grouped:
            summary["by_query_type"][query_type] = metric_block(grouped[query_type])
    hardcase_grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in case_results:
        for category in hardcase_categories(result):
            hardcase_grouped[category].append(result)
    if hardcase_grouped:
        summary["by_hardcase_category"] = {
            category: metric_block(hardcase_grouped[category])
            for category in sorted(hardcase_grouped)
        }
    if include_cases:
        summary["case_results"] = case_results
    return summary


def evaluate_run(
    index: dict[str, Any],
    cases: list[dict[str, Any]],
    run_config: dict[str, Any],
    answer_policy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    case_results = []
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
                prompt_profile=str(run_config.get("prompt_profile") or ""),
                conversation_state=conversation_state,
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
            verifier_retry=bool(run_config.get("verifier_retry", True)),
            retrieval_mode=str(run_config.get("retrieval_mode", "flat")),
            prompt_profile=str(run_config.get("prompt_profile") or ""),
            conversation_state=conversation_state,
        )
        case_results.append(score_case(case, prediction, answer_policy))
    return case_results


def ablation_runs(config: dict[str, Any]) -> list[dict[str, Any]]:
    runs = config.get("ablation_runs") or DEFAULT_ABLATION_RUNS
    return [normalize_run_config(run) for run in runs]


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
    try:
        for run_config in ablation_runs(config):
            case_results = evaluate_run(
                index,
                config["cases"],
                run_config,
                config.get("answer_policy") if isinstance(config.get("answer_policy"), dict) else {},
            )
            is_primary = run_config["name"] == primary_run_name
            run_summary = summarize_run(
                run_config["name"],
                run_config,
                case_results,
                include_cases=is_primary,
            )
            run_summaries.append(run_summary)
            if is_primary:
                primary_summary = run_summary
    except Exception as exc:
        print(f"[ERROR] Eval execution failed: {exc}", file=sys.stderr)
        return 2

    if primary_summary is None:
        primary_summary = run_summaries[0]

    summary = {
        "mode": "rag",
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
        "abstention": primary_summary["abstention"],
        "answer_format_compliance": primary_summary["answer_format_compliance"],
        "latency": primary_summary["latency"],
        "stage_latency": primary_summary.get("stage_latency", {}),
        "latency_by_retry_count": primary_summary.get("latency_by_retry_count", {}),
        "cold_start_samples": primary_summary.get("cold_start_samples", {}),
        "retry": primary_summary["retry"],
        "by_query_type": primary_summary["by_query_type"],
        "by_hardcase_category": primary_summary.get("by_hardcase_category", {}),
        "retry_cost": primary_summary["retry_cost"],
        "retry_reason_counts": primary_summary["retry_reason_counts"],
        "citation_grounding_error_counts": primary_summary["citation_grounding_error_counts"],
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
