# Planner & Query-Rewrite Trace Schema (v1)

이 문서는 `run_rag_query` 가 생성하고 `eval/run_eval.py` 가 `reports/traces/<run>/<case_id>.trace.json` 에 저장하는 로컬 trace 산출물에 대한 reviewer 대상 레퍼런스다.

목표는 reviewer 가 `.trace.json` 파일 하나를 열어 *계획(planner)이 무엇을 결정했는지, 왜 쿼리를 재작성(rewrite)했는지(또는 하지 않았는지), 시간이 어디에 쓰였는지* 를 파이프라인 재실행 없이 재구성할 수 있도록 하는 것이다.

빌더는 [rag_core.py](../../rag_core.py) 에 있다: `build_query_rewrite_trace`, `build_planner_trace`, `build_result_trace`.

## 최상위 구조

```jsonc
{
  "schema_version": 1,
  "query_rewrite": { ... },
  "planner":       { ... },
  "answer_schema": { ... }
}
```

`schema_version` 은 현재 `1` 이다. 하위 호환 가능한 필드 추가(새 optional 키)는 이 값을 올리지 않는다. 호환성을 깨는 구조 변경은 올린다(`#63` answer-schema v2 와 짝).

## `query_rewrite`

대화 컨텍스트 해소(context resolution)와 검색(retrieval) 전에 수행된 prefix 주입을 기록한다.

| Field | Type | Notes |
|---|---|---|
| `original_query` | str | 이번 턴의 사용자 쿼리 원문. |
| `resolved_query` | str | 실제 검색에 전달된 쿼리. 재작성이 없으면 `original_query` 와 동일. |
| `rewritten` | bool | `resolved_query != original_query` 일 때만 True. |
| `rewrite_type` | str | `conversation_state_prefix`, `explicit_context`, `clarification_required`, `none` 중 하나. |
| `context_source` | str | 해소 신호의 출처: `conversation_state`, `context_entities`, `query`, 또는 `none`. |
| `context_status` | str | `resolved`, `needs_clarification`, `not_needed` 등. |
| `context_resolution_confidence` | float (0.0–1.0) | 해소 결정의 신뢰도. `CONTEXT_RESOLUTION_THRESHOLD` 미만이면 clarification 을 유발. |
| `reason` | str | 진단 태그(예: `weak_active_state`, `ambiguous_active_state`, `no_active_state`). |
| `context_entities` | list[str] | 이월된 기관(agency) / 엔티티 이름. |
| `context_projects` | list[str] | 이월된 사업(project) 이름. |
| `active_doc_ids` | list[str] | 활성 대화 상태의 문서 ID. |
| `readable_summary` | str | 재작성 결과를 한 줄로 기술한 사람 친화 설명. |

### 읽는 요령

- `rewrite_type=clarification_required` 와 낮은 `context_resolution_confidence` 로 보류(abstain)한 follow-up 은 전형적인 "지시 대상을 특정하지 못함" 경로다.
- `rewrite_type=conversation_state_prefix` + 비어 있지 않은 `context_entities` 는 이전 턴의 기관/사업이 쿼리 앞에 덧붙여졌음을 의미한다.

## `planner`

검색/답변 계획(plan)과 stage 별 시도(attempt)를 기록한다.

| Field | Type | Notes |
|---|---|---|
| `query_type` | str | `single_doc`, `comparison`, `follow_up`, `abstention`. |
| `pipeline` | str | 활성 파이프라인 이름(예: `agentic_full`, `naive`). |
| `prompt_profile` | str | 이번 실행에 선택된 prompt profile. |
| `strategy` | str | 상위 수준 검색 전략 라벨. |
| `retrieval_mode` | str | `flat` 또는 계층(hierarchical) 모드. |
| `metadata_first` | bool | metadata-first 경로를 탔는지 여부. |
| `rerank` | bool | 재순위(reranker) 활성화 여부. |
| `verifier_retry` | bool | 검증기(verifier) 기반 재시도 활성화 여부. |
| `stage_sequence` | list[str] | 순서대로 시도한 필터 stage(예: `["strict", "reduced", "relaxed"]`). |
| `selected_stage` | str | 답변을 만들어 낸 최종 필터 stage. |
| `selected_top_k` | int \| null | 사용된 최종 top-k. |
| `retrieval_budget` | object | top-k 계획 세부 정보(기본값, query-type override, 사유). |
| `metadata_candidate_count` | int \| null | metadata 해소로 얻은 후보 문서 수. |
| `metadata_selected_doc_ids` | list[str] | metadata-first 해소로 선택된 문서 ID. |
| `metadata_ambiguous` | bool | metadata 해소가 모호성(ambiguity)을 표시했는지 여부. |
| `comparison_coverage` | object \| null | 비교(comparison) 커버리지 진단(해당 시). |
| `stage_latencies_ms` | object | `{query_analysis_ms, context_resolution_ms, answer_generation_ms}`. |
| `attempts` | list[object] | stage 별 시도 기록: `stage`, `top_k`, `verified`, `verification_reasons`, `metadata_doc_ids`. |
| `readable_summary` | str | 계획을 한 줄로 요약. 예: `single_doc planned with agentic_full stage=strict top_k=4 metadata_docs=['rfp-agency-a-ai-quality']`. |

### 읽는 요령

- 재시도 체인을 보려면 `attempts` 를 순서대로 따라간다. 첫 `verified=true` 가 답변 생성에 투입된 것이다.
- stage 수준의 `retrieve_ms` / `verify_ms` 는 각 attempt 항목 안에 있고, 최상위 `stage_latencies_ms` 는 분석 / 컨텍스트 해소 / 답변 생성을 다룬다.
- `metadata_selected_doc_ids` 와 `query_rewrite.active_doc_ids` 를 짝지어 계획이 활성 대화 컨텍스트를 존중했는지 확인한다.

## `answer_schema`

답변 envelope(`schema_version`, `status`, `status_reason`, `query_type`, `claim_count`)를 그대로 반영하므로, reviewer 가 답변 파일을 열지 않고도 검증기가 보류했는지 판단할 수 있다.

## 프라이버시 & 마스킹(redaction)

trace 에는 인덱싱된 코퍼스의 문서 ID, 기관 이름, 사업 이름이 담긴다. 이들은 **로컬 파일에만**(`reports/traces/...`) 기록되며 이 저장소의 어떤 코드 경로로도 업로드되지 않는다.

문서 ID / 엔티티가 민감한 reviewer 인계(hand-off) 상황에서는:

```bash
# mask both doc IDs and entities
python eval/run_eval.py --config eval/dev_config.yaml --redact_trace all

# mask only doc IDs
python eval/run_eval.py --config eval/dev_config.yaml --redact_trace doc_ids
```

마스킹은 리스트 길이를 보존한 채 각 리스트 항목을 리터럴 `"<redacted>"` 로 치환하므로, 구조적 형태(예: "문서 ID 두 개가 선택됨")는 여전히 검사 가능하다. `planner.readable_summary` 도 함께 재작성되어 요약 문자열로 선택된 문서 ID 가 새지 않는다. `run_rag_query` 가 반환하는 in-memory 결과는 절대 변형되지 않으며, 마스킹은 trace 기록 경계에서만 적용된다.

`eval_summary.json` 은 실효 마스킹 상태를 `trace_redaction` 아래에 기록한다.

## 회귀(regression) 커버리지

`tests/test_fuzzy_retrieval.py` 가 다음을 강제한다:

- Schema 버전 1.
- `query_rewrite` 와 `planner` 의 필수 필드 집합(향후 PR 이 필드를 조용히 누락하지 못하도록).
- `stage_latencies_ms` 키가 존재하며 숫자형일 것.
- `redact_trace` 가 입력을 변형하거나 길이를 잃지 않고 리스트 필드를 마스킹할 것.
