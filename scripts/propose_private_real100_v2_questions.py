#!/usr/bin/env python3
"""Generate a private real100_v2 RFP question draft plus aggregate summary.

The generated questions, gold evidence, and eval config are raw private eval
inputs and must stay under a gitignored directory. The optional aggregate JSON
contains only counts and closed labels so it can be committed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import json
from pathlib import Path
import re
import sys
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.private_data_quality_audit_utils import (  # noqa: E402
    assert_public_safe,
    gitignored_or_outside_repo,
    page_metadata_present,
)

SCHEMA_VERSION = 1
PROFILE_TYPE = "private_real100_v2_question_distribution"
DEFAULT_TARGETS = {
    "easy_sanity": 60,
    "standard_real": 150,
    "hard_stress": 90,
}

TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9_.-]{1,}")
DATE_RE = re.compile(
    r"(?:20\d{2}[./-]\d{1,2}[./-]\d{1,2}|20\d{2}\s*년\s*\d{1,2}\s*월(?:\s*\d{1,2}\s*일)?|\d{1,2}\s*월\s*\d{1,2}\s*일)"
)
AMOUNT_RE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:원|천원|만원|억원|%)|(?:예산|사업비|금액)")
SCORE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:점|%)|(?:배점|평가점수|정량|정성|기술평가|가격평가)")
TABLE_RE = re.compile(r"(<table\b|</t[dh]>|rowspan=|colspan=|\|[^\n]+\||\t)", re.IGNORECASE)
LOW_VALUE_TOKENS = {
    "사업",
    "제안",
    "요청",
    "제안요청서",
    "문서",
    "내용",
    "사항",
    "관련",
    "범위",
    "일반",
    "목차",
    "붙임",
    "별지",
    "서식",
    "양식",
    "페이지",
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _chunks(index: dict[str, Any]) -> list[dict[str, Any]]:
    return [chunk for chunk in index.get("chunks") or [] if isinstance(chunk, dict)]


def _doc_id(chunk: dict[str, Any]) -> str:
    return str(chunk.get("doc_id") or (chunk.get("metadata") or {}).get("doc_id") or "")


def _chunk_id(chunk: dict[str, Any]) -> str:
    return str(chunk.get("chunk_id") or "")


def _project(chunk: dict[str, Any]) -> str:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    return _compact(str(chunk.get("project") or metadata.get("project") or _doc_id(chunk)))


def _text(chunk: dict[str, Any]) -> str:
    return str(chunk.get("text") or "")


def _page_span(chunk: dict[str, Any]) -> list[int] | None:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    for node in (chunk, metadata):
        span = node.get("page_span")
        if isinstance(span, list) and span:
            try:
                start = int(span[0])
                end = int(span[-1])
                return [start, end]
            except (TypeError, ValueError):
                pass
        page = node.get("page") or node.get("page_number")
        if page not in (None, ""):
            try:
                parsed = int(page)
                return [parsed, parsed]
            except (TypeError, ValueError):
                pass
    return None


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _snippet(text: str, term: str, limit: int = 280) -> str:
    compact = _compact(text)
    pos = compact.find(term) if term else -1
    if pos < 0:
        return compact[:limit]
    start = max(0, pos - 90)
    end = min(len(compact), pos + len(term) + 160)
    return compact[start:end][:limit]


def _content_tokens(text: str) -> list[str]:
    tokens = []
    seen = set()
    for token in TOKEN_RE.findall(text):
        if token in LOW_VALUE_TOKENS or token.isdigit():
            continue
        if len(token) < 2:
            continue
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _first_match(regex: re.Pattern[str], text: str) -> str | None:
    match = regex.search(text)
    return _compact(match.group(0)) if match else None


def _table_marker_count(text: str) -> int:
    return len(TABLE_RE.findall(text or ""))


def _is_table_heavy_chunk(text: str) -> bool:
    lower = text.lower()
    if "<table" in lower or "rowspan=" in lower or "colspan=" in lower:
        return True
    return _table_marker_count(text) >= 5


def _anchor(text: str) -> str | None:
    for regex in (AMOUNT_RE, DATE_RE, SCORE_RE):
        match = _first_match(regex, text)
        if match and len(match) >= 2:
            return match
    tokens = _content_tokens(text)
    return tokens[0] if tokens else None


def _context_terms(text: str, *exclude: str | None, limit: int = 2) -> list[str]:
    excluded = {item for item in exclude if item}
    terms: list[str] = []
    for token in _content_tokens(text):
        if token in excluded:
            continue
        terms.append(token)
        if len(terms) >= limit:
            break
    return terms


def _with_context(base: str, text: str, term: str | None) -> str:
    terms = _context_terms(text, term, limit=2)
    if not term:
        return base
    if terms:
        joined = "', '".join([term, *terms])
        return f"문서에서 '{joined}' 단서가 함께 나오는 조건을 근거로 알려줘."
    return base


def _case_id(prefix: str, counter: int) -> str:
    return f"real100_v2_{prefix}_{counter:03d}"


def _evidence(case_id: str, chunk: dict[str, Any], support_type: str, term: str) -> dict[str, Any]:
    item = {
        "evidence_id": f"{case_id}_ev001",
        "question_id": case_id,
        "doc_id": _doc_id(chunk),
        "chunk_id": _chunk_id(chunk),
        "support_type": support_type,
        "support_text": _snippet(_text(chunk), term),
        "required_terms": [term] if term else [],
        "required": True,
    }
    span = _page_span(chunk)
    if span:
        item["page_span"] = span
    return item


def _question_row(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_id": case["id"],
        "question": case["query"],
        "answerable": case["answerable"],
        "query_type": case["query_type"],
        "difficulty_tier": case["difficulty_tier"],
        "question_type": case["question_type"],
        "expected_terms": case["expected_terms"],
        "hardcase_categories": case.get("hardcase_categories", []),
    }


def _gold_row(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_id": case["id"],
        "gold_evidence": case.get("gold_evidence", []),
    }


def _eval_case(case: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": case["id"],
        "query_type": case["query_type"],
        "query": case["query"],
        "expected_doc_ids": case.get("expected_doc_ids", []),
        "expected_terms": case["expected_terms"],
        "answerable": case["answerable"],
        "hardcase_categories": case.get("hardcase_categories", []),
        "gold_evidence": case.get("gold_evidence", []),
        "difficulty_tier": case["difficulty_tier"],
        "question_type": case["question_type"],
    }
    return payload


def _candidate_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            chunk
            for chunk in chunks
            if _doc_id(chunk) and _chunk_id(chunk) and len(_compact(_text(chunk))) >= 40
        ],
        key=lambda chunk: (_doc_id(chunk), _page_span(chunk) or [10**9, 10**9], _chunk_id(chunk)),
    )


def _make_easy(chunks: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen_docs: set[str] = set()
    for chunk in _candidate_chunks(chunks):
        if len(cases) >= limit:
            break
        text = _text(chunk)
        doc = _doc_id(chunk)
        if doc in seen_docs or _is_table_heavy_chunk(text):
            continue
        term = _anchor(text)
        if not term:
            continue
        case_id = _case_id("easy", len(cases) + 1)
        cases.append(
            {
                "id": case_id,
                "difficulty_tier": "easy_sanity",
                "question_type": "single_chunk_content_anchor",
                "query_type": "single_doc",
                "query": _with_context(
                    f"'{term}' 관련 요구사항이나 설명을 문서 근거로 알려줘.",
                    text,
                    term,
                ),
                "answerable": True,
                "expected_doc_ids": [doc],
                "expected_terms": [term],
                "hardcase_categories": [],
                "gold_evidence": [_evidence(case_id, chunk, "single_chunk", term)],
            }
        )
        seen_docs.add(doc)
    return cases


def _standard_kind(text: str) -> tuple[str, str | None, str]:
    amount = _first_match(AMOUNT_RE, text)
    if amount:
        return (
            "amount_extraction",
            amount,
            _with_context("금액/예산 관련 조건을 문서 근거로 알려줘.", text, amount),
        )
    date = _first_match(DATE_RE, text)
    if date:
        return (
            "date_extraction",
            date,
            _with_context("일정/마감 관련 조건을 문서 근거로 알려줘.", text, date),
        )
    score = _first_match(SCORE_RE, text)
    if score:
        return (
            "score_extraction",
            score,
            _with_context("평가점수/배점 관련 조건을 문서 근거로 알려줘.", text, score),
        )
    term = _anchor(text)
    return (
        "rfp_requirement",
        term,
        _with_context(f"'{term}' 관련 조건을 문서 근거로 알려줘.", text, term)
        if term
        else "",
    )


def _make_standard(chunks: list[dict[str, Any]], limit: int, exclude_ids: set[str]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    per_kind: Counter[str] = Counter()
    for chunk in _candidate_chunks(chunks):
        if len(cases) >= limit:
            break
        if _chunk_id(chunk) in exclude_ids:
            continue
        kind, term, prompt = _standard_kind(_text(chunk))
        if not term or not prompt:
            continue
        if per_kind[kind] > (limit // 3 + 8):
            continue
        case_id = _case_id("standard", len(cases) + 1)
        cases.append(
            {
                "id": case_id,
                "difficulty_tier": "standard_real",
                "question_type": kind,
                "query_type": "single_doc",
                "query": prompt,
                "answerable": True,
                "expected_doc_ids": [_doc_id(chunk)],
                "expected_terms": [term],
                "hardcase_categories": [],
                "gold_evidence": [_evidence(case_id, chunk, kind, term)],
            }
        )
        per_kind[kind] += 1
    return cases


def _make_hard_table(chunks: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for chunk in _candidate_chunks(chunks):
        if len(cases) >= limit:
            break
        text = _text(chunk)
        if not _is_table_heavy_chunk(text):
            continue
        term = _first_match(SCORE_RE, text) or _first_match(AMOUNT_RE, text) or _first_match(DATE_RE, text)
        if not term:
            continue
        kind = "table_heavy_score_or_amount"
        if len(DATE_RE.findall(text)) >= 3:
            kind = "schedule_or_gantt_like_table"
        case_id = _case_id("hard_table", len(cases) + 1)
        context = _with_context("표나 일정 형식의 근거에서 해당 수치/일정 조건을 정확히 알려줘.", text, term)
        cases.append(
            {
                "id": case_id,
                "difficulty_tier": "hard_stress",
                "question_type": kind,
                "query_type": "single_doc",
                "query": f"표나 일정 형식의 근거에서 {context}",
                "answerable": True,
                "expected_doc_ids": [_doc_id(chunk)],
                "expected_terms": [term],
                "hardcase_categories": ["table_heavy"],
                "gold_evidence": [_evidence(case_id, chunk, kind, term)],
            }
        )
    return cases


def _make_hard_multichunk(chunks: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in _candidate_chunks(chunks):
        by_doc[_doc_id(chunk)].append(chunk)
    for doc, doc_chunks in sorted(by_doc.items()):
        if len(cases) >= limit:
            break
        usable = []
        for chunk in doc_chunks:
            term = _anchor(_text(chunk))
            if term:
                usable.append((chunk, term))
        if len(usable) < 2:
            continue
        left, right = usable[0], usable[-1]
        if _chunk_id(left[0]) == _chunk_id(right[0]):
            continue
        case_id = _case_id("hard_multi", len(cases) + 1)
        cases.append(
            {
                "id": case_id,
                "difficulty_tier": "hard_stress",
                "question_type": "multi_chunk_same_doc",
                "query_type": "single_doc",
                "query": f"'{left[1]}' 조건과 '{right[1]}' 조건을 모두 찾아 함께 정리해줘.",
                "answerable": True,
                "expected_doc_ids": [doc],
                "expected_terms": [left[1], right[1]],
                "hardcase_categories": ["multi_chunk"],
                "gold_evidence": [
                    _evidence(f"{case_id}_a", left[0], "multi_chunk", left[1]),
                    _evidence(f"{case_id}_b", right[0], "multi_chunk", right[1]),
                ],
            }
        )
        for item in cases[-1]["gold_evidence"]:
            item["question_id"] = case_id
    return cases


def _make_hard_comparison(chunks: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    buckets: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
    for chunk in _candidate_chunks(chunks):
        kind, term, _prompt = _standard_kind(_text(chunk))
        if kind in {"amount_extraction", "date_extraction", "score_extraction"} and term:
            buckets[kind].append((chunk, term))
    labels = {
        "amount_extraction": "금액/예산",
        "date_extraction": "일정/마감",
        "score_extraction": "평가점수/배점",
    }
    for kind, items in sorted(buckets.items()):
        if len(cases) >= limit:
            break
        seen_pairs: set[tuple[str, str]] = set()
        for idx, left in enumerate(items):
            if len(cases) >= limit:
                break
            for right in items[idx + 1 :]:
                left_doc = _doc_id(left[0])
                right_doc = _doc_id(right[0])
                if not left_doc or not right_doc or left_doc == right_doc:
                    continue
                pair = tuple(sorted([left_doc, right_doc]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                case_id = _case_id("hard_compare", len(cases) + 1)
                left_project = _project(left[0])
                right_project = _project(right[0])
                cases.append(
                    {
                        "id": case_id,
                        "difficulty_tier": "hard_stress",
                        "question_type": f"multi_doc_{kind}",
                        "query_type": "comparison",
                        "query": (
                            f"'{left_project}' 문서와 '{right_project}' 문서의 "
                            f"{labels[kind]} 조건을 각각 비교해줘."
                        ),
                        "answerable": True,
                        "expected_doc_ids": [left_doc, right_doc],
                        "expected_terms": [left[1], right[1]],
                        "hardcase_categories": ["multi_doc", "comparison"],
                        "gold_evidence": [
                            _evidence(f"{case_id}_a", left[0], "multi_doc", left[1]),
                            _evidence(f"{case_id}_b", right[0], "multi_doc", right[1]),
                        ],
                    }
                )
                for item in cases[-1]["gold_evidence"]:
                    item["question_id"] = case_id
                break
    return cases


def _make_unanswerable(chunks: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen_docs: set[str] = set()
    templates = (
        "문서에 특정 상용 제품명과 라이선스 단가가 모두 명시되어 있는지 알려줘.",
        "문서에 자동 갱신 이후의 연도별 유지보수 단가 산식이 명시되어 있는지 알려줘.",
        "문서에 제안사가 반드시 사용해야 하는 특정 OCR/AI 모델 제품명이 명시되어 있는지 알려줘.",
    )
    for chunk in _candidate_chunks(chunks):
        if len(cases) >= limit:
            break
        doc = _doc_id(chunk)
        if doc in seen_docs:
            continue
        anchor = _anchor(_text(chunk)) or "해당 사업"
        context = _context_terms(_text(chunk), anchor, limit=1)
        context_text = f"와 '{context[0]}'" if context else ""
        case_id = _case_id("hard_abs", len(cases) + 1)
        cases.append(
            {
                "id": case_id,
                "difficulty_tier": "hard_stress",
                "question_type": "unanswerable_absence",
                "query_type": "abstention",
                "query": (
                    f"문서에서 '{anchor}'{context_text} 단서와 함께 "
                    f"{templates[len(cases) % len(templates)]}"
                ),
                "answerable": False,
                "expected_doc_ids": [],
                "expected_terms": [],
                "hardcase_categories": ["unanswerable"],
                "gold_evidence": [],
            }
        )
        seen_docs.add(doc)
    return cases


def generate_question_set(
    index: dict[str, Any],
    *,
    targets: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    chunks = _chunks(index)
    target = dict(DEFAULT_TARGETS if targets is None else targets)
    easy = _make_easy(chunks, target.get("easy_sanity", 0))
    used = {
        item.get("chunk_id")
        for case in easy
        for item in case.get("gold_evidence", [])
        if item.get("chunk_id")
    }
    standard = _make_standard(chunks, target.get("standard_real", 0), set(used))
    hard_target = target.get("hard_stress", 0)
    hard_table = _make_hard_table(chunks, max(0, hard_target * 25 // 100))
    hard_multi = _make_hard_multichunk(chunks, max(0, hard_target * 30 // 100))
    hard_compare = _make_hard_comparison(chunks, max(0, hard_target * 15 // 100))
    hard_unanswerable = _make_unanswerable(
        chunks,
        max(0, hard_target - len(hard_table) - len(hard_multi) - len(hard_compare)),
    )
    return [*easy, *standard, *hard_table, *hard_multi, *hard_compare, *hard_unanswerable]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _aggregate(cases: list[dict[str, Any]], targets: dict[str, int]) -> dict[str, Any]:
    tier_counts = Counter(str(case["difficulty_tier"]) for case in cases)
    type_counts = Counter(str(case["question_type"]) for case in cases)
    query_counts = Counter(str(case["query_type"]) for case in cases)
    hard_counts: Counter[str] = Counter()
    evidence_counts: Counter[str] = Counter()
    question_text_counts = Counter(str(case.get("query") or "") for case in cases)
    for case in cases:
        for category in case.get("hardcase_categories", []):
            hard_counts[str(category)] += 1
        evidence_count = len(case.get("gold_evidence", []))
        if not case.get("answerable"):
            evidence_counts["unanswerable_no_gold"] += 1
        elif evidence_count == 1:
            evidence_counts["single_chunk"] += 1
        elif evidence_count > 1:
            evidence_counts["multi_chunk"] += 1
    answerable = sum(1 for case in cases if case.get("answerable"))
    aggregate = {
        "schema_version": SCHEMA_VERSION,
        "profile_type": PROFILE_TYPE,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "recommended_case_count": sum(DEFAULT_TARGETS.values()),
        "target_distribution": targets,
        "actual_distribution": dict(sorted(tier_counts.items())),
        "generated_case_count": len(cases),
        "answerability": {
            "answerable": answerable,
            "unanswerable": len(cases) - answerable,
        },
        "query_type_distribution": dict(sorted(query_counts.items())),
        "question_type_distribution": dict(sorted(type_counts.items())),
        "hardcase_category_distribution": dict(sorted(hard_counts.items())),
        "evidence_cardinality_distribution": dict(sorted(evidence_counts.items())),
        "question_text_uniqueness": {
            "unique_question_texts": len(question_text_counts),
            "duplicate_question_texts": sum(1 for count in question_text_counts.values() if count > 1),
            "max_same_question_text_count": max(question_text_counts.values() or [0]),
        },
        "comparison_protocol": {
            "report_overall_and_each_tier": True,
            "explain_regressions_by_tier": True,
            "interpretation_not_cherry_picking": True,
        },
        "privacy": {
            "aggregate_only": True,
            "raw_questions_omitted": True,
            "raw_answers_omitted": True,
            "raw_evidence_omitted": True,
            "raw_text_omitted": True,
            "doc_ids_omitted": True,
            "chunk_ids_omitted": True,
            "filenames_omitted": True,
            "paths_omitted": True,
        },
    }
    assert_public_safe(aggregate)
    return aggregate


def _eval_config(cases: list[dict[str, Any]], index_dir: str) -> dict[str, Any]:
    return {
        "mode": "rag",
        "description": "Local-only real100_v2 private RFP eval draft. Do not commit.",
        "index_dir": index_dir,
        "answer_policy": {
            "answerable_status": "supported",
            "unanswerable_status": "insufficient",
            "min_claims_answerable": 1,
            "require_claim_citations": True,
        },
        "ablation_runs": [
            {
                "name": "full",
                "metadata_first": True,
                "rerank": True,
                "verifier_retry": True,
                "retrieval_mode": "flat",
            }
        ],
        "primary_run": "full",
        "cases": [_eval_case(case) for case in cases],
    }


def write_outputs(
    cases: list[dict[str, Any]],
    *,
    out_dir: Path,
    aggregate_path: Path | None,
    eval_config_path: Path | None,
    index_dir_label: str,
    targets: dict[str, int],
) -> dict[str, Any] | None:
    if not gitignored_or_outside_repo(out_dir, ROOT):
        raise ValueError("--out-dir must be gitignored or outside the repository")
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out_dir / "questions.jsonl", [_question_row(case) for case in cases])
    _write_jsonl(out_dir / "gold_evidence.jsonl", [_gold_row(case) for case in cases])
    (out_dir / "cases.local.yaml").write_text(
        yaml.safe_dump({"cases": [_eval_case(case) for case in cases]}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    if eval_config_path:
        if not gitignored_or_outside_repo(eval_config_path, ROOT):
            raise ValueError("--out-eval-config must be gitignored or outside the repository")
        eval_config_path.parent.mkdir(parents=True, exist_ok=True)
        eval_config_path.write_text(
            yaml.safe_dump(_eval_config(cases, index_dir_label), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    aggregate = _aggregate(cases, targets)
    if aggregate_path:
        aggregate_path.parent.mkdir(parents=True, exist_ok=True)
        aggregate_path.write_text(
            json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return aggregate


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--out-aggregate", type=Path)
    parser.add_argument("--out-eval-config", type=Path)
    parser.add_argument("--index-dir-label", default="data/index/real100_v2")
    parser.add_argument("--easy", type=int, default=DEFAULT_TARGETS["easy_sanity"])
    parser.add_argument("--standard", type=int, default=DEFAULT_TARGETS["standard_real"])
    parser.add_argument("--hard", type=int, default=DEFAULT_TARGETS["hard_stress"])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        index = _load_json(args.index)
        targets = {
            "easy_sanity": args.easy,
            "standard_real": args.standard,
            "hard_stress": args.hard,
        }
        cases = generate_question_set(index, targets=targets)
        aggregate = write_outputs(
            cases,
            out_dir=args.out_dir,
            aggregate_path=args.out_aggregate,
            eval_config_path=args.out_eval_config,
            index_dir_label=args.index_dir_label,
            targets=targets,
        )
    except Exception as exc:
        print(f"[ERROR] real100_v2 question proposal failed: {exc}", file=sys.stderr)
        return 2
    tier_counts = (aggregate or {}).get("actual_distribution", {})
    print(
        "[OK] generated private real100_v2 question draft:",
        f"cases={len(cases)}",
        f"tiers={tier_counts}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
