#!/usr/bin/env python3
"""Local-only aggregate audit for private real-eval dataset quality.

The script validates label/index consistency before private real-eval runs.
It writes only aggregate/redacted artifacts and does not change retrieval,
reranking, prompts, chunking, or verifier behavior.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from scripts.private_data_quality_audit_utils import (
        assert_public_safe,
        compact,
        containment,
        hash_ref,
        jaccard,
        jsonl_rows,
        repo_path,
        require_safe_out_dir,
        write_json,
        write_jsonl,
    )
except ImportError:  # pragma: no cover - direct script execution
    from private_data_quality_audit_utils import (  # type: ignore
        assert_public_safe,
        compact,
        containment,
        hash_ref,
        jaccard,
        jsonl_rows,
        repo_path,
        require_safe_out_dir,
        write_json,
        write_jsonl,
    )


MIN_TOTAL_QUESTIONS = 13
MIN_ANSWERABLE_QUESTIONS = 10
MIN_UNANSWERABLE_QUESTIONS = 3
NEAR_DUPLICATE_THRESHOLD = 0.90
OVERLY_COPIED_THRESHOLD = 0.82
RETRIEVAL_SATURATION_RECALL = 1.0
RETRIEVAL_SATURATION_MIN_CASES = 1


def _load_index_payload(index_dir: Path) -> dict[str, Any]:
    index_file = index_dir / "index.json"
    if not index_file.is_file():
        raise FileNotFoundError("index metadata is missing")
    payload = json.loads(index_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("index metadata root must be an object")
    return payload


def _parse_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return default


def _row_evidence_items(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    wrapped = row.get("gold_evidence")
    if isinstance(wrapped, list):
        return [dict(item) for item in wrapped if isinstance(item, dict)]
    direct_keys = {
        "doc_id",
        "chunk_id",
        "support_text",
        "support_claim",
        "required_terms",
        "expected_terms",
        "page",
        "page_span",
    }
    if any(row.get(key) not in (None, "", []) for key in direct_keys):
        return [{key: row.get(key) for key in direct_keys if row.get(key) not in (None, "", [])}]
    return []


def _infer_answerable(row: Mapping[str, Any]) -> bool:
    if "answerable" in row:
        return _parse_bool(row.get("answerable"), default=True)
    if "gold_evidence" in row:
        evidence = row.get("gold_evidence")
        return bool(evidence) if isinstance(evidence, list) else True
    return True


def _question_type(row: Mapping[str, Any]) -> str:
    raw = str(row.get("query_type") or row.get("question_type") or row.get("type") or "").strip()
    if not raw:
        return "unspecified"
    if re.fullmatch(r"[A-Za-z0-9_.:-]+", raw):
        return raw[:60]
    return "non_ascii_or_custom_type"


def _term_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _load_questions(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = jsonl_rows(path)
    questions: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row_index, row in enumerate(rows, start=1):
        qid = str(row.get("question_id") or row.get("id") or "").strip()
        row_ref = hash_ref(f"{row_index}:{qid}", namespace="question-row")
        if not qid:
            flags.append(
                {
                    "schema_version": 1,
                    "audit_type": "private_eval_dataset",
                    "severity": "error",
                    "flag_type": "missing_question_identifier",
                    "question_ref": row_ref,
                }
            )
            qid = f"missing-question-id-{row_index}"
        if qid in seen:
            flags.append(
                {
                    "schema_version": 1,
                    "audit_type": "private_eval_dataset",
                    "severity": "error",
                    "flag_type": "duplicate_question_identifier",
                    "question_ref": hash_ref(qid, namespace="question"),
                }
            )
        seen.add(qid)
        questions.append(
            {
                "_qid": qid,
                "_ref": hash_ref(qid, namespace="question"),
                "_content": str(row.get("question") or row.get("query") or ""),
                "_answerable": _infer_answerable(row),
                "_type": _question_type(row),
                "_expected_terms": _term_list(row.get("expected_terms") or row.get("required_terms")),
            }
        )
    return questions, flags


def _load_evidence_by_question(path: Path) -> dict[str, list[dict[str, Any]]]:
    by_qid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in jsonl_rows(path):
        qid = str(row.get("question_id") or row.get("id") or "").strip()
        if not qid:
            continue
        by_qid[qid].extend(_row_evidence_items(row))
    return by_qid


def _index_maps(index: Mapping[str, Any]) -> dict[str, Any]:
    docs = [doc for doc in index.get("documents") or [] if isinstance(doc, dict)]
    chunks = [chunk for chunk in index.get("chunks") or [] if isinstance(chunk, dict)]
    document_refs = {str(doc.get("doc_id") or "") for doc in docs if str(doc.get("doc_id") or "").strip()}
    chunk_refs = {str(chunk.get("chunk_id") or "") for chunk in chunks if str(chunk.get("chunk_id") or "").strip()}
    content_by_chunk = {str(chunk.get("chunk_id") or ""): str(chunk.get("text") or "") for chunk in chunks}
    document_by_chunk = {str(chunk.get("chunk_id") or ""): str(chunk.get("doc_id") or "") for chunk in chunks}
    return {
        "document_refs": document_refs,
        "chunk_refs": chunk_refs,
        "content_by_chunk": content_by_chunk,
        "document_by_chunk": document_by_chunk,
        "chunk_count": len(chunks),
        "document_count": len(docs),
    }


def _evidence_content(items: list[dict[str, Any]], content_by_chunk: Mapping[str, str]) -> str:
    parts: list[str] = []
    for item in items:
        for key in ("support_text", "support_claim"):
            value = str(item.get(key) or "").strip()
            if value:
                parts.append(value)
        chunk_ref = str(item.get("chunk_id") or "")
        if chunk_ref and content_by_chunk.get(chunk_ref):
            parts.append(str(content_by_chunk[chunk_ref]))
    return "\n".join(parts)


def _evidence_terms(question: Mapping[str, Any], items: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = list(question.get("_expected_terms") or [])
    for item in items:
        terms.extend(_term_list(item.get("required_terms")))
        terms.extend(_term_list(item.get("expected_terms")))
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(term)
    return unique


def _coverage_ratio(terms: list[str], evidence_content: str) -> float | None:
    if not terms:
        return None
    lowered = evidence_content.lower()
    return sum(1 for term in terms if term.lower() in lowered) / len(terms)


def _has_non_empty_evidence(items: list[dict[str, Any]]) -> bool:
    return any(
        str(item.get("doc_id") or item.get("chunk_id") or item.get("support_text") or "").strip()
        for item in items
    )


def _reference_flags(
    questions: list[dict[str, Any]],
    evidence_by_qid: Mapping[str, list[dict[str, Any]]],
    index_maps: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    coverage_scores: list[float] = []
    copied_scores: list[float] = []
    expected_rows = 0
    full_coverage_count = 0
    answerable_missing_evidence = 0
    unanswerable_with_evidence = 0
    missing_document_ref_count = 0
    missing_chunk_ref_count = 0
    absent_document_count = 0
    absent_chunk_count = 0
    document_chunk_mismatch_count = 0

    document_refs = set(index_maps["document_refs"])
    chunk_refs = set(index_maps["chunk_refs"])
    content_by_chunk = index_maps["content_by_chunk"]
    document_by_chunk = index_maps["document_by_chunk"]

    for question in questions:
        qid = str(question["_qid"])
        qref = str(question["_ref"])
        items = list(evidence_by_qid.get(qid, []))
        answerable = bool(question["_answerable"])
        has_evidence = _has_non_empty_evidence(items)

        if answerable and not has_evidence:
            answerable_missing_evidence += 1
            flags.append(
                {
                    "schema_version": 1,
                    "audit_type": "private_eval_dataset",
                    "severity": "error",
                    "flag_type": "answerable_missing_evidence",
                    "question_ref": qref,
                }
            )
        if not answerable and has_evidence:
            unanswerable_with_evidence += 1
            flags.append(
                {
                    "schema_version": 1,
                    "audit_type": "private_eval_dataset",
                    "severity": "error",
                    "flag_type": "unanswerable_has_evidence",
                    "question_ref": qref,
                }
            )

        for item in items:
            document_ref = str(item.get("doc_id") or "").strip()
            chunk_ref = str(item.get("chunk_id") or "").strip()
            redacted_document_ref = hash_ref(document_ref, namespace="document")
            redacted_chunk_ref = hash_ref(chunk_ref, namespace="chunk")
            if answerable and not document_ref:
                missing_document_ref_count += 1
                flags.append(
                    {
                        "schema_version": 1,
                        "audit_type": "private_eval_dataset",
                        "severity": "error",
                        "flag_type": "missing_evidence_document_reference",
                        "question_ref": qref,
                    }
                )
            if answerable and not chunk_ref:
                missing_chunk_ref_count += 1
                flags.append(
                    {
                        "schema_version": 1,
                        "audit_type": "private_eval_dataset",
                        "severity": "error",
                        "flag_type": "missing_evidence_chunk_reference",
                        "question_ref": qref,
                        "document_ref": redacted_document_ref,
                    }
                )
            if document_ref and document_ref not in document_refs:
                absent_document_count += 1
                flags.append(
                    {
                        "schema_version": 1,
                        "audit_type": "private_eval_dataset",
                        "severity": "error",
                        "flag_type": "evidence_document_reference_absent_from_index",
                        "question_ref": qref,
                        "document_ref": redacted_document_ref,
                    }
                )
            if chunk_ref and chunk_ref not in chunk_refs:
                absent_chunk_count += 1
                flags.append(
                    {
                        "schema_version": 1,
                        "audit_type": "private_eval_dataset",
                        "severity": "error",
                        "flag_type": "evidence_chunk_reference_absent_from_index",
                        "question_ref": qref,
                        "chunk_ref": redacted_chunk_ref,
                    }
                )
            if (
                document_ref
                and chunk_ref
                and chunk_ref in document_by_chunk
                and document_by_chunk[chunk_ref] != document_ref
            ):
                document_chunk_mismatch_count += 1
                flags.append(
                    {
                        "schema_version": 1,
                        "audit_type": "private_eval_dataset",
                        "severity": "error",
                        "flag_type": "evidence_document_chunk_mismatch",
                        "question_ref": qref,
                        "document_ref": redacted_document_ref,
                        "chunk_ref": redacted_chunk_ref,
                    }
                )

        evidence_content = _evidence_content(items, content_by_chunk)
        terms_for_row = _evidence_terms(question, items)
        coverage = _coverage_ratio(terms_for_row, evidence_content)
        if coverage is not None:
            expected_rows += 1
            coverage_scores.append(coverage)
            if coverage >= 1.0:
                full_coverage_count += 1
            else:
                flags.append(
                    {
                        "schema_version": 1,
                        "audit_type": "private_eval_dataset",
                        "severity": "warning",
                        "flag_type": "expected_terms_not_fully_covered",
                        "question_ref": qref,
                        "metrics": {"coverage_ratio": round(coverage, 4), "term_count": len(terms_for_row)},
                    }
                )
        copied_score = containment(question.get("_content") or "", evidence_content)
        if question.get("_content") and evidence_content:
            copied_scores.append(copied_score)
            if copied_score >= OVERLY_COPIED_THRESHOLD:
                flags.append(
                    {
                        "schema_version": 1,
                        "audit_type": "private_eval_dataset",
                        "severity": "warning",
                        "flag_type": "overly_copied_question",
                        "question_ref": qref,
                        "metrics": {"similarity_score": round(copied_score, 4)},
                    }
                )

    mean_coverage = sum(coverage_scores) / len(coverage_scores) if coverage_scores else None
    return flags, {
        "answerable_missing_evidence_count": answerable_missing_evidence,
        "unanswerable_with_evidence_count": unanswerable_with_evidence,
        "missing_document_reference_count": missing_document_ref_count,
        "missing_chunk_reference_count": missing_chunk_ref_count,
        "absent_document_reference_count": absent_document_count,
        "absent_chunk_reference_count": absent_chunk_count,
        "document_chunk_mismatch_count": document_chunk_mismatch_count,
        "expected_terms_rows": expected_rows,
        "expected_terms_full_coverage_count": full_coverage_count,
        "expected_terms_mean_coverage": round(mean_coverage, 6) if mean_coverage is not None else None,
        "overly_copied_question_count": sum(1 for score in copied_scores if score >= OVERLY_COPIED_THRESHOLD),
    }


def _duplicate_content_flags(questions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    flags: list[dict[str, Any]] = []
    exact_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for question in questions:
        content = compact(question.get("_content") or "").lower()
        if content:
            exact_buckets[content].append(question)

    exact_duplicate_count = 0
    near_duplicate_count = 0
    for bucket in exact_buckets.values():
        if len(bucket) <= 1:
            continue
        exact_duplicate_count += len(bucket) - 1
        flags.append(
            {
                "schema_version": 1,
                "audit_type": "private_eval_dataset",
                "severity": "warning",
                "flag_type": "duplicate_question_content",
                "pair_ref": hash_ref("|".join(sorted(item["_qid"] for item in bucket)), namespace="question-pair"),
                "metrics": {"duplicate_count": len(bucket)},
            }
        )

    max_pairs = 100
    pair_flags = 0
    for idx, left in enumerate(questions):
        left_content = str(left.get("_content") or "")
        if not left_content:
            continue
        for right in questions[idx + 1 :]:
            right_content = str(right.get("_content") or "")
            if not right_content:
                continue
            if compact(left_content).lower() == compact(right_content).lower():
                continue
            score = jaccard(left_content, right_content)
            if score >= NEAR_DUPLICATE_THRESHOLD:
                near_duplicate_count += 1
                if pair_flags < max_pairs:
                    flags.append(
                        {
                            "schema_version": 1,
                            "audit_type": "private_eval_dataset",
                            "severity": "warning",
                            "flag_type": "near_duplicate_question_content",
                            "pair_ref": hash_ref(
                                "|".join(sorted([str(left["_qid"]), str(right["_qid"])])),
                                namespace="question-pair",
                            ),
                            "metrics": {"similarity_score": round(score, 4)},
                        }
                    )
                    pair_flags += 1
    return flags, {
        "duplicate_content_count": exact_duplicate_count,
        "near_duplicate_pair_count": near_duplicate_count,
    }


def _recall_at_10(retrieved: list[str], expected: list[str]) -> float | None:
    expected_set = {item for item in expected if item}
    if not expected_set:
        return None
    retrieved_set = set(retrieved[:10])
    return len(expected_set & retrieved_set) / len(expected_set)


def _retrieval_probe(
    *,
    questions: list[dict[str, Any]],
    evidence_by_qid: Mapping[str, list[dict[str, Any]]],
    index_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    flags: list[dict[str, Any]] = []
    try:
        from rag_indexing import load_index
        from rag_retrieval import embed_query_for_index

        index = load_index(index_dir)
        vector_store = index.get("_vector_store")
        if vector_store is None or len(vector_store) == 0:
            raise ValueError("vector store unavailable")
        index_to_chunk = {
            int(chunk.get("embedding_idx")): str(chunk.get("chunk_id") or "")
            for chunk in index.get("chunks") or []
            if isinstance(chunk, dict) and chunk.get("embedding_idx") is not None
        }
        recalls: list[float] = []
        for question in questions:
            if not question.get("_answerable") or not question.get("_content"):
                continue
            gold_refs = [
                str(item.get("chunk_id") or "")
                for item in evidence_by_qid.get(str(question["_qid"]), [])
                if str(item.get("chunk_id") or "").strip()
            ]
            if not gold_refs:
                continue
            query_vector = embed_query_for_index(
                str(question["_content"]),
                index.get("embedding") if isinstance(index.get("embedding"), dict) else {},
            )
            retrieved = [
                index_to_chunk.get(int(idx), "")
                for idx, _score in vector_store.query(query_vector, top_k=10)
            ]
            recall = _recall_at_10(retrieved, gold_refs)
            if recall is not None:
                recalls.append(recall)
        mean_recall = sum(recalls) / len(recalls) if recalls else None
        full_count = sum(1 for value in recalls if value >= RETRIEVAL_SATURATION_RECALL)
        saturated = bool(
            recalls
            and len(recalls) >= RETRIEVAL_SATURATION_MIN_CASES
            and full_count == len(recalls)
        )
        if saturated:
            flags.append(
                {
                    "schema_version": 1,
                    "audit_type": "private_eval_dataset",
                    "severity": "warning",
                    "flag_type": "retrieval_saturation_warning",
                    "metrics": {"recall_at_10_mean": round(float(mean_recall), 6), "evaluated_count": len(recalls)},
                }
            )
        return {
            "attempted": True,
            "evaluated_count": len(recalls),
            "recall_at_10_mean": round(float(mean_recall), 6) if mean_recall is not None else None,
            "full_recall_at_10_count": full_count,
            "saturation_warning": saturated,
        }, flags
    except Exception:
        return {
            "attempted": False,
            "evaluated_count": 0,
            "recall_at_10_mean": None,
            "full_recall_at_10_count": 0,
            "saturation_warning": False,
        }, []


def _size_flags(total: int, answerable: int, unanswerable: int) -> list[dict[str, Any]]:
    checks = [
        ("minimum_total_questions", total, MIN_TOTAL_QUESTIONS),
        ("minimum_answerable_questions", answerable, MIN_ANSWERABLE_QUESTIONS),
        ("minimum_unanswerable_questions", unanswerable, MIN_UNANSWERABLE_QUESTIONS),
    ]
    flags: list[dict[str, Any]] = []
    for flag_type, actual, minimum in checks:
        if actual < minimum:
            flags.append(
                {
                    "schema_version": 1,
                    "audit_type": "private_eval_dataset",
                    "severity": "warning",
                    "flag_type": flag_type,
                    "metrics": {"actual_count": actual, "minimum_count": minimum},
                }
            )
    return flags


def _render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Private Eval Dataset Audit",
        "",
        "Local-only aggregate audit. Raw prompts, answers, evidence content, exact local locations, and raw identifiers are omitted.",
        "",
        "## Verdict",
        "",
        f"- Passed: `{summary['passed']}`",
        f"- Error flags: {summary['flag_counts']['error']}",
        f"- Warning flags: {summary['flag_counts']['warning']}",
        "",
        "## Dataset Counts",
        "",
        f"- Total questions: {summary['question_count']}",
        f"- Answerable: {summary['answerable_count']}",
        f"- Unanswerable: {summary['unanswerable_count']}",
        f"- Evidence records: {summary['evidence_record_count']}",
        "",
        "## Consistency",
        "",
        f"- Duplicate identifiers: {summary['question_identifier_uniqueness']['duplicate_count']}",
        f"- Answerable missing evidence: {summary['label_consistency']['answerable_missing_evidence_count']}",
        f"- Unanswerable with evidence: {summary['label_consistency']['unanswerable_with_evidence_count']}",
        f"- Missing chunk references: {summary['index_reference_coverage']['missing_chunk_reference_count']}",
        f"- Absent chunk references: {summary['index_reference_coverage']['absent_chunk_reference_count']}",
        "",
        "## Coverage",
        "",
        f"- Expected term rows: {summary['expected_terms_coverage']['row_count']}",
        f"- Full expected term coverage rows: {summary['expected_terms_coverage']['full_coverage_count']}",
        f"- Mean expected term coverage: {summary['expected_terms_coverage']['mean_coverage']}",
        "",
        "## Retrieval Saturation Probe",
        "",
        f"- Attempted: `{summary['retrieval_saturation_probe']['attempted']}`",
        f"- Evaluated cases: {summary['retrieval_saturation_probe']['evaluated_count']}",
        f"- Recall@10 mean: {summary['retrieval_saturation_probe']['recall_at_10_mean']}",
        f"- Saturation warning: `{summary['retrieval_saturation_probe']['saturation_warning']}`",
        "",
        "## Question Type Distribution",
        "",
    ]
    distribution = summary["question_type_distribution"]
    if distribution:
        for key, count in sorted(distribution.items()):
            lines.append(f"- `{key}`: {count}")
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def build_eval_dataset_audit(
    *,
    questions_path: Path,
    gold_evidence_path: Path,
    index_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    questions, question_flags = _load_questions(questions_path)
    evidence_by_qid = _load_evidence_by_question(gold_evidence_path)
    index = _load_index_payload(index_dir)
    maps = _index_maps(index)

    flags: list[dict[str, Any]] = list(question_flags)
    reference_flags, reference_summary = _reference_flags(questions, evidence_by_qid, maps)
    duplicate_flags, duplicate_summary = _duplicate_content_flags(questions)
    retrieval_probe, retrieval_flags = _retrieval_probe(
        questions=questions,
        evidence_by_qid=evidence_by_qid,
        index_dir=index_dir,
    )
    flags.extend(reference_flags)
    flags.extend(duplicate_flags)
    flags.extend(retrieval_flags)

    answerable_count = sum(1 for question in questions if question["_answerable"])
    unanswerable_count = len(questions) - answerable_count
    flags.extend(_size_flags(len(questions), answerable_count, unanswerable_count))

    evidence_record_count = sum(len(items) for items in evidence_by_qid.values())
    duplicate_identifier_count = sum(
        1 for flag in flags if flag.get("flag_type") == "duplicate_question_identifier"
    )
    error_count = sum(1 for flag in flags if flag.get("severity") == "error")
    warning_count = sum(1 for flag in flags if flag.get("severity") == "warning")
    type_counts = Counter(str(question["_type"]) for question in questions)

    summary = {
        "schema_version": 1,
        "audit_type": "private_eval_dataset",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "passed": error_count == 0,
        "question_count": len(questions),
        "answerable_count": answerable_count,
        "unanswerable_count": unanswerable_count,
        "evidence_record_count": evidence_record_count,
        "question_identifier_uniqueness": {
            "unique_count": len({str(question["_qid"]) for question in questions}),
            "duplicate_count": duplicate_identifier_count,
        },
        "label_consistency": {
            "answerable_missing_evidence_count": reference_summary["answerable_missing_evidence_count"],
            "unanswerable_with_evidence_count": reference_summary["unanswerable_with_evidence_count"],
        },
        "index_reference_coverage": {
            "index_document_count": maps["document_count"],
            "index_chunk_count": maps["chunk_count"],
            "missing_document_reference_count": reference_summary["missing_document_reference_count"],
            "missing_chunk_reference_count": reference_summary["missing_chunk_reference_count"],
            "absent_document_reference_count": reference_summary["absent_document_reference_count"],
            "absent_chunk_reference_count": reference_summary["absent_chunk_reference_count"],
            "document_chunk_mismatch_count": reference_summary["document_chunk_mismatch_count"],
        },
        "expected_terms_coverage": {
            "row_count": reference_summary["expected_terms_rows"],
            "full_coverage_count": reference_summary["expected_terms_full_coverage_count"],
            "mean_coverage": reference_summary["expected_terms_mean_coverage"],
        },
        "question_type_distribution": dict(sorted(type_counts.items())),
        "duplicate_question_detection": duplicate_summary,
        "overly_copied_question_detection": {
            "flagged_count": reference_summary["overly_copied_question_count"],
            "threshold": OVERLY_COPIED_THRESHOLD,
        },
        "retrieval_saturation_probe": retrieval_probe,
        "minimum_size_checks": {
            "minimum_total_questions": MIN_TOTAL_QUESTIONS,
            "minimum_answerable_questions": MIN_ANSWERABLE_QUESTIONS,
            "minimum_unanswerable_questions": MIN_UNANSWERABLE_QUESTIONS,
        },
        "flag_counts": {"error": error_count, "warning": warning_count, "total": len(flags)},
        "privacy": {
            "aggregate_only": True,
            "redacted_references_only": True,
            "raw_private_content_omitted": True,
        },
    }
    assert_public_safe(summary)
    for flag in flags:
        assert_public_safe(flag)
    return summary, flags, _render_report(summary)


def run_audit(
    *,
    questions_path: Path,
    gold_evidence_path: Path,
    index_dir: Path,
    out_dir: Path,
) -> dict[str, Any]:
    questions_path = repo_path(questions_path)
    gold_evidence_path = repo_path(gold_evidence_path)
    index_dir = repo_path(index_dir)
    out_dir = repo_path(out_dir)
    require_safe_out_dir(out_dir)

    summary, flags, report = build_eval_dataset_audit(
        questions_path=questions_path,
        gold_evidence_path=gold_evidence_path,
        index_dir=index_dir,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "eval_dataset_summary.json", summary)
    (out_dir / "eval_dataset_report.md").write_text(report, encoding="utf-8")
    write_jsonl(out_dir / "eval_dataset_flags.jsonl", flags)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", required=True)
    parser.add_argument("--gold-evidence", required=True)
    parser.add_argument("--index-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = run_audit(
            questions_path=Path(args.questions),
            gold_evidence_path=Path(args.gold_evidence),
            index_dir=Path(args.index_dir),
            out_dir=Path(args.out_dir),
        )
    except Exception as exc:
        print(f"[ERROR] private eval dataset audit failed: {exc}", file=sys.stderr)
        return 2
    print(
        "[OK]" if summary["passed"] else "[FAIL]",
        "private eval dataset audit:",
        f"questions={summary['question_count']}",
        f"errors={summary['flag_counts']['error']}",
        f"warnings={summary['flag_counts']['warning']}",
    )
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
