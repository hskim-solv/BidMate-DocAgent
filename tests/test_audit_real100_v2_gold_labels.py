from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts import audit_real100_v2_gold_labels as audit
from scripts.private_data_quality_audit_utils import assert_public_safe, forbidden_output_hits


PRIVATE_DOC = "PRIVATE-DOC-001"
PRIVATE_BOILERPLATE = "PRIVATE-DOC-001::boilerplate"
PRIVATE_BODY = "PRIVATE-DOC-001::body"
PRIVATE_SUPPORT = "예산 10억원 평가 90점"
PRIVATE_QUESTION = "PRIVATE-Q-001"


def _write_index(index_dir: Path) -> None:
    index_dir.mkdir(parents=True)
    payload = {
        "schema_version": 2,
        "documents": [{"doc_id": PRIVATE_DOC, "title": "PRIVATE TITLE"}],
        "chunks": [
            {
                "doc_id": PRIVATE_DOC,
                "chunk_id": PRIVATE_BOILERPLATE,
                "text": "표지 목차 기관 안내 boilerplate",
                "page_span": [1, 1],
            },
            {
                "doc_id": PRIVATE_DOC,
                "chunk_id": PRIVATE_BODY,
                "text": f"본문 요구사항 {PRIVATE_SUPPORT} 제출 마감",
                "page_span": [5, 5],
            },
        ],
    }
    (index_dir / "index.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_config(path: Path, *, chunk_id: str = PRIVATE_BOILERPLATE) -> None:
    payload = {
        "cases": [
            {
                "id": PRIVATE_QUESTION,
                "gold_evidence": [
                    {
                        "doc_id": PRIVATE_DOC,
                        "chunk_id": chunk_id,
                        "support_text": PRIVATE_SUPPORT,
                        "required_terms": ["예산", "평가"],
                        "support_claim": "PRIVATE CLAIM",
                    }
                ],
            },
            {
                "id": "PRIVATE-Q-002",
                "gold_evidence": [
                    {
                        "doc_id": PRIVATE_DOC,
                        "chunk_id": PRIVATE_BODY,
                        "support_text": PRIVATE_SUPPORT,
                        "required_terms": ["예산"],
                    }
                ],
            },
        ]
    }
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _write_canonical(path: Path) -> None:
    rows = [
        {
            "question_id": PRIVATE_QUESTION,
            "gold_evidence": [
                {
                    "doc_id": PRIVATE_DOC,
                    "chunk_id": PRIVATE_BODY,
                    "support_text": PRIVATE_SUPPORT,
                    "support_claim": "PRIVATE CLAIM",
                }
            ],
        },
        {
            "question_id": "PRIVATE-Q-002",
            "gold_evidence": [
                {"doc_id": PRIVATE_DOC, "chunk_id": PRIVATE_BODY, "support_text": PRIVATE_SUPPORT}
            ],
        },
    ]
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_gold_label_audit_detects_boilerplate_label_without_raw_leak(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    config = tmp_path / "real_config_v2.local.yaml"
    canonical = tmp_path / "gold_evidence.jsonl"
    out_dir = tmp_path / "audit"
    _write_index(index_dir)
    _write_config(config)
    _write_canonical(canonical)

    summary = audit.run_audit(
        config_path=config,
        index_dir=index_dir,
        canonical_gold_path=canonical,
        out_dir=out_dir,
        config_label="synthetic_config",
        index_label="synthetic_index",
        canonical_label="synthetic_canonical",
    )

    assert summary["schema_version"] == 1
    assert summary["audit_type"] == "real100_v2_gold_label_audit"
    assert summary["surface"] == "real100_v2"
    assert summary["passed"] is False
    assert summary["index_label_alignment"]["support_anchor_checked_count"] == 2
    assert summary["index_label_alignment"]["support_anchor_observed_count"] == 1
    assert summary["index_label_alignment"]["support_anchor_uncovered_count"] == 1
    assert summary["index_label_alignment"]["support_anchor_found_elsewhere_same_document_count"] == 1
    assert summary["index_label_alignment"]["required_terms_full_covered_count"] == 1
    assert summary["canonical_alignment"]["checked"] is True
    assert summary["canonical_alignment"]["mismatched_case_count"] == 1
    assert summary["flag_counts"]["error"] == 0
    assert summary["flag_counts"]["warning"] >= 2
    assert forbidden_output_hits(summary) == {}
    assert_public_safe(summary)

    flags = _read_jsonl(out_dir / "gold_label_audit.flags.jsonl")
    assert {flag["flag_type"] for flag in flags} >= {
        "support_anchor_not_observed_in_labelled_chunk",
        "required_terms_not_fully_observed_in_labelled_chunk",
        "inline_canonical_gold_mismatch",
    }
    for flag in flags:
        assert forbidden_output_hits(flag) == {}
        assert_public_safe(flag)

    serialized = (
        json.dumps(summary, ensure_ascii=False)
        + json.dumps(flags, ensure_ascii=False)
        + (out_dir / "gold_label_audit.report.md").read_text(encoding="utf-8")
    )
    for private_value in (PRIVATE_DOC, PRIVATE_BOILERPLATE, PRIVATE_BODY, PRIVATE_SUPPORT, PRIVATE_QUESTION):
        assert private_value not in serialized
    assert "support_text" not in serialized
    assert "chunk_id" not in serialized
    assert "doc_id" not in serialized


def test_gold_label_audit_passes_when_inline_labels_match_index_and_canonical(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    config = tmp_path / "real_config_v2.local.yaml"
    canonical = tmp_path / "gold_evidence.jsonl"
    out_dir = tmp_path / "audit"
    _write_index(index_dir)
    _write_config(config, chunk_id=PRIVATE_BODY)
    _write_canonical(canonical)

    summary = audit.run_audit(
        config_path=config,
        index_dir=index_dir,
        canonical_gold_path=canonical,
        out_dir=out_dir,
        config_label="synthetic_config",
        index_label="synthetic_index",
        canonical_label="synthetic_canonical",
    )

    assert summary["passed"] is True
    assert summary["index_label_alignment"]["support_anchor_uncovered_count"] == 0
    assert summary["canonical_alignment"]["mismatched_case_count"] == 0
    assert summary["flag_counts"] == {"error": 0, "warning": 0, "emitted": 0, "emission_cap": audit.MAX_FLAGS}


def test_gold_label_audit_flags_absent_chunk_labels(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    config = tmp_path / "real_config_v2.local.yaml"
    out_dir = tmp_path / "audit"
    _write_index(index_dir)
    _write_config(config, chunk_id="PRIVATE-DOC-001::missing")

    summary = audit.run_audit(
        config_path=config,
        index_dir=index_dir,
        out_dir=out_dir,
        config_label="synthetic_config",
        index_label="synthetic_index",
    )

    assert summary["passed"] is False
    assert summary["index_label_alignment"]["absent_chunk_label_count"] == 1
    assert summary["flag_counts"]["error"] == 1
    flags = _read_jsonl(out_dir / "gold_label_audit.flags.jsonl")
    assert any(flag["flag_type"] == "inline_chunk_label_absent_from_index" for flag in flags)
    assert "PRIVATE-DOC-001::missing" not in json.dumps(flags, ensure_ascii=False)
