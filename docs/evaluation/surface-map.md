# Evaluation Surface Map

이 문서는 BidMate-DocAgent의 평가(evaluation) 표면(surface)을 구분한다.
핵심 원칙은 [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md)다:
public fixture smoke는 wiring과 regression을 확인하고, 실제 성능(performance)
주장은 private/internal eval aggregate에서만 후보가 된다.

## Surface Summary

| Surface | 데이터 | 목적 | 대표 명령 | Commit boundary | 허용 claim |
|---|---|---|---|---|---|
| Public fixture smoke | `eval/fixtures/smoke_rfp/raw/`, `eval/config.yaml` | CI wiring, schema, deterministic regression, latency SLO | `make smoke`, `make harness-smoke`, `python3 eval/run_eval.py --index_dir data/index --output_dir reports --config eval/config.yaml` | raw run은 local/generated, small fixture는 commit 가능 | "eval harness가 동작한다", "regression guard 통과" |
| Public synthetic benchmark | `data/eval/benchmark/`, `configs/eval/benchmark_naive_rag_v1.yaml` | controlled failure discovery, ablation setup | `python3 eval/naive_rag/validate_benchmark_dataset.py --config configs/eval/benchmark_naive_rag_v1.yaml --report reports/benchmark/naive_rag_v1_validation.json`, `python3 -m eval.naive_rag.benchmark --config configs/eval/benchmark_naive_rag_v1.yaml` | synthetic corpus/config/gold는 public; generated run artifacts는 local | "synthetic v1에서 failure mode X 관측" |
| Private real-eval | `eval/real_config.local.yaml`, private corpus/index, `reports/real100/` local outputs | real RFP aggregate evidence, hardcase stress, paired delta | `make real-eval-check`, `make real-eval`, `make real-eval-semantic`, `make real-eval-delta` | raw/per-case local-only; allowlisted aggregate-only artifact만 commit | "private aggregate에서 delta X, provenance Y" |
| PR fixture eval | `.github/workflows/pr-eval.yml` | PR마다 public fixture delta와 tests 검증 | GitHub Actions `PR Eval Delta` | PR comment/check only | "CI smoke delta passed/failed" |
| Slow tests | `pytest -m slow`, `.github/workflows/slow-tests.yml` | real-model/full-corpus risk 확인 | `PYTEST_ADDOPTS="-m slow" bash scripts/test.sh` | generated outputs local | "slow gate passed on date/SHA" |

## Allowed And Disallowed Claims

### Public Fixture Smoke

허용:

- `reports/eval_summary.json` schema가 유지된다.
- smoke fixture에서 특정 regression이 재현/수정됐다.
- latency SLO check가 통과/실패했다.

금지:

- "RAG quality improved" 같은 real-world 성능 주장.
- public fixture accuracy/recall을 portfolio headline metric으로 확대.
- smoke fixture delta만으로 load-bearing behavior safety를 주장.

### Public Synthetic Benchmark

허용:

- synthetic corpus에서 특정 distractor/failure mode를 드러냈다.
- 같은 synthetic dataset/config/index에서 A/B 비교가 재현된다.
- benchmark validator가 leakage/gold-evidence 계약을 검증했다.

금지:

- synthetic benchmark 점수를 실제 RFP 성능으로 주장.
- gold evidence provenance 없이 `expected_terms` 기반 metric을 benchmark claim으로 사용.
- synthetic-only success로 private real-eval regression risk를 닫는 것.

### Private Real-Eval

허용:

- aggregate-only result를 기반으로 한 hardcase stress claim.
- dataset/config/index/provenance/command가 함께 있는 paired delta.
- private/non-public임을 명시한 reviewer evidence.

금지:

- raw private question, answer, evidence, filename, exact local path, doc/chunk id 노출.
- provenance 없는 headline metric.
- 같은 config/index가 아닌 run끼리 직접 비교.

## Required Evidence By Claim Type

| Claim type | Required evidence |
|---|---|
| Regression fixed | failing-before/passing-after test or replay command, affected failure mode |
| Benchmark improved | dataset id, config path, index provenance, command, metric with CI when available, artifact path |
| Retrieval improved | `chunk_recall@k`, MRR/nDCG, same corpus/index build rules, semantic backend provenance if dense/hybrid |
| Answer quality improved | answer metric semantics, abstention/citation guardrails, private aggregate if real-world claim |
| Latency improved | timed region, warm/cold split, stage latency, same hardware/process caveat |
| Privacy-safe report | aggregate-only proof, forbidden fields absent, commit allowlist path |

## Critical Warnings

- `reports/eval_summary.json` is usually public fixture smoke output. It is not private real-eval evidence.
- `reports/real100/eval_summary.json` is local/private and gitignored. Do not commit it.
- `artifacts/runs/*/metrics/eval_summary.json` belongs to a harness run. Compare only after checking
  dataset/config/index/provenance.
- `make real-eval` uses the deterministic offline hashing path unless overridden. It is useful for
  repeatable private eval plumbing, but semantic dense/hybrid retrieval quality claims require
  `make real-eval-semantic` or equivalent semantic index provenance.
- CI green means non-slow tests plus fixture smoke gate passed. It does not mean private real-eval passed.

## Benchmark Auditor Checklist

Before accepting an eval/benchmark claim, verify:

- surface is classified as smoke, synthetic benchmark, or private real-eval.
- dataset/config/index/provenance are named.
- command is reproducible or the private/non-public boundary is explicit.
- metric semantics match the wording.
- CI/smoke result is not used as real-world performance proof.
- synthetic result is not used as private real-eval substitute.
- private aggregate has no raw case content or raw IDs.
- regression guardrails are reported, not only headline improvements.

## Related Docs

- [Benchmarking](../benchmarking.md)
- [Eval Dataset Spec](../eval/eval-dataset-spec.md)
- [Synthetic Naive RAG Benchmark v1 Design](./synthetic_benchmark_v1_design.md)
- [Private Real-Eval Workflow](./private_real_eval_workflow.md)
- [Pre-Improvement Readiness Checklist](./pre_improvement_readiness_checklist.md)
