from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts import audit_private_eval_dataset as eval_audit
from scripts import audit_private_parse_quality as parse_audit
from scripts.private_data_quality_audit_utils import (
    AuditPrivacyError,
    assert_public_safe,
    forbidden_output_hits,
)


FORBIDDEN_RAW_KEYS = {
    "question",
    "answer",
    "answer_text",
    "gold_evidence",
    "retrieved_chunks",
    "text",
    "text_preview",
    "doc_id",
    "chunk_id",
    "file_name",
    "path",
}


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_index(index_dir: Path) -> None:
    index_dir.mkdir(parents=True)
    payload = {
        "schema_version": 2,
        "mode": "rag",
        "embedding": {"backend": "hashing", "dimension": 384, "storage": "sidecar_npy"},
        "build": {"num_documents": 1, "num_chunks": 1},
        "documents": [
            {
                "doc_id": "PRIVATE-DOC-001",
                "title": "PRIVATE TITLE",
                "agency": "PRIVATE AGENCY",
                "project": "PRIVATE PROJECT",
                "metadata": {},
            }
        ],
        "chunks": [
            {
                "doc_id": "PRIVATE-DOC-001",
                "chunk_id": "PRIVATE-DOC-001::chunk-001",
                "title": "PRIVATE TITLE",
                "section": "본문",
                "metadata": {},
                "page_span": [1, 1],
                "embedding_idx": 0,
                "text": "PRIVATE RAW EVIDENCE 예산 10억원, 평가점수 90점.",
            }
        ],
    }
    (index_dir / "index.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_parse_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    docs_dir = tmp_path / "files"
    docs_dir.mkdir()
    (docs_dir / "secret-private-file.pdf").write_text("placeholder", encoding="utf-8")
    data_list = tmp_path / "data_list.csv"
    with data_list.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["doc_id", "file_path"])
        writer.writeheader()
        writer.writerow({"doc_id": "PRIVATE-DOC-001", "file_path": "secret-private-file.pdf"})
    index_dir = tmp_path / "index"
    _write_index(index_dir)
    return docs_dir, data_list, index_dir


def _write_valid_eval_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    index_dir = tmp_path / "index"
    _write_index(index_dir)
    questions = tmp_path / "questions.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    _write_jsonl(
        questions,
        [
            {
                "question_id": "PRIVATE-Q-001",
                "question": "PRIVATE RAW QUESTION 예산은?",
                "answerable": True,
                "expected_terms": ["예산"],
                "query_type": "single_doc",
            },
            {
                "question_id": "PRIVATE-Q-002",
                "question": "PRIVATE RAW QUESTION 없는 항목은?",
                "answerable": False,
                "query_type": "abstention",
            },
        ],
    )
    _write_jsonl(
        evidence,
        [
            {
                "question_id": "PRIVATE-Q-001",
                "gold_evidence": [
                    {
                        "doc_id": "PRIVATE-DOC-001",
                        "chunk_id": "PRIVATE-DOC-001::chunk-001",
                        "required_terms": ["예산"],
                        "support_text": "PRIVATE RAW EVIDENCE 예산 10억원",
                    }
                ],
            },
            {"question_id": "PRIVATE-Q-002", "gold_evidence": []},
        ],
    )
    return questions, evidence, index_dir


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def test_public_safe_guard_rejects_forbidden_private_keys() -> None:
    for key in FORBIDDEN_RAW_KEYS:
        with pytest.raises(AuditPrivacyError):
            assert_public_safe({key: "PRIVATE"})


def test_parse_quality_summary_schema_and_privacy(tmp_path: Path) -> None:
    docs_dir, data_list, index_dir = _write_parse_inputs(tmp_path)
    out_dir = tmp_path / "audit"

    summary = parse_audit.run_audit(
        documents_dir=docs_dir,
        data_list=data_list,
        index_dir=index_dir,
        out_dir=out_dir,
    )

    assert summary["schema_version"] == 1
    assert summary["audit_type"] == "private_parse_quality"
    assert summary["total_document_count"] == 1
    assert summary["parse_success_count"] == 1
    assert summary["parse_failure_count"] == 0
    assert summary["chunk_count"] == 1
    assert "chunk_length_chars" in summary
    assert forbidden_output_hits(summary) == {}

    report = (out_dir / "parse_quality_report.md").read_text(encoding="utf-8")
    flags = _read_jsonl(out_dir / "parse_quality_flags.jsonl")
    serialized = json.dumps(summary, ensure_ascii=False) + report + json.dumps(flags, ensure_ascii=False)
    assert "PRIVATE-DOC-001" not in serialized
    assert "secret-private-file.pdf" not in serialized
    assert "PRIVATE RAW EVIDENCE" not in serialized
    for flag in flags:
        assert forbidden_output_hits(flag) == {}


def test_eval_dataset_summary_schema_and_privacy(tmp_path: Path) -> None:
    questions, evidence, index_dir = _write_valid_eval_inputs(tmp_path)
    out_dir = tmp_path / "audit"

    summary = eval_audit.run_audit(
        questions_path=questions,
        gold_evidence_path=evidence,
        index_dir=index_dir,
        out_dir=out_dir,
    )

    assert summary["schema_version"] == 1
    assert summary["audit_type"] == "private_eval_dataset"
    assert summary["question_count"] == 2
    assert summary["answerable_count"] == 1
    assert summary["unanswerable_count"] == 1
    assert summary["evidence_record_count"] == 1
    assert summary["label_consistency"]["answerable_missing_evidence_count"] == 0
    assert summary["index_reference_coverage"]["absent_chunk_reference_count"] == 0
    assert forbidden_output_hits(summary) == {}

    report = (out_dir / "eval_dataset_report.md").read_text(encoding="utf-8")
    flags = _read_jsonl(out_dir / "eval_dataset_flags.jsonl")
    serialized = json.dumps(summary, ensure_ascii=False) + report + json.dumps(flags, ensure_ascii=False)
    assert "PRIVATE-Q-001" not in serialized
    assert "PRIVATE RAW QUESTION" not in serialized
    assert "PRIVATE RAW EVIDENCE" not in serialized
    assert "PRIVATE-DOC-001" not in serialized
    assert "PRIVATE-DOC-001::chunk-001" not in serialized
    for flag in flags:
        assert forbidden_output_hits(flag) == {}


def test_eval_dataset_fails_when_answerable_has_no_evidence(tmp_path: Path) -> None:
    questions, evidence, index_dir = _write_valid_eval_inputs(tmp_path)
    _write_jsonl(
        evidence,
        [
            {"question_id": "PRIVATE-Q-001", "gold_evidence": []},
            {"question_id": "PRIVATE-Q-002", "gold_evidence": []},
        ],
    )

    summary = eval_audit.run_audit(
        questions_path=questions,
        gold_evidence_path=evidence,
        index_dir=index_dir,
        out_dir=tmp_path / "audit",
    )

    assert summary["passed"] is False
    assert summary["label_consistency"]["answerable_missing_evidence_count"] == 1


def test_eval_dataset_fails_when_unanswerable_has_evidence(tmp_path: Path) -> None:
    questions, evidence, index_dir = _write_valid_eval_inputs(tmp_path)
    _write_jsonl(
        evidence,
        [
            {
                "question_id": "PRIVATE-Q-001",
                "gold_evidence": [
                    {"doc_id": "PRIVATE-DOC-001", "chunk_id": "PRIVATE-DOC-001::chunk-001"}
                ],
            },
            {
                "question_id": "PRIVATE-Q-002",
                "gold_evidence": [
                    {"doc_id": "PRIVATE-DOC-001", "chunk_id": "PRIVATE-DOC-001::chunk-001"}
                ],
            },
        ],
    )

    summary = eval_audit.run_audit(
        questions_path=questions,
        gold_evidence_path=evidence,
        index_dir=index_dir,
        out_dir=tmp_path / "audit",
    )

    assert summary["passed"] is False
    assert summary["label_consistency"]["unanswerable_with_evidence_count"] == 1


def test_eval_dataset_fails_when_chunk_reference_is_missing(tmp_path: Path) -> None:
    questions, evidence, index_dir = _write_valid_eval_inputs(tmp_path)
    _write_jsonl(
        evidence,
        [
            {"question_id": "PRIVATE-Q-001", "gold_evidence": [{"doc_id": "PRIVATE-DOC-001"}]},
            {"question_id": "PRIVATE-Q-002", "gold_evidence": []},
        ],
    )

    summary = eval_audit.run_audit(
        questions_path=questions,
        gold_evidence_path=evidence,
        index_dir=index_dir,
        out_dir=tmp_path / "audit",
    )

    assert summary["passed"] is False
    assert summary["index_reference_coverage"]["missing_chunk_reference_count"] == 1


def test_eval_dataset_fails_when_chunk_reference_is_absent_from_index(tmp_path: Path) -> None:
    questions, evidence, index_dir = _write_valid_eval_inputs(tmp_path)
    _write_jsonl(
        evidence,
        [
            {
                "question_id": "PRIVATE-Q-001",
                "gold_evidence": [
                    {"doc_id": "PRIVATE-DOC-001", "chunk_id": "PRIVATE-DOC-001::missing"}
                ],
            },
            {"question_id": "PRIVATE-Q-002", "gold_evidence": []},
        ],
    )

    summary = eval_audit.run_audit(
        questions_path=questions,
        gold_evidence_path=evidence,
        index_dir=index_dir,
        out_dir=tmp_path / "audit",
    )

    assert summary["passed"] is False
    assert summary["index_reference_coverage"]["absent_chunk_reference_count"] == 1


def test_eval_dataset_fails_on_duplicate_question_identifier(tmp_path: Path) -> None:
    questions, evidence, index_dir = _write_valid_eval_inputs(tmp_path)
    _write_jsonl(
        questions,
        [
            {
                "question_id": "PRIVATE-Q-001",
                "question": "PRIVATE RAW QUESTION A",
                "answerable": True,
            },
            {
                "question_id": "PRIVATE-Q-001",
                "question": "PRIVATE RAW QUESTION B",
                "answerable": True,
            },
        ],
    )

    summary = eval_audit.run_audit(
        questions_path=questions,
        gold_evidence_path=evidence,
        index_dir=index_dir,
        out_dir=tmp_path / "audit",
    )

    assert summary["passed"] is False
    assert summary["question_identifier_uniqueness"]["duplicate_count"] == 1
