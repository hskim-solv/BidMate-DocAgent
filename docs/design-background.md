# 설계 배경 및 의사결정

## 핵심 의사결정
- Metadata-first Retrieval: 기관/사업 메타데이터로 후보군을 축소한 뒤 dense/lexical 점수를 결합해 본문 검색
- Evidence-grounded Answering: LLM 호출 없이 근거 chunk의 문장을 추출해 답변과 citation의 연결을 우선
- Abstention over Hallucination: 근거 부족 시 추측 대신 부재 응답
- Retry Loop: retrieval 실패 시 재시도 전략 적용

## 배경
RFP QA는 단순 검색보다 비교/정합성/부재판별이 중요해, retrieve→generate 단일 체인 대신 analyzer/planner/verifier를 포함한 agentic 구조를 채택했다. 공개본은 원본 RFP 비공개 제약을 고려해 synthetic RFP와 결정적 평가셋으로 재현성을 우선한다.
