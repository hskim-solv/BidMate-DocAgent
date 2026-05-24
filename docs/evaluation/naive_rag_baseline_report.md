# Naive RAG Baseline Report

이 문서는 공개 fixture smoke 계약으로 현재 naive baseline을 측정한 첫 재현 가능 baseline report입니다. 실제 성능 claim은 private/internal eval aggregate에서만 판단합니다.

## Evaluation Command

```bash
python3 eval/run_eval.py --config experiments/runs/naive_baseline_20260524T054514Z/config.naive.yaml --index_dir data/index --output_dir experiments/runs/naive_baseline_20260524T054514Z
```

## Run Metadata

- run_id: `naive_baseline_20260524T054514Z`
- dataset size: 5
- answerable questions: 4
- unanswerable questions: 1
- gold evidence source: 0 explicit, 4 derived from `expected_doc_ids` + `expected_terms`

## Metric Summary

| System | Recall@5 | Recall@10 | MRR@5 | nDCG@5 | Citation Acc. | Faithfulness | Hallucination | P95 Latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Naive Dense RAG | 1.000 | 1.000 | 1.000 | 1.000 | 0.875 | 1.000 | 0.000 | 2.52 ms |

## Failure Categories

### Retrieval Failures
- gold evidence not in top-k: 0
- gold evidence ranked too low: 0
- wrong similar clause: 0
- chunk boundary split: 0
- query wording mismatch: 0
- multi-chunk evidence missing: 0

### Parsing Failures
- table content lost: 0
- figure content ignored: 0
- page metadata missing: 5
- header/footer noise: 0
- Korean/English mixed text issue: 0

### Citation Failures
- correct answer but wrong citation: 1
- insufficient citation: 0
- missing page number: 5
- citation does not support claim: 0
- vague citation for multiple claims: 0

### Answer Failures
- hallucinated requirement: 0
- partial answer: 0
- overconfident weak evidence: 0
- wrong synthesis: 0
- failed to abstain: 1

### Evaluation Failures
- missing gold evidence: 0
- metric missing: 0
- failure case not saved: 0
- schema mismatch: 0

## Top Failure Categories

- citation: missing page number: 5
- parsing: page metadata missing: 5
- answer: failed to abstain: 1
- citation: correct answer but wrong citation: 1

## Representative Failure Cases

- `smoke_single_doc_security` (single_doc): citation: correct answer but wrong citation
  - expected: 보안 통제; 로그 추적
  - generated: AI 요구사항 개요 핵심 AI 요구사항은 모델 품질관리, 보안 통제, 로그 추적이다. 보안 및 감사 모든 승인 이력은 감사 로그로 남겨야 하며 운영자는 월간 감사 리포트를 생성할 수 있어야 한다. AI 요구사항 개요 핵심 AI 요구사항은 모델 품질관리, 보안 통제, 로그 추적이다. 보안 및 감사 모든 승인 이력은 감사 로그로 남겨야 하며 운영자는 월간 감사 리포트를 생성할 수 있어야 한다. 
- `smoke_abstention_missing_blockchain` (abstention): answer: failed to abstain
  - expected: 블록체인
  - generated: 납품 기한은 계약 체결일로부터 6개월이며 인수 시험은 단계별로 진행한다. 납품 기한은 계약 체결일로부터 6개월이며 인수 시험은 단계별로 진행한다. - 기관 A: 납품 기한은 계약 체결일로부터 6개월이며 인수 시험은 단계별로 진행한다. [rfp-agency-a-ai-quality::chunk-001] 납품 기한은 계약 체결일로부터 6개월이며 인수 시험은 단계별로 진행한다. 사업 개요 기관 A는

## What The Naive Baseline Does Reasonably Well

- Dense top-k retrieval found all derived gold chunks in the public fixture smoke set.
- Answerable fixture cases scored as relevant and faithful under the current rule-based scorer.

## What The Naive Baseline Fails At

- Citation accuracy is below perfect, so answers are not always tied to sufficient evidence.
- The baseline failed to abstain on at least one unanswerable case and answered with weak evidence.
- Parser/index metadata limitations affect simple source references such as page numbers.

## Recommended Next Experiments

### Audit citation support gaps in naive baseline answers
- problem: Observed citations are incomplete, vague, or not aligned with the generated claims.
- why it matters: RFP review needs claim-to-evidence traceability even when the textual answer is mostly correct.
- expected metric impact: Citation accuracy and claim-citation alignment should become explainable before verifier work starts.
- files likely to change: `eval/scorers/citation.py, eval/scorers/alignment.py, docs/evaluation/naive_rag_baseline_report.md`
- acceptance criteria: Each citation failure case has a deterministic reason code and a representative example.
- suitable for parallel AI-assisted coding: Yes

### Measure page metadata coverage for baseline citations
- problem: The current index/eval output exposes missing or weak page metadata as a baseline limitation.
- why it matters: Simple source references require stable page/chunk identifiers before richer grounding can be trusted.
- expected metric impact: Citation page coverage and missing-page-number counts become measurable.
- files likely to change: `ingestion.py, scripts/build_index.py, eval/scorers/citation.py`
- acceptance criteria: Smoke eval reports page metadata coverage without changing naive retrieval ranking.
- suitable for parallel AI-assisted coding: Yes

### Catalog naive answer failure modes without prompt tuning
- problem: The baseline produced an answer-policy failure on observed cases, including failed abstention when evidence was insufficient.
- why it matters: Answer failures must be separated from retrieval misses before prompt or verifier experiments.
- expected metric impact: Faithfulness, answer relevancy, hallucination, and abstention error rates get cleaner attribution.
- files likely to change: `docs/evaluation/naive_rag_baseline_report.md, eval/scorers/case.py`
- acceptance criteria: Failure cases distinguish partial answer, weak evidence, wrong synthesis, and failed abstention.
- suitable for parallel AI-assisted coding: Yes
