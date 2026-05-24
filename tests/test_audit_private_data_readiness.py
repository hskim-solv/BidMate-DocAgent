from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
import yaml

from scripts.audit_private_data_readiness import (
    DEFAULT_CONFIG,
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


def _make_legacy_real_config_fixture(tmp_path: Path) -> Path:
    files_dir = tmp_path / "data" / "files"
    index_dir = tmp_path / "data" / "index" / "real100"
    report_dir = tmp_path / "reports" / "real100"
    eval_dir = tmp_path / "eval"
    files_dir.mkdir(parents=True)
    index_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    eval_dir.mkdir()
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
    (tmp_path / "data" / "data_list.csv").write_text(
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
    (index_dir / "index.json").write_text(
        json.dumps(
            {
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
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (report_dir / "eval_summary.json").write_text(
        json.dumps(
            {
                "chunk_recall_at_5": 0.5,
                "chunk_recall_at_10": 0.5,
                "chunk_mrr_at_5": 0.5,
                "chunk_ndcg_at_5": 0.5,
                "failure_category_counts": {"retrieval_miss": 1, "unknown": 0},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config_path = eval_dir / "real_config.local.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "mode": "rag",
                "index_dir": "data/index/real100",
                "cases": [
                    {
                        "id": "q1",
                        "query": "private question placeholder",
                        "query_type": "single_doc",
                        "expected_doc_ids": ["notice-a"],
                        "expected_terms": ["Budget"],
                        "answerable": True,
                    },
                    {
                        "id": "q2",
                        "query": "private unanswerable placeholder",
                        "query_type": "abstention",
                        "expected_doc_ids": [],
                        "expected_terms": [],
                        "answerable": False,
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
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


def test_readiness_audit_accepts_legacy_real_config_local_cases(tmp_path: Path) -> None:
    config_path = _make_legacy_real_config_fixture(tmp_path)
    out_dir = tmp_path.parent / f"{tmp_path.name}-readiness-audit"

    summary, flags, _ = build_readiness_audit(config_path, out_dir, repo_root=tmp_path)

    assert flags == []
    assert summary["ready_for_improvement"] is True
    assert summary["config_format"] == "real_config_local_cases"
    assert summary["parse_quality"]["document_count"] == 2
    assert summary["eval_dataset_quality"]["question_count"] == 2
    assert summary["eval_dataset_quality"]["answerable_without_gold_evidence_count"] == 0
    assert summary["eval_dataset_quality"]["gold_chunk_missing_from_index_count"] == 0
    assert summary["baseline_metric_validity"]["metrics_source"] == "eval_summary_json"
    assert summary["failure_taxonomy_readiness"]["source"] == (
        "eval_summary_failure_category_counts"
    )


def test_readiness_audit_reports_page_metadata_go_fixture(tmp_path: Path) -> None:
    config_path = _make_legacy_real_config_fixture(tmp_path)
    index_path = tmp_path / "data" / "index" / "real100" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["documents"] = [
        {"doc_id": "notice-a", "page_span": [1, 1]},
        {"doc_id": "notice-b", "page_span": [2, 2]},
    ]
    index["parent_sections"] = [
        {"section_id": "notice-a::section-001", "doc_id": "notice-a", "page_span": [1, 1]},
        {"section_id": "notice-b::section-001", "doc_id": "notice-b", "page_span": [2, 2]},
    ]
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "reports" / "private_real_eval_summary.redacted.json").write_text(
        json.dumps(
            {
                "comparison_table": [
                    {"citation_accuracy": 0.25},
                    {"citation_accuracy": 0.75},
                ]
            }
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path.parent / f"{tmp_path.name}-page-go-audit"

    summary, flags, report = build_readiness_audit(config_path, out_dir, repo_root=tmp_path)

    assert flags == []
    page = summary["index_integrity"]["page_metadata"]
    assert page["citation_page_claim_go_no_go"] == "GO"
    assert page["chunk"]["any_page_metadata_coverage"] == 1.0
    assert page["parent_section"]["any_page_metadata_coverage"] == 1.0
    assert page["source_groups"][0]["page_span_coverage"] == 1.0
    relation = summary["baseline_metric_validity"]["citation_page_relationship"]
    assert relation["redacted_summary_citation_accuracy"]["mean"] == 0.5
    assert "Page citation/page claim: `GO`" in report


def test_readiness_audit_reports_page_metadata_no_go_by_source(tmp_path: Path) -> None:
    config_path = _make_legacy_real_config_fixture(tmp_path)
    index_path = tmp_path / "data" / "index" / "real100" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    for chunk in index["chunks"]:
        chunk.pop("page_span", None)
        chunk["metadata"] = {
            "document_type": "private_pdf_hwp_csv_text",
            "text_source": "kordoc",
            "file_format": "hwp",
        }
        chunk["chunking_strategy"] = "fixed"
    index["parent_sections"] = [
        {
            "section_id": "synthetic-parent",
            "metadata": {
                "document_type": "private_pdf_hwp_csv_text",
                "text_source": "kordoc",
                "file_format": "hwp",
            },
            "chunking_strategy": "fixed",
        }
    ]
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    eval_summary_path = tmp_path / "reports" / "real100" / "eval_summary.json"
    eval_summary_path.write_text(
        json.dumps(
            {
                "chunk_recall_at_5": 0.5,
                "chunk_recall_at_10": 0.5,
                "chunk_mrr_at_5": 0.5,
                "chunk_ndcg_at_5": 0.5,
                "case_results": [
                    {
                        "citation_precision": 1.0,
                        "claim_citation_alignment": 1.0,
                        "citation_page_precision": None,
                        "citation_region_precision": None,
                    },
                    {
                        "citation_precision": 0.0,
                        "claim_citation_alignment": 0.5,
                        "citation_page_precision": None,
                        "citation_region_precision": None,
                    },
                ],
                "failure_category_counts": {"retrieval_miss": 1, "unknown": 0},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "reports" / "private_real_eval_summary.redacted.json").write_text(
        json.dumps({"comparison_table": [{"citation_accuracy": 0.25}]}),
        encoding="utf-8",
    )
    out_dir = tmp_path.parent / f"{tmp_path.name}-page-no-go-audit"

    summary, flags, report = build_readiness_audit(config_path, out_dir, repo_root=tmp_path)

    assert "page_metadata_missing" in _flag_codes(flags)
    page = summary["index_integrity"]["page_metadata"]
    assert page["citation_page_claim_go_no_go"] == "NO-GO"
    assert page["recoverability"] == "not_recoverable_from_current_index"
    assert page["chunk"]["missing_page_metadata_rate"] == 1.0
    assert page["document"]["any_page_metadata_coverage"] == 0.0
    assert page["parent_section"]["any_page_metadata_coverage"] == 0.0
    assert page["source_groups"] == [
        {
            "document_type": "private_pdf_hwp_csv_text",
            "text_source": "kordoc",
            "file_format": "hwp",
            "chunking_strategy": "fixed",
            "doc_count": 2,
            "chunk_count": 2,
            "any_page_metadata_coverage": 0.0,
            "page_span_coverage": 0.0,
            "regions_page_number_coverage": 0.0,
        }
    ]
    relation = summary["baseline_metric_validity"]["citation_page_relationship"]
    assert relation["case_results_with_any_page_metadata_count"] == 0
    assert relation["metrics"]["citation_precision"]["mean"] == 0.5
    assert relation["metrics"]["claim_citation_alignment"]["mean"] == 0.75
    assert relation["metrics"]["citation_page_precision"]["mean"] is None
    assert relation["redacted_summary_citation_accuracy"]["mean"] == 0.25
    assert "Page citation/page claim: `NO-GO`" in report
    assert_public_safe_payload(summary)


def test_readiness_summary_schema_and_outputs(tmp_path: Path) -> None:
    config_path = _make_fixture(tmp_path)
    out_dir = tmp_path / "audit"

    summary, flags, report = build_readiness_audit(config_path, out_dir)
    write_outputs(out_dir, summary, flags, report)

    assert summary["schema_version"] == 1
    assert summary["audit_type"] == "private_data_readiness"
    assert summary["benchmark_type"] == "private_real_eval"
    assert summary["config_format"] == "private_real_eval_path_config"
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
    assert DEFAULT_CONFIG == "eval/real_config.local.yaml"
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
