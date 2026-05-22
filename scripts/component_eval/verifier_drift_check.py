#!/usr/bin/env python3
"""Annotation-drift check for retrieval-miss cases (READ-ONLY, 0 LLM).

The failure pivot found ~90% of single_doc failures = "gold chunk not retrieved".
But gold_chunk_ids are fixed yaml annotations; a chunker rebuild can move the
answer text to a different chunk number, faking a retrieval miss.

Definitive automated test (no manual spot-check needed):
  For each retrieval-miss case, fetch the gold chunk text FROM THE INDEX and
  test contains_all_terms(gold_text, expected_terms):
    - terms present  → annotation valid → GENUINE retrieval miss
    - terms absent   → answer moved off the annotated chunk → ANNOTATION DRIFT
    - gold cid not in index → annotation fully stale

Reuses eval/scorers/_shared.py::contains_all_terms (same substring semantics the
eval itself uses). No LLM calls.
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


def gold_retrieved(c: dict) -> bool:
    gold = {str(g) for g in (c.get("gold_chunk_ids") or [])}
    retr = {str(r) for r in (c.get("retrieved_chunk_ids") or [])}
    return bool(gold & retr)


def doc_matched(c: dict) -> bool:
    exp = {str(d) for d in (c.get("expected_doc_ids") or [])}
    ev = {str(d) for d in (c.get("evidence_doc_ids") or [])}
    return bool(exp) and exp.issubset(ev)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="eval_summary.json")
    p.add_argument("--config", required=True, help="real_config.local.yaml (expected_terms)")
    p.add_argument("--index", required=True, help="index.json (gold chunk text lookup)")
    p.add_argument("--output", required=True)
    p.add_argument("--query-type", default="single_doc")
    args = p.parse_args()

    es = json.loads(Path(args.input).read_text())
    cfg = yaml.safe_load(Path(args.config).read_text())
    yaml_terms = {c.get("id"): (c.get("expected_terms") or []) for c in (cfg.get("cases") or [])}
    idx = json.loads(Path(args.index).read_text())
    cid_to_text = {str(c["chunk_id"]): (c.get("text") or "") for c in idx.get("chunks") or []}

    crs = es.get("case_results") or []
    if args.query_type == "all":
        cases = crs
    else:
        cases = [c for c in crs if c.get("query_type") == args.query_type]

    # retrieval-miss cases: expected supported, status wrong, gold NOT retrieved
    miss = [
        c for c in cases
        if c.get("expected_answer_status") == "supported"
        and c.get("answer_status") != "supported"
        and not gold_retrieved(c)
    ]

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    verdict = Counter()
    by_docmatch = defaultdict(Counter)
    for c in miss:
        cid = c.get("id")
        gold_cids = [str(g) for g in (c.get("gold_chunk_ids") or [])]
        terms = yaml_terms.get(cid) or []
        in_index = [g for g in gold_cids if g in cid_to_text]
        gold_text = " ".join(cid_to_text.get(g, "") for g in gold_cids)
        dm = doc_matched(c)
        dm_key = "right_doc" if dm else "wrong_doc"

        if not gold_cids:
            v = "no_gold_annotation"
        elif not in_index:
            v = "gold_cid_not_in_index"   # annotation fully stale
        elif not terms:
            v = "no_expected_terms"        # can't判定 via terms
        elif contains_all_terms(gold_text, terms):
            v = "annotation_valid"         # gold chunk really holds the answer → GENUINE retrieval miss
        else:
            v = "drift"                    # answer not on annotated chunk → ANNOTATION DRIFT
        verdict[v] += 1
        by_docmatch[dm_key][v] += 1
        rows.append({
            "id": cid, "verdict": v, "doc_matched": dm,
            "n_gold": len(gold_cids), "n_gold_in_index": len(in_index),
            "expected_terms": terms,
            "gold_text_len": len(gold_text),
        })

    n = len(miss)
    genuine = verdict.get("annotation_valid", 0)
    drift = verdict.get("drift", 0)
    stale = verdict.get("gold_cid_not_in_index", 0)
    no_terms = verdict.get("no_expected_terms", 0)
    judgable = genuine + drift  # cases where the terms-test gives a verdict

    manifest = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "input": args.input, "config": args.config, "index": args.index,
        "query_type": args.query_type,
        "n_retrieval_miss": n,
        "verdict_counts": dict(verdict),
        "genuine_miss": genuine,
        "drift": drift,
        "gold_cid_not_in_index": stale,
        "no_expected_terms": no_terms,
        "drift_fraction_of_judgable": round(drift / judgable, 4) if judgable else None,
    }

    L = []
    L.append(f"# Annotation-drift check — retrieval-miss cases (query_type={args.query_type})\n")
    L.append(f"- generated: {manifest['generated_at']}")
    L.append(f"- input: `{args.input}`")
    L.append(f"- index: `{args.index}`")
    L.append(f"- retrieval-miss cases examined: **{n}**")
    L.append("")
    L.append("## Verdict (gold chunk text vs expected_terms)\n")
    L.append("| verdict | n | meaning |")
    L.append("|---------|---|---------|")
    meanings = {
        "annotation_valid": "gold chunk 에 답 있음 → **진짜 retrieval miss**",
        "drift": "gold chunk 에 답 없음 → **annotation drift** (chunker rebuild artifact)",
        "gold_cid_not_in_index": "gold chunk_id 가 index 에 아예 없음 → annotation 완전 stale",
        "no_expected_terms": "yaml 에 expected_terms 없음 → terms-test 불가",
        "no_gold_annotation": "gold_chunk_ids 없음",
    }
    for v in ("annotation_valid", "drift", "gold_cid_not_in_index", "no_expected_terms", "no_gold_annotation"):
        if verdict.get(v):
            L.append(f"| {v} | {verdict[v]} | {meanings[v]} |")
    L.append("")
    if judgable:
        L.append(f"- **terms-test 판정 가능 {judgable}건 중 drift = {drift} ({manifest['drift_fraction_of_judgable']:.1%})**")
        L.append(f"  - 진짜 retrieval miss: {genuine} ({genuine/judgable:.1%})")
    L.append(f"- terms-test 불가 (no_expected_terms): {no_terms} / index-stale: {stale}")
    L.append("")
    L.append("## doc_matched 별 분해\n")
    L.append("- right_doc = 정답 doc 가 evidence 에 있었으나 gold chunk 는 누락 (drift 유력 후보)")
    L.append("- wrong_doc = 정답 doc 자체가 안 나옴 (genuine 검색 실패 유력)")
    L.append("")
    for dm_key in ("right_doc", "wrong_doc"):
        d = by_docmatch.get(dm_key, {})
        if d:
            L.append(f"- **{dm_key}** (n={sum(d.values())}): {dict(d)}")
    L.append("")
    L.append("## 결론\n")
    if judgable:
        df = manifest["drift_fraction_of_judgable"]
        if df is not None and df < 0.2:
            L.append(f"- **drift 적음 ({df:.1%})** → 90% retrieval-miss 는 대체로 **진짜**. retrieval recall 이 진짜 병목 ★★★.")
        elif df is not None and df > 0.5:
            L.append(f"- **drift 많음 ({df:.1%})** → retrieval-miss 숫자가 chunker rebuild artifact 로 부풀려짐. eval_summary↔index 동기화부터 재검토 필요.")
        else:
            L.append(f"- **drift 중간 ({df:.1%})** → retrieval-miss 일부는 진짜, 일부는 artifact. 두 신호 분리해 보고.")
    L.append("")
    L.append("## Honesty / caveats\n")
    L.append("- terms-test = `contains_all_terms` (substring AND, eval scorer 와 동일 함수). expected_terms 가 부분적이면 false drift 가능.")
    L.append("- 'annotation_valid' = gold chunk 에 답이 있는데 retrieval 이 못 가져옴 = 진짜 검색 실패 (또는 ranking 이 top_k 밖).")
    L.append("- 0 LLM call.")

    (out / "report.md").write_text("\n".join(L) + "\n")
    (out / "raw.json").write_text(json.dumps({"manifest": manifest, "rows": rows}, ensure_ascii=False, indent=2))
    print(f"Wrote: {out}/report.md", file=sys.stderr)
    print(f"n_miss={n}, genuine={genuine}, drift={drift}, stale={stale}, no_terms={no_terms}, "
          f"drift_frac_judgable={manifest['drift_fraction_of_judgable']}", file=sys.stderr)


if __name__ == "__main__":
    main()
