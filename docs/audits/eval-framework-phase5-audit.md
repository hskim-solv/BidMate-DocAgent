# eval-framework-progressive-audit — Phase 5 (closed error loop)

| field | value |
|---|---|
| Skill | [`.claude/skills/eval-framework-progressive-audit/SKILL.md`](../../.claude/skills/eval-framework-progressive-audit/SKILL.md) (PR #889) |
| Phase | **5 — Closed error loop audit** (skill line 166-184) |
| Date | 2026-05-18 |
| Author | Hyunsoo Kim |
| Issue | #990 |
| Predecessor | Phase 4 audit (#962 / PR #963, merged `e65f792`) — STOP gate 영수증; gap fixes Step 1-3 (PR #965/#968/#987) merged |
| Successor | None — sequence A closure. 5-phase progressive audit completed. |
| Strict-forbid | **실제 taxonomy / dashboard / harden-process 구현 0건** (skill body 통일 — audit only) |

## Executive summary

| # | item | 상태 | 핵심 evidence |
|---|---|:---:|---|
| 1 | Failure taxonomy 정의 (retrieval_miss / planner_under_decomposition / verifier_false_negative / verifier_false_positive / generator_hallucination / context_dilution / unknown 등) | ◐ partial | **abstention_outcomes 3-bin (PR #464) 존재** — `correct_refusal` / `incorrect_answer` / `boundary_partial` (`eval/run_eval.py:377-411`). **그러나 7-category taxonomy 부재** — `grep -E 'retrieval_miss\|planner_under_decomposition\|generator_hallucination\|context_dilution' --include='*.py'` 0건. 3-bin 은 refusal-axis 만 분류; 정답 실패 (incorrect_answer) 의 root-cause stage 추적 부재. |
| 2 | Failure distribution dashboard (per-category 분포 표 / bar chart) | ◐ partial | **3-bin counts 노출 ✓** — `reports/real100/baseline.aggregate.json` 의 `abstention_outcomes: {correct_refusal: 16, incorrect_answer: 87, boundary_partial: 0}` 와 같이 raw count 가 aggregate 에 있음. **per-stage failure distribution dashboard ✗** — `scripts/` 의 어떤 plotter 도 stage-별 failure breakdown 그래프 emit 안 함 (`plot_cost_frontier.py` / `plot_pareto.py` 는 cost-accuracy 만, EDA 류는 corpus shape 만). |
| 3 | Monotone-harden process (새 failure mode → 카테고리 추가 + ≥5 예제 eval set 추가 워크플로) | ✗ absent | `grep -E 'harden\|failure_mode\|new_category' --include='*.py' --include='*.md' docs/operations/` → 0건. `docs/operations/` 에 incident-driven category 확장 protocol 부재. `scripts/generate_real_cases.py` (PR #936 ADR 0052) 는 hardcase generator 지만 failure-mode-driven 워크플로 (e.g. "이번 분기 incorrect_answer 87 케이스 분석 → 신규 category X 발견 → eval set 에 5 예제 추가") 와 연결 안 됨. |

**판정**: partial 2 + absent 1. 가장 큰 갭 = **item 3 (monotone-harden process 부재)** — 본 audit 가 발견한 신규 failure mode (item 4 아래) 같은 신호가 들어와도 *workflow 가 없어서 누적되지 않음*.

## 본 audit 가 raw 측정에서 발견한 신규 failure mode

스킬 본문 (line 175-176) 의 추가 요구 — "audit 중 실제로 새 failure mode 1개 이상 raw 측정에서 발견 보고".

### Finding #1 — `verifier_false_negative_on_unanswerable` 대량 발생

**Raw 측정 source**: `reports/real100/baseline.aggregate.json` (post-PR #987, `8307819f`).

```json
"abstention_outcomes": {
  "correct_refusal": 16,
  "incorrect_answer": 87,
  "boundary_partial": 0
},
"num_predictions": 221
```

**해석**:
- 본 corpus 의 unanswerable subset (no_answer hardcase) 에서 시스템이 **87 case 답변 시도, 16 case 만 정확히 거부** → **incorrect_answer / (correct_refusal + incorrect_answer) = 87/103 ≈ 84%**.
- `boundary_partial = 0` 도 두 번째 신호 — boundary 케이스가 정확히 0건이라는 건 *verifier 가 binary 로만 reject/accept 하고 partial 정보를 보존 안 함* 을 시사. ADR 0003 (answer dict `status: partial`) 가 정의된 케이스가 실제 시스템 동작에서 emit 안 됨.

**Failure mode 정의**:
- **이름**: `verifier_false_negative_on_unanswerable`
- **분류**: verifier_false_negative 의 sub-category — *답이 없음을 모르고 답을 만들어내는* 케이스.
- **Root cause 가설** (확정 아님, 본 audit scope 외):
  1. verifier (`rag_verifier.py`) 의 sufficiency rule 이 evidence 의 *부재* 보다 *존재* 에 weight 가 강함 — partial evidence 가 retrieved 되면 strict reject 안 함.
  2. abstention 의 `no_answer` hardcase 가 generator 의 *evidence-on-topic-but-no-answer* 인식을 강제하지 않음.

**왜 신규인가**:
- ADR 0054 (PR #959 scorer fix) 가 *측정 layer* 에서 vacuous-truth 1.0 을 제거했지만, *시스템 동작* 자체의 84% incorrect_answer rate 는 ADR 0054 이전에도 있었던 *시스템 layer* failure mode 다. ADR 0054 가 측정 정직성을 회복했기에 *이제 보이는* failure mode.
- Phase 3 audit (#961) 의 4-item / Phase 4 audit (#963) 의 3-item 중 어디에서도 이 mode 가 명시 진단되지 않았음 — 본 audit 가 trace v2 (PR #968) + rationality_judge (PR #987) 누적 후 처음 표면화.

### Finding #2 — abstention slice 의 planner 약점 (보조 신호)

**Raw 측정 source**: `reports/real100/rationality.md` (PR #987 산출).

```
### `planner_decomposition` — bottom 3
- real_hanyeong_noanswer_트랙시스템_예산규모   (slice=abstention) = 0.001
- real_광주연구원_no_answer_penalty_rate       (slice=abstention) = 0.003
- real_BIFF_penalty_clause_no_answer            (slice=abstention) = 0.005
```

bottom-3 planner_decomposition 모두 abstention slice. 단 — 현재 측정은 stub backend (SHA-256 해시) 이므로 *signal 강도 약함* (uniform 분포). LLM backend regen (별 PR scope) 이후 진짜 신호 여부 재확인 필요. **보조 신호** 로만 분류.

## 상세 진단

### Item 1 — Failure taxonomy 정의

**스킬 요구 (line 168-170)**: 시스템이 실패할 때 어느 단계에서 실패했는지 분류 가능한 taxonomy 존재 — retrieval_miss / planner_under_decomposition / verifier_false_negative / verifier_false_positive / generator_hallucination / context_dilution / unknown 등.

**현재 wiring**:
- **abstention_outcomes 3-bin (PR #464)**: `eval/run_eval.py:377-411` 의 `compute_abstention_outcome()` — `correct_refusal` / `incorrect_answer` / `boundary_partial`. 단 *refusal-axis 만* 분류 (answerable vs abstained 대각선의 4 quadrant 중 abstained 행).
- **answerable=True 의 실패 분류 부재**: answerable case 가 fail 했을 때 root-cause stage (retrieval / verifier / generator) 추적 0건.
- **trace v2 (PR #968, ADR 0001 invariance 유지)** 가 raw 자료 (planner attempts / synthesis prompt+completion) 는 dump 하지만, *category 라벨* 은 emit 안 함.

**Gap**:
- 7-category 분류기 (e.g. `eval/scorers/failure_classifier.py:classify(case, trace, expected) -> str`) 부재.
- 분류 없이는 distribution dashboard (item 2) / harden process (item 3) 모두 의미 불충분.

**Supply 제안** (별 PR):
- 신규 `eval/scorers/failure_classifier.py` (~150 LOC) — `classify_failure(case_result: dict) -> str` returning one of 7 categories.
- Rule-based 분류 (LLM-judge 와 별도, deterministic):
  - retrieval_miss: `case["evidence"] == []` 또는 expected doc not in retrieved
  - planner_under_decomposition: query_type=comparison/multi_hop 인데 `trace["planner"]["attempts"]` ≤ 1
  - verifier_false_negative: answerable=False AND status=supported (= 본 audit 의 87/103 패턴)
  - verifier_false_positive: answerable=True AND status=insufficient AND expected_terms 가 evidence 에 존재
  - generator_hallucination: claim 의 citation 이 evidence 에 부재
  - context_dilution: top_k 가 default 보다 크고 expected doc 가 lower rank (k>4 의 케이스)
  - unknown: 위 6 조건 미해당
- 출력: `case_results[*].failure_category: str` 신규 필드 (schema_version bump 검토).
- 추정 ~150 LOC + 1 test (각 카테고리 1 fixture).
- ADR 후보: 신규 측정 표면 도입 — ADR 0057 (가칭) 가 contract 고정 필요할 가능성.

### Item 2 — Failure distribution dashboard

**스킬 요구 (line 171-172)**: 카테고리 별 실패 비율을 보여주는 dashboard / aggregate report.

**현재 wiring**:
- **3-bin counts 노출 ✓**: `reports/real100/baseline.aggregate.json::abstention_outcomes` — raw counts emit.
- **Markdown 표 부재**: `reports/real100/` 어디에도 abstention_outcomes 의 percentage 표 render 안 됨. `reports/real100/eda.md` 는 corpus shape 만, `distinguishing_power.md` 는 gauge 만, `rag_pipeline.md` 는 retry/cost 만.
- **per-category bar chart 부재**: `scripts/plot_*.py` 중 failure-category-axis plotter 0건.

**Gap**:
- Item 1 의 7-category 분류기 도입 이후 부산물로 자동 emit 되어야 할 distribution table 부재.
- 현 3-bin (refusal-axis) 만으로도 표 + Markdown render 가능한데 안 됨.

**Supply 제안** (별 PR — item 1 이후):
- `scripts/render_failure_distribution.py` (~80 LOC) — `eval_summary.json` 읽고 `reports/real100/failure_distribution.{md,aggregate.json}` emit.
- 산출 schema: `{category_counts: {retrieval_miss: int, ..., unknown: int}, total: int, percentages: {...}}`.
- Markdown 은 단일 표 + 본 audit 의 finding #1 같은 highlight section.
- `.gitignore` allowlist 패치 (기존 `distinguishing_power.{md,aggregate.json}` 패턴 동일).
- ADR 미발행 (read-only 산출물, 측정 표면 추가).
- 추정 ~80 LOC + 1 test.

### Item 3 — Monotone-harden process

**스킬 요구 (line 173-176)**: 신규 failure mode 가 발견될 때마다 (a) 카테고리 추가, (b) ≥5 예제를 eval set 에 추가, (c) regression test 가 그 category 의 fail rate 가 임계값 이하로 유지되는지 강제하는 워크플로 존재.

**현재 wiring**:
- **(a) 카테고리 추가 워크플로 부재**: item 1 supply 자체가 안 들어왔으므로 카테고리 자체가 부재.
- **(b) hardcase generator 존재 ✓**: `scripts/generate_real_cases.py` (PR #936, ADR 0052) — 5 enum (distractor_heavy / ambiguous_query / multi_hop / no_answer / long_context) 기반 LLM-assisted generator. 단 enum 은 **query-shape** axis (어떤 모양의 query?), failure-mode axis (왜 fail?) 아님. cross-mapping 부재.
- **(c) regression test 부재**: `tests/test_*_regression.py` 가 specific bug fix 의 lock-in 은 보호 (e.g. `test_retrieval_loop_regression.py`) 하지만 *category fail rate ceiling* 같은 aggregate invariant 는 lock-in 안 됨.

**Gap**:
- 본 audit 의 finding #1 (87/103 incorrect_answer) 가 들어와도 *어디에도 누적 안 됨* — 다음 분기에 같은 신호가 나와도 다시 raw inspection 으로 발견해야 함.
- ADR 0055 (claim_validator) 가 *improvement claim* 의 자동 검증을 도입했듯, 본 item 의 supply 는 *failure regression* 의 자동 차단을 도입할 수 있음.

**Supply 제안** (별 PR — item 1 + item 2 이후):
- 신규 `docs/operations/failure-mode-harden-process.md` (~100 LOC) — 워크플로 정의:
  1. raw incident → trace inspection → 신규 category 후보 등록
  2. category 별 ≥5 예제를 `eval/real_config.local.yaml` (or 합성 `eval/config.yaml`) 에 hardcase 로 추가
  3. `eval/run_eval.py` 가 category 별 fail rate emit
  4. `tests/test_failure_rate_regression.py` 가 category 별 ceiling 보호 (e.g. `verifier_false_negative_on_unanswerable ≤ 0.30`)
- ADR 후보: ADR 0058 (가칭) — failure regression contract.
- 추정 ~100 LOC docs + ~50 LOC regression test + 1 ADR.

## 시퀀스 A 5-phase closure 영수증

| Phase | Audit PR | Gap fix PR | Closure |
|---|---|---|---|
| 1 (component-level isolation) | (skill 본문 Phase 1) | — | (본 시퀀스 외) |
| 2 (oracle ceilings) | (skill 본문 Phase 2) | — | (본 시퀀스 외) |
| 3 (process + trajectory) | **#961** `c50a3e7` | item 2 → **#968** `9cb6c00` (trace v2) / item 3 → **#987** `8307819f` (rationality_judge ADR 0056) | ✓ |
| 4 (statistical rigor) | **#963** `e65f792` | item 3 → **#965** `7370fa0` (claim_validator ADR 0055) | ✓ |
| 5 (closed error loop, **본 audit**) | **#990 / 본 PR** | — (audit only per skill) | ◐ 진단 완료, supply 별 PR |

**시퀀스 A 의 5-step portfolio narrative**:
1. 측정 표면 도입 (PR #946 distinguishing-power gauge)
2. Goodhart 함정 발견 + scorer semantics fix (PR #959 ADR 0054)
3. 측정 표면 audit (PR #961 + #963 Phase 3/4 audit)
4. 자동 게이트 도입 (PR #965 ADR 0055 claim_validator + PR #968 trace v2)
5. Process rationality 측정 표면 도입 (PR #987 ADR 0056 rationality_judge)
6. **Closed error loop audit (본 PR)** — 5-phase progressive audit 완주

## Out-of-scope (별 PR / 별 plan turn)

- Item 1 supply (failure_classifier.py + ADR 0057) — 별 PR scope.
- Item 2 supply (failure_distribution.{md,aggregate.json} + plot) — 별 PR scope.
- Item 3 supply (failure-mode-harden-process docs + regression test + ADR 0058) — 별 PR scope.
- LLM backend 로 rationality_judge regen (n=221 × 1 LLM call) — Step 3 (ADR 0056) Out-of-scope 와 동일.
- Phase 1/2 retro-fill audit (시퀀스 A 외, skill body 의 Phase 1/2 spec 그대로) — 별 시퀀스.

## Critical files (read-only inspect 대상)

- `reports/real100/baseline.aggregate.json` (post-PR #987 8307819f) — abstention_outcomes raw counts
- `reports/real100/rationality.aggregate.json` + `rationality.md` (PR #987 산출) — bottom-3 per axis
- `eval/run_eval.py:377-411` `compute_abstention_outcome` (PR #464 wiring)
- `rag_verifier.py` (rule-based, LLM call 0 — Step 2 audit finding)
- `scripts/generate_real_cases.py` (PR #936 ADR 0052) — hardcase generator (현 query-shape axis)
- `docs/audits/eval-framework-phase3-audit.md` (PR #961) — Phase 3 audit format reference
- `docs/audits/eval-framework-phase4-audit.md` (PR #963) — Phase 4 audit format reference
- `.claude/skills/eval-framework-progressive-audit/SKILL.md:166-184` — Phase 5 spec

## Verification

- audit doc 의 3-item 표 인용한 file path 모두 실제 존재 (`ls` 1회).
- 본 audit 가 발견한 finding #1 의 raw count (87/103) 가 `reports/real100/baseline.aggregate.json` 에 실제 존재 (`python3 -c "import json; print(json.load(open('reports/real100/baseline.aggregate.json'))['abstention_outcomes'])"`).
- PR body §5b heading 존재 (CI lint gate).
- `gh pr checks <PR-N>` 11 gate 전부 green.
