"""Unit coverage for ``rag_indexing.make_chunk`` chunk-record construction.

``make_chunk`` 는 ``build_chunk_records`` 가 청크마다 호출하는 순수 빌더로,
parent section + 문장 리스트 + 위치 인덱스로부터 ADR 0003 인덱스 레코드 dict 를
조립한다. 직접 단위 테스트가 없어 다음을 oracle 로 고정한다:

- ``chunk_id`` zero-pad 포맷과 ``section_id``/``parent_section_id`` 전파
- ``text`` join+strip(빈 리스트 → 빈 문자열)
- ``section``/``section_path`` fallback 사슬
- ``chunker_version`` 의 전략별/contextual 분기
- ``contextual`` 플래그에 따른 ``contextual_prefix`` 조건부 키와 'body' fallback
- doc 필드 기본값과 regions/page_span 조건부 키 부재

normalize_regions/normalize_page_span 의 내부 정규화는 별도 concern 이므로
여기선 "parent 에 없으면 키가 붙지 않는다" 경로만 고정한다.
모든 기대값은 소스 실행으로 캡처했다.
"""

from __future__ import annotations

from rag_indexing import make_chunk


def _doc() -> dict:
    return {
        "doc_id": "rfp1",
        "title": "조달 RFP",
        "agency": "조달청",
        "project": "P",
        "metadata": {"k": "v"},
    }


def _parent() -> dict:
    return {
        "section_id": "rfp1::section-002",
        "section": "사업 범위",
        "section_path": ["사업 범위"],
    }


def test_chunk_id_uses_three_digit_zero_padded_sequence() -> None:
    assert make_chunk(_doc(), _parent(), ["t"], 7, 1, 1, "section")["chunk_id"] == "rfp1::chunk-007"
    assert make_chunk(_doc(), _parent(), ["t"], 42, 1, 1, "section")["chunk_id"] == "rfp1::chunk-042"


def test_section_id_and_parent_section_id_both_taken_from_parent() -> None:
    chunk = make_chunk(_doc(), _parent(), ["t"], 1, 1, 1, "section")
    assert chunk["section_id"] == "rfp1::section-002"
    assert chunk["parent_section_id"] == "rfp1::section-002"


def test_text_is_space_joined_and_outer_stripped() -> None:
    # 내부 공백은 보존, 외곽만 strip: ["  a  ","b  "] -> "a   b"
    chunk = make_chunk(_doc(), _parent(), ["  a  ", "b  "], 1, 1, 1, "fixed")
    assert chunk["text"] == "a   b"


def test_empty_sentence_list_yields_empty_text() -> None:
    assert make_chunk(_doc(), _parent(), [], 1, 1, 1, "fixed")["text"] == ""


def test_section_label_prefers_explicit_section_key() -> None:
    chunk = make_chunk(_doc(), _parent(), ["t"], 1, 1, 1, "section")
    assert chunk["section"] == "사업 범위"


def test_section_label_falls_back_to_last_path_segment_when_section_absent() -> None:
    parent = {"section_id": "x::section-001", "section_path": ["A", "B 마지막"]}
    chunk = make_chunk(_doc(), parent, ["t"], 1, 1, 1, "fixed")
    assert chunk["section"] == "B 마지막"
    assert chunk["section_path"] == ["A", "B 마지막"]


def test_section_path_defaults_to_single_empty_string_when_both_absent() -> None:
    parent = {"section_id": "y::section-001"}
    chunk = make_chunk(_doc(), parent, ["t"], 1, 1, 1, "fixed")
    assert chunk["section_path"] == [""]
    assert chunk["section"] == ""


def test_chunker_version_and_strategy_field_encode_non_contextual_strategy() -> None:
    # chunker_version 뿐 아니라 chunking_strategy 필드도 인자에서 전파됨을 함께 고정한다
    # (strategy 를 상수로 하드코딩하는 회귀는 section 케이스에서 발산해 잡힌다).
    fixed = make_chunk(_doc(), _parent(), ["t"], 1, 1, 1, "fixed")
    assert fixed["chunker_version"] == "chunker.fixed.v1"
    assert fixed["chunking_strategy"] == "fixed"
    section = make_chunk(_doc(), _parent(), ["t"], 1, 1, 1, "section")
    assert section["chunker_version"] == "chunker.section.v1"
    assert section["chunking_strategy"] == "section"


def test_contextual_chunk_uses_dedicated_version_not_strategy_version() -> None:
    chunk = make_chunk(_doc(), _parent(), ["t"], 1, 1, 1, "section", contextual=True)
    assert chunk["chunker_version"] == "chunker.contextual_prefix.v1"
    assert chunk["contextual"] is True


def test_non_contextual_chunk_omits_contextual_prefix_key() -> None:
    chunk = make_chunk(_doc(), _parent(), ["t"], 1, 1, 1, "section")
    assert chunk["contextual"] is False
    assert "contextual_prefix" not in chunk


def test_contextual_prefix_includes_title_section_and_position() -> None:
    chunk = make_chunk(_doc(), _parent(), ["t"], 1, 2, 3, "section", contextual=True)
    assert chunk["contextual_prefix"] == (
        "Document title: 조달 RFP. Section path: 사업 범위. Chunk position: 2 of 3."
    )
    # 서로 다른 2/3 으로 호출 — 두 위치 필드의 출처를 고정한다(인자 swap 회귀 포착).
    assert chunk["chunk_seq_in_section"] == 2
    assert chunk["total_chunks_in_section"] == 3


def test_contextual_prefix_section_path_falls_back_to_body_when_empty() -> None:
    parent = {"section_id": "d::section-001"}  # no section / section_path
    doc = {"doc_id": "d", "title": "T"}
    chunk = make_chunk(doc, parent, ["t"], 1, 1, 2, "fixed", contextual=True)
    assert chunk["contextual_prefix"] == (
        "Document title: T. Section path: body. Chunk position: 1 of 2."
    )


def test_doc_optional_fields_default_to_empty() -> None:
    doc = {"doc_id": "d", "title": "T"}  # no agency / project / metadata
    chunk = make_chunk(doc, _parent(), ["t"], 1, 1, 1, "fixed")
    assert chunk["title"] == "T"  # title 은 doc 에서 전파(doc_id 등 타 필드로 새지 않음)
    assert chunk["agency"] == ""
    assert chunk["project"] == ""
    assert chunk["metadata"] == {}


def test_regions_and_page_span_keys_absent_when_parent_has_none() -> None:
    chunk = make_chunk(_doc(), _parent(), ["t"], 1, 1, 1, "section")
    assert "regions" not in chunk
    assert "page_span" not in chunk


def test_text_span_hash_and_tokens_always_present() -> None:
    chunk = make_chunk(_doc(), _parent(), ["t"], 1, 1, 1, "section")
    assert "text_span_hash" in chunk
    assert "tokens" in chunk
