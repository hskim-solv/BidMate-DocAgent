# BidMate Agent
**RFP 문서 이해를 위한 Agentic RAG 시스템**

## TL;DR
- **문제**: 길고 복잡한 RFP 문서에서 실무 의사결정에 필요한 핵심 조건(예산/일정/요구사항/제출조건)을 빠르게 찾기 어렵습니다.
- **해결**: 질문 유형 분석 + metadata-first 검색 + dense retrieval/reranking + 근거 검증/retry를 결합한 Agentic RAG 파이프라인을 구현했습니다.
- **성과**: 단일 추출/다문서 비교/후속질문/부재판별을 포함한 평가셋에서 근거 기반 응답 품질과 안정성을 검증했습니다.
- **재현**: 실행 방법과 평가 절차를 문서화해 동일 환경에서 재검증 가능하도록 구성했습니다.

---

## Quick Review

### 1) 문제 (Problem)
- RFP는 문서 길이·형식·용어가 다양해 단순 키워드 검색만으로는 정확한 의사결정 지원이 어렵습니다.
- 특히 다문서 비교, 후속 질문, 문서 부재 정보 판별이 병목이 됩니다.

### 2) 해결 (Solution)
- **Query Analyzer**: 질문 유형 및 핵심 엔터티(기관/사업/주제) 추출
- **Planner**: 메타데이터 필터 중심 검색 전략 수립
- **Retriever**: dense retrieval + reranking
- **Verifier/Retry**: 근거 부족 시 재검색·재시도 후 grounded answer 생성

### 3) 성과 (Outcome)
- 평가 범위: 단일 문서 추출, 단일 문서 심화 탐색, 다문서 비교, 후속 질문, 부재 정보 판별
- 핵심 지표: Answer Accuracy, Groundedness, Citation Precision, Abstention Accuracy, Latency, Retry Rate
- 상세 수치/해석은 아래 성능표 및 `docs/` 문서 참고

### 4) 재현 (Reproducibility)
- 실행/평가 절차를 README에 요약하고, 상세 배경/실패사례/회고는 `docs/`로 분리
- 원본 RFP 비공개 제약을 고려해 코드·구조·평가 방법 중심으로 재현 가능성 확보

---

## Demo / 스크린샷
- 데모 캡처(질문 → 검색 근거 → 최종 답변) 추가 예정
- 스크린샷 자리표시자: `docs/assets/demo-overview.png`

---

## 핵심 성능표 (실측)

| Category | Metric | Score |
|---|---:|---:|
| Single-doc extraction | Answer Accuracy | _TBD_ |
| Multi-doc comparison | Groundedness Rate | _TBD_ |
| Follow-up QA | Follow-up Consistency | _TBD_ |
| Abstention | Abstention Accuracy | _TBD_ |
| System | Latency (p50/p95) | _TBD_ |
| System | Retry Rate | _TBD_ |

> 주의: 저장소 공개본에는 원본 데이터 비공개 제약이 있어, 수치 공개 범위는 프로젝트 정책에 따라 업데이트됩니다.

---

## 아키텍처 (요약)

```text
User Query
  ↓
Query Analyzer
  ↓
Planner (metadata-first)
  ↓
Retriever (dense + reranking)
  ↓
Evidence Aggregator
  ↓
Answer Generator
  ↓
Verifier / Retry Loop
  ↓
Final Response (grounded)
```

---

## 실행 방법 (검증됨)

### 1) 환경 준비
```bash
# Python 3.10+ 권장
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) 인덱싱
```bash
python scripts/build_index.py --input_dir data/raw --output_dir data/index
```

### 3) 질의 실행
```bash
python app.py --input_dir data/index --output_dir outputs --query "기관 A와 기관 B의 AI 요구사항 차이 알려줘"
```

### 4) 평가 실행
```bash
python eval/run_eval.py --input_dir outputs --output_dir reports --config eval/config.yaml
```

> 참고: 현재 공개 저장소는 **샘플 모드**를 지원합니다. 산출물 경로는 `data/index`, `outputs/`, `reports/`로 고정합니다.
> - 인덱스: `data/index/index.json`
> - 질의 응답: `outputs/answer.json`
> - 평가 요약: `reports/eval_summary.json`

---

## 상세 설계 링크
- 설계 배경 및 의사결정: [`docs/design-background.md`](docs/design-background.md)
- 실패 사례 분석: [`docs/failure-cases.md`](docs/failure-cases.md)
- 회고 및 개선 방향: [`docs/retrospective.md`](docs/retrospective.md)
- 프로젝트 상세 문서 인덱스: [`docs/README.md`](docs/README.md)

---

## Notice
- 원본 RFP 문서는 외부 공유 제한으로 저장소에 포함하지 않았습니다.
- 본 저장소는 재현 가능한 구조/평가 관점의 포트폴리오 문서화를 목표로 합니다.
