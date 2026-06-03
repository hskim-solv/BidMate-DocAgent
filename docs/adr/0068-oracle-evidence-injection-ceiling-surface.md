# ADR 0068 — Oracle-evidence 주입을 컴포넌트 천장(ceiling) 측정 표면으로

- Status: Accepted
- Implemented: #1282 — `rag_core.run_rag_query_with_oracle_evidence` + `_phase_oracle_inject`, `eval/run_eval.build_oracle_evidence`, `oracle_evidence_source` ablation 필드
- Date: 2026-05-22
- Authors: Hyunsoo Kim
- Related: ADR 0001 (naive_baseline byte-identical), ADR 0005 (private/public eval 분리), ADR 0045 (phase 분해 + back-edge 0), ADR 0054 (conditional-on-answer scorer semantics), ADR 0059 (failure-mode classifier)
- Issue: #1282

> **Current-policy note (2026-06-03)**: this ADR remains an accepted historical
> decision record for the oracle-evidence ceiling measurement surface. Its
> legacy `real-100` / 221-case motivating measurements are not current
> claim-bearing private-eval evidence. New task, PR, claim, and handoff evidence
> must use the `real100_v2` aggregate-only surface in
> [Surface Map](../evaluation/surface-map.md), unless the maintainer explicitly
> re-enables another private-eval surface.

## Context

real-100 단독 측정 표면(ADR 0052, n=221)에서 파이프라인은 직렬 의존 `_phase_analyze → _phase_retrieve_loop → _phase_build_answer` (ADR 0045) 를 따른다. 상류(검색)가 하류(검증·답변) 천장을 가둔다 — 즉 "검색이 완벽했다면 답변·검증이 얼마나 맞힐 수 있었나?"를 현재 측정 표면은 답할 수 없다.

실측 신호가 이를 뒷받침한다 (#1282 batch1, n=221 hashing offline): `retrieval_miss` = 83/221 (38%) 가 모든 검색-time row-knob arm(`full_kiwi` / `hierarchical` / `no_metadata_first`)에서 거의 불변 — 검색 누락이 row-knob 이 아니라 임베딩에 묶여 있음을 시사한다. 그러나 "검색을 고정·완벽화했을 때 verifier_false_negative(49) 와 정확도가 어디까지 오르는가"는 검색과 분리해 측정할 수단이 없었다. 컴포넌트별 headroom 을 모르면 무거운 real-100 런 예산을 어디에 쓸지 triage 할 수 없다.

## Decision

1. **신규 eval-only 진입점 `run_rag_query_with_oracle_evidence(index, query, oracle_evidence, *, ...)`** (`rag_core.py`).
   - 실제 `_phase_analyze` 와 `_phase_build_answer` 를 실행하되 `_phase_retrieve_loop` 만 **`_phase_oracle_inject` 로 대체** — 주입된 oracle evidence 로 검색을 우회.
   - 실제 `verify_evidence` 와 `select_supporting_evidence` branch 를 그대로 실행 → 검증·답변 천장을 정직하게 측정 (검색만 우회).
   - LangGraph/ReAct dispatch 미경유 — 직렬 phase 경로 강제.

2. **`_phase_oracle_inject(ctx, oracle_evidence)`** 는 `_phase_retrieve_loop` 의 post-condition (writes: `stage_attempts`, `retry_count`, `plan`, `evidence`, `verified`, `verification_reasons`, `retrieved_chunk_ids`) 을 그대로 미러링 → `_phase_build_answer` 가 동형(同型) `ctx` 를 소비. ADR 0045 mutation-contract (`tests/test_phase_mutation_contract.py`) 가 lock-in.

3. **gold → oracle evidence 투영 `build_oracle_evidence(case, index)`** (`eval/run_eval.py`).
   - 기존 `derive_gold_chunk_ids` (chunk-recall scorer 와 동일 gold 집합) 재사용 + `rag_retrieval` evidence-item shape 으로 투영. `score=1.0` (verifier low-score floor 위), `retrieval_mode="oracle"`.
   - 빈 gold (abstention 케이스) → `[]` → verify 자연 실패 → 답변 abstain (올바른 천장 동작).

4. **신규 ablation 필드 `oracle_evidence_source`** (값 `"gold"` = 주입 발화, 미설정/`""` = OFF).
   - `eval/run_eval.normalize_run_config` 에서 **raw run dict 에서 직접** 파싱 — `resolve_pipeline_config` / `PIPELINE_CONFIG_KEYS` 를 **거치지 않음** → production code path 미도달.

5. **기본 OFF — opt-in.** 어떤 arm 도 `oracle_evidence_source` 를 설정하지 않으면 `evaluate_run` 은 기존 `run_rag_query` 를 그대로 호출 → 기존 summary byte-equal.

## Why these specific choices

| 결정 | 근거 |
|---|---|
| eval 레이어(`evaluate_run`)에서 분기, `run_rag_query` 미변경 | `case` dict(gold)는 eval 하네스에만 존재. production 진입점을 건드리지 않아 ADR 0001 byte-identity 가 by-construction 보존. |
| `PIPELINE_CONFIG_KEYS` 비경유 | oracle 은 파이프라인 knob 이 아니라 eval-harness knob. resolve_pipeline_config 에 넣으면 preset resolution 표면이 오염 → 기본 경로 회귀 위험. raw row 에서 직접 읽어 격리. |
| 실제 `verify_evidence` 실행 (verify 우회 안 함) | 목적은 **검증·답변 천장**. verify 까지 우회하면 측정이 무의미. 검색만 우회해야 "검색 완벽 시 verifier+generator 천장"이 나옴. |
| 기존 phase 헬퍼 재사용, 병렬 파이프라인 신설 금지 | ADR 0045 분해를 그대로 활용. CLAUDE.md "shadow dict 모델 추가 금지" 정신 — `_phase_oracle_inject` 는 `_phase_retrieve_loop` 의 대체이지 새 계약 아님. |
| `derive_gold_chunk_ids` 재사용 | chunk-recall scorer 의 gold 집합과 동일 정의 → oracle 천장과 recall 진단이 같은 gold 위에서 정합. |
| `score=1.0`, `score_parts={}` | verifier `low_top_score` floor(`rag_verifier.py:153`, `<0.18`) 회피 — oracle 은 정의상 완벽 검색이므로 floor 미적용이 맞음. |

## Consequences

- **신규 측정 표면 1차원 추가** — `oracle_evidence_source: gold` arm 이 검색을 우회한 답변·검증 천장 (accuracy / abstention / failure_category) 을 emit. Wave 0 headroom triage 와 Wave 3(verifier/synthesis) 컴포넌트 분리의 prerequisite 충족.
- 검색이 묶고 있던 하류 천장을 분리 측정 가능 → real-100 런 예산을 "천장 근처(개선 여지 작음)" vs "천장 멀음(개선 여지 큼)" 컴포넌트로 triage.
- production code path 0 변경 — `run_rag_query`, `api/`, `eval/config.yaml`, `eval/real_config.local.yaml` 무수정. 기본 오프라인 경로 SSoT 불변.

## Invariance check

- **ADR 0001** (`naive_baseline` byte-identical) — production 진입점 `run_rag_query` 미변경, oracle 은 별도 진입점이며 기본 OFF. naive_baseline golden + langgraph JSON-identity 회귀 테스트 통과로 입증.
- **ADR 0003** (answer dict `schema_version=2`) — oracle 경로도 동일 `_phase_build_answer` 를 거쳐 동일 answer dict 계약 생산. 변경 없음.
- **ADR 0005** (private/public 분리) — oracle evidence 는 런타임에 gitignored local config 의 gold 필드에서 파생, 신규 커밋 데이터 0. per-case 출력은 기존 trace 와 동일 boundary (gitignored), aggregate 만 commit.
- **ADR 0045** (phase 분해 + back-edge 0) — `_phase_oracle_inject` 는 `rag_core` 내부 leaf, supporting 모듈로의 back-edge 미추가. mutation-contract 테스트가 ctx-write 집합 고정.
- **ADR 0054** (conditional-on-answer scorer semantics) — 빈 gold → `[]` → abstain branch 가 ADR 0054 의 None-skip semantic 과 정합.

## Verification

<!-- verifies-key: rag_core.py:def run_rag_query_with_oracle_evidence -->
<!-- verifies-key: rag_core.py:def _phase_oracle_inject -->
<!-- verifies-key: eval/run_eval.py:def build_oracle_evidence -->
<!-- verifies-key: tests/test_oracle_evidence_injection.py:class OracleBypassTest -->

## Out-of-scope

- **oracle 천장 실측 런** — `oracle_full` arm 은 현재 승인된 private-eval 표면에서만 재측정한다. 기본 후속은 `real100_v2` aggregate-only evidence 이며, legacy real-100 재실행은 maintainer 가 명시적으로 re-enable 한 경우에만 허용한다.
- **comparison query_type balance** — `derive_gold_chunk_ids` 가 per-entity 균형을 강제하지 않아 비교 케이스 천장이 과소평가될 수 있음. v1 은 비교 케이스도 그대로 측정하되 해석 시 주의. 정밀화는 별 issue.
- **oracle-subqueries → retrieval 천장** — planner 우회 검색 천장(plan dict 주입)은 본 PR 의 evidence 주입과 별개 표면. 필요 시 별 ADR.
