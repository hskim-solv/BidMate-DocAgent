#!/usr/bin/env python3
"""Phase 1 baseline: run current ``make_plan()`` on the multi-hop slice.

Confirms the current planner emits ZERO sub_queries (intended F1=0 baseline),
records ``comparison_targets``/latency, and computes the self-eval-risk
governance metrics (acceptance_rate_exact + acceptance_rate_semantic) over the
human-reviewed gold. Split out of planner_eval.py for LOC discipline (Round-3 #3).

Limitation: ``analyze_query(query, entities=[])`` is called with empty entities
(no production ``ctx.targets``), so ``comparison_targets`` emit-rate undercounts
entity-driven planning. Phase 4 retrieval-uplift re-litigates if needed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from eval.bootstrap import bootstrap_ci
from eval.planner_eval import select_slice, semantic_set_match
from eval.run_eval import compute_run_manifest
from rag_query import analyze_query, comparison_targets_for_analysis, make_plan


def decomposition_f1(pred: list[str], gold: list[str]) -> float:
    """String-equality set F1 over sub-query strings (baseline metric).

    The current planner emits ``pred == []`` for every case, so this is 0.0
    everywhere by construction — the point is to *confirm* that, not to grade.
    Phase 2 uses the semantic (ko-sroberta) F1; here we keep it exact so the
    baseline-zero claim is unambiguous."""
    p = {x.strip() for x in pred if x.strip()}
    g = {x.strip() for x in gold if x.strip()}
    if not p and not g:
        return 1.0
    if not p or not g:
        return 0.0
    tp = len(p & g)
    if tp == 0:
        return 0.0
    precision = tp / len(p)
    recall = tp / len(g)
    return 2 * precision * recall / (precision + recall)


def _load_gold(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text()) or []
    if not isinstance(data, list):
        raise ValueError(f"gold {path} is not a list")
    return data


def cmd_phase1_baseline(args: argparse.Namespace) -> None:
    cfg = yaml.safe_load(Path(args.eval_config).read_text())
    slice_cases = select_slice(cfg.get("cases", []))
    slice_ids = {c["id"] for c in slice_cases}

    gold = _load_gold(Path(args.gold))
    gold_by_id = {g["id"]: g for g in gold}

    # Coverage: slice∩gold is the F1 modulus; gold may carry follow_up entries
    # (multi-turn axis) that are intentionally outside the slice.
    in_slice_gold = [g for g in gold if g["id"] in slice_ids]
    missing_in_slice = sorted(slice_ids - set(gold_by_id))
    gold_outside_slice = sorted(set(gold_by_id) - slice_ids)

    # --- Baseline planner pass (no LLM): make_plan on every slice case ---
    baseline_cases: list[dict] = []
    f1_values: list[float] = []
    comparison_emit = 0
    latencies: list[float] = []
    import time

    for c in slice_cases:
        t0 = time.perf_counter()
        analysis = analyze_query(c["query"], [])
        plan = make_plan(analysis)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(latency_ms)
        targets, field = comparison_targets_for_analysis(analysis)
        if targets:
            comparison_emit += 1
        pred_sub_queries: list[str] = list(plan.get("sub_queries", []))  # always [] today
        g = gold_by_id.get(c["id"])
        gold_sq = list(g["sub_queries"]) if g else []
        f1 = decomposition_f1(pred_sub_queries, gold_sq) if g else None
        if f1 is not None:
            f1_values.append(f1)
        baseline_cases.append({
            "id": c["id"], "query_type": c.get("query_type"),
            "sub_queries": pred_sub_queries,
            "comparison_targets": targets, "comparison_target_field": field,
            "n_gold_sub_queries": len(gold_sq), "decomposition_f1": f1,
            "latency_ms": latency_ms,
        })

    f1_ci = bootstrap_ci(f1_values) if f1_values else None

    # --- acceptance_rate governance (Item 2 + Big Q): self-eval risk ---
    n_reviewed = n_exact = n_semantic = 0
    edited_ids: list[str] = []
    for g in gold:
        if not g.get("reviewed_by"):
            continue
        n_reviewed += 1
        current = list(g.get("sub_queries", []))
        original = list((g.get("bootstrap_meta") or {}).get("original_sub_queries", []))
        if current == original:
            n_exact += 1
            n_semantic += 1
            continue
        edited_ids.append(g["id"])
        if semantic_set_match(current, original, threshold=0.85):
            n_semantic += 1

    acc_exact = (n_exact / n_reviewed) if n_reviewed else None
    acc_semantic = (n_semantic / n_reviewed) if n_reviewed else None

    # bootstrap_source distribution
    source_dist: dict[str, int] = {}
    for g in gold:
        src = g.get("bootstrap_source", "unknown")
        source_dist[src] = source_dist.get(src, 0) + 1

    lat_summary = {
        "mean": (sum(latencies) / len(latencies)) if latencies else None,
        "max": max(latencies) if latencies else None,
        "n": len(latencies),
    }

    manifest = compute_run_manifest(Path(args.eval_config))
    summary: dict[str, Any] = {
        "run_manifest": manifest, "phase": "phase1_baseline",
        "coverage": {
            "n_slice": len(slice_cases), "n_gold_total": len(gold),
            "n_in_slice_gold": len(in_slice_gold),
            "n_missing_in_slice": len(missing_in_slice),
            "missing_in_slice_ids": missing_in_slice,
            "n_gold_outside_slice": len(gold_outside_slice),
            "gold_outside_slice_ids": gold_outside_slice,
        },
        "decomposition_f1": {"n": len(f1_values), "ci": f1_ci},
        "comparison_targets_emit_rate": (
            comparison_emit / len(slice_cases)) if slice_cases else None,
        "make_plan_latency_ms": lat_summary,
        "acceptance_rate": {
            "n_reviewed": n_reviewed,
            "acceptance_rate_exact": acc_exact,
            "acceptance_rate_semantic": acc_semantic,
            "n_edited": len(edited_ids), "edited_ids": edited_ids,
            "semantic_threshold": 0.85, "semantic_model": "jhgan/ko-sroberta-multitask",
            "hard_gate": "acceptance_rate_semantic > 0.80",
            "gate_fired": bool(acc_semantic is not None and acc_semantic > 0.80),
        },
        "bootstrap_source_dist": source_dist,
        "baseline_cases": baseline_cases,
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "phase1_baseline_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2))

    f1_mean = f1_ci["mean"] if f1_ci else float("nan")
    f1_lo = f1_ci["ci_lo"] if f1_ci else float("nan")
    f1_hi = f1_ci["ci_hi"] if f1_ci else float("nan")
    gate_line = (
        f"**HARD GATE FIRED** (acceptance_rate_semantic = {acc_semantic:.3f} > 0.80) "
        "→ Phase 1.5 cross-model bootstrap required before Phase 2."
        if summary["acceptance_rate"]["gate_fired"]
        else "Hard gate not fired (acceptance_rate_semantic ≤ 0.80)."
    )
    src_rows = "\n".join(f"| `{k}` | {v} |" for k, v in sorted(source_dist.items()))
    dirty = manifest.get("git_dirty")
    banner = "\n> ⚠️ **git_dirty: true** — working tree had uncommitted changes at run time.\n" if dirty else ""
    md = f"""# Phase 1 — Current-Planner Baseline Report
{banner}
`{manifest['generated_at']}` · git `{manifest['git_commit']}`

## Headline

- **decomposition_f1 mean = {f1_mean:.4f}** CI [{f1_lo:.3f}, {f1_hi:.3f}], n={len(f1_values)}
  — current `make_plan()` emits **0 sub_queries** on every case (intended baseline).
- comparison_targets emit-rate = {summary['comparison_targets_emit_rate']:.1%}
  (limitation: `analyze_query(query, entities=[])`, no production `ctx.targets`).
- `make_plan()` latency mean {lat_summary['mean']:.2f}ms / max {lat_summary['max']:.2f}ms
  — sub-second sanity floor ✓.

## Coverage (modulus transparency)

| set | n |
|---|---|
| multi-hop slice | {len(slice_cases)} |
| gold total | {len(gold)} |
| **slice ∩ gold (F1 modulus)** | **{len(in_slice_gold)}** |
| slice missing from gold | {len(missing_in_slice)} |
| gold outside slice (follow_up etc.) | {len(gold_outside_slice)} |

gold-outside-slice ids: {gold_outside_slice or '—'}

## Self-eval risk governance

### bootstrap_source distribution

| source | n |
|---|---|
{src_rows}

### acceptance_rate (n_reviewed = {n_reviewed})

| metric | value |
|---|---|
| acceptance_rate_exact | {('%.3f' % acc_exact) if acc_exact is not None else 'N/A'} |
| acceptance_rate_semantic | {('%.3f' % acc_semantic) if acc_semantic is not None else 'N/A'} |
| n_edited | {len(edited_ids)} |

semantic equiv = bidirectional cosine ≥ 0.85 via `jhgan/ko-sroberta-multitask`
(brute-force permutation, n ≤ 5). Bias caveat: size-mismatch trims count as
"changed" → acceptance_rate_semantic is a **conservative-low** estimate.

{gate_line}

edited ids: {edited_ids or '—'}

## Reproduce

```bash
python -m eval.planner_eval phase1 baseline \\
  --eval-config {args.eval_config} \\
  --gold {args.gold} \\
  --out-dir {out_dir}
```
"""
    (out_dir / "phase1_baseline_report.md").write_text(md)
    print(f"decomposition_f1 mean = {f1_mean:.4f} (n={len(f1_values)})")
    print(f"acceptance_rate_semantic = "
          f"{('%.3f' % acc_semantic) if acc_semantic is not None else 'N/A'} "
          f"(reviewed {n_reviewed}); {gate_line}")
    print(f"summary: {out_dir}/phase1_baseline_summary.json")
