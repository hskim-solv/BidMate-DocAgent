"""Unit coverage for parser_page_metadata_contract.py 순수 helper (issue #2317).

page metadata 계약 검증 모듈(import-safe leaf)의 helper 6종은 직접 단위 테스트가
0건이었다. 특히 ``_safe_source_group`` 은 ADR 0005 데이터 경계 방어(source
path/filename redaction)인데 회귀 가드가 없었다(test-only, 소스 무수정).

핵심 변별:
- ``_safe_source_group`` redaction — PRIVATE path/Windows drive·파일명(확장자)·SAFE
  패턴 밖 문자를 ``<redacted_source_group>`` 으로 가리고, 원본 토큰이 새지 않는다.
- ``classify_parser_source_group`` 우선순위 — coverage>0 early-return 이 visual/kordoc
  분기보다 먼저; ``visual`` 이라도 ``fallback`` 동반 시 spike 아님(page_blind).
- ``_strict_int`` 는 bool 을 int 로 보지 않는다.
"""
from __future__ import annotations

from parser_page_metadata_contract import (
    ADAPTER_SPIKE_REQUIRED,
    PAGE_AWARE_CAPABLE,
    PAGE_BLIND,
    _empty_report,
    _page_span,
    _rate,
    _safe_source_group,
    _strict_int,
    classify_parser_source_group,
)

_REDACTED = "<redacted_source_group>"
_UNSPEC = "<unspecified>"


# ---- _rate ----

def test_rate_guards_nonpositive_denominator() -> None:
    # denominator<=0 은 ZeroDivision 대신 0.0; 양수는 6자리 반올림.
    assert _rate(5, 0) == 0.0
    assert _rate(5, -1) == 0.0
    assert _rate(1, 3) == 0.333333


# ---- _strict_int ----

def test_strict_int_excludes_bool_and_non_int() -> None:
    assert _strict_int(5) is True
    # bool 은 int 서브클래스지만 제외 — 이 가드를 죽이면 KILL.
    assert _strict_int(True) is False
    assert _strict_int(False) is False
    assert _strict_int(1.0) is False
    assert _strict_int("5") is False


# ---- _safe_source_group (ADR 0005 redaction) ----

def test_safe_source_group_redacts_private_path_and_filename_without_leak() -> None:
    # PRIVATE path → redact, 원본 경로/토큰이 결과에 남으면 누출 = KILL.
    out_path = _safe_source_group("/Users/secret/doc")
    assert out_path == _REDACTED
    assert "secret" not in out_path and "/Users" not in out_path
    # Windows drive 도 PRIVATE.
    assert _safe_source_group("C:\\secret\\x") == _REDACTED
    # 파일명(확장자) → redact, 파일명 토큰 누출 없음.
    out_file = _safe_source_group("비밀제안서.hwp")
    assert out_file == _REDACTED
    assert "비밀제안서" not in out_file and ".hwp" not in out_file


def test_safe_source_group_redacts_unsafe_chars() -> None:
    # SAFE 패턴(^[A-Za-z0-9_:/-]+$) 밖 문자(공백/특수/한글) → redact.
    assert _safe_source_group("a b") == _REDACTED
    assert _safe_source_group("특수!") == _REDACTED


def test_safe_source_group_passes_safe_label_and_marks_empty() -> None:
    # safe parser label 은 그대로 통과(과잉 redaction 이면 KILL).
    assert _safe_source_group("pdf/hwp_kordoc") == "pdf/hwp_kordoc"
    # None/빈 문자열 → <unspecified> (redacted 와 구별).
    assert _safe_source_group(None) == _UNSPEC
    assert _safe_source_group("   ") == _UNSPEC


# ---- _page_span ----

def test_page_span_validates_pair_and_order() -> None:
    assert _page_span([1, 3]) == (1, 3)
    assert _page_span([2, 2]) == (2, 2)  # 동률 허용
    assert _page_span([3, 1]) is None  # 역순 거부
    assert _page_span([1, 2, 3]) is None  # 길이 != 2
    assert _page_span([True, 3]) is None  # bool 은 strict_int 아님
    assert _page_span("x") is None  # list 아님


# ---- _empty_report ----

def test_empty_report_shape_and_source_group_redaction() -> None:
    report = _empty_report("pdf/v2")
    assert report["schema_version"] == 1
    assert report["ok"] is True
    assert report["section_count"] == 0
    assert report["uncovered_rate"] == 0.0
    assert report["malformed_counts"] == {}
    assert report["source_group"] == "pdf/v2"
    # source_group 도 redaction 경로를 거친다.
    assert _empty_report("비밀.hwp")["source_group"] == _REDACTED


# ---- classify_parser_source_group ----

def test_classify_coverage_early_return_takes_priority() -> None:
    # coverage>0 면 즉시 page_aware_capable — visual 신호가 있어도 우선한다(early return).
    assert classify_parser_source_group(any_page_metadata_coverage=0.5) == PAGE_AWARE_CAPABLE
    assert classify_parser_source_group(parent_any_page_metadata_coverage=0.1) == PAGE_AWARE_CAPABLE
    # 우선순위 KILL: visual + coverage → 여전히 page_aware_capable(adapter_spike 아님).
    assert (
        classify_parser_source_group(text_source="visual", any_page_metadata_coverage=0.5)
        == PAGE_AWARE_CAPABLE
    )


def test_classify_visual_requires_spike_unless_fallback() -> None:
    assert classify_parser_source_group(text_source="visual") == ADAPTER_SPIKE_REQUIRED
    assert classify_parser_source_group(document_type="visual") == ADAPTER_SPIKE_REQUIRED
    # 'fallback' 동반 시 spike 아님 — 'fallback not in' 가드를 죽이면 KILL.
    # text_source·document_type 두 축 모두 검증(가드가 두 분기에 각각 존재).
    assert classify_parser_source_group(text_source="visual_fallback") == PAGE_BLIND
    assert classify_parser_source_group(document_type="visual_fallback") == PAGE_BLIND


def test_classify_kordoc_and_default_combinations() -> None:
    assert classify_parser_source_group(file_format="pdf", text_source="kordoc") == ADAPTER_SPIKE_REQUIRED
    assert classify_parser_source_group(file_format="hwp", text_source="kordoc") == ADAPTER_SPIKE_REQUIRED
    assert classify_parser_source_group(file_format="hwp", document_type="fallback") == ADAPTER_SPIKE_REQUIRED
    # 일반 조합·빈 입력 → page_blind.
    assert classify_parser_source_group(file_format="pdf", text_source="csv_text") == PAGE_BLIND
    assert classify_parser_source_group() == PAGE_BLIND
