"""Unit coverage for ingestion.py doc_id 생성 규칙 (issue #2334).

``canonical_doc_id`` / ``make_doc_id`` / ``make_doc_id_from_file_name`` 은
ingestion 전 경로에서 문서 식별자를 결정하는 규칙인데 직접 단위 테스트가
0건이었다(test-only, 소스 무수정). import-safe leaf(torch/chromadb/rag_core 미로드).

핵심 변별:
- ``make_doc_id`` — notice_id 와 round 를 slug 후 ``-`` join, 빈 part 제외
  (``("","2")→"2"``, ``("","")→""`` 빈 문자열).
- ``make_doc_id_from_file_name`` — Path.stem 의 slug, 공백/빈 stem → None, basename 만.
- ``canonical_doc_id`` — notice_id(+round) 우선, blank 시 파일명 stem fallback,
  전부 비면 None.
"""
from __future__ import annotations

from ingestion import canonical_doc_id, make_doc_id, make_doc_id_from_file_name


# ---- make_doc_id ----

def test_make_doc_id_joins_notice_and_round_with_hyphen() -> None:
    # notice + round 를 slug 후 '-' 로 join, 내부 공백도 하이픈으로.
    assert make_doc_id("N 1", "차 2") == "N-1-차-2"


def test_make_doc_id_omits_empty_round() -> None:
    # round 가 비면 notice 만 — round 를 무조건 붙이면 trailing '-' 가 생겨 KILL.
    assert make_doc_id("공고 123", "") == "공고-123"


def test_make_doc_id_filters_empty_parts() -> None:
    # notice 가 비고 round 만 있으면 round 만 — 빈 part 필터(미필터 시 '-2' KILL).
    assert make_doc_id("", "2") == "2"
    # 둘 다 비면 빈 문자열(None 이 아니라 "").
    assert make_doc_id("", "") == ""


# ---- make_doc_id_from_file_name ----

def test_make_doc_id_from_file_name_uses_stem_slug() -> None:
    assert make_doc_id_from_file_name("doc.pdf") == "doc"
    # 확장자 제거 + 공백 stem → 하이픈.
    assert make_doc_id_from_file_name("공고 문서.hwp") == "공고-문서"


def test_make_doc_id_from_file_name_uses_basename_stem_only() -> None:
    # 경로가 섞여도 basename 의 stem 만(Path.stem) — 'a/b/c' 면 KILL.
    assert make_doc_id_from_file_name("a/b/c.pdf") == "c"


def test_make_doc_id_from_file_name_empty_or_blank_stem_is_none() -> None:
    # 빈 입력 → None, 공백뿐인 stem → slug 가 비어 None("" 이 아님).
    assert make_doc_id_from_file_name("") is None
    assert make_doc_id_from_file_name("   .pdf") is None


# ---- canonical_doc_id ----

def test_canonical_doc_id_prefers_notice_over_file() -> None:
    # notice_id 있으면 round 와 결합, file_name 은 무시(file 우선 시 KILL).
    assert canonical_doc_id("N-1", "2", "f.pdf") == "N-1-2"
    # round 없어도 notice 단독.
    assert canonical_doc_id("N-1", None, None) == "N-1"


def test_canonical_doc_id_falls_back_to_file_when_notice_blank() -> None:
    # notice 가 None/공백이면 파일명 stem fallback(clean_cell 로 공백 notice 무시).
    assert canonical_doc_id(None, None, "doc.pdf") == "doc"
    assert canonical_doc_id("  ", None, "doc.pdf") == "doc"


def test_canonical_doc_id_none_when_all_empty() -> None:
    # notice·file 모두 비면 None(빈 문자열 아님).
    assert canonical_doc_id("", "", "") is None
    assert canonical_doc_id(None, None, None) is None


# ---- case preservation (issue #2409) ----
# docstring 의 옛 'casefold' 문구는 미구현이고(slug_part 는 #49 이래 한 번도
# casefold 안 함), doc_id 는 대소문자를 보존한다. 아래 테스트가 그 계약을 pin —
# 누가 slug_part 에 casefold/.lower() 를 넣으면 FAIL 하여 ADR 0001 naive_baseline
# byte-identity 가 깨짐(모든 doc_id 변경)을 의식하게 만든다.

def test_canonical_doc_id_preserves_case_in_notice() -> None:
    # notice_id 경로: 대소문자 보존 — RFP-001 과 rfp-001 은 서로 다른 id.
    assert canonical_doc_id("RFP-001", None, None) == "RFP-001"
    assert canonical_doc_id("rfp-001", None, None) == "rfp-001"
    assert canonical_doc_id("RFP-001", None, None) != canonical_doc_id("rfp-001", None, None)


def test_canonical_doc_id_preserves_case_in_file_fallback() -> None:
    # file_name stem fallback 경로도 대소문자 보존 — Document ≠ document.
    assert canonical_doc_id(None, None, "Document.hwp") == "Document"
    assert canonical_doc_id(None, None, "document.hwp") == "document"
    assert canonical_doc_id(None, None, "Document.hwp") != canonical_doc_id(None, None, "document.hwp")
