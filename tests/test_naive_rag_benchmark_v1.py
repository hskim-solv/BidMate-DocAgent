from __future__ import annotations

from pathlib import Path

import yaml

from eval.naive_rag.run_eval import load_contract_config
from eval.naive_rag.validate_benchmark_dataset import validate_dataset


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_CONFIG = ROOT / "configs" / "eval" / "benchmark_naive_rag_v1.yaml"
SMOKE_CONFIG = ROOT / "configs" / "eval" / "rag_quality_v1.yaml"


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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
    assert benchmark["not_ci_smoke"] is True
    assert benchmark["index_dir"] == "data/eval/benchmark/index"
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
    display_names = config["metric_display_names"]["answer"]

    assert display_names["faithfulness"] == "citation-in-retrieved-context placeholder"
    assert display_names["answer_relevancy"] == "expected-answer lexical coverage placeholder"
    assert "semantic Faithfulness" not in repr(display_names)
    assert "semantic Answer Relevancy" not in repr(display_names)


def test_benchmark_index_path_is_ready_and_validator_passes() -> None:
    summary = validate_dataset(BENCHMARK_CONFIG)

    assert summary["errors"] == []
    assert (ROOT / "data" / "eval" / "benchmark" / "index" / "index.json").is_file()
    assert (ROOT / "data" / "eval" / "benchmark" / "index" / "embeddings.npy").is_file()
