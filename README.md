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

## Portfolio Review Guide

채용 검토자가 빠르게 확인할 수 있도록 이 프로젝트는 아래 7개 질문에 답하는 구조로 정리했습니다. 상세한 의사결정 흐름은 [`docs/portfolio-case-study.md`](docs/portfolio-case-study.md)를 참고하세요.

1. **왜 이 문제를 골랐는가**: RFP QA는 단순 검색보다 다문서 비교, 근거 정합성, 부재판별이 중요해 RAG 역량을 검증하기 좋습니다.
2. **성공 기준을 어떻게 정했는가**: 답변 정확도뿐 아니라 Groundedness, Citation Precision, Abstention, Latency/Retry를 함께 봅니다.
3. **어떤 실패가 났는가**: 메타데이터 불일치, 비교 질의의 한쪽 문서 누락, 후속 질문의 엔터티 소실을 주요 실패로 분리했습니다.
4. **어떤 실험을 비교했는가**: keyword-only, dense-only, metadata-first+dense/rerank, verifier/retry 유무를 비교 축으로 삼았습니다.
5. **왜 A안이 아니라 B안을 택했는가**: 생성 유창성보다 근거 재현성과 검증 가능성을 우선해 metadata-first + verifier/retry 구조를 채택했습니다.
6. **에이전트 산출물을 어떻게 검증했는가**: evidence doc id, expected terms, abstention 여부, README metric sync check로 산출물을 검증합니다.
7. **다음 실험을 왜 그렇게 설계했는가**: 평가셋 확대, citation 자동 검증, latency/retry 비용 분석을 다음 병목 확인 실험으로 둡니다.

---

## Demo / 산출물
- 질의 실행 결과: `outputs/answer.json`
- 평가 요약: `reports/eval_summary.json`
- PDF/HWP ingestion 진단 리포트: `data/index/ingestion_report.json` (`--metadata_csv` 사용 시)

---

## 핵심 성능표 (실측)

<!-- METRICS_TABLE:START -->
| Category | Metric | Score |
|---|---:|---:|
| Overall | Answer Accuracy | 1.000 |
| Single-doc extraction | Answer Accuracy | 1.000 |
| Multi-doc comparison | Groundedness Rate | 1.000 |
| Follow-up | Answer Accuracy | 1.000 |
| Evidence | Citation Precision | 1.000 |
| Abstention | Abstention Accuracy | 1.000 |
| System | Latency (p50/p95) | p50 1.1ms / p95 2.2ms |
| System | Retry Rate | 0.250 |

### Ablation comparison

| Run | Retrieval | Metadata-first | Rerank | Verifier/Retry | Accuracy | Groundedness | Citation | Abstention | Retry | Latency p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| full | flat | on | on | on | 1.000 | 1.000 | 1.000 | 1.000 | 0.250 | 2.2ms |
| hierarchical | hierarchical | on | on | on | 1.000 | 1.000 | 1.000 | 1.000 | 0.250 | 1.5ms |
| no_metadata_first | flat | off | on | on | 1.000 | 1.000 | 0.833 | 1.000 | 0.000 | 1.8ms |
| no_rerank | flat | on | off | on | 1.000 | 1.000 | 1.000 | 1.000 | 0.250 | 1.8ms |
| no_verifier_retry | flat | on | on | off | 1.000 | 0.750 | 0.750 | 0.000 | 0.000 | 1.5ms |
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
> Chunking 기본값은 `--chunking_strategy auto --chunk_max_chars 520 --chunk_overlap_sentences 1`입니다. `auto`는 heading/section 구조가 있으면 section-aware chunk metadata를 저장하고, 단일 본문처럼 구조가 약하면 fixed fallback을 사용합니다.
> 질의 기본값은 flat child-chunk retrieval입니다. parent section 단위 재조립을 확인하려면 `app.py`에 `--retrieval_mode hierarchical`을 지정하거나 `eval/config.yaml`의 `hierarchical` ablation run을 실행합니다.

평가 재현 기본 순서: **인덱싱(`scripts/build_index.py`) → 질의 실행(`app.py`) → 평가 실행(`eval/run_eval.py`) → 성능표 갱신(`scripts/update_readme_metrics.py`)**
> - 인덱스: `data/index/index.json`
> - 질의 응답: `outputs/answer.json`
> - 평가 요약: `reports/eval_summary.json`

### 선택) PDF/HWP + data_list.csv ingestion
비공개 원본 파일을 로컬에 보유한 경우 `data_list.csv`의 `텍스트` 컬럼을 v1 본문 소스로 사용해 PDF/HWP 메타데이터를 인덱스에 반영할 수 있습니다. `data/data_list.csv`와 `data/files/`는 비공개 데이터이므로 Git 추적 대상이 아닙니다.

```bash
python3 scripts/build_index.py \
  --metadata_csv data/data_list.csv \
  --files_dir data/files \
  --output_dir data/index \
  --embedding_backend hashing
```

이 모드는 `data/index/index.json`과 함께 `data/index/ingestion_report.json`을 생성합니다. 리포트에는 문서별 indexed/failed 상태와 `missing_file`, `empty_text`, `unsupported_file_format`, `duplicate_doc_id` 같은 실패 사유가 기록됩니다.

---

## 상세 설계 링크
- 포트폴리오 case study: [`docs/portfolio-case-study.md`](docs/portfolio-case-study.md)
- 설계 배경 및 의사결정: [`docs/design-background.md`](docs/design-background.md)
- Chunking diagnostics: [`docs/chunking-diagnostics.md`](docs/chunking-diagnostics.md)
- PDF/HWP ingestion: [`docs/real-data-ingestion.md`](docs/real-data-ingestion.md)
- 실패 사례 분석: [`docs/failure-cases.md`](docs/failure-cases.md)
- 회고 및 개선 방향: [`docs/retrospective.md`](docs/retrospective.md)
- 프로젝트 상세 문서 인덱스: [`docs/README.md`](docs/README.md)

---

## Notice
- 원본 RFP 문서는 외부 공유 제한으로 저장소에 포함하지 않았습니다.
- `data/raw` 문서는 공개 재현을 위해 작성한 synthetic RFP 샘플입니다.
- 본 저장소는 재현 가능한 구조/평가 관점의 포트폴리오 문서화를 목표로 합니다.
