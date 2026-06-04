"""Unit coverage for rag_metadata_processing.py 청킹/parent-section 순수 helper (issue #2306).

``split_section_text`` 와 ``fixed_parent_section`` 은 import-safe(torch/chromadb/
rag_core 미로드) leaf 로직인데 직접 단위 테스트가 0건이었다(test-only, 소스 무수정).

핵심 변별:
- ``split_section_text`` overlap sliding — overlap=1 이면 청크 경계마다 이전 마지막
  문장을 재포함(sliding window), overlap=0 이면 비재포함. overlap 로직을 죽이면
  두 결과가 같아져 KILL.
- ``fixed_parent_section`` WEAK heading — heading 이 ``WEAK_SECTION_HEADINGS`` 면
  text 만, 아니면 ``heading\ntext``. WEAK 체크를 죽이면 heading 이 본문에 새어 KILL.
"""
from __future__ import annotations

from typing import Any

from rag_metadata_processing import (
    WEAK_SECTION_HEADINGS,
    fixed_parent_section,
    split_section_text,
)


# ---- split_section_text ----

def test_split_single_chunk_for_short_text() -> None:
    # max_chars 안에 들어오면 한 청크 안에 한 문장.
    assert split_section_text("짧다.", 100, 0) == [["짧다."]]


def test_split_empty_text_yields_single_empty_sentence_chunk() -> None:
    # sentence_split("") 는 [] → ``or [text]`` 로 [""] 가 되어 빈 문장 한 청크.
    assert split_section_text("", 100, 0) == [[""]]


def test_split_packs_sentences_up_to_max_chars() -> None:
    # 각 "가."=2자, max_chars=7: 한 청크에 두 문장(2+1+2+1=6<=7)까지 채우고 분할.
    out = split_section_text("가. 나. 다. 라.", 7, 0)
    assert out == [["가.", "나."], ["다.", "라."]]
    # overlap=0 이므로 분할 경계에서 이전 문장을 재포함하지 않는다.
    assert out[1][0] == "다."


def test_split_overlap_reincludes_previous_sentence() -> None:
    # 핵심 변별: 같은 입력·max_chars 라도 overlap=1 이면 sliding window 로 청크가 늘고
    # 각 청크 첫 문장이 직전 청크의 마지막 문장과 같아진다(재포함).
    base = "가. 나. 다. 라."
    no_overlap = split_section_text(base, 7, 0)
    with_overlap = split_section_text(base, 7, 1)
    assert no_overlap == [["가.", "나."], ["다.", "라."]]
    assert with_overlap == [["가.", "나."], ["나.", "다."], ["다.", "라."]]
    # overlap 로직이 죽으면 두 결과가 같아진다 → KILL.
    assert with_overlap != no_overlap
    assert len(with_overlap) == 3
    # sliding: 각 후속 청크의 첫 문장 == 직전 청크의 마지막 문장.
    assert with_overlap[1][0] == with_overlap[0][-1] == "나."
    assert with_overlap[2][0] == with_overlap[1][-1] == "다."


def test_split_force_splits_long_sentence_and_pushes_oversize_single() -> None:
    # 한 문장(11자)이 max_chars(4)를 넘으면 split_long_text_unit 으로 4자씩 강제분할,
    # 빈 current 일 때는 max_chars 초과여도 단독 청크로 push(무한루프 방지).
    out = split_section_text("가" * 10 + ".", 4, 0)
    assert out == [["가가가가"], ["가가가가"], ["가가."]]
    # 각 조각은 별도 청크 — 어느 청크도 두 조각을 묶지 않는다.
    assert all(len(chunk) == 1 for chunk in out)


def test_split_packs_at_exact_max_chars_boundary() -> None:
    # 경계: 가.(2)+sep(1)+나.(2)+sep(1)=6 == max_chars. 패킹 guard 가 ``>`` 이므로
    # 동률은 분할하지 않고 한 청크에 둘 다 — ``>=`` 로 바뀌면 분할되어 KILL.
    assert split_section_text("가. 나.", 6, 0) == [["가.", "나."]]


def test_split_overlap_reincludes_at_exact_fit_boundary() -> None:
    # 경계: overlap "나."(ol_len=3) + 다.(2) + sep(1) = 6 == max_chars. 재포함 fit 비교가
    # ``<=`` 이므로 동률에서 재포함 — ``<`` 로 바뀌면 재포함이 빠져 [["다."]] 가 되어 KILL.
    assert split_section_text("가. 나. 다.", 6, 1) == [["가.", "나."], ["나.", "다."]]


def test_split_separator_counts_toward_max_chars() -> None:
    # 누적 길이는 문장 사이 separator 1자를 포함(``len(sentence)+1``). aa.(3)+sep(1)+bb.(3)=7
    # 은 max_chars=7 을 넘기지 않지만, 다음 문장을 더하면 넘어 한 문장씩 분리된다.
    # ``+1`` 을 빼면 동률 누적이라 한 청크에 다 들어가 KILL.
    assert split_section_text("aa. bb. cc.", 7, 0) == [["aa."], ["bb."], ["cc."]]


# ---- fixed_parent_section ----

def _doc() -> dict[str, Any]:
    return {"doc_id": "D1", "title": "T", "agency": "AG", "project": "PJ", "metadata": {"k": "v"}}


def test_parent_merges_sections_with_fixed_identity_fields() -> None:
    sections = [
        {"section": "개요", "text": "본문1", "regions": [], "page_span": [1, 1]},
        {"section": "본문", "text": "본문2", "regions": [], "page_span": [2, 2]},
    ]
    parent = fixed_parent_section(_doc(), sections)
    # 고정 identity — section_id 접미사·"문서 전체" 라벨·section_path 단일 원소.
    assert parent["section_id"] == "D1::section-001"
    assert parent["section"] == "문서 전체"
    assert parent["heading"] == "문서 전체"
    assert parent["section_path"] == ["문서 전체"]
    # doc 메타 전파.
    assert parent["doc_id"] == "D1"
    assert parent["agency"] == "AG"
    assert parent["project"] == "PJ"
    assert parent["metadata"] == {"k": "v"}


def test_parent_weak_heading_drops_heading_keeps_text() -> None:
    # 핵심 변별: "본문" 은 WEAK → text 만, "개요" 는 non-WEAK → "개요\n본문1".
    assert "본문" in WEAK_SECTION_HEADINGS
    assert "개요" not in WEAK_SECTION_HEADINGS
    sections = [
        {"section": "개요", "text": "본문1", "regions": [], "page_span": [1, 1]},
        {"section": "본문", "text": "본문2", "regions": [], "page_span": [2, 2]},
    ]
    text = fixed_parent_section(_doc(), sections)["text"]
    assert text == "개요\n본문1\n\n본문2"
    # WEAK 체크가 죽어 "본문" heading 을 붙이면 이 형태가 나온다 → KILL.
    assert "본문\n본문2" not in text
    # non-WEAK heading 은 살아 있어야 한다.
    assert "개요\n본문1" in text


def test_parent_aggregates_page_span_min_max() -> None:
    # 여러 section 의 page_span 을 [min, max] 로 집계(겹치고 역순이어도).
    sections = [
        {"section": "a", "text": "x", "page_span": [2, 4]},
        {"section": "b", "text": "y", "page_span": [1, 3]},
    ]
    assert fixed_parent_section(_doc(), sections)["page_span"] == [1, 4]


def test_parent_regions_fallback_page_span_from_regions() -> None:
    # page_span 미제공 + regions 의 page_number 만 있을 때 regions 에서 fallback.
    sections = [{"section": "개요", "text": "T1", "regions": [{"page_number": 5, "bbox": [0, 0, 1, 1]}]}]
    parent = fixed_parent_section(_doc(), sections)
    assert parent["page_span"] == [5, 5]
    assert "regions" in parent
    assert parent["regions"] == [{"page_number": 5, "bbox": [0, 0, 1, 1]}]


def test_parent_omits_regions_key_when_no_regions() -> None:
    # regions 가 전부 비면 'regions' 키 자체를 넣지 않는다.
    parent = fixed_parent_section(_doc(), [{"section": "개요", "text": "T", "regions": []}])
    assert "regions" not in parent


def test_parent_filters_empty_parts_and_applies_doc_defaults() -> None:
    # 빈 heading→text만, heading 있고 text 빈 경우 "heading\n" 잔존(빈 part 아님),
    # 그리고 doc 에 agency/metadata 없으면 기본값('' / {}).
    sections = [
        {"section": "", "text": "A"},
        {"section": "개요", "text": ""},
        {"section": "결론", "text": "C"},
    ]
    parent = fixed_parent_section({"doc_id": "D", "title": "X"}, sections)
    assert parent["text"] == "A\n\n개요\n\n\n결론\nC"
    assert parent["agency"] == ""
    assert parent["project"] == ""
    assert parent["metadata"] == {}


def test_parent_drops_interior_empty_part() -> None:
    # 가운데 section 이 WEAK heading("본문") + 빈 text → part 가 "" 가 된다. ``if part``
    # 필터가 이를 제거해야 "A\n\nB"; 필터를 빼면 "A\n\n\n\nB"(이중 빈 줄) 가 되어 KILL.
    sections = [
        {"section": "", "text": "A"},
        {"section": "본문", "text": ""},
        {"section": "", "text": "B"},
    ]
    assert fixed_parent_section(_doc(), sections)["text"] == "A\n\nB"


def test_parent_strips_trailing_newline_from_last_empty_text_heading() -> None:
    # 마지막 section 이 non-WEAK heading("개요") + 빈 text → part "개요\n" 로 join 결과가
    # "\n" 으로 끝난다. 바깥 ``.strip()`` 이 이를 제거해야 한다 — strip 제거 시 KILL.
    sections = [{"section": "결론", "text": "C"}, {"section": "개요", "text": ""}]
    assert fixed_parent_section(_doc(), sections)["text"] == "결론\nC\n\n개요"
