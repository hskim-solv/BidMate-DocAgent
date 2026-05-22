#!/usr/bin/env python3
"""Scorer surface-form mismatch diagnosis (READ-ONLY, 0 LLM).

The chunk-level gold survey found only 14/221 (6%) cases have a "clean"
substring-derivable gold set. Drilling into single_doc failures showed the
answer IS in the indexed document body, but written in a surface form the
substring scorer (`contains_all_terms`, used by BOTH gold derivation and the
eval groundedness scorer) cannot match:

  expected_term  '150,000,000원'   vs   doc text  '1억 5천만 원'
  expected_term  '2025-01-08'      vs   doc text  '2025. 1. 8.'

This script QUANTIFIES, with a numeric/date normalizer, how many
substring-FAILING expected_terms are actually present in the expected
document once Korean-myriad amounts and date separators are normalized.
That separates "scorer surface-form artifact" from genuine term absence
(textual terms that need a different fix).

No LLM calls. No estimates — every number is measured against the index text.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

_BIGS = {"억": 10**8, "만": 10**4}
_SMALLS = {"천": 10**3, "백": 10**2, "십": 10}
_AMOUNT_SPAN = re.compile(r"[\d억만천백십,\.\s]*[\d억만천백십]\s*원")
_DATE = re.compile(r"(\d{4})\D{0,3}?(\d{1,2})\D{0,3}?(\d{1,2})")


def kor_amount_to_int(s: str) -> int | None:
    """Parse Korean myriad or comma-grouped amount to int. None if unparseable."""
    s = s.replace(" ", "").replace(",", "").replace("원", "").replace("정", "")
    if not s:
        return None
    if not any(ch in s for ch in "억만천백십"):
        return int(s) if s.isdigit() else None
    total = section = num = 0
    for ch in s:
        if ch.isdigit():
            num = num * 10 + int(ch)
        elif ch in _SMALLS:
            section += (num if num else 1) * _SMALLS[ch]
            num = 0
        elif ch in _BIGS:
            section += num
            total += section * _BIGS[ch]
            section = num = 0
        else:
            return None  # stray char → give up (avoid false matches)
    return total + section + num


def amounts_in_text(text: str) -> set[int]:
    out: set[int] = set()
    for m in _AMOUNT_SPAN.finditer(text):
        v = kor_amount_to_int(m.group())
        if v is not None and v > 0:
            out.add(v)
    return out


def dates_in_text(text: str) -> set[tuple[int, int, int]]:
    out: set[tuple[int, int, int]] = set()
    for m in _DATE.finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 2000 <= y <= 2099 and 1 <= mo <= 12 and 1 <= d <= 31:
            out.add((y, mo, d))
    return out


def term_kind(t: str) -> str:
    if re.search(r"[0-9][0-9,]*\s*원", t) or ("원" in t and any(c.isdigit() for c in t)):
        return "amount"
    if re.fullmatch(r"\d{4}[-.\s]*\d{1,2}[-.\s]*\d{1,2}\.?", t.strip()):
        return "date"
    if any(c.isdigit() for c in t):
        return "other_numeric"
    return "textual"


def normalized_present(term: str, text: str, amt_set: set[int], date_set) -> bool:
    kind = term_kind(term)
    if kind == "amount":
        v = kor_amount_to_int(term)
        return v is not None and v in amt_set
    if kind == "date":
        m = _DATE.search(term)
        if not m:
            return False
        key = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return key in date_set
    return False  # other_numeric / textual: not handled by this normalizer


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="eval_summary.json")
    p.add_argument("--config", required=True)
    p.add_argument("--index", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--query-type", default="single_doc")
    args = p.parse_args()

    es = json.loads(Path(args.input).read_text())
    cfg = yaml.safe_load(Path(args.config).read_text())
    byid = {c.get("id"): c for c in (cfg.get("cases") or [])}
    idx = json.loads(Path(args.index).read_text())
    by_doc: dict[str, str] = {}
    for c in idx.get("chunks") or []:
        by_doc.setdefault(str(c.get("doc_id")), "")
        by_doc[str(c.get("doc_id"))] += " " + str(c.get("text") or "")

    crs = es.get("case_results") or []
    cases = crs if args.query_type == "all" else [c for c in crs if c.get("query_type") == args.query_type]

    kind_fail = Counter()
    kind_recovered = Counter()
    recovered_terms: list[tuple[str, str]] = []
    still_absent_textual: list[str] = []
    case_recover = Counter()  # how many cases flip all-numeric-terms recoverable

    for c in cases:
        cid = c.get("id")
        cc = byid.get(cid)
        if not cc:
            continue
        terms = cc.get("expected_terms") or []
        docs = [str(d) for d in (cc.get("expected_doc_ids") or [])]
        if not terms:
            continue
        text = " ".join(by_doc.get(d, "") for d in docs)
        low = text.lower()
        amt_set = amounts_in_text(text)
        date_set = dates_in_text(text)
        case_failing = [t for t in terms if t.lower() not in low]
        if not case_failing:
            continue
        for t in case_failing:
            k = term_kind(t)
            kind_fail[k] += 1
            if normalized_present(t, text, amt_set, date_set):
                kind_recovered[k] += 1
                if len(recovered_terms) < 40:
                    recovered_terms.append((t, k))
            elif k == "textual" and len(still_absent_textual) < 40:
                still_absent_textual.append(t)
        # case-level: did normalization recover ALL its failing numeric terms,
        # leaving only textual (or nothing)?
        numeric_fail = [t for t in case_failing if term_kind(t) != "textual"]
        numeric_rec = [t for t in numeric_fail if normalized_present(t, text, amt_set, date_set)]
        if numeric_fail and len(numeric_rec) == len(numeric_fail):
            case_recover["all_numeric_recovered"] += 1

    total_fail = sum(kind_fail.values())
    total_rec = sum(kind_recovered.values())

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "input": args.input, "config": args.config, "index": args.index,
        "query_type": args.query_type,
        "failing_terms_total": total_fail,
        "recovered_by_normalization": total_rec,
        "kind_fail": dict(kind_fail),
        "kind_recovered": dict(kind_recovered),
        "cases_all_numeric_recovered": case_recover.get("all_numeric_recovered", 0),
    }

    def pct(v, t):
        return f"{(v/t*100):.0f}%" if t else "—"

    L = []
    L.append("# Scorer surface-form mismatch diagnosis (READ-ONLY, 0 LLM)\n")
    L.append(f"- generated: {manifest['generated_at']}")
    L.append(f"- input: `{args.input}`")
    L.append(f"- index: `{args.index}`")
    L.append(f"- query_type: **{args.query_type}**")
    L.append("")
    L.append("## Substring-failing expected_terms — by kind, recovered by normalization\n")
    L.append("| kind | failing | recovered (normalized) | recover % | normalizer handles? |")
    L.append("|---|---|---|---|---|")
    for k in ("amount", "date", "other_numeric", "textual"):
        f = kind_fail.get(k, 0)
        r = kind_recovered.get(k, 0)
        handles = "yes" if k in ("amount", "date") else "no"
        L.append(f"| {k} | {f} | {r} | {pct(r, f)} | {handles} |")
    L.append(f"| **total** | **{total_fail}** | **{total_rec}** | {pct(total_rec, total_fail)} | |")
    L.append("")
    L.append(f"- cases where ALL substring-failing **numeric** terms become present after "
             f"normalization: **{manifest['cases_all_numeric_recovered']}**")
    L.append("")
    L.append("## 결론\n")
    L.append("- substring scorer (`contains_all_terms`) 가 못 잡는 expected_term 의 실패는 **두 갈래**:")
    L.append(f"  1. **숫자/날짜 표면형** (amount+date {kind_fail.get('amount',0)+kind_fail.get('date',0)}건): "
             f"한국식 만/억·날짜 구분자 정규화로 {kind_recovered.get('amount',0)+kind_recovered.get('date',0)}건 회복 — "
             "**scorer artifact (답은 본문에 있음)**")
    L.append(f"  2. **textual** ({kind_fail.get('textual',0)}건): 정규화 무관. expected_doc 오지정 / 동의어 / "
             "OCR 누락 / 진짜 부재 등 별도 원인 — 추가 조사 필요")
    L.append("- → 'verifier 30%' · chunk-level recall 수치는 (1) 만큼 **scorer 측정 오류로 부풀려진 실패**를 포함. "
             "숫자 정규화 레이어 (gold derivation + groundedness scorer 양쪽) 가 선결 과제.")
    L.append("")
    L.append("## Sample recovered (substring-absent → normalized-present)\n")
    for t, k in recovered_terms[:20]:
        L.append(f"- `{t}` ({k})")
    L.append("")
    L.append("## Sample still-absent textual (정규화로 안 풀림)\n")
    for t in still_absent_textual[:20]:
        L.append(f"- `{t}`")
    L.append("")
    L.append("## Honesty / caveats\n")
    L.append("- amount normalizer = Korean 억/만/천/백/십 + comma 파서. 텍스트의 amount-span 을 추출해 int 집합과 비교 (false-positive 회피 위해 stray char 시 포기).")
    L.append("- date = (Y,M,D) 튜플 비교, 2000–2099 / 1–12 / 1–31 범위 가드.")
    L.append("- other_numeric / textual 은 본 normalizer 범위 밖 — 'recovered' 0 으로 정직 보고.")
    L.append("- 0 LLM call. 모든 수치 index 본문 실측.")

    (out / "report.md").write_text("\n".join(L) + "\n")
    (out / "raw.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"Wrote: {out}/report.md", file=sys.stderr)
    print(f"failing={total_fail} recovered={total_rec} "
          f"(amount {kind_recovered.get('amount',0)}/{kind_fail.get('amount',0)}, "
          f"date {kind_recovered.get('date',0)}/{kind_fail.get('date',0)}), "
          f"cases_all_numeric_recovered={manifest['cases_all_numeric_recovered']}", file=sys.stderr)


if __name__ == "__main__":
    main()
