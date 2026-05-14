# 답변 출력 정책

이 문서는 최종 답변 생성 레이어가 어떤 형식으로 근거를 제시하고, 근거 부족을 어떻게 표시하는지 정리한다. 공개본은 외부 LLM 없이 retrieval evidence에서 문장을 추출해 claim과 citation을 연결한다.

## 상태 값

| status | 의미 | evidence | claims |
|---|---|---|---|
| `supported` | 모든 필수 대상과 주제가 근거로 확인됨 | 있음 | 1개 이상 |
| `partial` | (a) 비교 질문에서 일부 대상만 근거로 확인됨, 또는 (b) 검증 토픽 중 일부만 evidence에 매칭됨 (relaxed 단계의 partial-topic grounding) | 확인된 대상만 있음 | 1개 이상 |
| `insufficient` | 답변 가능한 근거를 찾지 못함 | 없음 | 없음 |

현재 답변 객체는 `schema_version: 2`를 사용한다. `answer_text`는 사람이 빠르게 읽기 위한 요약이고, 검증 가능한 계약은 `answer.schema_version`, `answer.status`, `answer.status_reason`, `answer.claims`, `answer.insufficiency`, top-level `evidence`를 기준으로 본다.

`status_reason`은 machine-readable 진단 필드다.

| field | 의미 |
|---|---|
| `code` | `verified`, `partial_comparison`, `partial_topic_grounding`, `insufficient_evidence`, `context_clarification`, `metadata_ambiguity_clarification` 중 하나 |
| `verified` | verifier 기준 통과 여부. 단, 명시 요청된 비교 대상이 corpus에 없으면 verifier 설정과 무관하게 `partial`이 될 수 있음. relaxed 단계의 partial-topic 매칭으로 통과한 경우 `verified=True`이지만 status는 `partial`로 surface된다 |
| `verification_reasons` | `topic_not_grounded`, `partial_topic_grounding`, `missing_comparison_doc:*`, `missing_requested_entity:*` 같은 근거 부족 또는 약한 근거 사유 |

## 좋은 답변 예시

```json
{
  "schema_version": 2,
  "status": "supported",
  "status_reason": {
    "code": "verified",
    "verified": true,
    "verification_reasons": []
  },
  "query_type": "comparison",
  "summary": "기관 A: ... 기관 B: ...",
  "claims": [
    {
      "target": "기관 A",
      "claim": "기관 A의 핵심 AI 요구사항은 모델 품질관리, 보안 통제, 로그 추적이다.",
      "support": "기관 A의 핵심 AI 요구사항은 모델 품질관리, 보안 통제, 로그 추적이다...",
      "citations": [
        {
          "doc_id": "rfp-agency-a-ai-quality",
          "chunk_id": "rfp-agency-a-ai-quality::chunk-002",
          "section": "AI 요구사항"
        }
      ]
    }
  ],
  "insufficiency": null
}
```

좋은 답변은 claim마다 citation이 있고, citation의 chunk text가 claim을 직접 지지한다. visual parsing v2 인덱스에서는 citation에 `page_span`과 `regions`가 추가될 수 있어 page/bbox 근거 위치까지 추적할 수 있다. page/region gold가 있는 평가셋은 [`citation-grounding-eval.md`](../eval/citation-grounding-eval.md)의 기준으로 문서 단위 citation precision과 위치 grounding을 분리해 본다. 비교 질문에서는 대상별 claim을 나눠 스캔 가능하게 유지한다.

## 나쁜 답변 예시

```json
{
  "schema_version": 2,
  "status": "supported",
  "status_reason": {
    "code": "verified",
    "verified": true,
    "verification_reasons": []
  },
  "summary": "기관 A는 블록체인 납품 실적이 있습니다.",
  "claims": [],
  "insufficiency": null
}
```

이 답변은 근거 없는 claim을 supported로 표시했고, claim 단위 citation도 없다. 이런 케이스는 `answer_format_compliance`와 abstention 평가에서 실패해야 한다.

## 근거 부족 정책

unsupported 질문은 다음처럼 답한다.

```json
{
  "schema_version": 2,
  "status": "insufficient",
  "status_reason": {
    "code": "insufficient_evidence",
    "verified": false,
    "verification_reasons": ["topic_not_grounded"]
  },
  "query_type": "abstention",
  "summary": "제공된 공개 샘플 RFP 근거에서는 '기관 A의 블록체인 납품 실적은?'에 답할 수 있는 내용을 찾지 못했습니다.",
  "claims": [],
  "insufficiency": {
    "reasons": ["topic_not_grounded"],
    "missing_targets": ["기관 A"],
    "missing_topics": ["블록체인", "납품"]
  }
}
```

비교 질문에서 한쪽만 확인되면 `partial`로 표시하고, 확인되지 않은 대상은 `missing_targets`에 남긴다. 명시적으로 요청된 기관이 corpus metadata에 없을 때도 `missing_requested_entity:*` 사유를 남겨 `partial`로 처리한다. 이 경우 확인된 claim만 citation과 함께 제공하며, 빠진 대상을 추측해 채우지 않는다.

## 계약 강제 메커니즘

`schema_version: 2` 계약은 두 단계로 강제된다. extractive 경로가 `status` / `claims` / `citations` / `status_reason` / `insufficiency`를 결정적으로 락하고, optional LLM 합성 경로는 `summary` / `answer_text`만 다시 쓸 수 있다 ([ADR 0001](../adr/0001-preserve-naive-baseline.md) extractive baseline invariant, [ADR 0011](../adr/0011-llm-synthesis-as-additive-ablation.md) additive synthesis).

### 1단계 — extractive (락 단계)

[`rag_core.py`](../rag_core.py) 안의 함수가 verifier 출력을 그대로 status로 굳힌다.

| 단계 | 함수 (rag_core.py) | 강제 내용 |
|---|---|---|
| Evidence 검증 | `verify_evidence` (L2252) | topic/entity coverage 체크. `allow_partial_topic`은 retrieval 마지막 시도에서만 `True`. partial-topic 매칭으로 통과하면 `verified=True`지만 status는 `partial`로 surface (#69 회귀 방지) |
| Claim 빌드 | `build_claims` / `build_comparison_claims` / `build_extract_claims` (L2495–2520) | claim마다 `chunk_id`가 evidence list에 존재함을 by-construction으로 보장 |
| Status 결정 | `answer_status` (L2594), `answer_status_reason` (L2469) | `ANSWER_STATUS_{SUPPORTED,PARTIAL,INSUFFICIENT}` (L215–217) 셋 중 하나로 클램프. 다른 값은 emit 불가 |

이 단계의 출력은 다운스트림에서 immutable로 취급된다.

### 2단계 — LLM synthesis (additive 단계, 옵션)

[`rag_synthesis.py`](../rag_synthesis.py) `synthesize_answer`는 위 단계 출력을 입력으로 받아 `summary`와 `answer_text`만 다시 쓴다. 6개 게이트가 직렬로 실행되며 하나라도 실패하면 fallback flag와 reason을 메타에 박은 채 extractive 답변을 그대로 반환한다.

| Gate | Trigger | `fallback_reason` |
|---|---|---|
| Backend 알 수 없음 | `BIDMATE_SYNTHESIS_BACKEND` 미지원 값 | `unknown_backend:<value>` |
| Evidence 없음 | `allowed_chunk_ids`가 빈 set | `no_evidence_chunks` |
| Backend 호출 실패 | 예외 발생 (network, parse, quota 등) | `backend_error:<exc_type>:<truncated>` |
| Summary 빈 문자열 | `payload.summary`가 비어 있음 | `empty_summary` |
| Unauthorized chunk | `used_chunk_ids ⊄ evidence chunk_ids` | `unauthorized_chunk_ids:<head>` |
| Claim 밖 chunk | `used_chunk_ids ⊄ claim citation chunk_ids` | `chunks_outside_claims:<head>` |

이 게이트들은 ADR 0011의 "no new chunk_ids" hard postcondition을 코드 레벨로 구현한다. LLM이 hallucinated citation을 만들어도 set-membership 체크로 즉시 거부되고 extractive 출력이 surface된다.

### `schema_version` bump 규칙

위 contract의 어느 부분이라도 *비호환*으로 바뀌면 `schema_version`을 3으로 올리고 [ADR 0003](../adr/0003-structured-answer-citation-contract.md) supersede를 새 ADR로 기록한다. additive 변경(예: `claims[].citations[]`에 optional `page_span` 추가)은 bump 없음. `claims` shape 변경, status enum 추가/제거, `status_reason.code` 의미 변경은 모두 비호환.

### 테스트 매트릭스

| 테스트 | 잠그는 contract |
|---|---|
| [`tests/test_llm_synthesis.py`](../tests/test_llm_synthesis.py) | 6개 게이트의 fallback reason 정확성, ADR 0011 additive 불변(extractive와 LLM 경로가 같은 `claims`/`citations` 반환) |
| [`tests/test_partial_topic_grounding.py`](../tests/test_partial_topic_grounding.py) | partial-topic 통과 시 `status=partial` 강제 (#69 회귀 가드) |
| [`tests/test_followup_entity_injection.py`](../tests/test_followup_entity_injection.py) | follow-up entity carryover에서 `status=partial` 비강등 |
| `eval/run_eval.py`의 `score_answer_format` | `Answer Format Compliance` metric — claim 단위 citation 누락 시 점수 차감 |

### 평가 surface와의 연결

eval pipeline은 `answer.status_reason.code` / `answer.claims` / top-level `evidence`만 검증 입력으로 사용한다 (`answer_text`는 검증 대상 아님). 따라서 위 두 단계가 만든 출력이 평가 metric에 그대로 surface된다.

## 실패 유형

- unsupported over-answering: 근거가 없는데 `supported`로 답함
- partial coverage hidden: 비교 질문에서 한 대상만 찾고 전체 답변처럼 제시함
- citation drift: claim은 맞아 보이지만 citation chunk가 같은 claim을 직접 지지하지 않음
- unreadable comparison: 여러 대상의 답을 한 문장에 섞어 리뷰가 어려움
