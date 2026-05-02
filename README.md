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
- **Answer Policy**: claim 단위 citation, partial/insufficient 상태, 사람이 읽는 `answer_text`를 함께 출력

### 3) 성과 (Outcome)
- 평가 범위: 단일 문서 추출, 단일 문서 심화 탐색, 다문서 비교, 후속 질문, 부재 정보 판별
- 핵심 지표: Answer Accuracy, Groundedness, Citation Precision, Abstention Accuracy, Latency, Retry Rate
- 상세 수치/해석은 아래 성능표 및 `docs/` 문서 참고

### 4) 재현 (Reproducibility)
- 실행/평가 절차를 README에 요약하고, 상세 배경/실패사례/회고는 `docs/`로 분리
- 원본 RFP 비공개 제약을 고려해 공개 synthetic RFP 문서와 평가셋으로 재현 가능성 확보

---

## Portfolio Review Guide

채용 검토자가 빠르게 확인할 수 있도록 5분 리뷰 경로와 포트폴리오 관점의 핵심 질문을 함께 정리했습니다. 상세한 의사결정 흐름은 [`docs/portfolio-case-study.md`](docs/portfolio-case-study.md)를 참고하세요.

### 5-minute reviewer path

처음 보는 리뷰어는 아래 순서로 확인하면 문제 정의, 데모, 검증 근거를 짧게 훑을 수 있습니다. 명령과 대표 질의는 [`docs/reviewer-evidence-pack.md`](docs/reviewer-evidence-pack.md)에 모았습니다.

1. **문제 이해**: 이 README의 `TL;DR`, `Quick Review`, `아키텍처`를 확인합니다.
2. **데모 실행**: `scripts/build_index.py`로 인덱스를 만들고 `app.py`로 대표 비교 질의를 실행합니다.
3. **예시 출력 확인**: `outputs/answer.json`에서 `answer.status`, claim별 citation, top-level evidence를 확인합니다.
4. **평가/ablation 확인**: `reports/eval_summary.json`, `docs/ablation-results.md`에서 metric과 설계 선택의 영향을 확인합니다.
5. **실패/개선 근거 확인**: `docs/failure-cases.md`, `docs/retrospective.md`에서 한계와 다음 실험 방향을 확인합니다.

이 프로젝트가 답하려는 핵심 질문은 다음 7개입니다.

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
- Benchmark registry: `benchmarks/registry.json`
- Benchmark local artifacts: `artifacts/benchmarks/` (gitignored)
- PDF/HWP ingestion 진단 리포트: `data/index/ingestion_report.json` (`--metadata_csv` 사용 시)
- Visual parsing v2 artifact: `data/index/visual_artifacts/*.visual.json` (`--visual_input_dir` 또는 `--ingestion_mode visual` 사용 시)
- Parser-stage 평가 리포트: `reports/parser_eval_summary.json` (`eval/run_parser_eval.py` 사용 시)

---

## 답변 출력 정책

`outputs/answer.json`의 `answer`는 구조화된 객체입니다. `status`는 `supported`, `partial`, `insufficient` 중 하나이며, `claims`의 각 항목은 `target`, `claim`, `support`, `citations`를 포함합니다. 근거가 부족하면 `claims`를 비우고 `insufficiency`에 사유와 확인 대상이 기록됩니다.

CLI와 리뷰 편의를 위해 같은 내용을 사람이 읽기 쉬운 `answer_text`로도 제공합니다. 자세한 예시는 [`docs/answer-policy.md`](docs/answer-policy.md)를 참고하세요.

## Baseline policy

기본 CLI/eval reference는 `naive_baseline`입니다. 이 baseline은 fixed-size chunking, hashing dense top-k=4 retrieval, minimal grounded extractive answer prompt만 사용하며 metadata-first filtering, rerank, verifier/retry는 제외합니다.

현재 agentic pipeline은 `agentic_full` preset으로 유지합니다. 기본 control과 비교하려면 `app.py --pipeline agentic_full` 또는 benchmark의 `full` run을 사용합니다.

---

## 핵심 성능표 (실측)

<!-- METRICS_TABLE:START -->
| Category | Metric | Score |
|---|---:|---:|
| Overall | Answer Accuracy | 0.947 |
| Single-doc extraction | Answer Accuracy | 1.000 |
| Multi-doc comparison | Groundedness Rate | 1.000 |
| Follow-up | Answer Accuracy | 0.857 |
| Evidence | Citation Precision | 0.519 |
| Evidence | Answer Format Compliance | 0.731 |
| Abstention | Abstention Accuracy | 0.143 |
| System | Latency (p50/p95) | p50 3.1ms / p95 5.8ms |
| System | Retry Rate | 0.000 |

### Ablation comparison

| Run | Pipeline | Top-k | Metadata-first | Rerank | Verifier/Retry | Accuracy | Groundedness | Citation | Format | Abstention | Retry | Latency p95 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| naive_baseline | naive_baseline | 4 | off | off | off | 0.947 | 0.731 | 0.519 | 0.731 | 0.143 | 0.000 | 5.8ms |
| full | agentic_full | auto | on | on | on | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.231 | 5.8ms |
| hierarchical | agentic_full | auto | on | on | on | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.231 | 6.4ms |
| no_metadata_first | agentic_full | auto | off | on | on | 0.947 | 0.962 | 0.750 | 0.962 | 1.000 | 0.000 | 4.7ms |
| no_rerank | agentic_full | auto | on | off | on | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.231 | 11.3ms |
| no_verifier_retry | agentic_full | auto | on | on | off | 1.000 | 0.769 | 0.769 | 0.769 | 0.143 | 0.000 | 4.5ms |
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
Verifier / Retry Loop
  ↓
Answer Generator (structured claims)
  ↓
Final Response (grounded)
```

---

## 실행 방법 (검증됨)

현재 공개본은 `data/raw`의 synthetic RFP 문서를 사용해 로컬에서 end-to-end RAG를 실행합니다. 기본 실행은 `naive_baseline` control이며, embedding `auto` 모드는 캐시된 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 모델을 우선 사용하고 모델을 사용할 수 없는 환경에서는 deterministic hashing embedding으로 자동 fallback합니다.

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

강한 agentic 파이프라인을 확인하려면 명시적으로 preset을 지정합니다.

```bash
python3 app.py \
  --input_dir data/index \
  --output_dir outputs \
  --query "기관 A와 기관 B의 AI 요구사항 차이 알려줘" \
  --pipeline agentic_full
```

후속 질문을 재현하려면 세션 상태 파일을 명시적으로 지정합니다. 상태에는 현재 활성 agency/project/topic/doc id와 최근 턴 요약이 JSON으로 저장되며, 생략된 참조가 모호하면 답을 추정하지 않고 clarification 응답으로 중단합니다.

```bash
python3 app.py \
  --input_dir data/index \
  --output_dir outputs \
  --query "기관 A의 AI 요구사항은?" \
  --session_state outputs/session_state.json \
  --reset_session

python3 app.py \
  --input_dir data/index \
  --output_dir outputs \
  --query "그 기관이 요구한 보안 조건도 보여줘" \
  --session_state outputs/session_state.json
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

### 7) Benchmark / ablation registry
```bash
python3 scripts/run_benchmark.py \
  --suite benchmarks/suites/public_synthetic_rfp.yaml \
  --ablations benchmarks/ablations/rag_quality_axes.yaml

python3 scripts/summarize_benchmark.py \
  --manifest artifacts/benchmarks/<run_id>/run_manifest.json
```

Benchmark source of truth는 `benchmarks/suites/`, `benchmarks/ablations/`, `benchmarks/registry.schema.json`에 둡니다. Raw predictions, traces, logs, latency samples, error examples는 `artifacts/benchmarks/` 아래에 생성되며 Git에 커밋하지 않습니다. 사람이 읽는 결과 해석은 [`docs/benchmarking.md`](docs/benchmarking.md)와 [`docs/ablation-results.md`](docs/ablation-results.md)를 참고하세요.

> 참고: 모델을 처음 내려받아 실제 sentence-transformers 인덱스를 만들려면 `--embedding_backend sentence-transformers`를 사용하세요. 네트워크가 제한된 환경에서는 `--embedding_backend hashing`으로 재현성을 우선한 로컬 실행이 가능합니다. 산출물 경로는 `data/index`, `outputs/`, `reports/`로 고정합니다.
> Chunking 기본값은 naive baseline 기준인 `--chunking_strategy fixed --chunk_max_chars 520 --chunk_overlap_sentences 1`입니다. section-aware 비교는 `--chunking_strategy auto` 또는 `section`으로 명시합니다.
> 질의 기본값은 `--pipeline naive_baseline`의 flat dense top-k=4 retrieval입니다. parent section 단위 재조립을 확인하려면 `app.py`에 `--pipeline agentic_full --retrieval_mode hierarchical`을 지정하거나 `eval/config.yaml`의 `hierarchical` ablation run을 실행합니다.

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

### 선택) Document visual parsing v2
원본 PDF/이미지 문서를 직접 파싱해 page/bbox/region metadata가 포함된 v2 artifact를 만들 수 있습니다. PDF는 text layer block을 우선 사용하고, text가 부족한 page 또는 이미지 파일은 OCR adapter를 사용합니다. HWP는 이번 v2에서 native visual parsing 대상이 아니며, metadata CSV visual mode에서는 기존 `텍스트` 컬럼으로 fallback하고 `visual_fallback_hwp`로 표시합니다.

```bash
python3 scripts/build_index.py \
  --visual_input_dir data/visual_samples \
  --output_dir data/index \
  --embedding_backend hashing
```

metadata CSV와 함께 v2를 비교하려면 다음처럼 실행합니다.

```bash
python3 scripts/build_index.py \
  --metadata_csv data/data_list.csv \
  --files_dir data/files \
  --ingestion_mode visual \
  --output_dir data/index \
  --embedding_backend hashing
```

이 모드는 `data/index/index.json`, `data/index/ingestion_report.json`, `data/index/visual_artifacts/*.visual.json`을 생성합니다. OCR에는 Python 패키지(`pymupdf`, `pdfplumber`, `pytesseract`, `Pillow`, `opencv-python-headless`)와 시스템 Tesseract 설치가 필요합니다. OCR 엔진이 없으면 text-layer PDF는 계속 처리할 수 있지만 image-only 문서는 `ocr_unavailable`로 실패합니다.

visual parsing 품질은 QA 평가와 별도로 parser-stage 평가로 확인합니다. 이 평가는 이미 생성된 `*.visual.json` artifact와 gold 기대값을 비교하며 OCR text, layout block, section boundary, table, field, bbox/page-region 지표를 `reports/parser_eval_summary.json`에 기록합니다. 공개 fixture로 먼저 실행해 report 형태를 확인할 수 있습니다.

```bash
python3 eval/run_parser_eval.py \
  --artifact_dir eval/fixtures/parser_visual_v2 \
  --gold eval/parser_visual_v2_gold.yaml \
  --output_dir reports \
  --run_name visual_v2_fixture \
  --parser_version 2
```

실제 visual ingestion 산출물을 비교할 때는 같은 gold 형식에서 `doc_id`와 artifact 이름을 맞춘 뒤 `--artifact_dir data/index/visual_artifacts`를 지정합니다. README의 핵심 성능표는 기존 QA 평가(`reports/eval_summary.json`) 기준으로 유지하고, parser-stage 지표는 별도 리포트로 관리합니다.

---

## 상세 설계 링크
- 포트폴리오 case study: [`docs/portfolio-case-study.md`](docs/portfolio-case-study.md)
- Benchmarking: [`docs/benchmarking.md`](docs/benchmarking.md)
- Ablation results: [`docs/ablation-results.md`](docs/ablation-results.md)
- 설계 배경 및 의사결정: [`docs/design-background.md`](docs/design-background.md)
- Chunking diagnostics: [`docs/chunking-diagnostics.md`](docs/chunking-diagnostics.md)
- PDF/HWP ingestion: [`docs/real-data-ingestion.md`](docs/real-data-ingestion.md)
- Visual parsing v2: [`docs/visual-ingestion-v2.md`](docs/visual-ingestion-v2.md)
- 답변 출력 정책: [`docs/answer-policy.md`](docs/answer-policy.md)
- 실패 사례 분석: [`docs/failure-cases.md`](docs/failure-cases.md)
- 회고 및 개선 방향: [`docs/retrospective.md`](docs/retrospective.md)
- 프로젝트 상세 문서 인덱스: [`docs/README.md`](docs/README.md)

---

## Notice
- 원본 RFP 문서는 외부 공유 제한으로 저장소에 포함하지 않았습니다.
- `data/raw` 문서는 공개 재현을 위해 작성한 synthetic RFP 샘플입니다.
- 본 저장소는 재현 가능한 구조/평가 관점의 포트폴리오 문서화를 목표로 합니다.
