#!/usr/bin/env python3
"""Phase 1.5: cross-model bootstrap (GPT vs Claude) — hard-gate escalation.

Phase 1 acceptance_rate_semantic = 89-90% > 80% threshold fired the Big-Q (가)
escalation: re-bootstrap the same slice with a *different* model (gpt-5.5) and
measure disagreement vs the Claude bootstrap. The disagreement_rate quantifies
gold confidence; single-model bootstrap is a self-agreement-inflation risk.

Compares against ``gold[id].bootstrap_meta.original_sub_queries`` (Claude output
*before* human review), so this measures model↔model divergence, not gold↔human.

Critical: ``semantic_set_match`` uses ko-sroberta (NOT hashing). A prior run hit
a false 92.5% because EMBEDDING_BACKEND was unset → bag-of-words fallback inverted
SAME/DIFF similarity. ``--recompute-from`` reuses cached GPT outputs and re-scores
agreement only (cost-0) — the path that corrected 92.5% → 26.9% medium tier.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from eval.bootstrap import bootstrap_ci
from eval.planner_eval import (
    BOOTSTRAP_PROMPT,
    estimate_cost_usd,
    parse_sub_queries,
    select_slice,
    semantic_set_match,
)
from eval.run_eval import compute_run_manifest

# Action templates per tier (Round-4 #3 fallback decision tree).
_FALLBACK = {
    "high": (
        "Phase 2 may start immediately. Report the single-model bootstrap "
        "limitation as resolved (cross-model agreement ≥ 85%)."
    ),
    "medium": (
        "Phase 2 proceeds CONDITIONALLY: (a) every Phase 2-4 report carries a "
        "cross-model variance section citing this run; (b) disagreed_case_ids "
        "(esp. structural-mismatch) become winner spot-check priorities; "
        "(c) Phase 2-4 conclusions are weighted down as 'medium gold confidence'."
    ),
    "low": (
        "Phase 2 BLOCKED. Run multi-LLM consensus revision (Claude+GPT side-by-side "
        "→ user final-final review of disagreed cases) OR explicitly opt out and "
        "demote to medium-tier handling with all results weakened."
    ),
}


def classify_tier(rate: float) -> tuple[str, str]:
    """Map disagreement_rate → (tier, fallback action). 3-tier (Round-4 #3)."""
    if rate <= 0.15:
        return "high", _FALLBACK["high"]
    if rate < 0.30:
        return "medium", _FALLBACK["medium"]
    return "low", _FALLBACK["low"]


def _jaccard_strict(a: list[str], b: list[str]) -> float:
    """String-equality Jaccard (secondary, granular signal)."""
    sa = {x.strip() for x in a if x.strip()}
    sb = {x.strip() for x in b if x.strip()}
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def call_openai_bootstrap(query: str, *, model: str, max_tokens: int) -> dict[str, Any]:
    """Single OpenAI bootstrap call. Never raises.

    gpt-5 family requires ``max_completion_tokens`` (``max_tokens`` → 400) and
    rejects non-default ``temperature`` — both omitted (limitation recorded)."""
    try:
        import openai  # type: ignore[import-not-found]
    except ImportError as exc:
        return {"sub_queries": [], "raw_response": "", "parse_error": f"ImportError: {exc}",
                "latency_ms": None, "tokens_in": None, "tokens_out": None}
    client = openai.OpenAI()
    t0 = time.perf_counter()
    try:
        resp = client.chat.completions.create(
            model=model, max_completion_tokens=max_tokens,
            messages=[{"role": "user", "content": BOOTSTRAP_PROMPT.format(query=query)}],
        )
    except Exception as exc:  # noqa: BLE001 — never-raise per plan
        return {"sub_queries": [], "raw_response": "", "parse_error": f"{type(exc).__name__}: {exc}",
                "latency_ms": (time.perf_counter() - t0) * 1000.0,
                "tokens_in": None, "tokens_out": None}
    latency_ms = (time.perf_counter() - t0) * 1000.0
    text = resp.choices[0].message.content or ""
    sub_queries, parse_error = parse_sub_queries(text)
    usage = getattr(resp, "usage", None)
    return {"sub_queries": sub_queries, "raw_response": text, "parse_error": parse_error,
            "latency_ms": latency_ms,
            "tokens_in": getattr(usage, "prompt_tokens", None),
            "tokens_out": getattr(usage, "completion_tokens", None)}


def _score(per_case: list[dict]) -> dict[str, Any]:
    """Score agreement over LLM-bootstrapped (non-skeleton) cases.

    Recomputes ``agree_semantic`` from cached claude_sq/gpt_sq via ko-sroberta —
    this is the cost-0 path used by ``--recompute-from``."""
    scored: list[dict] = []
    agree_flags: list[float] = []
    structural_mismatch = same_shape_semantic = 0
    for row in per_case:
        if row.get("skipped") or row.get("parse_error"):
            scored.append({**row, "agree_semantic": None})
            continue
        claude_sq = list(row["claude_sub_queries"])
        gpt_sq = list(row["gpt_sub_queries"])
        agree = semantic_set_match(claude_sq, gpt_sq, threshold=0.85)
        agree_flags.append(1.0 if agree else 0.0)
        same_len = len(claude_sq) == len(gpt_sq)
        if not agree:
            if not same_len:
                structural_mismatch += 1  # different decomposition depth
            else:
                same_shape_semantic += 1  # same depth, cosine < 0.85
        scored.append({
            **row, "agree_semantic": agree, "same_len": same_len,
            "jaccard_strict": _jaccard_strict(claude_sq, gpt_sq),
        })
    n = len(agree_flags)
    disagreement = 1.0 - (sum(agree_flags) / n) if n else None
    ci = bootstrap_ci([1.0 - f for f in agree_flags]) if agree_flags else None
    return {
        "scored": scored, "n_compared": n,
        "disagreement_rate": disagreement, "disagreement_ci": ci,
        "n_disagreed": int(sum(1 for f in agree_flags if f == 0.0)),
        "structural_depth_mismatch": structural_mismatch,
        "same_shape_semantic": same_shape_semantic,
        "structural_floor_rate": (structural_mismatch / n) if n else None,
        "disagreed_case_ids": [r["id"] for r in scored if r.get("agree_semantic") is False],
    }


def _build_per_case_from_gold(gold: list[dict], slice_ids: set[str],
                              *, model: str, max_tokens: int,
                              max_calls: int) -> tuple[list[dict], dict[str, int]]:
    """Live GPT bootstrap pass over LLM-bootstrapped gold (skip abstention skeletons)."""
    per_case: list[dict] = []
    totals = {"tokens_in": 0, "tokens_out": 0, "parse_errors": 0, "calls": 0}
    in_slice = [g for g in gold if g["id"] in slice_ids]
    for i, g in enumerate(in_slice, start=1):
        meta = g.get("bootstrap_meta") or {}
        claude_sq = list(meta.get("original_sub_queries", []))
        if meta.get("skipped") or not claude_sq:
            per_case.append({"id": g["id"], "query": g["query"], "skipped": True,
                             "claude_sub_queries": claude_sq, "gpt_sub_queries": []})
            print(f"[{i}/{len(in_slice)}] {g['id']}: SKIP (abstention skeleton)")
            continue
        if totals["calls"] >= max_calls:
            raise SystemExit(f"--max-calls {max_calls} guardrail hit")
        r = call_openai_bootstrap(g["query"], model=model, max_tokens=max_tokens)
        totals["calls"] += 1
        totals["tokens_in"] += r.get("tokens_in") or 0
        totals["tokens_out"] += r.get("tokens_out") or 0
        if r.get("parse_error"):
            totals["parse_errors"] += 1
        per_case.append({
            "id": g["id"], "query": g["query"], "skipped": False,
            "parse_error": r.get("parse_error"),
            "claude_sub_queries": claude_sq, "gpt_sub_queries": list(r["sub_queries"]),
            "latency_ms": r["latency_ms"],
        })
        print(f"[{i}/{len(in_slice)}] {g['id']}: gpt {len(r['sub_queries'])} sq"
              f"{' PARSE_ERR' if r.get('parse_error') else ''}")
    return per_case, totals


def cmd_phase1_cross_model(args: argparse.Namespace) -> None:
    cfg = yaml.safe_load(Path(args.eval_config).read_text())
    slice_ids = {c["id"] for c in select_slice(cfg.get("cases", []))}
    gold = yaml.safe_load(Path(args.gold).read_text()) or []

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.recompute_from:
        # cost-0 re-score: reuse cached GPT outputs, only re-run ko-sroberta agree.
        prior = json.loads(Path(args.recompute_from).read_text())
        per_case = prior.get("per_case") or prior.get("scored") or prior
        totals = {"tokens_in": 0, "tokens_out": 0, "parse_errors": 0, "calls": 0}
        provenance = f"recomputed agreement from {args.recompute_from} (cost-0, ko-sroberta)"
    else:
        n_llm = sum(1 for g in gold if g["id"] in slice_ids
                    and not (g.get("bootstrap_meta") or {}).get("skipped")
                    and (g.get("bootstrap_meta") or {}).get("original_sub_queries"))
        est = n_llm * estimate_cost_usd(350, 200, args.model)
        print(f"cross-model: {n_llm} LLM cases via {args.model}, est ~${est:.3f}")
        if not args.yes:
            print("proceed? [y/N] ", end="", flush=True)
            if sys.stdin.readline().strip().lower() != "y":
                sys.exit(1)
        per_case, totals = _build_per_case_from_gold(
            gold, slice_ids, model=args.model, max_tokens=args.max_tokens,
            max_calls=args.max_calls)
        provenance = f"live {args.model} bootstrap"

    result = _score(per_case)
    tier, action = classify_tier(result["disagreement_rate"]) \
        if result["disagreement_rate"] is not None else ("unknown", "no comparable cases")

    cost = estimate_cost_usd(totals["tokens_in"], totals["tokens_out"], args.model)
    manifest = compute_run_manifest(Path(args.eval_config))
    summary: dict[str, Any] = {
        "run_manifest": manifest, "phase": "phase1_cross_model",
        "model": args.model, "provenance": provenance,
        "n_compared": result["n_compared"],
        "disagreement_rate": result["disagreement_rate"],
        "disagreement_ci": result["disagreement_ci"],
        "tier": tier, "fallback_action": action,
        "n_disagreed": result["n_disagreed"],
        "structural_depth_mismatch": result["structural_depth_mismatch"],
        "same_shape_semantic": result["same_shape_semantic"],
        "structural_floor_rate": result["structural_floor_rate"],
        "disagreed_case_ids": result["disagreed_case_ids"],
        "cost": {"tokens_in": totals["tokens_in"], "tokens_out": totals["tokens_out"],
                 "cost_usd": cost, "parse_errors": totals["parse_errors"]},
        "per_case": [{k: v for k, v in r.items()} for r in result["scored"]],
    }
    (out_dir / "phase1_5_cross_model_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2))

    rate = result["disagreement_rate"] or 0.0
    ci = result["disagreement_ci"]
    ci_str = f"[{ci['ci_lo']:.3f}, {ci['ci_hi']:.3f}]" if ci else "N/A"
    floor = result["structural_floor_rate"]
    floor_str = f"{floor:.1%}" if floor is not None else "N/A"
    sample = result["disagreed_case_ids"][:15]
    dirty = manifest.get("git_dirty")
    banner = "\n> ⚠️ **git_dirty: true**\n" if dirty else ""
    md = f"""# Phase 1.5 — Cross-Model Bootstrap Report ({args.model})
{banner}
`{manifest['generated_at']}` · git `{manifest['git_commit']}`
provenance: {provenance}

## Headline

- **disagreement_rate = {rate:.1%}**, 95% CI {ci_str}, n={result['n_compared']}
- **tier = {tier.upper()}** ({'≤15% high' if tier=='high' else '15-30% medium' if tier=='medium' else '≥30% low'})
- structural floor (count-mismatch) = **{floor_str}** ({result['structural_depth_mismatch']}/{result['n_compared']})
- same-shape semantic disagree = {result['same_shape_semantic']}/{result['n_compared']}
  (often embedding false-negatives → headline is a conservative-high bound).

## Fallback action

{action}

## Disagreed cases (sample ≤15 of {result['n_disagreed']})

{sample or '—'}

## Notes

- Compared vs `bootstrap_meta.original_sub_queries` (Claude pre-review output).
- Abstention skeletons excluded from the disagreement modulus.
- semantic match: bidirectional cosine ≥ 0.85 via `jhgan/ko-sroberta-multitask`
  (NOT hashing — hashing inverts SAME/DIFF on Korean RFP queries).
- cost ${cost:.3f} (in {totals['tokens_in']:,} / out {totals['tokens_out']:,}),
  parse errors {totals['parse_errors']}.

## Reproduce

```bash
# live:
python -m eval.planner_eval phase1_cross_model \\
  --eval-config {args.eval_config} \\
  --gold {args.gold} --model {args.model} --out-dir {out_dir}
# cost-0 re-score from cached per_case.json:
python -m eval.planner_eval phase1_cross_model \\
  --eval-config {args.eval_config} --gold {args.gold} \\
  --recompute-from {out_dir}/phase1_5_cross_model_summary.json --out-dir {out_dir}
```
"""
    (out_dir / "phase1_5_cross_model_report.md").write_text(md)
    print(f"disagreement_rate = {rate:.1%} CI {ci_str} → tier {tier.upper()}")
    print(f"structural floor = {floor_str}; summary: {out_dir}/phase1_5_cross_model_summary.json")
