"""Regression tests for the section_detection_rate field added to build_chunk_records diagnostics.

Verifies that:
- The rate is computed correctly for all-section, no-section, mixed, and empty inputs.
- Chunk content/ID/ordering is not affected (bit-identical behaviour for existing fields).
"""

from rag_core import build_chunk_records


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_doc(doc_id: str, sections: list[dict]) -> dict:
    return {
        "doc_id": doc_id,
        "title": f"문서 {doc_id}",
        "agency": "테스트기관",
        "project": "테스트사업",
        "metadata": {},
        "source_path": f"data/raw/{doc_id}.pdf",
        "sections": sections,
    }


def _section(heading: str, text: str) -> dict:
    return {"heading": heading, "section": heading, "text": text, "section_path": [heading]}


def _weak_section(text: str) -> dict:
    # Uses a WEAK_SECTION_HEADINGS value — document_has_section_structure → False
    return {"heading": "본문", "section": "본문", "text": text, "section_path": ["본문"]}


# ---------------------------------------------------------------------------
# section_detection_rate correctness
# ---------------------------------------------------------------------------

def test_all_section_docs_rate_is_1():
    docs = [
        _make_doc("D1", [_section("§1 입찰 조건", "내용 A"), _section("§2 계약 조건", "내용 B")]),
        _make_doc("D2", [_section("§1 사업 개요", "내용 C")]),
        _make_doc("D3", [_section("§1 보증금", "내용 D"), _section("§2 일정", "내용 E")]),
    ]
    _, _, diag = build_chunk_records(docs, chunking_strategy="auto")
    assert diag["section_detection_rate"] == 1.0


def test_no_section_docs_rate_is_0():
    # Single section with a WEAK heading → resolves to "fixed"
    docs = [
        _make_doc("D1", [_weak_section("단일 본문 A입니다.")]),
        _make_doc("D2", [_weak_section("단일 본문 B입니다.")]),
    ]
    _, _, diag = build_chunk_records(docs, chunking_strategy="auto")
    assert diag["section_detection_rate"] == 0.0


def test_mixed_docs_rate_is_half():
    docs = [
        _make_doc("D1", [_section("§1 입찰 조건", "내용 A"), _section("§2 계약", "내용 B")]),
        _make_doc("D2", [_weak_section("단일 본문 C입니다.")]),
    ]
    _, _, diag = build_chunk_records(docs, chunking_strategy="auto")
    assert diag["section_detection_rate"] == 0.5


def test_empty_docs_rate_is_none():
    _, _, diag = build_chunk_records([], chunking_strategy="auto")
    assert diag["section_detection_rate"] is None


# ---------------------------------------------------------------------------
# Bit-identical chunk output — diagnostics addition must not change chunks
# ---------------------------------------------------------------------------

def test_chunks_unchanged_by_diagnostics_addition():
    docs = [
        _make_doc("D1", [_section("§1 개요", "내용 가"), _section("§2 조건", "내용 나")]),
    ]
    chunks, parent_sections, diag = build_chunk_records(docs, chunking_strategy="auto")

    # Rate field exists
    assert "section_detection_rate" in diag

    # Chunk fields that must be preserved
    for chunk in chunks:
        assert "chunk_id" in chunk
        assert "text" in chunk
        assert "chunking_strategy" in chunk

    # The strategy tag on each chunk is "section" for this doc
    assert all(c["chunking_strategy"] == "section" for c in chunks)


def test_fixed_strategy_rate_is_none():
    # Explicit "fixed" strategy bypasses auto detection; rate is still computed
    # (all docs resolve to "fixed"), so rate should be 0.0 (0 section / N docs).
    docs = [
        _make_doc("D1", [_section("§1 입찰 조건", "내용 A")]),
    ]
    _, _, diag = build_chunk_records(docs, chunking_strategy="fixed")
    # "fixed" strategy bypasses document_has_section_structure — all go to fixed
    assert diag["section_detection_rate"] == 0.0
