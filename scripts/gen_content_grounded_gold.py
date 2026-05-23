#!/usr/bin/env python3
"""Content-grounded gold generator (real-100 construct-validity fix, #1347).

The committed real-100 gold derives ``expected_terms`` from the
``data_list.csv`` catalog (budget/agency/deadline), but those surface forms are
largely absent from the indexed *body* text — capping accuracy regardless of
the pipeline (5-lever null cascade; see
``docs/audits/construct-validity-gold-grounding-inspection.md``). This generator
proposes single-fact cases whose ``expected_terms`` are *verbatim phrases from
the chunk body*, so the answer is genuinely retrievable and exact-match
scorable. Output is a reviewable yaml (ADR 0029 human-gate); deterministic,
no LLM.

Method per seed doc: pick a content chunk (skip TOC), enumerate sentences whose
content 2-gram is unique to exactly ONE doc, reject form/section boilerplate,
and emit the first acceptable verbatim phrase. The query is anchored on one
distinctive content keyword **without the project title** — the original pilot
embedded ``「{project}」`` which leaked the gold doc to the retriever; this
generator drops it so single_doc retrieval is a fair test.

Scope: the verbatim-phrase method is intrinsically single-fact / single_doc.
multi_hop / comparison / distractor difficulty arms need a different method and
are deferred to a follow-up (see audit Issue A note).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

TOKEN = re.compile(r"[가-힣A-Za-z0-9]{2,}")

# Common RFP scaffolding tokens — excluded from distinctive-bigram detection so
# anchors land on substantive content, not section headers.
STOP = {
    "사업", "제안", "요청", "제안요청서", "목차", "개요", "현황", "범위", "기대효과",
    "추진", "배경", "필요성", "관리", "시스템", "구축", "개발", "용역", "과업",
    "본문", "문서", "전체", "기관", "내용", "관련", "사항", "대한", "위한", "통한",
    # section-label / connective tokens — header-like, not substantive answers
    "일반", "일반사항", "사업명", "명칭", "기간", "일정", "장소", "방법", "조건",
    "목적", "정의", "구분", "절차", "기준", "단계", "결과", "효과", "따른", "따라",
    "위하여", "관하여", "경우", "다음", "아래", "해당", "이상", "이하", "이내",
}

# Form / section / procurement-boilerplate markers. A candidate phrase or anchor
# containing any of these is rejected — these are doc-unique bigrams that carry
# no substantive answer (e.g. attachment form names, scoring-table headers).
BOILERPLATE = {
    "별지", "별첨", "서식", "양식", "붙임", "첨부", "배점", "평가배점", "공동수급",
    "협정서", "이행방식", "분담이행", "낙찰", "입찰서", "산출내역", "내역서", "위임장",
    "인감", "청렴", "서약", "준수", "확약", "제출처", "접수처", "공고", "공고문",
    "유의사항", "가격", "총액", "단가", "견적", "페이지", "쪽", "항목", "표지",
    "여백", "세로방향", "가로방향", "줄간격", "글꼴", "폰트", "제출서류",
}


def content_tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text) if t not in STOP and not t.isdigit()]


def _has_boilerplate(s: str) -> bool:
    return any(b in s for b in BOILERPLATE)


_OCR_SPACING = re.compile(r"(?:[가-힣] ){2,}[가-힣]")


def _acceptable_anchor(anchor: str) -> bool:
    if _has_boilerplate(anchor):
        return False
    hangul = sum(1 for ch in anchor if "가" <= ch <= "힣")
    # Require a Korean content anchor (>=2 Hangul chars). ASCII-only anchors are
    # rejected — they are typically OCR/path artifacts (e.g. "gjlm"), not RFP
    # domain terms.
    return hangul >= 2


def _acceptable_phrase(phrase: str) -> bool:
    # Reject OCR-spaced runs ("사 업 명") and boilerplate-laden phrases.
    return not _has_boilerplate(phrase) and not _OCR_SPACING.search(phrase)


def distinctive_candidates(text: str, unique_bigrams: set[str]):
    """Yield (verbatim_phrase, anchor_keyword) for every sentence whose content
    2-gram is unique to this doc — caller picks the first acceptable one."""
    for sent in re.split(r"[\n。\.·•　]| {2,}", text):
        sent = sent.strip()
        if not (12 <= len(sent) <= 48):
            continue
        toks = content_tokens(sent)
        if len(toks) < 2:
            continue
        for i in range(len(toks) - 1):
            bg = toks[i] + " " + toks[i + 1]
            if bg in unique_bigrams:
                m = re.search(
                    re.escape(toks[i]) + r".{0,12}?" + re.escape(toks[i + 1]), sent
                )
                phrase = (m.group(0) if m else (toks[i] + " " + toks[i + 1])).strip()
                yield phrase, toks[i]


def generate_cases(chunks: list[dict], n: int) -> tuple[list[dict], int]:
    """Build content-grounded gold cases from index chunks.

    Returns ``(cases, skipped_boilerplate)``. Deterministic: docs are visited in
    sorted ``doc_id`` order. Each case's ``expected_terms[0]`` is a verbatim
    substring of its seed chunk text, and the query embeds only a distinctive
    content anchor — never the project title (no gold-doc leak)."""
    # bigrams unique to a single doc
    bigram_docs: dict[str, set[str]] = {}
    for c in chunks:
        doc = str(c.get("doc_id") or "")
        toks = content_tokens(str(c.get("text") or ""))
        for i in range(len(toks) - 1):
            bigram_docs.setdefault(toks[i] + " " + toks[i + 1], set()).add(doc)
    unique_bigrams = {bg for bg, docs in bigram_docs.items() if len(docs) == 1}

    # one chunk per doc (the longest non-TOC chunk)
    by_doc: dict[str, dict] = {}
    for c in chunks:
        doc = str(c.get("doc_id") or "")
        t = str(c.get("text") or "")
        if "목   차" in t or "목차" in t[:40]:
            continue
        if doc not in by_doc or len(t) > len(str(by_doc[doc].get("text") or "")):
            by_doc[doc] = c

    cases: list[dict] = []
    skipped_boilerplate = 0
    for doc, c in sorted(by_doc.items()):
        if len(cases) >= n:
            break
        phrase = anchor = None
        for cand_phrase, cand_anchor in distinctive_candidates(
            str(c.get("text") or ""), unique_bigrams
        ):
            if not _acceptable_phrase(cand_phrase) or not _acceptable_anchor(cand_anchor):
                skipped_boilerplate += 1
                continue
            phrase, anchor = cand_phrase, cand_anchor
            break
        if not phrase:
            continue
        cases.append(
            {
                "id": f"cg_{doc.replace('-', '_').replace('.', '_')}",
                # No project title in the query: avoid leaking the gold doc to
                # the retriever. The anchor is a distinctive content keyword.
                "query": f"'{anchor}' 관련 요구사항이나 설명을 문서에서 찾아 알려줘.",
                "query_type": "single_doc",
                "expected_doc_ids": [doc],
                "expected_terms": [phrase],
                "hardcase_categories": ["content_grounded"],
                "_provenance": "verbatim_chunk_phrase_v2",
            }
        )
    return cases, skipped_boilerplate


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--index-dir", default="data/index/real100")
    ap.add_argument("--out", default="reports/proposed/content_grounded_gold.local.yaml")
    ap.add_argument("--n", type=int, default=60)
    args = ap.parse_args()

    idx = json.loads(Path(args.index_dir, "index.json").read_text(encoding="utf-8"))
    cases, skipped_boilerplate = generate_cases(idx["chunks"], args.n)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        yaml.safe_dump({"cases": cases}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"wrote {len(cases)} content-grounded gold cases -> {out}")
    print(f"  (skipped {skipped_boilerplate} boilerplate candidates)")
    for c in cases[:8]:
        print(f"  {c['id']}: q={c['query'][:46]!r} term={c['expected_terms']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
