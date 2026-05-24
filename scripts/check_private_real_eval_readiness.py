#!/usr/bin/env python3
"""Local-only readiness validator for private Naive RAG real-eval inputs.

The validator reports structure, counts, and privacy safety only. It never
prints raw questions, document names, support text, generated answers, or
customer-specific paths.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Mapping

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]

REQUIRED_CONFIG_FIELDS = (
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
)
PRIVATE_MANIFEST_COLUMNS = {"doc_id", "file_path"}
LEGACY_MANIFEST_COLUMNS = {"공고 번호", "사업명", "발주 기관", "파일형식", "파일명", "텍스트"}
RUNNABLE_MIN_ANSWERABLE = 10
RUNNABLE_MIN_UNANSWERABLE = 3
PORTFOLIO_MIN_QUESTIONS = 100
PORTFOLIO_MIN_DOCUMENTS = 50

PRIVATE_PATHS_THAT_MUST_BE_IGNORED = (
    "eval/real_config.local.yaml",
    "configs/eval/private_real_eval.local.yaml",
    "data/files/",
    "data/files_kordoc/",
    "data/private/",
    "data/data_list.csv",
    "data/index/real100/",
    "data/index/real100_kordoc/",
    "data/index-private-hardcase/",
    "experiments/private_runs/",
    "reports/real100/eval_summary.json",
    "reports/real100/raw/",
    "reports/private_real_eval_summary.raw.json",
)

VERDICT_LABELS = {
    "A": "A. Not ready",
    "B": "B. Config ready, data missing",
    "C": "C. Data present, labels/index missing",
    "D": "D. First baseline runnable",
    "E": "E. Portfolio-level readiness possible after manual review",
}


@dataclass
class ReadinessReport:
    verdict: str
    ready_to_run: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, Any] = field(default_factory=dict)
    checks: dict[str, Any] = field(default_factory=dict)
    build_command_available: bool = False
    build_command: list[str] = field(default_factory=list)

    @property
    def verdict_label(self) -> str:
        return VERDICT_LABELS[self.verdict]

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["verdict_label"] = self.verdict_label
        return payload


def _repo_path(value: str | Path, repo_root: Path = ROOT_DIR) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else repo_root / path


def _relative_to_repo(path: Path, repo_root: Path = ROOT_DIR) -> str | None:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return None


def _load_yaml(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, "config file is missing"
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return None, f"config YAML is invalid: {exc.__class__.__name__}"
    if not isinstance(payload, dict):
        return None, "config root must be a mapping"
    return payload, None


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _jsonl_rows(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    if not path.exists():
        return rows, ["file is missing"]
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            errors.append(f"invalid JSONL at line {lineno}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"JSONL row at line {lineno} is not an object")
            continue
        rows.append(payload)
    return rows, errors


def _is_git_ignored(path: Path, repo_root: Path = ROOT_DIR) -> tuple[bool, str]:
    rel = _relative_to_repo(path, repo_root)
    if rel is None:
        return True, "outside_repo"
    candidates = [rel]
    if not rel.endswith("/"):
        candidates.append(rel + "/")
        candidates.append(rel + "/.private-real-eval-sentinel")
    for candidate in candidates:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", candidate],
            cwd=repo_root,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            return True, "gitignored"
        if result.returncode not in (0, 1):
            return False, "git_check_failed"
    return False, "not_ignored"


def _safe_path_for_manifest(value: str, documents_dir: Path, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    if value.startswith("data/") or value.startswith("./data/"):
        return _repo_path(path, repo_root)
    return documents_dir / path


def _manifest_doc_id(row: Mapping[str, Any]) -> str:
    for key in ("doc_id", "공고 번호", "notice_id"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _manifest_file_path(row: Mapping[str, Any]) -> str:
    for key in ("file_path", "파일명", "file_name"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _page_metadata_present(item: Mapping[str, Any]) -> bool:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
    for node in (item, metadata):
        for key in ("page", "page_number", "page_span", "page_start", "page_end", "pages"):
            value = node.get(key)
            if value not in (None, "", []):
                return True
    return False


def _index_counts(payload: Mapping[str, Any]) -> tuple[int | None, int | None]:
    build = payload.get("build") if isinstance(payload.get("build"), Mapping) else {}
    docs = build.get("num_documents")
    chunks = build.get("num_chunks")
    if docs is None:
        docs = len(payload.get("documents") or []) if isinstance(payload.get("documents"), list) else None
    if chunks is None:
        chunks = len(payload.get("chunks") or []) if isinstance(payload.get("chunks"), list) else None
    try:
        doc_count = int(docs) if docs is not None else None
    except (TypeError, ValueError):
        doc_count = None
    try:
        chunk_count = int(chunks) if chunks is not None else None
    except (TypeError, ValueError):
        chunk_count = None
    return doc_count, chunk_count


def _evidence_items(row: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    wrapped = row.get("gold_evidence")
    if isinstance(wrapped, list):
        for item in wrapped:
            if isinstance(item, dict):
                merged = dict(item)
                if "question_id" not in merged and row.get("question_id"):
                    merged["question_id"] = row.get("question_id")
                yield merged
        return
    yield dict(row)


def _derived_from_expected_terms(item: Mapping[str, Any]) -> bool:
    marker = str(item.get("derived_from") or item.get("source") or item.get("method") or "").lower()
    if "expected_terms" in marker:
        return True
    return bool(item.get("expected_terms")) and not (item.get("doc_id") and item.get("chunk_id"))


def assess_readiness(config_path: Path, repo_root: Path = ROOT_DIR) -> ReadinessReport:
    blockers: list[str] = []
    warnings: list[str] = []
    counts: dict[str, Any] = {
        "document_count": 0,
        "manifest_rows": 0,
        "manifest_missing_files": 0,
        "question_count": 0,
        "answerable_count": 0,
        "unanswerable_count": 0,
        "gold_evidence_count": 0,
        "gold_evidence_with_page_metadata": 0,
        "gold_evidence_with_support_text": 0,
        "index_document_count": None,
        "chunk_count": None,
        "chunk_top_k_ratio": None,
    }
    checks: dict[str, Any] = {}

    config_path = _repo_path(config_path, repo_root)
    config, config_error = _load_yaml(config_path)
    if config_error:
        blockers.append("config_file_missing_or_invalid")
        return ReadinessReport("A", False, blockers, warnings, counts, {"config": config_error})

    assert config is not None
    config_blockers: list[str] = []
    if not (
        config.get("eval_type") == "private_real_eval"
        or config.get("benchmark_type") == "private_real_eval"
    ):
        config_blockers.append("eval_type_or_benchmark_type_must_be_private_real_eval")
    if config.get("baseline_system") != "naive_rag":
        config_blockers.append("baseline_system_must_be_naive_rag")
    if not _boolish(config.get("not_ci_smoke")):
        config_blockers.append("not_ci_smoke_must_be_true")
    if not _boolish(config.get("is_private_data")):
        config_blockers.append("is_private_data_must_be_true")
    missing_fields = [field for field in REQUIRED_CONFIG_FIELDS if field not in config]
    if missing_fields:
        config_blockers.append("required_config_fields_missing")
    try:
        top_k = int(config.get("top_k") or 0)
    except (TypeError, ValueError):
        top_k = 0
    if top_k <= 0:
        config_blockers.append("top_k_must_be_positive")
    checks["config"] = {
        "ok": not config_blockers,
        "missing_field_count": len(missing_fields),
        "top_k": top_k,
    }
    blockers.extend(config_blockers)

    path_fields = {
        "documents_dir": config.get("documents_dir"),
        "data_list_path": config.get("data_list_path"),
        "questions_path": config.get("questions_path"),
        "gold_evidence_path": config.get("gold_evidence_path"),
        "index_dir": config.get("index_dir"),
        "output_dir": config.get("output_dir"),
        "redacted_summary_path": config.get("redacted_summary_path"),
    }
    if any(not value for value in path_fields.values()):
        blockers.append("required_path_field_missing")
        return ReadinessReport("A", False, blockers, warnings, counts, checks)

    documents_dir = _repo_path(str(path_fields["documents_dir"]), repo_root)
    data_list_path = _repo_path(str(path_fields["data_list_path"]), repo_root)
    questions_path = _repo_path(str(path_fields["questions_path"]), repo_root)
    gold_path = _repo_path(str(path_fields["gold_evidence_path"]), repo_root)
    index_dir = _repo_path(str(path_fields["index_dir"]), repo_root)
    output_dir = _repo_path(str(path_fields["output_dir"]), repo_root)
    redacted_summary_path = _repo_path(str(path_fields["redacted_summary_path"]), repo_root)

    for label, candidate in (
        ("local_config", config_path),
        ("documents_dir", documents_dir),
        ("data_list_path", data_list_path),
        ("questions_path", questions_path),
        ("gold_evidence_path", gold_path),
        ("index_dir", index_dir),
        ("output_dir", output_dir),
    ):
        ignored, source = _is_git_ignored(candidate, repo_root)
        checks.setdefault("privacy", {})[label] = source
        if not ignored:
            blockers.append(f"{label}_must_be_gitignored_or_outside_repo")

    for rel in PRIVATE_PATHS_THAT_MUST_BE_IGNORED:
        ignored, source = _is_git_ignored(repo_root / rel, repo_root)
        checks.setdefault("privacy", {})[rel] = source
        if not ignored:
            blockers.append(f"private_path_not_gitignored:{rel}")

    redacted_ignored, redacted_source = _is_git_ignored(redacted_summary_path, repo_root)
    checks.setdefault("privacy", {})["redacted_summary_path"] = redacted_source
    if redacted_ignored:
        blockers.append("redacted_summary_path_must_be_committable_after_checks")
    if not redacted_summary_path.name.endswith(".redacted.json"):
        blockers.append("redacted_summary_path_must_end_with_redacted_json")

    data_blockers: list[str] = []
    manifest_doc_ids: set[str] = set()
    if not documents_dir.is_dir():
        data_blockers.append("documents_dir_missing")
    if not data_list_path.is_file():
        data_blockers.append("data_list_path_missing")
    if documents_dir.is_dir() and data_list_path.is_file():
        with data_list_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            columns = set(reader.fieldnames or [])
            private_schema = PRIVATE_MANIFEST_COLUMNS.issubset(columns)
            legacy_schema = LEGACY_MANIFEST_COLUMNS.issubset(columns)
            checks["manifest_schema"] = (
                "private_real_eval_v1" if private_schema else "legacy_data_list" if legacy_schema else "unknown"
            )
            if not (private_schema or legacy_schema):
                data_blockers.append("data_list_required_columns_missing")
            seen_doc_ids: set[str] = set()
            duplicate_doc_ids = 0
            missing_doc_ids = 0
            missing_files = 0
            rows = list(reader)
            counts["manifest_rows"] = len(rows)
            for row in rows:
                doc_id = _manifest_doc_id(row)
                file_value = _manifest_file_path(row)
                if not doc_id:
                    missing_doc_ids += 1
                elif doc_id in seen_doc_ids:
                    duplicate_doc_ids += 1
                else:
                    seen_doc_ids.add(doc_id)
                    manifest_doc_ids.add(doc_id)
                if not file_value or not _safe_path_for_manifest(file_value, documents_dir, repo_root).exists():
                    missing_files += 1
            counts["document_count"] = len(manifest_doc_ids) or len(rows)
            counts["manifest_missing_files"] = missing_files
            if missing_doc_ids:
                data_blockers.append("manifest_doc_id_values_missing")
            if duplicate_doc_ids:
                data_blockers.append("manifest_doc_id_values_not_unique")
            if missing_files:
                data_blockers.append("manifest_referenced_files_missing")
    blockers.extend(data_blockers)

    question_blockers: list[str] = []
    question_rows, question_errors = _jsonl_rows(questions_path)
    if question_errors:
        question_blockers.extend(f"questions_{error.replace(' ', '_')}" for error in question_errors[:3])
    question_ids: set[str] = set()
    duplicate_question_ids = 0
    missing_question_ids = 0
    answerable_ids: set[str] = set()
    for row in question_rows:
        qid = str(row.get("question_id") or "").strip()
        if not qid:
            missing_question_ids += 1
            continue
        if qid in question_ids:
            duplicate_question_ids += 1
        question_ids.add(qid)
        answerable = _boolish(row.get("answerable", True))
        if answerable:
            answerable_ids.add(qid)
    counts["question_count"] = len(question_rows)
    counts["answerable_count"] = len(answerable_ids)
    counts["unanswerable_count"] = len(question_rows) - len(answerable_ids)
    if missing_question_ids:
        question_blockers.append("question_ids_missing")
    if duplicate_question_ids:
        question_blockers.append("question_ids_not_unique")
    if question_rows and counts["answerable_count"] < RUNNABLE_MIN_ANSWERABLE:
        question_blockers.append("answerable_question_count_below_naive_runner_minimum")
    if question_rows and counts["unanswerable_count"] < RUNNABLE_MIN_UNANSWERABLE:
        question_blockers.append("unanswerable_question_count_below_naive_runner_minimum")
    blockers.extend(question_blockers)

    gold_blockers: list[str] = []
    gold_rows, gold_errors = _jsonl_rows(gold_path)
    if gold_errors:
        gold_blockers.extend(f"gold_evidence_{error.replace(' ', '_')}" for error in gold_errors[:3])
    evidence_ids: set[str] = set()
    duplicate_evidence_ids = 0
    missing_evidence_ids = 0
    explicit_by_question: dict[str, int] = {}
    invalid_doc_refs = 0
    derived_gold = 0
    for row in gold_rows:
        for item in _evidence_items(row):
            qid = str(item.get("question_id") or row.get("question_id") or "").strip()
            evidence_id = str(item.get("evidence_id") or "").strip()
            if not evidence_id:
                missing_evidence_ids += 1
            elif evidence_id in evidence_ids:
                duplicate_evidence_ids += 1
            else:
                evidence_ids.add(evidence_id)
            if _derived_from_expected_terms(item):
                derived_gold += 1
            doc_id = str(item.get("doc_id") or "").strip()
            chunk_id = str(item.get("chunk_id") or "").strip()
            if doc_id and manifest_doc_ids and doc_id not in manifest_doc_ids:
                invalid_doc_refs += 1
            if qid and doc_id and chunk_id:
                explicit_by_question[qid] = explicit_by_question.get(qid, 0) + 1
            if _page_metadata_present(item):
                counts["gold_evidence_with_page_metadata"] += 1
            if str(item.get("support_text") or "").strip():
                counts["gold_evidence_with_support_text"] += 1
    counts["gold_evidence_count"] = len(evidence_ids)
    if missing_evidence_ids:
        gold_blockers.append("gold_evidence_ids_missing")
    if duplicate_evidence_ids:
        gold_blockers.append("gold_evidence_ids_not_unique")
    if derived_gold:
        gold_blockers.append("gold_evidence_must_not_be_derived_from_expected_terms")
    if invalid_doc_refs:
        gold_blockers.append("gold_evidence_doc_id_references_invalid")
    if answerable_ids:
        missing_gold_for_answerable = sorted(qid for qid in answerable_ids if explicit_by_question.get(qid, 0) == 0)
        if missing_gold_for_answerable:
            gold_blockers.append("answerable_questions_missing_explicit_gold_evidence")
    blockers.extend(gold_blockers)

    index_blockers: list[str] = []
    build_script = repo_root / "scripts" / "build_index.py"
    build_command_available = build_script.exists()
    build_command = [
        "python3",
        "scripts/build_index.py",
        "--metadata_csv",
        "<data_list_path>",
        "--files_dir",
        "<documents_dir>",
        "--output_dir",
        "<index_dir>",
        "--hwp_loader",
        "kordoc",
        "--pdf_loader",
        "kordoc",
        "--embedding_backend",
        "hashing",
    ]
    if not index_dir.is_dir():
        index_blockers.append("index_dir_missing")
    else:
        index_json = index_dir / "index.json"
        if not index_json.is_file():
            index_blockers.append("index_metadata_missing")
        else:
            try:
                payload = json.loads(index_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
                index_blockers.append("index_metadata_invalid_json")
            if isinstance(payload, dict):
                doc_count, chunk_count = _index_counts(payload)
                counts["index_document_count"] = doc_count
                counts["chunk_count"] = chunk_count
                if chunk_count is not None and top_k:
                    counts["chunk_top_k_ratio"] = round(chunk_count / top_k, 3)
                chunks = payload.get("chunks") if isinstance(payload.get("chunks"), list) else []
                if chunks:
                    chunk_id_coverage = sum(1 for chunk in chunks if isinstance(chunk, dict) and chunk.get("chunk_id"))
                    doc_id_coverage = sum(1 for chunk in chunks if isinstance(chunk, dict) and chunk.get("doc_id"))
                    page_coverage = sum(
                        1 for chunk in chunks if isinstance(chunk, dict) and _page_metadata_present(chunk)
                    )
                    checks["index_metadata"] = {
                        "chunk_id_coverage": f"{chunk_id_coverage}/{len(chunks)}",
                        "doc_id_coverage": f"{doc_id_coverage}/{len(chunks)}",
                        "page_metadata_coverage": f"{page_coverage}/{len(chunks)}",
                    }
                    if chunk_id_coverage != len(chunks):
                        index_blockers.append("index_chunk_id_metadata_incomplete")
                    if doc_id_coverage != len(chunks):
                        index_blockers.append("index_doc_id_metadata_incomplete")
    blockers.extend(index_blockers)

    data_present = documents_dir.is_dir() and data_list_path.is_file() and not data_blockers
    labels_present = bool(question_rows) and bool(gold_rows) and not question_blockers and not gold_blockers
    index_ready = index_dir.is_dir() and not index_blockers
    config_ok = not config_blockers and not any(
        b.endswith("_must_be_gitignored_or_outside_repo")
        or b.startswith("private_path_not_gitignored:")
        or b.startswith("redacted_summary_path")
        for b in blockers
    )
    ready_to_run = config_ok and data_present and labels_present and index_ready

    if not config_ok:
        verdict = "A"
    elif not data_present:
        verdict = "B"
    elif not (labels_present and index_ready):
        verdict = "C"
    elif (
        counts["question_count"] >= PORTFOLIO_MIN_QUESTIONS
        and counts["document_count"] >= PORTFOLIO_MIN_DOCUMENTS
    ):
        verdict = "E"
        warnings.append("portfolio_readiness_still_requires_manual_privacy_and_label_review")
    else:
        verdict = "D"

    return ReadinessReport(
        verdict,
        ready_to_run,
        blockers,
        warnings,
        counts,
        checks,
        build_command_available,
        build_command,
    )


def _render_report(report: ReadinessReport) -> str:
    lines = [f"Private real-eval readiness verdict: {report.verdict_label}", ""]
    lines.append("Counts:")
    for key in (
        "document_count",
        "manifest_rows",
        "manifest_missing_files",
        "question_count",
        "answerable_count",
        "unanswerable_count",
        "gold_evidence_count",
        "gold_evidence_with_page_metadata",
        "gold_evidence_with_support_text",
        "index_document_count",
        "chunk_count",
        "chunk_top_k_ratio",
    ):
        lines.append(f"- {key}: {report.counts.get(key)}")
    if report.blockers:
        lines.extend(["", "Blockers:"])
        for blocker in report.blockers:
            lines.append(f"- {blocker}")
    if report.warnings:
        lines.extend(["", "Warnings:"])
        for warning in report.warnings:
            lines.append(f"- {warning}")
    if report.build_command_available:
        lines.extend(["", "Index build command shape:"])
        lines.append("$ " + " ".join(report.build_command))
    lines.extend(
        [
            "",
            "Privacy note: raw document names, question text, answer text, support_text, and absolute local paths are omitted.",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="eval/real_config.local.yaml")
    parser.add_argument("--json", action="store_true", help="Emit sanitized machine-readable readiness JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = assess_readiness(Path(args.config))
    if args.json:
        print(json.dumps(report.to_json(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_render_report(report))
    return 0 if report.ready_to_run else 1


if __name__ == "__main__":
    raise SystemExit(main())
