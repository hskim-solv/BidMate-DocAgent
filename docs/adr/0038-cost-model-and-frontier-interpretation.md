# 0038: Cost 모델: PRICING_PER_MTOK_USD 룩업 테이블; frontier x축 = 측정된 $/query

- **Status**: accepted
- **Date**: 2026-05-14
- **Deciders**: hskim
- **Related**: [ADR 0025](./0025-cost-frontier-defer-until-real-baselines.md) (deferral, 현재 superseded),
  [ADR 0015](./0015-cost-telemetry-additive.md) (cost telemetry 설계),
  [ADR 0009](./0009-external-baseline-comparison.md) (외부 baseline 인프라),
  [`rag_synthesis.py`](../../rag_synthesis.py) `PRICING_PER_MTOK_USD` / `compute_cost_usd()`,
  [`eval/run_eval.py`](../../eval/run_eval.py) `evaluate_run()`,
  [`reports/external_baselines.json`](../../reports/external_baselines.json),
  issue #449, issue #177

## TL;DR

- `rag_synthesis.py`의 `PRICING_PER_MTOK_USD` 룩업 테이블을 canonical cost 모델로 확정 + `evaluate_run()`이 `tokens_in/out/cost/llm_model`을 `case_results[i]`에 자동 추가.
- Frontier x축 = 측정된 $/query 합계, y축 = accuracy with 95% CI. 알려지지 않은 모델은 `None` propagate, 비조작.
- ADR 0025 조건 2 (cost 모델) + 3 (frontier 해석) 충족; 조건 1 (실 백엔드 실행)은 issue #449 별도.

## 배경

ADR 0025가 cost-accuracy frontier(issue #177)를 세 조건 충족까지 deferral. 이 ADR이 ADR 0025의 **조건 2와 3** 충족:

- **조건 2** (cost 모델): `rag_synthesis.py`가 이미 `PRICING_PER_MTOK_USD` + `compute_cost_usd()` 구현 (ADR 0015). 이 ADR이 그 룩업 테이블을 canonical cost 모델로 문서화하고 `tokens_in / tokens_out / cost_estimate_usd`를 `evaluate_run()` 경유 `eval_summary.json.case_results[i]`에 wire.
- **조건 3** (frontier 해석): 이 ADR이 x축 단위, 세 reading anchor(#177 spec), stub 제외 규칙 정의.

**조건 1** (실 백엔드 실행)은 API 키로 `make external-baselines-langchain` (또는 `-llamaindex`) 실행 + 결과 `reports/external_baselines.json` commit으로 독립 충족. issue #449 cover, 코드 변경 아님.

## 결정

**`rag_synthesis.py`의 `PRICING_PER_MTOK_USD`를 canonical cost 모델로 사용.** Per-query cost는 `compute_cost_usd(model, tokens_in, tokens_out, cache_read_tokens, cache_write_tokens)`로 계산 (longest-prefix 모델 ID 매칭, 알려지지 않은 모델 → `None`, 6 소수점 rounding). 테이블에 없는 모델용 estimate는 fabricate 안 함 — `None`이 `case_results[i].cost_estimate_usd`로 propagate되어 aggregation 제외.

`eval/run_eval.py`의 `evaluate_run()`이 `prediction["diagnostics"]["synthesis"]`에서 네 필드를 추출해 각 case 결과에 merge:

| field | source |
|---|---|
| `tokens_in` | `synthesis["tokens_in"]` |
| `tokens_out` | `synthesis["tokens_out"]` |
| `cost_estimate_usd` | `synthesis["cost_estimate_usd"]` |
| `llm_model` | `synthesis["model"]` |

네 필드 모두 `case_results[i]`에 항상 존재 (절대 absent 아님). Stub/hashing 백엔드는 모두 `null`; 실 Anthropic API 백엔드는 populated.

**Frontier 해석** (issue #177 세 reading anchor):

- **x축**: 평가된 n cases의 `sum(case_results[i].cost_estimate_usd)`, USD. Self-hosted 분석 변형은 cost = `null` → 플롯에서 x = 0 처리 (legend "self-hosted" 라벨, cost 축에 미플롯).
- **y축**: `accuracy.mean` with bootstrap 95% CI band.
- **Production sweet spot**: accuracy CI 하한이 acceptable floor 임계값(프로젝트 정의, 기본 0.70) 초과하는 최저 cost 외부 백엔드.
- **Accuracy ceiling**: 최고 in-repo 분석 변형 accuracy (x = 0). ceiling 초과 가격에 동등/낮은 accuracy 유료 백엔드는 dominated.
- **Cheapest acceptable floor**: floor 통과하는 최저 cost 외부 백엔드. floor 이하 포인트는 회색 non-Pareto 점으로 플롯.

실제 frontier 플롯(`scripts/plot_pareto.py` 확장 또는 신규 `scripts/plot_cost_frontier.py`)은 issue #177 하 follow-up PR로 deferral. 이 ADR은 cost 모델과 해석 스키마만 lock.

## 결과

Easier:

- **모든 미래 실 API eval 실행이 자동 per-case cost 산출.** `evaluate_run()` 추가 변경 불필요; `eval_summary.json` 작성 호출자가 추가 비용 없이 `case_results`에 `tokens_in/out/cost/llm_model` 상속.
- **ADR 0025 close 가능.** 세 re-open 조건 모두 외부 baseline 실 실행 commit(issue #449) 시 충족.
- **"no fabricated numbers" 자세 보존.** Cost는 SDK `usage` 객체 존재 시에만 populate; 알려지지 않은 모델은 `null` 유지.

비용 / 제약:

- `case_results[i]`가 이제 네 추가 키 보유. 알려진 키를 iterate하는 downstream consumer(예: tight 스키마 validator)는 extras 허용 필요. 기존 consumer(`summarize_run`, `metric_block`, leaderboard renderer)는 `.get()` 접근 → 무영향.
- Frontier 플롯은 issue #177 재개까지 미구축. 이 ADR은 이미지 생산 안 함 — 데이터 파이프라인 wiring만 보장.
- `PRICING_PER_MTOK_USD`가 2026-Q2 공개 list price 사용. Anthropic 가격 변경 시 `rag_synthesis.py` constant 업데이트 필수. 자동 업데이트 메커니즘 미계획.

## Follow-up status (2026-05-15)

Deferred frontier 플롯이 `scripts/plot_cost_frontier.py`로 구현 (issue #798, script 없이 close된 issue #177 follow-up). 스크립트가 `reports/eval_summary.json` (in-repo 분석 변형, "self-hosted" 규칙으로 x=0 배치) + `reports/external_baselines.json` (실 API 백엔드, `case_results[i].cost_estimate_usd`에서 cost) 양쪽 읽고 `reports/cost_frontier.md` + matplotlib 설치 시 optional `reports/cost_frontier.png` emit. `tests/test_plot_cost_frontier_regression.py` 회귀 테스트가 Pareto-frontier dominance 규칙, stub-exclusion 행동(per-case cost 없는 외부 실행은 x=0 플롯 대신 stderr note + drop), 세 anchor(accuracy ceiling / production sweet spot / cheapest acceptable floor) lock.

첫 artifact는 `make external-baselines-langchain`을 통한 실 Anthropic API 실행이 `reports/external_baselines.json`의 per-case cost를 populate할 때까지 sanity-only. 그때까지 플롯의 외부 측은 비고 in-repo accuracy ceiling만 표시 — 의도된 설계, 이 ADR의 "no fabricated numbers" 자세는 cost 데이터 합성을 거부.

## 검토한 대안

- **분석 변형 레벨에서만 cost 집계 (per-case 아님).** Simpler, `evaluate_run()` 변경 회피. *기각:* per-case cost는 per-query-type 분해(메타데이터 vs 다문서 vs 비교 쿼리)를 가능케 하고 기존 per-case latency 필드와 일관. 증분 코드 4줄.
- **플롯 스크립트 작성까지 wiring 연기.** *기각:* 데이터 가용성을 플롯에서 분리. Wiring 먼저면 데이터가 미래 모든 eval 실행에 등장, 역사적 replay 포함, 재실행 불필요.
- **별도 cost 모델 파일 (YAML/JSON) 사용.** *기각:* `rag_synthesis.py`의 `PRICING_PER_MTOK_USD`가 이미 `compute_cost_usd()`에 의해 사용되고 `tests/test_synthesis_cost_telemetry.py`에서 테스트되는 단일 진리 소스. config 파일로 중복 시 drift 위험.
