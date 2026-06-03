"""Unit coverage for rag_pipeline_presets.py name lookup helpers (issue #2184).

``rag_pipeline_presets.py`` 의 4 공개 함수 중 ``resolve_pipeline_config`` 만
기존 테스트가 커버한다. 이 파일은 나머지 3종의 동작 계약을 oracle 로 고정한다
(test-only, 소스 무수정):

- ``is_pipeline_name`` — preset/alias 이름 검증(None/빈/비문자열 → False)
- ``pipeline_cli_choices`` — ``PIPELINE_PRESETS.keys()`` (CLI 노출 SSoT)
- ``canonical_pipeline_name`` — alias→canonical 해석, preset 통과, None→default,
  미존재→ValueError

ADR 0001 reproducibility invariant 가드: ``naive_baseline`` 이 PRESETS 에 존재하고
CLI choices 에 노출되며 canonical 해석을 통과해야 한다. 이 테스트가 baseline preset
제거/이름변경 회귀를 표면화한다. leaf 모듈(import 2ms, 무거운 의존 0).
"""
from __future__ import annotations

from typing import Any

import pytest

from rag_pipeline_presets import (
    DEFAULT_RAG_PIPELINE_NAME,
    PIPELINE_ALIASES,
    PIPELINE_PRESETS,
    canonical_pipeline_name,
    is_pipeline_name,
    pipeline_cli_choices,
)


# --- ADR 0001 baseline invariant 가드 (핵심) ---


def test_naive_baseline_is_surfaced_everywhere() -> None:
    """ADR 0001: naive_baseline 은 preset·CLI choices·canonical 해석 모두 통과해야 한다.

    baseline preset 이 제거/개명되면 세 단언이 동시에 FAIL 해 회귀를 표면화한다.
    """
    assert "naive_baseline" in PIPELINE_PRESETS
    assert is_pipeline_name("naive_baseline") is True
    assert "naive_baseline" in pipeline_cli_choices()
    assert canonical_pipeline_name("naive_baseline") == "naive_baseline"


# --- is_pipeline_name ---


def test_is_pipeline_name_accepts_presets_and_aliases() -> None:
    assert is_pipeline_name("agentic_full") is True
    # alias 도 유효한 이름으로 인정
    assert is_pipeline_name("full") is True


def test_is_pipeline_name_rejects_unknown() -> None:
    assert is_pipeline_name("nonexistent_pipeline") is False


def test_is_pipeline_name_rejects_none_and_empty() -> None:
    # str(value or "") 가 None/빈문자열을 "" 로 접어 PRESETS 미포함
    assert is_pipeline_name(None) is False
    assert is_pipeline_name("") is False


def test_is_pipeline_name_non_string_coerced() -> None:
    # 비문자열은 str() 강제 후 미존재 판정
    value: Any = 123
    assert is_pipeline_name(value) is False


# --- pipeline_cli_choices ---


def test_pipeline_cli_choices_mirrors_presets_keys() -> None:
    # ADR 0001: PIPELINE_PRESETS 가 CLI 노출의 단일 출처
    assert pipeline_cli_choices() == list(PIPELINE_PRESETS.keys())


def test_pipeline_cli_choices_returns_fresh_list() -> None:
    # 호출마다 새 list — 호출자가 변형해도 PRESETS 가 오염되지 않는다
    choices = pipeline_cli_choices()
    choices.append("mutated")
    assert "mutated" not in pipeline_cli_choices()


# --- canonical_pipeline_name ---


def test_canonical_pipeline_name_passes_through_preset() -> None:
    assert canonical_pipeline_name("agentic_full") == "agentic_full"


def test_canonical_pipeline_name_resolves_alias() -> None:
    # 'full' alias → 'agentic_full' canonical (PIPELINE_ALIASES 매핑)
    alias, canonical = next(iter(PIPELINE_ALIASES.items()))
    assert canonical_pipeline_name(alias) == canonical
    assert canonical in PIPELINE_PRESETS  # 해석 결과는 항상 실제 preset


def test_canonical_pipeline_name_none_and_empty_use_default() -> None:
    assert canonical_pipeline_name(None) == DEFAULT_RAG_PIPELINE_NAME
    assert canonical_pipeline_name("") == DEFAULT_RAG_PIPELINE_NAME


def test_canonical_pipeline_name_custom_default() -> None:
    # default 인자가 실제로 사용된다
    assert canonical_pipeline_name(None, default="single_chunk") == "single_chunk"


def test_canonical_pipeline_name_unknown_raises() -> None:
    with pytest.raises(ValueError, match="pipeline must be one of"):
        canonical_pipeline_name("nonexistent_pipeline")
