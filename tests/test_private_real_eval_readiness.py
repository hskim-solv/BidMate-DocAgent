from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
import yaml

from scripts._governance import (
    find_redacted_summary_forbidden_fields,
    private_real_eval_gitignore_violations,
)
from scripts.export_private_real_eval_summary import export_summary
from scripts.real_eval_paths import privacy_guard_violations


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "eval" / "real_config.template.yaml"


def test_private_real_config_template_exists_and_pins_naive_contract() -> None:
    payload = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))

    assert payload["eval_type"] == "private_real_eval"
    assert payload["benchmark_type"] == "private_real_eval"
    assert payload["baseline_system"] == "naive_rag"
    assert payload["not_ci_smoke"] is True
    assert payload["is_private_data"] is True
    for key in (
        "documents_dir",
        "data_list_path",
        "questions_path",
        "gold_evidence_path",
        "index_dir",
        "output_dir",
        "redacted_summary_path",
        "top_k",
        "metrics",
        "answer_metric_mode",
        "latency_scope",
        "privacy_policy",
    ):
        assert key in payload


def test_private_local_paths_are_gitignored_and_redacted_summary_is_allowlisted() -> None:
    assert private_real_eval_gitignore_violations(str(ROOT)) == {}
    assert privacy_guard_violations(ROOT) == {}


@pytest.mark.parametrize(
    "path",
    [
        "eval/real_config.local.yaml",
        "configs/eval/private_real_eval.local.yaml",
        "data/files/example.pdf",
        "data/files_kordoc/example.pdf",
        "data/private/questions.jsonl",
        "data/data_list.csv",
        "data/index/real100/index.json",
        "data/index/real100_kordoc/index.json",
        "data/index-private-hardcase/index.json",
        "experiments/private_runs/run/metrics.json",
        "reports/real100/eval_summary.json",
        "reports/real100/raw/cases.jsonl",
        "reports/private_real_eval_summary.raw.json",
    ],
)
def test_private_data_index_and_raw_output_paths_are_gitignored(path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", path],
        cwd=ROOT,
        text=True,
    )
    assert result.returncode == 0, path


def test_redacted_summary_path_is_not_gitignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", "reports/private_real_eval_summary.redacted.json"],
        cwd=ROOT,
        text=True,
    )
    assert result.returncode == 1


def test_readiness_validator_fails_clearly_when_private_files_are_missing(tmp_path: Path) -> None:
    local_config = tmp_path / "real_config.local.yaml"
    local_config.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")

    result = subprocess.run(
        [
            "python3",
            "scripts/check_private_real_eval_readiness.py",
            "--config",
            str(local_config),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "B. Config ready, data missing" in result.stdout
    assert "documents_dir_missing" in result.stdout
    assert "No private raw" not in result.stdout
    assert "support_text" in result.stdout


def _clean_metrics() -> dict:
    return {
        "run_id": "run_001",
        "dataset": {
            "num_questions": 13,
            "answerable_count": 10,
            "unanswerable_count": 3,
        },
        "retrieval_metrics": {
            "recall_at_10": {"mean": 0.5, "n": 10, "missing": 3},
        },
        "answer_metrics": {
            "faithfulness": {"mean": 0.4, "n": 10, "missing": 3},
            "answer_relevancy": {"mean": 0.3, "n": 10, "missing": 3},
            "citation_accuracy": {"mean": 0.2, "n": 10, "missing": 3},
            "hallucination_flag": {"mean": 0.1, "n": 13, "missing": 0},
            "unanswerable_detection_flag": {"mean": 1.0, "n": 3, "missing": 10},
        },
        "failure_counts": {
            "retrieval_failure.gold_evidence_not_in_top_k": 2,
        },
    }


def test_redacted_summary_exporter_rejects_unsafe_fields(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    unsafe = _clean_metrics()
    unsafe["question"] = "PLACEHOLDER raw question must not export"
    (run_dir / "metrics.json").write_text(json.dumps(unsafe), encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden raw/private keys"):
        export_summary(run_dir, tmp_path / "summary.redacted.json")


def test_redacted_summary_exporter_writes_aggregate_only_payload(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "metrics.json").write_text(json.dumps(_clean_metrics()), encoding="utf-8")
    out = tmp_path / "private_real_eval_summary.redacted.json"

    payload = export_summary(run_dir, out)

    assert out.is_file()
    assert payload["eval_type"] == "private_real_eval"
    assert payload["baseline_system"] == "naive_rag"
    assert payload["run_id"].startswith("redacted_")
    assert payload["run_id"] != "run_001"
    assert payload["run_id_redacted"] is True
    assert "question_count" in payload
    assert find_redacted_summary_forbidden_fields(payload) == {}


def test_governance_redacted_summary_scanner_flags_forbidden_keys() -> None:
    found = find_redacted_summary_forbidden_fields(
        {
            "question": "PLACEHOLDER",
            "nested": {"support_text": "PLACEHOLDER"},
            "path": "/Users/example/private/file.pdf",
        }
    )
    assert found["question"] == 1
    assert found["support_text"] == 1
    assert found["absolute_path_value"] == 1


def test_private_real_eval_workflow_doc_exists_with_required_wording() -> None:
    text = (ROOT / "docs" / "evaluation" / "private_real_eval_workflow.md").read_text(
        encoding="utf-8"
    )
    assert "Smoke eval is CI/regression only." in text
    assert "Synthetic benchmark is public reproducibility and ablation only." in text
    assert "Private real-eval is required for credible real-world baseline claims." in text
    assert "No private raw content should be committed." in text
    assert "Redacted aggregate summaries may be committed only if they pass privacy checks." in text
    assert "No Naive RAG real baseline has been measured yet." in text


def test_smoke_and_synthetic_benchmark_configs_remain_unaffected() -> None:
    rag_quality = yaml.safe_load((ROOT / "configs" / "eval" / "rag_quality_v1.yaml").read_text())
    assert rag_quality["index_dir"] == "data/index"
    assert rag_quality["questions_path"] == "data/eval/rag_questions.jsonl"
    assert rag_quality["gold_evidence_path"] == "data/eval/gold_evidence.jsonl"
    assert rag_quality["output_root"] == "experiments/runs"

    eval_config = yaml.safe_load((ROOT / "eval" / "config.yaml").read_text())
    runs = eval_config.get("ablation_runs") or []
    assert any(run.get("name") == "naive_baseline" for run in runs if isinstance(run, dict))
