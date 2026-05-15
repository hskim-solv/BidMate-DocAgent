# Eval Dataset Spec — Public Synthetic RFP Surface

공개 합성 평가셋의 구성, 평가 방법론, 재현 절차를 담은 reviewer-facing 명세서입니다.

- **평가셋 분리 정책**: [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md)
- **비공개 100-doc 집계**: [`docs/real-data/private-100-doc-experiments.md`](../real-data/private-100-doc-experiments.md) (별도 문서)

---

## 1. Corpus

### 문서 구성 (7개 합성 RFP 문서)

| Doc ID | 기관 | 도메인 | 용도 | sections |
|---|---|---|---:|---:|
| rfp-agency-a-ai-quality | 기관 A | AI 품질관리 | 표준 단일문서 / 비교 | 4 |
| rfp-agency-b-mlops-governance | 기관 B | MLOps 자동화 | 표준 단일문서 / 비교 | 4 |
| rfp-agency-c-chatbot | 기관 C | 고객지원 챗봇 | 표준 단일문서 / 비교 | 3 |
| rfp-agency-d-spectrometer-probe | 기관 D | 분광기 시스템 | chunk-boundary probe | 3 |
| rfp-agency-e-water-quality-main | 기관 E (본) | 수질 모니터링 | single-turn ambiguity probe | 2 |
| rfp-agency-e-water-quality-supplement | 기관 E (부속) | 수질 모니터링 | multi-doc follow-up probe | 2 |
| rfp-common-submission | 공통 | 제출조건·산출물 | 공통 참조 문서 | 2 |

**합성 사유**: 한국 공공기관 발주 RFP의 실제 구조(추진목표 / 일정 / 예산 / 요구사항 / 제출조건)를 그대로 모방하되, 기관명·금액·일정을 익명 처리한 합성 문서. 원본 RFP 데이터는 저작권·계약 제약으로 저장소에 포함하지 않음 (ADR 0005).

**도메인 특성**: 한국어 기관명 약칭(기관명 음운변화 포함) + alias-entity 패턴이 포함되어 있어, 형태소 분석 기반 lexical matcher와 metadata-first retrieval 모두 실전 조건에 노출됨.

---

## 2. Queries (n=42)

> **`eval/config.yaml` 기준 n=42**. `eval/dev_queries_v1.jsonl` (44-line source)과 포맷이 다르며, jsonl은 human-readable 설계 문서 역할. 두 파일의 case 수 차이는 config의 `prior_turns` 방식 직렬화 때문.

### 카테고리 분포

| Category | n | 설명 |
|---|---:|---|
| `single_doc` | 14 | 단일 RFP 문서에서 항목(예산·일정·요구사항) 추출 |
| `comparison` | 10 | 두 기관 RFP의 특정 항목을 직접 비교 |
| `follow_up` | 9 | 선행 질의의 문맥을 이어받아 세부 범위를 재질의 |
| `abstention` | 9 | 문서 내 관련 내용 없음 → `insufficient` 응답 기대 |
| **합계** | **42** | |

### Hardcase 태그 분포

| Tag | count | 의미 |
|---|---:|---|
| `retrieval_hardening` | 5 | 표제어·키워드 없이 의미만으로 검색해야 하는 케이스 |
| `one_sided_comparison` | 3 | 한쪽 기관에만 항목이 있어 비교 시 half-answer 위험 |
| `ambiguous_follow_up` | 3 | 선행 문맥 없이 재질의만 보면 대상 기관이 불분명 |
| `chunk_boundary` | 3 | 핵심 정보가 섹션 경계에 걸려있어 parent-reassembly 필요 |
| `alias_entity` | 2 | 기관 약칭·alias로만 질의 — metadata normalization 필수 |
| `noisy_entity` | 1 | 음운변화/오타 포함 질의 |
| `partial_comparison` | 1 | 비교 항목 중 일부만 존재 — partial-grounding 판단 |
| `answer_schema_v2` | 1 | ADR 0003 `schema_version: 2` 필드 준수 검증 케이스 |
| `follow_up_context` | 1 | `prior_turns` 문맥 2-turn 이상 연쇄 |

### 질의 예시 (anonymized)

```
# single_doc — 예산 추출
Q: "기관 B의 MLOps 자동화 과제 총 예산은?"

# comparison
Q: "품질관리 관점에서 기관 A와 기관 B의 AI 요구사항 차이는?"

# abstention
Q: "기관 C의 데이터센터 운영 비용은?" → should_abstain: true
```

---

## 3. Evaluation Methodology

### 채점 기준

| Metric | 계산 방식 | 해석 |
|---|---|---|
| Answer Accuracy | `gold_answer` vs model answer (LLM-judge) | 사실 일치 여부 |
| Groundedness Rate | evidence coverage (verifier) | 근거 없는 claim 비율 |
| Citation Precision | cited chunks ∩ target_chunks / cited chunks | 인용 정확도 |
| Claim Citation Alignment | claim↔citation 매핑 일치 | ADR 0003 계약 이행 |
| Answer Format Compliance | ADR 0003 schema 필드 체크 | 구조 준수 |
| Abstention Accuracy | `should_abstain` 일치 (3-bin) | 부재판별 정확도 |

**3-bin abstention outcomes**: `correct_refusal` (정상 abstention) / `incorrect_answer` (있다고 잘못 답변) / `boundary_partial` (부분 답변)

### Bootstrap CI

- **Resamples**: 1000
- **Seed**: 17 (고정 — 재현성)
- **Coverage**: 95% 양측
- **구현**: [`eval/bootstrap.py`](../eval/bootstrap.py)
- **비-CI 컬럼** (Format, Abstention, Retry): point estimate — CIs는 메인 성능표 별도 열에 보고

### LLM-as-judge (ADR 0012)

- `eval/synthetic_judge.py` — stub 기본값 (CI 비용 0)
- live 점수: `BIDMATE_SYNTHETIC_JUDGE_BACKEND=openai_compatible`로 개발자 수동 실행 후 commit
- 공개 synthetic 표면 한정 (ADR 0006 real-data-only 원칙 준수)
- aggregate 결과: [`reports/synthetic_judge.aggregate.json`](../reports/synthetic_judge.aggregate.json)

---

## 4. Reproducibility

### 빠른 재현 (CI gate)

```bash
make smoke                          # hashing backend, ~수분
bash scripts/test.sh                # pytest gate (동일 결과)
```

### 전체 ablation 재실행

```bash
python -m eval.run_eval \
  --config eval/config.yaml \
  --index_dir data/index \
  --output_dir reports
```

### LLM-judge (선택)

```bash
BIDMATE_SYNTHETIC_JUDGE_BACKEND=openai_compatible make synthetic-judge
```

### README 메트릭 갱신 검증

```bash
python3 scripts/update_readme_metrics.py --check   # reports/ ↔ README 일치 확인
```

### 카테고리 분포 재확인 (jsonl)

```bash
jq -r '.question_type' eval/dev_queries_v1.jsonl | sort | uniq -c
```

### Config 기준 n=42 재확인

```bash
python3 -c "
import yaml
cfg = yaml.safe_load(open('eval/config.yaml'))
cases = cfg['cases']
from collections import Counter
print('n_cases:', len(cases))
print(dict(Counter(c['query_type'] for c in cases)))
"
```

---

## 5. Boundary (ADR 0005)

이 문서가 다루는 공개 합성 평가셋과, **공개하지 않는** 비공개 평가셋의 경계:

| 항목 | 공개 synthetic (이 문서) | 비공개 100-doc |
|---|---|---|
| 문서 원본 | 저장소 내 `data/raw/` | **포함 금지** (계약·저작권) |
| 평가 케이스 | `eval/config.yaml` (n=42) | 비공개 config |
| 케이스별 예측 | `reports/` (gitignored, 로컬) | 동일 |
| Aggregate 집계 | `reports/synthetic_judge.aggregate.json` | `docs/real-data/private-100-doc-experiments.md` 별도 공개 |
| CI gate | `make smoke` / `bash scripts/test.sh` | 차단 (`tests/` 내 raw-data 의존 금지) |

전체 정책 전문: [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md)

---

## 6. 관련 문서

- [`eval/dev_queries_v1_summary.md`](../../eval/dev_queries_v1_summary.md) — jsonl 기반 질의 목록 요약
- [`eval/eval_scoring_guide.md`](../../eval/eval_scoring_guide.md) — 채점 가이드
- [`docs/real-data/private-100-doc-experiments.md`](../real-data/private-100-doc-experiments.md) — 비공개 aggregate 정책 (PR-C)
- [ADR 0003](../adr/0003-structured-answer-citation-contract.md) — 답변/인용 계약
- [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md) — eval split 정책
- [ADR 0012](../adr/0012-llm-judge-on-public-synthetic.md) — synthetic LLM-judge
