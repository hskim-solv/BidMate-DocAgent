# Evaluation Surface Map

이 문서는 BidMate-DocAgent의 평가(evaluation) 표면(surface)을 구분한다.
핵심 원칙은 [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md)다:
public fixture smoke는 wiring과 regression을 확인하고, 실제 성능(performance)
주장은 private/internal eval aggregate에서만 후보가 된다.

## Environment Axis

Evaluation surface and execution environment are separate axes. The claim surface
still follows ADR 0005: real-world performance evidence requires private
real-eval aggregate. The execution environment follows
[ADR 0079](../adr/0079-agent-gated-offline-online-rfp-eval-loop.md):

| Environment | Allowed | Claim rule |
|---|---|---|
| Offline / closed network | 외부 API 불가, 외부 모델 다운로드 가능, GPU 가능, local LLM judge 가능 | private real-eval aggregate required for performance evidence |
| Online / non-closed network | 외부 judge/model/API 가능, private RFP raw text egress 가능 | private real-eval aggregate required, plus provider/model/payload provenance |

The operating policy for metric-suite adoption, loop termination, and conservative
agent gate behavior is [Agent-Gated RFP Evaluation Loop](./agent-gated-rfp-eval-loop.md).

## Surface Summary

| Surface | 데이터 | 목적 | 대표 명령 | Commit boundary | 허용 claim |
|---|---|---|---|---|---|
| Public fixture smoke | `eval/fixtures/smoke_rfp/raw/`, `eval/config.yaml` | CI wiring, schema, deterministic regression, latency SLO | `make smoke`, `make harness-smoke`, `python3 eval/run_eval.py --index_dir data/index --output_dir reports --config eval/config.yaml` | raw run은 local/generated, small fixture는 commit 가능 | "eval harness가 동작한다", "regression guard 통과" |
| Public synthetic benchmark | `data/eval/benchmark/`, `configs/eval/benchmark_naive_rag_v1.yaml` | controlled failure discovery, ablation setup | `python3 eval/naive_rag/validate_benchmark_dataset.py --config configs/eval/benchmark_naive_rag_v1.yaml --report reports/benchmark/naive_rag_v1_validation.json`, `python3 -m eval.naive_rag.benchmark --config configs/eval/benchmark_naive_rag_v1.yaml` | synthetic corpus/config/gold는 public; generated run artifacts는 local | "synthetic v1에서 failure mode X 관측" |
| Private real-eval | `data/private/real100_v2/real_config_v2.local.yaml`, private v2 corpus/index, `reports/real100_v2/` aggregate outputs | real RFP aggregate evidence, tiered v2 baseline, paired delta, opt-in judge aggregate | `make real-eval-v2-check`, `make real-eval-v2-inventory`, `make real-eval-v2-guard`, `make real-eval-v2-chroma`, `make real-eval-v2-chroma-llm`, `make real-eval-v2-judge`, `make real-eval-v2-ragas-judge`, `make real-eval-v2-rationality-judge` | raw/per-case local-only; allowlisted aggregate-only artifact만 commit | "private real100_v2 aggregate에서 delta X, provenance Y" |
| PR fixture eval | `.github/workflows/pr-eval.yml` | PR마다 public fixture delta와 tests 검증 | GitHub Actions `PR Eval Delta` | PR comment/check only | "CI smoke delta passed/failed" |
| Slow tests | `pytest -m slow`, `.github/workflows/slow-tests.yml` | real-model/full-corpus risk 확인 | `PYTEST_ADDOPTS="-m slow" bash scripts/test.sh` | generated outputs local | "slow gate passed on date/SHA" |
| Operator-skill eval | `agent-evals/` (PR1: `README.md` 단 하나; PR2+: aggregate-only `reports/*.aggregate.json`, raw run-log/diff/reviewer-input은 local) | 운영자(사람)의 코딩-에이전트 운영 능력 paired holdout delta — 모델 성능 아님 ([ADR 0100](../adr/0100-operator-skill-eval-surface.md)) | PR2/PR3 wire 예정: `make agent-eval-mine`, `make agent-eval-run`, `make agent-eval-report` | **PR1 = `agent-evals/README.md` exact-path 단 하나** (3-layer: `.gitignore` deny-by-default + index-aware 가드 + pre-commit mirror); raw per-run local-only, aggregate report는 PR2 content scanner 통과 후에만 commit | "운영자 playbook v1−v0 paired delta X (cross-family oracle; freshness-exclusion + counterbalanced order balanced 시에만, 미balance면 비주장)" |

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

Naive RAG local private runner 경계:

- `eval.naive_rag.private_real_eval` 은 새 run 의 `output_dir`, `index_dir`,
  `index_build.hwp_pdf_artifact_dir` 가 legacy `data/index/real100*`,
  `reports/real100*`, `outputs/real100*` 표면으로 향하면 실패해야 한다.
  `real100_v2*` 는 현재 private-eval 표면으로 허용된다.
- `run_id` 는 단일 안전 path segment 여야 하며 `..`, 절대경로, `/`, `\`
  로 output root 를 벗어나면 안 된다.
- Raw/private run output 은 gitignored/local-only 여야 한다. Redacted aggregate
  summary 는 `reports/*.redacted.json` 처럼 raw case/id/path 를 포함하지 않는
  allowlisted aggregate artifact 일 때만 commit boundary 에 들어갈 수 있다.

금지:

- raw private question, answer, evidence, filename, exact local path, doc/chunk id 노출.
- provenance 없는 headline metric.
- 같은 config/index가 아닌 run끼리 직접 비교.

### Operator-Skill Eval

측정 대상은 모델이 아니라 **운영자(사람)의 코딩-에이전트 운영 능력**이다 ([ADR 0100](../adr/0100-operator-skill-eval-surface.md)). PR1 표면은 *경로* 경계(`agent-evals/README.md` exact-path 단 하나)만 확립하며, content aggregate-only 강제와 report 산출은 PR2/PR3 가 wire 한다.

허용:

- 같은 모델·repo·budget 에서 frozen playbook v1 − v0 의 **paired holdout delta** (cross-family oracle: `reviewer_family != candidate_family`).
- v1 ≤ v0 인 directional finding ("이 운영자의 spec-first scaffolding 은 고정 budget 에서 accepted output 을 못 올린다") — eval 실패 아님.
- balance 가 측정·확보됐을 때만(freshness-exclusion + counterbalanced order + familiarity 메타)의 delta.

금지:

- 절대 solve rate / accepted rate 를 표면 claim 으로 사용 (운영자-기억 오염으로 inflated 가능 — paired delta 만).
- contamination-balance 미측정·미확보 상태의 paired-delta 주장 (fail-closed, PR3 runner 강제).
- same-family reviewer(candidate 와 같은 family)가 최종 accepted arbiter 인 결과를 claim 으로 사용.
- raw run-log/diff/reviewer-input/task 본문을 commit 경계 안으로 노출 (PR1 = README only; aggregate 는 PR2 content scanner 통과 후).

## Required Evidence By Claim Type

| Claim type | Required evidence |
|---|---|
| Regression fixed | failing-before/passing-after test or replay command, affected failure mode |
| Benchmark improved | dataset id, config path, index provenance, command, metric with CI when available, artifact path |
| Retrieval improved | `chunk_recall@k`, MRR/nDCG, same corpus/index build rules, semantic backend provenance if dense/hybrid, vector-store backend provenance |
| Answer quality improved | answer metric semantics, abstention/citation guardrails, private aggregate if real-world claim |
| Latency improved | timed region, warm/cold split, stage latency, same hardware/process caveat |
| Privacy-safe report | aggregate-only proof, forbidden fields absent, commit allowlist path |
| Operator-skill delta | frozen playbook SHA (v0/v1), holdout split + freshness-exclusion proof, counterbalanced order, `reviewer_family != candidate_family`, **external reviewer payload public-data attestation OR proof of no-external-egress (local/stub reviewer)** — 없으면 fail-closed no-claim, paired bootstrap CI with min-N guard, aggregate-only report path |

## Critical Warnings

- `reports/eval_summary.json` is usually public fixture smoke output. It is not private real-eval evidence.
- `reports/real100_v2/` is the current claim-bearing aggregate surface.
- `judge.aggregate.json`, `judge_ragas.aggregate.json`, and `rationality.aggregate.json` are aggregate-only reviewer evidence. Their local per-case siblings (`*.local.json`, traces, prompts, completions) and human review views such as `rationality.md` must stay outside the commit boundary.
- Legacy `reports/real100/`, 221-case aggregates, and kordoc/v1 indexes are archive-only and must not be used for new tasks until the maintainer explicitly re-enables them.
- New private Naive RAG runs must not write fresh result/index/artifact outputs
  to legacy `real100*` surfaces; use `real100_v2*` paths or another explicitly
  approved current surface.
- `artifacts/runs/*/metrics/eval_summary.json` belongs to a harness run. Compare only after checking
  dataset/config/index/provenance.
- `naive_baseline` is Chroma-backed by default (ADR 0081). `memory` and `qdrant`
  backend runs are control/ops comparisons unless paired same-config evidence
  shows ranking drift. Use `make real-eval-v2-chroma` for the isolated Chroma
  private-v2 command; it writes to `reports/real100_v2_chroma/` by default.
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
- [real100_v2 Benchmark Tier Split](./real100_v2-benchmark-tiers.md)
- [Agent-Gated RFP Evaluation Loop](./agent-gated-rfp-eval-loop.md)
- [Pre-Improvement Readiness Checklist](./pre_improvement_readiness_checklist.md)
- [RAG Performance Experiment Stack](./rag-performance-experiment-stack.md)
