"""Unit coverage for rag_synthesis.py 보안/프롬프트/pricing 순수 helper (issue #2299).

대상 7종은 모두 순수(import 시 torch/chromadb/rag_core/openai/anthropic
미로드)인데 직접 단위 테스트가 0건이라 SSRF/데이터 경계(ADR 0005) 방어와
프롬프트 빌더가 조용히 깨질 수 있었다(test-only, 소스 무수정).

핵심 변별: ``_is_loopback_base_url`` 이 private(10.x)·외부 IP·도메인을 실제
거부(loopback only), ``_assert_loopback_openai_base_url`` 이 비loopback env 에서
``ExternalPayloadBlocked`` raise, ``_resolve_pricing`` longest-prefix versioned
매칭, 프롬프트 빌더의 빈 sentinel·citation suffix 조건.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import rag_synthesis
from rag_synthesis import (
    ENV_BASE_URL,
    PRICING_PER_MTOK_USD,
    ExternalPayloadBlocked,
    TOOL_DEFINITION,
    _assert_loopback_openai_base_url,
    _claim_chunk_ids,
    _extract_tool_payload,
    _format_claims_for_prompt,
    _format_evidence_for_prompt,
    _is_loopback_base_url,
    _resolve_pricing,
)


# ---- _is_loopback_base_url (SSRF 방어) ----

def test_loopback_url_accepts_only_loopback_hosts() -> None:
    assert _is_loopback_base_url("http://localhost") is True
    assert _is_loopback_base_url("http://127.0.0.1:8000") is True  # 포트 무관
    assert _is_loopback_base_url("http://[::1]") is True  # IPv6 loopback


def test_loopback_url_rejects_external_private_and_non_http() -> None:
    assert _is_loopback_base_url("https://8.8.8.8") is False  # 외부 IP
    assert _is_loopback_base_url("http://example.com") is False  # 도메인
    # private 대역(10.x)은 loopback 이 아니다 — SSRF 방어가 private 를 허용하면 KILL.
    assert _is_loopback_base_url("http://10.0.0.1") is False
    assert _is_loopback_base_url("ftp://localhost") is False  # non-http scheme
    assert _is_loopback_base_url("not a url") is False


# ---- _assert_loopback_openai_base_url (egress 차단) ----

def test_assert_loopback_passes_for_loopback_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_BASE_URL, "http://localhost:1234")
    _assert_loopback_openai_base_url()  # raise 하지 않아야 한다


def test_assert_loopback_raises_for_external_or_unset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_BASE_URL, "https://api.openai.com")
    with pytest.raises(ExternalPayloadBlocked):
        _assert_loopback_openai_base_url()  # 외부 → 차단
    monkeypatch.delenv(ENV_BASE_URL, raising=False)
    with pytest.raises(ExternalPayloadBlocked):
        _assert_loopback_openai_base_url()  # unset → 차단(기본 허용 아님)


# ---- _extract_tool_payload ----

def test_extract_tool_payload_requires_type_and_name() -> None:
    name = TOOL_DEFINITION["name"]
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", name=name, input={"ignored": 1}),  # type 불일치
            SimpleNamespace(type="tool_use", name=name, input={"summary": "S"}),
        ]
    )
    assert _extract_tool_payload(response) == {"summary": "S"}


def test_extract_tool_payload_empty_on_mismatch_or_non_dict() -> None:
    name = TOOL_DEFINITION["name"]
    wrong = SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="other", input={"a": 1})])
    assert _extract_tool_payload(wrong) == {}
    assert _extract_tool_payload(SimpleNamespace(content=None)) == {}
    nondict = SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=name, input="x")])
    assert _extract_tool_payload(nondict) == {}


# ---- _claim_chunk_ids ----

def test_claim_chunk_ids_collects_skips_falsy_and_dedups() -> None:
    answer: dict[str, Any] = {
        "claims": [
            {"citations": [{"chunk_id": "c1"}, {"chunk_id": ""}, {"chunk_id": "c2"}]},
            {"citations": [{"chunk_id": "c1"}]},  # 중복 → set 으로 1개
        ]
    }
    assert _claim_chunk_ids(answer) == {"c1", "c2"}  # 빈 chunk_id skip, dedup


def test_claim_chunk_ids_empty_when_no_claims() -> None:
    assert _claim_chunk_ids({}) == set()


# ---- _format_claims_for_prompt ----

def test_format_claims_sentinel_and_citation_suffix() -> None:
    assert _format_claims_for_prompt({"claims": []}) == "(no claims)"
    out = _format_claims_for_prompt(
        {
            "claims": [
                {"target": "A", "claim": "X", "citations": [{"chunk_id": "c1"}]},
                {"target": "B", "claim": "Y", "citations": []},  # citation 없음 → suffix 없음
            ]
        }
    )
    assert out == "- A: X [c1]\n- B: Y"


# ---- _format_evidence_for_prompt ----

def test_format_evidence_sentinel_and_shape() -> None:
    assert _format_evidence_for_prompt([]) == "(no evidence)"
    out = _format_evidence_for_prompt([{"chunk_id": "c1", "doc_id": "d1", "agency": "기관", "text": "본문"}])
    assert out == "[c1] doc=d1 agency=기관\n본문"


def test_format_evidence_caps_at_limit() -> None:
    # 8개 입력이라도 EVIDENCE_FOR_PROMPT(6)개만 직렬화한다.
    evidence = [{"chunk_id": f"c{i}", "text": f"t{i}"} for i in range(8)]
    out = _format_evidence_for_prompt(evidence)
    assert out.count("doc=") == rag_synthesis.EVIDENCE_FOR_PROMPT


def test_format_evidence_truncates_text() -> None:
    # text 는 EVIDENCE_TEXT_LIMIT(600)자로 절단된다.
    long_text = "가" * (rag_synthesis.EVIDENCE_TEXT_LIMIT + 100)
    out = _format_evidence_for_prompt([{"chunk_id": "c1", "text": long_text}])
    body = out.split("\n", 1)[1]
    assert len(body) == rag_synthesis.EVIDENCE_TEXT_LIMIT


# ---- _resolve_pricing ----

def test_resolve_pricing_longest_prefix_and_versioned() -> None:
    known = next(iter(PRICING_PER_MTOK_USD))
    assert _resolve_pricing(known) == PRICING_PER_MTOK_USD[known]
    # versioned id(접미사 추가)도 base prefix 로 매칭된다.
    assert _resolve_pricing(known + "-20260301") == PRICING_PER_MTOK_USD[known]


def test_resolve_pricing_none_for_unknown_or_missing() -> None:
    assert _resolve_pricing(None) is None
    assert _resolve_pricing("") is None
    assert _resolve_pricing("zzz-unknown-model") is None
