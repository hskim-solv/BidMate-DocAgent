# eval-framework-progressive-audit — Phase 3 (process + trajectory)

| field | value |
|---|---|
| Skill | [`.claude/skills/eval-framework-progressive-audit/SKILL.md`](../../.claude/skills/eval-framework-progressive-audit/SKILL.md) (PR #889) |
| Phase | **3 — Process + trajectory audit** (skill line 133-149) |
| Date | 2026-05-18 |
| Author | Hyunsoo Kim |
| Issue | #960 |
| Predecessor | Phase 2 acceptance — skipped (본 audit 는 Phase 3 acceptance 만 산출; Phase 1 / 2 acceptance 는 별 audit turn) |
| Successor | Phase 4 (Statistical rigor audit) — 별 plan turn (스킬 본문 STOP gate, 사용자 승인 영수증 필요) |
| Strict-forbid | **실제 로깅 추가 / trajectory writer 작성 0건** (skill body line 148-149) |

## Executive summary

| # | item | 상태 | 핵심 evidence |
|---|---|:---:|---|
| 1 | per-query 로깅 (latency / call count / token / cost) | ◐ partial | `eval_summary.json` aggregate `stage_latency` ✓ + per-case `tokens_in/out/cost_estimate_usd/llm_model` schema-wired ✓; 그러나 token/cost 가 `prediction.diagnostics.synthesis` 에 채워질 때만 propagate (`eval/run_eval.py:983-985`) — answer LLM call path 가 SDK `usage` field 를 synthesis dict 로 surface 하는 wiring 미확정. |
| 2 | trajectory 직렬화 (모든 LLM call I/O) | ◐ partial | `reports/real100/traces/{full,random_retrieval,single_chunk}/*.trace.json` per-case file ✓; `trace` dict default = `{schema_version, query_rewrite, planner, answer_schema}` 만 (`eval/run_eval.py:829-861`). env-gated `BIDMATE_TRACE_VERBOSE=1` 시 `evidence/answer_text/answer/diagnostics_subset` 추가. **verifier full I/O는 별도 dump** (`scripts/dump_verifier_trajectories.py`, Phase 1 Step 2.5). **retrieval / generator (answer LLM) input/output 부재**. |
| 3 | trajectory-rationality rubric (LLM-as-judge: planner decomp / retrieval 재호출 / verifier 판정) | ✗ absent | `(planner\|retrieval\|verifier).*rationale\|process.*judg\|trajectory.*judg\|rubric` grep → 0건. 단 매칭은 `eval/synthetic_judge.py` 의 `multihop_valid` (ADR 0033, case validity gate; process rationality 아님). `eval/judges/{llm_judge,synthetic_judge,judge_common}.py` 는 ADR 0006 answer-quality judge surface. |
| 4 | pareto reporting (quality vs cost 2D plot) | ◐ partial | `scripts/plot_cost_frontier.py` (line 43 `cost_usd` field, line 196 pareto dominance) + `scripts/plot_pareto.py` 둘 다 ✓. **그러나 `reports/real100/cost_frontier*` 산출물 0건** — plotter 가 있고 ADR 0054 n=221 baseline 으로 regen 안 됨. (`reports/real100/eda.{md,aggregate.json}` 는 별 surface — EDA report.) |

**판정**: partial 3 + absent 1. 가장 큰 갭 = **item 3 (rationality rubric 0건)** — Phase 3 의 "process rationality 가 측정 가능한가?" 질문에 현재 답이 "측정 불가능".

## 상세 진단

### Item 1 — Per-query 로깅 범위

**스킬 요구 (line 135-137)**: total latency, component별 latency, retriever call count, verifier retry count, token in/out, 추정 $.

**현재 wiring**:

- **Aggregate** (`reports/real100/eval_summary.json` top-level — 본 audit 시점 ADR 0054 baseline regen 후):
  ```
  latency, stage_latency = {query_analysis_ms, context_resolution_ms, answer_generation_ms, retrieve_ms, verify_ms},
  latency_by_retry_count, cold_start_samples, retry, retry_cost, retry_reason_counts, retry_effectiveness
  ```
  → **component-별 latency ✓**, **verifier retry count ✓**, **retry cost ✓** (aggregate).
- **Per-case** (`case_results[*]`, `eval/run_eval.py:975-989`):
  ```python
  synth = (prediction or {}).get("diagnostics", {}).get("synthesis") or {}
  result["tokens_in"]  = synth.get("tokens_in")
  result["tokens_out"] = synth.get("tokens_out")
  result["cost_estimate_usd"] = synth.get("cost_estimate_usd")
  result["llm_model"] = synth.get("model")
  ```
  → schema 는 wired ✓, **하지만 `prediction["diagnostics"]["synthesis"]` 가 채워지는 path 가 answer LLM call 부 (anthropic/openai SDK response.usage) 에서 wiring 됐는지** grep 으로 확정 어려움 (RAG production 경로의 prediction 생성 다층 함수).

**Gap**:
- (a) per-case retrieval call count / verifier retry count — schema 없음 (aggregate `retry` 만).
- (b) token / cost propagation 의 end-to-end 검증 (real-eval surface 에서 `tokens_in` 이 None 외 값으로 채워지는지) 부재. 본 audit 시점에 1 case_results row 인용해 검증 가능하나 trace surface 외부 — 별 PR scope.

**Supply 제안** (별 PR):
- 신규 helper `eval/run_eval.py:record_per_case_tokens(case_result, llm_response_metadata)` — `anthropic.Message.usage.{input_tokens, output_tokens}` / `openai.ChatCompletion.usage.{prompt_tokens, completion_tokens}` 두 backend 통합 추출. `rag_answer.py` 의 LLM call site 가 `prediction["diagnostics"]["synthesis"]` 에 위 필드 + `model` 까지 항상 채우도록 invariance 강화.
- 별 ADR 미발행 (기존 schema 확장이므로). 추정 ~50 LOC + 1 test.

### Item 2 — Trajectory 직렬화

**스킬 요구 (line 138-140)**: 전체 trajectory (모든 LLM call 의 input/output) 이 eval 예제별 구조화 포맷으로 저장 가능한지.

**현재 wiring**:

- **Per-case file**: `reports/real100/traces/{run}/{case_id}.trace.json` — `write_prediction_trace` (`eval/run_eval.py:863-890`) 가 `prediction_trace_payload` (line 829-861) 의 결과를 디스크에 기록.
- **trace dict 내용물** (default, sample inspection 결과):
  ```json
  {
    "schema_version": 1,
    "case_id": "...",
    "run": "full",
    "pipeline": "agentic_full",
    "slice": "abstention",
    "query": "...",
    "answer_status": "partial",
    "trace": {"schema_version": ..., "query_rewrite": {...}, "planner": {...}, "answer_schema": {...}}
  }
  ```
  → **planner ✓**, **query_rewrite ✓**, **answer_schema ✓** (출력만, LLM input prompt 는 아님).
- **Env-gated 확장** (`BIDMATE_TRACE_VERBOSE=1`): `evidence`, `answer_text`, `answer`, `diagnostics_subset` 추가 — Phase 1 Step 2.5 의 verifier-trajectory dump 용 (line 849-858, ADR 0001 invariant 위해 default off).
- **Verifier 전용 별 dump**: `scripts/dump_verifier_trajectories.py` — `reports/phase1_step2_5_trajectories.jsonl` 로 verifier 의 (claim, evidence, sufficiency) 결정 trace 만 dump (스크립트 docstring line 1-12).

**Gap**:
- (a) **Retrieval LLM call I/O** (query expansion / HyDE 등) — 부재.
- (b) **Answer LLM call I/O** (full prompt + completion + token usage) — `answer_schema` 만 있고 prompt 자체는 trace 외부.
- (c) Verifier LLM I/O 는 별 dump 로만 존재 — main trace 와 join 가능하나 schema 통합 안 됨.

**Supply 제안** (별 PR — ADR-worthy, schema_version bump):
- `prediction["trace"]` dict 에 신규 key `retrieval_llm_calls`, `answer_llm_call`, `verifier_llm_calls` 추가. 각 record = `{prompt, completion, model, usage: {input_tokens, output_tokens}, latency_ms}`.
- `prediction_trace_payload` 의 `schema_version` 을 1 → 2 로 bump (기존 consumer 호환성 유지를 위해 default off 도 가능 — 새 env `BIDMATE_TRACE_FULL=1`).
- 별 ADR 발행 필요 (trace schema 변경 = measurement contract). **ADR 0055 후보** (가칭, 본 audit 시점 미예약).
- 추정 ~150 LOC + 1 ADR + 1 test (schema round-trip).

### Item 3 — Trajectory-rationality rubric

**스킬 요구 (line 141-143)**: LLM-as-judge 기반 rubric — "Planner decomposition 이 query 의도와 일치하는가? Retrieval 재호출이 합당한 이유로 발생했는가? Verifier 판정이 evidence 와 정합적인가?"

**현재 wiring**: **부재 (✗)**.

**Evidence**:
- `(planner|retrieval|verifier).*rationale|process.*judg|trajectory.*judg|rubric` grep across `eval/`, `scripts/`, `docs/adr/` → 단 5건 매칭, 모두 비-rationality:
  - `scripts/synthesize_multihop_queries.py:223` — `multihop_valid` filter (case validity gate, ADR 0033)
  - `scripts/claude-hooks/_self_review.py:546,591,621,725` — self-review LLM rubric (Claude 사용 검토용, eval surface 아님)
  - `docs/adr/0033-multihop-cross-section-eval-slice.md:57` — `multihop_valid` rubric (case validity)
  - `docs/adr/0040-react-agent-loop-additive-preset.md:27` — senior-positioning rubric reference (포트폴리오 surface)
- `eval/judges/{llm_judge,synthetic_judge,judge_common}.py` — ADR 0006 / 0012 answer-quality judge. 입력 = (query, answer, gold_answer), 출력 = 정답-여부 / 점수. **trajectory 입력 안 받음**.

**Gap**: process rationality 가 0차원 측정. trajectory file (`*.trace.json`) + verifier dump (`reports/phase1_step2_5_trajectories.jsonl`) 가 raw 자료를 이미 emit 하지만 그것을 채점하는 rubric 자산 부재.

**Supply 제안** (별 PR — **ADR-worthy**):
- 신규 `eval/judges/rationality_judge.py` — `eval/judges/judge_common.py` 의 stub/llm 백엔드 패턴 재사용. 3-axis prompt:
  ```
  Given a query and a trace (planner sub-queries, retrieval re-calls with reasons, verifier
  sufficiency judgments + evidence), rate each axis independently:
  1. planner_decomposition (1-5): sub-queries cover query intent fully without redundancy?
  2. retrieval_recalls (1-5): re-call reasons are evidence-driven (low-recall trigger,
     ambiguity detection)?
  3. verifier_judgments (1-5): sufficiency verdict consistent with provided evidence?
  Output JSON: {planner_score: int, retrieval_score: int, verifier_score: int,
                rationale: str}.
  ```
- Stub backend (deterministic, no API key) — CI smoke + test 용. ADR 0006 패턴 동일.
- 호출 entrypoint: `scripts/run_rationality_judge.py --traces reports/real100/traces/full --out reports/real100/rationality.{md,aggregate.json}`.
- 별 ADR 발행 필요 — **ADR 0055 후보** (가칭, "rationality judge as measurement surface").
- 추정 ~250 LOC + 1 ADR + 1 test (stub determinism).

### Item 4 — Pareto reporting (quality vs cost)

**스킬 요구 (line 144-145)**: quality vs cost 2D plot 자산 존재 여부 (`scripts/plot_cost_frontier.py` 등).

**현재 wiring**:

- `scripts/plot_cost_frontier.py` — `cost_usd` field 정의 (line 43), pareto dominance 구현 (line 196: `other.cost_usd <= cand.cost_usd ... other.cost_usd < cand.cost_usd`), CLI entrypoint 존재.
- `scripts/plot_pareto.py` — sibling plotter (별 surface).
- **그러나** `reports/real100/cost_frontier.{png,md,aggregate.json}` 산출물 0건. `reports/real100/` 내 frontier 매칭 file 부재.
- 비교: `reports/real100/eda.{md,aggregate.json}` 는 EDA report 의 별 surface — pareto 와 무관.

**Gap**: plotter 는 ✓ 그러나 ADR 0054 n=221 baseline 으로 산출물 regen 안 됨. 즉 1-command 실행 시 산출 가능하나 자동화 (Makefile / CI) 미연동.

**Supply 제안** (별 PR — small):
- `Makefile` 신규 target `real-eval-frontier-regen`:
  ```makefile
  real-eval-frontier-regen:
      python3 scripts/plot_cost_frontier.py \
        --input reports/real100/eval_summary.json \
        --out reports/real100/cost_frontier
  ```
- 산출물 1회 commit (`reports/real100/cost_frontier.{md,aggregate.json}`).
- 별 ADR 미발행. 추정 ~10 LOC Makefile + 0 code.

## Acceptance checklist 매핑

스킬 본문 line 147-149 의 Phase 3 acceptance:

> per-query 로깅 / trajectory 직렬화 / rationality rubric / pareto plot 4-item present/partial/absent 표 산출; 누락 항목별 supply 제안 명시. **실제 로깅 추가 / trajectory writer 작성 0건.**

| 요구사항 | 본 audit |
|---|:---:|
| 4-item present/partial/absent 표 산출 | ✓ (Executive summary) |
| 각 partial/absent 항목 supply 제안 명시 | ✓ (상세 진단 §item 1/2/3/4) |
| 실제 로깅 / writer 0건 | ✓ (code path 0 — docs only) |

→ **Phase 3 acceptance 통과**. 사용자 머지 행위 자체가 STOP gate 영수증 (skill line 102: "사용자 명시 승인 전 Phase 4 진입 금지").

## Out of scope (별 PR / 별 plan turn)

- **위 4 supply 의 실제 구현** — 스킬 본문 strictly forbid.
- **Skill Phase 4 (Statistical rigor)** + **Phase 5 (Closed error loop)** audit — 별 plan turn. 본 audit 머지 후 사용자 승인 영수증 받고 진행.
- **Retrieval-eval skill Phase 4 (Metadata / filtering ablation)** — 별 surface (skill 다름). PR #952 (Phase 2 chunking) → #956 (Phase 3 retrieval mode) 의 자연스러운 후속.
- **`answer_format_compliance −0.64pp` 잔여 false-negative** — ADR 0054 머지 직후 식별된 별 축. ADR 0055 (가칭) 의 다른 후보 (gauge per-metric weighting) 와 함께 검토.
- **Portfolio repo `BidMate-DocAgent-portfolio` blog narrative 갱신** — D층 surface, 본 audit 와 독립.

## References

- 본 audit 의 mother skill: [`.claude/skills/eval-framework-progressive-audit/SKILL.md`](../../.claude/skills/eval-framework-progressive-audit/SKILL.md) (PR #889)
- Predecessor Phase 2 / 1 acceptance: 본 audit 미산출 (별 plan turn)
- Item 1 코드 근거: [`eval/run_eval.py:975-989`](../../eval/run_eval.py) (token/cost capture from synthesis)
- Item 2 코드 근거: [`eval/run_eval.py:829-890`](../../eval/run_eval.py) (`prediction_trace_payload` + `write_prediction_trace`)
- Item 2 reference dump: [`scripts/dump_verifier_trajectories.py`](../../scripts/dump_verifier_trajectories.py) (Phase 1 Step 2.5 verifier-only)
- Item 3 referenced rubric ADRs (비-rationality 비교용): [ADR 0006](../adr/0006-llm-judge-on-real-data-only.md) (answer-quality judge), [ADR 0012](../adr/0012-llm-judge-on-public-synthetic.md), [ADR 0033](../adr/0033-multihop-cross-section-eval-slice.md) (`multihop_valid` case validity)
- Item 4 코드 근거: [`scripts/plot_cost_frontier.py`](../../scripts/plot_cost_frontier.py) (cost_usd field line 43, pareto line 196)
- Sibling skill (다른 surface): [`.claude/skills/retrieval-eval/SKILL.md`](../../.claude/skills/retrieval-eval/SKILL.md) (4-phase retrieval measurement, PR #889)
- Recent Goodhart 폐루프 (Phase 2 산출물): [ADR 0053](../adr/0053-distinguishing-power-floor-ablations.md) (gauge), [ADR 0054](../adr/0054-conditional-on-answer-scorer-semantics.md) (scorer fix)
