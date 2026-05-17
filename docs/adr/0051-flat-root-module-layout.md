# 0051: flat-root module layout 유지 — `src/` 마이그레이션 거절

- **Status**: accepted
- **Date**: 2026-05-17
- **Deciders**: hskim
- **Related**: [ADR 0045](./0045-rag-core-leaf-migration-plan.md) (leaf DAG 불변량) · [CLAUDE.md](../../CLAUDE.md) *저장소 맵* · [`scripts/_governance.py`](../../scripts/_governance.py) `LOAD_BEARING_PATHS` · issue #933

## TL;DR

- 루트에 ~35개 Python 모듈이 평탄 배치된 현 layout 을 **의도된 영구 구조**로 고정
- `src/<pkg>/` 마이그레이션은 이득(import cleanliness)이 ADR 0045 와 중복이고 비용(governance / hooks / import / real-eval 델타 전면 갱신)이 큼 — 거절
- Revisit triggers 4개 명시: 루트 파일 50개 초과 / 외부 publish 필요 / cycle·namespace 충돌 / 컨트리뷰터 다수 혼란 보고

## 배경

레포 루트에 도메인 모듈 24개(`rag_*.py`) + 인프라 모듈 4개(`bidmate_logging.py`, `bidmate_security.py`, `text_normalize.py`, `korean_lexicon.py`) + 진입점 1개(`app.py`) + 파이프라인 코어 2개(`ingestion.py`, `visual_ingestion.py`)가 평탄 배치되어 있다. 별도 `src/` 또는 패키지 디렉토리 없음.

이 layout 은 세 곳이 SSoT 로 가리킨다:

- [`pyproject.toml`](../../pyproject.toml) `tool.pytest.ini_options.pythonpath = ["."]`
- [CLAUDE.md](../../CLAUDE.md) "저장소 맵" 섹션 (load-bearing 6 + supporting 9 + 디렉토리 5)
- [`scripts/_governance.py`](../../scripts/_governance.py) `LOAD_BEARING_PATHS` — pre-push hook + PreToolUse load-bearing awareness + `--check-5b` CI gate 가 함께 읽는 단일 출처

그러나 **"왜 평탄한가" 가 ADR 로 기록되어 있지 않다.** 외부 리뷰어 / 신규 컨트리뷰터 / 미래의 본인이 이를 "정리해야 할 기술 부채" 로 오해할 위험이 있고, 그 오해가 large-scale refactor 압력으로 누적될 가능성이 있다. CLAUDE.md "ADR 임계값" 조항 — *load-bearing 결정의 유지/교체 시 ADR 필요* — 에 부합하므로 결정을 명문화한다.

## 결정

flat-root layout 을 의도된 영구 구조로 채택. `src/<pkg>/` 마이그레이션은 거절.

핵심 근거는 **ADR 0045 가 이미 패키지화의 핵심 이득을 달성**했다는 점:

- 6개 leaf 모듈(`rag_query`, `rag_retrieval`, `rag_verifier`, `rag_answer`, `rag_embedding`, `rag_indexing`)이 `rag_core` 로의 back-edge 0 — top-level + function-level
- 이 불변량은 [`tests/test_dependency_graph_invariance.py`](../../tests/test_dependency_graph_invariance.py) 가 회귀 테스트로 강제. 미래 PR 의 back-edge 재도입은 CI 실패
- 깨끗한 의존성 그래프는 `src/` 패키지화의 가장 큰 명목 이득(import cycle 방지 / IDE go-to-definition / mypy reachability)과 겹친다 → 추가 이득 marginal

knob: 본 결정에는 토글이 없다. 재검토 trigger 가 충족되면 별도 ADR 로 supersede.

## 결과

**Wins**

- ADR 0045 leaf DAG 불변량이 패키지화 이득의 95%를 무료로 제공. `src/` 추가 비용 0
- `pythonpath = ["."]` + `sys.path.insert(0, str(ROOT))` 패턴이 pytest / 스크립트 / CI 에서 균일 동작 — 자동화 안정성 확보
- `LOAD_BEARING_PATHS` 가 짧은 파일명(`rag_core.py`, `rag_retrieval.py` 등) 그대로 사용 → governance regex 단순, hook 빠름
- CLAUDE.md "저장소 맵" 의 load-bearing/supporting 분류가 디렉토리 hierarchy 없이도 명시적 — reviewer 가 한 화면에서 의도 파악 가능

**Costs**

- `tests/` 76개 파일에 `sys.path.insert(0, str(ROOT))` 보일러플레이트 잔존. 통증 누적 시 `tests/conftest.py` 단일화로 **구조 변경 없이** 별도 해결 가능 (deferred to issue)
- 신규 루트 모듈 추가 시 naming rule 모호(`rag_*` 도메인 vs `bidmate_*` 인프라 vs bare 일반). CLAUDE.md "저장소 맵" 갱신으로 흡수 (deferred to issue)
- `LOAD_BEARING_PATHS` 가 파일명을 hard-code → 디렉토리 재구성 비용 큼. 본 ADR 결정의 일관된 귀결, 비용 아님

**미변경**

- ADR 0001 naive-baseline 불변량: 코드 무변경
- ADR 0003 답변 계약: 무변경
- ADR 0045 leaf DAG: 본 ADR 의 전제이자 강화 대상

## 검토한 대안

### (a) `src/bidmate/` 패키지 마이그레이션

*거부*: 명목 이득(import cleanliness, distribution-readiness)이 ADR 0045 와 중복. 비용은:

- `LOAD_BEARING_PATHS` 의 35개 파일명 모두 prefix 갱신
- 35개 모듈 import 광역 변경 (`from rag_core` → `from bidmate.rag_core`)
- tests/ 76곳 sys.path 또는 console_scripts entry point 정리
- governance regex + pre-push hook + PreToolUse awareness 갱신
- real-eval 델타 검증 (load-bearing 변경)
- ADR 0007 브랜치 컨벤션 / PR 템플릿 5b 절차

현재 layout 으로 인한 구체적 통증이 보고된 바 없는 상태에서 정당화 불가.

### (b) 부분 그룹화 (`rag/`, `ingestion/` 하위 디렉토리)

*거부*: ADR 0045 가 모듈 간 경계를 이미 잡았고, 디렉토리화는 `LOAD_BEARING_PATHS` 와 governance regex 를 깨면서 동등 이득 없음. CLAUDE.md "저장소 맵" 의 load-bearing/supporting 분류로 같은 cognitive grouping 효과 달성 중.

### (c) 결정을 ADR 로 명문화하지 않고 CLAUDE.md 한 줄로 처리

*거부*: load-bearing 결정의 유지 결정은 ADR 임계값에 해당(CLAUDE.md 명시). CLAUDE.md 본문은 자주 갱신되고 분량이 누적되어 *왜* 가 흐려진다. ADR 은 영구·번호·status lifecycle 을 갖는 reviewer-defensible 표면.

## Revisit triggers

다음 중 하나라도 충족되면 본 결정 supersede 후보:

- 루트 Python 파일 50개 초과 (현재 ~35개, 헤드룸 ~15)
- 외부 PyPI / wheel 로 publish 필요 발생 — `pip install bidmate` use case
- import cycle 또는 namespace 충돌이 ADR 0045 `test_dependency_graph_invariance.py` 가드를 우회하기 시작
- 신규 컨트리뷰터 5명 이상이 동일 layout 혼란을 issue 로 보고

## 본 ADR 범위 외 (별도 issue 후보)

- `tests/` 76곳 `sys.path.insert` → `tests/conftest.py` 일원화
- CLAUDE.md "저장소 맵" 에 루트 모듈 naming rule 명문화 (`rag_*` = 도메인 / `bidmate_*` = 공통 인프라 / bare = 일반 유틸)
- `LOAD_BEARING_PATHS` 표기 개선 (현 hard-code 파일명 → 카테고리화)

이 세 항목은 구조 변경 없이 처리 가능. 통증이 구체화되는 시점에 별도 PR.

## Verification

본 결정의 commitment 는 세 measurement surface 에 wired:

<!-- verifies-key: pyproject.toml:pythonpath -->
<!-- verifies-key: scripts/_governance.py:LOAD_BEARING_PATHS -->
<!-- verifies-key: tests/test_dependency_graph_invariance.py:rag_core -->

- `pyproject.toml::pythonpath = ["."]` 가 사라지면 본 결정의 핵심 메커니즘 손실 — 재검토 트리거
- `LOAD_BEARING_PATHS` 가 파일명 hard-code 를 떠나면 디렉토리 재구성 비용 가설(본 ADR consequences) 무효화 — 재검토 트리거
- `test_dependency_graph_invariance.py` 가 `rag_core` back-edge 가드를 잃으면 ADR 0045 전제 붕괴 — 본 ADR 의 핵심 근거 무효화, 재검토 트리거
