#!/usr/bin/env python3
"""Phase 3 retrieval-eval — mode ablation on real100 (n=221).

Runs 4 retrieval-mode variants against the same ``data/index/real100``
index (no reindexing) and computes paired bootstrap CI deltas vs the
``dense`` baseline per category:

* ``dense``              — ADR 0001 baseline retrieval path
* ``hybrid_bm25_k30``    — RRF over (dense, BM25), k=30 (more top-rank weight)
* ``hybrid_bm25_k60``    — RRF over (dense, BM25), k=60 (ADR 0010 default)
* ``hybrid_bm25_k100``   — RRF over (dense, BM25), k=100 (smoother)

m3 (FlagEmbedding, separate index) and k=10 are out of scope for
Phase 3 — deferred to Phase 3.5 with rationale in the REPORT.md Notes.

Output lives under ``reports/retrieval/phase3_mode_<TIMESTAMP>/``:

* ``mode_specs.json``  — variant metadata
* ``raw_results.json`` — per-case scores for all 4 variants
* ``deltas.json``      — paired CI vs dense per (variant, metric, category)
* ``REPORT.md``        — <=200 line markdown with per-category winner or
  ``NOT SIGNIFICANT`` (CI crosses 0) per absolute rule #5

Reuses (no new abstraction — absolute rule #3):

* ``rag_retrieval.retrieve_candidates`` (planner bypass — full query as
  the only sub-query, identity expansion, no rerank, ``metadata_first=False``)
* ``rag_indexing.load_index``
* ``eval.scorers.chunk_metrics.{derive_gold_chunk_ids, chunk_recall_at_k,
  chunk_mrr, chunk_ndcg_at_k}``
* ``scripts._ablation_common`` — paired CI aggregation + report formatting
  helpers extracted in PR-C (issue #953)

BM25 is built lazily on the first hybrid call via
``rag_retrieval.get_or_build_bm25`` and cached on the index dict, so
``hybrid_bm25_k30`` pays the BM25 build cost once and ``k60`` / ``k100``
are cache hits.
"""
from __future__ import annotations

import argparse
import json
import os
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
from rag_indexing import load_index  # noqa: E402
from rag_retrieval import retrieve_candidates  # noqa: E402
from rag_text_processing import tokenize  # noqa: E402
from scripts._ablation_common import (  # noqa: E402
    _fmt_ci,
    _fmt_mean,
    categories_from_case,
    compute_deltas,
)


@dataclass(frozen=True)
class VariantSpec:
    name: str
    retrieval_backend: str  # "dense" | "hybrid"
    rrf_k: int | None       # None for dense
    index_dir: Path         # all 4 variants share the same dir


def _plan_for_variant(spec: VariantSpec, top_k: int) -> dict[str, Any]:
    """Build a plan dict that exercises exactly the variant's retrieval
    mode — everything else (expansion, rerank, metadata-first) is held
    flat across variants to isolate the mode effect.
    """
    plan: dict[str, Any] = {
        "retrieval_backend": spec.retrieval_backend,
        "metadata_filters": {},
        "metadata_first": False,
        "rerank": False,
        "query_expansion": "identity",
        "bm25_stopword_profile": "shared",
        "bm25_tokenizer": "regex",
        "top_k": top_k,
    }
    if spec.rrf_k is not None:
        plan["rrf_k"] = spec.rrf_k
    return plan


def _analysis_stub(query: str) -> dict[str, Any]:
    return {
        "query_type": "single_doc",
        "tokens": list(tokenize(query)),
        "topics": [],
        "entities": [],
        "metadata_filters_by_stage": {"strict": {}, "reduced": {}, "relaxed": {}},
    }


def run_single_case(
    index: dict[str, Any], case: dict[str, Any], spec: VariantSpec, top_k: int
) -> tuple[list[str], float]:
    query = str(case.get("query") or "")
    analysis = _analysis_stub(query)
    plan = _plan_for_variant(spec, top_k)
    t0 = time.perf_counter()
    retrieved = retrieve_candidates(index, query, analysis, plan)
    latency_ms = (time.perf_counter() - t0) * 1000.0
    retrieved_sorted = sorted(retrieved, key=lambda c: c["score"], reverse=True)[:top_k]
    return [str(c["chunk_id"]) for c in retrieved_sorted], latency_ms


def measure_variant(
    spec: VariantSpec,
    index: dict[str, Any],
    cases: list[dict[str, Any]],
    top_k: int,
    ks: list[int],
    warmup_n: int,
) -> dict[str, Any]:
    """Run ``cases`` through ``index`` for ``spec`` and return per-case +
    aggregate scores. Per-case rows preserve list order so paired CI in
    ``compute_deltas`` aligns across variants.
    """
    print(f"[measure] {spec.name}: {len(cases)} cases (warmup {warmup_n})", flush=True)
    for case in cases[:warmup_n]:
        run_single_case(index, case, spec, top_k)

    per_case_rows: list[dict[str, Any]] = []
    latency_vals: list[float] = []
    for idx, case in enumerate(cases, 1):
        qid = case.get("id") or case.get("qid") or f"?#{idx}"
        qt = case.get("query_type") or "unknown"
        gold_chunk_ids = derive_gold_chunk_ids(case, index)
        retrieved_chunk_ids, latency_ms = run_single_case(index, case, spec, top_k)
        latency_vals.append(latency_ms)
        row: dict[str, Any] = {
            "qid": qid,
            "query_type": qt,
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
            print(f"[measure] {spec.name}: {idx}/{len(cases)}", flush=True)

    return {
        "variant": spec.name,
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
    baseline = config["baseline"]
    lines: list[str] = []
    lines.append(
        f"# Phase 3 retrieval-eval — mode ablation (real100 n={config['num_cases']})"
    )
    lines.append("")
    lines.append(
        f"Run: `{config['run_id']}` · commit `{config['git_commit'][:10]}` · "
        f"index_dir=`{config['index_dir']}` · "
        f"eval_config=`{config['eval_config']}` · "
        f"seeds={config['seeds']} · top_k={config['top_k']} · ks={config['ks']}"
    )
    lines.append("")
    lines.append("## Variants")
    lines.append("")
    lines.append("| Variant | Backend | RRF k | Docs | Chunks |")
    lines.append("|---|---|---|---|---|")
    for spec in specs:
        rrf = spec.get("rrf_k")
        rrf_str = str(rrf) if rrf is not None else "—"
        lines.append(
            f"| `{spec['name']}` | {spec['retrieval_backend']} | {rrf_str} | "
            f"{spec['num_documents']} | {spec['num_chunks']} |"
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
        lines.append(f"### {metric} — paired CI delta vs `{baseline}` (seed-averaged)")
        lines.append("")
        header_cols = ["Category"] + [
            f"`{s['name']}`" for s in specs if s["name"] != baseline
        ]
        lines.append("| " + " | ".join(header_cols) + " |")
        lines.append("|" + "|".join(["---"] * len(header_cols)) + "|")
        for category in categories:
            cells = [category]
            for spec in specs:
                if spec["name"] == baseline:
                    continue
                ci = deltas.get(spec["name"], {}).get(metric, {}).get(category)
                cells.append(_fmt_ci(ci))
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    lines.append("## Per-category winner")
    lines.append("")
    lines.append(
        f"Winner = variant with highest `chunk_recall@10` mean AND paired CI vs "
        f"`{baseline}` fully above 0. \"NOT SIGNIFICANT\" = no variant's CI clears 0 "
        f"(absolute rule #5)."
    )
    lines.append("")
    lines.append("| Category | Winner | Mean recall@10 | Delta CI vs " + f"`{baseline}` |")
    lines.append("|---|---|---|---|")
    for category in categories:
        winner = "NOT SIGNIFICANT"
        winner_mean: float | None = None
        winner_ci: dict[str, Any] | None = None
        for spec in specs:
            if spec["name"] == baseline:
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
        "no rerank, `metadata_first=False` — isolates retrieval-mode impact from "
        "expansion / rerank / metadata-filter effects."
    )
    lines.append(
        "* All 4 variants share `data/index/real100`; only `plan['retrieval_backend']` "
        "and `plan['rrf_k']` differ. BM25 lazy-builds on the first hybrid call via "
        "`rag_retrieval.get_or_build_bm25` and is cached on the index dict, so "
        "`hybrid_bm25_k30` pays the BM25 build cost once and `k60`/`k100` are cache hits."
    )
    lines.append(
        "* `chunk_recall@k` is None for cases without `expected_terms` / "
        "`expected_doc_ids` (e.g. abstention) — those are dropped pairwise to "
        "preserve case alignment between variants."
    )
    lines.append(
        "* Seeds drive only the bootstrap RNG; retrieval itself is deterministic "
        "for the same query+index+backend+rrf_k (dense + BM25 both)."
    )
    lines.append(
        "* Category bucketing uses `hardcase_categories` (semantic difficulty tags). "
        "Multi-tag cases appear in multiple buckets, so per-category counts overlap "
        "and per-category paired CIs share cases."
    )
    lines.append(
        f"* `{baseline}` is the delta baseline because ADR 0010's accept rationale "
        "for `hybrid` framed the question as \"is hybrid actually better than dense?\". "
        "Deltas above 0 favor the hybrid variant; below 0 favor dense."
    )
    lines.append(
        "* m3 (FlagEmbedding 3-channel RRF) is **out of scope** for Phase 3 — it "
        "requires a separate index build (`build_m3_index`), so deferring to "
        "Phase 3.5 keeps Phase 3 measurement narrow (mode ↔ index decoupled)."
    )
    lines.append(
        "* k=10 / k=200 are **out of scope** for Phase 3 — k∈{30,60,100} brackets "
        "ADR 0010's k=60 default without inflating the variant count. Tighter/looser "
        "k swings can be added in a follow-up if k=30 vs k=100 shows a clean gradient."
    )
    if config.get("reaggregate_source"):
        lines.append(
            "* This report was regenerated via `--reaggregate` from "
            f"`{config['reaggregate_source']}` — categorization re-derived from "
            "`hardcase_categories`; retrieval scores in `raw_results.json` are "
            "unchanged byte-for-byte modulo the injected `categories` field."
        )

    report_path = out_dir / "REPORT.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[report] wrote {report_path} ({len(lines)} lines)", flush=True)


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
    index_dir = Path(args.index_dir)
    return [
        VariantSpec(name="dense", retrieval_backend="dense", rrf_k=None, index_dir=index_dir),
        VariantSpec(name="hybrid_bm25_k30", retrieval_backend="hybrid", rrf_k=30, index_dir=index_dir),
        VariantSpec(name="hybrid_bm25_k60", retrieval_backend="hybrid", rrf_k=60, index_dir=index_dir),
        VariantSpec(name="hybrid_bm25_k100", retrieval_backend="hybrid", rrf_k=100, index_dir=index_dir),
    ]


def _spec_meta(
    spec: VariantSpec, payload: dict[str, Any]
) -> dict[str, Any]:
    return {
        "name": spec.name,
        "retrieval_backend": spec.retrieval_backend,
        "rrf_k": spec.rrf_k,
        "index_dir": str(spec.index_dir),
        "num_documents": len(payload.get("documents", [])),
        "num_chunks": len(payload.get("chunks", [])),
    }


def _run_reaggregate(
    args: argparse.Namespace,
    out_dir: Path,
    seeds: list[int],
    ks: list[int],
) -> int:
    """Re-derive ``row['categories']`` from ``hardcase_categories`` and
    regenerate deltas + REPORT.md without re-running retrieval. Useful
    when the categorization schema changes between runs but raw scores
    are still trustworthy.
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

    for variant_name, m in measurements.items():
        rows = m.get("per_case", []) or []
        untagged = 0
        for row in rows:
            case = cases_by_qid.get(str(row.get("qid")))
            tags = categories_from_case(case or {})
            row["categories"] = tags
            if tags == ["uncategorized"]:
                untagged += 1
        print(
            f"[reaggregate] {variant_name}: {len(rows)} rows, {untagged} uncategorized",
            flush=True,
        )

    specs_path = raw_path.parent / "mode_specs.json"
    if not specs_path.exists():
        print(
            f"[ERROR] mode_specs.json not found beside raw: {specs_path}",
            file=sys.stderr,
        )
        return 2
    spec_metas = json.loads(specs_path.read_text(encoding="utf-8"))
    (out_dir / "mode_specs.json").write_text(
        json.dumps(spec_metas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "raw_results.json").write_text(
        json.dumps(measurements, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("[phase] deltas (reaggregate)", flush=True)
    metrics_to_delta = [f"chunk_recall@{k}" for k in ks] + ["mrr", "ndcg@10"]
    deltas: dict[str, dict[str, dict[str, dict[str, Any] | None]]] = {}
    baseline = args.baseline
    baseline_rows = measurements[baseline]["per_case"]
    for variant_name in measurements:
        if variant_name == baseline:
            continue
        deltas[variant_name] = {
            metric: compute_deltas(
                baseline_rows, measurements[variant_name]["per_case"], metric, seeds
            )
            for metric in metrics_to_delta
        }
    (out_dir / "deltas.json").write_text(
        json.dumps(deltas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    git_commit, git_dirty = _git_state()
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        + "-phase3-mode-reaggregate"
    )
    baseline_spec = next(
        (s for s in spec_metas if s.get("name") == baseline),
        {"index_dir": "unknown"},
    )
    config = {
        "run_id": run_id,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "index_dir": baseline_spec.get("index_dir", "unknown"),
        "eval_config": args.eval_config,
        "seeds": seeds,
        "top_k": args.top_k,
        "ks": ks,
        "num_cases": len(baseline_rows),
        "baseline": baseline,
        "reaggregate_source": str(raw_path),
    }
    print("[phase] render (reaggregate)", flush=True)
    render_report(out_dir, spec_metas, measurements, deltas, config)
    print(f"[done] output_dir={out_dir}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--index_dir",
        default="data/index/real100",
        help="Shared index for all 4 variants (default: data/index/real100).",
    )
    parser.add_argument("--eval_config", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument(
        "--reaggregate",
        default=None,
        help=(
            "Path to an existing raw_results.json. Skips measurement, "
            "re-derives row['categories'] from hardcase_categories in --eval_config, "
            "and regenerates deltas + REPORT.md into --output_dir. "
            "Companion mode_specs.json must sit beside raw_results.json."
        ),
    )
    parser.add_argument("--seeds", default="17,23,29")
    parser.add_argument("--top_k", type=int, default=20)
    parser.add_argument("--ks", default="5,10")
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument(
        "--cases_subset_n",
        type=int,
        default=None,
        help="Truncate to first N cases (for pre-flight dry-runs).",
    )
    parser.add_argument(
        "--baseline",
        default="dense",
        choices=["dense", "hybrid_bm25_k30", "hybrid_bm25_k60", "hybrid_bm25_k100"],
        help="Baseline variant for paired CI deltas (default: dense).",
    )
    args = parser.parse_args(argv)

    seeds = [int(x) for x in args.seeds.split(",")]
    ks = [int(x) for x in args.ks.split(",")]
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.reaggregate:
        return _run_reaggregate(args, out_dir, seeds, ks)

    specs = _resolve_specs(args)

    print("[phase] measure", flush=True)
    cfg = yaml.safe_load(Path(args.eval_config).read_text(encoding="utf-8"))
    cases = cfg.get("cases", []) or []
    if args.cases_subset_n is not None:
        cases = cases[: args.cases_subset_n]
        print(f"[measure] truncated to first {len(cases)} cases", flush=True)
    print(f"[measure] {len(cases)} cases", flush=True)

    # All variants share the same index; load once and reuse so the
    # BM25 cache populated by the first hybrid variant is hit by the
    # remaining ones.
    print(f"[measure] loading shared index from {args.index_dir}", flush=True)
    index = load_index(Path(args.index_dir))
    spec_metas = [_spec_meta(spec, index) for spec in specs]
    (out_dir / "mode_specs.json").write_text(
        json.dumps(spec_metas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    measurements: dict[str, dict[str, Any]] = {}
    for spec in specs:
        measurements[spec.name] = measure_variant(
            spec, index, cases, args.top_k, ks, args.warmup
        )

    raw_path = out_dir / "raw_results.json"
    raw_path.write_text(
        json.dumps(measurements, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[measure] wrote {raw_path}", flush=True)

    print("[phase] deltas", flush=True)
    metrics_to_delta = [f"chunk_recall@{k}" for k in ks] + ["mrr", "ndcg@10"]
    deltas: dict[str, dict[str, dict[str, dict[str, Any] | None]]] = {}
    baseline = args.baseline
    baseline_rows = measurements[baseline]["per_case"]
    for spec in specs:
        if spec.name == baseline:
            continue
        deltas[spec.name] = {
            metric: compute_deltas(
                baseline_rows, measurements[spec.name]["per_case"], metric, seeds
            )
            for metric in metrics_to_delta
        }
    (out_dir / "deltas.json").write_text(
        json.dumps(deltas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    git_commit, git_dirty = _git_state()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M") + "-phase3-mode"
    config = {
        "run_id": run_id,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "index_dir": str(specs[0].index_dir),
        "eval_config": args.eval_config,
        "seeds": seeds,
        "top_k": args.top_k,
        "ks": ks,
        "num_cases": len(cases),
        "baseline": baseline,
    }

    print("[phase] render", flush=True)
    render_report(out_dir, spec_metas, measurements, deltas, config)
    print(f"[done] output_dir={out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
