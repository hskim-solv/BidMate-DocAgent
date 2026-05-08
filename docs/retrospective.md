# 회고 및 향후 개선

## 회고
- 실무형 QA에서는 생성 품질보다 근거 정합성이 신뢰를 좌우함
- 다문서 비교와 부재판별은 평가셋 설계 단계부터 분리해야 안정적으로 개선 가능
- 공개 synthetic 평가는 query type별 6개씩 총 24개 케이스로 확장해 단일/다문서/후속질문/부재판별을 같은 실행 경로에서 비교한다.
- ablation은 naive keyword baseline, dense-only, metadata-first, rerank, verifier/retry를 분리해 각 설계 선택의 retrieval/answer 품질과 비용 영향을 추적한다.

## 향후 개선
- 공개 synthetic 외 실제 원문 기반 평가셋을 별도로 확보해 일반화 성능을 검증한다.
- citation 품질은 문서 ID 일치뿐 아니라 evidence text의 핵심 근거 포함 여부까지 계속 강화한다.
- latency 최적화는 retry가 발생한 부재판별 케이스와 첫 질의 모델 로드 비용을 분리해 추적한다.
- 실데이터 평가는 aggregate-only 산출물로 공유하고, case별 query/answer와 원문 경로는 로컬에만 남긴다.
