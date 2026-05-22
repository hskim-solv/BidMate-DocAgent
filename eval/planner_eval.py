#!/usr/bin/env python3
"""Planner / query-decomposition component eval orchestrator (Path D).

Single-file orchestrator per CLAUDE.md "no premature abstraction": one
``decompose_query()`` callsite (in rag_query.py), prompt strings inline/external,
no Protocol/registry. Phase command bodies live in split files (LOC discipline,
Round-3 #3): planner_phase1_baseline / planner_phase1_cross_model / planner_phase2.
This module owns shared utils + the phase1 bootstrap subcommand + argparse.

Subcommands:
  phase1 bootstrap     — LLM-bootstrap draft gold sub_queries for multi-hop slice
  phase1 baseline      — current make_plan() baseline (→ planner_phase1_baseline.py)
  phase1_cross_model   — GPT cross-bootstrap vs Claude (→ planner_phase1_cross_model.py)
  phase2               — V0-V4 decomposition ablation (→ planner_phase2.py)

Hard STOP gates between every phase. Fake metrics forbidden — all numbers from
real execution. paired bootstrap CI 95%, seed-3 averaging.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from eval.run_eval import compute_run_manifest  # noqa: E402


# USD per 1M tokens. Rates verified 2026-05-21 against platform.claude.com
# pricing (output = 5x input). Update via 1-line edit when pricing shifts.
MODEL_RATES = {
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0},
    "claude-opus-4-7": {"in": 5.0, "out": 25.0},
    "claude-haiku-4-5-20251001": {"in": 1.0, "out": 5.0},
    # OpenAI rates (standard tier, USD per 1M tokens), Phase 1.5 cross-model.
    "gpt-5.5": {"in": 5.0, "out": 30.0},
    "gpt-5.4": {"in": 2.5, "out": 15.0},
    "gpt-5.4-mini": {"in": 0.75, "out": 4.5},
    "gpt-5.2": {"in": 1.75, "out": 14.0},
    "gpt-5.1": {"in": 1.25, "out": 10.0},
    "gpt-5": {"in": 1.25, "out": 10.0},
    "gpt-4o": {"in": 2.5, "out": 10.0},
    "gpt-4o-mini": {"in": 0.15, "out": 0.60},
}


# Semantic-match embedding model (plan §Phase 1.5 retrospective). The repo
# default (paraphrase-multilingual-MiniLM-L12-v2) under-discriminates Korean
# RFP short queries (SAME paraphrase 0.927 vs DIFF 0.901 — gap 0.026), and when
# its cache is absent embed_texts silently falls back to bag-of-words hashing
# (SAME 0.313 < DIFF 0.447 — inverted, the cause of a false 92.5% disagreement).
# Candidates measured on the same Korean RFP paraphrase/diff pairs:
#   - upskyy/bge-m3-korean: gap 0.271, peak RSS ~2.5GB (1024d) — too heavy.
#   - jhgan/ko-sroberta-multitask: gap 0.300, peak RSS 0.61GB (768d),
#     STS-fine-tuned (KorSTS+KorNLI). CHOSEN.
# Used ONLY for eval semantic matching — does NOT touch production retrieval
# embeddings (ADR 0001 baseline untouched).
SEMANTIC_MATCH_MODEL = "jhgan/ko-sroberta-multitask"


BOOTSTRAP_PROMPT = """\
You are decomposing a Korean RFP-domain query into retrievable sub-queries.

Return ONLY a JSON array (no preamble, no markdown fences, no explanation) of \
2-5 self-contained sub-queries in Korean. Each sub-query must:
  - be answerable by retrieving a single passage from RFP documents
  - rephrase or extract one sub-goal (do NOT include the original query verbatim)
  - be standalone (not require context from siblings)

If the original query asks to compare two or more entities/documents, emit one \
sub-query per entity. If it asks for multiple aspects of one entity, emit one \
sub-query per aspect.

Example A (comparison, multi entity):
Query: 울산광역시와 경기도 평택시의 BIS 사업을 비교해줘
Output: ["울산광역시의 BIS 사업 내용은?", "경기도 평택시의 BIS 사업 내용은?"]

Example B (single entity, multi aspect — single_doc multi-hop):
Query: X 사업의 평가 기준과 가점 항목은?
Output: ["X 사업의 평가 기준은?", "X 사업의 가점 항목은?"]

Now decompose:
Query: {query}
Output:"""


def parse_sub_queries(text: str) -> tuple[list[str], str | None]:
    """Extract a JSON array of non-empty strings (cap 5) from an LLM response.
    Strips markdown fences/preamble; falls back to the first ``[...]`` region."""
    import json as _json

    t = re.sub(r"\s*```$", "", re.sub(r"^```(?:json)?\s*", "", text.strip()))
    candidates = [t]
    m = re.search(r"\[[^\[\]]*\]", t, re.DOTALL)
    if m:
        candidates.append(m.group(0))
    for src in candidates:
        try:
            v = _json.loads(src)
        except _json.JSONDecodeError:
            continue
        if isinstance(v, list) and all(isinstance(x, str) and x.strip() for x in v):
            return [x.strip() for x in v[:5]], None
    return [], f"could not parse JSON list from {len(text)}-char response"


def select_slice(cases: list[dict]) -> list[dict]:
    """Multi-hop reasoning slice: query_type==multi_doc OR 'multi_hop' hardcase.
    EXCLUDES follow_up (multi-turn = a separate axis, plan scope correction)."""
    out: list[dict] = []
    for c in cases:
        if c.get("query_type") == "follow_up":
            continue
        hc = c.get("hardcase_categories") or []
        if c.get("query_type") == "multi_doc" or "multi_hop" in hc:
            out.append(c)
    return out


def estimate_cost_usd(tokens_in: int, tokens_out: int, model: str) -> float:
    rates = MODEL_RATES.get(model)
    if not rates:
        return 0.0
    return (tokens_in / 1_000_000) * rates["in"] + (tokens_out / 1_000_000) * rates["out"]


def call_anthropic_bootstrap(query: str, *, model: str, max_tokens: int) -> dict[str, Any]:
    """Single Anthropic bootstrap call (Phase 1 gold draft). Never raises."""
    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError as exc:
        return {"sub_queries": [], "raw_response": "", "parse_error": f"ImportError: {exc}",
                "latency_ms": None, "tokens_in": None, "tokens_out": None}
    client = anthropic.Anthropic()
    t0 = time.perf_counter()
    try:
        response = client.messages.create(
            model=model, max_tokens=max_tokens, temperature=0.0,
            messages=[{"role": "user", "content": BOOTSTRAP_PROMPT.format(query=query)}],
        )
    except Exception as exc:  # noqa: BLE001 — never-raise per plan
        return {"sub_queries": [], "raw_response": "", "parse_error": f"{type(exc).__name__}: {exc}",
                "latency_ms": (time.perf_counter() - t0) * 1000.0,
                "tokens_in": None, "tokens_out": None}
    latency_ms = (time.perf_counter() - t0) * 1000.0
    text = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", None) == "text")
    sub_queries, parse_error = parse_sub_queries(text)
    return {"sub_queries": sub_queries, "raw_response": text, "parse_error": parse_error,
            "latency_ms": latency_ms,
            "tokens_in": getattr(response.usage, "input_tokens", None),
            "tokens_out": getattr(response.usage, "output_tokens", None)}


def cmd_phase1_bootstrap(args: argparse.Namespace) -> None:
    """Phase 1 step 1+2: LLM-bootstrap a draft gold for the multi-hop slice.
    abstention cases → skeleton (sub_queries=[], skipped) requiring manual fill."""
    today = datetime.date.today().isoformat()
    cfg = yaml.safe_load(Path(args.eval_config).read_text())
    slice_cases = select_slice(cfg.get("cases", []))
    n = len(slice_cases)
    n_llm = sum(1 for c in slice_cases if c.get("query_type") != "abstention")
    print(f"slice: {n} cases ({n_llm} LLM, {n - n_llm} abstention skeleton)")
    print(f"estimated cost: ~${n_llm * estimate_cost_usd(300, 150, args.model):.3f}")
    if not args.yes:
        print("proceed? [y/N] ", end="", flush=True)
        if sys.stdin.readline().strip().lower() != "y":
            sys.exit(1)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    draft_path = Path(args.draft_out)

    entries: list[dict] = []
    skip_entries: list[dict] = []
    total_in = total_out = 0
    n_parse_errors = 0
    for i, c in enumerate(slice_cases, start=1):
        if c.get("query_type") == "abstention":
            entry = {
                "id": c["id"], "query": c["query"], "sub_queries": [],
                "bootstrap_source": f"abstention-skip / {today}",
                "reviewed_by": None, "reviewed_at": None,
                "bootstrap_meta": {"skipped": "abstention; manual fill required",
                                   "original_sub_queries": [], "latency_ms": None,
                                   "tokens_in": None, "tokens_out": None, "parse_error": None},
            }
            skip_entries.append(entry)
            entries.append(entry)
            print(f"[{i}/{n}] {c['id']}: SKIP (abstention)")
            continue
        r = call_anthropic_bootstrap(c["query"], model=args.model, max_tokens=args.max_tokens)
        if r.get("parse_error"):
            n_parse_errors += 1
        total_in += r.get("tokens_in") or 0
        total_out += r.get("tokens_out") or 0
        entries.append({
            "id": c["id"], "query": c["query"], "sub_queries": list(r["sub_queries"]),
            "bootstrap_source": f"{args.model} / {today}",
            "reviewed_by": None, "reviewed_at": None,
            "bootstrap_meta": {"skipped": None, "original_sub_queries": list(r["sub_queries"]),
                               "latency_ms": r["latency_ms"], "tokens_in": r["tokens_in"],
                               "tokens_out": r["tokens_out"], "parse_error": r.get("parse_error")},
        })
        print(f"[{i}/{n}] {c['id']}: {len(r['sub_queries'])} sub-queries")

    draft_path.write_text(yaml.dump(entries, allow_unicode=True, sort_keys=False))
    cost = estimate_cost_usd(total_in, total_out, args.model)
    summary = {
        "run_manifest": compute_run_manifest(Path(args.eval_config)),
        "phase": "phase1_bootstrap", "model": args.model, "n_cases": n,
        "n_llm": n_llm, "n_abstention_skip": len(skip_entries),
        "n_parse_errors": n_parse_errors,
        "cost": {"tokens_in": total_in, "tokens_out": total_out, "cost_usd": cost},
        "draft_path": str(draft_path),
    }
    (out_dir / "phase1_bootstrap_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    md = f"""# Phase 1 — Bootstrap Draft Report

`{summary['run_manifest']['generated_at']}` · git `{summary['run_manifest']['git_commit']}`

## Headline

- slice: **{n}** cases ({n_llm} LLM-bootstrapped, {len(skip_entries)} abstention skeleton)
- parse errors: {n_parse_errors}/{n_llm}
- cost: **${cost:.3f}** (in {total_in:,} / out {total_out:,})

Draft gold written to: `{draft_path}`

**Plan acceptance gate** requires:
1. ≥30% (≥{max(1, n // 3)} cases) human-reviewed
2. ALL {len(skip_entries)} abstention skeleton entries manually filled with 2-5 sub_queries each (validator will reject otherwise)
3. `reviewed_by` + `reviewed_at` set on every reviewed entry

Then:

```bash
mv {draft_path} eval/multihop_sub_queries.local.yaml
pytest tests/test_planner_eval_phase1.py -q
```

## Reproduce

```bash
python -m eval.planner_eval phase1 bootstrap \\
  --eval-config {args.eval_config} \\
  --model {args.model} \\
  --max-tokens {args.max_tokens} \\
  --out-dir {out_dir} \\
  --draft-out {draft_path}{' -y' if args.yes else ''}
```
"""
    (out_dir / "phase1_bootstrap_report.md").write_text(md)
    print(f"\ndraft: {draft_path}")
    print(f"summary: {out_dir}/phase1_bootstrap_summary.json")
    print(f"Next: edit draft, then `mv {draft_path} eval/multihop_sub_queries.local.yaml`")


def semantic_set_match(
    pred: list[str], gold: list[str], *, threshold: float = 0.85,
    model_name: str = SEMANTIC_MATCH_MODEL,
) -> bool:
    """True iff pred and gold are 1:1 bidirectionally matched as sets via cosine >= threshold.

    Empty/empty → True; one empty → False; cardinality mismatch → False (different
    set sizes = substantive difference). Algorithm: brute-force permutation (n ≤ 5,
    cap 120 perms, early termination) — eliminates greedy false-negative risk.
    Used by acceptance_rate_semantic + Phase 1.5 disagreement (cosine 0.85)."""
    pred = [p.strip() for p in (pred or []) if (p or "").strip()]
    gold = [g.strip() for g in (gold or []) if (g or "").strip()]
    if not pred and not gold:
        return True
    if not pred or not gold:
        return False
    if len(pred) != len(gold):
        return False
    from itertools import permutations  # noqa: E402

    import numpy as np  # noqa: E402
    from rag_embedding import embed_texts  # noqa: E402

    pred_emb = embed_texts(pred, backend="sentence-transformers", model_name=model_name).vectors
    gold_emb = embed_texts(gold, backend="sentence-transformers", model_name=model_name).vectors

    def _cos(a: "np.ndarray", b: "np.ndarray") -> float:
        na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return float(np.dot(a, b) / (na * nb))

    n = len(gold_emb)
    cos = [[_cos(gold_emb[i], pred_emb[j]) for j in range(n)] for i in range(n)]
    for perm in permutations(range(n)):
        if all(cos[i][perm[i]] >= threshold for i in range(n)):
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(prog="planner_eval", description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)

    p1 = sub.add_parser("phase1", help="Phase 1: multi-hop gold + current-planner baseline")
    p1_sub = p1.add_subparsers(dest="step", required=True)

    p1_bs = p1_sub.add_parser("bootstrap", help="LLM-bootstrap draft gold sub_queries")
    p1_bs.add_argument("--eval-config", required=True)
    p1_bs.add_argument("--model", default="claude-sonnet-4-6")
    p1_bs.add_argument("--max-tokens", type=int, default=512)
    p1_bs.add_argument("--out-dir", required=True)
    p1_bs.add_argument("--draft-out", default="eval/multihop_sub_queries.draft.local.yaml")
    p1_bs.add_argument("-y", "--yes", action="store_true", help="skip cost confirmation")
    p1_bs.set_defaults(func=cmd_phase1_bootstrap)

    p1_bl = p1_sub.add_parser("baseline", help="Run current make_plan() on slice")
    p1_bl.add_argument("--eval-config", required=True)
    p1_bl.add_argument("--gold", required=True)
    p1_bl.add_argument("--out-dir", required=True)

    def _baseline_dispatch(args: argparse.Namespace) -> None:
        from eval.planner_phase1_baseline import cmd_phase1_baseline
        cmd_phase1_baseline(args)
    p1_bl.set_defaults(func=_baseline_dispatch)

    p15 = sub.add_parser("phase1_cross_model",
                         help="Phase 1.5: GPT cross-bootstrap vs Claude (hard gate)")
    p15.add_argument("--eval-config", required=True)
    p15.add_argument("--gold", required=True)
    p15.add_argument("--model", default="gpt-5.5")
    p15.add_argument("--max-tokens", type=int, default=512)
    p15.add_argument("--out-dir", required=True)
    p15.add_argument("--max-calls", type=int, default=120, help="guardrail")
    p15.add_argument("-y", "--yes", action="store_true", help="skip cost confirmation")
    p15.add_argument("--recompute-from", default=None,
                     help="prior per_case.json; reuse GPT sub_queries, re-score agree_semantic only (cost-0)")

    def _cross_model_dispatch(args: argparse.Namespace) -> None:
        from eval.planner_phase1_cross_model import cmd_phase1_cross_model
        cmd_phase1_cross_model(args)
    p15.set_defaults(func=_cross_model_dispatch)

    p2 = sub.add_parser("phase2", help="Phase 2: V0-V4 decomposition ablation (3-seed, 2-winner)")
    p2.add_argument("--eval-config", required=True)
    p2.add_argument("--gold", required=True)
    p2.add_argument("--variants", default="v0,v1,v2,v3,v4")
    p2.add_argument("--seeds", default="17,42,123")
    p2.add_argument("--model", default="claude-sonnet-4-6")
    p2.add_argument("--prompts", default="eval/planner_variants.local.txt")
    p2.add_argument("--max-tokens", type=int, default=512)
    p2.add_argument("--f1-threshold", type=float, default=0.85,
                    help="primary semantic-match threshold (ko-sroberta validated point)")
    p2.add_argument("--out-dir", required=True)
    p2.add_argument("--max-calls", type=int, default=2000, help="guardrail")
    p2.add_argument("--allow-unreviewed", action="store_true",
                    help="DEBUG ONLY — include reviewed_by==null gold (default rejects)")
    p2.add_argument("--phase1-5-summary", default=None,
                    help="Phase 1.5 summary.json for MEDIUM-tier caveat (default: canonical run)")
    p2.add_argument("-y", "--yes", action="store_true", help="skip cost confirmation")

    def _phase2_dispatch(args: argparse.Namespace) -> None:
        from eval.planner_phase2 import cmd_phase2, DEFAULT_PHASE1_5_SUMMARY
        if args.phase1_5_summary is None:
            args.phase1_5_summary = DEFAULT_PHASE1_5_SUMMARY
        cmd_phase2(args)
    p2.set_defaults(func=_phase2_dispatch)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
