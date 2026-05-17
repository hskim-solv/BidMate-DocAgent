# 0045: rag_core leaf 마이그레이션 계획 — embedding helpers + comparison_targets routing

- **Status**: accepted (completed by PR-G2 #847 + PR-G3 #861 + PR-G4 #872)
- **Date**: 2026-05-15
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) · CLAUDE.md
  *Repository map* (rag_retrieval / rag_verifier / rag_answer / rag_query
  분리) · issue #762
- **Deciders**: hskim

## TL;DR

- `rag_retrieval` 이 `rag_core` 로의 late-import 두 곳을 가지고 있음 (embedding primitives + comparison_targets)
- Plan A: embedding primitives 를 새 leaf `rag_embedding.py` 로 이동
- Plan B: comparison_targets 를 `rag_query` 직접 import (이미 거기 있음)

> **2026-05-15 업데이트 (G4):** 6개 ADR-0045 leaf 모듈 (`rag_query`, `rag_retrieval`, `rag_verifier`, `rag_answer`, `rag_embedding`, `rag_indexing`) 모두 `rag_core` 로의 **0** import 에지 — top-level + function-level. 이 불변량은 [`tests/test_dependency_graph_invariance.py`](../../tests/test_dependency_graph_invariance.py) (issue #872) 가 회귀 테스트. back-edge 재도입하는 모든 미래 PR (function-body late-import 포함) 은 CI 실패.

## 배경

`rag_core.py` 가 1728 LOC. PR-H1a/b (issue #459 / #461) 와 PR-J1/J2/J3 (issue #465 / #468 / #478) 가 retrieval / verifier / answer / query 를 sibling leaf 모듈로 추출했지만 import 그래프가 아직 깨끗하지 않음: `rag_retrieval.py` 가 두 함수 내부에서 late-import 로 `rag_core` 에 reach back.

### 관찰된 late-import 인벤토리 (2026-05-15, branch `main`)

| Call site | Late-imported symbols |
|-----------|----------------------|
| [`rag_retrieval.py:168`](../../rag_retrieval.py:168) | `comparison_targets_for_analysis` |
| [`rag_retrieval.py:490`](../../rag_retrieval.py:490) | `DEFAULT_EMBEDDING_MODEL`, `DEFAULT_HASH_DIM`, `embed_texts`, `hashing_embeddings` |

call site 2 × 심볼 5. 다른 3개 분리 모듈은 이미 top-level-clean:

- `rag_query.py`, `rag_verifier.py`, `rag_answer.py` — `rag_core` import **0** (top-level + late)

CLAUDE.md 자체가 미완성 상태 인정:

> *"`rag_core.py` 는 여전히 orchestration + 많은 utilities → cycle 회피 위한 late-import (의존성 그래프 leaf 아님)."*

본 ADR 은 cleanup 계획. 실제 코드 마이그레이션은 본 ADR **범위 외** — 별도 PR (GEF loop 의 `G2`, `/Users/hskim/.claude/plans/gleaming-forging-dove.md` 추적) 로 land.

### 왜 둘로 나누나, 하나가 아니라

5개 late-imported 심볼이 두 semantic 그룹으로 나뉨:

1. **Embedding primitives** — `embed_texts`, `hashing_embeddings`, `_embed_with_openai`, `sentence_transformer_cache_available`, `huggingface_offline`, `expand_features`, `EmbeddingResult`, `DEFAULT_EMBEDDING_MODEL`, `DEFAULT_HASH_DIM`. `rag_retrieval.embed_query_for_index`, `rag_core` 인덱스 빌드, `scripts/build_index.py` — 3개 독립 consumer 가 사용. 검색 전용 아님.
2. **Query-analysis 출력 reader** — `comparison_targets_for_analysis` 는 PR-J3 추출의 일환으로 **이미 `rag_query.py:397` 에 정의**; `rag_core` 는 re-export 만. 검색의 late-import 는 stale routing 결정, 누락된 home 아님.

다른 fix (새 leaf 모듈 vs import-source 변경) 라서 별도 PR 에 속함.

## 결정

### Plan A: embedding primitives → 새 leaf 모듈 `rag_embedding.py`

`rag_embedding.py` 를 sibling leaf 로 생성, 기존 [`rag_text_processing.py`](../../rag_text_processing.py) / [`rag_metadata_processing.py`](../../rag_metadata_processing.py) 패턴 모델링. 이동:

- 상수: `DEFAULT_EMBEDDING_MODEL`, `DEFAULT_HASH_DIM`
- Dataclasses: `EmbeddingResult`
- 함수: `embed_texts`, `_embed_with_openai`, `sentence_transformer_cache_available`, `huggingface_offline`, `hashing_embeddings`, `expand_features`

Consumer 업데이트:

- `rag_core.py` — top-level `from rag_embedding import …`; 다운스트림 코드 (tests, eval 스크립트) 안 깨지게 re-export alias 유지
- `rag_retrieval.py` — late-import 블록을 top-level `from rag_embedding import …` 로 교체
- `scripts/build_index.py` — `from rag_core import DEFAULT_EMBEDDING_MODEL` 를 `from rag_embedding import …` 로 교체

### Plan B: comparison_targets routing

`rag_retrieval.py:168` 에서 late-import 를 `rag_query` 의 top-level import 로 변경:

```python
# old:
from rag_core import comparison_targets_for_analysis  # inside function
# new (top-level):
from rag_query import comparison_targets_for_analysis
```

방향 안전성 검증 (2026-05-15):

```
$ grep -nE "^from rag_|^import rag_" rag_query.py
# (rag_retrieval 참조 없음)
```

`rag_query` 는 이미 leaf; `rag_retrieval → rag_query` 는 clean DAG 에지.

### Sequencing

- Plan B 는 **2줄 변경** (import 이동 1 + late-import 삭제 1). 같은 파일 (`rag_retrieval.py`) 타겟이고 같은 `rag_core` back-edge 제거라 Plan A 와 같은 PR 묶음 허용.
- Plan A + B 합쳐서 = G2 PR.

## 검토한 대안

### (a) embedding primitives 를 `rag_retrieval.py` 로 이동

*거부*: `scripts/build_index.py` 는 검색 불필요하며 cross-encoder reranker, query expander 등의 import 비용 지불 안 해야 함. Embedding primitives 는 검색 전용 아님.

### (b) `rag_core` 를 정식 home 으로 두고 late-import 를 accepted 로 문서화

*거부*: CLAUDE.md 가 이미 미완성 작업으로 호출. late-import 는 런타임에는 작동하지만 정적 분석 (IDE go-to-definition, mypy reachability) 패배시키고 신규 contributor 에게 아키텍처 부채 신호. senior-portfolio 가독성 비용.

### (c) text/metadata helpers 도 분리하는 단일 big-bang 마이그레이션

*거부*: text/metadata helpers 는 *이미* 추출됨 (`rag_text_processing.py`, `rag_metadata_processing.py`). embedding 마이그레이션을 존재하지 않는 추가 분리와 묶으면 이득 없이 diff 부풀음. one concern per PR (CLAUDE.md).

### (d) 실제 이동 대신 Python `__all__` / re-export 사용

*거부*: re-export 는 cycle 못 깸; rag_core 가 여전히 함수 본체 소유. 전체 목적은 `rag_core` 를 얇게 만드는 것.

## 결과

**Wins**

- `rag_retrieval.py` 가 `rag_core` 에 대해 진정한 leaf — back-edge 없음
- `rag_core.py` 가 ~150 LOC 축소 (embedding 블록). GEF loop 가 명명한 ~600-LOC orchestration-only 목표로의 step
- `scripts/build_index.py` 가 embed 위해 rag_core 불필요 — 인덱스 빌드가 원칙적으로 full retrieval/answer 스택 로딩 없이 실행 가능
- IDE / 정적 분석기가 진정한 의존성 그래프 보고

**Costs**

- 유지할 새 모듈 파일 1개. 완화: 기존 `rag_*_processing.py` 패턴 따르므로 온보딩 비용 0 에 가까움
- `rag_core` 의 re-export alias 는 그래프 깨끗함 관점에서 dead weight. eval 스크립트 안 깨지도록 첫 마이그레이션에서 **의도적 유지**; import site audit 후 제거 스케줄링 follow-up ADR 가능

**미변경**

- ADR 0001 naive-baseline 불변량: `embed_texts` / `hashing_embeddings` 시맨틱이 이동 후 byte-identical — G2 PR 은 순수 재배치, logic 변경 아님
- ADR 0003 답변 계약: 미터치 (답변 생성이 embed 안 함)
- `EMBEDDING_BACKEND` env 계약: 미변경 (env-var dispatch 는 `embed_texts` 내부 거주, as-is 이동)

### 본 ADR 범위 외

- embedding 너머 추가 `rag_core` slim-down (ingestion 분리, `_RunContext` 재배치) — GEF plan 의 G3 가 cover
- `rag_core` 의 re-export shim 제거 — 무기한 연기. 외부 caller (`tests/`, `scripts/`, `eval/`, `demo/`, `api/`) 가 shim 의존; deprecate 는 leaf-migration 목표 너머의 별도 breaking 변경
- pgvector / Qdrant adapter 구현 — GEF plan 의 F1/F2

## Verification

본 ADR 은 plan-only. PR 시점 워킹 트리에 존재해야 할 두 전제조건 (G2 가 코드 이동 후 *제거* 검증):

<!-- verifies-key: rag_retrieval.py:from rag_core import -->
<!-- verifies-key: rag_query.py:def comparison_targets_for_analysis -->

G2 구현 PR 은 다음을 보여야 함:

1. `make smoke` 통과 (`EMBEDDING_BACKEND=hashing`, hashing 경로 사용)
2. `bash scripts/test.sh` 통과 (full pytest)
3. `make real-eval-delta` 가 §5b parity 보임 (본 ADR 불변량은 *bit-identical embeddings* — 모든 델타는 버그)
4. `git grep -nE "^\s+from rag_core" rag_retrieval.py rag_query.py rag_verifier.py rag_answer.py` 가 **0** 라인 반환
5. ADR 0001 `naive_baseline` 프리셋 golden 미변경
