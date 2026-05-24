# ADR 0056 — Trajectory-rationality judge 를 새 측정 표면으로

- Status: Accepted
- Implemented: #987 (2026-05-18) — `eval/judges/rationality_judge.py` 3-axis trajectory surface. (#1297 (2026-05-22) 가 committed artifact 와의 모순을 정정해 일시적으로 2-axis measured + 1-axis `answer_reasoning` pending 으로 relabel; #1326 (2026-05-22) 가 stub full-trace 캡처 wiring 을 고쳐 **3-axis 모두 measured** 로 복원 — `answer_reasoning` effective_n=166)
- Date: 2026-05-18
- Authors: Hyunsoo Kim
- Related: ADR 0006 (real-data LLM-judge), ADR 0054 (conditional-on-substantive-answer scorer semantics), ADR 0055 (claim_validator)
- Augments: Phase 3 audit (`docs/audits/eval-framework-phase3-audit.md`, PR #961) item 3 supply ("trajectory-rationality rubric ✗ absent")
- Issue: #969

## Context

Phase 3 audit (PR #961 `c50a3e7`) 의 4-item 표 중 **item 3 진단 = ✗ absent** — `grep '(planner|retrieval|verifier).*rationale|process.*judg|trajectory.*judg|rubric'` 0건. 기존 3 judge gate (Gate 1 real-data answer-quality / Gate 2 synthetic answer-quality / Gate 3 RAGAS answer-quality) 모두 *answer correctness* 만 채점 — *process rationality* (planner 가 합리적으로 decompose 했는가, retrieval 재호출이 evidence-driven 인가, synthesis 가 evidence 와 일관한가) 측정 표면 0차원.

ADR 0006 (real-data only) 가 정한 boundary 는 본 judge 에도 그대로 적용 — 본 모듈은 trace JSON 의 read-only consumer 이며 production code path 0 변경.

Step 2 (PR #968, ADR-free) 의 trace schema v2 `synthesis_llm_call` 키 (`BIDMATE_TRACE_FULL=1` env-gated) 가 `answer_reasoning` axis 의 input 자료 공급.

## Decision

1. **신규 모듈 `eval/judges/rationality_judge.py`** 도입.
   - 시그니처 `judge_rationality(summary, *, backend="stub", traces_dir=None, cache_dir=None, token_budget=200_000) -> (local_payload, aggregate)`.
   - **3 axis** (각 `[0.0, 1.0]` continuous, 4-th decimal precision):
     - `planner_decomposition` — `trace["planner"]` 의 `query_type` / `pipeline` / `stage_sequence` / `selected_top_k` / `retrieval_budget.reason` subset 기반.
     - `retrieval_recalls` — `trace["planner"]["attempts"][*]["verification_reasons"]` (retry 사유) 기반.
     - `answer_reasoning` — `trace["synthesis_llm_call"].{user_prompt_text, completion_text}` 기반. `BIDMATE_TRACE_FULL=1` 미설정 시 None → aggregate `effective_n` 에서 drop.

2. **시그니처는 Gate 3 RAGAS (`eval/judges/llm_judge.py:judge_ragas`) 의 패턴 그대로**.
   - `(summary, *, backend, cache_dir, token_budget) -> (local, aggregate)` — 4 judge surface 모두 같은 contract.
   - Backends: `stub` (default, deterministic SHA-256) + `openai_compatible` (`judge_common.build_openai_client` 재사용, 동일 env contract).

3. **신규 CLI `scripts/run_rationality_judge.py`**.
   - `--eval-summary` / `--output` / `--out-aggregate` / `--out-md` / `--backend` / `--traces-dir` / `--cache-dir` / `--token-budget`.
   - `eval/judges/llm_judge.py` 의 CLI 패턴과 1:1.

4. **신규 committable artifacts**:
   - `reports/real100/rationality.aggregate.json` — per-axis mean + 95 % bootstrap CI + effective_n.
   - `reports/real100/rationality.md` — axis 표 + bottom-3 case per axis (rationale review).
   - 둘 다 `.gitignore` allowlist 에 등재 (기존 `eda.md` / `distinguishing_power.md` sibling).

5. **`answer_reasoning` None-skip semantics — ADR 0054 의 substantive-only 의미를 trajectory 측정에도 적용**.
   - `synthesis_llm_call` 부재 케이스 (env=off 또는 stub answer backend) 는 `answer_reasoning = None`.
   - aggregate `effective_n["answer_reasoning"]` 가 실제 측정 가능했던 케이스 수 보고.
   - mean 분모 제외 — sample 부재 axis 는 `mean = None`, `ci` 미발행.

6. **측정은 stub backend + n=221, 3-axis 모두 measured**. 비용 0, deterministic. committed artifact (`reports/real100/rationality.aggregate.json`) 는 `cases_with_synthesis_llm_call=166` / `answer_reasoning` effective_n=166 (나머지 55 케이스는 abstention 으로 synthesis 미수행 → 정상 drop). 이를 위한 두 전제: ① **`answer_reasoning` 측정은 synthesis 가 도는 run 한정** — eval_summary 의 `case_results` 는 primary run 것만 담으므로(`run_eval.py`), real config 의 `primary_run` 이 `agentic_full_llm`(`prompt_profile=llm_synthesis`) arm 을 가리켜야 한다(또는 judge 를 `--traces-dir .../full_llm` 로 override). extractive `full` primary 로는 synthesis trace 가 case_results 에 없어 effective_n=0. ② **stub synthesis backend 가 `BIDMATE_TRACE_FULL=1` 에서 full I/O 를 캡처** — #1326 이전엔 `_stub_backend` 가 `user_prompt_text`/`completion_text` 를 반환하지 않아 effective_n=0 였다(#1297 이 pending 으로 정직하게 표시했던 상태). #1326 이 stub 캡처를 live backend 와 동일하게 고쳐 ② 를 해소. LLM backend 실측정(`BIDMATE_RATIONALITY_BACKEND=openai_compatible`)은 별 PR (token budget + cost analysis 동반). `--expect-full-trace` (#1297) 가 effective_n=0 인 full-trace 기대 run 을 incomplete 로 표면화.

## Why these specific choices

| 결정 | 근거 |
|---|---|
| Verifier axis 제외 (원래 sketch 의 3-axis 중 하나) | Step 2 (#968) 작성 중 발견 — `rag_verifier.py` 가 rule-based (LLM call 0건). LLM judge 의 ROI 가 약함 (sufficiency rule 의 재검증일 뿐). `answer_reasoning` 으로 대체 — 실 LLM call site (synthesis) 의 합리성 측정. |
| 1 LLM call per case (3-axis 합본) vs axis 별 3 call | RAGAS (Gate 3) 와 동일 — 3 LLM call 분할은 비용 3× / 일관성 위협. 합본 prompt 는 모든 axis 가 같은 trace context 를 봄. |
| `traces_dir` parameter 도입 | per-case trace JSON 이 `case.trace_path` 의 별도 파일 (eval_summary 에 embed 안 됨). traces directory 위치 override 옵션 — CI 환경에서 base/pr artifact 경로 다를 때 대응. |
| stub backend = SHA-256(trace subset, axis, case_id) | byte-identical cross-platform (Gate 3 stub 의 constant scores 보다 strong — case 별 차이 보존 → 분포 aggregate 가 stub 만으로도 의미 있음). 다른 backend 와 변별력 비교용 floor. |
| `cache_dir` 파라미터 reserve | 현재 stub 은 cache 불필요 (free + deterministic). LLM backend cache 는 follow-up PR — Gate 3 와 contract 호환 유지. |
| Markdown bottom-3 per axis | dashboard 없이도 rationale review 가능. `rag_pipeline.md` / `distinguishing_power.md` 의 1-screen surface convention 준수. |

## Consequences

- **Phase 3 audit item 3 (✗ absent → ✓ present)** 폐쇄. 5-step portfolio narrative ("측정 → 함정 발견 → 함정 fix → 측정 표면 audit → 자동 게이트 도입 → process rationality 측정 도입") 의 step 3 (= 측정 표면 완비) 까지 달성.
- 신규 `reports/real100/rationality.{md,aggregate.json}` 두 산출물 → eval surface 의 1-차원 추가.
- judge LLM backend 의 실 측정 비용 (n=221 × 1 LLM call = 221 LLM call/run) 은 별 PR scope. 본 PR 의 measurement scope = stub backend (0 cost, deterministic).
- `answer_reasoning` 의 effective_n 는 `BIDMATE_TRACE_FULL=1` + synthesis trace 캡처 여부에 의존. **#1326 측정에서 effective_n=166 (cases_with_synthesis_llm_call=166)** — synthesis-primary run (`agentic_full_llm`) + stub full-trace 캡처 wiring fix 로 3-axis 모두 measured. 나머지 55 케이스는 abstention 으로 synthesis 미수행(정상 drop, ADR 0054 substantive-only semantics). (이력: #987 최초 measured 주장 → #1297 이 effective_n=0 artifact 와의 모순을 pending 으로 정직 정정 → #1326 이 wiring 을 고쳐 measured 복원. 이전 본문의 "모든 case cover" 표현은 abstention drop 을 누락했던 부정확 — "synthesis 수행 case 전부 cover" 가 정확.)
- 향후 PR 에서 `Claim:` (ADR 0055) 으로 rationality axis 의 변화 보고 가능 — `Claim: planner_decomposition=+0.05pp` 식. 단 본 PR 에서는 baseline 측정만, claim 0건.

## Invariance check

- **ADR 0001** (`naive_baseline` byte-identical) — 본 judge 는 read-only consumer, production code path 0 변경 → 합성 baseline 영향 없음.
- **ADR 0003** (answer dict schema_version=2) — 변경 없음.
- **ADR 0005** (private real / public fixture smoke 분리) — `reports/real100/rationality.*` 는 ADR 0005 의 aggregate-only allowlist 패턴 그대로 (eda / distinguishing_power 와 동일). per-case (case id 포함) 는 `rationality.local.json` gitignored. `rationality.md` 의 bottom-3 행은 발주기관명-인코딩 qid 대신 익명 rank (`#1/#2/#3`) + slice + score 만 노출 (#1297 sanitize; 이전엔 raw qid 가 committed 되어 본 주장과 모순이었음 — `real-data-failure-taxonomy.md` 의 P-NN 컨벤션과 일관화).
- **ADR 0006** (LLM-judge real-data only) — rationality_judge 도 real eval surface 에서만 의미 (synthetic 의 trajectory 는 deterministic). 본 PR 의 첫 측정은 real n=221, ADR 0006 boundary 준수.
- **ADR 0054** (substantive-only scorer semantics) — `answer_reasoning` 의 None-skip 이 같은 의미를 trajectory 측정 layer 에 propagate.
- **ADR 0055** (claim_validator) — rationality axis 는 향후 `Claim:` 검증 대상이 될 수 있음. paired_bootstrap_ci 가 None pair drop 하므로 호환.

## Out-of-scope

- LLM backend 실측정 (`BIDMATE_RATIONALITY_BACKEND=openai_compatible`, n=221 × 1 call = ~$1 추정) — 별 PR.
- Verifier-axis rationality (Step 2 audit finding 으로 폐기 — `rag_verifier.py` LLM call 0).
- Planner full I/O trace dump (Step 2 surgical scope 외).
- Per-axis weighting / composite "process_health" score — 본 PR 은 raw axis 만, 합성 score 는 portfolio narrative 가 정해진 후 별 ADR.

## Verification

```bash
# Stub backend determinism + 6-case unit test
EMBEDDING_BACKEND=hashing python3 -m pytest -q tests/test_rationality_judge.py

# Real-eval regen at n=221 with BIDMATE_TRACE_FULL=1.
# answer_reasoning 측정은 synthesis 가 도는 run 한정 — local config 의
# primary_run 이 `agentic_full_llm`(prompt_profile=llm_synthesis) arm 을
# 가리켜야 case_results 에 synthesis trace 가 담긴다. extractive `full`
# primary 로는 effective_n["answer_reasoning"]=0 (synthesis 미수행).
BIDMATE_TRACE_FULL=1 BIDMATE_SYNTHESIS_BACKEND=stub make real-eval

# Score traces (stub backend, 0 cost). --expect-full-trace 로 answer_reasoning
# effective_n==0 (silently-incomplete) 인 run 을 exit 3 으로 표면화.
python3 scripts/run_rationality_judge.py \
  --eval-summary reports/real100/eval_summary.json \
  --output reports/real100/rationality.local.json \
  --out-aggregate reports/real100/rationality.aggregate.json \
  --out-md reports/real100/rationality.md \
  --backend stub --expect-full-trace

# Aggregate inspection
python3 -c "import json; r=json.load(open('reports/real100/rationality.aggregate.json')); \
  print('n:', r['n']); print('effective_n:', r['effective_n']); \
  print('means:', {k: round(v, 3) if v else None for k, v in r['axis_means'].items()})"
```

<!-- verifies-key: eval/judges/rationality_judge.py:judge_rationality -->
<!-- verifies-key: eval/judges/rationality_judge.py:_stub_backend -->
<!-- verifies-key: eval/judges/rationality_judge.py:_aggregate -->
<!-- verifies-key: scripts/run_rationality_judge.py:main -->
