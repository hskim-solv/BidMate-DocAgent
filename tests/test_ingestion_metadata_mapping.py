"""Unit coverage for ingestion.normalize_metadata CSV→메타데이터 매핑 (issue #2325).

``normalize_metadata`` 는 한국어 CSV 헤더를 정규화 메타데이터 dict 로 옮기는
import-safe leaf 인데 직접 단위 테스트가 0건이었다(test-only, 소스 무수정).

핵심 변별:
- 헤더 매핑 — `사업명→project`, `발주 기관→agency` 등 키가 정확히 연결.
- ``doc_id_source`` — `공고 번호` 가 있으면 ``"notice_id"``, 비면 ``"file_name"``.
- ``budget`` 만 ``parse_budget``(int/float), 나머지는 ``clean_cell``.
"""
from __future__ import annotations

from ingestion import normalize_metadata


def _full_row() -> dict[str, str]:
    return {
        "공고 번호": " N-1 ",
        "공고 차수": "2",
        "사업명": "AI 사업",
        "사업 금액": "1,000",
        "발주 기관": "기관A",
        "공개 일자": "2026-01-01",
        "입찰 참여 시작일": "2026-01-05",
        "입찰 참여 마감일": "2026-01-20",
        "사업 요약": "요약",
    }


def test_normalize_metadata_maps_korean_headers() -> None:
    meta = normalize_metadata(_full_row(), "pdf", "doc.pdf")
    # 헤더 → 키 매핑이 정확해야 한다(오결선 시 KILL).
    assert meta["notice_id"] == "N-1"  # clean_cell 로 strip
    assert meta["notice_round"] == "2"
    assert meta["project"] == "AI 사업"
    assert meta["agency"] == "기관A"
    assert meta["published_at"] == "2026-01-01"
    assert meta["bid_start_at"] == "2026-01-05"
    assert meta["bid_deadline_at"] == "2026-01-20"
    assert meta["summary"] == "요약"
    assert meta["file_format"] == "pdf"
    assert meta["file_name"] == "doc.pdf"


def test_doc_id_source_switches_on_notice_id() -> None:
    # 공고 번호 있음 → notice_id, 없음/공백 → file_name (분기 KILL).
    assert normalize_metadata({"공고 번호": "N-1"}, "pdf", "f.pdf")["doc_id_source"] == "notice_id"
    assert normalize_metadata({}, "pdf", "f.pdf")["doc_id_source"] == "file_name"
    assert normalize_metadata({"공고 번호": "   "}, "pdf", "f.pdf")["doc_id_source"] == "file_name"


def test_budget_uses_parse_budget_not_clean_cell() -> None:
    # budget 만 parse_budget — '1,000' 이 int 1000 으로 파싱(clean_cell 이면 '1,000' 문자열 → KILL).
    meta = normalize_metadata({"사업 금액": "1,000"}, "pdf", "f.pdf")
    assert meta["budget"] == 1000 and isinstance(meta["budget"], int)
    # 소수는 float.
    assert normalize_metadata({"사업 금액": "1,234.5"}, "pdf", "f.pdf")["budget"] == 1234.5
    # 빈 금액 → None.
    assert normalize_metadata({}, "pdf", "f.pdf")["budget"] is None


def test_text_source_arg_and_fixed_document_type() -> None:
    # text_source 는 인자로 전파, 기본값 data_list_csv_text.
    assert normalize_metadata({}, "pdf", "f", text_source="visual_ocr")["text_source"] == "visual_ocr"
    assert normalize_metadata({}, "pdf", "f")["text_source"] == "data_list_csv_text"
    # document_type 은 고정.
    assert normalize_metadata({}, "pdf", "f")["document_type"] == "private_pdf_hwp_csv_text"
