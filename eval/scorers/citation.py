"""Citation grounding scorers — page/region match with bbox IoU."""
from __future__ import annotations

from typing import Any

from rag_core import rate

from eval.scorers._shared import answer_citations


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
