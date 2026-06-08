#!/usr/bin/env python3
"""Render an aggregate-only T-2026-0076 real100_v2 retrieval collapse diagnosis.

The input eval summaries may contain private case payloads. This module never
copies case-level rows, raw queries, answers, text previews, document names, or
chunk identifiers into its output; it emits only aggregate counts/rates and safe
run-manifest fields.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_real_eval_delta import _safe_run_manifest_field
DEFAULT_CURRENT = ROOT / "reports" / "real100_v2" / "eval_summary.json"
DEFAULT_BACKUP = ROOT / "reports" / "real100_v2" / "eval_summary.hashing-backup.json"
DEFAULT_JSON = ROOT / "reports" / "real100_v2" / "retrieval_collapse_diagnosis.aggregate.json"
DEFAULT_MD = ROOT / "docs" / "evaluation" / "real100_v2-retrieval-collapse-diagnosis.md"

SAFE_MANIFEST_FIELDS = (
    "git_commit",
    "git_dirty",
    "config_sha256",
    "index_schema_version",
    "embedding_backend",
    "embedding_model_id",
    "embedding_dim",
    "vector_store_backend",
    "chunking_strategy",
    "chunker_version",
    "chunk_max_chars",
    "chunk_overlap_sentences",
    "retrieval_backend",
    "retrieval_mode",
    "retrieval_top_k",
    "retrieval_rerank",
    "rrf_k",
    "bm25_backend",
    "bm25_tokenizer",
    "bm25_stopword_profile",
)


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _case_is_answerable(case: Mapping[str, Any]) -> bool:
    if "answerable" in case:
        return bool(case.get("answerable"))
    return bool(case.get("gold_chunk_ids") or case.get("gold_evidence"))


def _gold_chunk_ids(case: Mapping[str, Any]) -> set[str]:
    explicit = {str(item) for item in (case.get("gold_chunk_ids") or []) if item}
    if explicit:
        return explicit
    return {
        str(item.get("chunk_id"))
        for item in (case.get("gold_evidence") or [])
        if isinstance(item, Mapping) and item.get("chunk_id")
    }


def _gold_doc_ids(case: Mapping[str, Any]) -> set[str]:
    explicit = {str(item) for item in (case.get("expected_doc_ids") or []) if item}
    evidence = {
        str(item.get("doc_id"))
        for item in (case.get("gold_evidence") or [])
        if isinstance(item, Mapping) and item.get("doc_id")
    }
    return explicit | evidence


def _retrieved_chunks(case: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    chunks = case.get("retrieved_chunks") or []
    return [item for item in chunks if isinstance(item, Mapping)]


def _hits_at(retrieved: Iterable[Mapping[str, Any]], gold: set[str], field: str, k: int) -> bool:
    if not gold:
        return False
    for item in list(retrieved)[:k]:
        value = item.get(field)
        if value is not None and str(value) in gold:
            return True
    return False


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _manifest(summary: Mapping[str, Any]) -> dict[str, Any]:
    source = summary.get("run_manifest") or {}
    if not isinstance(source, Mapping):
        source = {}
    return {
        field: _safe_run_manifest_field(field, source.get(field))
        for field in SAFE_MANIFEST_FIELDS
        if field in source
    }


def _page_metadata(summary: Mapping[str, Any]) -> dict[str, Any]:
    meta = summary.get("index_citation_metadata_coverage") or {}
    if not isinstance(meta, Mapping):
        return {}
    return {
        key: meta.get(key)
        for key in ("chunks_total", "chunks_with_page_span", "page_span_coverage", "coverage_reason")
        if key in meta
    }


def summarize_run(label: str, summary: Mapping[str, Any]) -> dict[str, Any]:
    cases = [case for case in (summary.get("case_results") or []) if isinstance(case, Mapping)]
    answerable_cases = [case for case in cases if _case_is_answerable(case)]
    retrieval_lengths = collections.Counter(len(_retrieved_chunks(case)) for case in cases)

    chunk_hit_at_5: list[float] = []
    chunk_hit_at_8: list[float] = []
    doc_hit_at_5: list[float] = []
    doc_hit_at_8: list[float] = []
    chunk_recall_5_values: list[float] = []
    chunk_recall_10_values: list[float] = []
    mrr5_values: list[float] = []

    for case in answerable_cases:
        retrieved = _retrieved_chunks(case)
        gold_chunks = _gold_chunk_ids(case)
        gold_docs = _gold_doc_ids(case)
        chunk_hit_at_5.append(float(_hits_at(retrieved, gold_chunks, "chunk_id", 5)))
        chunk_hit_at_8.append(float(_hits_at(retrieved, gold_chunks, "chunk_id", 8)))
        doc_hit_at_5.append(float(_hits_at(retrieved, gold_docs, "doc_id", 5)))
        doc_hit_at_8.append(float(_hits_at(retrieved, gold_docs, "doc_id", 8)))
        if isinstance(case.get("chunk_recall_at_5"), int | float):
            chunk_recall_5_values.append(float(case["chunk_recall_at_5"]))
        if isinstance(case.get("chunk_recall_at_10"), int | float):
            chunk_recall_10_values.append(float(case["chunk_recall_at_10"]))
        if isinstance(case.get("chunk_mrr_at_5"), int | float):
            mrr5_values.append(float(case["chunk_mrr_at_5"]))

    top_level = {
        "chunk_recall_at_5": summary.get("chunk_recall_at_5"),
        "chunk_recall_at_10": summary.get("chunk_recall_at_10"),
        "chunk_mrr_at_5": summary.get("chunk_mrr_at_5"),
    }
    return {
        "label": label,
        "population": {
            "num_predictions": int(summary.get("num_predictions") or len(cases)),
            "evaluated_rows_count": len(cases),
            "answerable_count": len(answerable_cases),
        },
        "run_manifest": _manifest(summary),
        "page_metadata": _page_metadata(summary),
        "retrieval": {
            "chunk_hit_at_5": _round(_mean(chunk_hit_at_5)),
            "chunk_hit_at_8": _round(_mean(chunk_hit_at_8)),
            "doc_hit_at_5": _round(_mean(doc_hit_at_5)),
            "doc_hit_at_8": _round(_mean(doc_hit_at_8)),
            "chunk_recall_at_5_mean_from_cases": _round(_mean(chunk_recall_5_values)),
            "chunk_recall_at_10_mean_from_cases": _round(_mean(chunk_recall_10_values)),
            "chunk_mrr_at_5_mean_from_cases": _round(_mean(mrr5_values)),
            "top_level_metrics": {k: _round(v) for k, v in top_level.items() if isinstance(v, int | float)},
            "retrieved_length_counts": {str(k): retrieval_lengths[k] for k in sorted(retrieval_lengths)},
        },
    }


def _delta(current: Mapping[str, Any], backup: Mapping[str, Any], path: tuple[str, ...]) -> float | None:
    left: Any = current
    right: Any = backup
    for key in path:
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            return None
        left = left.get(key)
        right = right.get(key)
    if not isinstance(left, int | float) or not isinstance(right, int | float):
        return None
    return _round(float(left) - float(right))


def _changed_stack(current: Mapping[str, Any], backup: Mapping[str, Any]) -> list[str]:
    fields = (
        "embedding_backend",
        "embedding_model_id",
        "chunking_strategy",
        "chunker_version",
        "vector_store_backend",
        "retrieval_backend",
        "retrieval_mode",
        "retrieval_top_k",
        "retrieval_rerank",
        "rrf_k",
        "bm25_backend",
        "bm25_tokenizer",
        "bm25_stopword_profile",
    )
    cur = current.get("run_manifest") or {}
    old = backup.get("run_manifest") or {}
    changed = []
    for field in fields:
        if isinstance(cur, Mapping) and isinstance(old, Mapping) and cur.get(field) != old.get(field):
            changed.append(field)
    return changed


def build_report(current_summary: Mapping[str, Any], backup_summary: Mapping[str, Any]) -> dict[str, Any]:
    current = summarize_run("current_page_aware", current_summary)
    backup = summarize_run("hashing_backup", backup_summary)
    changed = _changed_stack(current, backup)
    doc_delta = _delta(current, backup, ("retrieval", "doc_hit_at_5"))
    chunk_delta = _delta(current, backup, ("retrieval", "chunk_hit_at_5"))

    if doc_delta is not None and doc_delta <= -0.2:
        primary_signal = "doc_ranking_collapse_not_chunk_id_only"
    elif chunk_delta is not None and chunk_delta <= -0.2:
        primary_signal = "chunk_retrieval_collapse"
    else:
        primary_signal = "no_large_retrieval_delta_observed"

    return {
        "schema_version": 1,
        "profile_type": "private_real100_v2_retrieval_collapse_diagnosis",
        "generated_at": _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "privacy": {
            "redacted": True,
            "aggregate_only": True,
            "omission_policy": "omits raw private rows, prompts, answers, retrieved evidence, gold evidence, identifiers, and text previews",
        },
        "source": {
            "current_sha256_prefix": _sha_prefix(current_summary),
            "backup_sha256_prefix": _sha_prefix(backup_summary),
        },
        "current": current,
        "backup": backup,
        "comparison": {
            "changed_stack_fields": changed,
            "baseline_comparability": "not_comparable_stack_changed" if changed else "same_stack",
            "doc_hit_at_5_delta_current_minus_backup": doc_delta,
            "doc_hit_at_8_delta_current_minus_backup": _delta(current, backup, ("retrieval", "doc_hit_at_8")),
            "chunk_hit_at_5_delta_current_minus_backup": chunk_delta,
            "chunk_hit_at_8_delta_current_minus_backup": _delta(current, backup, ("retrieval", "chunk_hit_at_8")),
            "chunk_recall_at_5_delta_current_minus_backup": _delta(current, backup, ("retrieval", "chunk_recall_at_5_mean_from_cases")),
            "chunk_recall_at_10_delta_current_minus_backup": _delta(current, backup, ("retrieval", "chunk_recall_at_10_mean_from_cases")),
        },
        "diagnosis": {
            "primary_signal": primary_signal,
            "baseline_comparability": "not_comparable_stack_changed" if changed else "same_stack",
            "interpretation": (
                "The page-aware current run changed retrieval stack fields and shows a doc-level hit-rate collapse, "
                "so downstream reranker/window experiments should not treat the hashing backup as a comparable baseline."
                if primary_signal == "doc_ranking_collapse_not_chunk_id_only"
                else "No doc-level collapse signal crossed the conservative aggregate threshold."
            ),
            "recommended_next_step": (
                "Re-run or instrument a same-stack page-aware MiniLM retrieval aggregate with explicit retrieval_backend provenance before T-2026-0030/T-2026-0032/T-2026-0033 optimization."
            ),
        },
    }


def _sha_prefix(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def render_markdown(report: Mapping[str, Any]) -> str:
    current = report["current"]
    backup = report["backup"]
    comparison = report["comparison"]
    diagnosis = report["diagnosis"]

    def metric(run: Mapping[str, Any], key: str) -> Any:
        return run.get("retrieval", {}).get(key)

    lines = [
        "# T-2026-0076 real100_v2 Retrieval Collapse Diagnosis",
        "",
        "This reviewer note is aggregate-only. It intentionally omits raw case rows, queries, answers, doc IDs, chunk IDs, and text previews.",
        "",
        "## Verdict",
        "",
        f"- Primary signal: `{diagnosis['primary_signal']}`",
        f"- Baseline comparability: `{diagnosis['baseline_comparability']}`",
        f"- Recommendation: {diagnosis['recommended_next_step']}",
        "",
        "## Aggregate comparison",
        "",
        "| Metric | Current page-aware | Hashing backup | Delta current-backup |",
        "| --- | ---: | ---: | ---: |",
        f"| doc_hit_at_5 | {metric(current, 'doc_hit_at_5')} | {metric(backup, 'doc_hit_at_5')} | {comparison.get('doc_hit_at_5_delta_current_minus_backup')} |",
        f"| doc_hit_at_8 | {metric(current, 'doc_hit_at_8')} | {metric(backup, 'doc_hit_at_8')} | {comparison.get('doc_hit_at_8_delta_current_minus_backup')} |",
        f"| chunk_hit_at_5 | {metric(current, 'chunk_hit_at_5')} | {metric(backup, 'chunk_hit_at_5')} | {comparison.get('chunk_hit_at_5_delta_current_minus_backup')} |",
        f"| chunk_hit_at_8 | {metric(current, 'chunk_hit_at_8')} | {metric(backup, 'chunk_hit_at_8')} | {comparison.get('chunk_hit_at_8_delta_current_minus_backup')} |",
        f"| chunk_recall_at_5 | {metric(current, 'chunk_recall_at_5_mean_from_cases')} | {metric(backup, 'chunk_recall_at_5_mean_from_cases')} | {comparison.get('chunk_recall_at_5_delta_current_minus_backup')} |",
        "",
        "## Stack comparison",
        "",
        f"- Changed stack fields: `{', '.join(comparison.get('changed_stack_fields') or []) or 'none'}`",
        f"- Current run manifest: `{json.dumps(current.get('run_manifest', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- Backup run manifest: `{json.dumps(backup.get('run_manifest', {}), ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Interpretation",
        "",
        str(diagnosis["interpretation"]),
        "",
    ]
    return "\n".join(lines)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument("--backup", type=Path, default=DEFAULT_BACKUP)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_MD)
    args = parser.parse_args(argv)

    report = build_report(_load_json(args.current), _load_json(args.backup))
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(f"wrote {args.output_json}")
    print(f"wrote {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
