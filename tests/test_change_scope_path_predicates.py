"""Unit coverage for ``pr_eval_change_scope`` 의 path-classifier predicate 5종 + _normalize.

`classify` 는 PR 의 changed-file 경로를 runtime/pytest/docs 스코프로 나눠 CI 의
eval/pytest 잡 실행 여부를 정한다. 기존 테스트는 상위 `classify` 만 덮어 토대가
되는 개별 predicate 의 경계가 노출되지 않았다. 이 경계가 조용히 회귀하면:

- runtime 오탐/누락으로 eval 잡이 잘못 (안) 돌고,
- 특히 ``_is_pytest_path`` 의 **ADR 0100 분기**(agent-evals/ 비-README 변경은
  pytest 를 강제해 privacy 가드 ``tests/test_agent_evals_gitignore.py`` 를 돌려야
  함)가 무너지면 비공개 데이터 가드가 CI 에서 toothless 가 된다.

핵심 비대칭: ``_is_rag_module`` 은 경로에 ``/`` 가 없어야(top-level) 하지만
``_is_requirements`` 는 ``Path(path).name`` 기반이라 ``sub/requirements.txt`` 도
True 다. 이 둘을 한 테스트로 묶어 회귀를 막는다.

모든 기대값은 pristine 소스 실행으로 캡처했다.
"""

from __future__ import annotations

import pytest

from scripts.pr_eval_change_scope import (
    _is_docs_or_reports_only_path,
    _is_pytest_path,
    _is_rag_module,
    _is_requirements,
    _is_runtime_path,
    _normalize,
)


# ----------------------------------------------------------------------
# _is_rag_module — top-level(/ 없음) + name rag_*.py
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("rag_core.py", True),
        ("rag_retrieval.py", True),
        ("rag_.py", True),            # 최소형: "rag_" + ".py"
        ("scripts/rag_x.py", False),  # "/" 있음 → top-level 아님
        ("rag_core.txt", False),      # 확장자 .py 아님
        ("xrag_core.py", False),      # name 이 "rag_" 로 시작 안 함
        ("ragx.py", False),           # "rag" 로 시작하지만 "rag_" 아님 → prefix 경계
        ("RAG_core.py", False),       # 대소문자 구분
    ],
)
def test_is_rag_module(path: str, expected: bool) -> None:
    assert _is_rag_module(path) is expected


# ----------------------------------------------------------------------
# _is_requirements — Path.name 기반 requirements*.txt (/ 무관 → rag 와 비대칭)
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("requirements.txt", True),
        ("requirements-dev.txt", True),
        ("sub/requirements.txt", True),   # name 기반 → / 있어도 True (rag 와 대조)
        ("requirements.md", False),       # 확장자 .txt 아님
        ("myrequirements.txt", False),    # name 이 "requirements" 로 시작 안 함
        ("requirement.txt", False),       # 단수형 → "requirements" prefix 미일치
    ],
)
def test_is_requirements(path: str, expected: bool) -> None:
    assert _is_requirements(path) is expected


def test_rag_vs_requirements_slash_asymmetry() -> None:
    # 같은 "sub/" 접두에서 rag 는 top-level 제한으로 False, requirements 는 name 기반 True.
    assert _is_rag_module("sub/rag_core.py") is False
    assert _is_requirements("sub/requirements.txt") is True


# ----------------------------------------------------------------------
# _is_runtime_path — RUNTIME_FILES ∪ rag ∪ requirements ∪ RUNTIME_PREFIXES
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("ingestion.py", True),                    # RUNTIME_FILES 정확 일치
        ("scripts/build_index.py", True),          # RUNTIME_FILES 정확 일치
        (".github/workflows/pr-eval.yml", True),   # RUNTIME_FILES 정확 일치
        ("eval/naive_rag/benchmark.py", True),     # RUNTIME_PREFIXES "eval/"
        ("api/main.py", True),                     # RUNTIME_PREFIXES "api/"
        ("rag_core.py", True),                     # _is_rag_module 위임
        ("requirements.txt", True),                # _is_requirements 위임
        ("docs/x.md", False),
        ("random.py", False),                      # 최상위 .py 지만 runtime 아님
    ],
)
def test_is_runtime_path(path: str, expected: bool) -> None:
    assert _is_runtime_path(path) is expected


# ----------------------------------------------------------------------
# _is_docs_or_reports_only_path — docs/·reports/·artifacts/ prefix 또는 .md/.txt/.rst suffix
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("docs/x.md", True),       # docs/ prefix
        ("reports/y.json", True),  # reports/ prefix (suffix 는 doc 아님)
        ("artifacts/z", True),     # artifacts/ prefix (suffix 없음)
        ("README.md", True),       # .md suffix
        ("notes.rst", True),       # .rst suffix
        ("top.txt", True),         # .txt suffix
        ("rag_core.py", False),    # runtime, doc 아님
        ("docsx/a", False),        # "docs/" 가 아니라 "docsx/" → prefix 미일치
        ("reportsx/a", False),     # 마찬가지로 substring 아닌 prefix
        ("lib/docs/conf.py", False),  # 중간 substring "docs/" → prefix 미일치 (startswith 고정)
    ],
)
def test_is_docs_or_reports_only_path(path: str, expected: bool) -> None:
    assert _is_docs_or_reports_only_path(path) is expected


# ----------------------------------------------------------------------
# _is_pytest_path — runtime ∪ .py ∪ PYTEST_FILES ∪ agent-evals(ADR 0100) ∪ PYTEST_PREFIXES
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("tests/test_x.py", True),     # tests/ prefix
        ("scripts/x.py", True),        # scripts/ prefix (+ .py)
        ("x.py", True),                # .py suffix
        ("Makefile", True),            # PYTEST_FILES
        ("requirements.txt", True),    # _is_requirements 위임
        (".githooks/pre-commit", True),  # .githooks/ prefix
        ("docs/x.md", False),          # docs-only → pytest 아님
        ("reports/y.json", False),     # report-only → pytest 아님
        ("random.txt", False),         # 최상위 비-runtime .txt
    ],
)
def test_is_pytest_path(path: str, expected: bool) -> None:
    assert _is_pytest_path(path) is expected


def test_is_pytest_path_adr0100_agent_evals_guard() -> None:
    # ADR 0100: agent-evals/ 의 비-README 변경(강제추가된 raw .md 포함)은 pytest 를
    # 강제해야 privacy 가드가 CI 에서 동작한다. README 만 예외(docs-only 허용).
    assert _is_pytest_path("agent-evals/runs/T-1/secret.md") is True
    assert _is_pytest_path("agent-evals/README.md") is False


# ----------------------------------------------------------------------
# _normalize — strip() 후 선행 "./" 반복 제거
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  ./a/b.py  ", "a/b.py"),  # 공백 strip + 선행 ./
        ("././x", "x"),              # 반복 ./ 제거
        ("a/b", "a/b"),             # 변화 없음
        ("./", ""),                 # 전부 ./ → 빈 문자열
        ("  x  ", "x"),             # 공백만 strip
        ("a/./b.py", "a/./b.py"),    # 내부 ./ 세그먼트는 canonicalize 하지 않음
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert _normalize(raw) == expected
