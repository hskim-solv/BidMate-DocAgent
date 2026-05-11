#!/usr/bin/env python3
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re
import sys
from typing import Any
import unicodedata

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from rag_core import (
    DEFAULT_CLI_PIPELINE_NAME,
    MAX_AGENT_ITERATIONS,
    load_index,
    percentile,
    rate,
    redact_trace,
    resolve_pipeline_config,
    run_rag_query,
)


QUERY_TYPES = ("single_doc", "comparison", "follow_up", "abstention")
QUERY_TYPE_ALIASES = {"multi_doc": "comparison"}
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


def canonical_query_type(query_type: Any) -> str:
    value = str(query_type or "").strip()
    return QUERY_TYPE_ALIASES.get(value, value)


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


ALIGN_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]+")
ALIGN_STOPWORDS = {
    "기관",
    "핵심",
    "요구사항",
    "요구",
    "차이",
    "비교",
    "관련",
    "확인",
    "대상",
    "한다",
    "있다",
    "이다",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "의",
    "와",
    "과",
}


def normalized_alignment_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text).lower()
    return re.sub(r"[^0-9a-z가-힣]+", "", normalized)


def alignment_tokens(text: str) -> list[str]:
    tokens = []
    for match in ALIGN_TOKEN_RE.finditer(unicodedata.normalize("NFC", text).lower()):
        token = match.group(0)
        if len(token) <= 1 or token in ALIGN_STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def evidence_alignment_text(item: dict[str, Any]) -> str:
    parts = [
        item.get("title", ""),
        item.get("agency", ""),
        item.get("project", ""),
        item.get("section", ""),
        item.get("text", ""),
    ]
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        for key, value in sorted(metadata.items()):
            if value is None or value == "":
                continue
            parts.append(str(key))
            parts.append(str(value))
    return " ".join(str(part) for part in parts if str(part).strip())


def claim_text_supported_by_citation(claim: dict[str, Any], citation_text: str) -> bool:
    claim_text = " ".join(
        str(claim.get(key) or "") for key in ("claim", "support") if claim.get(key)
    )
    if not claim_text.strip() or not citation_text.strip():
        return False

    compact_claim = normalized_alignment_text(str(claim.get("claim") or ""))
    compact_citation = normalized_alignment_text(citation_text)
    if compact_claim and compact_claim in compact_citation:
        return True

    tokens = alignment_tokens(str(claim.get("claim") or ""))
    if not tokens:
        return bool(compact_claim and compact_claim in compact_citation)
    citation_tokens = set(alignment_tokens(citation_text))
    overlap = sum(1 for token in tokens if token in citation_tokens)
    return (overlap / max(1, len(tokens))) >= 0.5


def expected_claim_specs_for_target(
    case: dict[str, Any],
    target: str,
) -> list[dict[str, Any]]:
    specs = case.get("expected_claim_citations") or []
    matched = []
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        expected_target = str(spec.get("target") or "").strip()
        if not expected_target or expected_target == target:
            matched.append(spec)
    return matched


def score_claim_citation_alignment(
    case: dict[str, Any],
    prediction: dict[str, Any],
) -> dict[str, Any]:
    evidence_by_chunk = {
        str(item.get("chunk_id")): item
        for item in prediction.get("evidence") or []
        if item.get("chunk_id")
    }
    claims = answer_claims(prediction)
    expected_specs = [
        spec for spec in case.get("expected_claim_citations") or [] if isinstance(spec, dict)
    ]
    errors: list[dict[str, Any]] = []
    scores: list[float] = []
    claim_targets = {str(claim.get("target") or "") for claim in claims}

    for claim_index, claim in enumerate(claims):
        target = str(claim.get("target") or "")
        citations = [citation for citation in claim.get("citations") or [] if isinstance(citation, dict)]
        if not citations:
            scores.append(0.0)
            errors.append(
                {
                    "code": "claim_missing_citation",
                    "message": "Claim has no citation.",
                    "claim_index": claim_index,
                    "target": target,
                }
            )
            continue

        citation_items = []
        missing_chunk_ids = []
        for citation in citations:
            chunk_id = str(citation.get("chunk_id") or "")
            item = evidence_by_chunk.get(chunk_id)
            if item is None:
                missing_chunk_ids.append(chunk_id)
                continue
            citation_items.append(item)
        citation_text = " ".join(evidence_alignment_text(item) for item in citation_items)
        citation_doc_ids = {str(item.get("doc_id") or "") for item in citation_items}

        claim_errors: list[dict[str, Any]] = []
        if missing_chunk_ids and not citation_items:
            claim_errors.append(
                {
                    "code": "citation_not_in_evidence",
                    "message": "Claim citation chunk was not present in top-level evidence.",
                    "claim_index": claim_index,
                    "target": target,
                    "chunk_ids": missing_chunk_ids,
                }
            )
        elif not claim_text_supported_by_citation(claim, citation_text):
            claim_errors.append(
                {
                    "code": "claim_text_not_supported_by_citation",
                    "message": "Claim text was not directly supported by the cited evidence text.",
                    "claim_index": claim_index,
                    "target": target,
                    "citation_chunk_ids": [item.get("chunk_id") for item in citation_items],
                }
            )

        for spec in expected_claim_specs_for_target(case, target):
            expected_doc_ids = {str(doc_id) for doc_id in spec.get("expected_doc_ids") or []}
            expected_terms = [str(term) for term in spec.get("expected_terms") or []]
            if expected_doc_ids and not (expected_doc_ids & citation_doc_ids):
                claim_errors.append(
                    {
                        "code": "expected_claim_doc_mismatch",
                        "message": "Claim citation doc_id did not match the expected claim-level doc.",
                        "claim_index": claim_index,
                        "target": target,
                        "expected_doc_ids": sorted(expected_doc_ids),
                        "actual_doc_ids": sorted(doc_id for doc_id in citation_doc_ids if doc_id),
                    }
                )
            if expected_terms and not contains_all_terms(citation_text, expected_terms):
                claim_errors.append(
                    {
                        "code": "expected_claim_terms_missing",
                        "message": "Claim citation text missed expected claim-level terms.",
                        "claim_index": claim_index,
                        "target": target,
                        "expected_terms": expected_terms,
                    }
                )

        errors.extend(claim_errors)
        scores.append(0.0 if claim_errors else 1.0)

    for spec in expected_specs:
        expected_target = str(spec.get("target") or "").strip()
        if expected_target and expected_target not in claim_targets:
            scores.append(0.0)
            errors.append(
                {
                    "code": "expected_claim_missing",
                    "message": "Expected claim target was not emitted.",
                    "target": expected_target,
                }
            )

    return {
        "claim_citation_alignment": rate(scores) if scores else None,
        "claim_citation_aligned": sum(1 for score in scores if score >= 1.0),
        "claim_citation_checked": len(scores),
        "claim_citation_errors": errors,
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
    expected_missing_targets = {
        str(target) for target in case.get("expected_missing_targets") or []
    }

    payload = answer_payload(prediction)
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

    insufficiency = payload.get("insufficiency") if isinstance(payload, dict) else {}
    if not isinstance(insufficiency, dict):
        insufficiency = {}
    missing_targets = {str(target) for target in insufficiency.get("missing_targets") or []}

    checks = {
        "schema_version": int(payload.get("schema_version") or 0) >= 2,
        "status_match": answer_status(prediction) == str(expected_status),
        "min_claims": len(claims) >= int(min_claims),
        "claim_targets": expected_targets.issubset(claim_targets),
        "claim_citations": citations_ok,
    }
    if expected_missing_targets:
        checks["missing_targets"] = expected_missing_targets.issubset(missing_targets)
    return {
        "expected_answer_status": str(expected_status),
        "answer_status": answer_status(prediction),
        "expected_claim_targets": sorted(expected_targets),
        "claim_targets": sorted(target for target in claim_targets if target),
        "expected_missing_targets": sorted(expected_missing_targets),
        "missing_targets": sorted(target for target in missing_targets if target),
        "claim_count": len(claims),
        "format_checks": checks,
        "answer_format_compliance": 1.0 if all(checks.values()) else 0.0,
    }


CHUNK_METRIC_KS = (5, 10)


def derive_gold_chunk_ids(
    case: dict[str, Any],
    index: dict[str, Any] | None,
) -> list[str]:
    """Derive a chunk-level gold set from ``expected_doc_ids`` + ``expected_terms``.

    A chunk is gold if its ``doc_id`` is in the case's ``expected_doc_ids`` AND
    its text contains at least one ``expected_term``. If the case provides an
    explicit ``gold_chunk_ids`` list it is used verbatim. Returns an empty list
    for cases without expectations (e.g. abstention).
    """
    explicit = case.get("gold_chunk_ids")
    if explicit:
        return [str(item) for item in explicit if item]
    expected_doc_ids = set(case.get("expected_doc_ids") or [])
    expected_terms = [str(term) for term in case.get("expected_terms") or [] if term]
    if not expected_doc_ids or not expected_terms or not index:
        return []
    chunks = index.get("chunks") or []
    gold: list[str] = []
    for chunk in chunks:
        if chunk.get("doc_id") not in expected_doc_ids:
            continue
        text = str(chunk.get("text") or "")
        if any(term in text for term in expected_terms):
            chunk_id = str(chunk.get("chunk_id") or "")
            if chunk_id:
                gold.append(chunk_id)
    return gold


def chunk_recall_at_k(retrieved: list[str], gold: list[str], k: int) -> float | None:
    if not gold:
        return None
    if not retrieved or k <= 0:
        return 0.0
    head = retrieved[:k]
    hits = sum(1 for chunk_id in gold if chunk_id in head)
    return hits / len(gold)


def chunk_mrr(retrieved: list[str], gold: list[str]) -> float | None:
    if not gold:
        return None
    if not retrieved:
        return 0.0
    gold_set = set(gold)
    for rank, chunk_id in enumerate(retrieved, start=1):
        if chunk_id in gold_set:
            return 1.0 / rank
    return 0.0


def chunk_ndcg_at_k(retrieved: list[str], gold: list[str], k: int) -> float | None:
    if not gold:
        return None
    if not retrieved or k <= 0:
        return 0.0
    gold_set = set(gold)
    dcg = 0.0
    for rank, chunk_id in enumerate(retrieved[:k], start=1):
        rel = 1.0 if chunk_id in gold_set else 0.0
        if rel:
            dcg += rel / math.log2(rank + 1)
    ideal_hits = min(len(gold_set), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return (dcg / idcg) if idcg else 0.0


def score_case(
    case: dict[str, Any],
    prediction: dict[str, Any],
    answer_policy: dict[str, Any] | None = None,
    *,
    gold_chunk_ids: list[str] | None = None,
) -> dict[str, Any]:
    answerable = bool(case.get("answerable", True))
    query_type = canonical_query_type(case.get("query_type"))
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
    claim_alignment = score_claim_citation_alignment(case, prediction)

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
    if query_type == "comparison" and len(expected_doc_ids) >= 2:
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

    retrieved_chunk_ids = [
        str(chunk_id)
        for chunk_id in diagnostics.get("retrieved_chunk_ids") or []
        if chunk_id
    ]
    gold_for_chunks = [str(item) for item in gold_chunk_ids or [] if item]
    chunk_metrics: dict[str, float | None] = {
        f"chunk_recall_at_{k}": chunk_recall_at_k(retrieved_chunk_ids, gold_for_chunks, k)
        for k in CHUNK_METRIC_KS
    }
    chunk_metrics["chunk_mrr"] = chunk_mrr(retrieved_chunk_ids, gold_for_chunks)
    chunk_metrics["chunk_ndcg_at_10"] = chunk_ndcg_at_k(retrieved_chunk_ids, gold_for_chunks, 10)

    return {
        "id": case.get("id"),
        "query_type": query_type,
        "slice": query_type,
        "hardcase_categories": hardcase_categories(case),
        "query": case.get("query"),
        "answerable": answerable,
        "expected_doc_ids": sorted(expected_doc_ids),
        "evidence_doc_ids": sorted(doc_id for doc_id in evidence_doc_ids if doc_id),
        "gold_chunk_ids": gold_for_chunks,
        "retrieved_chunk_ids": retrieved_chunk_ids,
        **chunk_metrics,
        "doc_match": doc_match,
        "term_match": term_match,
        "citation_term_match": citation_term_match,
        "citation_doc_precision": citation_doc_precision,
        "accuracy": accuracy,
        "groundedness": groundedness,
        "citation_precision": citation_precision,
        **citation_grounding,
        **claim_alignment,
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
    claim_alignment_scores = [
        r["claim_citation_alignment"]
        for r in case_results
        if r.get("claim_citation_alignment") is not None
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

    chunk_metric_summary: dict[str, float | None] = {}
    for key in [f"chunk_recall_at_{k}" for k in CHUNK_METRIC_KS] + [
        "chunk_mrr",
        "chunk_ndcg_at_10",
    ]:
        values = [r[key] for r in case_results if r.get(key) is not None]
        chunk_metric_summary[key] = rate(values)
    cases_with_gold = sum(1 for r in case_results if r.get("gold_chunk_ids"))
    chunk_metric_summary["cases_with_gold"] = cases_with_gold
    chunk_metric_summary["cases_total"] = len(case_results)

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
        "answer_format_compliance": rate(format_scores),
        "chunk_retrieval": chunk_metric_summary,
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
        "citation_grounding_error_counts": dict(sorted(citation_grounding_error_counts.items())),
        "claim_citation_error_counts": dict(sorted(claim_citation_error_counts.items())),
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
    if include_cases:
        summary["case_results"] = case_results
    return summary


def safe_path_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "unknown"


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
    return {
        "schema_version": 1,
        "case_id": case.get("id"),
        "run": run_config.get("name"),
        "pipeline": run_config.get("pipeline"),
        "slice": canonical_query_type(case.get("query_type")),
        "query": case.get("query"),
        "answer_status": answer_status(prediction),
        "trace": trace,
    }


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


def evaluate_run(
    index: dict[str, Any],
    cases: list[dict[str, Any]],
    run_config: dict[str, Any],
    answer_policy: dict[str, Any] | None = None,
    trace_dir: Path | None = None,
    redact_options: dict[str, bool] | None = None,
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
        case_results.append(result)
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
    trace_root = Path(args.trace_dir) if args.trace_dir else Path(args.output_dir) / "traces"
    redact_options = trace_redact_options(args.redact_trace)
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
        "claim_citation_alignment": primary_summary["claim_citation_alignment"],
        "abstention": primary_summary["abstention"],
        "answer_format_compliance": primary_summary["answer_format_compliance"],
        "latency": primary_summary["latency"],
        "stage_latency": primary_summary.get("stage_latency", {}),
        "latency_by_retry_count": primary_summary.get("latency_by_retry_count", {}),
        "cold_start_samples": primary_summary.get("cold_start_samples", {}),
        "retry": primary_summary["retry"],
        "by_query_type": primary_summary["by_query_type"],
        "by_slice": primary_summary.get("by_slice", {}),
        "by_hardcase_category": primary_summary.get("by_hardcase_category", {}),
        "retry_cost": primary_summary["retry_cost"],
        "retry_reason_counts": primary_summary["retry_reason_counts"],
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
