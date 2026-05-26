"""Runner for the public synthetic Naive RAG benchmark v1."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import sys
import time
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from eval.naive_rag.build_benchmark_index import (  # noqa: E402
    PROHIBITED_CORPUS_FIELDS,
    load_corpus_chunks,
)
from eval.naive_rag.metrics import (  # noqa: E402
    BENCHMARK_CITATION_PAGE_METRIC_KEYS,
    BENCHMARK_LATENCY_METRIC_KEYS,
    RETRIEVAL_METRIC_KEYS,
    RULE_BASED_ANSWER_METRIC_KEYS,
    contains_terms,
    retrieval_metrics,
    summarize_case_metrics,
    summarize_latency,
    summarize_metric,
    unique_ids,
)
from eval.naive_rag.run_eval import (  # noqa: E402
    _answer_status,
    _compact_retrieved_chunks,
    _relative,
    _repo_path,
    _write_jsonl,
    load_contract_config,
    load_gold_evidence,
    load_questions,
)
from eval.naive_rag.taxonomy import ALL_FAILURE_TYPES, classify_failure, count_failures  # noqa: E402
from eval.scorers._shared import answer_citations, answer_to_text  # noqa: E402
from rag_core import load_index, run_rag_query  # noqa: E402


REQUIRED_OUTPUTS = (
    "metrics.json",
    "retrieved_chunks.jsonl",
    "answers.jsonl",
    "failure_cases.jsonl",
    "summary.md",
)
GOLD_DERIVED_FIELDS = frozenset(
    {"expected_terms", "required_terms", "derived_from_expected_terms"}
)
MULTI_CHUNK_DOC_CARDINALITY_BUCKETS = ("same_doc", "multi_doc", "unknown")
MULTI_CHUNK_RETRIEVAL_OUTCOME_BUCKETS = (
    "all_gold_retrieved",
    "partial_gold_retrieved",
    "no_gold_retrieved",
    "not_observable",
)
MULTI_CHUNK_TOP10_FAILURE_MODE_BUCKETS = (
    "same_doc_single_gold_hit",
    "same_doc_multi_gold_partial_hit",
    "multi_doc_partial_hit",
    "same_document_distractor_without_gold",
    "cross_document_distractor_only",
    "not_observable",
)
EXPECTED_INDEX_LEAKAGE_GUARD = "query_and_gold_label_files_not_read"


def _chunk_for_provenance_comparison(chunk: dict[str, Any]) -> dict[str, Any]:
    """Normalize volatile index-only fields before corpus/index comparison."""
    normalized = dict(chunk)
    normalized.pop("embedding", None)
    normalized.pop("embedding_idx", None)
    return normalized


def load_benchmark_config(path: Path) -> dict[str, Any]:
    config = load_contract_config(path)
    if config.get("benchmark_type") != "naive_rag_benchmark":
        raise ValueError("Benchmark config must set benchmark_type=naive_rag_benchmark")
    if str(config.get("benchmark_version") or "") != "v1":
        raise ValueError("Benchmark config must set benchmark_version=v1")
    if config.get("not_ci_smoke") is not True:
        raise ValueError("Benchmark config must set not_ci_smoke=true")
    if not str(config.get("corpus_path") or "").strip():
        raise ValueError("Benchmark config must include corpus_path")
    return config


def flatten_gold_evidence(gold_by_question: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [item for items in gold_by_question.values() for item in items]


def assert_explicit_gold_evidence(
    questions: list[dict[str, Any]],
    gold_by_question: dict[str, list[dict[str, Any]]],
) -> None:
    for item in flatten_gold_evidence(gold_by_question):
        evidence_id = str(item.get("evidence_id") or "").strip()
        if not evidence_id:
            raise ValueError(f"Gold evidence item missing evidence_id: {item}")
        leaked = sorted(GOLD_DERIVED_FIELDS & set(item))
        if leaked:
            raise ValueError(
                f"Gold evidence {evidence_id} contains expected-terms-derived fields: {', '.join(leaked)}"
            )
        if item.get("derived_from_expected_terms") is True:
            raise ValueError(f"Gold evidence {evidence_id} is marked derived_from_expected_terms=true")

    for question in questions:
        qid = str(question["question_id"])
        expected_ids = question.get("expected_evidence_ids")
        if not isinstance(expected_ids, list):
            raise ValueError(f"{qid}: expected_evidence_ids must be a list")
        if bool(question.get("answerable", True)):
            if not gold_by_question.get(qid):
                raise ValueError(f"{qid}: answerable question has no explicit gold evidence")
            if not expected_ids:
                raise ValueError(f"{qid}: answerable question has no expected_evidence_ids")
        else:
            if gold_by_question.get(qid):
                raise ValueError(f"{qid}: unanswerable question must not have gold evidence")
            if expected_ids:
                raise ValueError(f"{qid}: unanswerable question must have empty expected_evidence_ids")


def assert_benchmark_index_provenance(
    *,
    index: dict[str, Any],
    index_dir: Path,
    corpus_path: Path,
    corpus_chunks: list[dict[str, Any]],
) -> None:
    build = index.get("build") if isinstance(index.get("build"), dict) else {}
    errors: list[str] = []
    expected_corpus_path = _relative(corpus_path)

    if build.get("input_kind") != "corpus_chunks_jsonl":
        errors.append("index.build.input_kind must be corpus_chunks_jsonl")
    if build.get("source_corpus_path") != expected_corpus_path:
        errors.append(
            "index.build.source_corpus_path must match benchmark config corpus_path "
            f"({expected_corpus_path})"
        )
    if build.get("leakage_guard") != EXPECTED_INDEX_LEAKAGE_GUARD:
        errors.append(f"index.build.leakage_guard must be {EXPECTED_INDEX_LEAKAGE_GUARD}")

    try:
        num_chunks = int(build.get("num_chunks"))
    except (TypeError, ValueError):
        num_chunks = -1
    if num_chunks != len(corpus_chunks):
        errors.append(
            "index.build.num_chunks must match corpus_path chunk count "
            f"({len(corpus_chunks)})"
        )

    index_chunks = index.get("chunks") if isinstance(index.get("chunks"), list) else []
    contaminated_rows = [
        idx
        for idx, chunk in enumerate(index_chunks, start=1)
        if isinstance(chunk, dict) and PROHIBITED_CORPUS_FIELDS & set(chunk)
    ]
    if contaminated_rows:
        errors.append("index chunks must not contain query/gold label fields")

    comparable_index_chunks = [
        _chunk_for_provenance_comparison(chunk)
        for chunk in index_chunks
        if isinstance(chunk, dict)
    ]
    comparable_corpus_chunks = [
        _chunk_for_provenance_comparison(chunk)
        for chunk in corpus_chunks
    ]
    if comparable_index_chunks != comparable_corpus_chunks:
        errors.append("index chunks must match corpus_path chunk ids, order, metadata, and text")

    if errors:
        raise ValueError(
            f"Benchmark index provenance mismatch in {_relative(index_dir)}:\n- "
            + "\n- ".join(errors)
        )


def _pages_from_span(value: Any) -> set[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        return {value}
    if isinstance(value, list) and len(value) == 2:
        start, end = value
        if isinstance(start, int) and isinstance(end, int) and start > 0 and end >= start:
            return set(range(start, end + 1))
    return set()


def _citation_page_metrics_for_case(
    *,
    answerable: bool,
    citations: list[dict[str, Any]],
    gold_evidence: list[dict[str, Any]],
) -> dict[str, float | None]:
    if not answerable:
        return {
            "citation_chunk_accuracy": None,
            "citation_page_coverage": None,
            "citation_page_precision": None,
            "missing_page_number_rate": None,
        }

    gold_chunk_ids = set(unique_ids([str(item.get("chunk_id") or "") for item in gold_evidence]))
    cited_chunk_ids = unique_ids([str(citation.get("chunk_id") or "") for citation in citations])
    if cited_chunk_ids:
        citation_chunk_accuracy: float | None = (
            sum(1 for chunk_id in cited_chunk_ids if chunk_id in gold_chunk_ids) / len(cited_chunk_ids)
        )
    else:
        citation_chunk_accuracy = 0.0

    gold_pages = {
        int(item["page"])
        for item in gold_evidence
        if isinstance(item.get("page"), int) and not isinstance(item.get("page"), bool)
    }
    cited_pages: set[int] = set()
    missing_page_count = 0
    for citation in citations:
        pages = _pages_from_span(citation.get("page_span")) or _pages_from_span(citation.get("page"))
        if pages:
            cited_pages |= pages
        else:
            missing_page_count += 1

    citation_page_coverage = (
        len(gold_pages & cited_pages) / len(gold_pages) if gold_pages else None
    )
    citation_page_precision = (
        len(gold_pages & cited_pages) / len(cited_pages) if cited_pages else 0.0
    )
    missing_page_number_rate = (
        missing_page_count / len(citations) if citations else 0.0
    )
    return {
        "citation_chunk_accuracy": citation_chunk_accuracy,
        "citation_page_coverage": citation_page_coverage,
        "citation_page_precision": citation_page_precision,
        "missing_page_number_rate": missing_page_number_rate,
    }


def _rule_based_answer_metrics_for_case(
    *,
    question: dict[str, Any],
    prediction: dict[str, Any],
    gold_chunk_ids: list[str],
    retrieved_chunk_ids: list[str],
    citations: list[dict[str, Any]],
) -> dict[str, float | int | None]:
    answerable = bool(question.get("answerable", True))
    cited_chunk_ids = unique_ids([str(citation.get("chunk_id") or "") for citation in citations])
    answer_text = answer_to_text(prediction)
    status = _answer_status(prediction)

    if answerable:
        term_coverage = contains_terms(answer_text, [str(term) for term in question.get("expected_terms") or []])
        groundedness: float | None = (
            1.0 if cited_chunk_ids and set(cited_chunk_ids).issubset(set(retrieved_chunk_ids)) else 0.0
        )
        if cited_chunk_ids:
            citation_accuracy = (
                sum(1 for chunk_id in cited_chunk_ids if chunk_id in set(gold_chunk_ids))
                / len(cited_chunk_ids)
            )
        else:
            citation_accuracy = 0.0
        hallucination = 1 if status == "supported" and cited_chunk_ids and citation_accuracy == 0.0 else 0
        failed_abstention = None
        unsafe = hallucination
    else:
        term_coverage = None
        groundedness = None
        unanswerable_detected = status == "insufficient" or bool(
            (prediction.get("diagnostics") or {}).get("abstained")
        )
        failed_abstention = 0 if unanswerable_detected else 1
        hallucination = None
        unsafe = failed_abstention

    return {
        "rule_based_groundedness": groundedness,
        "term_coverage_accuracy": term_coverage,
        "failed_abstention_rate": failed_abstention,
        "unsafe_answer_rate": unsafe,
        "rule_based_hallucination_rate": hallucination,
    }


def _compat_answer_metrics(
    rule_metrics: dict[str, float | int | None],
    citation_metrics: dict[str, float | None],
) -> dict[str, float | int | None]:
    failed_abstention = rule_metrics.get("failed_abstention_rate")
    unanswerable_detection = None
    if isinstance(failed_abstention, (int, float)):
        unanswerable_detection = 0 if failed_abstention else 1
    return {
        "faithfulness": rule_metrics.get("rule_based_groundedness"),
        "answer_relevancy": rule_metrics.get("term_coverage_accuracy"),
        "citation_accuracy": citation_metrics.get("citation_chunk_accuracy"),
        "hallucination_flag": rule_metrics.get("unsafe_answer_rate"),
        "unanswerable_detection_flag": unanswerable_detection,
    }


def _empty_bucket_counts(keys: tuple[str, ...]) -> dict[str, int]:
    return {key: 0 for key in keys}


def _multi_chunk_doc_cardinality(gold_evidence: list[dict[str, Any]]) -> str:
    doc_ids = unique_ids([str(item.get("doc_id") or "") for item in gold_evidence])
    if len(doc_ids) == 1:
        return "same_doc"
    if len(doc_ids) > 1:
        return "multi_doc"
    return "unknown"


def _multi_chunk_evidence_profile_for_case(
    gold_evidence: list[dict[str, Any]],
    retrieved_chunks: list[dict[str, Any]],
    *,
    k: int = 10,
) -> dict[str, Any] | None:
    gold_chunk_ids = unique_ids([str(item.get("chunk_id") or "") for item in gold_evidence])
    if len(gold_chunk_ids) < 2:
        return None

    top_retrieved = retrieved_chunks[:k]
    retrieved_chunk_ids = unique_ids(
        [str(item.get("chunk_id") or "") for item in top_retrieved]
    )
    gold_doc_ids = set(unique_ids([str(item.get("doc_id") or "") for item in gold_evidence]))
    retrieved_doc_ids = set(
        unique_ids([str(item.get("doc_id") or "") for item in top_retrieved])
    )
    gold_hits = set(gold_chunk_ids) & set(retrieved_chunk_ids)
    doc_cardinality = _multi_chunk_doc_cardinality(gold_evidence)

    if len(gold_hits) == len(gold_chunk_ids):
        retrieval_outcome = "all_gold_retrieved"
    elif gold_hits:
        retrieval_outcome = (
            "not_observable" if len(top_retrieved) < k else "partial_gold_retrieved"
        )
    else:
        retrieval_outcome = "no_gold_retrieved"

    failure_mode = None
    if retrieval_outcome == "not_observable":
        failure_mode = "not_observable"
    elif retrieval_outcome == "partial_gold_retrieved":
        if doc_cardinality == "same_doc":
            failure_mode = (
                "same_doc_single_gold_hit"
                if len(gold_hits) == 1
                else "same_doc_multi_gold_partial_hit"
            )
        elif doc_cardinality == "multi_doc":
            failure_mode = "multi_doc_partial_hit"
        else:
            failure_mode = "not_observable"
    elif retrieval_outcome == "no_gold_retrieved":
        if not gold_doc_ids or not retrieved_doc_ids:
            failure_mode = "not_observable"
        elif retrieved_doc_ids.isdisjoint(gold_doc_ids):
            failure_mode = "cross_document_distractor_only"
        else:
            failure_mode = "same_document_distractor_without_gold"

    return {
        "gold_chunk_count": len(gold_chunk_ids),
        "gold_doc_cardinality": doc_cardinality,
        "retrieval_outcome_at_10": retrieval_outcome,
        "top10_failure_mode": failure_mode,
    }


def _summarize_multi_chunk_evidence_profiles(
    case_profiles: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = {
        "case_count": len(case_profiles),
        "top_k": 10,
        "gold_doc_cardinality": _empty_bucket_counts(MULTI_CHUNK_DOC_CARDINALITY_BUCKETS),
        "retrieval_outcome_at_10": _empty_bucket_counts(MULTI_CHUNK_RETRIEVAL_OUTCOME_BUCKETS),
        "top10_failure_count": 0,
        "top10_not_observable_count": 0,
        "top10_failure_modes": _empty_bucket_counts(MULTI_CHUNK_TOP10_FAILURE_MODE_BUCKETS),
        "definition": (
            "answerable benchmark cases with two or more explicit gold chunk ids; "
            "closed buckets only, no question text or document ids"
        ),
    }
    for profile in case_profiles:
        doc_bucket = str(profile.get("gold_doc_cardinality") or "unknown")
        if doc_bucket not in summary["gold_doc_cardinality"]:
            doc_bucket = "unknown"
        summary["gold_doc_cardinality"][doc_bucket] += 1

        outcome = str(profile.get("retrieval_outcome_at_10") or "not_observable")
        if outcome not in summary["retrieval_outcome_at_10"]:
            outcome = "not_observable"
        summary["retrieval_outcome_at_10"][outcome] += 1

        failure_mode = profile.get("top10_failure_mode")
        if failure_mode:
            mode = str(failure_mode)
            if mode not in summary["top10_failure_modes"]:
                mode = "not_observable"
            summary["top10_failure_modes"][mode] += 1
            if mode == "not_observable":
                summary["top10_not_observable_count"] += 1
            else:
                summary["top10_failure_count"] += 1
    return summary


def _mean(metrics: dict[str, dict[str, Any]], key: str) -> float | None:
    block = metrics.get(key) or {}
    value = block.get("mean")
    return float(value) if isinstance(value, (int, float)) else None


def _all_means_equal(metrics: dict[str, dict[str, Any]], keys: tuple[str, ...], target: float) -> bool:
    values = [_mean(metrics, key) for key in keys]
    return bool(values) and all(value == target for value in values if value is not None)


def _warnings(metrics: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    retrieval = metrics["retrieval_metrics"]
    answer = metrics["rule_based_answer_metrics"]
    citation = metrics["citation_page_metrics"]
    dataset = metrics["dataset"]
    latency = metrics["latency_metrics"]

    if _all_means_equal(retrieval, RETRIEVAL_METRIC_KEYS, 1.0):
        warnings.append(
            "Retrieval metrics are saturated at 1.000; do not infer that the naive baseline is strong."
        )

    quality_keys = ("rule_based_groundedness", "term_coverage_accuracy")
    error_rate_keys = ("failed_abstention_rate", "unsafe_answer_rate", "rule_based_hallucination_rate")
    quality_perfect = _all_means_equal(answer, quality_keys, 1.0)
    error_rates_zero = all((_mean(answer, key) in (0.0, None)) for key in error_rate_keys)
    if quality_perfect and error_rates_zero:
        warnings.append(
            "Rule-based answer metrics saturate; they are not judge-based faithfulness or answer relevancy."
        )

    failed_abstention = _mean(answer, "failed_abstention_rate")
    hallucination = _mean(answer, "rule_based_hallucination_rate")
    if failed_abstention and failed_abstention > 0.0 and hallucination == 0.0:
        warnings.append(
            "Failed abstention is nonzero while rule-based hallucination is zero; unsafe answers must be read separately."
        )

    page_metadata_coverage = _mean(citation, "page_metadata_coverage")
    if page_metadata_coverage is not None and page_metadata_coverage < 1.0:
        warnings.append("Page metadata coverage is below 1.0; citation/page metrics are provisional.")

    if int(dataset["chunk_count"]) <= int(dataset["top_k"]) * 3:
        warnings.append("chunk_count <= top_k * 3; retrieval metrics are likely under-stressed.")

    if latency.get("benchmark_excludes_setup_costs") is True:
        warnings.append("Latency excludes index loading, ingestion, parsing, chunking, and index build costs.")
    if latency.get("generation_latency_ms") is None:
        warnings.append("External generation latency is not measured; latency numbers are not end-to-end RAG latency.")

    metadata = dataset.get("metadata") if isinstance(dataset.get("metadata"), dict) else {}
    if metadata.get("privacy") == "public_synthetic" or int(dataset["question_count"]) < 100:
        warnings.append("Dataset is synthetic-public and still small; it is not sufficient for production claims.")

    return warnings


def _format_mean(block: dict[str, Any]) -> str:
    value = block.get("mean")
    return "null" if value is None else f"{float(value):.4f}"


def _summary_markdown(metrics: dict[str, Any]) -> str:
    lines = [
        "# Naive RAG Benchmark v1 Summary",
        "",
        f"- Run ID: `{metrics['run_id']}`",
        f"- Config: `{metrics['config_path']}`",
        f"- Index: `{metrics['index_dir']}`",
        f"- Corpus chunks: {metrics['dataset']['chunk_count']}",
        f"- Questions: {metrics['dataset']['question_count']} "
        f"({metrics['dataset']['answerable_count']} answerable, "
        f"{metrics['dataset']['unanswerable_count']} unanswerable)",
        "",
        "## Retrieval Metrics",
        "",
        "| metric | mean | n | missing |",
        "|---|---:|---:|---:|",
    ]
    for key in RETRIEVAL_METRIC_KEYS:
        block = metrics["retrieval_metrics"][key]
        lines.append(f"| `{key}` | {_format_mean(block)} | {block['n']} | {block['missing']} |")

    lines.extend(["", "## Citation/Page Metrics", "", "| metric | mean | n | missing |", "|---|---:|---:|---:|"])
    for key in BENCHMARK_CITATION_PAGE_METRIC_KEYS:
        block = metrics["citation_page_metrics"][key]
        lines.append(f"| `{key}` | {_format_mean(block)} | {block['n']} | {block['missing']} |")

    lines.extend(["", "## Rule-Based Answer Metrics", "", "| metric | mean | n | missing |", "|---|---:|---:|---:|"])
    for key in RULE_BASED_ANSWER_METRIC_KEYS:
        block = metrics["rule_based_answer_metrics"][key]
        lines.append(f"| `{key}` | {_format_mean(block)} | {block['n']} | {block['missing']} |")

    lines.extend(["", "## Latency Metrics", "", "| metric | mean | p50 | p95 | n |", "|---|---:|---:|---:|---:|"])
    for key in BENCHMARK_LATENCY_METRIC_KEYS:
        if key == "generation_latency_ms":
            lines.append("| `generation_latency_ms` | null | null | null | 0 |")
            continue
        block = metrics["latency_metrics"][key]
        mean = "null" if block["mean"] is None else f"{block['mean']:.2f}"
        p50 = "null" if block["p50"] is None else f"{block['p50']:.2f}"
        p95 = "null" if block["p95"] is None else f"{block['p95']:.2f}"
        lines.append(f"| `{key}` | {mean} | {p50} | {p95} | {block['n']} |")

    lines.extend(["", "## Validity Warnings", ""])
    for warning in metrics["benchmark_validity_warnings"]:
        lines.append(f"- {warning}")
    lines.extend(
        [
            "",
            "This benchmark is for failure discovery and ablation setup only. It is not sufficient for production-level performance claims.",
            "",
        ]
    )
    return "\n".join(lines)


def _dataset_summary(
    *,
    config: dict[str, Any],
    corpus_path: Path,
    corpus_chunks: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    gold_items: list[dict[str, Any]],
) -> dict[str, Any]:
    top_k = int(config["pipeline"]["top_k"])
    doc_ids = unique_ids([str(chunk.get("doc_id") or "") for chunk in corpus_chunks])
    gold_chunk_ids = unique_ids([str(item.get("chunk_id") or "") for item in gold_items])
    chunk_ids = unique_ids([str(chunk.get("chunk_id") or "") for chunk in corpus_chunks])
    page_chunks = [chunk for chunk in corpus_chunks if chunk.get("page_span")]
    explicit_gold_items = [
        item
        for item in gold_items
        if item.get("evidence_id") and item.get("chunk_id") and item.get("support_text")
    ]
    metadata = config.get("dataset_metadata") if isinstance(config.get("dataset_metadata"), dict) else {}
    return {
        "corpus_path": _relative(corpus_path),
        "corpus_size": len(doc_ids),
        "chunk_count": len(corpus_chunks),
        "question_count": len(questions),
        "answerable_count": sum(1 for row in questions if row.get("answerable", True)),
        "unanswerable_count": sum(1 for row in questions if not row.get("answerable", True)),
        "top_k": top_k,
        "chunk_count_top_k_ratio": round(len(corpus_chunks) / top_k, 3) if top_k else None,
        "gold_evidence_count": len(gold_items),
        "explicit_gold_evidence_items": len(explicit_gold_items),
        "unique_gold_chunk_count": len(gold_chunk_ids),
        "distractor_chunk_count": len(set(chunk_ids) - set(gold_chunk_ids)),
        "distractor_chunk_count_definition": "corpus chunks not referenced by explicit gold evidence",
        "page_metadata_chunks": len(page_chunks),
        "metadata": metadata,
    }


def _index_missing_message(config: dict[str, Any], index_dir: Path) -> str:
    build_config = config.get("index_build") if isinstance(config.get("index_build"), dict) else {}
    command = str(build_config.get("command") or "").strip()
    if not command:
        command = (
            "python3 -m eval.naive_rag.build_benchmark_index "
            f"--corpus {config['corpus_path']} --output {config['index_dir']}"
        )
    return f"Benchmark index missing: {_relative(index_dir)}. Build it with: {command}"


def run_from_config(
    config_path: Path,
    *,
    output_root_override: Path | None = None,
    run_id_override: str | None = None,
) -> Path:
    config_path = _repo_path(config_path)
    config = load_benchmark_config(config_path)
    corpus_path = _repo_path(config["corpus_path"])
    questions_path = _repo_path(config["questions_path"])
    gold_path = _repo_path(config["gold_evidence_path"])
    index_dir = _repo_path(config["index_dir"])
    if not (index_dir / "index.json").is_file():
        raise FileNotFoundError(_index_missing_message(config, index_dir))

    questions = load_questions(questions_path)
    gold_by_question = load_gold_evidence(gold_path)
    assert_explicit_gold_evidence(questions, gold_by_question)
    gold_items = flatten_gold_evidence(gold_by_question)
    corpus_chunks = load_corpus_chunks(corpus_path)
    index_load_start = time.perf_counter()
    index = load_index(index_dir)
    assert_benchmark_index_provenance(
        index=index,
        index_dir=index_dir,
        corpus_path=corpus_path,
        corpus_chunks=corpus_chunks,
    )
    index_load_ms = (time.perf_counter() - index_load_start) * 1000
    pipeline = config["pipeline"]

    output_root = output_root_override or _repo_path(config.get("output_root", "experiments/runs"))
    run_id = run_id_override or str(config.get("run_id") or "").strip()
    if not run_id:
        run_id = "naive-rag-benchmark-v1-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    retrieved_rows: list[dict[str, Any]] = []
    answer_rows: list[dict[str, Any]] = []
    failure_rows: list[dict[str, Any]] = []
    retrieval_case_metrics: list[dict[str, Any]] = []
    citation_case_metrics: list[dict[str, Any]] = []
    answer_case_metrics: list[dict[str, Any]] = []
    latency_case_metrics: list[dict[str, float | None]] = []
    primary_failures: list[str | None] = []
    multi_chunk_case_profiles: list[dict[str, Any]] = []

    for question in questions:
        qid = str(question["question_id"])
        query_start = time.perf_counter()
        prediction = run_rag_query(
            index,
            str(question["question"]),
            pipeline=str(pipeline["name"]),
            top_k=int(pipeline["top_k"]),
            metadata_first=False,
            rerank=False,
            rerank_cross_encoder=False,
            verifier_retry=False,
            retrieval_mode=str(pipeline.get("retrieval_mode", "flat")),
            retrieval_backend="dense",
            prompt_profile=str(pipeline.get("prompt_profile") or ""),
            bm25_tokenizer=str(pipeline.get("bm25_tokenizer", "regex")),
            bm25_backend=str(pipeline.get("bm25_backend", "okapi")),
            _skip_graph=True,
        )
        query_wall_ms = (time.perf_counter() - query_start) * 1000
        diagnostics = prediction.get("diagnostics") if isinstance(prediction.get("diagnostics"), dict) else {}
        retrieved_chunks = _compact_retrieved_chunks(prediction)
        retrieved_chunk_ids = unique_ids([str(item["chunk_id"]) for item in retrieved_chunks])
        gold_evidence = gold_by_question.get(qid, [])
        gold_chunk_ids = unique_ids([str(item.get("chunk_id") or "") for item in gold_evidence])
        citations = answer_citations(prediction)
        cited_chunk_ids = unique_ids([str(citation.get("chunk_id") or "") for citation in citations])

        retrieval_metric = retrieval_metrics(retrieved_chunk_ids, gold_chunk_ids)
        citation_metric = _citation_page_metrics_for_case(
            answerable=bool(question.get("answerable", True)),
            citations=citations,
            gold_evidence=gold_evidence,
        )
        rule_metric = _rule_based_answer_metrics_for_case(
            question=question,
            prediction=prediction,
            gold_chunk_ids=gold_chunk_ids,
            retrieved_chunk_ids=retrieved_chunk_ids,
            citations=citations,
        )
        compat_metric = _compat_answer_metrics(rule_metric, citation_metric)
        multi_chunk_profile = _multi_chunk_evidence_profile_for_case(
            gold_evidence,
            retrieved_chunks,
            k=10,
        )
        if multi_chunk_profile is not None:
            multi_chunk_case_profiles.append(multi_chunk_profile)
        primary_failure, all_failures = classify_failure(
            question=question,
            gold_chunk_ids=gold_chunk_ids,
            retrieved_chunk_ids=retrieved_chunk_ids,
            cited_chunk_ids=cited_chunk_ids,
            retrieval_metrics=retrieval_metric,
            answer_metrics=compat_metric,
        )
        primary_failures.append(primary_failure)
        retrieval_case_metrics.append(retrieval_metric)
        citation_case_metrics.append(citation_metric)
        answer_case_metrics.append(rule_metric)

        retrieve_ms = None
        attempts = diagnostics.get("filter_stage_attempts") if isinstance(diagnostics, dict) else []
        if isinstance(attempts, list):
            retrieve_values = [
                float(attempt.get("retrieve_ms"))
                for attempt in attempts
                if isinstance(attempt, dict) and isinstance(attempt.get("retrieve_ms"), (int, float))
            ]
            if retrieve_values:
                retrieve_ms = sum(retrieve_values)
        warm_latency = diagnostics.get("latency_ms") if isinstance(diagnostics, dict) else None
        if not isinstance(warm_latency, (int, float)):
            warm_latency = query_wall_ms
        latency_case_metrics.append(
            {
                "warm_query_latency_ms": float(warm_latency),
                "retrieval_latency_ms": retrieve_ms,
                "generation_latency_ms": None,
            }
        )

        retrieved_row = {
            "run_id": run_id,
            "question_id": qid,
            "question": question["question"],
            "answerable": bool(question.get("answerable", True)),
            "gold_chunk_ids": gold_chunk_ids,
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "retrieved_chunks": retrieved_chunks,
            "retrieval_metrics": retrieval_metric,
        }
        answer_row = {
            "run_id": run_id,
            "question_id": qid,
            "question": question["question"],
            "answerable": bool(question.get("answerable", True)),
            "answer_status": _answer_status(prediction),
            "answer_text": answer_to_text(prediction),
            "citations": citations,
            "gold_evidence": gold_evidence,
            "retrieval_metrics": retrieval_metric,
            "citation_page_metrics": citation_metric,
            "rule_based_answer_metrics": rule_metric,
            "latency_metrics": latency_case_metrics[-1],
        }
        retrieved_rows.append(retrieved_row)
        answer_rows.append(answer_row)

        if primary_failure:
            failure_rows.append(
                {
                    "run_id": run_id,
                    "question_id": qid,
                    "question": question["question"],
                    "failure_type": primary_failure,
                    "additional_failure_types": all_failures[1:],
                    "metrics": {
                        "retrieval": retrieval_metric,
                        "citation_page": citation_metric,
                        "rule_based_answer": rule_metric,
                    },
                    "gold_evidence": gold_evidence,
                    "retrieved_chunks": retrieved_chunks,
                    "answer": {
                        "status": _answer_status(prediction),
                        "text": answer_to_text(prediction),
                        "citations": citations,
                    },
                }
            )

    page_metadata_coverage = (
        sum(1 for chunk in corpus_chunks if chunk.get("page_span")) / len(corpus_chunks)
        if corpus_chunks
        else 0.0
    )
    citation_metrics = summarize_case_metrics(
        citation_case_metrics,
        tuple(key for key in BENCHMARK_CITATION_PAGE_METRIC_KEYS if key != "page_metadata_coverage"),
    )
    citation_metrics["page_metadata_coverage"] = summarize_metric(
        [1 if chunk.get("page_span") else 0 for chunk in corpus_chunks],
        len(corpus_chunks),
    )
    citation_metrics["page_metadata_coverage"]["mean"] = page_metadata_coverage

    latency_metrics = {
        "warm_query_latency_ms": summarize_latency(
            [row.get("warm_query_latency_ms") for row in latency_case_metrics]
        ),
        "retrieval_latency_ms": summarize_latency(
            [row.get("retrieval_latency_ms") for row in latency_case_metrics]
        ),
        "generation_latency_ms": None,
        "benchmark_excludes_setup_costs": True,
        "index_load_ms_observed_but_excluded": round(index_load_ms, 2),
    }

    artifact_paths = {name: output_dir / name for name in REQUIRED_OUTPUTS}
    _write_jsonl(artifact_paths["retrieved_chunks.jsonl"], retrieved_rows)
    _write_jsonl(artifact_paths["answers.jsonl"], answer_rows)
    _write_jsonl(artifact_paths["failure_cases.jsonl"], failure_rows)

    metrics_payload: dict[str, Any] = {
        "schema_version": 1,
        "benchmark_type": "naive_rag_benchmark",
        "benchmark_version": "v1",
        "run_id": run_id,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "config_path": _relative(config_path),
        "output_dir": _relative(output_dir),
        "index_dir": _relative(index_dir),
        "pipeline": {
            "name": pipeline["name"],
            "top_k": int(pipeline["top_k"]),
            "retrieval_backend": "dense",
            "metadata_first": False,
            "rerank": False,
            "verifier_retry": False,
            "query_expansion": "identity",
        },
        "dataset": _dataset_summary(
            config=config,
            corpus_path=corpus_path,
            corpus_chunks=corpus_chunks,
            questions=questions,
            gold_items=gold_items,
        ),
        "retrieval_metrics": summarize_case_metrics(retrieval_case_metrics, RETRIEVAL_METRIC_KEYS),
        "citation_page_metrics": citation_metrics,
        "rule_based_answer_metrics": summarize_case_metrics(
            answer_case_metrics,
            RULE_BASED_ANSWER_METRIC_KEYS,
        ),
        "latency_metrics": latency_metrics,
        "metric_labels": {
            "retrieval": "computed from explicit gold evidence chunk_ids",
            "citation_page": "rule-based citation chunk/page checks using explicit gold evidence and page metadata",
            "answer": "rule-based/provisional lexical and citation checks, not judge-based faithfulness or answer relevancy",
            "latency": "warm query timing only; setup and external generation costs excluded",
        },
        "failure_counts": count_failures(primary_failures),
        "failure_taxonomy": list(ALL_FAILURE_TYPES),
        "multi_chunk_evidence_profile": _summarize_multi_chunk_evidence_profiles(
            multi_chunk_case_profiles
        ),
        "artifact_paths": {name: _relative(path) for name, path in artifact_paths.items()},
    }
    metrics_payload["benchmark_validity_warnings"] = _warnings(metrics_payload)

    artifact_paths["metrics.json"].write_text(
        json.dumps(metrics_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    artifact_paths["summary.md"].write_text(_summary_markdown(metrics_payload), encoding="utf-8")
    return output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Naive RAG benchmark v1.")
    parser.add_argument("--config", required=True, help="Path to configs/eval/benchmark_naive_rag_v1.yaml")
    parser.add_argument("--run-id", default=None, help="Optional deterministic run id override.")
    parser.add_argument("--output-root", default=None, help="Optional output root override.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output_dir = run_from_config(
            Path(args.config),
            output_root_override=Path(args.output_root) if args.output_root else None,
            run_id_override=args.run_id,
        )
    except Exception as exc:
        print(f"[ERROR] Naive RAG benchmark failed: {exc}", file=sys.stderr)
        return 2
    print(f"[OK] Naive RAG benchmark artifacts written: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
