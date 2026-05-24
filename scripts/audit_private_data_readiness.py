#!/usr/bin/env python3
"""Aggregate-only local readiness audit before private real-data improvement.

The audit reads local private inputs and existing local run artifacts, then
writes only aggregate/redacted readiness outputs. It does not run retrieval,
reranking, prompt generation, chunking, or verification.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
from typing import Any, Mapping, Sequence

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = "configs/eval/private_real_eval.local.yaml"
DEFAULT_OUT_DIR = "experiments/private_runs/readiness_audit"
SCHEMA_VERSION = 1

SHORT_DOCUMENT_CHARS = 500
SUSPICIOUS_GARBLED_RATE = 0.01
LOW_EXPECTED_TERM_COVERAGE = 0.5
RETRIEVAL_SATURATION_RECALL10 = 0.95

FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "question",
        "raw_question",
        "answer",
        "raw_answer",
        "answer_text",
        "raw_evidence",
        "evidence",
        "gold_evidence",
        "retrieved_chunks",
        "retrieved_chunk_ids",
        "gold_chunk_ids",
        "text",
        "raw_text",
        "document_text",
        "text_preview",
        "support_text",
        "filename",
        "file_name",
        "file_path",
        "source_path",
        "path",
        "absolute_path",
        "config_path",
        "documents_dir",
        "data_list_path",
        "questions_path",
        "gold_evidence_path",
        "index_dir",
        "output_dir",
        "doc_id",
        "chunk_id",
    }
)
ABSOLUTE_LOCAL_PATH_RE = re.compile(
    r"(^|[\s'\"])(?:/Users/|/private/|/home/|/Volumes/|[A-Za-z]:[\\/])"
)
SAFE_FAILURE_TYPE_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
TABLE_RE = re.compile(r"(<table\b|</td>|rowspan=|colspan=|\|[^\n]+\|)")
DATE_RE = re.compile(r"\b\d{4}\s*[.\-/년]\s*\d{1,2}(?:\s*[.\-/월]\s*\d{1,2})?")
AMOUNT_RE = re.compile(r"(\d{1,3}(?:,\d{3})+\s*(?:원|천원|만원|억원)?|사업비|예산|금액)")
SCORE_RE = re.compile(r"(\d+(?:\.\d+)?\s*(?:점|%)|배점|평가점수|score)", re.IGNORECASE)
GARBLED_RE = re.compile(r"[\uFFFD\x00-\x08\x0B\x0C\x0E-\x1F]|(?:Ã|Â|�)")


def repo_path(value: str | Path, repo_root: Path = ROOT_DIR) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else repo_root / path


def rel_to_repo(path: Path, repo_root: Path = ROOT_DIR) -> str | None:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return None


def is_gitignored_or_outside(path: Path, repo_root: Path = ROOT_DIR) -> bool:
    rel = rel_to_repo(path, repo_root)
    if rel is None:
        return True
    candidates = [rel]
    if not rel.endswith("/"):
        candidates.append(rel + "/")
        candidates.append(rel + "/.readiness-audit-probe")
    for candidate in candidates:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", candidate],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return True
    return False


def assert_public_safe_payload(payload: Mapping[str, Any]) -> None:
    """Reject keys/values that would expose private raw fields in summaries."""

    violations: list[str] = []

    def walk(node: Any, trail: str) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                key_text = str(key)
                key_lower = key_text.lower()
                next_trail = f"{trail}.{key_text}".strip(".")
                if key_lower in FORBIDDEN_PUBLIC_KEYS:
                    violations.append(next_trail)
                if ABSOLUTE_LOCAL_PATH_RE.search(key_text):
                    violations.append(next_trail)
                walk(value, next_trail)
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                walk(item, f"{trail}[{idx}]")
        elif isinstance(node, str):
            if ABSOLUTE_LOCAL_PATH_RE.search(node):
                violations.append(trail or "$")

    walk(payload, "")
    if violations:
        raise ValueError(
            "public-safe readiness summary contains forbidden private fields: "
            + ", ".join(violations[:10])
        )


def _load_yaml(path: Path) -> tuple[dict[str, Any], list[str]]:
    if not path.is_file():
        return {}, ["config_missing"]
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}, ["config_invalid_yaml"]
    if not isinstance(payload, dict):
        return {}, ["config_root_not_mapping"]
    return payload, []


def _load_json(path: Path) -> tuple[dict[str, Any], list[str]]:
    if not path.is_file():
        return {}, ["json_missing"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, ["json_invalid"]
    if not isinstance(payload, dict):
        return {}, ["json_root_not_mapping"]
    return payload, []


def _jsonl_rows(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.is_file():
        return [], ["jsonl_missing"]
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], ["jsonl_unreadable"]
    for lineno, line in enumerate(lines, start=1):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            errors.append("jsonl_invalid_json")
            continue
        if not isinstance(payload, dict):
            errors.append("jsonl_row_not_mapping")
            continue
        rows.append(payload)
    return rows, errors


def _csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file():
        return [], ["csv_missing"]
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            return [dict(row) for row in reader], []
    except (OSError, csv.Error, UnicodeDecodeError):
        return [], ["csv_unreadable"]


def _text_from_manifest_row(row: Mapping[str, Any]) -> str:
    for key in ("텍스트", "text", "body", "content"):
        value = row.get(key)
        if value is not None:
            return str(value).strip()
    return ""


def _file_value_from_manifest_row(row: Mapping[str, Any]) -> str:
    for key in ("file_path", "파일명", "file_name", "filename"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _resolve_manifest_file(value: str, documents_dir: Path, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    if value.startswith("data/") or value.startswith("./data/"):
        return repo_path(path, repo_root)
    return documents_dir / path


def _char_len(text: str) -> int:
    return len(text.strip())


def _garbled_count(text: str) -> int:
    return len(GARBLED_RE.findall(text))


def _rate(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 6)


def _percentile(values: Sequence[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return int(ordered[0])
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return int(round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction))


def _length_summary(values: Sequence[int]) -> dict[str, int | None]:
    return {
        "min": min(values) if values else None,
        "p50": int(round(statistics.median(values))) if values else None,
        "p95": _percentile(values, 0.95),
        "max": max(values) if values else None,
    }


def _coverage_summary(texts: Sequence[str]) -> dict[str, Any]:
    denominator = len(texts)
    table = sum(1 for text in texts if TABLE_RE.search(text))
    date = sum(1 for text in texts if DATE_RE.search(text))
    amount = sum(1 for text in texts if AMOUNT_RE.search(text))
    score = sum(1 for text in texts if SCORE_RE.search(text))
    return {
        "sample_count": denominator,
        "table_like_rate": _rate(table, denominator),
        "date_like_rate": _rate(date, denominator),
        "amount_like_rate": _rate(amount, denominator),
        "score_like_rate": _rate(score, denominator),
    }


def _has_page_metadata(item: Mapping[str, Any]) -> bool:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
    for node in (item, metadata):
        for key in ("page", "page_number", "page_span", "page_start", "page_end", "pages"):
            value = node.get(key)
            if value not in (None, "", []):
                return True
    return False


def _index_chunks(index_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    payload, errors = _load_json(index_dir / "index.json")
    if errors:
        return [], {}, ["index_metadata_" + errors[0]]
    chunks = payload.get("chunks")
    if not isinstance(chunks, list):
        return [], payload, ["index_chunks_missing"]
    cleaned = [chunk for chunk in chunks if isinstance(chunk, dict)]
    return cleaned, payload, []


def _build_count(payload: Mapping[str, Any], key: str) -> int | None:
    build = payload.get("build") if isinstance(payload.get("build"), Mapping) else {}
    value = build.get(key)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "answerable"}:
            return True
        if normalized in {"0", "false", "no", "n", "unanswerable"}:
            return False
    return bool(value)


def _expected_terms(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("expected_terms") or row.get("required_terms") or []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _evidence_items(row: Mapping[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    evidence = row.get("gold_evidence")
    if evidence is None:
        direct = {
            key: row.get(key)
            for key in ("doc_id", "chunk_id", "page_span", "support_text", "required_terms")
            if row.get(key) not in (None, "", [])
        }
        return ([direct] if direct else []), False
    if not isinstance(evidence, list):
        return [], True
    items = [dict(item) for item in evidence if isinstance(item, dict)]
    invalid = len(items) != len(evidence)
    return items, invalid


def _evidence_has_payload(item: Mapping[str, Any]) -> bool:
    for key in ("doc_id", "chunk_id", "page_span", "support_text"):
        if item.get(key) not in (None, "", []):
            return True
    return False


def _question_id(row: Mapping[str, Any]) -> str:
    return str(row.get("question_id") or "").strip()


def _metric_mean(block: Any) -> float | None:
    if isinstance(block, Mapping):
        value = block.get("mean")
    else:
        value = block
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    return None


def _latest_metrics(output_dir: Path, audit_out_dir: Path) -> tuple[dict[str, Any] | None, int]:
    if not output_dir.is_dir():
        return None, 0
    candidates: list[Path] = []
    for path in output_dir.rglob("metrics.json"):
        try:
            path.resolve().relative_to(audit_out_dir.resolve())
            continue
        except ValueError:
            pass
        candidates.append(path)
    if not candidates:
        return None, 0
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    payload, errors = _load_json(candidates[0])
    if errors:
        return None, len(candidates)
    return payload, len(candidates)


def _failure_case_path(output_dir: Path, audit_out_dir: Path) -> Path | None:
    if not output_dir.is_dir():
        return None
    candidates: list[Path] = []
    for path in output_dir.rglob("failure_cases.jsonl"):
        try:
            path.resolve().relative_to(audit_out_dir.resolve())
            continue
        except ValueError:
            pass
        candidates.append(path)
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0]


def _safe_failure_counts(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, int], int]:
    counts: dict[str, int] = {}
    rejected = 0
    for row in rows:
        values = [row.get("failure_type")]
        additional = row.get("additional_failure_types")
        if isinstance(additional, list):
            values.extend(additional)
        for value in values:
            label = str(value or "").strip()
            if not label:
                continue
            if not SAFE_FAILURE_TYPE_RE.fullmatch(label):
                rejected += 1
                continue
            counts[label] = counts.get(label, 0) + 1
    return counts, rejected


def _flag(
    flags: list[dict[str, Any]],
    *,
    severity: str,
    surface: str,
    code: str,
    count: int | float = 1,
) -> None:
    if isinstance(count, (int, float)) and count <= 0:
        return
    flags.append(
        {
            "schema_version": SCHEMA_VERSION,
            "severity": severity,
            "surface": surface,
            "code": code,
            "count": count,
        }
    )


def _audit_documents(
    config: Mapping[str, Any],
    repo_root: Path,
    flags: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    documents_dir = repo_path(str(config.get("documents_dir") or ""), repo_root)
    data_list_path = repo_path(str(config.get("data_list_path") or ""), repo_root)
    rows, errors = _csv_rows(data_list_path)
    for error in errors:
        _flag(flags, severity="blocker", surface="parse_quality", code=error)
    if not documents_dir.is_dir():
        _flag(
            flags,
            severity="blocker",
            surface="parse_quality",
            code="documents_dir_missing",
        )

    texts = [_text_from_manifest_row(row) for row in rows]
    lengths = [_char_len(text) for text in texts]
    empty = sum(1 for length in lengths if length == 0)
    short = sum(1 for length in lengths if 0 < length < SHORT_DOCUMENT_CHARS)
    char_total = sum(lengths)
    garbled = sum(_garbled_count(text) for text in texts)
    suspicious = sum(
        1
        for text in texts
        if text
        and (
            _rate(_garbled_count(text), max(len(text), 1)) > SUSPICIOUS_GARBLED_RATE
            or len(set(text)) <= 5
        )
    )

    missing_source_refs = 0
    missing_source_files = 0
    if documents_dir.is_dir():
        for row in rows:
            file_value = _file_value_from_manifest_row(row)
            if not file_value:
                missing_source_refs += 1
                continue
            if not _resolve_manifest_file(file_value, documents_dir, repo_root).exists():
                missing_source_files += 1

    if not rows:
        _flag(flags, severity="blocker", surface="parse_quality", code="document_manifest_empty")
    if empty:
        _flag(flags, severity="blocker", surface="parse_quality", code="empty_documents", count=empty)
    if short:
        _flag(flags, severity="warning", surface="parse_quality", code="short_documents", count=short)
    if suspicious:
        _flag(
            flags,
            severity="warning",
            surface="parse_quality",
            code="suspicious_documents",
            count=suspicious,
        )
    if missing_source_files:
        _flag(
            flags,
            severity="warning",
            surface="parse_quality",
            code="manifest_source_files_missing",
            count=missing_source_files,
        )

    summary = {
        "document_count": len(rows),
        "parsed_document_count": sum(1 for length in lengths if length > 0),
        "empty_document_count": empty,
        "short_document_count": short,
        "suspicious_document_count": suspicious,
        "missing_source_reference_count": missing_source_refs,
        "missing_source_file_count": missing_source_files,
        "garbled_character_rate": _rate(garbled, char_total),
        "document_length": _length_summary(lengths),
        "token_coverage": _coverage_summary(texts),
    }
    return summary, texts


def _audit_index(
    config: Mapping[str, Any],
    repo_root: Path,
    flags: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, str], set[str]]:
    index_dir = repo_path(str(config.get("index_dir") or ""), repo_root)
    chunks, payload, errors = _index_chunks(index_dir)
    for error in errors:
        _flag(flags, severity="blocker", surface="index_integrity", code=error)

    chunk_text_by_id: dict[str, str] = {}
    chunk_ids: set[str] = set()
    missing_chunk_id = 0
    lengths: list[int] = []
    text_hashes: list[str] = []
    missing_page = 0
    garbled = 0
    char_total = 0
    chunk_texts: list[str] = []
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        text = str(chunk.get("text") or "")
        if not chunk_id:
            missing_chunk_id += 1
        else:
            chunk_ids.add(chunk_id)
            chunk_text_by_id[chunk_id] = text
        length = _char_len(text)
        lengths.append(length)
        chunk_texts.append(text)
        char_total += length
        garbled += _garbled_count(text)
        normalized = " ".join(text.split())
        if normalized:
            text_hashes.append(hashlib.sha256(normalized.encode("utf-8")).hexdigest())
        if not _has_page_metadata(chunk):
            missing_page += 1

    duplicate_count = max(0, len(text_hashes) - len(set(text_hashes)))
    if not chunks:
        _flag(flags, severity="blocker", surface="index_integrity", code="index_has_no_chunks")
    if missing_chunk_id:
        _flag(
            flags,
            severity="blocker",
            surface="index_integrity",
            code="index_chunk_id_missing",
            count=missing_chunk_id,
        )
    if duplicate_count:
        _flag(
            flags,
            severity="warning",
            surface="index_integrity",
            code="duplicate_chunks_detected",
            count=duplicate_count,
        )
    if missing_page and chunks:
        _flag(
            flags,
            severity="warning",
            surface="index_integrity",
            code="page_metadata_missing",
            count=missing_page,
        )

    chunk_count = len(chunks) or _build_count(payload, "num_chunks") or 0
    summary = {
        "chunk_count": chunk_count,
        "chunk_length": _length_summary(lengths),
        "duplicate_chunk_ratio": _rate(duplicate_count, len(text_hashes)),
        "missing_page_metadata_rate": _rate(missing_page, len(chunks)),
        "garbled_character_rate": _rate(garbled, char_total),
        "token_coverage": _coverage_summary(chunk_texts),
        "index_document_count": _build_count(payload, "num_documents"),
        "chunk_id_missing_count": missing_chunk_id,
    }
    return summary, chunk_text_by_id, chunk_ids


def _audit_eval_dataset(
    config: Mapping[str, Any],
    repo_root: Path,
    chunk_text_by_id: Mapping[str, str],
    index_chunk_ids: set[str],
    flags: list[dict[str, Any]],
) -> dict[str, Any]:
    gold_path = repo_path(str(config.get("gold_evidence_path") or ""), repo_root)
    questions_path = repo_path(str(config.get("questions_path") or config.get("gold_evidence_path") or ""), repo_root)
    question_rows, question_errors = _jsonl_rows(questions_path)
    gold_rows, gold_errors = _jsonl_rows(gold_path)
    for error in question_errors:
        _flag(flags, severity="blocker", surface="eval_dataset_quality", code="questions_" + error)
    for error in gold_errors:
        _flag(flags, severity="blocker", surface="eval_dataset_quality", code="gold_" + error)

    seen_qids: set[str] = set()
    duplicate_qids = 0
    missing_qids = 0
    answerable_qids: set[str] = set()
    unanswerable_qids: set[str] = set()
    expected_by_qid: dict[str, list[str]] = {}
    for row in question_rows:
        qid = _question_id(row)
        if not qid:
            missing_qids += 1
            continue
        if qid in seen_qids:
            duplicate_qids += 1
        seen_qids.add(qid)
        answerable = _as_bool(row.get("answerable", True), default=True)
        if answerable:
            answerable_qids.add(qid)
        else:
            unanswerable_qids.add(qid)
        terms = _expected_terms(row)
        if terms:
            expected_by_qid[qid] = terms

    gold_by_qid: dict[str, list[dict[str, Any]]] = {}
    invalid_gold_shape = 0
    for row in gold_rows:
        qid = _question_id(row)
        if not qid:
            continue
        items, invalid = _evidence_items(row)
        invalid_gold_shape += int(invalid)
        gold_by_qid.setdefault(qid, []).extend(items)

    answerable_without_gold = 0
    unanswerable_with_gold = 0
    gold_chunk_ids: set[str] = set()
    for qid in answerable_qids:
        explicit_items = [
            item
            for item in gold_by_qid.get(qid, [])
            if str(item.get("chunk_id") or "").strip()
        ]
        if not explicit_items:
            answerable_without_gold += 1
        for item in explicit_items:
            gold_chunk_ids.add(str(item.get("chunk_id") or "").strip())
    for qid in unanswerable_qids:
        if any(_evidence_has_payload(item) for item in gold_by_qid.get(qid, [])):
            unanswerable_with_gold += 1

    missing_gold_chunks = sorted(chunk_id for chunk_id in gold_chunk_ids if chunk_id not in index_chunk_ids)
    expected_questions = 0
    expected_answerable = 0
    expected_gold_coverage_ratios: list[float] = []
    for qid, terms in expected_by_qid.items():
        expected_questions += 1
        if qid in answerable_qids:
            expected_answerable += 1
        evidence_text = " ".join(
            chunk_text_by_id.get(str(item.get("chunk_id") or "").strip(), "")
            for item in gold_by_qid.get(qid, [])
        ).lower()
        if not evidence_text or not terms:
            continue
        covered = sum(1 for term in terms if term.lower() in evidence_text)
        expected_gold_coverage_ratios.append(covered / len(terms))

    if duplicate_qids:
        _flag(
            flags,
            severity="blocker",
            surface="eval_dataset_quality",
            code="duplicate_question_id",
            count=duplicate_qids,
        )
    if missing_qids:
        _flag(
            flags,
            severity="blocker",
            surface="eval_dataset_quality",
            code="missing_question_id",
            count=missing_qids,
        )
    if invalid_gold_shape:
        _flag(
            flags,
            severity="blocker",
            surface="eval_dataset_quality",
            code="invalid_gold_shape",
            count=invalid_gold_shape,
        )
    if answerable_without_gold:
        _flag(
            flags,
            severity="blocker",
            surface="eval_dataset_quality",
            code="answerable_without_gold_evidence",
            count=answerable_without_gold,
        )
    if unanswerable_with_gold:
        _flag(
            flags,
            severity="blocker",
            surface="eval_dataset_quality",
            code="unanswerable_with_gold_evidence",
            count=unanswerable_with_gold,
        )
    if missing_gold_chunks:
        _flag(
            flags,
            severity="blocker",
            surface="index_integrity",
            code="gold_chunk_missing_from_index",
            count=len(missing_gold_chunks),
        )
    if expected_gold_coverage_ratios:
        mean_coverage = round(statistics.mean(expected_gold_coverage_ratios), 6)
        if mean_coverage < LOW_EXPECTED_TERM_COVERAGE:
            _flag(
                flags,
                severity="warning",
                surface="eval_dataset_quality",
                code="expected_terms_low_gold_coverage",
            )
    else:
        mean_coverage = None

    return {
        "question_count": len(question_rows),
        "answerable_count": len(answerable_qids),
        "unanswerable_count": len(unanswerable_qids),
        "duplicate_question_id_count": duplicate_qids,
        "missing_question_id_count": missing_qids,
        "answerable_without_gold_evidence_count": answerable_without_gold,
        "unanswerable_with_gold_evidence_count": unanswerable_with_gold,
        "gold_chunk_missing_from_index_count": len(missing_gold_chunks),
        "expected_terms": {
            "question_count": expected_questions,
            "answerable_question_count": expected_answerable,
            "gold_text_mean_term_coverage": mean_coverage,
            "gold_text_coverage_sample_count": len(expected_gold_coverage_ratios),
        },
    }


def _audit_baseline_metrics(
    config: Mapping[str, Any],
    repo_root: Path,
    audit_out_dir: Path,
    flags: list[dict[str, Any]],
) -> dict[str, Any]:
    output_dir = repo_path(str(config.get("output_dir") or "experiments/private_runs"), repo_root)
    metrics, candidate_count = _latest_metrics(output_dir, audit_out_dir)
    if metrics is None:
        _flag(
            flags,
            severity="blocker",
            surface="baseline_metric_validity",
            code="existing_baseline_metrics_missing",
        )
        return {
            "available": False,
            "metrics_file_count": candidate_count,
            "retrieval_saturation_warning": False,
        }
    retrieval = metrics.get("retrieval_metrics") if isinstance(metrics.get("retrieval_metrics"), Mapping) else {}
    safe_metrics = {
        key: _metric_mean(retrieval.get(key))
        for key in ("recall_at_5", "recall_at_10", "mrr_at_5", "ndcg_at_5")
        if _metric_mean(retrieval.get(key)) is not None
    }
    recall10 = safe_metrics.get("recall_at_10")
    saturation = recall10 is not None and recall10 >= RETRIEVAL_SATURATION_RECALL10
    if saturation:
        _flag(
            flags,
            severity="warning",
            surface="baseline_metric_validity",
            code="retrieval_saturation_warning",
        )
    return {
        "available": True,
        "metrics_file_count": candidate_count,
        "retrieval_metrics": safe_metrics,
        "retrieval_saturation_warning": saturation,
    }


def _audit_failure_taxonomy(
    config: Mapping[str, Any],
    repo_root: Path,
    audit_out_dir: Path,
    flags: list[dict[str, Any]],
) -> dict[str, Any]:
    output_dir = repo_path(str(config.get("output_dir") or "experiments/private_runs"), repo_root)
    failure_path = _failure_case_path(output_dir, audit_out_dir)
    if failure_path is None:
        _flag(
            flags,
            severity="blocker",
            surface="failure_taxonomy_readiness",
            code="failure_cases_missing",
        )
        return {
            "available": False,
            "failure_case_count": 0,
            "unique_failure_type_count": 0,
            "top_failure_type_available": False,
        }
    rows, errors = _jsonl_rows(failure_path)
    for error in errors:
        _flag(
            flags,
            severity="warning",
            surface="failure_taxonomy_readiness",
            code="failure_cases_" + error,
        )
    counts, rejected = _safe_failure_counts(rows)
    total = sum(counts.values())
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    if not top:
        _flag(
            flags,
            severity="warning",
            surface="failure_taxonomy_readiness",
            code="top_failure_type_unavailable",
        )
    return {
        "available": True,
        "failure_case_count": len(rows),
        "unique_failure_type_count": len(counts),
        "top_failure_type_available": bool(top),
        "top_failure_types": [
            {
                "failure_type": label,
                "count": count,
                "share": _rate(count, total),
            }
            for label, count in top
        ],
        "rejected_failure_type_label_count": rejected,
    }


def build_readiness_audit(
    config_path: Path,
    out_dir: Path,
    *,
    repo_root: Path = ROOT_DIR,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    flags: list[dict[str, Any]] = []
    resolved_config_path = repo_path(config_path, repo_root)
    resolved_out_dir = repo_path(out_dir, repo_root)

    if not is_gitignored_or_outside(resolved_out_dir, repo_root):
        _flag(
            flags,
            severity="blocker",
            surface="output_policy",
            code="output_path_not_gitignored",
        )

    config, config_errors = _load_yaml(resolved_config_path)
    for error in config_errors:
        _flag(flags, severity="blocker", surface="config", code=error)

    documents, document_texts = _audit_documents(config, repo_root, flags)
    index, chunk_text_by_id, index_chunk_ids = _audit_index(config, repo_root, flags)
    eval_dataset = _audit_eval_dataset(
        config,
        repo_root,
        chunk_text_by_id,
        index_chunk_ids,
        flags,
    )
    baseline = _audit_baseline_metrics(config, repo_root, resolved_out_dir, flags)
    failure_taxonomy = _audit_failure_taxonomy(config, repo_root, resolved_out_dir, flags)

    if not document_texts and index.get("chunk_count"):
        documents["token_coverage_source"] = "index_chunks"
        documents["token_coverage"] = index["token_coverage"]
    else:
        documents["token_coverage_source"] = "manifest_text"

    severity_counts = {
        "blocker": sum(1 for flag in flags if flag["severity"] == "blocker"),
        "warning": sum(1 for flag in flags if flag["severity"] == "warning"),
        "info": sum(1 for flag in flags if flag["severity"] == "info"),
    }
    ready = severity_counts["blocker"] == 0
    summary = {
        "schema_version": SCHEMA_VERSION,
        "audit_type": "private_data_readiness",
        "benchmark_type": "private_real_eval",
        "local_only": True,
        "public_safe": True,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "ready_for_improvement": ready,
        "privacy": {
            "raw_private_fields_excluded": True,
            "aggregate_only": True,
            "local_output_only": True,
        },
        "scope": {
            "retrieval_behavior_changed": False,
            "reranker_behavior_changed": False,
            "prompt_behavior_changed": False,
            "chunking_behavior_changed": False,
            "verifier_behavior_changed": False,
        },
        "output_policy": {
            "gitignored_or_outside_repo": is_gitignored_or_outside(resolved_out_dir, repo_root),
        },
        "parse_quality": documents,
        "index_integrity": index,
        "eval_dataset_quality": eval_dataset,
        "baseline_metric_validity": baseline,
        "failure_taxonomy_readiness": failure_taxonomy,
        "flags_summary": severity_counts,
    }
    assert_public_safe_payload(summary)
    for flag in flags:
        assert_public_safe_payload(flag)
    report = render_report(summary, flags)
    return summary, flags, report


def render_report(summary: Mapping[str, Any], flags: Sequence[Mapping[str, Any]]) -> str:
    parse = summary["parse_quality"]
    index = summary["index_integrity"]
    dataset = summary["eval_dataset_quality"]
    baseline = summary["baseline_metric_validity"]
    taxonomy = summary["failure_taxonomy_readiness"]
    lines = [
        "# Private Data Readiness Audit",
        "",
        "Local-only aggregate audit before any Naive RAG performance improvement.",
        "",
        "## Verdict",
        "",
        f"- Ready for improvement: `{summary['ready_for_improvement']}`",
        f"- Blockers: {summary['flags_summary']['blocker']}",
        f"- Warnings: {summary['flags_summary']['warning']}",
        "",
        "## Parse Quality",
        "",
        f"- Documents: {parse['document_count']}",
        f"- Parsed / empty / short / suspicious: {parse['parsed_document_count']} / "
        f"{parse['empty_document_count']} / {parse['short_document_count']} / "
        f"{parse['suspicious_document_count']}",
        f"- Garbled character rate: {parse['garbled_character_rate']}",
        f"- Table/date/amount/score-like coverage: "
        f"{parse['token_coverage']['table_like_rate']} / "
        f"{parse['token_coverage']['date_like_rate']} / "
        f"{parse['token_coverage']['amount_like_rate']} / "
        f"{parse['token_coverage']['score_like_rate']}",
        "",
        "## Index Integrity",
        "",
        f"- Chunks: {index['chunk_count']}",
        f"- Chunk length min/p50/p95/max: {index['chunk_length']['min']} / "
        f"{index['chunk_length']['p50']} / {index['chunk_length']['p95']} / "
        f"{index['chunk_length']['max']}",
        f"- Duplicate chunk ratio: {index['duplicate_chunk_ratio']}",
        f"- Missing page metadata rate: {index['missing_page_metadata_rate']}",
        f"- Gold chunks missing from index: {dataset['gold_chunk_missing_from_index_count']}",
        "",
        "## Eval Dataset Quality",
        "",
        f"- Questions: {dataset['question_count']}",
        f"- Answerable / unanswerable: {dataset['answerable_count']} / "
        f"{dataset['unanswerable_count']}",
        f"- Duplicate question IDs: {dataset['duplicate_question_id_count']}",
        f"- Answerable without gold: {dataset['answerable_without_gold_evidence_count']}",
        f"- Unanswerable with gold: {dataset['unanswerable_with_gold_evidence_count']}",
        f"- Expected terms questions: {dataset['expected_terms']['question_count']}",
        f"- Expected terms mean gold-text coverage: "
        f"{dataset['expected_terms']['gold_text_mean_term_coverage']}",
        "",
        "## Baseline Metric Validity",
        "",
        f"- Existing baseline metrics available: `{baseline['available']}`",
        f"- Retrieval saturation warning: `{baseline['retrieval_saturation_warning']}`",
        "",
        "## Failure Taxonomy Readiness",
        "",
        f"- Failure cases available: `{taxonomy['available']}`",
        f"- Top failure type available: `{taxonomy['top_failure_type_available']}`",
        "",
        "## Flags",
        "",
    ]
    if flags:
        for flag in flags:
            lines.append(
                f"- `{flag['severity']}` `{flag['surface']}` `{flag['code']}` "
                f"count={flag['count']}"
            )
    else:
        lines.append("- No flags.")
    lines.extend(
        [
            "",
            "Privacy note: raw document text, raw questions, raw answers, raw evidence, "
            "filenames, exact local paths, doc IDs, and chunk IDs are omitted.",
            "",
            "Scope note: this audit does not change retrieval, reranking, prompts, "
            "chunking, or verifier behavior.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(out_dir: Path, summary: Mapping[str, Any], flags: Sequence[Mapping[str, Any]], report: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "readiness_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "readiness_report.md").write_text(report, encoding="utf-8")
    (out_dir / "readiness_flags.jsonl").write_text(
        "".join(json.dumps(flag, ensure_ascii=False, sort_keys=True) + "\n" for flag in flags),
        encoding="utf-8",
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = repo_path(args.out_dir)
    try:
        summary, flags, report = build_readiness_audit(Path(args.config), Path(args.out_dir))
        if not summary["output_policy"]["gitignored_or_outside_repo"]:
            raise ValueError("--out-dir must be gitignored or outside the repository")
        write_outputs(out_dir, summary, flags, report)
    except Exception as exc:
        print(f"[ERROR] readiness audit failed: {exc}", file=sys.stderr)
        return 2
    print(
        "[OK] readiness audit written: "
        "readiness_summary.json, readiness_report.md, readiness_flags.jsonl"
    )
    return 0 if summary["ready_for_improvement"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
