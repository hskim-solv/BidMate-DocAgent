#!/usr/bin/env python3
"""Verifier failure-mode pivot — single_doc decomposition (READ-ONLY, 0 LLM).

The headline "verifier accuracy 30.3% / single_doc 0.089" conflates two very
different failure sources. This script separates them per case using fields
already present in eval_summary case_results:

  - gold_retrieved  = (gold_chunk_ids ∩ retrieved_chunk_ids) non-empty
  - doc_matched     = expected_doc_ids ⊆ evidence_doc_ids
  - answer_status vs expected_answer_status

Failure taxonomy for expected=supported cases:
  1. retrieval_miss_doc    — gold chunk NOT retrieved AND wrong doc      (retrieval fault)
  2. retrieval_miss_chunk  — gold chunk NOT retrieved BUT right doc      (retrieval rank / re-chunk drift)
  3. verifier_downgrade    — gold chunk retrieved, but status != supported (verifier fault candidate)
  4. correct               — status == expected

⚠️ Caveat: gold_chunk_ids are fixed yaml annotations. A chunker rebuild can
move the answer text to a different chunk number, inflating retrieval_miss_*.
We surface doc_matched separately so "right doc, wrong chunk" (drift-suspect)
is distinguishable from "wrong doc" (genuine retrieval miss).

No LLM calls.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def gold_retrieved(c: dict) -> bool:
    gold = {str(g) for g in (c.get("gold_chunk_ids") or [])}
    retr = {str(r) for r in (c.get("retrieved_chunk_ids") or [])}
    return bool(gold & retr)


def doc_matched(c: dict) -> bool:
    exp = {str(d) for d in (c.get("expected_doc_ids") or [])}
    ev = {str(d) for d in (c.get("evidence_doc_ids") or [])}
    return bool(exp) and exp.issubset(ev)


def classify(c: dict) -> str:
    actual = c.get("answer_status")
    expected = c.get("expected_answer_status")
    if actual == expected:
        return "correct"
    if expected == "supported":
        if gold_retrieved(c):
            return "verifier_downgrade"  # gold chunk present but not 'supported'
        elif doc_matched(c):
            return "retrieval_miss_chunk"  # right doc, gold chunk ranked out / drift
        else:
            return "retrieval_miss_doc"  # wrong doc entirely
    if expected == "insufficient" and actual in ("supported", "partial"):
        return "false_confident"
    return f"other:{actual}->{expected}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="eval_summary.json")
    p.add_argument("--output", required=True)
    p.add_argument("--query-type", default="single_doc",
                   help="focus query_type (default single_doc); 'all' for every type")
    args = p.parse_args()

    es = json.loads(Path(args.input).read_text())
    crs = es.get("case_results") or []
    if args.query_type == "all":
        cases = crs
    else:
        cases = [c for c in crs if c.get("query_type") == args.query_type]

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    # status confusion
    confusion = defaultdict(lambda: defaultdict(int))
    for c in cases:
        confusion[c.get("answer_status")][c.get("expected_answer_status")] += 1

    # classify each case
    by_mode = defaultdict(list)
    for c in cases:
        by_mode[classify(c)].append(c)

    n = len(cases)
    correct = len(by_mode.get("correct", []))

    # for verifier_downgrade — how many actually had correct answer (accuracy=1.0)?
    downgrade = by_mode.get("verifier_downgrade", [])
    downgrade_acc1 = sum(1 for c in downgrade if c.get("accuracy") == 1.0)
    downgrade_status = Counter(c.get("answer_status") for c in downgrade)

    # retrieval-miss cases: filter_stage + retry distribution
    miss_doc = by_mode.get("retrieval_miss_doc", [])
    miss_chunk = by_mode.get("retrieval_miss_chunk", [])
    miss_all = miss_doc + miss_chunk
    miss_status = Counter(c.get("answer_status") for c in miss_all)

    def ids(cases_list, k=12):
        out_ids = [str(c.get("id")) for c in cases_list[:k]]
        if len(cases_list) > k:
            out_ids.append(f"... +{len(cases_list)-k} more")
        return out_ids

    manifest = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "input": args.input,
        "query_type": args.query_type,
        "n_cases": n,
        "n_correct": correct,
        "status_accuracy": round(correct / n, 4) if n else 0.0,
        "mode_counts": {m: len(v) for m, v in sorted(by_mode.items())},
        "retrieval_miss_total": len(miss_all),
        "retrieval_miss_pct_of_failures": round(len(miss_all) / max(n - correct, 1), 4),
        "verifier_downgrade_total": len(downgrade),
        "verifier_downgrade_acc1": downgrade_acc1,
    }

    # ---- report ----
    L = []
    L.append(f"# Verifier failure-mode pivot — query_type={args.query_type} (READ-ONLY)\n")
    L.append(f"- generated: {manifest['generated_at']}")
    L.append(f"- input: `{args.input}`")
    L.append(f"- n_cases: {n}, correct: {correct}, **status accuracy: {manifest['status_accuracy']:.3f}**")
    L.append("")
    L.append("## 1. Status confusion (actual verifier × expected yaml)\n")
    statuses = ["insufficient", "partial", "supported"]
    L.append("| actual\\expected | " + " | ".join(statuses) + " |")
    L.append("|---|" + "---|" * len(statuses))
    for a in statuses:
        row = [str(confusion.get(a, {}).get(e, 0)) for e in statuses]
        L.append(f"| **{a}** | " + " | ".join(row) + " |")
    L.append("")
    L.append("## 2. Failure-mode decomposition\n")
    L.append("| mode | n | % of all | % of failures |")
    L.append("|------|---|----------|---------------|")
    fails = n - correct
    for mode in ("correct", "verifier_downgrade", "retrieval_miss_chunk",
                 "retrieval_miss_doc", "false_confident"):
        cnt = len(by_mode.get(mode, []))
        if cnt == 0 and mode not in ("correct",):
            continue
        pct_all = cnt / n if n else 0
        pct_fail = cnt / fails if fails and mode != "correct" else 0
        fail_str = f"{pct_fail:.1%}" if mode != "correct" else "—"
        L.append(f"| {mode} | {cnt} | {pct_all:.1%} | {fail_str} |")
    # any 'other:' modes
    for mode, v in sorted(by_mode.items()):
        if mode.startswith("other:"):
            L.append(f"| {mode} | {len(v)} | {len(v)/n:.1%} | {len(v)/fails:.1%} |")
    L.append("")
    L.append(f"- **retrieval-miss total** (wrong doc + right-doc-wrong-chunk): "
             f"{len(miss_all)} = **{manifest['retrieval_miss_pct_of_failures']:.1%} of failures**")
    L.append(f"  - retrieval_miss_doc (wrong doc): {len(miss_doc)}")
    L.append(f"  - retrieval_miss_chunk (right doc, gold chunk ranked out / re-chunk drift): {len(miss_chunk)}")
    L.append(f"  - retrieval-miss status spread: {dict(miss_status)}")
    L.append(f"- **verifier_downgrade** (gold retrieved but not 'supported'): {len(downgrade)}")
    L.append(f"  - of which accuracy=1.0 (answer actually correct): {downgrade_acc1}")
    L.append(f"  - their status spread: {dict(downgrade_status)}")
    L.append("")
    L.append("## 3. 결론 — single_doc 0.089 의 진짜 원인\n")
    if len(miss_all) / max(fails, 1) >= 0.6:
        L.append(f"- **retrieval recall 실패가 지배적** ({len(miss_all)}/{fails} = {len(miss_all)/fails:.0%} of failures).")
        L.append("  gold chunk 가 애초에 retrieved 안 됨 → verifier 는 근거 없으니 partial/insufficient 정직 반환. **verifier 잘못 아님.**")
        L.append(f"- verifier 자체 의심 (gold 있는데 downgrade) 은 {len(downgrade)} 건뿐, 그 중 정답 맞춘 건 {downgrade_acc1} 건.")
    else:
        L.append(f"- verifier_downgrade 가 {len(downgrade)} 건으로 무시 못 함 — substring AND-gate 영향 가능.")
    L.append("")
    L.append("## 4. ⚠️ Annotation-drift caveat\n")
    L.append("- gold_chunk_ids 는 yaml 고정 annotation. chunker rebuild (2026-05-19) 가 답 텍스트를 다른 chunk 번호로 이동시켰을 수 있음.")
    L.append(f"- `retrieval_miss_chunk` ({len(miss_chunk)} 건, right doc 인데 gold chunk 못 맞춤) 일부는 진짜 retrieval rank 문제가 아니라 **annotation drift** 일 수 있음.")
    L.append(f"- `retrieval_miss_doc` ({len(miss_doc)} 건, 아예 다른 doc) 은 drift 아닌 genuine 검색 실패에 가까움.")
    L.append("- 확정하려면 gold chunk 텍스트가 실제 답을 담는지 + retrieved doc 가 정답 doc 인지 수동 spot-check 필요 (별도 작업).")
    L.append("")
    L.append("## 5. Example case IDs\n")
    L.append("### verifier_downgrade (gold retrieved, status != supported)")
    for cid in ids(downgrade):
        L.append(f"  - `{cid}`")
    L.append("")
    L.append("### retrieval_miss_chunk (right doc, gold chunk out — drift-suspect)")
    for cid in ids(miss_chunk):
        L.append(f"  - `{cid}`")
    L.append("")
    L.append("### retrieval_miss_doc (wrong doc)")
    for cid in ids(miss_doc):
        L.append(f"  - `{cid}`")
    L.append("")
    L.append("## 6. Honesty / caveats\n")
    L.append("- 0 LLM call — eval_summary case_results 필드만 재분석.")
    L.append("- expected_answer_status (yaml 수동 라벨) 를 ground truth 로 가정.")
    L.append("- gold_retrieved/doc_matched 는 chunk_id / doc_id 집합 연산 — annotation 정확성에 의존.")
    L.append("- single_doc 의 expected_answer_status 는 전부 'supported' (이 데이터셋), 그래서 false_confident 모드는 single_doc 에서 0.")

    (out / "report.md").write_text("\n".join(L) + "\n")
    (out / "raw.json").write_text(json.dumps({
        "manifest": manifest,
        "confusion": {a: dict(d) for a, d in confusion.items()},
        "mode_case_ids": {m: [str(c.get("id")) for c in v] for m, v in by_mode.items()},
    }, ensure_ascii=False, indent=2))
    print(f"Wrote: {out}/report.md", file=sys.stderr)
    print(f"Wrote: {out}/raw.json", file=sys.stderr)
    print(f"status_accuracy={manifest['status_accuracy']:.3f}, "
          f"retrieval_miss={manifest['retrieval_miss_pct_of_failures']:.1%} of failures, "
          f"verifier_downgrade={len(downgrade)} (acc1={downgrade_acc1})", file=sys.stderr)


if __name__ == "__main__":
    main()
