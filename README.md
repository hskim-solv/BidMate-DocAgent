# BidMate Agent
**RFP 문서 이해를 위한 Agentic RAG 시스템**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) [![PR Eval Delta](https://github.com/hskim-solv/BidMate-DocAgent/actions/workflows/pr-eval.yml/badge.svg?branch=main)](https://github.com/hskim-solv/BidMate-DocAgent/actions/workflows/pr-eval.yml) [![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)](pyproject.toml)

## Business context

RFP/제안요청서는 한국 B2B/공공 입찰 시장에서 평균 수십~수백 페이지에 달하며, 검토자는 (a) 요건 추출, (b) 평가 기준 매핑, (c) 모순/누락 탐지를 수동으로 수행한다. 도메인 보고에 따르면 RFP 1건당 검토 시간은 복잡도에 따라 **약 4–20시간** 범위로 추정되고, 누락된 요건은 입찰 실격 또는 계약 조건 불이익으로 직결된다. 본 시스템은 위 세 단계를 grounded answer 형태로 자동화해 검토자가 *판단*에 집중하도록 시간을 절감하는 것을 목표로 한다.

> 비즈니스 임팩트는 보수적 추정 범위로 표기했다. 정확한 시간 단축률은 도메인 사용자 평가가 필요하며, 본 저장소의 정량 지표(groundedness, citation precision 등)는 *검토 보조 품질*의 proxy로 측정됐다. 비즈니스 임팩트 실증은 다음 실험 사이클 항목.

## TL;DR
- **문제**: 길고 복잡한 RFP 문서에서 실무 의사결정에 필요한 핵심 조건(예산/일정/요구사항/제출조건)을 빠르게 찾기 어렵습니다.
- **해결**: 질문 유형 분석 + metadata-first 검색 + local dense retrieval/reranking + 근거 검증/retry를 결합한 Agentic RAG 파이프라인을 구현했습니다.
- **시스템 설계**: 외부 LLM(GPT/Claude 등) 호출 없이, 검색 evidence에서 claim을 추출하고 citation을 연결하는 **extractive grounded-answer 파이프라인**입니다. 재현성 / 비용 영점 / LLM-as-judge confound 제거를 위해 generator를 의도적으로 extractive로 한정했습니다 ([ADR 0003](docs/adr/0003-structured-answer-citation-contract.md), [docs/answer-policy.md](docs/answer-policy.md)).
- **성과**: 공개 synthetic 평가셋 **n=36** (single_doc 11 / comparison 10 / follow_up 9 / abstention 6) 기준 단일 추출/다문서 비교/후속질문/부재판별의 근거 기반 응답 품질을 검증했습니다. 통계적 유의성 한계와 다음 실험 우선순위는 아래 [성능표 캐비뱃](#핵심-성능표-실측)에 정직하게 명시했습니다.
- **재현**: 실행 방법과 평가 절차를 문서화해 동일 환경에서 재검증 가능하도록 구성했습니다.

---

## Key technical contribution — comparison-aware balanced top-k

본 프로젝트의 가장 큰 차별점은 RFP 비교 질의(`query_type == "comparison"`)에서 발생하는 한쪽 문서 starvation을 막는 **balanced top-k retrieval ranking** 입니다. 일반 agentic RAG 튜토리얼에는 없는 RFP 도메인-특화 ranking 결정입니다.

**문제 패턴**: 단순 global top-k 컷은 score가 높은 한 문서가 결과 슬롯을 과점하면 다른 비교 대상 문서가 evidence에서 누락됩니다. 이로 인해 verifier가 근거 부족을 감지해 불필요한 retry를 트리거하거나 abstention으로 응답하는 실패가 발생합니다.

**설계**: Query Analyzer가 추출한 비교 target 별로 `min_per_target=1` 이상 evidence를 보장한 뒤, 남은 슬롯을 글로벌 score 순으로 채웁니다. 단일 문서 질의에서는 no-op으로 동작해 추가 비용이 없습니다.

**구현 / 테스트 / 설계 문서**:
- 구현: [`apply_comparison_balance()` (rag_core.py:1854)](rag_core.py), [`retrieve()` 내 호출 (rag_core.py:1838)](rag_core.py), 기본 설정 [`DEFAULT_COMPARISON_BALANCE` (rag_core.py:41)](rag_core.py)
- 테스트: [asymmetric corpus 균형 보장 (tests/test_fuzzy_retrieval.py:750)](tests/test_fuzzy_retrieval.py), [disabled 시 global ordering 보존 (tests/test_fuzzy_retrieval.py:769)](tests/test_fuzzy_retrieval.py), [single-doc no-op (tests/test_fuzzy_retrieval.py:781)](tests/test_fuzzy_retrieval.py)
- 설계 문서: [`docs/comparison-ranking.md`](docs/comparison-ranking.md) — target 식별, balance 알고리즘, diagnostics 스키마, eval 지표

> **One-line pitch**: RFP 비교 질의의 실패 패턴(한쪽 문서 starvation → verifier retry → abstention)을 발견하고, 이를 막는 retrieval ranking 전략을 설계·구현·테스트로 검증한 것이 본 프로젝트의 핵심 기여입니다.

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
- 핵심 지표: Answer Accuracy, Groundedness, Citation Precision, Claim Citation Alignment, Abstention Accuracy, Latency, Retry Rate
- 상세 수치/해석은 아래 성능표 및 `docs/` 문서 참고

### 4) 재현 (Reproducibility)
- 실행/평가 절차를 README에 요약하고, 상세 배경/실패사례/회고는 `docs/`로 분리
- 원본 RFP 비공개 제약을 고려해 공개 synthetic RFP 문서와 평가셋으로 재현 가능성 확보

---

## Portfolio Review Guide

채용 검토자가 빠르게 확인할 수 있도록 5분 리뷰 경로와 포트폴리오 관점의 핵심 질문을 함께 정리했습니다. 상세한 의사결정 흐름은 [`docs/portfolio-case-study.md`](docs/portfolio-case-study.md)를, 시니어 엔지니어링 시그널 관점의 narrative와 인터뷰 talking point는 [`docs/senior-positioning.md`](docs/senior-positioning.md)를 참고하세요.

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

비교 질의에 대한 grounded answer 출력 예시 ([`outputs/answer.json`](outputs/answer.json) 발췌). 각 claim에는 출처 문서/섹션 citation이 붙어 있고, diagnostics에 latency와 사용된 embedding backend가 함께 기록된다.

```json
{
  "query": "기관 A와 기관 B의 AI 요구사항 차이 알려줘",
  "answer": {
    "schema_version": 2,
    "status": "supported",
    "claims": [
      {
        "target": "기관 A",
        "claim": "사업 개요 — 기관 A는 AI 품질관리 플랫폼 구축을 추진한다.",
        "citations": [
          {"doc_id": "rfp-agency-a-ai-quality", "section": "문서 전체"}
        ]
      },
      {
        "target": "기관 B",
        "claim": "기관 B의 핵심 AI 요구사항은 데이터 거버넌스, MLOps 배포 자동화, 모델 모니터링이다.",
        "citations": [
          {"doc_id": "rfp-agency-b-mlops-governance", "section": "문서 전체"}
        ]
      }
    ]
  },
  "diagnostics": {"latency_ms": 1.91, "embedding_backend": "hashing", "pipeline": "naive_baseline"}
}
```

- 질의 실행 결과: `outputs/answer.json`
- 평가 요약: `reports/eval_summary.json`
- Planner/rewrite trace: `reports/traces/<run>/<case>.trace.json` (`eval/run_eval.py` 실행 시 생성, Git 미추적)
- Benchmark registry: `benchmarks/registry.json`
- Benchmark local artifacts: `artifacts/benchmarks/` (gitignored)
- PDF/HWP ingestion 진단 리포트: `data/index/ingestion_report.json` (`--metadata_csv` 사용 시)
- Visual parsing v2 artifact: `data/index/visual_artifacts/*.visual.json` (`--visual_input_dir` 또는 `--ingestion_mode visual` 사용 시)
- Parser-stage 평가 리포트: `reports/parser_eval_summary.json` (`eval/run_parser_eval.py` 사용 시)

---

## 답변 출력 정책

`outputs/answer.json`의 `answer`는 `schema_version: 2`인 구조화 객체입니다. `status`는 `supported`, `partial`, `insufficient` 중 하나이며, `status_reason`은 machine-readable 사유를 담습니다. `claims`의 각 항목은 `target`, `claim`, `support`, `citations`를 포함합니다. 근거가 부족하면 `claims`를 비우고 `insufficiency`에 사유와 확인 대상이 기록됩니다.

CLI와 리뷰 편의를 위해 같은 내용을 사람이 읽기 쉬운 `answer_text`로도 제공합니다. 자세한 예시는 [`docs/answer-policy.md`](docs/answer-policy.md)를 참고하세요.

Planner와 query rewrite 결정은 `outputs/answer.json`의 `trace`와 eval 실행 후 `reports/traces/`에서 확인할 수 있습니다. Grounding/eval hardening 변경 사항과 trace 해석 방법은 [`docs/grounding-eval-hardening.md`](docs/grounding-eval-hardening.md)를 참고하세요.

## Baseline policy

기본 CLI/eval reference는 `naive_baseline`입니다. 이 baseline은 fixed-size chunking, hashing dense top-k=4 retrieval, minimal grounded extractive answer prompt만 사용하며 metadata-first filtering, rerank, verifier/retry는 제외합니다.

현재 agentic pipeline은 `agentic_full` preset으로 유지합니다. 기본 control과 비교하려면 `app.py --pipeline agentic_full` 또는 benchmark의 `full` run을 사용합니다.

---

## 핵심 성능표 (실측)

**측정 환경**:
- **시스템 타입**: Extractive-only — 외부 LLM(GPT/Claude 등) 호출 없음, 의도된 설계입니다.
- **임베딩 백엔드**: 아래 metric table은 `hashing` (CI source of truth) 측정값입니다. `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 비교는 [Latency by embedding backend](#latency-by-embedding-backend) 보조 표를 참고하세요.
- **측정 범위**: `Latency p95` 컬럼은 query_analysis + context_resolution + answer_generation 합의 walltime입니다. retrieve / verify stage는 `reports/eval_summary.json`의 `stage_latency` 블록에서 별도 확인할 수 있습니다.
- **실행 환경**: macOS / CPU-only / Python 3.11 / 단일 워커.
- **Cold start 분리**: 첫 질의의 임베딩 모델 로드 시간은 별도 `cold_start_samples` 블록으로 분리 측정합니다 (hashing ≈ 2.1ms / sentence-transformers ≈ 5.7s).
- **평가셋**: 공개 synthetic n=36 (single_doc 11 / comparison 10 / follow_up 9 / abstention 6). 비공개 RFP eval은 [ADR 0005](docs/adr/0005-eval-split-public-synthetic-private-local.md)에 따라 분리합니다.

<!-- METRICS_TABLE:START -->
| Category | Metric | Score |
|---|---:|---:|
| Overall | Answer Accuracy | 0.828 |
| Single-doc extraction | Answer Accuracy | 1.000 |
| Multi-doc comparison | Groundedness Rate | 0.700 |
| Follow-up | Answer Accuracy | 0.750 |
| Evidence | Citation Precision | 0.459 |
| Evidence | Claim Citation Alignment | 0.971 |
| Evidence | Answer Format Compliance | 0.649 |
| Abstention | Abstention Accuracy | 0.125 |
| System | Latency (p50/p95) | p50 1.0ms / p95 1.9ms |
| System | Retry Rate | 0.000 |

### Ablation comparison

| Run | Pipeline | Top-k | Metadata-first | Rerank | Verifier/Retry | Accuracy | Groundedness | Citation | Claim Align | Format | Abstention | Retry | Latency p95 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| naive_baseline | naive_baseline | 4 | off | off | off | 0.828 | 0.676 | 0.459 | 0.971 | 0.649 | 0.125 | 0.000 | 1.9ms |
| full | agentic_full | auto | on | on | on | 0.862 | 0.892 | 0.878 | 0.966 | 0.892 | 1.000 | 0.351 | 1.9ms |
| hierarchical | agentic_full | auto | on | on | on | 0.862 | 0.892 | 0.878 | 0.966 | 0.892 | 1.000 | 0.351 | 2.2ms |
| no_metadata_first | agentic_full | auto | off | on | on | 0.793 | 0.838 | 0.635 | 0.929 | 0.838 | 1.000 | 0.000 | 1.7ms |
| no_rerank | agentic_full | auto | on | off | on | 0.862 | 0.892 | 0.878 | 0.966 | 0.892 | 1.000 | 0.351 | 2.0ms |
| no_verifier_retry | agentic_full | auto | on | on | off | 0.897 | 0.730 | 0.730 | 1.000 | 0.703 | 0.125 | 0.000 | 1.4ms |
<!-- METRICS_TABLE:END -->

### Latency by embedding backend

동일 ablation runs를 두 임베딩 백엔드(`hashing` fallback vs `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`)로 측정한 p95 latency 비교입니다. agentic pipeline에서는 두 백엔드가 거의 동일한 품질(accuracy 0.862 / groundedness 0.861)을 보이지만, **latency는 약 10–200× 차이**가 납니다. CI/CD 재현성을 위해 hashing을 기본으로 사용하고, sentence-transformers는 production-grade 품질 비교용으로 로컬에서 별도 측정합니다.

| Run | p95 (hashing) | p95 (sentence-transformers) | Notes |
|---|---:|---:|---|
| naive_baseline | 1.6ms | 367.4ms | dense retrieval만 — 전체 corpus에 ST 임베딩 비용 직격 |
| full | 1.9ms | 32.2ms | metadata-first가 dense 호출을 우회해 비용 절감 |
| hierarchical | 2.0ms | 30.0ms | full과 동일 운영, retrieval_mode 차이만 |
| no_metadata_first | 1.7ms | 15.4ms | 단순 dense — metadata 우회 없음 |
| no_rerank | 1.9ms | 30.1ms | metadata-first + 무 rerank |
| no_verifier_retry | 1.4ms | 16.9ms | verifier loop 제거 |

Cold start (모델 첫 로드): hashing ≈ 2.1ms / sentence-transformers ≈ 5.7s. ST cold start는 모델 캐시가 있어도 로드 + 초기 inference warm-up 비용이 발생합니다. 재실행 방법은 [실행 방법](#실행-방법-검증됨) 섹션의 `--embedding_backend` 플래그를 참고하세요.

> **데이터 범위**: 성능표는 공개 synthetic RFP 평가셋(n=36) 기준이며, hashing 백엔드 측정값입니다. 원본 RFP 데이터는 비공개 제약으로 저장소에 포함하지 않았습니다.
> **통계적 유의성 한계**: n=36은 ablation 차이의 통계적 유의성 검증에 충분치 않습니다. 평가셋 확대(n≥100)와 bootstrap CI 보고가 다음 실험 사이클의 최우선 항목입니다.
> **Latency 해석**: CLI 프로세스 walltime이며, 첫 질의의 모델 로드 시간은 위 cold-start sample로 분리 측정합니다. stage별 latency(retrieve/verify 포함)는 `reports/eval_summary.json`의 `stage_latency` 블록에서 확인할 수 있습니다.
> **시스템 설계 재확인**: 위 latency 측정에는 외부 LLM API 호출 비용이 포함되지 않습니다(extractive-only). 검증된 설계 가치 — `no_verifier_retry` ablation에서 accuracy는 약간 상승(0.862→0.897)하지만 groundedness가 큰 폭으로 하락(0.861→0.750)하는 점이 verifier/retry 루프의 설계 효용을 수치로 보여줍니다.

---

## 아키텍처 (요약)

```text
User Query
  ↓
Query Analyzer
  ↓
Planner (metadata-first, comparison-aware top_k)
  ↓
Retriever (staged metadata filters + dense/reranking + query-type top_k)
  ↓
Evidence Aggregator
  ↓
Verifier / Retry Loop
  ↓
Answer Generator (structured claims)
  ↓
Final Response (grounded)
```

비교 질의(`query_type == "comparison"`)에서는 단순 global top-k 컷이 한쪽 문서만 채워 verifier가 불필요한 retry를 트리거하는 문제를 막기 위해, 각 비교 대상에 최소 1개 이상의 evidence가 들어가도록 보장하는 balanced top-k 컷을 적용한다. Metadata filter staging, alias lexicon, follow-up carryover, ambiguity clarification, query-type top_k 진단은 [docs/retrieval-hardening.md](docs/retrieval-hardening.md)에 정리했다. 비교 ranking 상세 설계는 [docs/comparison-ranking.md](docs/comparison-ranking.md) 참고.

---

## 실행 방법 (검증됨)

두 가지 흐름을 제공합니다.

- **CLI 평가 흐름 (source of truth)**: `scripts/build_index.py` → `app.py` → `eval/run_eval.py`. 재현 가능한 측정/벤치마크/ablation 보고서 생성용.
- **API 데모 흐름 (리뷰어용)**: `make api` 또는 `make api-docker`로 FastAPI 서버를 띄워 `/health`, `/pipelines`, `POST /query` 엔드포인트로 RAG를 호출. 출력은 grounded answer/citation 계약을 그대로 보존. 자세한 내용은 [`docs/api-demo.md`](docs/api-demo.md).

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

Private 100-doc 실험은 원문/개별 예측 없이 anonymized aggregate만 요약합니다. 아래 fixture는 summary flow 검증용이며 실측 private 성과가 아닙니다.

```bash
python3 scripts/summarize_benchmark.py \
  --manifest benchmarks/examples/private100_aggregate_manifest.example.json \
  --registry /private/tmp/private100-registry.json \
  --docs /private/tmp/private100-summary.md
```

운영 기준과 커밋 금지 항목은 [`docs/private-100-doc-experiments.md`](docs/private-100-doc-experiments.md)를 참고하세요.

### 선택) Harness smoke run
재현 가능한 smoke 실행의 config snapshot, 로그, prediction, metric을 한 디렉터리에 모으려면 `python3 scripts/run_harness.py --config harness/smoke.yaml` 또는 `make harness-smoke`를 실행합니다. 산출물은 `artifacts/runs/<run_id>/` 아래에 생성되며 Git 추적 대상이 아닙니다. 자세한 흐름은 [`docs/harness.md`](docs/harness.md)를 참고하세요.

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

#### Optional real-data profile

공개 synthetic baseline과 성능표는 그대로 유지하고, 로컬 private 실데이터는 별도 profile로 실행합니다.

```bash
bash scripts/smoke_real.sh
```

기본 입력은 `data/data_list.csv`와 `data/files/`이며, 산출물은 `data/index/real100/`, `outputs/real100/`, `reports/real100/`에 생성됩니다. `eval/real_config.local.yaml`이 있으면 실데이터 gold 평가까지 실행하고, 없으면 인덱싱과 대표 질의까지만 실행합니다. 로컬 평가 파일은 `eval/real_config.example.yaml`을 복사해 만들며, `eval/*.local.yaml`은 Git 추적 대상이 아닙니다.

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
- Private 100-doc experiments: [`docs/private-100-doc-experiments.md`](docs/private-100-doc-experiments.md)
- 설계 배경 및 의사결정: [`docs/design-background.md`](docs/design-background.md)
- Chunking diagnostics: [`docs/chunking-diagnostics.md`](docs/chunking-diagnostics.md)
- PDF/HWP ingestion: [`docs/real-data-ingestion.md`](docs/real-data-ingestion.md)
- Visual parsing v2: [`docs/visual-ingestion-v2.md`](docs/visual-ingestion-v2.md)
- Citation grounding evaluation: [`docs/citation-grounding-eval.md`](docs/citation-grounding-eval.md)
- Grounding/eval hardening: [`docs/grounding-eval-hardening.md`](docs/grounding-eval-hardening.md)
- Reproducible harness: [`docs/harness.md`](docs/harness.md)
- API demo (FastAPI + container): [`docs/api-demo.md`](docs/api-demo.md)
- Architecture Decision Records: [`docs/adr/README.md`](docs/adr/README.md)
- Engineering governance (workflow map): [`docs/engineering-governance.md`](docs/engineering-governance.md)
- 답변 출력 정책: [`docs/answer-policy.md`](docs/answer-policy.md)
- 실패 사례 분석: [`docs/failure-cases.md`](docs/failure-cases.md)
- 회고 및 개선 방향: [`docs/retrospective.md`](docs/retrospective.md)
- 프로젝트 상세 문서 인덱스: [`docs/README.md`](docs/README.md)

---

## Notice
- 원본 RFP 문서는 외부 공유 제한으로 저장소에 포함하지 않았습니다.
- `data/raw` 문서는 공개 재현을 위해 작성한 synthetic RFP 샘플입니다.
- 본 저장소는 재현 가능한 구조/평가 관점의 포트폴리오 문서화를 목표로 합니다.
