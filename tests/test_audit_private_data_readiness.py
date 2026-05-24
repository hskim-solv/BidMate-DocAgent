from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
import yaml

from scripts.audit_private_data_readiness import (
    DEFAULT_OUT_DIR,
    ROOT_DIR,
    assert_public_safe_payload,
    build_readiness_audit,
    is_gitignored_or_outside,
    write_outputs,
)


def _jsonl(rows: list[dict]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)


def _make_fixture(tmp_path: Path) -> Path:
    private_dir = tmp_path / "private"
    files_dir = private_dir / "files"
    index_dir = private_dir / "index"
    output_dir = private_dir / "runs"
    files_dir.mkdir(parents=True)
    index_dir.mkdir()
    output_dir.mkdir()
    (files_dir / "doc_a.pdf").write_text("placeholder", encoding="utf-8")
    (files_dir / "doc_b.pdf").write_text("placeholder", encoding="utf-8")

    long_a = (
        "Budget 100000원 and schedule 2026.05.24 are specified. "
        "| item | score | table | "
        * 20
    )
    long_b = (
        "Evaluation score 90점 and amount 200000원 are present. "
        "The appendix has page metadata. "
        * 20
    )
    data_list = private_dir / "data_list.csv"
    data_list.write_text(
        "\n".join(
            [
                "공고 번호,사업명,발주 기관,파일형식,파일명,텍스트",
                f"notice-a,project-a,agency-a,pdf,doc_a.pdf,{long_a}",
                f"notice-b,project-b,agency-b,pdf,doc_b.pdf,{long_b}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    questions = private_dir / "questions.jsonl"
    questions.write_text(
        _jsonl(
            [
                {
                    "question_id": "q1",
                    "question": "private question placeholder",
                    "answerable": True,
                    "expected_terms": ["Budget"],
                },
                {
                    "question_id": "q2",
                    "question": "private unanswerable placeholder",
                    "answerable": False,
                    "expected_terms": [],
                },
            ]
        ),
        encoding="utf-8",
    )
    gold = private_dir / "gold.jsonl"
    gold.write_text(
        _jsonl(
            [
                {
                    "question_id": "q1",
                    "gold_evidence": [
                        {"doc_id": "notice-a", "chunk_id": "notice-a::chunk-001"}
                    ],
                },
                {"question_id": "q2", "gold_evidence": []},
            ]
        ),
        encoding="utf-8",
    )

    index = {
        "schema_version": 2,
        "mode": "rag",
        "build": {"num_documents": 2, "num_chunks": 2},
        "chunks": [
            {
                "chunk_id": "notice-a::chunk-001",
                "doc_id": "notice-a",
                "text": long_a,
                "page_span": [1, 1],
            },
            {
                "chunk_id": "notice-b::chunk-001",
                "doc_id": "notice-b",
                "text": long_b,
                "page_span": [2, 2],
            },
        ],
    }
    (index_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    run_dir = output_dir / "run-001"
    run_dir.mkdir()
    (run_dir / "metrics.json").write_text(
        json.dumps(
            {
                "retrieval_metrics": {
                    "recall_at_5": {"mean": 0.5, "n": 1, "missing": 0},
                    "recall_at_10": {"mean": 0.5, "n": 1, "missing": 0},
                    "mrr_at_5": {"mean": 0.5, "n": 1, "missing": 0},
                    "ndcg_at_5": {"mean": 0.5, "n": 1, "missing": 0},
                }
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "failure_cases.jsonl").write_text(
        _jsonl([{"failure_type": "retrieval_miss"}]),
        encoding="utf-8",
    )

    config = {
        "benchmark_type": "private_real_eval",
        "not_ci_smoke": True,
        "is_private_data": True,
        "documents_dir": str(files_dir),
        "data_list_path": str(data_list),
        "questions_path": str(questions),
        "gold_evidence_path": str(gold),
        "index_dir": str(index_dir),
        "output_dir": str(output_dir),
        "top_k": 10,
        "metrics": {"retrieval": ["recall_at_10"]},
    }
    config_path = private_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path


def _flag_codes(flags: list[dict]) -> set[str]:
    return {str(flag["code"]) for flag in flags}


def test_public_safe_summary_rejects_forbidden_private_keys() -> None:
    with pytest.raises(ValueError, match="forbidden private fields"):
        assert_public_safe_payload({"doc_id": "private-doc"})

    with pytest.raises(ValueError, match="forbidden private fields"):
        assert_public_safe_payload({"aggregate": {"value": "/Users/example/private.pdf"}})


def test_readiness_audit_duplicate_question_id_fixture_fails(tmp_path: Path) -> None:
    config_path = _make_fixture(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    questions_path = Path(config["questions_path"])
    questions_path.write_text(
        _jsonl(
            [
                {"question_id": "q1", "question": "one", "answerable": True},
                {"question_id": "q1", "question": "two", "answerable": True},
            ]
        ),
        encoding="utf-8",
    )

    summary, flags, _ = build_readiness_audit(config_path, tmp_path / "audit")

    assert summary["ready_for_improvement"] is False
    assert "duplicate_question_id" in _flag_codes(flags)


def test_readiness_audit_answerable_gold_missing_fixture_fails(tmp_path: Path) -> None:
    config_path = _make_fixture(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    Path(config["gold_evidence_path"]).write_text(
        _jsonl(
            [
                {"question_id": "q1", "gold_evidence": []},
                {"question_id": "q2", "gold_evidence": []},
            ]
        ),
        encoding="utf-8",
    )

    summary, flags, _ = build_readiness_audit(config_path, tmp_path / "audit")

    assert summary["ready_for_improvement"] is False
    assert "answerable_without_gold_evidence" in _flag_codes(flags)


def test_readiness_audit_unanswerable_gold_non_empty_fixture_fails(tmp_path: Path) -> None:
    config_path = _make_fixture(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    Path(config["gold_evidence_path"]).write_text(
        _jsonl(
            [
                {
                    "question_id": "q1",
                    "gold_evidence": [
                        {"doc_id": "notice-a", "chunk_id": "notice-a::chunk-001"}
                    ],
                },
                {
                    "question_id": "q2",
                    "gold_evidence": [
                        {"doc_id": "notice-b", "chunk_id": "notice-b::chunk-001"}
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )

    summary, flags, _ = build_readiness_audit(config_path, tmp_path / "audit")

    assert summary["ready_for_improvement"] is False
    assert "unanswerable_with_gold_evidence" in _flag_codes(flags)


def test_readiness_audit_missing_chunk_id_fixture_fails(tmp_path: Path) -> None:
    config_path = _make_fixture(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    Path(config["gold_evidence_path"]).write_text(
        _jsonl(
            [
                {
                    "question_id": "q1",
                    "gold_evidence": [
                        {"doc_id": "notice-a", "chunk_id": "notice-a::chunk-999"}
                    ],
                },
                {"question_id": "q2", "gold_evidence": []},
            ]
        ),
        encoding="utf-8",
    )

    summary, flags, _ = build_readiness_audit(config_path, tmp_path / "audit")

    assert summary["ready_for_improvement"] is False
    assert "gold_chunk_missing_from_index" in _flag_codes(flags)


def test_readiness_audit_missing_documents_dir_fixture_fails(tmp_path: Path) -> None:
    config_path = _make_fixture(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["documents_dir"] = str(tmp_path / "missing-documents")
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    summary, flags, _ = build_readiness_audit(config_path, tmp_path / "audit")

    assert summary["ready_for_improvement"] is False
    assert "documents_dir_missing" in _flag_codes(flags)


def test_readiness_audit_missing_baseline_artifacts_fixture_fails(tmp_path: Path) -> None:
    config_path = _make_fixture(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    for path in Path(config["output_dir"]).rglob("metrics.json"):
        path.unlink()
    for path in Path(config["output_dir"]).rglob("failure_cases.jsonl"):
        path.unlink()

    summary, flags, _ = build_readiness_audit(config_path, tmp_path / "audit")

    assert summary["ready_for_improvement"] is False
    assert "existing_baseline_metrics_missing" in _flag_codes(flags)
    assert "failure_cases_missing" in _flag_codes(flags)


def test_readiness_summary_schema_and_outputs(tmp_path: Path) -> None:
    config_path = _make_fixture(tmp_path)
    out_dir = tmp_path / "audit"

    summary, flags, report = build_readiness_audit(config_path, out_dir)
    write_outputs(out_dir, summary, flags, report)

    assert summary["schema_version"] == 1
    assert summary["audit_type"] == "private_data_readiness"
    assert summary["benchmark_type"] == "private_real_eval"
    assert summary["local_only"] is True
    assert summary["public_safe"] is True
    assert summary["ready_for_improvement"] is True
    assert summary["parse_quality"]["document_count"] == 2
    assert summary["index_integrity"]["chunk_count"] == 2
    assert summary["eval_dataset_quality"]["question_count"] == 2
    assert summary["flags_summary"]["blocker"] == 0
    assert (out_dir / "readiness_summary.json").is_file()
    assert (out_dir / "readiness_report.md").is_file()
    assert (out_dir / "readiness_flags.jsonl").is_file()


def test_default_readiness_audit_output_path_is_gitignored() -> None:
    assert is_gitignored_or_outside(ROOT_DIR / DEFAULT_OUT_DIR)
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "-q",
            "--",
            "experiments/private_runs/readiness_audit/readiness_summary.json",
        ],
        cwd=ROOT_DIR,
        text=True,
        check=False,
    )
    assert result.returncode == 0
