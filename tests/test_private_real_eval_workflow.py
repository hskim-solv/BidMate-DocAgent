from __future__ import annotations

import json
import subprocess
from pathlib import Path

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
    return result.returncode == 0


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
                "documents_dir": "data/private/files",
                "data_list_path": "data/private/data_list.csv",
                "gold_evidence_path": "data/private/gold_evidence.jsonl",
                "index_dir": "data/private/index",
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
    assert "documents_dir does not exist" in result.stderr
    assert "data_list_path does not exist" in result.stderr
    assert "gold_evidence_path does not exist" in result.stderr


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
        "failure_counts": {"retrieval_failure.gold_evidence_not_in_top_k": 1},
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
