from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from eval.naive_rag.benchmark import REQUIRED_OUTPUTS, run_from_config as run_benchmark_from_config
from eval.naive_rag.build_benchmark_index import build_benchmark_index
from eval.naive_rag.run_eval import load_contract_config
from eval.naive_rag.validate_benchmark_dataset import validate_dataset


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_CONFIG = ROOT / "configs" / "eval" / "benchmark_naive_rag_v1.yaml"
SMOKE_CONFIG = ROOT / "configs" / "eval" / "rag_quality_v1.yaml"


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_temp_benchmark_config(tmp_path: Path, *, index_dir: Path) -> Path:
    config = _yaml(BENCHMARK_CONFIG)
    config["index_dir"] = str(index_dir)
    config["output_root"] = str(tmp_path / "runs")
    config_path = tmp_path / "benchmark_naive_rag_v1.yaml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return config_path


def test_benchmark_config_pins_naive_dense_only_without_optimizations() -> None:
    config = load_contract_config(BENCHMARK_CONFIG)
    pipeline = config["pipeline"]

    assert pipeline["name"] == "naive_baseline"
    assert pipeline["top_k"] == 10
    assert pipeline["retrieval_backend"] == "dense"
    assert pipeline["metadata_first"] is False
    assert pipeline["rerank"] is False
    assert pipeline["verifier_retry"] is False
    assert pipeline["query_expansion"] == "identity"


def test_benchmark_eval_is_separate_from_smoke_eval() -> None:
    benchmark = _yaml(BENCHMARK_CONFIG)
    smoke = _yaml(SMOKE_CONFIG)

    assert benchmark["benchmark_type"] == "naive_rag_benchmark"
    assert benchmark["benchmark_version"] == "v1"
    assert benchmark["not_ci_smoke"] is True
    assert benchmark["corpus_path"] == "data/eval/benchmark/corpus_chunks_v1.jsonl"
    assert benchmark["index_dir"] == "data/eval/benchmark/index_v1"
    assert benchmark["corpus_dir"] == "data/eval/benchmark/corpus"
    assert benchmark["questions_path"] == "data/eval/benchmark/rag_questions_v1.jsonl"
    assert benchmark["gold_evidence_path"] == "data/eval/benchmark/gold_evidence_v1.jsonl"

    assert smoke["index_dir"] == "data/index"
    assert smoke["questions_path"] == "data/eval/rag_questions.jsonl"
    assert smoke["gold_evidence_path"] == "data/eval/gold_evidence.jsonl"
    assert benchmark["index_dir"] != smoke["index_dir"]
    assert benchmark["questions_path"] != smoke["questions_path"]


def test_placeholder_answer_metrics_are_not_named_as_semantic_claims() -> None:
    config = _yaml(BENCHMARK_CONFIG)
    answer_metrics = config["metrics"]["answer"]
    display_names = config["metric_display_names"]["answer"]

    assert "faithfulness" not in answer_metrics
    assert "answer_relevancy" not in answer_metrics
    assert display_names["rule_based_groundedness"] == "provisional citation-in-retrieved-context check"
    assert display_names["term_coverage_accuracy"] == "provisional expected-term lexical coverage check"
    assert "semantic Faithfulness" not in repr(display_names)
    assert "semantic Answer Relevancy" not in repr(display_names)


def test_benchmark_dataset_validator_reports_counts() -> None:
    summary = validate_dataset(BENCHMARK_CONFIG)
    dataset = summary["dataset_summary"]

    assert summary["errors"] == []
    assert dataset["corpus_path"] == "data/eval/benchmark/corpus_chunks_v1.jsonl"
    assert dataset["num_docs"] == 6
    assert dataset["num_chunks"] == 72
    assert dataset["num_questions"] == 55
    assert dataset["answerable_count"] == 40
    assert dataset["unanswerable_count"] == 15
    assert summary["gold_evidence_summary"]["num_evidence_records"] == 47


def test_benchmark_dataset_validator_reports_corpus_only_index_boundary() -> None:
    summary = validate_dataset(BENCHMARK_CONFIG)
    boundary = summary["index_build_boundary"]

    assert summary["errors"] == []
    assert boundary["status"] == "pass"
    assert boundary["surface"] == "public_synthetic_benchmark"
    assert boundary["input_kind"] == "corpus_chunks_jsonl"
    assert boundary["allowed_input_path"] == "data/eval/benchmark/corpus_chunks_v1.jsonl"
    assert boundary["configured_input_path"] == "data/eval/benchmark/corpus_chunks_v1.jsonl"
    assert boundary["input_matches_corpus_path"] is True
    assert boundary["command_uses_corpus_path"] is True
    assert boundary["command_references_question_or_gold_paths"] is False
    assert boundary["corpus_rows_with_query_or_gold_fields"] == 0
    assert boundary["prohibited_corpus_fields_detected"] == []


def test_benchmark_dataset_validator_rejects_index_build_from_questions(tmp_path: Path) -> None:
    config = _yaml(BENCHMARK_CONFIG)
    config["index_build"]["input_path"] = config["questions_path"]
    config_path = tmp_path / "benchmark_naive_rag_v1.yaml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    summary = validate_dataset(config_path)

    assert summary["index_build_boundary"]["status"] == "fail"
    assert "index_build.input_path must match corpus_path" in summary["errors"]


def test_benchmark_dataset_validator_parses_actual_corpus_arg(tmp_path: Path) -> None:
    config = _yaml(BENCHMARK_CONFIG)
    config["index_build"]["command"] = (
        "python3 -m eval.naive_rag.build_benchmark_index "
        f"--corpus {config['questions_path']} "
        f"--note {config['corpus_path']} "
        "--output data/eval/benchmark/index_v1"
    )
    config_path = tmp_path / "benchmark_naive_rag_v1.yaml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    summary = validate_dataset(config_path)

    assert summary["index_build_boundary"]["status"] == "fail"
    assert summary["index_build_boundary"]["command_uses_corpus_path"] is False
    assert summary["index_build_boundary"]["command_corpus_args"] == [
        "data/eval/benchmark/rag_questions_v1.jsonl"
    ]
    assert (
        "index_build.command must pass exactly one --corpus argument matching corpus_path"
        in summary["errors"]
    )


def test_benchmark_dataset_validator_rejects_label_fields_in_corpus_chunks(tmp_path: Path) -> None:
    source = ROOT / "data" / "eval" / "benchmark" / "corpus_chunks_v1.jsonl"
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    rows[0]["expected_answer"] = "leaked label"
    contaminated = tmp_path / "corpus_chunks_v1.jsonl"
    contaminated.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    config = _yaml(BENCHMARK_CONFIG)
    config["corpus_path"] = str(contaminated)
    config["index_build"]["input_path"] = str(contaminated)
    config["index_build"]["command"] = (
        "python3 -m eval.naive_rag.build_benchmark_index "
        f"--corpus {contaminated} --output data/eval/benchmark/index_v1"
    )
    config_path = tmp_path / "benchmark_naive_rag_v1.yaml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    summary = validate_dataset(config_path)
    boundary = summary["index_build_boundary"]

    assert boundary["status"] == "fail"
    assert boundary["corpus_rows_with_query_or_gold_fields"] == 1
    assert boundary["prohibited_corpus_fields_detected"] == ["expected_answer"]
    assert "corpus_path rows must not contain query/gold label fields" in summary["errors"]


def test_benchmark_index_can_be_built_from_corpus_chunks_v1(tmp_path: Path) -> None:
    output_dir = tmp_path / "index_v1"
    build_benchmark_index(
        ROOT / "data" / "eval" / "benchmark" / "corpus_chunks_v1.jsonl",
        output_dir,
    )

    index_path = output_dir / "index.json"
    assert index_path.is_file()
    assert (output_dir / "embeddings.npy").is_file()
    index = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    assert index["build"]["input_kind"] == "corpus_chunks_jsonl"
    assert index["build"]["num_chunks"] == 72
    assert index["build"]["leakage_guard"] == "query_and_gold_label_files_not_read"


def test_benchmark_index_build_does_not_persist_questions_or_gold_labels(tmp_path: Path) -> None:
    output_dir = tmp_path / "index_v1"
    build_benchmark_index(
        ROOT / "data" / "eval" / "benchmark" / "corpus_chunks_v1.jsonl",
        output_dir,
    )

    index_text = (output_dir / "index.json").read_text(encoding="utf-8")
    assert "brag_q" not in index_text
    assert "brag_ev" not in index_text
    assert "expected_answer" not in index_text
    assert "expected_terms" not in index_text
    assert "gold_evidence" not in index_text


def test_benchmark_runner_fails_when_index_v1_is_missing(tmp_path: Path) -> None:
    config_path = _write_temp_benchmark_config(tmp_path, index_dir=tmp_path / "missing_index_v1")

    with pytest.raises(FileNotFoundError, match="Build it with"):
        run_benchmark_from_config(config_path)


def test_benchmark_runner_writes_required_artifacts(tmp_path: Path) -> None:
    index_dir = tmp_path / "index_v1"
    build_benchmark_index(
        ROOT / "data" / "eval" / "benchmark" / "corpus_chunks_v1.jsonl",
        index_dir,
    )
    config_path = _write_temp_benchmark_config(tmp_path, index_dir=index_dir)

    output_dir = run_benchmark_from_config(
        config_path,
        run_id_override="pytest-naive-rag-benchmark-v1",
    )

    for name in REQUIRED_OUTPUTS:
        assert (output_dir / name).is_file(), name

    metrics = yaml.safe_load((output_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["benchmark_type"] == "naive_rag_benchmark"
    assert metrics["benchmark_version"] == "v1"
    assert metrics["dataset"]["chunk_count"] == 72
    assert set(metrics["retrieval_metrics"]) >= {"recall_at_5", "recall_at_10", "mrr_at_5", "ndcg_at_5"}
    assert set(metrics["citation_page_metrics"]) >= {
        "citation_chunk_accuracy",
        "citation_page_coverage",
        "citation_page_precision",
        "missing_page_number_rate",
        "page_metadata_coverage",
    }
    assert set(metrics["rule_based_answer_metrics"]) >= {
        "rule_based_groundedness",
        "term_coverage_accuracy",
        "failed_abstention_rate",
        "unsafe_answer_rate",
    }
    assert metrics["latency_metrics"]["benchmark_excludes_setup_costs"] is True
    assert metrics["latency_metrics"]["generation_latency_ms"] is None
    assert "semantic Faithfulness" not in repr(metrics["metric_labels"])
    assert "semantic Answer Relevancy" not in repr(metrics["metric_labels"])


def test_benchmark_result_report_contains_conservative_warnings() -> None:
    report = ROOT / "docs" / "evaluation" / "naive_rag_benchmark_v1_results.md"
    text = report.read_text(encoding="utf-8")

    assert "synthetic-public" in text
    assert "not sufficient for performance claims" in text
    assert "Latency Scope Warning" in text
    assert "Rule-Based" in text
