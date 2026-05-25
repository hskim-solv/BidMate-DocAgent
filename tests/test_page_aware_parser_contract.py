from __future__ import annotations

import json
from pathlib import Path

import pytest

from parser_page_metadata_contract import (
    ADAPTER_SPIKE_REQUIRED,
    PAGE_AWARE_CAPABLE,
    PAGE_BLIND,
    PageMetadataContractError,
    classify_parser_source_group,
    validate_page_metadata_sections,
)
from rag_indexing import build_chunks, normalize_json_document


ROOT_DIR = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT_DIR / "eval" / "fixtures" / "page_aware_parser_contract"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_valid_page_span_passes() -> None:
    report = validate_page_metadata_sections(
        [{"heading": "Scope", "text": "Synthetic text.", "page_span": [1, 2]}],
        source_group="pdf/visual_parsing_v2/public_synthetic_page_contract",
    )

    assert report["ok"] is True
    assert report["section_count"] == 1
    assert report["with_page_span_count"] == 1
    assert report["with_any_page_metadata_count"] == 1
    assert report["page_aware_capable"] is True
    assert report["page_metadata_capability"] == PAGE_AWARE_CAPABLE


def test_invalid_page_span_fails_loudly_without_raw_values() -> None:
    with pytest.raises(PageMetadataContractError) as exc_info:
        validate_page_metadata_sections(
            [
                {
                    "heading": "Synthetic heading must not leak",
                    "text": "SYNTHETIC_SNIPPET_SHOULD_NOT_LEAK",
                    "doc_id": "synthetic-doc-id-should-not-leak",
                    "chunk_id": "synthetic-chunk-id-should-not-leak",
                    "source_path": "synthetic-source.pdf",
                    "file_name": "synthetic-source.pdf",
                    "page_span": [3, 1],
                }
            ],
            source_group="synthetic-source.pdf",
        )

    message = str(exc_info.value)
    encoded_report = json.dumps(exc_info.value.report, ensure_ascii=False)
    assert "invalid_page_span=1" in message
    assert exc_info.value.report["source_group"] == "<redacted_source_group>"
    for forbidden in (
        "SYNTHETIC_SNIPPET_SHOULD_NOT_LEAK",
        "synthetic-doc-id-should-not-leak",
        "synthetic-chunk-id-should-not-leak",
        "synthetic-source.pdf",
    ):
        assert forbidden not in message
        assert forbidden not in encoded_report


def test_region_page_outside_page_span_fails() -> None:
    with pytest.raises(PageMetadataContractError) as exc_info:
        validate_page_metadata_sections(
            [
                {
                    "heading": "Region",
                    "text": "Synthetic text.",
                    "page_span": [2, 2],
                    "regions": [{"page_number": 3}],
                }
            ]
        )

    assert exc_info.value.report["malformed_counts"] == {
        "region_page_outside_page_span": 1
    }


def test_missing_page_metadata_is_allowed_and_counted_uncovered() -> None:
    report = validate_page_metadata_sections(
        [
            {"heading": "Body", "text": "Synthetic text without page metadata."},
            {"heading": "Scope", "text": "Synthetic text.", "page_span": [1, 1]},
        ]
    )

    assert report["ok"] is True
    assert report["section_count"] == 2
    assert report["with_any_page_metadata_count"] == 1
    assert report["uncovered_count"] == 1
    assert report["uncovered_rate"] == 0.5


def test_region_page_number_must_be_int_when_present() -> None:
    with pytest.raises(PageMetadataContractError) as exc_info:
        validate_page_metadata_sections(
            [
                {
                    "heading": "Region",
                    "text": "Synthetic text.",
                    "regions": [{"page_number": "2"}],
                }
            ]
        )

    assert exc_info.value.report["malformed_counts"] == {
        "invalid_region_page_number": 1
    }


def test_source_group_capability_classification() -> None:
    assert (
        classify_parser_source_group(
            file_format="pdf",
            text_source="visual_parsing_v2",
            document_type="visual_parsing_v2",
            any_page_metadata_coverage=1.0,
        )
        == PAGE_AWARE_CAPABLE
    )
    assert (
        classify_parser_source_group(
            file_format="hwp",
            text_source="kordoc",
            document_type="private_pdf_hwp_csv_text",
        )
        == ADAPTER_SPIKE_REQUIRED
    )
    assert (
        classify_parser_source_group(
            file_format="pdf",
            text_source="data_list_csv_text",
            document_type="private_pdf_hwp_csv_text",
        )
        == PAGE_BLIND
    )


def test_public_fixture_roundtrip_preserves_page_metadata() -> None:
    payload = _load_fixture("valid_sections.json")
    report = validate_page_metadata_sections(payload["sections"])
    document = normalize_json_document(payload, FIXTURE_DIR / "valid_sections.json")
    chunks = build_chunks([document], chunking_strategy="section", max_chars=1000)

    assert report["with_page_span_count"] == 1
    assert report["with_regions_page_number_count"] == 1
    assert chunks[0]["page_span"] == [1, 2]
    assert chunks[1]["page_span"] == [3, 3]
    assert chunks[1]["regions"][0]["page_number"] == 3
    assert chunks[1]["regions"][0]["bbox"] == [10.0, 20.0, 110.0, 160.0]


@pytest.mark.parametrize(
    ("fixture_name", "malformed_key"),
    [
        ("invalid_page_span.json", "invalid_page_span"),
        ("invalid_region_outside_span.json", "region_page_outside_page_span"),
    ],
)
def test_malformed_public_fixtures_fail(fixture_name: str, malformed_key: str) -> None:
    payload = _load_fixture(fixture_name)

    with pytest.raises(PageMetadataContractError) as exc_info:
        validate_page_metadata_sections(payload["sections"])

    assert exc_info.value.report["malformed_counts"][malformed_key] == 1
