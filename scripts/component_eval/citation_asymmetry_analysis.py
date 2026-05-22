#!/usr/bin/env python3
"""Phase 2-bis B step — Citation asymmetry analysis (READ-ONLY, 0 LLM calls).

Hypothesis: In Phase 2-bis v2, gold-chunk citation rate at position=first (0.857)
is lower than middle/last (0.952 each). CI overlaps but margin is ~10pp.
Re-analyze the raw .jsonl to either confirm or refute:
  1. Paired bootstrap: per (case, seed) compute cite(first) - cite(last/middle), CI 95%
  2. Per-case breakdown: list (case, seed) where first-position cite failed
  3. Distractor-cite frequency: when LLM cites in first-position cases, what got cited?
  4. Cite chunk_id histogram per position (gold vs distractor vs nothing)

No LLM calls — reads Phase 2-bis raw and derives stats only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from eval.bootstrap import bootstrap_ci  # noqa: E402

CITE_RE = re.compile(r"\[([^\[\]]+?)\]")


def extract_cites(text: str) -> list[str]:
    """Return all [chunk_id] tokens from response text (unique-preserving order)."""
    if not text:
        return []
    seen = set()
    out = []
    for m in CITE_RE.finditer(text):
        cid = m.group(1).strip()
        if cid and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def fmt_ci(vals: list[float]) -> str:
    if not vals:
        return "n=0"
    c = bootstrap_ci(vals)
    return f"mean={c['mean']:.3f} ci=[{c['ci_lo']:.3f}, {c['ci_hi']:.3f}] n={c['n']}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="phase2_bis_raw.jsonl path")
    p.add_argument("--output", required=True, help="output dir")
    args = p.parse_args()

    rows = [json.loads(l) for l in Path(args.input).read_text().splitlines() if l.strip()]
    # only successful gen rows
    ok_rows = [r for r in rows if r.get("position") and r.get("error") is None]
    print(f"loaded {len(rows)} rows ({len(ok_rows)} successful gen)", file=sys.stderr)

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    # ---- triple build ----
    triples_cite: dict[tuple, dict[str, int]] = defaultdict(dict)  # 1=cited, 0=not
    triples_distractor_cite: dict[tuple, dict[str, int]] = defaultdict(dict)  # cited a distractor
    triples_no_cite: dict[tuple, dict[str, int]] = defaultdict(dict)  # cited nothing
    per_call_cite_dist: dict[str, Counter] = {"first": Counter(), "middle": Counter(), "last": Counter()}

    for r in ok_rows:
        key = (r["case_id"], r["seed"])
        pos = r["position"]
        gold_cid = str(r["gold_chunk_id"])
        hard_neg_cids = set(map(str, r.get("hard_neg_chunk_ids") or []))
        cites = extract_cites(r.get("response_text") or "")
        cite_set = set(cites)
        cited_gold = 1 if gold_cid in cite_set else 0
        cited_distractor = 1 if (cite_set & hard_neg_cids) else 0
        no_cite = 1 if not cites else 0
        triples_cite[key][pos] = cited_gold
        triples_distractor_cite[key][pos] = cited_distractor
        triples_no_cite[key][pos] = no_cite
        # cite distribution: classify each citation
        for cid in cites:
            if cid == gold_cid:
                per_call_cite_dist[pos]["gold"] += 1
            elif cid in hard_neg_cids:
                per_call_cite_dist[pos]["distractor"] += 1
            else:
                per_call_cite_dist[pos]["other"] += 1  # unknown — usually parse noise

    full_triples = [(k, v, triples_distractor_cite[k], triples_no_cite[k])
                    for k, v in triples_cite.items() if len(v) == 3]
    print(f"complete triples: {len(full_triples)}", file=sys.stderr)

    # paired diffs (gold citation)
    diff_first_last = [v["first"] - v["last"] for k, v, _, _ in full_triples]
    diff_first_middle = [v["first"] - v["middle"] for k, v, _, _ in full_triples]
    diff_middle_last = [v["middle"] - v["last"] for k, v, _, _ in full_triples]

    # paired diffs (distractor citation)
    dd_first_last = [d["first"] - d["last"] for _, _, d, _ in full_triples]
    dd_first_middle = [d["first"] - d["middle"] for _, _, d, _ in full_triples]

    # per-position means (gold cite)
    by_pos_cite = {"first": [], "middle": [], "last": []}
    by_pos_distractor = {"first": [], "middle": [], "last": []}
    by_pos_no_cite = {"first": [], "middle": [], "last": []}
    for _, v, d, nc in full_triples:
        for pos in ("first", "middle", "last"):
            by_pos_cite[pos].append(v[pos])
            by_pos_distractor[pos].append(d[pos])
            by_pos_no_cite[pos].append(nc[pos])

    # per-case breakdown: which (case, seed) had first=0 cite?
    fail_cases = [(k, v) for k, v, _, _ in full_triples if v["first"] == 0]
    fail_cases_first_only = [(k, v) for k, v, _, _ in full_triples
                              if v["first"] == 0 and v["middle"] == 1 and v["last"] == 1]
    # cases where first failed but middle/last succeeded — directly supports asymmetry hypothesis

    # McNemar 2x2 (first vs last cite)
    # b = first=1 & last=0; c = first=0 & last=1
    b = sum(1 for _, v, _, _ in full_triples if v["first"] == 1 and v["last"] == 0)
    c = sum(1 for _, v, _, _ in full_triples if v["first"] == 0 and v["last"] == 1)
    n_disc = b + c
    # exact McNemar p-value (binomial test, two-sided, p=0.5)
    # approximate with chi-square if n_disc >= 25; exact otherwise
    if n_disc > 0:
        # exact binomial: 2 * sum(C(n,k) for k in [0..min(b,c)]) * 0.5**n
        from math import comb
        k_min = min(b, c)
        p_one = sum(comb(n_disc, k) for k in range(0, k_min + 1)) * 0.5 ** n_disc
        mcnemar_p = min(1.0, 2 * p_one)
    else:
        mcnemar_p = 1.0

    # ---- manifest ----
    manifest = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "input": args.input,
        "n_rows_input": len(rows),
        "n_rows_ok": len(ok_rows),
        "n_complete_triples": len(full_triples),
        "n_first_fail_cases": len(fail_cases),
        "n_first_fail_only": len(fail_cases_first_only),
        "mcnemar_first_vs_last": {"b_first1_last0": b, "c_first0_last1": c, "p_two_sided_exact": round(mcnemar_p, 6)},
    }

    # ---- markdown report ----
    L = []
    L.append("# Phase 2-bis B — Citation asymmetry verification (READ-ONLY)\n")
    L.append(f"- generated: {manifest['generated_at']}")
    L.append(f"- input: `{args.input}`")
    L.append(f"- n_rows: {manifest['n_rows_input']}, n_ok: {manifest['n_rows_ok']}, "
             f"complete triples: {manifest['n_complete_triples']}")
    L.append("")
    L.append("## 1. Gold citation rate per position (paired bootstrap CI 95%)\n")
    for pos in ("first", "middle", "last"):
        L.append(f"- **{pos}**: {fmt_ci(by_pos_cite[pos])}")
    L.append("")
    L.append("## 2. Paired diffs — gold citation (within (case, seed))\n")
    L.append(f"- cite(first) - cite(last):   {fmt_ci(diff_first_last)}")
    L.append(f"- cite(first) - cite(middle): {fmt_ci(diff_first_middle)}")
    L.append(f"- cite(middle) - cite(last):  {fmt_ci(diff_middle_last)}")
    L.append("")
    L.append("## 3. McNemar exact (first vs last gold-citation discordant)\n")
    L.append(f"- b (first=1, last=0): {b}")
    L.append(f"- c (first=0, last=1): {c}")
    L.append(f"- discordant n: {n_disc}")
    L.append(f"- two-sided exact p: {mcnemar_p:.4f}")
    L.append(f"  ({'significant @ p<0.05' if mcnemar_p < 0.05 else 'NOT significant @ p<0.05'})")
    L.append("")
    L.append("## 4. Distractor citation rate per position\n")
    L.append("- (cases where LLM cited any of the 5 hard-neg distractors)")
    for pos in ("first", "middle", "last"):
        L.append(f"- **{pos}**: {fmt_ci(by_pos_distractor[pos])}")
    L.append("")
    L.append("## 5. No-citation rate per position\n")
    L.append("- (cases where LLM cited nothing at all)")
    for pos in ("first", "middle", "last"):
        L.append(f"- **{pos}**: {fmt_ci(by_pos_no_cite[pos])}")
    L.append("")
    L.append("## 6. Cite chunk_id classification per position\n")
    L.append("- counts across all per-call cites; each call may contribute multiple")
    L.append("| position | gold | distractor | other (unknown) |")
    L.append("|----------|------|------------|-----------------|")
    for pos in ("first", "middle", "last"):
        d = per_call_cite_dist[pos]
        L.append(f"| {pos} | {d['gold']} | {d['distractor']} | {d['other']} |")
    L.append("")
    L.append("## 7. Per-case breakdown — first-position cite failures\n")
    L.append(f"- cases (= (case_id, seed)) where first=0: **{len(fail_cases)}**")
    L.append(f"- of which first=0 AND middle=1 AND last=1 (asymmetry pattern): **{len(fail_cases_first_only)}**")
    L.append("")
    if fail_cases_first_only:
        L.append("Asymmetric-fail (case_id, seed):")
        for (cid, seed), _ in fail_cases_first_only[:20]:
            L.append(f"  - `{cid}` seed={seed}")
        if len(fail_cases_first_only) > 20:
            L.append(f"  - ... +{len(fail_cases_first_only) - 20} more")
        L.append("")
    L.append("## 8. Distractor citation paired diff (within (case, seed))\n")
    L.append(f"- distractor_cite(first) - distractor_cite(last):   {fmt_ci(dd_first_last)}")
    L.append(f"- distractor_cite(first) - distractor_cite(middle): {fmt_ci(dd_first_middle)}")
    L.append("- (positive = first position more likely to misattribute to distractor)")
    L.append("")
    L.append("## 9. 결론\n")
    # judge significance
    rng_low_high = lambda v: bootstrap_ci(v) if v else None
    c_fl = rng_low_high(diff_first_last)
    sig_paired = (c_fl is not None and (c_fl['ci_lo'] > 0 or c_fl['ci_hi'] < 0))
    sig_mcnemar = mcnemar_p < 0.05
    if sig_paired or sig_mcnemar:
        L.append("- **citation asymmetry CONFIRMED** at first position")
        if sig_paired:
            L.append(f"  - paired bootstrap CI excludes 0: {fmt_ci(diff_first_last)}")
        if sig_mcnemar:
            L.append(f"  - McNemar exact p={mcnemar_p:.4f} < 0.05")
    else:
        L.append("- **citation asymmetry NOT confirmed** (보고된 ~10pp 차이는 noise 수준)")
        L.append(f"  - paired diff CI {fmt_ci(diff_first_last)} crosses 0")
        L.append(f"  - McNemar exact p={mcnemar_p:.4f} (no significance @ 0.05)")
    if len(fail_cases_first_only) > 0:
        L.append(f"- 비대칭 패턴 case 수: {len(fail_cases_first_only)} / {len(full_triples)} triples")
    L.append("")
    L.append("## 10. Honesty / caveats\n")
    L.append("- 입력 = Phase 2-bis v2 (n=14 cases × 3 seeds × 3 positions). Small sample — sub-CI wide.")
    L.append("- Citation = response text 에 `[chunk_id]` 패턴 검색. malformed cite (괄호 없음, typo) 는 miss.")
    L.append("- McNemar exact 는 두 marginals 균등 (p=0.5) 가정. 작은 discordant n 에서 검정력 낮음.")
    L.append("- 0 LLM call — Phase 2-bis 의 raw response 만 재사용.")
    (out / "analysis.md").write_text("\n".join(L) + "\n")
    (out / "analysis.json").write_text(json.dumps({
        "manifest": manifest,
        "per_position_gold_cite": {p: by_pos_cite[p] for p in ("first", "middle", "last")},
        "per_position_distractor_cite": {p: by_pos_distractor[p] for p in ("first", "middle", "last")},
        "per_position_no_cite": {p: by_pos_no_cite[p] for p in ("first", "middle", "last")},
        "diff_first_last_gold": diff_first_last,
        "diff_first_middle_gold": diff_first_middle,
        "diff_middle_last_gold": diff_middle_last,
        "diff_first_last_distractor": dd_first_last,
        "fail_cases_first_only": [{"case_id": k[0], "seed": k[1]} for k, _ in fail_cases_first_only],
        "cite_dist_per_position": {p: dict(per_call_cite_dist[p]) for p in ("first", "middle", "last")},
    }, ensure_ascii=False, indent=2))
    print(f"Wrote: {out}/analysis.md", file=sys.stderr)
    print(f"Wrote: {out}/analysis.json", file=sys.stderr)


if __name__ == "__main__":
    main()
