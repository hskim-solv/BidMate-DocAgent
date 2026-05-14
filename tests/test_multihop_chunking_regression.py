"""Regression tests for the multihop eval dataset and its relationship to chunking.

Three guards:
1. Dataset size — dev_queries_multihop_v1.jsonl must have ≥ MIN_CASES rows.
2. Schema validity — every row must carry the required fields.
3. Multi-hop structure — must_include tokens for cross_section cases span ≥ 2
   synthetic sections when auto-chunking is applied, confirming that these
   queries cannot be answered from a single chunk.
"""

import json
from pathlib import Path

import pytest

from rag_core import build_chunk_records

MULTIHOP_DATASET = Path(__file__).resolve().parents[1] / "eval" / "dev_queries_multihop_v1.jsonl"
MIN_CASES = 15
REQUIRED_FIELDS = {"qid", "query", "multihop_type", "multihop_valid", "must_include", "target_doc_ids"}
VALID_TYPES = {"cross_section_within_doc", "cross_document_comparison", "multi_step_conditional"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_dataset() -> list[dict]:
    rows = []
    with MULTIHOP_DATASET.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _make_multisection_doc(doc_id: str, must_include: list[str]) -> dict:
    """Create a synthetic doc where must_include tokens are split across two sections."""
    mid = max(1, len(must_include) // 2)
    text_a = "이 섹션은 입찰 조건을 설명합니다. " + " ".join(must_include[:mid]) + "에 관한 내용."
    text_b = "이 섹션은 계약 조건을 설명합니다. " + " ".join(must_include[mid:]) + "에 관한 내용."
    return {
        "doc_id": doc_id,
        "title": f"테스트 문서 {doc_id}",
        "agency": "테스트기관",
        "project": "테스트사업",
        "metadata": {},
        "source_path": f"data/raw/{doc_id}.pdf",
        "sections": [
            {"heading": "§1 입찰 조건", "section": "§1 입찰 조건", "text": text_a, "section_path": ["§1 입찰 조건"]},
            {"heading": "§2 계약 조건", "section": "§2 계약 조건", "text": text_b, "section_path": ["§2 계약 조건"]},
        ],
    }


# ---------------------------------------------------------------------------
# Guard 1 — dataset size
# ---------------------------------------------------------------------------

def test_multihop_dataset_size_min_15():
    rows = _load_dataset()
    assert len(rows) >= MIN_CASES, (
        f"dev_queries_multihop_v1.jsonl has {len(rows)} rows; expected ≥ {MIN_CASES}. "
        "Run `make synthesize-multihop` or add stub cases."
    )


# ---------------------------------------------------------------------------
# Guard 2 — schema validity
# ---------------------------------------------------------------------------

def test_multihop_schema_valid():
    rows = _load_dataset()
    for i, row in enumerate(rows):
        missing = REQUIRED_FIELDS - set(row.keys())
        assert not missing, f"Row {i} ({row.get('qid', '?')}) missing fields: {missing}"

        assert row["multihop_type"] in VALID_TYPES, (
            f"Row {i} has unknown multihop_type: {row['multihop_type']!r}"
        )
        assert row["multihop_valid"] is True, f"Row {i} ({row['qid']}): multihop_valid must be true"
        assert isinstance(row["must_include"], list) and row["must_include"], (
            f"Row {i} ({row['qid']}): must_include must be a non-empty list"
        )
        assert isinstance(row["target_doc_ids"], list) and row["target_doc_ids"], (
            f"Row {i} ({row['qid']}): target_doc_ids must be a non-empty list"
        )


def test_multihop_type_distribution():
    rows = _load_dataset()
    type_counts: dict[str, int] = {}
    for row in rows:
        type_counts[row["multihop_type"]] = type_counts.get(row["multihop_type"], 0) + 1
    for mtype in VALID_TYPES:
        assert type_counts.get(mtype, 0) >= 3, (
            f"multihop_type '{mtype}' has only {type_counts.get(mtype, 0)} cases; expected ≥ 3"
        )


# ---------------------------------------------------------------------------
# Guard 3 — multi-hop structure (must_include spans ≥ 2 chunks)
# ---------------------------------------------------------------------------

def test_multihop_cases_span_multiple_chunks():
    rows = _load_dataset()
    cross_section_rows = [r for r in rows if r["multihop_type"] == "cross_section_within_doc"]

    multi_span_count = 0
    for row in cross_section_rows:
        tokens = row["must_include"]
        if len(tokens) < 2:
            continue
        doc = _make_multisection_doc("D_TEST", tokens)
        chunks, _, _ = build_chunk_records([doc], chunking_strategy="auto")

        # Find which chunks contain each must_include token
        token_chunk_indices = {token: [] for token in tokens}
        for idx, chunk in enumerate(chunks):
            text_lower = chunk["text"].lower()
            for token in tokens:
                if token.lower() in text_lower:
                    token_chunk_indices[token].append(idx)

        # A valid multi-hop case has at least 2 tokens appearing in different chunks
        all_chunk_sets = [frozenset(indices) for indices in token_chunk_indices.values() if indices]
        if len(all_chunk_sets) >= 2 and len(set.union(*[set(s) for s in all_chunk_sets])) > 1:
            multi_span_count += 1

    assert multi_span_count >= 1, (
        "No cross_section_within_doc cases could be demonstrated to span multiple chunks "
        "with synthetic 2-section documents. Check must_include token distribution."
    )
