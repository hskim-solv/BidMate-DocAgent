from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from eval.naive_rag import private_real_eval as pre


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_private_real_eval_template_schema() -> None:
    config = yaml.safe_load(
        (REPO_ROOT / "configs" / "eval" / "private_real_eval.template.yaml").read_text(
            encoding="utf-8"
        )
    )

    pre.validate_template_schema(config)

    assert config["benchmark_type"] == "private_real_eval"
    assert config["not_ci_smoke"] is True
    assert config["is_private_data"] is True
    assert int(config["top_k"]) >= 10
    assert "retrieval" in config["metrics"]
    assert "answer_control" in config["metrics"]


def _is_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", path],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    candidate = REPO_ROOT / path
    for parent in [candidate, *candidate.parents]:
        try:
            rel = parent.relative_to(REPO_ROOT)
        except ValueError:
            break
        if str(rel) == ".":
            break
        if parent.is_symlink():
            return _is_ignored(str(rel))
    return False


def test_private_local_configs_and_data_paths_are_gitignored() -> None:
    ignored_paths = [
        "configs/eval/private_real_eval.local.yaml",
        "eval/real_config.local.yaml",
        "data/private/files/private.pdf",
        "data/private/data_list.csv",
        "data/private/gold_evidence.jsonl",
        "data/private/index/index.json",
        "data/files/private.pdf",
        "data/files_kordoc/private.json",
        "data/data_list.csv",
        "data/index/private-real/index.json",
        "data/index/real221/index.json",
        "experiments/private_runs/run/metrics.json",
        "reports/real100/eval_summary.json",
        "reports/real221/eval_summary.json",
    ]

    missing = [path for path in ignored_paths if not _is_ignored(path)]

    assert missing == []


def test_private_runner_fails_clearly_when_private_files_missing(tmp_path: Path) -> None:
    config_path = tmp_path / "private_real_eval.local.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "benchmark_type": "private_real_eval",
                "not_ci_smoke": True,
                "is_private_data": True,
                "documents_dir": "data/private/missing/files",
                "data_list_path": "data/private/missing/data_list.csv",
                "gold_evidence_path": "data/private/missing/gold_evidence.jsonl",
                "index_dir": "data/private/missing/index",
                "output_dir": "experiments/private_runs/missing",
                "top_k": 10,
                "metrics": {
                    "retrieval": ["recall_at_5"],
                    "citation": ["citation_accuracy"],
                    "answer_control": ["unanswerable_detection_flag"],
                },
                "latency_scope": "private_runner_wall_clock",
                "answer_metric_mode": "deterministic_contract_v1",
                "redaction_policy": {"summary_only": True},
                "minimums": {
                    "min_documents": 1,
                    "min_questions": 1,
                    "min_answerable_questions": 1,
                    "min_unanswerable_questions": 0,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "python3",
            "-m",
            "eval.naive_rag.private_real_eval",
            "--config",
            str(config_path),
            "--validate-only",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Private real-eval validation failed" in result.stderr
    assert "missing_required_input: documents_dir" in result.stderr
    assert "missing_required_input: data_list_path" in result.stderr
    assert "missing_required_input: gold_evidence_path" in result.stderr
    assert str(REPO_ROOT) not in result.stderr
    assert "data/private" not in result.stderr


def test_private_runner_requires_private_inputs_to_be_gitignored() -> None:
    config = {
        "benchmark_type": "private_real_eval",
        "not_ci_smoke": True,
        "is_private_data": True,
        "documents_dir": "docs",
        "data_list_path": "docs/not_ignored_data_list.csv",
        "gold_evidence_path": "docs/not_ignored_gold_evidence.jsonl",
        "questions_path": "docs/not_ignored_gold_evidence.jsonl",
        "index_dir": "data/private/index",
        "output_dir": "experiments/private_runs/not_ignored_guard",
        "top_k": 10,
        "metrics": {
            "retrieval": ["recall_at_5"],
            "citation": ["citation_accuracy"],
            "answer_control": ["unanswerable_detection_flag"],
        },
        "latency_scope": "private_runner_wall_clock",
        "answer_metric_mode": "deterministic_contract_v1",
        "redaction_policy": {"summary_only": True},
        "minimums": {
            "min_documents": 1,
            "min_questions": 1,
            "min_answerable_questions": 1,
            "min_unanswerable_questions": 0,
        },
    }

    with pytest.raises(pre.PrivateRealEvalError) as exc_info:
        pre.validate_private_inputs(config)

    message = str(exc_info.value)
    assert "private_path_not_gitignored: documents_dir" in message
    assert "private_path_not_gitignored: data_list_path" in message
    assert "private_path_not_gitignored: gold_evidence_path" in message
    assert "private_path_not_gitignored: questions_path" in message
    assert str(REPO_ROOT) not in message


def test_private_runner_reports_label_gaps_without_private_ids(tmp_path: Path) -> None:
    docs_dir = tmp_path / "files"
    docs_dir.mkdir()
    (docs_dir / "private.pdf").write_text("placeholder", encoding="utf-8")
    data_list = tmp_path / "data_list.csv"
    data_list.write_text("placeholder\n", encoding="utf-8")
    gold = tmp_path / "gold_evidence.jsonl"
    gold.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "question_id": "PRIVATE-QID-001",
                        "question": "PRIVATE RAW QUESTION",
                        "answerable": True,
                        "gold_evidence": [],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "question_id": "PRIVATE-QID-002",
                        "question": "PRIVATE RAW UNANSWERABLE",
                        "answerable": False,
                        "gold_evidence": [
                            {"doc_id": "PRIVATE-DOC", "chunk_id": "PRIVATE-CHUNK"}
                        ],
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config = {
        "benchmark_type": "private_real_eval",
        "not_ci_smoke": True,
        "is_private_data": True,
        "documents_dir": str(docs_dir),
        "data_list_path": str(data_list),
        "gold_evidence_path": str(gold),
        "questions_path": str(gold),
        "index_dir": str(tmp_path / "index"),
        "output_dir": str(tmp_path / "runs"),
        "top_k": 10,
        "metrics": {
            "retrieval": ["recall_at_5"],
            "citation": ["citation_accuracy"],
            "answer_control": ["unanswerable_detection_flag"],
        },
        "latency_scope": "private_runner_wall_clock",
        "answer_metric_mode": "deterministic_contract_v1",
        "redaction_policy": {"summary_only": True},
        "minimums": {
            "min_documents": 1,
            "min_questions": 1,
            "min_answerable_questions": 1,
            "min_unanswerable_questions": 0,
        },
    }

    with pytest.raises(pre.PrivateRealEvalError) as exc_info:
        pre.validate_private_inputs(config)

    message = str(exc_info.value)
    assert "missing_explicit_gold_chunk_id: answerable_questions count=1" in message
    assert "unanswerable_gold_evidence_not_empty: questions count=1" in message
    assert "PRIVATE-QID" not in message
    assert "PRIVATE-DOC" not in message
    assert "PRIVATE-CHUNK" not in message
    assert "PRIVATE RAW" not in message


def test_answerable_strings_are_parsed_strictly() -> None:
    questions = pre._questions_from_rows(
        [
            {"question_id": "q1", "question": "Answerable?", "answerable": "true"},
            {"question_id": "q2", "question": "Unanswerable?", "answerable": "false"},
        ]
    )

    assert [question["answerable"] for question in questions] == [True, False]

    with pytest.raises(pre.PrivateRealEvalError, match="answerable must be a boolean"):
        pre._questions_from_rows(
            [{"question_id": "q3", "question": "Ambiguous?", "answerable": "no"}]
        )


def test_document_count_follows_private_symlink_layout(tmp_path: Path) -> None:
    source = tmp_path / "source-files"
    source.mkdir()
    (source / "one.pdf").write_text("placeholder", encoding="utf-8")
    linked = tmp_path / "data" / "private" / "files"
    linked.parent.mkdir(parents=True)
    linked.symlink_to(source, target_is_directory=True)

    assert pre._count_documents(linked) == 1


def test_redacted_summary_excludes_private_raw_fields() -> None:
    metrics_payload = {
        "dataset": {
            "num_questions": 2,
            "answerable_count": 1,
            "unanswerable_count": 1,
            "questions_path": "data/private/gold_evidence.jsonl",
        },
        "retrieval_metrics": {"recall_at_5": {"mean": 0.5, "n": 1, "missing": 0}},
        "answer_metrics": {
            "citation_accuracy": {"mean": 0.5, "n": 1, "missing": 0},
            "answer_text": "PRIVATE RAW ANSWER",
        },
        "failure_counts": {
            "retrieval_failure.gold_evidence_not_in_top_k": 1,
            "path": 1,
            "/Users/example/private/file.pdf": 1,
            "unsafe": "data/private/file.pdf",
        },
        "case_results": [
            {
                "question": "PRIVATE RAW QUESTION",
                "answer": "PRIVATE RAW ANSWER",
                "retrieved_chunks": [{"text_preview": "PRIVATE DOC TEXT"}],
            }
        ],
    }
    validation = {
        "document_count": 3,
        "question_count": 2,
        "answerable_count": 1,
        "unanswerable_count": 1,
        "index_dir": REPO_ROOT / "does-not-exist",
    }
    config = {"top_k": 10, "latency_scope": "private_runner_wall_clock"}

    summary = pre.build_redacted_summary(metrics_payload, validation, config, elapsed_ms=123.4)
    rendered = json.dumps(summary, ensure_ascii=False)

    assert "PRIVATE RAW QUESTION" not in rendered
    assert "PRIVATE RAW ANSWER" not in rendered
    assert "PRIVATE DOC TEXT" not in rendered
    assert "questions_path" not in rendered
    assert "answer_text" not in rendered
    assert "retrieved_chunks" not in rendered
    assert "/Users/example" not in rendered
    assert "data/private" not in rendered
    assert '"path"' not in rendered
    assert "retrieval_failure.gold_evidence_not_in_top_k" in rendered
    assert summary["index_provenance"] == {}


def test_redacted_summary_rejects_path_like_values() -> None:
    with pytest.raises(pre.PrivateRealEvalError, match="forbidden private fields"):
        pre.assert_redacted_summary_safe({"safe_key": "/Users/example/private/file.pdf"})


def test_index_embedding_summary_is_aggregate_only(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    (index_dir / "index.json").write_text(
        json.dumps(
            {
                "embedding": {
                    "backend": "hashing",
                    "dimension": 384,
                    "model": "/Users/example/private/model",
                },
                "build": {
                    "num_chunks": 26,
                    "generated_at": "2026-05-24T00:00:00+00:00",
                },
            }
        ),
        encoding="utf-8",
    )

    assert pre._index_embedding_summary(index_dir) == {
        "embedding_backend": "hashing",
        "embedding_dimension": 384,
        "chunk_count": 26,
        "generated_at": "2026-05-24T00:00:00+00:00",
    }


def test_redacted_summary_includes_semantic_provenance_and_comparison(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    (index_dir / "index.json").write_text(
        json.dumps(
            {
                "embedding": {
                    "backend": "sentence-transformers",
                    "model": pre.PREFERRED_SEMANTIC_MODEL,
                    "dimension": 384,
                },
                "build": {
                    "num_documents": 100,
                    "num_chunks": 26376,
                    "generated_at": "2026-05-24T00:00:00+00:00",
                },
            }
        ),
        encoding="utf-8",
    )
    metrics_payload = {
        "dataset": {"num_questions": 217, "answerable_count": 114, "unanswerable_count": 103},
        "retrieval_metrics": {
            "recall_at_5": {"mean": 0.1, "n": 114, "missing": 103},
            "recall_at_10": {"mean": 0.2, "n": 114, "missing": 103},
            "mrr_at_5": {"mean": 0.3, "n": 114, "missing": 103},
            "ndcg_at_5": {"mean": 0.4, "n": 114, "missing": 103},
        },
        "answer_metrics": {
            "citation_accuracy": {"mean": 0.5, "n": 114, "missing": 103},
            "answer_relevancy": {"mean": 0.6, "n": 114, "missing": 103},
            "faithfulness": {"mean": 0.7, "n": 114, "missing": 103},
            "unanswerable_detection_flag": {"mean": 0.8, "n": 103, "missing": 114},
        },
        "failure_counts": {"retrieval_failure.gold_evidence_not_in_top_k": 1},
    }
    validation = {
        "document_count": 100,
        "question_count": 217,
        "answerable_count": 114,
        "unanswerable_count": 103,
        "index_dir": index_dir,
    }
    config = {"top_k": 10, "latency_scope": "private_runner_wall_clock"}
    hashing_summary = {
        "benchmark_type": "private_real_eval",
        "dataset": {"num_questions": 217},
        "index_provenance": {
            "embedding_backend": "hashing",
            "model": "local-hashing-bow",
            "embedding_dimension": 384,
            "chunk_count": 26376,
            "generated_at": "2026-05-23T00:00:00+00:00",
        },
        "metrics": {"retrieval": {"recall_at_5": {"mean": 0.05}}},
        "latency_summary": {"mean_wall_clock_ms_per_question": 621.58},
    }

    summary = pre.build_redacted_summary(
        metrics_payload,
        validation,
        config,
        elapsed_ms=2000.0,
        comparison_summary=hashing_summary,
    )

    assert summary["index_provenance"] == {
        "embedding_backend": "sentence-transformers",
        "model": pre.PREFERRED_SEMANTIC_MODEL,
        "embedding_dimension": 384,
        "chunk_count": 26376,
        "generated_at": "2026-05-24T00:00:00+00:00",
    }
    assert summary["claim_readiness"]["status"] == "claim-ready"
    assert [row["workflow"] for row in summary["comparison_table"]] == [
        "hashing workflow-validation run",
        "semantic dense baseline run",
    ]
    rendered = json.dumps(summary, ensure_ascii=False)
    assert "doc_id" not in rendered
    assert "chunk_id" not in rendered


def test_public_smoke_and_synthetic_configs_remain_unaffected() -> None:
    public_contract = yaml.safe_load(
        (REPO_ROOT / "configs" / "eval" / "rag_quality_v1.yaml").read_text(encoding="utf-8")
    )
    smoke_config = yaml.safe_load((REPO_ROOT / "eval" / "config.yaml").read_text(encoding="utf-8"))
    registry = json.loads((REPO_ROOT / "benchmarks" / "registry.json").read_text(encoding="utf-8"))

    assert public_contract["name"] == "rag_quality_v1"
    assert public_contract["pipeline"]["name"] == "naive_baseline"
    assert public_contract["pipeline"]["retrieval_backend"] == "dense"
    assert any(run.get("name") == "naive_baseline" for run in smoke_config["ablation_runs"])
    assert "private_real_eval" not in json.dumps(registry)
