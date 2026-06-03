#!/usr/bin/env python3
"""Aggregate-only audit for real100_v2 inline gold chunk labels.

Issue #1851: chunk-level recall can collapse when inline ``gold_evidence``
labels point at boilerplate chunks instead of the support-text/body chunks.
This script audits the current local private config against a chosen index, but
writes only aggregate counts plus hashed row refs. It does not rewrite private
configs, indexes, labels, or raw evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from scripts.private_data_quality_audit_utils import (
        assert_public_safe,
        hash_ref,
        jsonl_rows,
        repo_path,
        write_json,
        write_jsonl,
    )
except ImportError:  # pragma: no cover - direct script execution
    from private_data_quality_audit_utils import (  # type: ignore
        assert_public_safe,
        hash_ref,
        jsonl_rows,
        repo_path,
        write_json,
        write_jsonl,
    )


DEFAULT_CONFIG = "data/private/real100_v2/real_config_v2.local.yaml"
DEFAULT_INDEX_DIR = "data/index/real100_v2_checkpoint_minilm_pageaware"
DEFAULT_OUT_DIR = "reports/real100_v2"
DEFAULT_MIN_WINDOW_CHARS = 30
MAX_FLAGS = 200


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("config root must be a mapping")
    return payload


def _load_index(index_dir: Path) -> dict[str, Any]:
    index_file = index_dir / "index.json"
    payload = json.loads(index_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("index root must be an object")
    return payload


def _chunks(index: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [chunk for chunk in index.get("chunks") or [] if isinstance(chunk, dict)]


def _chunk_maps(index: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    by_label: dict[str, dict[str, Any]] = {}
    by_document: dict[str, list[dict[str, Any]]] = {}
    for chunk in _chunks(index):
        label = str(chunk.get("chunk_id") or "").strip()
        doc = str(chunk.get("doc_id") or "").strip()
        if label:
            by_label[label] = chunk
        if doc:
            by_document.setdefault(doc, []).append(chunk)
    return by_label, by_document


_WHITESPACE_RE = re.compile(r"\s+")


def _norm_anchor(value: Any) -> str:
    return _WHITESPACE_RE.sub("", str(value or "")).strip()


def _norm_terms(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _iter_windows(anchor: str, *, min_window_chars: int) -> list[str]:
    if len(anchor) < min_window_chars:
        return [anchor] if anchor else []
    step = max(1, min_window_chars // 2)
    windows = [anchor[start : start + min_window_chars] for start in range(0, len(anchor) - min_window_chars + 1, step)]
    tail = anchor[-min_window_chars:]
    if tail and tail not in windows:
        windows.append(tail)
    return windows


def _anchor_match(anchor: str, text: str, *, min_window_chars: int) -> str:
    """Return none/window/full for normalized support anchor coverage."""
    if not anchor:
        return "not_checked"
    if anchor in text:
        return "full"
    for window in _iter_windows(anchor, min_window_chars=min_window_chars):
        if len(window) >= min_window_chars and window in text:
            return "window"
    return "none"


def _same_document_anchor_found(
    *,
    anchor: str,
    expected_doc: str,
    labelled_chunk: str,
    by_document: Mapping[str, list[dict[str, Any]]],
    min_window_chars: int,
) -> bool:
    if not anchor or not expected_doc:
        return False
    for chunk in by_document.get(expected_doc, []):
        candidate_label = str(chunk.get("chunk_id") or "")
        if candidate_label == labelled_chunk:
            continue
        candidate_text = _norm_anchor(chunk.get("text"))
        if _anchor_match(anchor, candidate_text, min_window_chars=min_window_chars) in {"full", "window"}:
            return True
    return False


def _case_id(case: Mapping[str, Any], row_index: int) -> str:
    return str(case.get("id") or case.get("question_id") or f"row-{row_index}").strip()


def _inline_cases(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    cases = config.get("cases")
    if not isinstance(cases, list):
        raise ValueError("config must include a cases list")
    return [case for case in cases if isinstance(case, dict)]


def _evidence_items(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = case.get("gold_evidence") or []
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _signature(items: list[dict[str, Any]]) -> set[tuple[str, str, str, str]]:
    """Private in-memory source comparison signature; never emitted."""
    out: set[tuple[str, str, str, str]] = set()
    for item in items:
        out.add(
            (
                str(item.get("doc_id") or ""),
                str(item.get("chunk_id") or ""),
                str(item.get("support_claim") or ""),
                str(item.get("support_text") or ""),
            )
        )
    return out


def _canonical_by_case(path: Path | None) -> dict[str, list[dict[str, Any]]] | None:
    if path is None:
        return None
    by_case: dict[str, list[dict[str, Any]]] = {}
    for row_index, row in enumerate(jsonl_rows(path), start=1):
        qid = str(row.get("question_id") or row.get("id") or f"row-{row_index}").strip()
        wrapped = row.get("gold_evidence")
        if isinstance(wrapped, list):
            by_case[qid] = [dict(item) for item in wrapped if isinstance(item, dict)]
        elif isinstance(row, dict):
            direct_keys = {"doc_id", "chunk_id", "support_claim", "support_text", "required_terms", "page_span"}
            if any(row.get(key) not in (None, "", []) for key in direct_keys):
                by_case[qid] = [{key: row.get(key) for key in direct_keys if row.get(key) not in (None, "", [])}]
            else:
                by_case[qid] = []
    return by_case


def _add_flag(flags: list[dict[str, Any]], flag: dict[str, Any]) -> None:
    if len(flags) < MAX_FLAGS:
        flags.append(flag)


def _flag(
    *,
    severity: str,
    flag_type: str,
    case_key: str,
    evidence_index: int | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "audit_type": "real100_v2_gold_label_audit",
        "severity": severity,
        "flag_type": flag_type,
        "case_ref": hash_ref(case_key, namespace="real100-v2-case"),
    }
    if evidence_index is not None:
        payload["evidence_ref"] = hash_ref(f"{case_key}:{evidence_index}", namespace="real100-v2-evidence")
    if metrics:
        payload["metrics"] = metrics
    return payload


def _audit_inline_labels(
    *,
    cases: list[dict[str, Any]],
    by_label: Mapping[str, dict[str, Any]],
    by_document: Mapping[str, list[dict[str, Any]]],
    min_window_chars: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    flags: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    coverage: Counter[str] = Counter()
    term_rows = 0
    term_full = 0

    for row_index, case in enumerate(cases, start=1):
        case_key = _case_id(case, row_index)
        items = _evidence_items(case)
        counts["evidence_count"] += len(items)
        if not items:
            counts["cases_without_inline_gold_count"] += 1
        for evidence_index, item in enumerate(items, start=1):
            expected_doc = str(item.get("doc_id") or "").strip()
            label = str(item.get("chunk_id") or "").strip()
            if not label:
                counts["missing_chunk_label_count"] += 1
                _add_flag(
                    flags,
                    _flag(
                        severity="error",
                        flag_type="missing_inline_chunk_label",
                        case_key=case_key,
                        evidence_index=evidence_index,
                    ),
                )
                continue
            counts["with_chunk_label_count"] += 1
            chunk = by_label.get(label)
            if chunk is None:
                counts["absent_chunk_label_count"] += 1
                _add_flag(
                    flags,
                    _flag(
                        severity="error",
                        flag_type="inline_chunk_label_absent_from_index",
                        case_key=case_key,
                        evidence_index=evidence_index,
                    ),
                )
                continue
            actual_doc = str(chunk.get("doc_id") or "").strip()
            if expected_doc and actual_doc and expected_doc != actual_doc:
                counts["document_chunk_mismatch_count"] += 1
                _add_flag(
                    flags,
                    _flag(
                        severity="error",
                        flag_type="inline_document_chunk_mismatch",
                        case_key=case_key,
                        evidence_index=evidence_index,
                    ),
                )

            chunk_text = _norm_anchor(chunk.get("text"))
            support_anchor = _norm_anchor(item.get("support_text") or item.get("support_claim"))
            match = _anchor_match(support_anchor, chunk_text, min_window_chars=min_window_chars)
            if match != "not_checked":
                coverage["support_anchor_checked_count"] += 1
                if match == "full":
                    coverage["support_anchor_full_covered_count"] += 1
                elif match == "window":
                    coverage["support_anchor_window_covered_count"] += 1
                else:
                    coverage["support_anchor_uncovered_count"] += 1
                    found_elsewhere = _same_document_anchor_found(
                        anchor=support_anchor,
                        expected_doc=expected_doc or actual_doc,
                        labelled_chunk=label,
                        by_document=by_document,
                        min_window_chars=min_window_chars,
                    )
                    if found_elsewhere:
                        coverage["support_anchor_found_elsewhere_same_document_count"] += 1
                    _add_flag(
                        flags,
                        _flag(
                            severity="warning",
                            flag_type="support_anchor_not_observed_in_labelled_chunk",
                            case_key=case_key,
                            evidence_index=evidence_index,
                            metrics={"same_document_candidate_observed": bool(found_elsewhere)},
                        ),
                    )

            terms = _norm_terms(item.get("required_terms"))
            if terms:
                term_rows += 1
                lowered = str(chunk.get("text") or "").lower()
                covered = sum(1 for term in terms if term.lower() in lowered)
                if covered == len(terms):
                    term_full += 1
                else:
                    _add_flag(
                        flags,
                        _flag(
                            severity="warning",
                            flag_type="required_terms_not_fully_observed_in_labelled_chunk",
                            case_key=case_key,
                            evidence_index=evidence_index,
                            metrics={"covered_term_count": covered, "required_term_count": len(terms)},
                        ),
                    )

    support_checked = coverage["support_anchor_checked_count"]
    support_observed = coverage["support_anchor_full_covered_count"] + coverage["support_anchor_window_covered_count"]
    summary = {
        "case_count": len(cases),
        "cases_without_inline_gold_count": counts["cases_without_inline_gold_count"],
        "evidence_count": counts["evidence_count"],
        "with_chunk_label_count": counts["with_chunk_label_count"],
        "missing_chunk_label_count": counts["missing_chunk_label_count"],
        "absent_chunk_label_count": counts["absent_chunk_label_count"],
        "document_chunk_mismatch_count": counts["document_chunk_mismatch_count"],
        "support_anchor_checked_count": support_checked,
        "support_anchor_observed_count": support_observed,
        "support_anchor_full_covered_count": coverage["support_anchor_full_covered_count"],
        "support_anchor_window_covered_count": coverage["support_anchor_window_covered_count"],
        "support_anchor_uncovered_count": coverage["support_anchor_uncovered_count"],
        "support_anchor_found_elsewhere_same_document_count": coverage[
            "support_anchor_found_elsewhere_same_document_count"
        ],
        "support_anchor_observed_rate": round(support_observed / support_checked, 6) if support_checked else None,
        "required_terms_checked_count": term_rows,
        "required_terms_full_covered_count": term_full,
        "required_terms_full_covered_rate": round(term_full / term_rows, 6) if term_rows else None,
    }
    return summary, flags


def _audit_canonical_alignment(
    *,
    cases: list[dict[str, Any]],
    canonical: Mapping[str, list[dict[str, Any]]] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if canonical is None:
        return {
            "checked": False,
            "inline_case_count": len(cases),
            "canonical_case_count": None,
            "matching_case_count": None,
            "mismatched_case_count": None,
            "missing_in_canonical_count": None,
            "canonical_only_count": None,
        }, []

    flags: list[dict[str, Any]] = []
    inline_by_case = {_case_id(case, idx): _evidence_items(case) for idx, case in enumerate(cases, start=1)}
    inline_keys = set(inline_by_case)
    canonical_keys = set(canonical)
    matching = 0
    mismatched = 0
    missing = 0
    for case_key, inline_items in inline_by_case.items():
        if case_key not in canonical:
            missing += 1
            _add_flag(flags, _flag(severity="error", flag_type="inline_case_missing_from_canonical_gold", case_key=case_key))
            continue
        if _signature(inline_items) == _signature(list(canonical[case_key])):
            matching += 1
        else:
            mismatched += 1
            _add_flag(flags, _flag(severity="warning", flag_type="inline_canonical_gold_mismatch", case_key=case_key))
    canonical_only = len(canonical_keys - inline_keys)
    return {
        "checked": True,
        "inline_case_count": len(inline_by_case),
        "canonical_case_count": len(canonical),
        "matching_case_count": matching,
        "mismatched_case_count": mismatched,
        "missing_in_canonical_count": missing,
        "canonical_only_count": canonical_only,
    }, flags


def _render_report(summary: Mapping[str, Any]) -> str:
    label = summary["index_label_alignment"]
    canonical = summary["canonical_alignment"]
    lines = [
        "# real100_v2 Gold Label Audit",
        "",
        "Aggregate-only local audit. Raw questions, answers, evidence content, exact paths, doc ids, and chunk ids are omitted.",
        "",
        "## Verdict",
        "",
        f"- Passed: `{summary['passed']}`",
        f"- Error flags: {summary['flag_counts']['error']}",
        f"- Warning flags: {summary['flag_counts']['warning']}",
        "",
        "## Inline Gold ↔ Index Alignment",
        "",
        f"- Cases: {label['case_count']}",
        f"- Evidence rows: {label['evidence_count']}",
        f"- Missing chunk labels: {label['missing_chunk_label_count']}",
        f"- Absent chunk labels: {label['absent_chunk_label_count']}",
        f"- Document/chunk mismatches: {label['document_chunk_mismatch_count']}",
        f"- Support anchors checked: {label['support_anchor_checked_count']}",
        f"- Support anchors observed in labelled chunk: {label['support_anchor_observed_count']}",
        f"- Support anchors not observed: {label['support_anchor_uncovered_count']}",
        f"- Same-document alternate candidate observed: {label['support_anchor_found_elsewhere_same_document_count']}",
        f"- Required-term rows checked: {label['required_terms_checked_count']}",
        f"- Required-term rows fully covered: {label['required_terms_full_covered_count']}",
        "",
        "## Canonical Gold Alignment",
        "",
        f"- Checked: `{canonical['checked']}`",
        f"- Inline cases: {canonical['inline_case_count']}",
        f"- Canonical cases: {canonical['canonical_case_count']}",
        f"- Matching cases: {canonical['matching_case_count']}",
        f"- Mismatched cases: {canonical['mismatched_case_count']}",
        f"- Missing in canonical: {canonical['missing_in_canonical_count']}",
        f"- Canonical-only cases: {canonical['canonical_only_count']}",
        "",
        "## Boundary",
        "",
        f"- Privacy boundary: `{summary['privacy_boundary']}`",
        f"- Surface: `{summary['surface']}`",
    ]
    return "\n".join(lines) + "\n"


def run_audit(
    *,
    config_path: Path,
    index_dir: Path,
    out_dir: Path,
    canonical_gold_path: Path | None = None,
    config_label: str = "local_real100_v2_config",
    index_label: str = "local_real100_v2_index",
    canonical_label: str = "local_real100_v2_canonical_gold",
    min_window_chars: int = DEFAULT_MIN_WINDOW_CHARS,
) -> dict[str, Any]:
    config_path = repo_path(config_path)
    index_dir = repo_path(index_dir)
    out_dir = repo_path(out_dir)
    canonical_gold_path = repo_path(canonical_gold_path) if canonical_gold_path else None

    config = _load_yaml_mapping(config_path)
    index = _load_index(index_dir)
    cases = _inline_cases(config)
    by_label, by_document = _chunk_maps(index)
    label_summary, label_flags = _audit_inline_labels(
        cases=cases,
        by_label=by_label,
        by_document=by_document,
        min_window_chars=min_window_chars,
    )
    canonical_summary, canonical_flags = _audit_canonical_alignment(
        cases=cases,
        canonical=_canonical_by_case(canonical_gold_path),
    )
    flags = label_flags + canonical_flags
    severity_counts = Counter(str(flag.get("severity") or "") for flag in flags)
    passed = bool(
        severity_counts.get("error", 0) == 0
        and label_summary["support_anchor_uncovered_count"] == 0
        and canonical_summary.get("mismatched_case_count") in (None, 0)
        and canonical_summary.get("canonical_only_count") in (None, 0)
    )
    summary = {
        "schema_version": 1,
        "audit_type": "real100_v2_gold_label_audit",
        "surface": "real100_v2",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "passed": passed,
        "privacy_boundary": "aggregate_only_no_raw_questions_answers_evidence_ids_paths_or_filenames",
        "input_labels": {
            "config": config_label,
            "index": index_label,
            "canonical_gold": canonical_label if canonical_gold_path else None,
        },
        "index_metadata": {
            "chunk_count": len(_chunks(index)),
            "document_count": len(index.get("documents") or []) if isinstance(index.get("documents"), list) else None,
        },
        "index_label_alignment": label_summary,
        "canonical_alignment": canonical_summary,
        "flag_counts": {
            "error": severity_counts.get("error", 0),
            "warning": severity_counts.get("warning", 0),
            "emitted": len(flags),
            "emission_cap": MAX_FLAGS,
        },
        "known_limits": [
            "This audit measures label/index consistency; it does not rewrite gold labels.",
            "Support-anchor checks are string/window observations, not a semantic judge.",
            "Hashed refs are for local triage correlation only and are not stable public identifiers.",
        ],
    }
    assert_public_safe(summary)
    for flag in flags:
        assert_public_safe(flag)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "gold_label_audit.aggregate.json", summary)
    write_jsonl(out_dir / "gold_label_audit.flags.jsonl", flags)
    report = _render_report(summary)
    assert "doc_id" not in report and "chunk_id" not in report and "support_text" not in report
    (out_dir / "gold_label_audit.report.md").write_text(report, encoding="utf-8")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit real100_v2 inline gold labels against an index.")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Local real100_v2 YAML config.")
    parser.add_argument("--index-dir", default=DEFAULT_INDEX_DIR, help="Index directory containing index.json.")
    parser.add_argument("--canonical-gold-jsonl", default=None, help="Optional canonical gold JSONL for inline-vs-canonical drift checks.")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Directory for aggregate-only audit artifacts.")
    parser.add_argument("--config-label", default="local_real100_v2_config", help="Safe label stored in output instead of the config path.")
    parser.add_argument("--index-label", default="local_real100_v2_index", help="Safe label stored in output instead of the index path.")
    parser.add_argument("--canonical-label", default="local_real100_v2_canonical_gold", help="Safe label stored in output instead of the canonical path.")
    parser.add_argument("--min-window-chars", type=int, default=DEFAULT_MIN_WINDOW_CHARS, help="Minimum normalized support anchor window size.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_audit(
        config_path=Path(args.config),
        index_dir=Path(args.index_dir),
        out_dir=Path(args.out_dir),
        canonical_gold_path=Path(args.canonical_gold_jsonl) if args.canonical_gold_jsonl else None,
        config_label=str(args.config_label),
        index_label=str(args.index_label),
        canonical_label=str(args.canonical_label),
        min_window_chars=int(args.min_window_chars),
    )
    print(json.dumps({"passed": summary["passed"], "flag_counts": summary["flag_counts"]}, sort_keys=True))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
