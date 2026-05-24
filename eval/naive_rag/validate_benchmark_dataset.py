#!/usr/bin/env python3
"""Validate the public synthetic Naive RAG benchmark dataset.

This script checks dataset composition, explicit gold evidence, distractor
coverage, chunk/index readiness, and lexical leakage risk. It does not run
retrieval or answer generation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from rag_indexing import (  # noqa: E402
    DEFAULT_CHUNK_MAX_CHARS,
    DEFAULT_CHUNK_OVERLAP_SENTENCES,
    build_chunk_records,
    load_raw_documents,
)


MIN_TOTAL_QUESTIONS = 50
MIN_ANSWERABLE = 35
MIN_UNANSWERABLE = 15
MIN_DISTRACTOR_SENSITIVE = 8
MIN_CHUNK_TOP_K_RATIO = 3.0
SATURATION_WARNING_RATIO = 5.0

QUESTION_TYPE_MINIMUMS = {
    "exact_fact": 10,
    "similar_clause_disambiguation": 8,
    "multi_chunk_synthesis": 7,
    "table_structured_data": 5,
    "date_amount_score_extraction": 5,
    "mixed_language": 5,
    "unanswerable": 15,
}

VALID_DIFFICULTIES = {"easy", "medium", "hard"}
VALID_SUPPORT_TYPES = {"exact_span", "table_cell", "multi_chunk", "section"}
GOLD_DERIVED_FIELDS = {"expected_terms", "required_terms", "derived_from_expected_terms"}
TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]{2,}")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT_DIR / path


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{lineno}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"JSONL row must be an object at {path}:{lineno}")
        rows.append(row)
    return rows


def load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError(f"Config must be a mapping: {path}")
    return config


def load_questions(path: Path) -> list[dict[str, Any]]:
    questions = jsonl_rows(path)
    seen: set[str] = set()
    for row in questions:
        qid = str(row.get("question_id") or "").strip()
        if not qid:
            raise ValueError(f"Question missing question_id: {row}")
        if qid in seen:
            raise ValueError(f"Duplicate question_id: {qid}")
        seen.add(qid)
    return questions


def load_gold_evidence(path: Path) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for row in jsonl_rows(path):
        if isinstance(row.get("gold_evidence"), list):
            qid = str(row.get("question_id") or "").strip()
            for item in row["gold_evidence"]:
                if not isinstance(item, dict):
                    raise ValueError(f"gold_evidence item must be an object for {qid}")
                evidence.append({"question_id": qid, **item})
        else:
            evidence.append(row)
    return evidence


def corpus_text_by_doc(documents: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for doc in documents:
        text = " ".join(str(section.get("text") or "") for section in doc.get("sections") or [])
        result[str(doc["doc_id"])] = compact_text(text)
    return result


def tokens(value: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(str(value or ""))}


def overlap_ratio(left: str, right: str) -> float:
    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def containment_ratio(needle: str, haystack: str) -> float:
    needle_tokens = tokens(needle)
    haystack_tokens = tokens(haystack)
    if not needle_tokens:
        return 0.0
    return len(needle_tokens & haystack_tokens) / len(needle_tokens)


def leakage_flags(question: dict[str, Any], support_texts: list[str]) -> dict[str, Any]:
    support = compact_text(" ".join(support_texts))
    question_text = compact_text(str(question.get("question") or ""))
    expected_answer = compact_text(str(question.get("expected_answer") or ""))
    q_overlap = overlap_ratio(question_text, support)
    q_containment = containment_ratio(question_text, support)
    answer_overlap = overlap_ratio(expected_answer, support)
    answer_containment = containment_ratio(expected_answer, support)

    flags: list[str] = []
    if question_text and question_text in support:
        flags.append("question_substring_of_support")
    if expected_answer and expected_answer in support:
        flags.append("expected_answer_substring_of_support")
    if q_containment >= 0.82:
        flags.append("question_high_token_containment")
    if question.get("difficulty") == "hard" and q_overlap >= 0.65:
        flags.append("hard_question_high_overlap")
    if answer_containment >= 0.9:
        flags.append("expected_answer_high_token_containment")

    return {
        "question_id": question.get("question_id"),
        "question_type": question.get("question_type"),
        "difficulty": question.get("difficulty"),
        "question_support_jaccard": round(q_overlap, 4),
        "question_support_containment": round(q_containment, 4),
        "answer_support_jaccard": round(answer_overlap, 4),
        "answer_support_containment": round(answer_containment, 4),
        "flags": flags,
    }


def has_korean_and_latin(text: str) -> bool:
    return bool(re.search(r"[가-힣]", text)) and bool(re.search(r"[A-Za-z]", text))


def validate_dataset(config_path: Path) -> dict[str, Any]:
    config_path = repo_path(config_path)
    config = load_config(config_path)
    errors: list[str] = []
    warnings: list[str] = []

    if config.get("benchmark_type") != "naive_rag_benchmark":
        errors.append("config.benchmark_type must be naive_rag_benchmark")
    if str(config.get("benchmark_version") or "") != "v1":
        errors.append("config.benchmark_version must be v1")
    if config.get("not_ci_smoke") is not True:
        errors.append("config.not_ci_smoke must be true")

    corpus_dir = repo_path(config.get("corpus_dir") or "")
    corpus_path = repo_path(config.get("corpus_path") or "")
    questions_path = repo_path(config.get("questions_path") or "")
    gold_path = repo_path(config.get("gold_evidence_path") or "")

    questions = load_questions(questions_path)
    gold_evidence = load_gold_evidence(gold_path)
    question_by_id = {str(row["question_id"]): row for row in questions}
    gold_by_question: dict[str, list[dict[str, Any]]] = defaultdict(list)
    gold_by_id: dict[str, dict[str, Any]] = {}

    for item in gold_evidence:
        evidence_id = str(item.get("evidence_id") or "").strip()
        qid = str(item.get("question_id") or "").strip()
        if not evidence_id:
            errors.append(f"gold evidence missing evidence_id: {item}")
            continue
        if evidence_id in gold_by_id:
            errors.append(f"duplicate evidence_id: {evidence_id}")
        gold_by_id[evidence_id] = item
        gold_by_question[qid].append(item)

    documents = load_raw_documents(corpus_dir)
    doc_ids = {str(doc["doc_id"]) for doc in documents}
    doc_texts = corpus_text_by_doc(documents)
    build_config = config.get("index_build") if isinstance(config.get("index_build"), dict) else {}
    chunking_strategy = str(build_config.get("chunking_strategy") or "auto")
    chunk_max_chars = int(build_config.get("chunk_max_chars") or DEFAULT_CHUNK_MAX_CHARS)
    chunk_overlap_sentences = int(
        build_config.get("chunk_overlap_sentences") or DEFAULT_CHUNK_OVERLAP_SENTENCES
    )
    chunks, _, chunking_diagnostics = build_chunk_records(
        documents,
        max_chars=chunk_max_chars,
        chunking_strategy=chunking_strategy,
        overlap_sentences=chunk_overlap_sentences,
    )
    corpus_chunks = jsonl_rows(corpus_path) if corpus_path.is_file() else []
    if not corpus_chunks:
        errors.append(f"corpus_path must exist and contain JSONL chunks: {corpus_path}")
        corpus_chunks = chunks
    raw_chunk_ids = {str(chunk["chunk_id"]) for chunk in chunks}
    corpus_chunk_ids = {str(chunk.get("chunk_id") or "") for chunk in corpus_chunks}
    if raw_chunk_ids != corpus_chunk_ids:
        errors.append("corpus_path chunk ids must match configured corpus_dir chunking output")
    chunk_by_id = {str(chunk.get("chunk_id") or ""): chunk for chunk in corpus_chunks}

    answerable = [row for row in questions if bool(row.get("answerable", True))]
    unanswerable = [row for row in questions if not bool(row.get("answerable", True))]
    if len(questions) < MIN_TOTAL_QUESTIONS:
        errors.append(f"question count must be >= {MIN_TOTAL_QUESTIONS}, got {len(questions)}")
    if len(answerable) < MIN_ANSWERABLE:
        errors.append(f"answerable count must be >= {MIN_ANSWERABLE}, got {len(answerable)}")
    if len(unanswerable) < MIN_UNANSWERABLE:
        errors.append(f"unanswerable count must be >= {MIN_UNANSWERABLE}, got {len(unanswerable)}")

    type_counts = Counter(str(row.get("question_type") or "") for row in questions)
    for question_type, minimum in QUESTION_TYPE_MINIMUMS.items():
        if type_counts[question_type] < minimum:
            errors.append(
                f"question_type {question_type} must have >= {minimum}, got {type_counts[question_type]}"
            )

    distractor_sensitive = [
        row
        for row in questions
        if row.get("distractor_sensitive") is True
        or row.get("question_type") == "similar_clause_disambiguation"
    ]
    if len(distractor_sensitive) < MIN_DISTRACTOR_SENSITIVE:
        errors.append(
            f"distractor-sensitive questions must be >= {MIN_DISTRACTOR_SENSITIVE}, "
            f"got {len(distractor_sensitive)}"
        )
    if not any(row.get("difficulty") == "hard" for row in questions):
        errors.append("at least one hard question is required")

    for row in questions:
        qid = str(row.get("question_id") or "")
        if not compact_text(str(row.get("question") or "")):
            errors.append(f"{qid}: missing question text")
        if not compact_text(str(row.get("expected_answer") or "")):
            errors.append(f"{qid}: missing expected_answer")
        if row.get("difficulty") not in VALID_DIFFICULTIES:
            errors.append(f"{qid}: invalid difficulty {row.get('difficulty')!r}")
        if not str(row.get("question_type") or "").strip():
            errors.append(f"{qid}: missing question_type")
        expected_evidence_ids = row.get("expected_evidence_ids")
        if not isinstance(expected_evidence_ids, list):
            errors.append(f"{qid}: expected_evidence_ids must be a list")
            expected_evidence_ids = []

        row_gold = gold_by_question.get(qid, [])
        if bool(row.get("answerable", True)):
            if not row_gold:
                errors.append(f"{qid}: answerable question has no explicit gold evidence")
            if not expected_evidence_ids:
                errors.append(f"{qid}: answerable question has no expected_evidence_ids")
            for evidence_id in expected_evidence_ids:
                evidence_id = str(evidence_id)
                if evidence_id not in gold_by_id:
                    errors.append(f"{qid}: expected_evidence_id does not exist: {evidence_id}")
                elif str(gold_by_id[evidence_id].get("question_id")) != qid:
                    errors.append(f"{qid}: expected_evidence_id belongs to another question: {evidence_id}")
        else:
            if row_gold:
                errors.append(f"{qid}: unanswerable question must not have gold evidence")
            if expected_evidence_ids:
                errors.append(f"{qid}: unanswerable question must have empty expected_evidence_ids")

        if row.get("question_type") == "multi_chunk_synthesis":
            required_count = sum(1 for item in row_gold if item.get("required") is True)
            if required_count <= 1:
                errors.append(f"{qid}: multi-chunk question needs more than one required evidence item")
        if row.get("question_type") == "mixed_language" and not has_korean_and_latin(
            f"{row.get('question', '')} {row.get('expected_answer', '')}"
        ):
            errors.append(f"{qid}: mixed_language question must include Korean and English wording")

    for item in gold_evidence:
        qid = str(item.get("question_id") or "")
        evidence_id = str(item.get("evidence_id") or "")
        if qid not in question_by_id:
            errors.append(f"{evidence_id}: gold evidence references unknown question_id {qid}")
        if any(field in item for field in GOLD_DERIVED_FIELDS):
            errors.append(f"{evidence_id}: gold evidence must not use expected_terms-derived fields")
        if item.get("derived_from_expected_terms") is True:
            errors.append(f"{evidence_id}: derived_from_expected_terms must not be true")
        if str(item.get("support_type") or "") not in VALID_SUPPORT_TYPES:
            errors.append(f"{evidence_id}: invalid support_type {item.get('support_type')!r}")
        if item.get("required") not in {True, False}:
            errors.append(f"{evidence_id}: required must be true or false")

        doc_id = str(item.get("doc_id") or "")
        if doc_id not in doc_ids:
            errors.append(f"{evidence_id}: doc_id does not exist in corpus: {doc_id}")

        support_text = compact_text(str(item.get("support_text") or ""))
        if not support_text:
            errors.append(f"{evidence_id}: missing support_text")
        elif doc_id in doc_texts and support_text not in doc_texts[doc_id]:
            errors.append(f"{evidence_id}: support_text is not present in corpus doc {doc_id}")

        chunk_id = str(item.get("chunk_id") or "")
        if chunk_id:
            chunk = chunk_by_id.get(chunk_id)
            if chunk is None:
                errors.append(f"{evidence_id}: chunk_id does not exist for configured chunking: {chunk_id}")
            elif support_text and support_text not in compact_text(str(chunk.get("text") or "")):
                errors.append(f"{evidence_id}: support_text is not present in chunk {chunk_id}")

    top_k = int((config.get("pipeline") or {}).get("top_k") or 10)
    chunk_top_k_ratio = len(corpus_chunks) / top_k if top_k else 0.0
    minimum_ratio = float(
        (config.get("dataset_metadata") or {}).get(
            "minimum_chunk_to_top_k_ratio",
            MIN_CHUNK_TOP_K_RATIO,
        )
    )
    warning_ratio = float(
        (config.get("dataset_metadata") or {}).get(
            "saturation_warning_chunk_to_top_k_ratio",
            SATURATION_WARNING_RATIO,
        )
    )
    if chunk_top_k_ratio < minimum_ratio:
        errors.append(
            f"chunk_count/top_k ratio must be >= {minimum_ratio:.1f}, got {chunk_top_k_ratio:.2f}"
        )
    elif chunk_top_k_ratio < warning_ratio:
        warnings.append(
            f"chunk_count/top_k ratio is {chunk_top_k_ratio:.2f}; retrieval metrics may saturate"
        )

    support_texts_by_question = {
        qid: [str(item.get("support_text") or "") for item in items]
        for qid, items in gold_by_question.items()
    }
    leakage_report = [
        leakage_flags(row, support_texts_by_question.get(str(row.get("question_id")), []))
        for row in answerable
    ]
    leakage_flags_count = sum(1 for row in leakage_report if row["flags"])
    if leakage_flags_count:
        warnings.append(
            f"lexical leakage report flagged {leakage_flags_count} answerable questions; review iteratively"
        )

    page_gold_count = sum(1 for item in gold_evidence if item.get("page") is not None)
    page_chunk_count = sum(1 for chunk in corpus_chunks if chunk.get("page_span"))
    summary = {
        "config_path": str(config_path.relative_to(ROOT_DIR)),
        "errors": errors,
        "warnings": warnings,
        "dataset_summary": {
            "num_docs": len(documents),
            "num_chunks": len(corpus_chunks),
            "num_questions": len(questions),
            "answerable_count": len(answerable),
            "unanswerable_count": len(unanswerable),
            "chunk_count_top_k_ratio": round(chunk_top_k_ratio, 3),
            "corpus_path": str(corpus_path.relative_to(ROOT_DIR)) if corpus_path.is_absolute() else str(corpus_path),
            "chunking_strategy": chunking_strategy,
            "chunking": chunking_diagnostics,
        },
        "question_type_distribution": dict(sorted(type_counts.items())),
        "difficulty_distribution": dict(sorted(Counter(row.get("difficulty") for row in questions).items())),
        "gold_evidence_summary": {
            "num_evidence_records": len(gold_evidence),
            "num_questions_with_gold": len(gold_by_question),
            "support_type_distribution": dict(
                sorted(Counter(str(item.get("support_type") or "") for item in gold_evidence).items())
            ),
            "required_evidence_count": sum(1 for item in gold_evidence if item.get("required") is True),
        },
        "coverage_summary": {
            "distractor_sensitive_questions": len(distractor_sensitive),
            "multi_chunk_questions": type_counts["multi_chunk_synthesis"],
            "table_structured_questions": type_counts["table_structured_data"],
            "mixed_language_questions": type_counts["mixed_language"],
            "page_metadata_gold_coverage": round(page_gold_count / len(gold_evidence), 3)
            if gold_evidence
            else 0.0,
            "page_metadata_chunk_coverage": round(page_chunk_count / len(corpus_chunks), 3)
            if corpus_chunks
            else 0.0,
        },
        "leakage_report": leakage_report,
    }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the public synthetic Naive RAG benchmark dataset.")
    parser.add_argument("--config", required=True, help="Path to benchmark_naive_rag_v1.yaml")
    parser.add_argument("--report", default=None, help="Optional JSON report path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = validate_dataset(Path(args.config))
    except Exception as exc:
        print(f"[ERROR] Benchmark dataset validation failed: {exc}", file=sys.stderr)
        return 2

    if args.report:
        report_path = repo_path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    dataset = summary["dataset_summary"]
    print(
        "[OK]" if not summary["errors"] else "[FAIL]",
        "synthetic benchmark:",
        f"{dataset['num_docs']} docs,",
        f"{dataset['num_chunks']} chunks,",
        f"{dataset['num_questions']} questions",
        f"({dataset['answerable_count']} answerable, {dataset['unanswerable_count']} unanswerable)",
    )
    print("question_type_distribution:", json.dumps(summary["question_type_distribution"], ensure_ascii=False, sort_keys=True))
    print("gold_evidence_summary:", json.dumps(summary["gold_evidence_summary"], ensure_ascii=False, sort_keys=True))
    for warning in summary["warnings"]:
        print(f"[WARN] {warning}")
    for error in summary["errors"]:
        print(f"[ERROR] {error}", file=sys.stderr)
    return 2 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
