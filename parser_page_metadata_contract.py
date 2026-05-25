"""Parser output contract for optional section page metadata.

This module validates parser-produced ``sections`` before page-aware re-index
work. It is intentionally independent from RAG runtime normalizers so existing
retrieval, verifier, answer, and citation behavior stays unchanged.
"""

from __future__ import annotations

from collections import Counter
import re
from typing import Any, Mapping, Sequence


PAGE_AWARE_CAPABLE = "page_aware_capable"
PAGE_BLIND = "page_blind"
ADAPTER_SPIKE_REQUIRED = "adapter_spike_required"
SAFE_SOURCE_GROUP_RE = re.compile(r"^[A-Za-z0-9_:/-]+$")
PRIVATE_SOURCE_VALUE_RE = re.compile(
    r"(^|[\s\"'`])(/Users/|/private/|/tmp/|/var/|/home/|/Volumes/|[A-Za-z]:\\)"
)
FILENAME_VALUE_RE = re.compile(
    r"(^|[\s\"'`])[^/\s\"'`]+\.(pdf|hwp|hwpx|docx|xlsx|csv|jsonl|md|txt)\b",
    re.IGNORECASE,
)


class PageMetadataContractError(ValueError):
    """Raised when parser section page metadata violates the contract."""

    def __init__(self, message: str, report: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.report = dict(report)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _safe_source_group(value: str | None) -> str:
    label = str(value or "").strip()
    if not label:
        return "<unspecified>"
    if PRIVATE_SOURCE_VALUE_RE.search(label) or FILENAME_VALUE_RE.search(label):
        return "<redacted_source_group>"
    if not SAFE_SOURCE_GROUP_RE.fullmatch(label):
        return "<redacted_source_group>"
    return label


def _page_span(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, list) or len(value) != 2:
        return None
    if not all(_strict_int(page) for page in value):
        return None
    start, end = value
    if start > end:
        return None
    return start, end


def classify_parser_source_group(
    *,
    file_format: str | None = None,
    text_source: str | None = None,
    document_type: str | None = None,
    any_page_metadata_coverage: float = 0.0,
    parent_any_page_metadata_coverage: float = 0.0,
) -> str:
    """Classify whether a parser source group can support page-aware re-index.

    The classification is aggregate-only and does not include identifiers,
    filenames, source paths, or raw text.
    """

    if any_page_metadata_coverage > 0 or parent_any_page_metadata_coverage > 0:
        return PAGE_AWARE_CAPABLE

    file_format = str(file_format or "")
    text_source = str(text_source or "")
    document_type = str(document_type or "")

    if "visual" in text_source and "fallback" not in text_source:
        return ADAPTER_SPIKE_REQUIRED
    if "visual" in document_type and "fallback" not in document_type:
        return ADAPTER_SPIKE_REQUIRED
    if file_format == "pdf" and text_source == "kordoc":
        return ADAPTER_SPIKE_REQUIRED
    if file_format == "hwp" and text_source == "kordoc":
        return ADAPTER_SPIKE_REQUIRED
    if file_format == "hwp" and "fallback" in document_type:
        return ADAPTER_SPIKE_REQUIRED
    return PAGE_BLIND


def _empty_report(source_group: str | None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_group": _safe_source_group(source_group),
        "section_count": 0,
        "with_page_span_count": 0,
        "with_regions_page_number_count": 0,
        "with_any_page_metadata_count": 0,
        "uncovered_count": 0,
        "uncovered_rate": 0.0,
        "page_span_coverage": 0.0,
        "regions_page_number_coverage": 0.0,
        "any_page_metadata_coverage": 0.0,
        "malformed_counts": {},
        "ok": True,
        "page_aware_capable": False,
        "page_metadata_capability": PAGE_BLIND,
        "privacy": {
            "aggregate_only": True,
            "omits_raw_text": True,
            "omits_doc_ids": True,
            "omits_chunk_ids": True,
            "omits_file_names": True,
            "omits_source_paths": True,
        },
    }


def validate_page_metadata_sections(
    sections: Sequence[Mapping[str, Any]],
    source_group: str | None = None,
) -> dict[str, Any]:
    """Validate parser output page metadata and return aggregate coverage.

    Missing page metadata is valid and counted as uncovered. Malformed
    ``page_span`` / ``regions`` metadata raises ``PageMetadataContractError``
    with aggregate counts only.
    """

    if not isinstance(sections, Sequence) or isinstance(sections, (str, bytes)):
        report = _empty_report(source_group)
        report["malformed_counts"] = {"sections_not_sequence": 1}
        report["ok"] = False
        raise PageMetadataContractError(
            "parser page metadata contract failed: sections_not_sequence=1",
            report,
        )

    section_count = len(sections)
    with_page_span = 0
    with_region_page = 0
    with_any_page = 0
    malformed: Counter[str] = Counter()

    for section in sections:
        if not isinstance(section, Mapping):
            malformed["section_not_object"] += 1
            continue

        raw_page_span = section.get("page_span")
        has_page_span_key = "page_span" in section and raw_page_span is not None
        page_span = _page_span(raw_page_span) if has_page_span_key else None
        if has_page_span_key and page_span is None:
            malformed["invalid_page_span"] += 1

        raw_regions = section.get("regions")
        regions: list[Mapping[str, Any]] = []
        if "regions" in section and raw_regions is not None:
            if not isinstance(raw_regions, list):
                malformed["regions_not_list"] += 1
            else:
                for region in raw_regions:
                    if not isinstance(region, Mapping):
                        malformed["region_not_object"] += 1
                        continue
                    regions.append(region)

        section_has_region_page = False
        for region in regions:
            if "page_number" not in region or region.get("page_number") is None:
                continue
            page_number = region.get("page_number")
            if not _strict_int(page_number):
                malformed["invalid_region_page_number"] += 1
                continue
            section_has_region_page = True
            if page_span is not None:
                start, end = page_span
                if not (start <= page_number <= end):
                    malformed["region_page_outside_page_span"] += 1

        if page_span is not None:
            with_page_span += 1
        if section_has_region_page:
            with_region_page += 1
        if page_span is not None or section_has_region_page:
            with_any_page += 1

    uncovered = section_count - with_any_page
    report = {
        "schema_version": 1,
        "source_group": _safe_source_group(source_group),
        "section_count": section_count,
        "with_page_span_count": with_page_span,
        "with_regions_page_number_count": with_region_page,
        "with_any_page_metadata_count": with_any_page,
        "uncovered_count": uncovered,
        "uncovered_rate": _rate(uncovered, section_count),
        "page_span_coverage": _rate(with_page_span, section_count),
        "regions_page_number_coverage": _rate(with_region_page, section_count),
        "any_page_metadata_coverage": _rate(with_any_page, section_count),
        "malformed_counts": dict(sorted(malformed.items())),
        "ok": not malformed,
        "page_aware_capable": with_any_page > 0 and not malformed,
        "page_metadata_capability": (
            PAGE_AWARE_CAPABLE if with_any_page > 0 and not malformed else PAGE_BLIND
        ),
        "privacy": {
            "aggregate_only": True,
            "omits_raw_text": True,
            "omits_doc_ids": True,
            "omits_chunk_ids": True,
            "omits_file_names": True,
            "omits_source_paths": True,
        },
    }
    if malformed:
        detail = ", ".join(f"{key}={value}" for key, value in sorted(malformed.items()))
        raise PageMetadataContractError(
            f"parser page metadata contract failed: {detail}",
            report,
        )
    return report
