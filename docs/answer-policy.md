# 답변 출력 정책

이 문서는 최종 답변 생성 레이어가 어떤 형식으로 근거를 제시하고, 근거 부족을 어떻게 표시하는지 정리한다. 공개본은 외부 LLM 없이 retrieval evidence에서 문장을 추출해 claim과 citation을 연결한다.

## 상태 값

| status | 의미 | evidence | claims |
|---|---|---|---|
| `supported` | 모든 필수 대상과 주제가 근거로 확인됨 | 있음 | 1개 이상 |
| `partial` | 비교 질문에서 일부 대상만 근거로 확인됨 | 확인된 대상만 있음 | 1개 이상 |
| `insufficient` | 답변 가능한 근거를 찾지 못함 | 없음 | 없음 |

`answer_text`는 사람이 빠르게 읽기 위한 요약이고, 검증 가능한 계약은 `answer.status`, `answer.claims`, `answer.insufficiency`, top-level `evidence`를 기준으로 본다.

## 좋은 답변 예시

```json
{
  "status": "supported",
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

좋은 답변은 claim마다 citation이 있고, citation의 chunk text가 claim을 직접 지지한다. 비교 질문에서는 대상별 claim을 나눠 스캔 가능하게 유지한다.

## 나쁜 답변 예시

```json
{
  "status": "supported",
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
  "status": "insufficient",
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

비교 질문에서 한쪽만 확인되면 `partial`로 표시하고, 확인되지 않은 대상은 `missing_targets`에 남긴다. 이 경우 확인된 claim만 citation과 함께 제공하며, 빠진 대상을 추측해 채우지 않는다.

## 실패 유형

- unsupported over-answering: 근거가 없는데 `supported`로 답함
- partial coverage hidden: 비교 질문에서 한 대상만 찾고 전체 답변처럼 제시함
- citation drift: claim은 맞아 보이지만 citation chunk가 같은 claim을 직접 지지하지 않음
- unreadable comparison: 여러 대상의 답을 한 문장에 섞어 리뷰가 어려움
