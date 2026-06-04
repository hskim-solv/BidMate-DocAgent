"""Unit coverage for rag_provenance.py provenance-row 순수 helper (issue #2315).

``_embedding_row_from_backend`` / ``_iter_run_configs`` / ``_label_as`` 는
import-safe(torch/chromadb/rag_core 미로드) leaf 로직인데 직접 단위 테스트가
0건이었다(test-only, 소스 무수정).

핵심 변별:
- ``_embedding_row_from_backend`` backend 별 status — hashing→WARN, openai→INFO,
  그 외→OK 가 서로 달라야 한다(분기를 죽이면 KILL).
- ``_iter_run_configs`` ablation_runs 펼치기 — 비어있지 않은 list 면 dict 원소만
  yield(top-level 무시, non-dict skip), 빈 list/non-list 면 config 자체 yield.
- ``_label_as`` 는 Row 의 label 만 교체하고 value/status/note 를 보존.
"""
from __future__ import annotations

from typing import Any

from rag_provenance import (
    INFO,
    OK,
    WARN,
    _embedding_row_from_backend,
    _iter_run_configs,
    _label_as,
)


# ---- _label_as ----

def test_label_as_replaces_only_label() -> None:
    row = ("embedding", "val", OK, "note")
    out = _label_as(row, "NEW")
    assert out[0] == "NEW"
    # value/status/note 는 그대로 — 다른 위치를 건드리면 KILL.
    assert out[1:] == ("val", OK, "note")


# ---- _embedding_row_from_backend ----

def test_embedding_row_hashing_warns() -> None:
    label, value, status, note = _embedding_row_from_backend("hashing", "m")
    assert (label, value, status) == ("embedding", "hashing (m)", WARN)
    assert status == WARN and status != OK  # hashing 은 OK 가 아니라 WARN
    # note 정확 고정 — 부분 문자열만 보면 note 변조가 새어 KILL.
    assert note == "feature-hashing BoW — 의미 검색 무력, term-overlap only"


def test_embedding_row_openai_info() -> None:
    label, value, status, note = _embedding_row_from_backend("openai", "gpt")
    assert (label, value, status) == ("embedding", "openai (gpt)", INFO)
    assert status == INFO and status not in {OK, WARN}  # 외부 API 는 INFO
    # note 정확 고정 — 부분 문자열만 보면 note 변조가 새어 KILL.
    assert note == "외부 API (BIDMATE_OPENAI_API_KEY)"


def test_embedding_row_other_backend_is_ok_without_note() -> None:
    # 알려진 분기(hashing/openai) 밖은 OK + note 없음 — 셋이 같은 status 면 KILL.
    label, value, status, note = _embedding_row_from_backend("minilm", "x")
    assert (label, value, status, note) == ("embedding", "minilm (x)", OK, None)
    assert OK != WARN != INFO and OK != INFO  # 세 status 가 서로 구별됨


def test_embedding_row_blank_inputs_use_question_fallback() -> None:
    # 빈 backend/model 은 "?" 로 대체되고 strip 된다.
    assert _embedding_row_from_backend("", "") == ("embedding", "? (?)", OK, None)
    assert _embedding_row_from_backend("  hashing  ", "  m  ")[1] == "hashing (m)"


# ---- _iter_run_configs ----

def test_iter_run_configs_expands_dict_runs_and_ignores_top_level() -> None:
    config: dict[str, Any] = {"ablation_runs": [{"a": 1}, {"b": 2}], "top": 9}
    out = list(_iter_run_configs(config))
    assert out == [{"a": 1}, {"b": 2}]
    # ablation_runs 가 있으면 config 자체는 yield 되지 않는다.
    assert config not in out


def test_iter_run_configs_falls_back_to_config_for_empty_or_non_list() -> None:
    # 빈 list 는 falsy → config 자체 yield. non-list 도 마찬가지.
    empty = {"ablation_runs": [], "mode": "h"}
    non_list = {"ablation_runs": "notalist", "m": 1}
    assert list(_iter_run_configs(empty)) == [empty]
    assert list(_iter_run_configs(non_list)) == [non_list]


def test_iter_run_configs_skips_non_dict_entries() -> None:
    # list 안 non-dict 원소는 건너뛴다 — isinstance 가드가 죽으면 'skip' 이 새어 KILL.
    out = list(_iter_run_configs({"ablation_runs": [{"a": 1}, "skip", {"b": 2}]}))
    assert out == [{"a": 1}, {"b": 2}]
