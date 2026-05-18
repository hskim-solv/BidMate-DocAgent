#!/usr/bin/env python3
"""Phase 2 retrieval-eval — chunking ablation on real100 (n=221).

Builds 3 new indexes (smaller/larger/structure_aware) and reuses the
current ``data/index/real100`` for the baseline. For each of 4 variants
runs the planner-bypass ``retrieve_candidates`` against eval-config
cases and computes paired bootstrap CI deltas vs ``current`` per
category. Output lives under
``reports/retrieval/phase2_chunking_<TIMESTAMP>/``:

* ``chunking_specs.json``  — variant metadata + section_detection_rate
* ``raw_results.json``     — per-case scores for all 4 variants
* ``REPORT.md``            — <=200 line markdown with per-category
  winner or "NOT SIGNIFICANT" (CI crosses 0)

Reuses (no new abstraction):

* ``rag_indexing.build_index_payload_from_documents``
* ``rag_retrieval.retrieve_candidates`` (planner bypass — full query
  as the only sub-query, identity expansion, no rerank)
* ``eval.scorers.chunk_metrics.{derive_gold_chunk_ids,
  chunk_recall_at_k, chunk_mrr, chunk_ndcg_at_k}``
* ``eval.bootstrap.paired_bootstrap_ci`` (PR #950)

Heuristic boundary detector for the structure-aware variant is
inlined (~25 LOC, RFP-specific patterns). Not factored out because
this script is the only call site (absolute rule #3).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from eval.scorers.chunk_metrics import (  # noqa: E402
    chunk_mrr,
    chunk_ndcg_at_k,
    chunk_recall_at_k,
    derive_gold_chunk_ids,
)
from ingestion import load_documents_from_metadata_csv  # noqa: E402
from rag_indexing import (  # noqa: E402
    EMBEDDINGS_FILENAME,
    build_index_payload_from_documents,
    load_index,
    write_index,
)
from rag_retrieval import retrieve_candidates  # noqa: E402
from rag_text_processing import tokenize  # noqa: E402
from scripts._ablation_common import (  # noqa: E402
    _category_split,
    _drop_paired_nones,
    _fmt_ci,
    _fmt_mean,
    _seed_averaged_paired_ci,
    categories_from_case,
    compute_deltas,
)


CATEGORY_BY_TYPE = {
    "single_doc": "single_hop",
    "follow_up": "single_hop",
    "multi_doc": "multi_hop",
    "abstention": "no_answer",
}


@dataclass(frozen=True)
class VariantSpec:
    name: str
    chunking_strategy: str
    max_chars: int
    overlap_sentences: int
    index_dir: Path
    needs_heuristic_split: bool  # True only for structure_aware


# --- Heuristic boundary detector (RFP-specific, inline) ---------------

# Korean section headers (제 N 장/조/항) — common in RFP/contract bodies.
_KO_HEADER = re.compile(r"^\s*제\s*\d+\s*[장조항편]", re.MULTILINE)
# Enumeration: "1. " / "1.1 " / "1.1.1 " or "가. " / "(1) ".
_ENUM = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\s+|\([0-9가-힣]+\)\s+|[가-힣]\.\s+)", re.MULTILINE
)
# Markdown headings.
_MD_HEADER = re.compile(r"^\s*#{1,6}\s+\S", re.MULTILINE)
# Blank-line gap (>= 2 consecutive newlines).
_BLANK_GAP = re.compile(r"\n\s*\n\s*\n+")

# Minimum body characters to consider splitting (avoid trivial fragments).
_MIN_SPLIT_BODY = 300
# Minimum chars per emitted section (merge adjacent if smaller).
_MIN_SECTION_CHARS = 80


def detect_boundaries(text: str) -> list[int]:
    """Return sorted unique line-start offsets where a section boundary
    is plausible. Empty list when no heuristic engages — the caller
    keeps the input as a single section in that case.
    """
    if not text or len(text) < _MIN_SPLIT_BODY:
        return []
    offsets: set[int] = set()
    for pattern in (_KO_HEADER, _ENUM, _MD_HEADER):
        for match in pattern.finditer(text):
            offsets.add(match.start())
    for match in _BLANK_GAP.finditer(text):
        offsets.add(match.end())
    offsets.discard(0)
    return sorted(offsets)


def split_body_into_sections(body_text: str) -> tuple[list[dict[str, str]], bool]:
    """Apply heuristic boundary detection and return ``(sections, engaged)``.

    ``engaged`` is True iff at least one boundary survived merging and
    yielded >1 section. When False the caller keeps the single
    ``[{"heading": "본문", "text": body_text}]`` ingestion default — this
    is the honest "heuristic did not fire" path (absolute rule #5).
    """
    boundaries = detect_boundaries(body_text)
    if not boundaries:
        return [{"heading": "본문", "text": body_text}], False

    boundaries = [0, *boundaries, len(body_text)]
    raw_pieces: list[str] = []
    for start, end in zip(boundaries, boundaries[1:]):
        piece = body_text[start:end].strip()
        if piece:
            raw_pieces.append(piece)

    # Merge tiny adjacent pieces into the previous to avoid <80-char shrapnel.
    merged: list[str] = []
    for piece in raw_pieces:
        if merged and len(piece) < _MIN_SECTION_CHARS:
            merged[-1] = merged[-1] + "\n" + piece
        else:
            merged.append(piece)

    if len(merged) < 2:
        return [{"heading": "본문", "text": body_text}], False

    sections: list[dict[str, str]] = []
    for idx, piece in enumerate(merged, start=1):
        first_line = piece.splitlines()[0].strip() if piece else f"section-{idx}"
        heading = first_line[:80] if first_line else f"section-{idx}"
        sections.append({"heading": heading, "text": piece})
    return sections, True


# --- Build pipeline ---------------------------------------------------


def patch_documents_with_heuristic_sections(
    documents: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    """Replace each doc's single ingestion section with heuristic-split
    sections (where engagement fires). Returns ``(patched, engaged_n, total_n)``.
    """
    patched: list[dict[str, Any]] = []
    engaged = 0
    for doc in documents:
        sections = doc.get("sections") or []
        body = ""
        if sections:
            body = "\n\n".join(str(s.get("text") or "") for s in sections).strip()
        if not body:
            patched.append(doc)
            continue
        new_sections, did_engage = split_body_into_sections(body)
        if did_engage:
            engaged += 1
        patched_doc = dict(doc)
        patched_doc["sections"] = new_sections
        patched.append(patched_doc)
    return patched, engaged, len(documents)


def build_variant_index(
    spec: VariantSpec,
    documents: list[dict[str, Any]],
    metadata_csv: Path,
    embedding_backend: str,
) -> dict[str, Any]:
    """Build one variant's index from preloaded ingestion ``documents``.

    Returns a small diagnostics dict ``{name, num_docs, num_chunks,
    section_detection_rate, heuristic_engagement_rate (structure_aware only)}``.
    ``documents`` is loaded once in ``main()`` and reused across variants
    so HWP/PDF parsing (the ingestion bottleneck) runs once total.
    """
    heuristic_engagement_rate: float | None = None
    docs_for_build = documents
    if spec.needs_heuristic_split:
        docs_for_build, engaged_n, total_n = patch_documents_with_heuristic_sections(documents)
        heuristic_engagement_rate = (engaged_n / total_n) if total_n else None
        print(
            f"[build] {spec.name}: heuristic split engaged on "
            f"{engaged_n}/{total_n} docs "
            f"({heuristic_engagement_rate * 100 if heuristic_engagement_rate else 0:.1f}%)",
            flush=True,
        )

    print(
        f"[build] {spec.name}: chunking strategy={spec.chunking_strategy}, "
        f"max_chars={spec.max_chars}, overlap={spec.overlap_sentences}",
        flush=True,
    )
    payload = build_index_payload_from_documents(
        docs_for_build,
        source_dir=str(metadata_csv),
        embedding_backend=embedding_backend,
        chunking_strategy=spec.chunking_strategy,
        chunk_max_chars=spec.max_chars,
        chunk_overlap_sentences=spec.overlap_sentences,
        message=f"Phase 2 chunking ablation variant: {spec.name}",
    )
    spec.index_dir.mkdir(parents=True, exist_ok=True)
    num_docs = payload["build"]["num_documents"]
    num_chunks = payload["build"]["num_chunks"]
    section_detection_rate = payload["build"]["chunking"].get("section_detection_rate")
    out_path = write_index(payload, spec.index_dir)
    print(
        f"[build] {spec.name}: wrote {out_path} ({num_docs} docs, "
        f"{num_chunks} chunks, +{(spec.index_dir / EMBEDDINGS_FILENAME).name})",
        flush=True,
    )
    return {
        "name": spec.name,
        "chunking_strategy": spec.chunking_strategy,
        "chunk_max_chars": spec.max_chars,
        "chunk_overlap_sentences": spec.overlap_sentences,
        "num_documents": num_docs,
        "num_chunks": num_chunks,
        "section_detection_rate": section_detection_rate,
        "heuristic_engagement_rate": heuristic_engagement_rate,
        "index_dir": str(spec.index_dir),
    }


# --- Measurement ------------------------------------------------------


def build_stub(query: str, top_k: int) -> tuple[dict[str, Any], dict[str, Any]]:
    analysis = {
        "query_type": "single_doc",
        "tokens": list(tokenize(query)),
        "topics": [],
        "entities": [],
        "metadata_filters_by_stage": {"strict": {}, "reduced": {}, "relaxed": {}},
    }
    plan = {
        "retrieval_backend": "dense",
        "metadata_filters": {},
        "metadata_first": False,
        "rerank": False,
        "query_expansion": "identity",
        "bm25_stopword_profile": "shared",
        "bm25_tokenizer": "regex",
        "top_k": top_k,
    }
    return analysis, plan


def run_single_case(
    index: dict[str, Any], case: dict[str, Any], top_k: int
) -> tuple[list[str], float]:
    query = str(case.get("query") or "")
    analysis, plan = build_stub(query, top_k)
    t0 = time.perf_counter()
    retrieved = retrieve_candidates(index, query, analysis, plan)
    latency_ms = (time.perf_counter() - t0) * 1000.0
    retrieved_sorted = sorted(retrieved, key=lambda c: c["score"], reverse=True)[:top_k]
    return [str(c["chunk_id"]) for c in retrieved_sorted], latency_ms


def measure_variant(
    variant_name: str,
    index: dict[str, Any],
    cases: list[dict[str, Any]],
    top_k: int,
    ks: list[int],
    warmup_n: int,
) -> dict[str, Any]:
    """Run ``cases`` through ``index`` and return per-case + aggregate scores.

    Per-case scores are the inputs to paired bootstrap CI, so each
    case keeps its position in the ``cases`` list — a None entry
    means "metric not applicable" (e.g. no_answer cases have no gold
    chunks for recall@k) and the caller drops both arrays' Nones in
    sync to preserve pairing.
    """
    print(f"[measure] {variant_name}: {len(cases)} cases (warmup {warmup_n})", flush=True)
    for case in cases[:warmup_n]:
        run_single_case(index, case, top_k)

    per_case_rows: list[dict[str, Any]] = []
    latency_vals: list[float] = []
    for idx, case in enumerate(cases, 1):
        qid = case.get("id") or case.get("qid") or f"?#{idx}"
        qt = case.get("query_type") or "unknown"
        category = CATEGORY_BY_TYPE.get(qt, "other")
        gold_chunk_ids = derive_gold_chunk_ids(case, index)
        retrieved_chunk_ids, latency_ms = run_single_case(index, case, top_k)
        latency_vals.append(latency_ms)
        row: dict[str, Any] = {
            "qid": qid,
            "query_type": qt,
            "category": category,
            "categories": categories_from_case(case),
            "gold_chunk_n": len(gold_chunk_ids),
            "latency_ms": round(latency_ms, 3),
        }
        for k in ks:
            row[f"chunk_recall@{k}"] = chunk_recall_at_k(
                retrieved_chunk_ids, gold_chunk_ids, k
            )
        row["mrr"] = chunk_mrr(retrieved_chunk_ids, gold_chunk_ids)
        row["ndcg@10"] = chunk_ndcg_at_k(retrieved_chunk_ids, gold_chunk_ids, 10)
        per_case_rows.append(row)
        if idx % 50 == 0:
            print(f"[measure] {variant_name}: {idx}/{len(cases)}", flush=True)

    return {
        "variant": variant_name,
        "per_case": per_case_rows,
        "latency_ms": {
            "p50": round(statistics.median(latency_vals), 3) if latency_vals else None,
            "p95": (
                round(statistics.quantiles(latency_vals, n=20)[-1], 3)
                if len(latency_vals) > 1
                else (round(latency_vals[0], 3) if latency_vals else None)
            ),
            "mean": round(statistics.mean(latency_vals), 3) if latency_vals else None,
            "n": len(latency_vals),
        },
    }


# --- Report rendering -------------------------------------------------
# (paired CI aggregation + formatting helpers extracted to
# scripts/_ablation_common — imported above and shared with Phase 3.)


def render_report(
    out_dir: Path,
    specs: list[dict[str, Any]],
    measurements: dict[str, dict[str, Any]],
    deltas: dict[str, dict[str, dict[str, dict[str, Any] | None]]],
    config: dict[str, Any],
) -> None:
    """Write REPORT.md (<=200 lines). ``deltas`` shape:
    ``{other_name: {metric: {category: ci}}}``.
    """
    lines: list[str] = []
    lines.append(f"# Phase 2 retrieval-eval — chunking ablation (real100 n={config['num_cases']})")
    lines.append("")
    lines.append(
        f"Run: `{config['run_id']}` · commit `{config['git_commit'][:10]}` · "
        f"index_dir_current=`{config['index_dir_current']}` · "
        f"eval_config=`{config['eval_config']}` · "
        f"seeds={config['seeds']} · top_k={config['top_k']} · ks={config['ks']}"
    )
    lines.append("")
    lines.append("## Variants")
    lines.append("")
    lines.append("| Variant | Strategy | Max chars | Overlap | Docs | Chunks | Section detect | Heuristic engaged |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for spec in specs:
        sd = spec.get("section_detection_rate")
        he = spec.get("heuristic_engagement_rate")
        sd_str = f"{sd * 100:.1f}%" if sd is not None else "—"
        he_str = f"{he * 100:.1f}%" if he is not None else "—"
        lines.append(
            f"| `{spec['name']}` | {spec['chunking_strategy']} | "
            f"{spec['chunk_max_chars']} | {spec['chunk_overlap_sentences']} | "
            f"{spec['num_documents']} | {spec['num_chunks']} | "
            f"{sd_str} | {he_str} |"
        )
    lines.append("")
    lines.append("## Latency (ms)")
    lines.append("")
    lines.append("| Variant | p50 | p95 | mean | n |")
    lines.append("|---|---|---|---|---|")
    for variant_name in [s["name"] for s in specs]:
        lat = measurements[variant_name]["latency_ms"]
        lines.append(
            f"| `{variant_name}` | {lat['p50']} | {lat['p95']} | {lat['mean']} | {lat['n']} |"
        )
    lines.append("")

    metrics_to_report = ["chunk_recall@5", "chunk_recall@10", "mrr", "ndcg@10"]
    categories = [
        "overall",
        "multi_hop",
        "distractor_heavy",
        "long_context",
        "no_answer",
        "ambiguous_query",
        "uncategorized",
    ]

    for metric in metrics_to_report:
        lines.append(f"## {metric}")
        lines.append("")
        header_cols = ["Category"] + [f"`{s['name']}`" for s in specs]
        lines.append("| " + " | ".join(header_cols) + " |")
        lines.append("|" + "|".join(["---"] * len(header_cols)) + "|")
        for category in categories:
            cells = [category]
            for spec in specs:
                cat_arg = None if category == "overall" else category
                cells.append(
                    _fmt_mean(measurements[spec["name"]]["per_case"], metric, cat_arg)
                )
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
        lines.append(f"### {metric} — paired CI delta vs `current` (seed-averaged)")
        lines.append("")
        header_cols = ["Category"] + [
            f"`{s['name']}`" for s in specs if s["name"] != "current"
        ]
        lines.append("| " + " | ".join(header_cols) + " |")
        lines.append("|" + "|".join(["---"] * len(header_cols)) + "|")
        for category in categories:
            cells = [category]
            for spec in specs:
                if spec["name"] == "current":
                    continue
                ci = deltas.get(spec["name"], {}).get(metric, {}).get(category)
                cells.append(_fmt_ci(ci))
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    lines.append("## Per-category winner")
    lines.append("")
    lines.append(
        "Winner = variant with highest `chunk_recall@10` mean AND paired CI vs `current` "
        "fully above 0. \"NOT SIGNIFICANT\" = no variant's CI clears 0 (absolute rule #5)."
    )
    lines.append("")
    lines.append("| Category | Winner | Mean recall@10 | Delta CI vs current |")
    lines.append("|---|---|---|---|")
    for category in categories:
        winner = "NOT SIGNIFICANT"
        winner_mean: float | None = None
        winner_ci: dict[str, Any] | None = None
        for spec in specs:
            if spec["name"] == "current":
                continue
            ci = deltas.get(spec["name"], {}).get("chunk_recall@10", {}).get(category)
            if ci is None:
                continue
            if ci["ci_lo"] > 0 and (winner_mean is None or ci["mean_other"] > winner_mean):
                winner = spec["name"]
                winner_mean = ci["mean_other"]
                winner_ci = ci
        mean_str = f"{winner_mean:.3f}" if winner_mean is not None else "—"
        ci_str = _fmt_ci(winner_ci) if winner_ci is not None else "—"
        lines.append(f"| {category} | `{winner}` | {mean_str} | {ci_str} |")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "* Planner-bypass: full query as the only sub-query, identity expansion, "
        "no rerank — isolates chunking impact from query expansion / rerank effects."
    )
    lines.append(
        "* `chunk_recall@k` is None for cases without `expected_terms` / "
        "`expected_doc_ids` (e.g. abstention) — those are dropped pairwise to "
        "preserve case alignment between current and the variant."
    )
    lines.append(
        "* Seeds drive only the bootstrap RNG; retrieval itself is deterministic "
        "for the same query+index (hashing-backend / dense backend both)."
    )
    lines.append("* Index storage: `data/index/phase2_smaller`, `phase2_larger`, `phase2_structure_aware`.")
    lines.append(
        "* Category bucketing uses `hardcase_categories` (semantic difficulty tags) "
        "from the eval config. The legacy `query_type` field "
        "(single_doc / multi_doc / follow_up / abstention) is **not** used here. "
        "A case tagged with N categories appears in N buckets, so per-category "
        "counts overlap and per-category paired CIs share cases — combining "
        "multiple categories via OR inflates family-wise error rate."
    )
    lines.append(
        "* `uncategorized` covers cases without `hardcase_categories` tags "
        "(typically the initial seed + probe cases authored before the tag "
        "schema). They still contribute to `overall`."
    )
    lines.append(
        "* Phase 1 baseline (`UNIFIED_PHASE1_REPORT.md`) categorized by "
        "`query_type` (e.g. `multi_doc → multi_hop` with n=1); direct "
        "cross-phase category-by-category trend comparison is not meaningful "
        "until Phase 1 is re-aggregated against the same `hardcase_categories` "
        "field."
    )
    if config.get("reaggregate_source"):
        lines.append(
            "* This report was regenerated via `--reaggregate` from "
            f"`{config['reaggregate_source']}` — categorization re-derived "
            "from `hardcase_categories`; retrieval scores in "
            "`raw_results.json` are unchanged byte-for-byte modulo the "
            "injected `categories` field."
        )

    report_path = out_dir / "REPORT.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[report] wrote {report_path} ({len(lines)} lines)", flush=True)


# --- Orchestration ----------------------------------------------------


def _git_state() -> tuple[str, bool]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        dirty = bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        )
        return commit, dirty
    except Exception:
        return "unknown", True


def _resolve_specs(args: argparse.Namespace) -> list[VariantSpec]:
    return [
        VariantSpec(
            name="current",
            chunking_strategy="fixed",
            max_chars=520,
            overlap_sentences=1,
            index_dir=Path(args.index_dir_current),
            needs_heuristic_split=False,
        ),
        VariantSpec(
            name="smaller",
            chunking_strategy="fixed",
            max_chars=260,
            overlap_sentences=1,
            index_dir=Path(args.index_dir_smaller),
            needs_heuristic_split=False,
        ),
        VariantSpec(
            name="larger",
            chunking_strategy="fixed",
            max_chars=1040,
            overlap_sentences=1,
            index_dir=Path(args.index_dir_larger),
            needs_heuristic_split=False,
        ),
        VariantSpec(
            name="structure_aware",
            chunking_strategy="section",
            max_chars=520,
            overlap_sentences=1,
            index_dir=Path(args.index_dir_structure_aware),
            needs_heuristic_split=True,
        ),
    ]


def _run_reaggregate(
    args: argparse.Namespace,
    out_dir: Path,
    seeds: list[int],
    ks: list[int],
) -> int:
    """Re-derive ``row['categories']`` from ``hardcase_categories`` and
    regenerate deltas + REPORT.md without touching retrieval.

    Use case: original measurement bucketed by ``query_type`` (which only
    distinguishes single_doc / multi_doc / follow_up / abstention) and
    therefore reported ``multi_hop n=1`` even though the eval config
    carries 95 cases tagged ``multi_hop`` via ``hardcase_categories``.
    Re-aggregation is cheap because retrieval is deterministic and the
    per-case scores are already in ``raw_results.json``.
    """
    raw_path = Path(args.reaggregate)
    if not raw_path.exists():
        print(f"[ERROR] --reaggregate path not found: {raw_path}", file=sys.stderr)
        return 2
    print(f"[reaggregate] loading {raw_path}", flush=True)
    measurements = json.loads(raw_path.read_text(encoding="utf-8"))

    cfg = yaml.safe_load(Path(args.eval_config).read_text(encoding="utf-8"))
    cases = cfg.get("cases", []) or []
    cases_by_qid = {str(c.get("id")): c for c in cases}

    untagged_per_variant: int | None = None
    for variant_name, m in measurements.items():
        rows = m.get("per_case", []) or []
        untagged = 0
        for row in rows:
            case = cases_by_qid.get(str(row.get("qid")))
            tags = categories_from_case(case or {})
            row["categories"] = tags
            if tags == ["uncategorized"]:
                untagged += 1
        if untagged_per_variant is None:
            untagged_per_variant = untagged
        print(
            f"[reaggregate] {variant_name}: {len(rows)} rows, "
            f"{untagged} uncategorized",
            flush=True,
        )

    specs_path = raw_path.parent / "chunking_specs.json"
    if not specs_path.exists():
        print(
            f"[ERROR] chunking_specs.json not found beside raw: {specs_path}",
            file=sys.stderr,
        )
        return 2
    spec_metas = json.loads(specs_path.read_text(encoding="utf-8"))
    (out_dir / "chunking_specs.json").write_text(
        json.dumps(spec_metas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (out_dir / "raw_results.json").write_text(
        json.dumps(measurements, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("[phase] deltas (reaggregate)", flush=True)
    metrics_to_delta = [f"chunk_recall@{k}" for k in ks] + ["mrr", "ndcg@10"]
    deltas: dict[str, dict[str, dict[str, dict[str, Any] | None]]] = {}
    current_rows = measurements["current"]["per_case"]
    for variant_name in measurements:
        if variant_name == "current":
            continue
        deltas[variant_name] = {
            metric: compute_deltas(
                current_rows, measurements[variant_name]["per_case"], metric, seeds
            )
            for metric in metrics_to_delta
        }
    (out_dir / "deltas.json").write_text(
        json.dumps(deltas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    git_commit, git_dirty = _git_state()
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        + "-phase2-chunking-reaggregate"
    )
    current_idx = next(
        (s for s in spec_metas if s.get("name") == "current"),
        {"index_dir": "unknown"},
    )
    config = {
        "run_id": run_id,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "index_dir_current": current_idx.get("index_dir", "unknown"),
        "eval_config": args.eval_config,
        "seeds": seeds,
        "top_k": args.top_k,
        "ks": ks,
        "num_cases": len(current_rows),
        "embedding_backend": args.embedding_backend,
        "reaggregate_source": str(raw_path),
    }
    print("[phase] render (reaggregate)", flush=True)
    render_report(out_dir, spec_metas, measurements, deltas, config)
    print(f"[done] output_dir={out_dir}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata_csv", default=None)
    parser.add_argument("--files_dir", default=None)
    parser.add_argument("--index_dir_current", default=None)
    parser.add_argument("--index_dir_smaller", default=None)
    parser.add_argument("--index_dir_larger", default=None)
    parser.add_argument("--index_dir_structure_aware", default=None)
    parser.add_argument("--eval_config", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument(
        "--build",
        action="store_true",
        help="Build the 3 non-current indexes before measurement (skip if already present).",
    )
    parser.add_argument(
        "--reaggregate",
        default=None,
        help=(
            "Path to an existing raw_results.json. Skips build + measurement, "
            "re-derives row['categories'] from hardcase_categories in --eval_config, "
            "and regenerates deltas + REPORT.md into --output_dir. "
            "Companion chunking_specs.json must sit beside raw_results.json."
        ),
    )
    parser.add_argument("--seeds", default="17,23,29")
    parser.add_argument("--top_k", type=int, default=20)
    parser.add_argument("--ks", default="5,10")
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument(
        "--embedding_backend",
        default=os.environ.get("EMBEDDING_BACKEND", "hashing"),
        help="Embedding backend for the 3 built indexes (default: hashing — deterministic).",
    )
    args = parser.parse_args()

    seeds = [int(x) for x in args.seeds.split(",")]
    ks = [int(x) for x in args.ks.split(",")]
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.reaggregate:
        return _run_reaggregate(args, out_dir, seeds, ks)

    missing = [
        name
        for name, val in [
            ("--metadata_csv", args.metadata_csv),
            ("--files_dir", args.files_dir),
            ("--index_dir_current", args.index_dir_current),
            ("--index_dir_smaller", args.index_dir_smaller),
            ("--index_dir_larger", args.index_dir_larger),
            ("--index_dir_structure_aware", args.index_dir_structure_aware),
        ]
        if not val
    ]
    if missing:
        parser.error(
            "the following arguments are required for measurement runs "
            f"(omit only with --reaggregate): {', '.join(missing)}"
        )

    specs = _resolve_specs(args)

    if args.build:
        print("[phase] build", flush=True)
        print(
            f"[build] loading documents from {args.metadata_csv} (HWP/PDF parsing, one-time)",
            flush=True,
        )
        documents, _ingestion_report = load_documents_from_metadata_csv(
            Path(args.metadata_csv), Path(args.files_dir), on_duplicate_doc_id="fail"
        )
        print(f"[build] loaded {len(documents)} documents", flush=True)
        spec_metas: list[dict[str, Any]] = []
        for spec in specs:
            if spec.name == "current":
                # Reuse — read diagnostics from on-disk payload.
                payload = load_index(spec.index_dir)
                spec_metas.append(
                    {
                        "name": spec.name,
                        "chunking_strategy": spec.chunking_strategy,
                        "chunk_max_chars": spec.max_chars,
                        "chunk_overlap_sentences": spec.overlap_sentences,
                        "num_documents": len(payload.get("documents", [])),
                        "num_chunks": len(payload.get("chunks", [])),
                        "section_detection_rate": (payload.get("build", {})
                            .get("chunking", {})
                            .get("section_detection_rate")),
                        "heuristic_engagement_rate": None,
                        "index_dir": str(spec.index_dir),
                    }
                )
                continue
            spec_metas.append(
                build_variant_index(
                    spec, documents, Path(args.metadata_csv), args.embedding_backend
                )
            )
        (out_dir / "chunking_specs.json").write_text(
            json.dumps(spec_metas, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        # Re-derive specs from existing payloads (no build).
        spec_metas = []
        for spec in specs:
            payload = load_index(spec.index_dir)
            spec_metas.append(
                {
                    "name": spec.name,
                    "chunking_strategy": spec.chunking_strategy,
                    "chunk_max_chars": spec.max_chars,
                    "chunk_overlap_sentences": spec.overlap_sentences,
                    "num_documents": len(payload.get("documents", [])),
                    "num_chunks": len(payload.get("chunks", [])),
                    "section_detection_rate": (payload.get("build", {})
                        .get("chunking", {})
                        .get("section_detection_rate")),
                    "heuristic_engagement_rate": None,
                    "index_dir": str(spec.index_dir),
                }
            )
        (out_dir / "chunking_specs.json").write_text(
            json.dumps(spec_metas, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print("[phase] measure", flush=True)
    cfg = yaml.safe_load(Path(args.eval_config).read_text(encoding="utf-8"))
    cases = cfg.get("cases", []) or []
    print(f"[measure] {len(cases)} cases", flush=True)

    measurements: dict[str, dict[str, Any]] = {}
    for spec in specs:
        index = load_index(spec.index_dir)
        measurements[spec.name] = measure_variant(
            spec.name, index, cases, args.top_k, ks, args.warmup
        )

    raw_path = out_dir / "raw_results.json"
    raw_path.write_text(
        json.dumps(measurements, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[measure] wrote {raw_path}", flush=True)

    print("[phase] deltas", flush=True)
    metrics_to_delta = [f"chunk_recall@{k}" for k in ks] + ["mrr", "ndcg@10"]
    deltas: dict[str, dict[str, dict[str, dict[str, Any] | None]]] = {}
    current_rows = measurements["current"]["per_case"]
    for spec in specs:
        if spec.name == "current":
            continue
        deltas[spec.name] = {
            metric: compute_deltas(
                current_rows, measurements[spec.name]["per_case"], metric, seeds
            )
            for metric in metrics_to_delta
        }
    (out_dir / "deltas.json").write_text(
        json.dumps(deltas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    git_commit, git_dirty = _git_state()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M") + "-phase2-chunking"
    config = {
        "run_id": run_id,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "index_dir_current": str(specs[0].index_dir),
        "eval_config": args.eval_config,
        "seeds": seeds,
        "top_k": args.top_k,
        "ks": ks,
        "num_cases": len(cases),
        "embedding_backend": args.embedding_backend,
    }

    print("[phase] render", flush=True)
    render_report(out_dir, spec_metas, measurements, deltas, config)
    print(f"[done] output_dir={out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
