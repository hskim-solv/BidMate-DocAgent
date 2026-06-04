"""Unit coverage for ingestion.py dedup/redaction 순수 helper (issue #2329).

``_redact_section_text`` / ``validate_fieldnames`` / ``_compute_next_unique_doc_id`` /
``_looks_like_notice_id_doc`` 은 import-safe leaf(torch/chromadb/rag_core 미로드)인데
직접 단위 테스트가 0건이었다(test-only, 소스 무수정).

핵심 변별:
- ``_redact_section_text`` — 각 section dict 를 copy 한 뒤 ``text`` 만 ``redact_pii``
  로 치환. 원본 list/dict 는 불변, ``text`` 키 부재 시에도 빈 문자열로 채운다.
- ``validate_fieldnames`` — ``REQUIRED_COLUMNS`` 누락 시 누락 컬럼을 원래 순서대로
  담은 ``ValueError``, 전부 있으면 조용히 ``None``.
- ``_compute_next_unique_doc_id`` — ``counts`` 를 시작점으로, ``seen`` 충돌은 skip 하며
  ``<base>-N`` 후보와 N 을 함께 반환.
- ``_looks_like_notice_id_doc`` — doc_id 가 파일명 stem slug 와 다르면(또는 비면) True.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ingestion import (
    REQUIRED_COLUMNS,
    IngestionRecord,
    _DuplicateTracker,
    _compute_next_unique_doc_id,
    _looks_like_notice_id_doc,
    _redact_section_text,
    validate_fieldnames,
)


# ---- _redact_section_text ----

def test_redact_section_text_masks_phone_and_preserves_other_keys() -> None:
    out = _redact_section_text([{"section": "1", "text": "전화 010-1234-5678"}])
    # redact_pii 호출 — 전화번호가 <phone> 으로 마스킹(미호출 시 원문 KILL).
    assert out[0]["text"] == "전화 <phone>"
    # text 외 다른 필드(section) 는 보존.
    assert out[0]["section"] == "1"


def test_redact_section_text_copies_and_does_not_mutate_input() -> None:
    secs = [{"section": "1", "text": "010-1234-5678"}]
    out = _redact_section_text(secs)
    # 원본 dict 는 불변(dict copy 안 하고 in-place 치환하면 KILL).
    assert secs[0]["text"] == "010-1234-5678"
    assert out[0] is not secs[0]


def test_redact_section_text_none_or_missing_text_becomes_empty() -> None:
    # text=None / text 키 부재 모두 빈 문자열(str(... or "")), 문자열 "None" 아님.
    out = _redact_section_text([{"text": None}, {"key": "x"}])
    assert out[0]["text"] == ""
    # text 키가 없던 dict 에도 text="" 가 채워진다.
    assert out[1]["text"] == "" and out[1]["key"] == "x"


# ---- validate_fieldnames ----

def test_validate_fieldnames_passes_when_all_required_present() -> None:
    # 전체 컬럼 present → 예외 없이 None 반환.
    assert validate_fieldnames(list(REQUIRED_COLUMNS), Path("ok.csv")) is None


def test_validate_fieldnames_raises_with_missing_columns_in_order() -> None:
    with pytest.raises(ValueError) as ei:
        validate_fieldnames(["공고 번호"], Path("data/x.csv"))
    msg = str(ei.value)
    # 경로 + 누락 컬럼(REQUIRED_COLUMNS 순서)이 메시지에 담긴다.
    assert "data/x.csv" in msg
    assert "사업명, 발주 기관, 파일형식, 파일명, 텍스트" in msg
    # 이미 존재하는 '공고 번호' 는 누락 목록에서 빠진다(필터 KILL).
    assert "공고 번호" not in msg.split("required columns:", 1)[1]


# ---- _compute_next_unique_doc_id ----

def test_compute_next_starts_at_two_on_empty_tracker() -> None:
    # 빈 tracker: counts.get(base,1)=1, +1 → base-2 (base-1 이면 +1 KILL, default 1 KILL).
    assert _compute_next_unique_doc_id("base", _DuplicateTracker()) == ("base-2", 2)


def test_compute_next_uses_counts_as_starting_point() -> None:
    # counts 시작점 사용 → base-6 (counts 무시 시 base-2 KILL).
    t = _DuplicateTracker(counts={"base": 5})
    assert _compute_next_unique_doc_id("base", t) == ("base-6", 6)


def test_compute_next_skips_seen_collisions() -> None:
    # seen 에 base-2,base-3 점유 → while loop 가 base-4 까지 skip(loop 없으면 base-2 KILL).
    t = _DuplicateTracker(seen={"base-2": 0, "base-3": 0})
    assert _compute_next_unique_doc_id("base", t) == ("base-4", 4)


# ---- _looks_like_notice_id_doc ----

def _rec(doc_id: str | None, file_name: str) -> IngestionRecord:
    return IngestionRecord(
        row_number=1,
        status="ok",
        doc_id=doc_id,
        file_name=file_name,
        file_format="pdf",
        source_path="/x",
    )


def test_looks_like_notice_id_doc_compares_doc_id_to_stem_slug() -> None:
    # doc_id 가 파일명 stem slug 와 같으면 file_name 기반 → False.
    assert _looks_like_notice_id_doc(_rec("doc", "doc.pdf")) is False
    # 다르면 notice_id 기반 → True.
    assert _looks_like_notice_id_doc(_rec("N-1", "doc.pdf")) is True


def test_looks_like_notice_id_doc_true_when_missing_id_or_name() -> None:
    # doc_id None / file_name 빈 문자열 → stem 비교 전 early True.
    assert _looks_like_notice_id_doc(_rec(None, "doc.pdf")) is True
    assert _looks_like_notice_id_doc(_rec("doc", "")) is True
    # guard 자체를 pin: doc_id="" 빈 + file_name 공백뿐 → fallback 이라면
    # ""!=slug_part("")="" → False 였을 입력. 이 True 는 오직 early-return
    # guard(`not record.doc_id`)에서 나온다(guard 제거 / `or`→`and` 시 KILL).
    assert _looks_like_notice_id_doc(_rec("", "   ")) is True
