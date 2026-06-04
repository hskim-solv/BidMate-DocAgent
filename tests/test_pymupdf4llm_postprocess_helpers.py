"""Unit coverage for ingestion.py pymupdf4llm 후처리 순수 helper (issue #2286).

대상 4종은 모두 순수(I/O·외부 의존 없음; import 시 torch/chromadb/pymupdf4llm
미로드)인데 직접 단위 테스트가 0건이라 조용히 깨질 수 있었다(test-only, 소스
무수정):

- ``_safe_process_tail`` — stderr tail + 경로/파일명 redaction(PII·경로 누출
  방지 보안 함수). 누출 0 을 negative assertion 으로 못 박는다.
- ``_page_number_from_pymupdf4llm_chunk`` — page_number>page 우선, bool·≤0·
  비dict 거부 → fallback.
- ``_is_numeric_only_page_chunk`` — 구분자 제거 후 숫자-only 페이지 판별.
- ``_sections_from_pymupdf4llm_output`` — str/list → (sections, skipped count).

ingestion 은 load-bearing 이나 본 파일은 test-only(동작 무변경). 무한 비중첩
leaf 커버리지 루프의 일부.
"""
from __future__ import annotations

from pathlib import Path

import ingestion
from ingestion import (
    _is_numeric_only_page_chunk,
    _page_number_from_pymupdf4llm_chunk,
    _safe_process_tail,
    _sections_from_pymupdf4llm_output,
)

_SRC = Path("/Users/x/Desktop/secret RFP 문서.hwp")


# ---- _safe_process_tail (redaction 보안) ----

def test_safe_tail_empty_inputs_return_blank() -> None:
    assert _safe_process_tail(None, _SRC) == ""
    assert _safe_process_tail("", _SRC) == ""
    assert _safe_process_tail("   ", _SRC) == ""  # strip 후 빈 → ""


def test_safe_tail_decodes_bytes_and_redacts_abspath() -> None:
    out = _safe_process_tail(b"error at /tmp/abc.pdf", _SRC)
    assert out == "error at <path>"  # bytes decode + 절대경로 마스킹


def test_safe_tail_redacts_full_source_path_not_partial() -> None:
    # full path 가 filename 보다 먼저 치환 → 통째로 <source_path>.
    out = _safe_process_tail("at /Users/x/Desktop/secret RFP 문서.hwp now", _SRC)
    assert out == "at <source_path> now"
    # 누출 0: 원본 경로/파일명 어떤 조각도 결과에 남지 않는다.
    assert "secret RFP 문서.hwp" not in out
    assert "/Users/x" not in out


def test_safe_tail_full_path_redaction_is_sole_defense_for_uncommon_root() -> None:
    # /data/ 는 절대경로 정규식 목록(/Users//private//tmp//var//home//Volumes/) 밖 →
    # source_path 전체 치환만이 유일 방어선. redaction 라인을 제거하면 경로가 그대로
    # 누출되므로 누출 0 을 단독으로 못 박는다(정규식 백업에 기대지 않음).
    src = Path("/data/rfp/비밀 제안서.hwp")
    out = _safe_process_tail("변환 실패: /data/rfp/비밀 제안서.hwp 확인", src)
    assert out == "변환 실패: <source_path> 확인"
    assert "비밀 제안서.hwp" not in out  # full-path redaction 없으면 누출 → KILL
    assert "/data/rfp" not in out


def test_safe_tail_redacts_bare_filename() -> None:
    out = _safe_process_tail("fail: secret RFP 문서.hwp bad", _SRC)
    assert out == "fail: <source_file> bad"
    assert "secret RFP 문서.hwp" not in out  # 파일명 누출 0


def test_safe_tail_redacts_windows_path() -> None:
    out = _safe_process_tail(r"open C:\Users\me\f.txt fail", _SRC)
    assert out == "open <path> fail"
    assert "C:\\Users" not in out


def test_safe_tail_keeps_only_last_chars() -> None:
    # tail 은 마지막 _HWP_TO_PDF_STDERR_TAIL_CHARS 자만. 앞부분은 버려진다.
    n = ingestion._HWP_TO_PDF_STDERR_TAIL_CHARS
    stderr = "HEAD_MARKER" + ("x" * n) + "TAIL_MARKER"
    out = _safe_process_tail(stderr, _SRC)
    assert "TAIL_MARKER" in out
    assert "HEAD_MARKER" not in out  # n자 초과분(앞)은 잘려나감
    assert len(out) <= n


# ---- _page_number_from_pymupdf4llm_chunk ----

def test_page_number_prefers_page_number_over_page() -> None:
    assert _page_number_from_pymupdf4llm_chunk({"metadata": {"page_number": 5, "page": 7}}, 9) == 5
    # page_number 부재 시 page 키로 fallback(전역 fallback 아님).
    assert _page_number_from_pymupdf4llm_chunk({"metadata": {"page": 7}}, 9) == 7


def test_page_number_rejects_bool_true() -> None:
    # True 는 int 1 이지만 bool 이므로 거부 → fallback. (1 로 새면 KILL)
    assert _page_number_from_pymupdf4llm_chunk({"metadata": {"page_number": True}}, 9) == 9


def test_page_number_rejects_nonpositive_and_non_dict_metadata() -> None:
    assert _page_number_from_pymupdf4llm_chunk({"metadata": {"page_number": 0}}, 9) == 9
    assert _page_number_from_pymupdf4llm_chunk({"metadata": {"page_number": -3}}, 9) == 9
    assert _page_number_from_pymupdf4llm_chunk({"metadata": "not-a-dict"}, 9) == 9
    assert _page_number_from_pymupdf4llm_chunk({}, 9) == 9


# ---- _is_numeric_only_page_chunk ----

def test_numeric_only_true_for_digits_and_separator_wrapped() -> None:
    assert _is_numeric_only_page_chunk("12") is True
    assert _is_numeric_only_page_chunk("- 3 -") is True  # 구분자 제거 후 "3"
    assert _is_numeric_only_page_chunk("1.2.3") is True
    assert _is_numeric_only_page_chunk("·• 7") is True


def test_numeric_only_false_for_blank_and_text() -> None:
    assert _is_numeric_only_page_chunk("") is False  # bool(compact) 가드
    assert _is_numeric_only_page_chunk("   ") is False
    assert _is_numeric_only_page_chunk("3 페이지") is False  # 한글 남음 → isdigit False
    assert _is_numeric_only_page_chunk("abc") is False


# ---- _sections_from_pymupdf4llm_output ----

def test_sections_from_string_output() -> None:
    assert _sections_from_pymupdf4llm_output("") == ([], 0)
    assert _sections_from_pymupdf4llm_output("12") == ([], 1)  # numeric-only str → skipped 1
    sections, skipped = _sections_from_pymupdf4llm_output("본문 텍스트")
    assert skipped == 0
    assert sections == [{"heading": "page-1", "text": "본문 텍스트", "page_span": [1, 1]}]


def test_sections_non_list_non_str_is_empty() -> None:
    assert _sections_from_pymupdf4llm_output(None) == ([], 0)
    assert _sections_from_pymupdf4llm_output(42) == ([], 0)


def test_sections_from_list_skips_only_numeric_chunks() -> None:
    # 빈 텍스트·non-dict 는 skip 하되 카운트 제외; numeric-only 만 skipped 에 집계.
    out, skipped = _sections_from_pymupdf4llm_output(
        [
            {"text": "첫 페이지 본문", "metadata": {"page_number": 1}},
            {"text": "   "},                  # 빈 → skip, count 제외
            {"text": "5"},                      # numeric-only → skip + count
            "not-a-dict",                       # non-dict → skip, count 제외
            {"text": "셋째 본문", "metadata": {"page": 3}},
        ]
    )
    assert [s["heading"] for s in out] == ["page-1", "page-3"]
    assert [s["page_span"] for s in out] == [[1, 1], [3, 3]]
    assert skipped == 1  # numeric "5" 만; 빈/non-dict 는 미집계


def test_sections_uses_enumerate_fallback_page_when_no_metadata() -> None:
    # metadata page 부재 시 enumerate(start=1) 순번이 fallback → page-1, page-2.
    out, _ = _sections_from_pymupdf4llm_output([{"text": "본문A"}, {"text": "본문B"}])
    assert [s["heading"] for s in out] == ["page-1", "page-2"]
