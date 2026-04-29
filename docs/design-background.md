# 설계 배경 및 의사결정

## 핵심 의사결정
- Metadata-first Retrieval: 기관/사업 메타데이터로 후보군을 축소한 뒤 본문 검색
- Evidence-grounded Answering: 답변과 근거의 연결을 우선
- Abstention over Hallucination: 근거 부족 시 추측 대신 부재 응답
- Retry Loop: retrieval 실패 시 재시도 전략 적용

## 배경
RFP QA는 단순 검색보다 비교/정합성/부재판별이 중요해, retrieve→generate 단일 체인 대신 analyzer/planner/verifier를 포함한 agentic 구조를 채택했다.
