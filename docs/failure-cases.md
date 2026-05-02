# 실패 사례 분석

## 관찰된 실패 유형
1. 메타데이터 불일치로 인한 후보 문서 누락
2. 비교 질의에서 한쪽 문서만 상위 노출
3. 후속 질문에서 문맥 엔터티 소실

## 대응 전략
- 필터 완화 + 질의 재작성
- top-k/rerank 파라미터 조정
- 세션 컨텍스트 보강 및 검증 로그 점검
- 공개본에서는 agency/project/title metadata를 정규화해 exact/partial/fuzzy 후보를 확장한다.
- verifier가 topic/entity/doc coverage를 확인하고 실패 시 strict → reduced → relaxed 단계로 metadata filter를 완화한다.
- retrieval diagnostics에는 단계별 filter, 후보 수, 검증 실패 사유를 남겨 metadata mismatch를 추적한다.

## 후속 질문 문맥 해석 예시
- 성공 예시: `기관 A의 AI 요구사항은?` 이후 `그 기관이 요구한 보안 조건도 보여줘`는 session state의 `active_agencies=["기관 A"]`, `active_doc_ids=["rfp-agency-a-ai-quality"]`를 사용해 `기관 A 그 기관이 요구한 보안 조건도 보여줘`로 해석한다.
- 실패 방지 예시: `기관 A와 기관 B의 보안 요구사항 차이를 비교해줘` 이후 `그 기관의 보안 조건은?`은 활성 기관이 둘이라 `ambiguous_active_state`로 clarification 처리한다.
- 한계: session state는 명시한 JSON 파일 안에서만 유지된다. 파일을 지정하지 않거나 `--reset_session`을 사용하면 이전 턴은 이어지지 않는다.
