#!/usr/bin/env python3
"""Phase 2: V0-V4 decomposition ablation (3-seed, 2-winner).

Runs ``decompose_query()`` (rag_query.py) in 5 variants over the multi-hop
slice ∩ gold, 3 seeds each, and ranks by semantic decomposition F1 (ko-sroberta,
cosine ≥ 0.85). Two winners: F1-best and cost-adjusted (f1_per_dollar) best —
each must clear a paired-delta CI_lo > 0 vs V0 at ALL sweep thresholds
{0.80, 0.85, 0.90}, else NO WINNER.

F1 framing (load-bearing caveat — do NOT over-read):
  The gold was bootstrapped by claude-sonnet-4-6, so a Claude variant scoring
  high F1 is partly self-agreement, NOT proof of correctness. F1 here is a
  RANKING signal between variants, not a trustworthy absolute. Phase 1.5 found
  MEDIUM cross-model disagreement (26.9%) → gold confidence is medium. The real
  ship validation is Phase 4 retrieval uplift, not this F1.

reject_unreviewed=True by default (Item 4): reviewed_by==null gold is excluded
from scoring and only counted (``--allow-unreviewed`` is debug-only).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from eval.bootstrap import bootstrap_ci
from eval.planner_eval import SEMANTIC_MATCH_MODEL, estimate_cost_usd, select_slice
from eval.run_eval import compute_run_manifest
from rag_query import decompose_query

THRESHOLDS = (0.80, 0.85, 0.90)  # sweep; primary = 0.85 (ko-sroberta clean zone)
# Canonical corrected Phase 1.5 run (ko-sroberta), for MEDIUM-tier caveat wiring.
DEFAULT_PHASE1_5_SUMMARY = (
    "reports/planner/20260520T143552Z-phase1_5-cross-model-koemb/"
    "phase1_5_cross_model_summary.json"
)


def load_reviewed_gold(path: Path, *, allow_unreviewed: bool = False) -> tuple[dict, int]:
    """Return (id→gold, n_excluded_unreviewed). Default rejects reviewed_by==null."""
    data = yaml.safe_load(path.read_text()) or []
    kept: dict[str, dict] = {}
    excluded = 0
    for g in data:
        if not allow_unreviewed and not g.get("reviewed_by"):
            excluded += 1
            continue
        kept[g["id"]] = g
    return kept, excluded


_EMB_CACHE: dict[str, Any] = {}


def _embed_cached(texts: list[str], model_name: str) -> dict[str, Any]:
    from rag_embedding import embed_texts

    missing = [t for t in texts if t not in _EMB_CACHE]
    if missing:
        vecs = embed_texts(missing, backend="sentence-transformers",
                           model_name=model_name).vectors
        for t, v in zip(missing, vecs):
            _EMB_CACHE[t] = v
    return {t: _EMB_CACHE[t] for t in texts}


def _cos(a: Any, b: Any) -> float:
    import numpy as np
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def f1_coverage_spuriousness(
    pred: list[str], gold: list[str], *, threshold: float, model_name: str,
) -> dict[str, float]:
    """Semantic set F1/coverage/spuriousness via ko-sroberta cosine ≥ threshold.

    A pred is matched if its max cosine to any gold ≥ threshold (and vice versa).
    precision = matched_pred/|pred|, recall = matched_gold/|gold|."""
    pred = [p.strip() for p in pred if p.strip()]
    gold = [g.strip() for g in gold if g.strip()]
    if not pred and not gold:
        return {"f1": 1.0, "coverage": 1.0, "spuriousness": 0.0}
    if not pred:
        return {"f1": 0.0, "coverage": 0.0, "spuriousness": 0.0}
    if not gold:
        return {"f1": 0.0, "coverage": 0.0, "spuriousness": 1.0}
    emb = _embed_cached(list({*pred, *gold}), model_name)
    matched_pred = sum(
        1 for p in pred if max(_cos(emb[p], emb[g]) for g in gold) >= threshold)
    matched_gold = sum(
        1 for g in gold if max(_cos(emb[g], emb[p]) for p in pred) >= threshold)
    precision = matched_pred / len(pred)
    recall = matched_gold / len(gold)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    spuriousness = (len(pred) - matched_pred) / max(1, len(pred))
    return {"f1": f1, "coverage": recall, "spuriousness": spuriousness}


def _per_case_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _load_phase1_5(path: str | None) -> dict | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[1] / p
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def cmd_phase2(args: argparse.Namespace) -> None:
    cfg = yaml.safe_load(Path(args.eval_config).read_text())
    slice_cases = select_slice(cfg.get("cases", []))
    gold_by_id, n_excluded = load_reviewed_gold(
        Path(args.gold), allow_unreviewed=args.allow_unreviewed)

    cases = [c for c in slice_cases if c["id"] in gold_by_id]
    # F1 aggregate over len(gold) ≥ 2 only; len==1 reported separately (Phase 3 router signal).
    cases_ge2 = [c for c in cases if len(gold_by_id[c["id"]]["sub_queries"]) >= 2]
    cases_len1 = [c for c in cases if len(gold_by_id[c["id"]]["sub_queries"]) == 1]

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    prompts_path = Path(args.prompts)
    model_name = SEMANTIC_MATCH_MODEL

    n_llm_variants = sum(1 for v in variants if v != "v0")
    est_calls = n_llm_variants * len(seeds) * len(cases)
    est_cost = est_calls * estimate_cost_usd(400, 200, args.model)
    print(f"phase2: {len(variants)} variants × {len(seeds)} seeds × {len(cases)} cases")
    print(f"  ≈ {est_calls} LLM calls, est ~${est_cost:.2f} (V0 free)")
    if est_calls > args.max_calls:
        raise SystemExit(f"--max-calls {args.max_calls} guardrail: est {est_calls}")
    if not args.yes:
        print("proceed? [y/N] ", end="", flush=True)
        if sys.stdin.readline().strip().lower() != "y":
            sys.exit(1)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # raw[variant][case_id][seed] = {pred, f1@thr, cov, spur, cost, latency, parse_error}
    raw: dict[str, dict[str, dict[int, dict]]] = {v: {} for v in variants}
    total_calls = 0
    # Per-variant checkpointing (recovery hardening — repeated harness/sleep
    # kills on the ~30min run). After each variant's full loop, dump raw[v] to
    # out_dir/_ckpt_{v}.json; on restart, completed variants are loaded and
    # skipped. JSON keys are str so seed/threshold are restored on load.
    def _ckpt(v: str) -> Path:
        return out_dir / f"_ckpt_{v}.json"

    def _save_ckpt(v: str) -> None:
        ser = {gid: {str(s): cell for s, cell in seedmap.items()}
               for gid, seedmap in raw[v].items()}
        _ckpt(v).write_text(json.dumps(ser, ensure_ascii=False))

    def _load_ckpt(v: str) -> bool:
        p = _ckpt(v)
        if not p.exists():
            return False
        ser = json.loads(p.read_text())
        raw[v] = {gid: {int(s): {**cell, "metrics": {float(t): m for t, m in cell["metrics"].items()}}
                        for s, cell in seedmap.items()}
                  for gid, seedmap in ser.items()}
        return len(raw[v]) == len(cases)

    for v in variants:
        if _load_ckpt(v):
            print(f"  {v}: resumed from checkpoint ({len(raw[v])} cases)")
            continue
        for c in cases:
            gid = c["id"]
            gold_sq = list(gold_by_id[gid]["sub_queries"])
            raw[v][gid] = {}
            for seed in seeds:
                r = decompose_query(c["query"], variant=v, seed=seed,
                                    prompt_profile_path=prompts_path,
                                    model=args.model, max_tokens=args.max_tokens)
                if v != "v0":
                    total_calls += 1
                pred = list(r.get("sub_queries", []))
                metrics = {thr: f1_coverage_spuriousness(
                    pred, gold_sq, threshold=thr, model_name=model_name)
                    for thr in THRESHOLDS}
                cost = r.get("cost_usd")
                if cost is None:
                    cost = estimate_cost_usd(r.get("tokens_in") or 0,
                                             r.get("tokens_out") or 0, args.model)
                raw[v][gid][seed] = {
                    "pred": pred, "metrics": metrics, "cost_usd": cost,
                    "latency_ms": r.get("latency_ms"),
                    "parse_error": r.get("parse_error"),
                }
            print(f"  {v} {gid}: "
                  f"f1@0.85 seed-mean "
                  f"{_per_case_mean([raw[v][gid][s]['metrics'][0.85]['f1'] for s in seeds]):.3f}")
        _save_ckpt(v)

    # ---- aggregate ----
    def case_seedmean_f1(v: str, gid: str, thr: float) -> float:
        return _per_case_mean([raw[v][gid][s]["metrics"][thr]["f1"] for s in seeds])

    agg: dict[str, Any] = {}
    for v in variants:
        # per-case seed-mean f1 at primary threshold, over len≥2 cases
        per_case_f1 = [case_seedmean_f1(v, c["id"], 0.85) for c in cases_ge2]
        ci = bootstrap_ci(per_case_f1) if per_case_f1 else None
        costs = [raw[v][c["id"]][s]["cost_usd"] for c in cases for s in seeds]
        lats = [raw[v][c["id"]][s]["latency_ms"] for c in cases for s in seeds
                if raw[v][c["id"]][s]["latency_ms"] is not None]
        n_calls = len(cases) * len(seeds) if v != "v0" else 0
        n_parse_err = sum(1 for c in cases for s in seeds
                          if raw[v][c["id"]][s]["parse_error"])
        mean_cost_per_call = (sum(costs) / len(costs)) if costs else 0.0
        mean_f1 = ci["mean"] if ci else 0.0
        f1_per_dollar = (mean_f1 / mean_cost_per_call) if mean_cost_per_call > 0 else None
        cov = _per_case_mean([_per_case_mean(
            [raw[v][c["id"]][s]["metrics"][0.85]["coverage"] for s in seeds])
            for c in cases_ge2])
        spur = _per_case_mean([_per_case_mean(
            [raw[v][c["id"]][s]["metrics"][0.85]["spuriousness"] for s in seeds])
            for c in cases_ge2])
        agg[v] = {
            "f1_ci": ci, "coverage": cov, "spuriousness": spur,
            "mean_cost_per_call": mean_cost_per_call, "total_cost": sum(costs),
            "f1_per_dollar": f1_per_dollar,
            "latency_ms_mean": (sum(lats) / len(lats)) if lats else None,
            "n_calls": n_calls, "parse_error_rate": (n_parse_err / n_calls) if n_calls else 0.0,
        }

    # paired delta vs v0 at every sweep threshold
    def passes_all_thresholds(v: str) -> bool:
        if v == "v0":
            return False
        for thr in THRESHOLDS:
            delta = [case_seedmean_f1(v, c["id"], thr) - case_seedmean_f1("v0", c["id"], thr)
                     for c in cases_ge2]
            ci = bootstrap_ci(delta)
            if ci is None or ci["ci_lo"] <= 0:
                return False
        return True

    paired = {}
    for v in variants:
        if v == "v0":
            continue
        per_thr = {}
        for thr in THRESHOLDS:
            delta = [case_seedmean_f1(v, c["id"], thr) - case_seedmean_f1("v0", c["id"], thr)
                     for c in cases_ge2]
            per_thr[str(thr)] = bootstrap_ci(delta)
        paired[v] = {"deltas": per_thr, "passes_all_thresholds": passes_all_thresholds(v)}

    qualified = [v for v in variants if v != "v0" and paired[v]["passes_all_thresholds"]]
    winner_f1 = max(qualified, key=lambda v: agg[v]["f1_ci"]["mean"]) if qualified else None
    cost_qual = [v for v in qualified if agg[v]["f1_per_dollar"] is not None]
    winner_cost = max(cost_qual, key=lambda v: agg[v]["f1_per_dollar"]) if cost_qual else None

    phase1_5 = _load_phase1_5(args.phase1_5_summary)
    manifest = compute_run_manifest(Path(args.eval_config))
    summary = {
        "run_manifest": manifest, "phase": "phase2",
        "model": args.model, "variants": variants, "seeds": seeds,
        "thresholds": list(THRESHOLDS), "primary_threshold": 0.85,
        "n_cases": len(cases), "n_cases_ge2": len(cases_ge2),
        "n_cases_len1": len(cases_len1), "len1_ids": [c["id"] for c in cases_len1],
        "n_excluded_unreviewed": n_excluded,
        "aggregate": agg, "paired_delta_vs_v0": paired,
        "winner_f1": winner_f1, "winner_cost": winner_cost,
        "no_winner": not qualified,
        "phase1_5_tier": (phase1_5 or {}).get("tier"),
        "phase1_5_disagreement_rate": (phase1_5 or {}).get("disagreement_rate"),
        "phase1_5_structural_ids": (phase1_5 or {}).get("disagreed_case_ids", []),
        "total_llm_calls": total_calls,
    }
    (out_dir / "phase2_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=lambda _: None))
    _write_report(out_dir, summary, args)

    print(f"\nwinner_f1 = {winner_f1}  winner_cost = {winner_cost}  "
          f"no_winner = {not qualified}")
    print(f"summary: {out_dir}/phase2_summary.json")


def _write_report(out_dir: Path, s: dict, args: argparse.Namespace) -> None:
    m = s["run_manifest"]
    agg = s["aggregate"]
    dirty = m.get("git_dirty")
    banner = "\n> ⚠️ **git_dirty: true**\n" if dirty else ""

    def fmt_ci(ci):
        return f"{ci['mean']:.3f} [{ci['ci_lo']:.3f}, {ci['ci_hi']:.3f}]" if ci else "N/A"

    f1_rows = "\n".join(
        f"| {v} | {fmt_ci(agg[v]['f1_ci'])} | {agg[v]['coverage']:.3f} | "
        f"{agg[v]['spuriousness']:.3f} | {agg[v]['parse_error_rate']:.1%} |"
        for v in s["variants"])
    cost_rows = "\n".join(
        f"| {v} | ${agg[v]['mean_cost_per_call']:.5f} | ${agg[v]['total_cost']:.3f} | "
        f"{('%.1f' % agg[v]['f1_per_dollar']) if agg[v]['f1_per_dollar'] is not None else '— (free)'} | "
        f"{('%.1f' % agg[v]['latency_ms_mean']) if agg[v]['latency_ms_mean'] is not None else 'N/A'} |"
        for v in s["variants"])
    delta_rows = ""
    for v in s["variants"]:
        if v == "v0":
            continue
        pr = s["paired_delta_vs_v0"][v]["deltas"]
        cells = " | ".join(
            f"{pr[str(t)]['ci_lo']:+.3f}/{pr[str(t)]['ci_hi']:+.3f}" if pr[str(t)] else "N/A"
            for t in s["thresholds"])
        ok = "✓" if s["paired_delta_vs_v0"][v]["passes_all_thresholds"] else "✗"
        delta_rows += f"| {v} | {cells} | {ok} |\n"

    tier = s.get("phase1_5_tier")
    dr = s.get("phase1_5_disagreement_rate")
    variance_section = ""
    if tier == "medium":
        struct = s.get("phase1_5_structural_ids", [])[:16]
        variance_section = f"""
## Cross-model variance (MEDIUM tier — Phase 1.5)

Phase 1.5 cross-model disagreement = **{dr:.1%}** (MEDIUM, 15-30%). Per the
fallback decision tree, Phase 2 conclusions carry **medium gold confidence**.
Winner spot-check priority = the structural-disagreement cases:

{struct or '—'}

These are cases where Claude (gold author) and GPT chose different decomposition
*depth* — the winner variant's output on them deserves manual eyeball before any
ship decision.
"""

    no_winner_section = ""
    if s["no_winner"]:
        no_winner_section = """
## NO WINNER (Item 3 fallback)

No variant cleared paired-delta CI_lo > 0 vs V0 at ALL sweep thresholds.
Path D conclusion candidate: prompt-only decomposition is insufficient; Phase 3
runs `should_decompose` router only, Phase 4 reduces to V0 vs V_oracle.
"""

    md = f"""# Phase 2 — Decomposition Variants Ablation
{banner}
`{m['generated_at']}` · git `{m['git_commit']}` · model {s['model']}

## How to read this (load-bearing caveat)

F1 here is a **ranking signal between variants, NOT a trustworthy absolute**.
The gold was bootstrapped by claude-sonnet-4-6, so a Claude variant scoring high
F1 is partly **self-agreement inflation**, not proof of correctness — a
cross-model scorer would read lower. Phase 1.5 found {('%.1f%%' % (dr*100)) if dr else 'medium'}
cross-model disagreement. **The real ship validation is Phase 4 retrieval uplift.**
Do not over-read these numbers.

## Headline

- **winner_f1 = `{s['winner_f1']}`** · **winner_cost = `{s['winner_cost']}`**
  {'(NO WINNER)' if s['no_winner'] else ''}
- modulus: {s['n_cases']} cases (F1 over len(gold)≥2 = **{s['n_cases_ge2']}**;
  len==1 = {s['n_cases_len1']} {s['len1_ids'] or ''})
- excluded unreviewed gold: {s['n_excluded_unreviewed']}
- seeds {s['seeds']}; V0/V3 deterministic, V1/V2/V4 temp=0.7 (Anthropic has no
  seed param — variance is temperature-driven).

## F1 / coverage / spuriousness (primary threshold 0.85)

| variant | F1 (95% CI) | coverage | spuriousness | parse-err |
|---|---|---|---|---|
{f1_rows}

## Cost / latency

| variant | $/call | total $ | f1/$ | latency ms |
|---|---|---|---|---|
{cost_rows}

## Paired delta vs V0 (CI_lo/CI_hi per threshold)

| variant | {' | '.join(str(t) for t in s['thresholds'])} | passes all |
|---|{'---|' * len(s['thresholds'])}---|
{delta_rows}
{variance_section}{no_winner_section}
## Notes

- V3 (structured tool-use) parse behavior is model-dependent; parse-err column
  flags Korean-query degradation if any.
- semantic match: cosine ≥ threshold via `{SEMANTIC_MATCH_MODEL}`.

## Reproduce

```bash
python -m eval.planner_eval phase2 \\
  --eval-config {args.eval_config} --gold {args.gold} \\
  --variants {args.variants} --seeds {args.seeds} \\
  --model {args.model} --prompts {args.prompts} --out-dir {out_dir}
```
"""
    (out_dir / "phase2_report.md").write_text(md)
