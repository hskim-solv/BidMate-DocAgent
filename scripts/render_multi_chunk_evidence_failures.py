#!/usr/bin/env python3
"""Render aggregate-only multi-chunk evidence failure analysis.

Reads the local-only ``reports/real100/eval_summary.json`` case results and
writes a committable aggregate JSON artifact. This is a read-only measurement
surface: it does not import or change retrieval, verifier, prompt, chunking, or
answer runtime behavior.

ADR 0005 boundary: query text, answer text, doc_id, chunk_id, section names,
paths, and retrieved text previews are consumed only to derive counts or closed
enum buckets. They are never copied into the output payload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_SUMMARY = ROOT / "reports" / "real100" / "eval_summary.json"
DEFAULT_OUT_JSON = (
    ROOT / "reports" / "real100" / "multi_chunk_evidence_failures.aggregate.json"
)

K_VALUES: tuple[int, ...] = (5, 10, 20)
METADATA_STRUCTURED_FIELDS: frozenset[str] = frozenset({"budget", "deadline"})
SAFE_SOURCE_FORMATS: tuple[str, ...] = (
    "csv",
    "docx",
    "hwp",
    "json",
    "pdf",
    "pptx",
    "txt",
    "xlsx",
    "unknown",
    "other",
)


def _load_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"eval_summary.json not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("eval_summary.json root must be an object")
    return payload


def source_provenance(path: Path) -> dict[str, Any]:
    """Return provenance without leaking external absolute paths."""
    resolved_root = ROOT.resolve()
    resolved_path = path.resolve()
    try:
        location = str(resolved_path.relative_to(resolved_root))
        redacted = False
    except ValueError:
        location = f"external_private/{path.name}"
        redacted = True
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return {
        "location": location,
        "location_redacted": redacted,
        "basename": path.name,
        "sha256_12": digest,
    }


def _case_results(summary: dict[str, Any]) -> list[dict[str, Any]]:
    raw = summary.get("case_results")
    if not isinstance(raw, list):
        raise ValueError(
            "eval_summary.json::case_results missing or not a list; regenerate "
            "a local real-eval summary with per-case retrieval diagnostics."
        )
    return [case for case in raw if isinstance(case, dict)]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _gold_chunk_ids(case: dict[str, Any]) -> list[str]:
    explicit = [str(item) for item in case.get("gold_chunk_ids") or [] if item]
    evidence_ids = [
        str(item.get("chunk_id") or "")
        for item in case.get("gold_evidence") or []
        if isinstance(item, dict) and item.get("chunk_id")
    ]
    return _unique([*explicit, *evidence_ids])


def _gold_doc_ids(case: dict[str, Any], gold_ids: list[str]) -> set[str]:
    docs: set[str] = set()
    gold_set = set(gold_ids)
    for item in case.get("gold_evidence") or []:
        if not isinstance(item, dict):
            continue
        chunk_id = str(item.get("chunk_id") or "")
        doc_id = str(item.get("doc_id") or "")
        if chunk_id in gold_set and doc_id:
            docs.add(doc_id)
    return docs


def _retrieved_chunk_ids(case: dict[str, Any]) -> list[str]:
    rows = case.get("retrieved_chunks")
    if isinstance(rows, list):
        clean_rows: list[tuple[int, int, str]] = []
        for ordinal, item in enumerate(rows):
            if not isinstance(item, dict):
                continue
            chunk_id = str(item.get("chunk_id") or "")
            if not chunk_id:
                continue
            try:
                rank = int(item.get("rank") or ordinal + 1)
            except (TypeError, ValueError):
                rank = ordinal + 1
            clean_rows.append((rank, ordinal, chunk_id))
        if clean_rows:
            return _unique([chunk_id for _, _, chunk_id in sorted(clean_rows)])
        if rows:
            raise ValueError("retrieved_chunks contains no usable chunk_id values")
        return []
    if "retrieved_chunk_ids" in case:
        raw_ids = case.get("retrieved_chunk_ids")
        if not isinstance(raw_ids, list):
            raise ValueError("retrieved_chunk_ids must be a list when provided")
        return _unique([str(item) for item in raw_ids if item])
    raise ValueError(
        "multi-chunk analysis requires retrieved_chunks or retrieved_chunk_ids diagnostics"
    )


def _retrieval_outcome(retrieved: list[str], gold: list[str], k: int) -> str:
    gold_set = set(gold)
    observed = set(retrieved[:k])
    hits = len(gold_set & observed)
    if hits == len(gold_set):
        return "all_gold_retrieved"
    if len(retrieved) < k and hits > 0:
        return "not_observable"
    if len(retrieved) < k and hits == 0 and len(retrieved) > 0:
        return "not_observable"
    if hits > 0:
        return "partial_gold_retrieved"
    return "no_gold_retrieved"


def _empty_outcome_counts() -> dict[str, int]:
    return {
        "all_gold_retrieved": 0,
        "partial_gold_retrieved": 0,
        "no_gold_retrieved": 0,
        "not_observable": 0,
    }


def _split_bucket(doc_ids: set[str]) -> str:
    if len(doc_ids) == 1:
        return "same_doc"
    if len(doc_ids) >= 2:
        return "multi_doc"
    return "unknown"


def _source_format_bucket(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "unknown"
    return text if text in SAFE_SOURCE_FORMATS and text != "other" else "other"


def _empty_structured_overlap() -> dict[str, Any]:
    return {
        "hardcase_table_heavy": 0,
        "metadata_field_structured": 0,
        "case_source_format": {key: 0 for key in SAFE_SOURCE_FORMATS},
    }


def _add_structured_overlap(bucket: dict[str, Any], case: dict[str, Any]) -> None:
    categories = {str(item) for item in case.get("hardcase_categories") or []}
    if "table_heavy" in categories:
        bucket["hardcase_table_heavy"] += 1
    if str(case.get("metadata_field") or "") in METADATA_STRUCTURED_FIELDS:
        bucket["metadata_field_structured"] += 1
    fmt = _source_format_bucket(case.get("case_source_format"))
    bucket["case_source_format"][fmt] += 1


def _numeric_lt_one(case: dict[str, Any], key: str) -> bool:
    value = case.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return float(value) < 1.0


def _is_top10_failure(retrieved: list[str], gold: list[str]) -> bool:
    return not set(gold).issubset(set(retrieved[:10]))


def build_aggregate(summary: dict[str, Any], *, source: dict[str, Any] | None = None) -> dict[str, Any]:
    cases = _case_results(summary)
    multi_cases: list[tuple[dict[str, Any], list[str], list[str], str]] = []
    for case in cases:
        if case.get("answerable") is False:
            continue
        gold = _gold_chunk_ids(case)
        if len(gold) < 2:
            continue
        retrieved = _retrieved_chunk_ids(case)
        split = _split_bucket(_gold_doc_ids(case, gold))
        multi_cases.append((case, gold, retrieved, split))

    retrieval_outcome_by_k = {str(k): _empty_outcome_counts() for k in K_VALUES}
    evidence_split = {"same_doc": 0, "multi_doc": 0, "unknown": 0}
    structured_all = _empty_structured_overlap()
    structured_failures = _empty_structured_overlap()
    candidate_pool_expansion = {
        "missing_gold_seen_after_top10": 0,
        "all_missing_gold_seen_after_top10": 0,
        "not_observable_due_to_depth": 0,
    }
    expected_impact = {
        "pool_or_rerank_candidate": 0,
        "query_decomposition_candidate": 0,
        "section_expansion_candidate": 0,
        "unknown_due_to_limited_depth": 0,
    }
    citation_guardrails = {
        "citation_claim_coverage_lt_1": 0,
        "citation_page_coverage_lt_1": 0,
        "citation_region_coverage_lt_1": 0,
        "claim_citation_alignment_lt_1": 0,
    }

    top10_failures = 0
    for case, gold, retrieved, split in multi_cases:
        evidence_split[split] += 1
        _add_structured_overlap(structured_all, case)
        for k in K_VALUES:
            outcome = _retrieval_outcome(retrieved, gold, k)
            retrieval_outcome_by_k[str(k)][outcome] += 1

        if not _is_top10_failure(retrieved, gold):
            continue

        top10_failures += 1
        _add_structured_overlap(structured_failures, case)
        if _numeric_lt_one(case, "citation_claim_coverage"):
            citation_guardrails["citation_claim_coverage_lt_1"] += 1
        if _numeric_lt_one(case, "citation_page_coverage"):
            citation_guardrails["citation_page_coverage_lt_1"] += 1
        if _numeric_lt_one(case, "citation_region_coverage"):
            citation_guardrails["citation_region_coverage_lt_1"] += 1
        if _numeric_lt_one(case, "claim_citation_alignment"):
            citation_guardrails["claim_citation_alignment_lt_1"] += 1

        top10 = set(retrieved[:10])
        beyond_top10 = set(retrieved[10:])
        missing = set(gold) - top10
        seen_after_top10 = missing & beyond_top10
        all_missing_seen_after_top10 = bool(missing) and missing.issubset(beyond_top10)
        if seen_after_top10:
            candidate_pool_expansion["missing_gold_seen_after_top10"] += 1
        if all_missing_seen_after_top10:
            candidate_pool_expansion["all_missing_gold_seen_after_top10"] += 1
            expected_impact["pool_or_rerank_candidate"] += 1
        else:
            candidate_pool_expansion["not_observable_due_to_depth"] += 1

        if split == "multi_doc":
            expected_impact["query_decomposition_candidate"] += 1
        elif split == "same_doc" and set(gold) & top10:
            expected_impact["section_expansion_candidate"] += 1
        if not all_missing_seen_after_top10 and not (
            split == "multi_doc" or (split == "same_doc" and set(gold) & top10)
        ):
            expected_impact["unknown_due_to_limited_depth"] += 1

    return {
        "schema_version": 1,
        "source": source
        or {
            "location": "reports/real100/eval_summary.json",
            "location_redacted": False,
            "basename": "eval_summary.json",
            "sha256_12": None,
        },
        "population": {
            "num_predictions": int(summary.get("num_predictions") or len(cases)),
            "multi_chunk_gold_cases": len(multi_cases),
            "multi_chunk_top10_evidence_failures": top10_failures,
        },
        "retrieval_outcome_by_k": retrieval_outcome_by_k,
        "evidence_split": evidence_split,
        "structured_overlap": {
            "multi_chunk_gold_cases": structured_all,
            "top10_evidence_failures": structured_failures,
        },
        "candidate_pool_expansion": candidate_pool_expansion,
        "expected_impact": expected_impact,
        "citation_guardrails": citation_guardrails,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render aggregate-only multi-chunk evidence failure analysis.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_SUMMARY,
        help=f"eval_summary.json path (default: {DEFAULT_SUMMARY})",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=DEFAULT_OUT_JSON,
        help=f"Aggregate JSON output path (default: {DEFAULT_OUT_JSON})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary = _load_summary(args.summary)
        aggregate = build_aggregate(summary, source=source_provenance(args.summary))
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"Failed to build multi-chunk evidence aggregate: {exc}", file=sys.stderr)
        return 1
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(aggregate, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] Wrote {args.out_json}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
