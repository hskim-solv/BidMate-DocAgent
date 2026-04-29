# BidMate Agent
**RFP 문서 이해를 위한 Agentic RAG 시스템**

## TL;DR
- **문제**: 길고 복잡한 RFP 문서에서 실무 의사결정에 필요한 핵심 조건(예산/일정/요구사항/제출조건)을 빠르게 찾기 어렵습니다.
- **해결**: 질문 유형 분석 + metadata-first 검색 + local dense retrieval/reranking + 근거 검증/retry를 결합한 Agentic RAG 파이프라인을 구현했습니다.
- **성과**: 공개 synthetic RFP 평가셋에서 단일 추출/다문서 비교/후속질문/부재판별을 포함한 근거 기반 응답 품질을 검증했습니다.
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
- 원본 RFP 비공개 제약을 고려해 공개 synthetic RFP 문서와 평가셋으로 재현 가능성 확보

---

## Demo / 산출물
- 질의 실행 결과: `outputs/answer.json`
- 평가 요약: `reports/eval_summary.json`

---

## 핵심 성능표 (실측)

<!-- METRICS_TABLE:START -->
| Category | Metric | Score |
|---|---:|---:|
| Single-doc extraction | Answer Accuracy | 1.000 |
| Multi-doc comparison | Groundedness Rate | 1.000 |
| Evidence | Citation Precision | 1.000 |
| Abstention | Abstention Accuracy | 1.000 |
| System | Latency (p50/p95) | p50 99.6ms / p95 7524.0ms |
| System | Retry Rate | 0.200 |
<!-- METRICS_TABLE:END -->

> 주의: 성능표는 공개 synthetic RFP 평가셋 기준입니다. 원본 RFP 데이터는 비공개 제약으로 저장소에 포함하지 않았습니다.
> Latency는 CLI 프로세스 기준이라 첫 질의의 로컬 임베딩 모델 로드 시간이 포함됩니다.

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

현재 공개본은 `data/raw`의 synthetic RFP 문서를 사용해 로컬에서 end-to-end RAG를 실행합니다. `auto` 모드는 캐시된 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 모델을 우선 사용하며, 모델을 사용할 수 없는 환경에서는 deterministic hashing embedding으로 자동 fallback합니다.

### 1) 환경 준비
```bash
# Python 3.10+ 권장
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) 인덱싱
```bash
python3 scripts/build_index.py --input_dir data/raw --output_dir data/index
```

### 3) 질의 실행
```bash
python3 app.py --input_dir data/index --output_dir outputs --query "기관 A와 기관 B의 AI 요구사항 차이 알려줘"
```

### 4) 평가 실행
```bash
python3 eval/run_eval.py --index_dir data/index --output_dir reports --config eval/config.yaml
```

### 5) 성능표 갱신
```bash
python3 scripts/update_readme_metrics.py --report reports/eval_summary.json --readme README.md
```

### 6) 일관성 검증 (reports ↔ README)
```bash
python3 scripts/update_readme_metrics.py --report reports/eval_summary.json --readme README.md --check
```

> 참고: 모델을 처음 내려받아 실제 sentence-transformers 인덱스를 만들려면 `--embedding_backend sentence-transformers`를 사용하세요. 네트워크가 제한된 환경에서는 `--embedding_backend hashing`으로 재현성을 우선한 로컬 실행이 가능합니다. 산출물 경로는 `data/index`, `outputs/`, `reports/`로 고정합니다.

평가 재현 기본 순서: **인덱싱(`scripts/build_index.py`) → 질의 실행(`app.py`) → 평가 실행(`eval/run_eval.py`) → 성능표 갱신(`scripts/update_readme_metrics.py`)**
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
- `data/raw` 문서는 공개 재현을 위해 작성한 synthetic RFP 샘플입니다.
- 본 저장소는 재현 가능한 구조/평가 관점의 포트폴리오 문서화를 목표로 합니다.
