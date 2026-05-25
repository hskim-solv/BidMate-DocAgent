from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from rag_indexing import build_chunks
from scripts.page_metadata_recovery_audit import (
    build_audit_report,
    readiness_checks,
    render_markdown,
)


ROOT_DIR = Path(__file__).resolve().parents[1]


def _write_index(index_dir: Path, payload: dict) -> None:
    index_dir.mkdir(parents=True)
    (index_dir / "index.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _base_index(chunks: list[dict], parent_sections: list[dict] | None = None) -> dict:
    return {
        "schema_version": 2,
        "mode": "rag",
        "documents": [
            {
                "doc_id": "doc-a",
                "title": "redacted synthetic",
                "metadata": {
                    "file_format": "hwp",
                    "text_source": "kordoc",
                    "document_type": "private_pdf_hwp_csv_text",
                },
            }
        ],
        "parent_sections": parent_sections or [],
        "chunks": chunks,
    }


def test_page_aware_sections_pass_page_metadata_to_chunks() -> None:
    chunks = build_chunks(
        [
            {
                "doc_id": "visual-doc",
                "title": "visual fixture",
                "agency": "",
                "project": "",
                "metadata": {"file_format": "pdf", "text_source": "visual_parsing_v2"},
                "sections": [
                    {
                        "heading": "Scope",
                        "section_path": ["Scope"],
                        "text": "Page-aware section text.",
                        "page_span": [2, 3],
                        "regions": [
                            {
                                "page_number": 2,
                                "bbox": [10.0, 20.0, 100.0, 120.0],
                                "source": "pdf_text_layer",
                            }
                        ],
                    }
                ],
            }
        ],
        chunking_strategy="section",
    )

    assert chunks[0]["page_span"] == [2, 3]
    assert chunks[0]["regions"][0]["page_number"] == 2
    assert chunks[0]["regions"][0]["bbox"] == [10.0, 20.0, 100.0, 120.0]


def test_no_page_metadata_reports_no_go_and_parser_change(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    _write_index(
        index_dir,
        _base_index(
            [
                {
                    "chunk_id": "doc-a::chunk-001",
                    "doc_id": "doc-a",
                    "chunking_strategy": "fixed",
                    "metadata": {
                        "file_format": "hwp",
                        "text_source": "kordoc",
                        "document_type": "private_pdf_hwp_csv_text",
                    },
                }
            ],
            parent_sections=[
                {
                    "section_id": "doc-a::section-001",
                    "doc_id": "doc-a",
                    "chunking_strategy": "fixed",
                    "metadata": {
                        "file_format": "hwp",
                        "text_source": "kordoc",
                        "document_type": "private_pdf_hwp_csv_text",
                    },
                }
            ],
        ),
    )

    report = build_audit_report(index_dir)

    assert report["decision"]["citation_page_claim_go_no_go"] == "NO-GO"
    assert report["decision"]["recoverability"] == "not_recoverable_from_existing_artifacts"
    assert report["decision"]["requires_reindex"] is True
    assert report["decision"]["requires_parser_change"] is True
    assert report["decision"]["recommendation"] == "full re-index"
    assert report["index"]["source_groups"][0]["decision"] == "requires_page_aware_hwp_parser_change"
    assert report["index"]["source_groups"][0]["any_page_metadata_coverage"] == 0.0
    matrix_row = report["implementation_matrix"][0]
    assert matrix_row["source_type"] == "hwp_via_kordoc"
    assert matrix_row["current_coverage"] == 0.0
    assert matrix_row["recoverable"] is False
    assert matrix_row["requires_parser_change"] is True
    assert matrix_row["requires_reindex"] is True
    assert report["readiness_checks"]["page_metadata_coverage_gt_0"] is False
    assert report["readiness_checks"]["aggregate_only_outputs"] is True


def test_source_group_uses_document_metadata_for_missing_chunk_fields(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    _write_index(
        index_dir,
        _base_index(
            [
                {
                    "chunk_id": "doc-a::chunk-001",
                    "doc_id": "doc-a",
                    "chunking_strategy": "fixed",
                    "metadata": {"file_format": "hwp"},
                }
            ]
        ),
    )

    report = build_audit_report(index_dir)

    group = report["index"]["source_groups"][0]
    assert group["file_format"] == "hwp"
    assert group["text_source"] == "kordoc"
    assert group["document_type"] == "private_pdf_hwp_csv_text"
    assert group["decision"] == "requires_page_aware_hwp_parser_change"


def test_reindex_only_group_does_not_force_parser_change(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    _write_index(
        index_dir,
        {
            "schema_version": 2,
            "mode": "rag",
            "documents": [{"doc_id": "doc-a", "metadata": {}}],
            "parent_sections": [],
            "chunks": [
                {
                    "chunk_id": "doc-a::chunk-001",
                    "doc_id": "doc-a",
                    "chunking_strategy": "fixed",
                    "metadata": {},
                }
            ],
        },
    )

    report = build_audit_report(index_dir)

    assert report["index"]["source_groups"][0]["decision"] == "requires_page_aware_reindex"
    assert report["decision"]["requires_reindex"] is True
    assert report["decision"]["requires_parser_change"] is False


def test_nonzero_source_group_page_coverage_enables_page_claim_scope(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    _write_index(
        index_dir,
        _base_index(
            [
                {
                    "chunk_id": "doc-a::chunk-001",
                    "doc_id": "doc-a",
                    "chunking_strategy": "section",
                    "page_span": [4, 4],
                    "regions": [{"page_number": 4, "bbox": [1, 2, 3, 4]}],
                    "metadata": {
                        "file_format": "pdf",
                        "text_source": "visual_parsing_v2",
                        "document_type": "visual_parsing_v2",
                    },
                }
            ]
        ),
    )

    report = build_audit_report(index_dir)

    assert report["decision"]["citation_page_claim_go_no_go"] == "GO"
    assert report["decision"]["page_claim_scope"] == "covered_source_groups_only"
    assert report["decision"]["recoverability"] == "recoverable_from_current_index"
    assert report["decision"]["recommendation"] == "lightweight metadata recovery"
    assert report["index"]["source_groups"][0]["regions_page_number_coverage"] == 1.0
    assert report["implementation_matrix"][0]["source_type"] == "existing_index_with_page_fields"
    assert report["implementation_matrix"][0]["recoverable"] is True
    assert report["implementation_matrix"][0]["requires_reindex"] is False
    assert report["readiness_checks"]["page_metadata_coverage_gt_0"] is True
    assert report["readiness_checks"]["chunk_page_span_integrity"]["ok"] is True


def test_readiness_flags_invalid_page_span_integrity(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    _write_index(
        index_dir,
        _base_index(
            [
                {
                    "chunk_id": "doc-a::chunk-001",
                    "doc_id": "doc-a",
                    "chunking_strategy": "section",
                    "page_span": [5, 4],
                    "regions": [{"page_number": 6, "bbox": [1, 2, 3, 4]}],
                    "metadata": {
                        "file_format": "pdf",
                        "text_source": "visual_parsing_v2",
                        "document_type": "visual_parsing_v2",
                    },
                },
                {
                    "chunk_id": "doc-a::chunk-002",
                    "doc_id": "doc-a",
                    "chunking_strategy": "section",
                    "page_span": [2, 3],
                    "regions": [{"page_number": 4, "bbox": [1, 2, 3, 4]}],
                    "metadata": {
                        "file_format": "pdf",
                        "text_source": "visual_parsing_v2",
                        "document_type": "visual_parsing_v2",
                    },
                },
            ]
        ),
    )

    report = build_audit_report(index_dir)
    integrity = report["readiness_checks"]["chunk_page_span_integrity"]

    assert integrity["checked_count"] == 2
    assert integrity["invalid_page_span_count"] == 1
    assert integrity["region_outside_page_span_count"] == 1
    assert integrity["ok"] is False
    assert report["readiness_checks"]["citation_renderer_compatible"] is False


def test_aggregate_report_omits_private_text_filenames_and_paths(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    cache_dir = tmp_path / "files_kordoc"
    cache_dir.mkdir()
    secret_filename = "private_agency_secret.pdf"
    secret_text = "SECRET_PRIVATE_SNIPPET page-break SHOULD_NOT_LEAK"
    (cache_dir / "private_agency_secret.md").write_text(secret_text, encoding="utf-8")
    (cache_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {
                    "private_agency_secret": {
                        "source_relpath": secret_filename,
                        "source_sha256": "abc123",
                        "source_size": 123,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    _write_index(
        index_dir,
        _base_index(
            [
                {
                    "chunk_id": "doc-a::chunk-001",
                    "doc_id": "doc-a",
                    "chunking_strategy": "fixed",
                    "text": secret_text,
                    "metadata": {
                        "file_format": "pdf",
                        "text_source": "kordoc",
                        "document_type": "private_pdf_hwp_csv_text",
                        "file_name": secret_filename,
                    },
                }
            ]
        ),
    )

    report = build_audit_report(index_dir, kordoc_cache_dir=cache_dir)
    encoded = json.dumps(report, ensure_ascii=False)

    assert "SECRET_PRIVATE_SNIPPET" not in encoded
    assert "SHOULD_NOT_LEAK" not in encoded
    assert secret_filename not in encoded
    assert str(tmp_path) not in encoded
    assert "doc-a::chunk-001" not in encoded
    assert report["privacy"]["aggregate_only"] is True
    assert report["privacy"]["omits_chunk_ids"] is True
    assert report["artifacts"]["kordoc_cache"]["markdown_has_page_markers"] is True
    assert report["artifacts"]["kordoc_cache"]["manifest_entry_key_counts"]["source_relpath"] == 1


def test_readiness_checks_scan_payload_for_private_path_values(tmp_path: Path) -> None:
    report_payload = {
        "privacy": {"aggregate_only": True, "omits_source_paths": True},
        "future_field": str(tmp_path / "private_agency_secret.pdf"),
    }

    checks = readiness_checks([], report_payload)

    assert checks["aggregate_only_outputs"] is True
    assert checks["no_private_path_leakage"] is False


def test_markdown_and_cli_emit_aggregate_decision(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    out_dir = tmp_path / "out"
    _write_index(
        index_dir,
        _base_index(
            [
                {
                    "chunk_id": "doc-a::chunk-001",
                    "doc_id": "doc-a",
                    "chunking_strategy": "fixed",
                    "metadata": {
                        "file_format": "hwp",
                        "text_source": "data_list_csv_text",
                        "document_type": "private_pdf_hwp_csv_text",
                    },
                }
            ]
        ),
    )

    report = build_audit_report(index_dir)
    markdown = render_markdown(report)
    assert "Citation page claim: `NO-GO`" in markdown
    assert "requires_raw_source_reparse" in markdown
    assert "## Implementation Matrix" in markdown
    assert "## Readiness Checks" in markdown
    assert markdown.rstrip().endswith("`full re-index`")
    assert report["decision"]["requires_parser_change"] is False
    assert report["implementation_matrix"][0]["source_type"] == "csv_text_fallback"
    assert report["implementation_matrix"][0]["requires_reindex"] is True

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT_DIR / "scripts" / "page_metadata_recovery_audit.py"),
            "--index-dir",
            str(index_dir),
            "--output-dir",
            str(out_dir),
            "--format",
            "markdown",
        ],
        cwd=ROOT_DIR,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Citation page claim: `NO-GO`" in completed.stdout
    assert completed.stdout.rstrip().endswith("`full re-index`")
    assert (out_dir / "page_metadata_recovery_audit.json").is_file()
    assert (out_dir / "page_metadata_recovery_audit.md").is_file()
