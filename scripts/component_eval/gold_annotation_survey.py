#!/usr/bin/env python3
"""Gold-annotation health survey (READ-ONLY, 0 LLM).

Component-level retrieval/verifier diagnosis depends on chunk-level gold
annotations (gold_chunk_ids). This survey quantifies, across ALL eval cases,
whether that annotation layer can actually support such diagnosis:

  - coverage: how many cases carry gold_chunk_ids at all
  - in-index: gold cid resolvable in current index.json
  - drift: gold chunk text vs expected_terms (substring AND) —
           present ⇒ annotation valid, absent ⇒ answer moved off chunk

Per query_type breakdown. Reuses eval/scorers/_shared.py::contains_all_terms.
No LLM calls.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from eval.scorers._shared import contains_all_terms  # noqa: E402


def survey_case(c, yaml_terms, cid_to_text):
    gold_cids = [str(g) for g in (c.get("gold_chunk_ids") or [])]
    terms = yaml_terms.get(c.get("id")) or []
    if not gold_cids:
        return "no_gold"
    in_index = [g for g in gold_cids if g in cid_to_text]
    if not in_index:
        return "gold_not_in_index"
    if not terms:
        return "gold_no_terms"  # has gold cid but no expected_terms to validate
    gold_text = " ".join(cid_to_text.get(g, "") for g in gold_cids)
    if contains_all_terms(gold_text, terms):
        return "gold_valid"
    return "gold_drift"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--index", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    es = json.loads(Path(args.input).read_text())
    cfg = yaml.safe_load(Path(args.config).read_text())
    yaml_terms = {c.get("id"): (c.get("expected_terms") or []) for c in (cfg.get("cases") or [])}
    idx = json.loads(Path(args.index).read_text())
    cid_to_text = {str(c["chunk_id"]): (c.get("text") or "") for c in idx.get("chunks") or []}
    crs = es.get("case_results") or []

    overall = Counter()
    by_qt = defaultdict(Counter)
    for c in crs:
        v = survey_case(c, yaml_terms, cid_to_text)
        overall[v] += 1
        by_qt[c.get("query_type") or "?"][v] += 1

    n = len(crs)
    cats = ["gold_valid", "gold_drift", "gold_not_in_index", "gold_no_terms", "no_gold"]

    def pct(v, tot):
        return f"{(v/tot*100):.0f}%" if tot else "—"

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "input": args.input, "config": args.config, "index": args.index,
        "n_cases": n,
        "overall": dict(overall),
        "by_query_type": {qt: dict(d) for qt, d in by_qt.items()},
    }

    has_gold = n - overall.get("no_gold", 0)
    judgable = overall.get("gold_valid", 0) + overall.get("gold_drift", 0)
    drift = overall.get("gold_drift", 0)

    L = []
    L.append("# Gold-annotation health survey (READ-ONLY, 0 LLM)\n")
    L.append(f"- generated: {manifest['generated_at']}")
    L.append(f"- input: `{args.input}`")
    L.append(f"- index: `{args.index}`")
    L.append(f"- n_cases: **{n}**")
    L.append("")
    L.append("## Overall\n")
    L.append("| category | n | % of all | meaning |")
    L.append("|---|---|---|---|")
    meanings = {
        "gold_valid": "chunk-gold 있고 답 텍스트도 일치 → diagnosis 가능",
        "gold_drift": "chunk-gold 있으나 답이 다른 chunk 로 이동 → stale",
        "gold_not_in_index": "gold cid 가 index 에 없음 → 완전 stale",
        "gold_no_terms": "gold cid 있으나 expected_terms 없어 검증 불가",
        "no_gold": "chunk-level gold annotation 자체가 없음",
    }
    for cat in cats:
        if overall.get(cat):
            L.append(f"| {cat} | {overall[cat]} | {pct(overall[cat], n)} | {meanings[cat]} |")
    L.append("")
    L.append(f"- chunk-gold 보유: **{has_gold}/{n} ({pct(has_gold, n)})**")
    if judgable:
        L.append(f"- terms-검증 가능 {judgable}건 중 **drift {drift} ({pct(drift, judgable)})**, valid {overall.get('gold_valid',0)}")
    L.append("")
    L.append("## Per query_type\n")
    L.append("| query_type | n | gold_valid | gold_drift | no_gold | etc |")
    L.append("|---|---|---|---|---|---|")
    for qt in sorted(by_qt):
        d = by_qt[qt]
        tot = sum(d.values())
        etc = d.get("gold_not_in_index", 0) + d.get("gold_no_terms", 0)
        L.append(f"| {qt} | {tot} | {d.get('gold_valid',0)} | {d.get('gold_drift',0)} | "
                 f"{d.get('no_gold',0)} | {etc} |")
    L.append("")
    L.append("## 결론\n")
    L.append(f"- **chunk-level component diagnosis (retrieval recall / verifier status) 에 쓸 수 있는 깨끗한 케이스 = gold_valid {overall.get('gold_valid',0)}건 ({pct(overall.get('gold_valid',0), n)}).**")
    L.append(f"- 나머지 {n - overall.get('gold_valid',0)}건은 no-gold / drift / stale 로 chunk-level 진단 불가.")
    L.append("- → retrieval recall · verifier status 의 component-level 수치는 이 {n}건 전체로 내면 안 됨. gold_valid 부분집합에서만 유효.")
    L.append("")
    L.append("## Honesty / caveats\n")
    L.append("- terms-test = substring AND (`contains_all_terms`). expected_terms 부분적이면 false drift.")
    L.append("- no_gold 는 의도된 설계일 수 있음 (abstention 쿼리는 gold 없음이 정상). query_type 별 표로 구분.")
    L.append("- 0 LLM call.")

    (out / "report.md").write_text("\n".join(L) + "\n")
    (out / "raw.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"Wrote: {out}/report.md", file=sys.stderr)
    print(f"n={n} has_gold={has_gold} gold_valid={overall.get('gold_valid',0)} "
          f"drift={drift} no_gold={overall.get('no_gold',0)}", file=sys.stderr)


if __name__ == "__main__":
    main()
