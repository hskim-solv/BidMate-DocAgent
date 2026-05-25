from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from eval.naive_rag.benchmark import (
    MULTI_CHUNK_TOP10_FAILURE_MODE_BUCKETS,
    REQUIRED_OUTPUTS,
    _multi_chunk_evidence_profile_for_case,
    _summarize_multi_chunk_evidence_profiles,
    run_from_config as run_benchmark_from_config,
)
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
    return _write_config(tmp_path, config)


def _write_config(tmp_path: Path, config: dict) -> Path:
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


def test_benchmark_dataset_validator_reports_metadata_and_smoke_boundaries() -> None:
    summary = validate_dataset(BENCHMARK_CONFIG)

    assert summary["errors"] == []
    assert summary["benchmark_metadata"]["status"] == "pass"
    assert summary["benchmark_metadata"]["surface"] == "public_synthetic_benchmark"
    assert summary["benchmark_metadata"]["dataset_id"] == "synthetic_naive_rag_benchmark_v1"
    assert summary["benchmark_metadata"]["privacy"] == "public_synthetic"
    assert summary["benchmark_metadata"]["not_for_claims_mentions_private_real_eval"] is True
    assert summary["smoke_fixture_path_boundary"]["status"] == "pass"
    assert summary["smoke_fixture_path_boundary"]["smoke_fixture_path_matches"] == []


def test_benchmark_dataset_validator_reports_corpus_only_index_boundary() -> None:
    summary = validate_dataset(BENCHMARK_CONFIG)
    boundary = summary["index_build_boundary"]

    assert summary["errors"] == []
    assert boundary["status"] == "pass"
    assert boundary["surface"] == "public_synthetic_benchmark"
    assert boundary["input_kind"] == "corpus_chunks_jsonl"
    assert boundary["allowed_input_path"] == "data/eval/benchmark/corpus_chunks_v1.jsonl"
    assert boundary["configured_input_path"] == "data/eval/benchmark/corpus_chunks_v1.jsonl"
    assert boundary["allowed_output_dir"] == "data/eval/benchmark/index_v1"
    assert boundary["configured_output_dir"] == "data/eval/benchmark/index_v1"
    assert boundary["input_matches_corpus_path"] is True
    assert boundary["output_matches_index_dir"] is True
    assert boundary["command_uses_corpus_path"] is True
    assert boundary["command_writes_index_dir"] is True
    assert boundary["command_references_question_or_gold_paths"] is False
    assert boundary["corpus_rows_with_query_or_gold_fields"] == 0
    assert boundary["prohibited_corpus_fields_detected"] == []


def test_benchmark_dataset_validator_rejects_missing_claim_boundary_metadata(tmp_path: Path) -> None:
    config = _yaml(BENCHMARK_CONFIG)
    del config["dataset_metadata"]["not_for_claims"]
    config["dataset_metadata"]["privacy"] = "public_fixture"
    config_path = _write_config(tmp_path, config)

    summary = validate_dataset(config_path)

    assert summary["benchmark_metadata"]["status"] == "fail"
    assert summary["benchmark_metadata"]["surface"] == "invalid"
    assert "dataset_metadata.privacy must be public_synthetic" in summary["errors"]
    assert (
        "dataset_metadata.not_for_claims must describe disallowed real-world claims"
        in summary["errors"]
    )


def test_benchmark_dataset_validator_rejects_smoke_fixture_paths(tmp_path: Path) -> None:
    config = _yaml(BENCHMARK_CONFIG)
    config["index_dir"] = "data/index"
    config["index_build"]["output_dir"] = "data/index"
    config["index_build"]["command"] = (
        "python3 -m eval.naive_rag.build_benchmark_index "
        f"--corpus {config['corpus_path']} --output data/index"
    )
    config_path = _write_config(tmp_path, config)

    summary = validate_dataset(config_path)

    assert summary["smoke_fixture_path_boundary"]["status"] == "fail"
    assert {
        (match["field"], match["configured_path"], match["blocked_smoke_path"])
        for match in summary["smoke_fixture_path_boundary"]["smoke_fixture_path_matches"]
    } >= {
        ("index_dir", "data/index", "data/index"),
        ("index_build.output_dir", "data/index", "data/index"),
        ("index_build.command", "data/index", "data/index"),
    }
    assert (
        "benchmark paths must not point at public fixture smoke assets: "
        "index_build.command, index_build.output_dir, index_dir"
    ) in summary["errors"]


def test_benchmark_dataset_validator_normalizes_smoke_fixture_paths(tmp_path: Path) -> None:
    config = _yaml(BENCHMARK_CONFIG)
    config["index_dir"] = "data/not_smoke/../index"
    config["index_build"]["output_dir"] = "data/not_smoke/../index"
    config["index_build"]["command"] = (
        "python3 -m eval.naive_rag.build_benchmark_index "
        f"--corpus {config['corpus_path']} --output data/not_smoke/../index"
    )
    config_path = _write_config(tmp_path, config)

    summary = validate_dataset(config_path)

    assert summary["smoke_fixture_path_boundary"]["status"] == "fail"
    assert {
        (match["field"], match["blocked_smoke_path"])
        for match in summary["smoke_fixture_path_boundary"]["smoke_fixture_path_matches"]
    } >= {
        ("index_dir", "data/index"),
        ("index_build.output_dir", "data/index"),
        ("index_build.command", "data/index"),
    }


def test_benchmark_dataset_validator_rejects_smoke_path_in_index_command(tmp_path: Path) -> None:
    config = _yaml(BENCHMARK_CONFIG)
    config["index_build"]["command"] = (
        "python3 -m eval.naive_rag.build_benchmark_index "
        f"--corpus {config['corpus_path']} "
        "--output data/eval/benchmark/index_v1 "
        "--note data/eval/rag_questions.jsonl"
    )
    config_path = _write_config(tmp_path, config)

    summary = validate_dataset(config_path)

    assert summary["smoke_fixture_path_boundary"]["status"] == "fail"
    assert {
        (match["field"], match["configured_path"], match["blocked_smoke_path"])
        for match in summary["smoke_fixture_path_boundary"]["smoke_fixture_path_matches"]
    } == {
        ("index_build.command", "data/eval/rag_questions.jsonl", "data/eval/rag_questions.jsonl")
    }


def test_benchmark_dataset_validator_rejects_index_output_drift(tmp_path: Path) -> None:
    config = _yaml(BENCHMARK_CONFIG)
    config["index_build"]["output_dir"] = "data/eval/benchmark/index_drift"
    config["index_build"]["command"] = (
        "python3 -m eval.naive_rag.build_benchmark_index "
        f"--corpus {config['corpus_path']} --output data/eval/benchmark/index_drift"
    )
    config_path = _write_config(tmp_path, config)

    summary = validate_dataset(config_path)
    boundary = summary["index_build_boundary"]

    assert boundary["status"] == "fail"
    assert boundary["output_matches_index_dir"] is False
    assert boundary["command_writes_index_dir"] is False
    assert "index_build.output_dir must match index_dir" in summary["errors"]
    assert (
        "index_build.command must pass exactly one --output argument matching index_dir"
        in summary["errors"]
    )


def test_benchmark_dataset_validator_rejects_index_build_from_questions(tmp_path: Path) -> None:
    config = _yaml(BENCHMARK_CONFIG)
    config["index_build"]["input_path"] = config["questions_path"]
    config_path = _write_config(tmp_path, config)

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
    config_path = _write_config(tmp_path, config)

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
    config_path = _write_config(tmp_path, config)

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


def test_benchmark_runner_rejects_index_with_mismatched_source_corpus_path(tmp_path: Path) -> None:
    index_dir = tmp_path / "index_v1"
    build_benchmark_index(
        ROOT / "data" / "eval" / "benchmark" / "corpus_chunks_v1.jsonl",
        index_dir,
    )
    index_path = index_dir / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["build"]["source_corpus_path"] = "data/eval/benchmark/rag_questions_v1.jsonl"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    config_path = _write_temp_benchmark_config(tmp_path, index_dir=index_dir)

    with pytest.raises(ValueError, match="source_corpus_path"):
        run_benchmark_from_config(config_path)


def test_benchmark_runner_rejects_index_with_stale_chunk_content(tmp_path: Path) -> None:
    index_dir = tmp_path / "index_v1"
    build_benchmark_index(
        ROOT / "data" / "eval" / "benchmark" / "corpus_chunks_v1.jsonl",
        index_dir,
    )
    index_path = index_dir / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["chunks"][0]["text"] = "stale corpus chunk text"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    config_path = _write_temp_benchmark_config(tmp_path, index_dir=index_dir)

    with pytest.raises(ValueError, match="chunk ids, order, metadata, and text"):
        run_benchmark_from_config(config_path)


def test_benchmark_runner_rejects_index_with_stale_chunk_metadata(tmp_path: Path) -> None:
    index_dir = tmp_path / "index_v1"
    build_benchmark_index(
        ROOT / "data" / "eval" / "benchmark" / "corpus_chunks_v1.jsonl",
        index_dir,
    )
    index_path = index_dir / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["chunks"][0]["metadata"] = {"stale": True}
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    config_path = _write_temp_benchmark_config(tmp_path, index_dir=index_dir)

    with pytest.raises(ValueError, match="chunk ids, order, metadata, and text"):
        run_benchmark_from_config(config_path)


def test_multi_chunk_evidence_profile_distinguishes_failure_modes() -> None:
    same_doc_partial = _multi_chunk_evidence_profile_for_case(
        [
            {"chunk_id": "doc-a::chunk-001", "doc_id": "doc-a"},
            {"chunk_id": "doc-a::chunk-002", "doc_id": "doc-a"},
        ],
        [
            {"chunk_id": "doc-a::chunk-001", "doc_id": "doc-a"},
            {"chunk_id": "doc-b::chunk-001", "doc_id": "doc-b"},
        ]
        + [
            {"chunk_id": f"doc-c::chunk-{idx:03d}", "doc_id": "doc-c"}
            for idx in range(2, 11)
        ],
    )
    cross_doc_distractor = _multi_chunk_evidence_profile_for_case(
        [
            {"chunk_id": "doc-gold::chunk-001", "doc_id": "doc-gold"},
            {"chunk_id": "doc-gold::chunk-002", "doc_id": "doc-gold"},
        ],
        [
            {"chunk_id": f"doc-other::chunk-{idx:03d}", "doc_id": "doc-other"}
            for idx in range(1, 11)
        ],
    )
    not_observable = _multi_chunk_evidence_profile_for_case(
        [
            {"chunk_id": "doc-short::chunk-001", "doc_id": "doc-short"},
            {"chunk_id": "doc-short::chunk-002", "doc_id": "doc-short"},
        ],
        [{"chunk_id": "doc-short::chunk-001", "doc_id": "doc-short"}],
    )
    assert same_doc_partial is not None
    assert cross_doc_distractor is not None
    assert not_observable is not None

    summary = _summarize_multi_chunk_evidence_profiles(
        [same_doc_partial, cross_doc_distractor, not_observable]
    )

    assert same_doc_partial["top10_failure_mode"] == "same_doc_single_gold_hit"
    assert cross_doc_distractor["top10_failure_mode"] == "cross_document_distractor_only"
    assert not_observable["top10_failure_mode"] == "not_observable"
    assert summary["case_count"] == 3
    assert summary["retrieval_outcome_at_10"]["partial_gold_retrieved"] == 1
    assert summary["retrieval_outcome_at_10"]["no_gold_retrieved"] == 1
    assert summary["retrieval_outcome_at_10"]["not_observable"] == 1
    assert summary["top10_failure_count"] == 2
    assert summary["top10_not_observable_count"] == 1
    assert summary["top10_failure_modes"]["same_doc_single_gold_hit"] == 1
    assert summary["top10_failure_modes"]["cross_document_distractor_only"] == 1
    assert summary["top10_failure_modes"]["not_observable"] == 1
    assert set(summary["top10_failure_modes"]) == set(MULTI_CHUNK_TOP10_FAILURE_MODE_BUCKETS)


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

    multi_chunk = metrics["multi_chunk_evidence_profile"]
    assert multi_chunk["case_count"] == 7
    assert multi_chunk["top_k"] == 10
    assert multi_chunk["gold_doc_cardinality"] == {
        "multi_doc": 0,
        "same_doc": 7,
        "unknown": 0,
    }
    assert multi_chunk["retrieval_outcome_at_10"] == {
        "all_gold_retrieved": 6,
        "partial_gold_retrieved": 1,
        "no_gold_retrieved": 0,
        "not_observable": 0,
    }
    assert multi_chunk["top10_failure_count"] == 1
    assert multi_chunk["top10_not_observable_count"] == 0
    assert multi_chunk["top10_failure_modes"]["same_doc_single_gold_hit"] == 1
    assert multi_chunk["top10_failure_modes"]["not_observable"] == 0
    assert set(multi_chunk["top10_failure_modes"]) == set(
        MULTI_CHUNK_TOP10_FAILURE_MODE_BUCKETS
    )


def test_benchmark_result_report_contains_conservative_warnings() -> None:
    report = ROOT / "docs" / "evaluation" / "naive_rag_benchmark_v1_results.md"
    text = report.read_text(encoding="utf-8")

    assert "synthetic-public" in text
    assert "not sufficient for performance claims" in text
    assert "Latency Scope Warning" in text
    assert "Rule-Based" in text
