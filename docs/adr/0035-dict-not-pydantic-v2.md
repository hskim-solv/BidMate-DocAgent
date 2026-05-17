# 0035: Answer dict — parallel Pydantic / TypedDict shadow 모델 금지

- **Status**: accepted
- **Date**: 2026-05-13
- **Related**: [ADR 0003](0003-structured-answer-citation-contract.md) (answer 계약, `schema_version: 2`), [`CLAUDE.md` §Prohibited](../../CLAUDE.md), [`api/schemas.py`](../../api/schemas.py) (경계 전용 Pydantic 사용), [issue #451](https://github.com/hskim-solv/BidMate-DocAgent/issues/451)

## TL;DR

- `run_rag_query` answer dict가 ADR 0003 계약 — 파이프라인 내부에서 Pydantic/TypedDict/dataclass shadow 모델 금지.
- `api/schemas.py`의 FastAPI 경계 검증은 허용 (downstream of `run_rag_query`).
- 외부 시니어 리뷰의 Pydantic v2 재요청에 대응해 한 줄 prose 금지 규정을 명시적 trade-off 기록으로 격상.

## 배경

`run_rag_query`는 ADR 0003에 의해 pinned된 plain Python `dict` 반환 (`schema_version: 2`, `status`, `claims[{target, claim, support, citations[]}]`, `evidence[…]`). `CLAUDE.md` §"Prohibited"가 명시: *"Adding a parallel pydantic / TypedDict model that shadows `run_rag_query`'s answer dict — the dict is the contract."*

이 금지가 한 줄 prose로만 존재했다. 외부 시니어 리뷰(2026-05, §A2-S4)가 런타임 안전성과 IDE ergonomics를 인용해 Pydantic v2 검증을 재제기. 문서화된 ADR 없이는 반복적 questioning에서 살아남지 못함 — 이 문서가 한 줄을 명시적 trade-off 기록으로 변환.

두 압력 충돌:
1. **단일 진리 소스**: ADR 0003이 이미 계약을 pin. Parallel 모델은 두 권위 정의를 만들어 silently 발산 가능.
2. **검증 안전성**: 호출자가 타입 체크된 접근을 원할 수 있음; raw dict 접근은 오류 가능. 정답은 검증이 *어디에* 있느냐지 존재 여부가 아니다.

## 결정

`run_rag_query`가 생산하는 answer dict가 내부 계약. *파이프라인 내부에서* Pydantic / TypedDict / dataclass 모델이 shadow 금지.

**허용 사항:**

- `api/schemas.py`가 FastAPI 응답 경계에서 dict를 검증하는 Pydantic 모델 정의 가능 (`Answer.model_validate(result)`). `run_rag_query` downstream — retrieval, verification, answer-generation 내부에는 절대 두지 않음.
- 내부 helper 함수가 IDE 힌트 위해 `TypedDict` 사용 가능, 단 타입 annotation이 런타임에서 load-bearing이지 않음 (no `isinstance` 검사, no `.model_dump()` 파이프라인 round-trip).

**스키마 변경 protocol**: answer dict의 신규 필드는 먼저 dict에 추가(backward compat 위해 default 제공), 그 다음 `api/schemas.py`, 마지막 eval runner. 역순 금지.

## 결과

**Easier:**
- 필드 추가/이름 변경 1회: `run_rag_query` 반환 블록 + eval runner 편집. 모델 sync 단계 없음.
- CI eval byte-identical 유지: serialization round-trip이 silently 필드 누락 불가.
- `schema_version` bump가 의미 유지 — dict 계약 추적, 모델 버전 drift 아님.

**Harder / constrained:**
- 파이프라인 layer로부터 auto-generated OpenAPI 스키마 없음. dict 진화 시 `api/schemas.py`를 수동 sync 필수.
- Raw dict 키 IDE autocomplete가 typed 모델보다 약함. TypedDict escape hatch가 런타임 계약 오염 없이 해결.

**Contract locked in:**
- `schema_version: 2` literal in `rag_answer.py` (`ANSWER_SCHEMA_VERSION`).
- `status` enum: `supported | partial | insufficient` — 호출자는 다른 문자열로 분기 금지.
- Eval 파이프라인(`eval/run_eval.py`)이 `status_reason.code` 및 `claims[].citations[].chunk_id`로 keying — 변경 시 version bump + eval 회귀 검사 필요.

## 검토한 대안

- **Full Pydantic v2 내부 모델**: 기각. 모든 `run_rag_query` 호출이 `.model_validate()` + `.model_dump()` round-trip 동반. 더 중요한 점: dict와 모델이 두 진리 소스가 됨 — 스키마 변경이 양쪽 touch, merge 충돌이 silently stale 모델 + 정확한 dict 생산.
- **JSON Schema 외부 검증**: eval-side 계약 체크로 트래킹, 런타임 파이프라인 가드 아님. 이 ADR과 충돌 없음; 내부 typing과 직교.
- **API 경계 only Pydantic (채택 패턴)**: 외부 호출자에게 노출되는 surface에서 정확히 한 번 검증. 파이프라인 내부 dual 계약 없음; 런타임 비용은 FastAPI 레이어 요청당 O(1), 내부 함수 호출당 아님.
