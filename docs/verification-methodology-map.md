# 검증 가능한 문제풀이 방법론 × BidMate-DocAgent 매핑

> **목적.** "검증 가능한 문제풀이(verifiable problem-solving)" 방법론 11종을 이 레포가 **어디서 어떻게 제도화·강제하는지**의 단일 출처(single source of truth). 신규 agent·세션 핸드오프 시 "우리가 어떤 검증 방법론을 어느 표면에서 강제하는가"를 한 번에 파악하기 위한 reference 문서다.
>
> **성격.** 자동 강제되지 않는 **현황 매핑(reference)** — 새 측정 표면이나 baseline이 아니므로 ADR 임계값 대상이 아니다. [`CLAUDE.md`](../CLAUDE.md)의 "자동 강제 안 되는 원칙·포인터" 계열, [`docs/engineering-governance.md`](engineering-governance.md)·[`docs/agent-utilization.md`](agent-utilization.md)와 같은 거버넌스 reference 문서다.

## 사용처

- **신규 agent/세션 온보딩** — "이 레포가 검증을 어디서 강제하는지" 빠른 지도
- **새 방법론 도입 검토 전** — 이미 STRONG하게 커버되는지, 도메인 부적합 non-goal인지 먼저 대조 (무비판 도입 차단)
- **포트폴리오·핸드오프** — 암묵지(이미 하고 있음)를 형식지로 고정

## 출처 & 갱신

- 1차 진단: deep-interview 세션(2026-06-03, brownfield). 원본 spec은 `.omc/specs/`에 있으나 **gitignored**(레포 비추적) — 본 문서가 그 진단의 추적 가능한 영구판이다.
- **정정 이력**: 1차 진단은 #5 ReAct를 "PARTIAL(유일 코드 갭)", #11 property test를 "미구현 갭"으로 판정했으나, 본 문서 작성 시 별도 lane code-review가 코드 반증으로 둘 다 정정했다 — #5는 `agent_react` 프리셋(ADR 0040)으로 이미 STRONG, #11 property test는 [`tests/test_retrieval_invariants_property.py`](../tests/test_retrieval_invariants_property.py)(issue #1826)로 이미 구현. 이 정정 과정 자체가 Evaluator-Optimizer(#8) 원칙의 실증이다(§메타 참조).
- 갱신 규칙: 새 방법론 표면이 STRONG으로 승격되거나 non-goal 판정이 바뀌면 이 표를 갱신한다. 인용 경로/ADR 번호는 갱신 시 실재를 재확인한다.

## TL;DR

1. **도메인에 적합한 검증 방법론은 사실상 전부 제도화**되어 있다 — 8종 STRONG(#1·2·3·6·7·8·9·10) + #5 ReAct closed-loop(`agent_react` 프리셋, ADR 0040) + #11의 도메인 적합 형태(statistical + property/metamorphic test, 구현 완료). **미해소 코드 갭은 없다.**
2. 따라서 이 매핑의 가치는 "새 기법 도입"이 아니라 **(a) 암묵 강점의 명문화 + (b) 도메인 부적합 갭의 의식적 non-goal 기록**이다.
3. 도구 자동 분류가 보고한 "ABSENT 2개(ToT / Formal Methods)"는 **무비판 수용 대상이 아니다.** Formal Methods의 좁은 형태(property/metamorphic/statistical test)는 eval 도메인에 적합하고 이미 구현되어 있다. online-ToT / proof-assistant의 일반형만 도메인 부적합 non-goal이다 — "범용 AI 실험장 아님"([`CLAUDE.md`](../CLAUDE.md)) 정신과 정합한다.

## 11종 방법론 × 레포 표면

| # | 방법론 | 판정 | 레포 표면 (증거) |
|---|--------|------|-----------------|
| 1 | CoT / Scratchpad | **STRONG** | [`docs/plans/TEMPLATE.md`](plans/TEMPLATE.md)(assumptions/validation/failure-modes), ADR 본문, [`tasks/queue.md`](../tasks/queue.md) |
| 2 | Least-to-Most / 분해 | **STRONG** | [`tasks/queue.md`](../tasks/queue.md)(task + Ready Order + Owner), [`docs/plans/`](plans/), 1-day PR decomposition 패턴 |
| 3 | Self-Consistency / Best-of-N | **STRONG** (미시 갭 有) | [`eval/config.yaml`](../eval/config.yaml)(`naive_baseline` ↔ `agentic_full` side-by-side), 다중 ablation preset |
| 4 | Tree of Thoughts / Search | **NON-GOAL (online)** · 오프라인은 eval로 커버 | online tree-search 부재 = 의도된 부재. 오프라인 전략 비교는 `eval/config.yaml` ablation이 수행 |
| 5 | ReAct closed-loop | **STRONG** (opt-in 프리셋) | [`rag_graph_react.py`](../rag_graph_react.py)의 `react_loop`(plan_next→executor→verifier), [`rag_planner.py`](../rag_planner.py)(`StaticPlanner`/`LLMPlanner`), [ADR 0040](adr/0040-react-agent-loop-additive-preset.md)/[ADR 0041](adr/0041-agent-budget-cap-contract.md). agentic_full은 bounded verifier retry도 보유 |
| 6 | PAL / Code-as-Reasoning | **STRONG** | [`eval/`](../eval/) scorer, [`eval/bootstrap.py`](../eval/bootstrap.py), judge 스크립트, [`scripts/build_index.py`](../scripts/build_index.py) |
| 7 | Spec-First / Test-First | **STRONG** | TEMPLATE의 Acceptance Criteria 우선, `tests/test_*_regression.py`, ADR, pre-commit 게이트 |
| 8 | Evaluator-Optimizer / Critic | **STRONG** | pre-commit Codex adversarial([ADR 0066](adr/0066-codex-pr-adversarial-review.md)), [`docs/reviews/ai-review-checklists.md`](reviews/ai-review-checklists.md), [`scripts/run_real_eval_delta.py`](../scripts/run_real_eval_delta.py) |
| 9 | Multi-Agent / Orchestrator | **STRONG** | [`docs/multi-agent-ownership.md`](multi-agent-ownership.md)(role 분담), [`docs/agent-utilization.md`](agent-utilization.md)(5축 × 4-pillar), [`overlap-preflight`](operations/ai-codex-workflow.md#overlap-preflight)(병행 worktree 시작 전 겹침 증거) |
| 10 | Context Engineering / Memory | **STRONG** (미시 갭 有) | memory 시스템, [`tasks/queue.md`](../tasks/queue.md), plan 문서, [`docs/operations/long-session-workflow.md`](operations/long-session-workflow.md) |
| 11 | Formal Methods / Solver | **PARTIAL (도메인 적합 형태 구현)** | statistical test = STRONG([`eval/bootstrap.py`](../eval/bootstrap.py) bootstrap CI); property/metamorphic test = 구현됨([`tests/test_retrieval_invariants_property.py`](../tests/test_retrieval_invariants_property.py), #1826); 일반형(Lean/SAT/SMT) = non-goal |

## 재분류 논거 (자동 분류의 "ABSENT"를 수정한 이유)

증거 기반 반증 없이 도구의 자동 판정을 그대로 수용하지 않는다. 다음 둘은 도메인 렌즈로 재검토해 판정을 수정했다.

- **#11 Formal Methods — ABSENT → PARTIAL.** "검증 가능한 문제풀이" 원전의 11번은 proof assistant뿐 아니라 *brute-force oracle + randomized test, property-based testing, reproducible notebook + statistical test* 를 포함한다. 이 좁은 형태는 RFP RAG eval에 정확히 적합하다. [`eval/bootstrap.py`](../eval/bootstrap.py)의 paired bootstrap 95% CI는 이미 statistical test이고, [`tests/test_retrieval_invariants_property.py`](../tests/test_retrieval_invariants_property.py)가 `retrieve()`에 대한 metamorphic relation(INV-2 결정성, INV-3 chunk-순서 불변)을 property로 검사한다. 잔여는 일반형(Lean/SAT) 부재인데 이는 non-goal이다.
- **#4 ToT — ABSENT → NON-GOAL(online) + 오프라인 커버.** online tree-search/MCTS는 근거 기반 답변 생성의 latency·복잡도 대비 ROI가 없다(도메인 부적합). 단 "여러 retrieval 전략 비교 후 best 선택"의 **오프라인 형태는 [`eval/config.yaml`](../eval/config.yaml) ablation이 이미 수행**한다. 따라서 online은 non-goal, 오프라인은 커버됨 — 진정한 ABSENT가 아니다.

## #5 ReAct closed-loop — 어떻게 구현되어 있는가

이 레포는 ReAct를 두 층위로 제도화했다:

1. **`agentic_full` — bounded verifier retry.** `verifier_retry=True`([`rag_pipeline_presets.py`](../rag_pipeline_presets.py))로 실행되며, `metadata_stage_sequence()`([`rag_core.py`](../rag_core.py))가 `strict → reduced → relaxed` 단계 시퀀스를 생성한다. 각 단계에서 [`rag_verifier.py`](../rag_verifier.py)의 `verify_evidence()`를 호출하고, 근거가 부족하면 다음(더 완화된) 단계로 자동 재검색한 뒤 충분해지면 멈춘다. metadata filter 완화 방향의 적응적 재검색이다.
2. **`agent_react` — 진정한 closed-loop (ADR 0040, opt-in).** [`rag_graph_react.py`](../rag_graph_react.py)의 `react_loop` 노드가 `Planner.plan_next → executor → verifier` 사이클을 evidence가 grounded되거나 budget cap([ADR 0041](adr/0041-agent-budget-cap-contract.md), `max_iterations` 기본 5)에 도달할 때까지 반복한다. `Planner`는 5번째 pluggable 축([`rag_planner.py`](../rag_planner.py))으로, CI 기본값은 `StaticPlanner`(deterministic)이고 `LLMPlanner`는 `BIDMATE_PLANNER_BACKEND=anthropic`로 opt-in 활성화한다.

`LLMPlanner`를 기본값이 아닌 opt-in으로 둔 것은 **갭이 아니라 의도된 설계**다 — [ADR 0001](adr/0001-preserve-naive-baseline.md) `naive_baseline` byte-identical 보존과 [ADR 0024](adr/0024-agentic-full-llm-as-api-default.md)([ADR 0074](adr/0074-rfp-rag-stage-separation.md)로 단계 분리 보강) 기본값 정책을 지키기 위함이다. 따라서 ReAct closed-loop 방법론은 제도화 완료 상태이며, 1차 진단이 이를 "갭"으로 본 것은 자기가 인용한 ADR 0040을 간과한 오류였다(§출처 정정 이력).

## 적용 현황 & 방향

두 렌즈(A = RAG 답변 품질/eval 지표, B = 거버넌스/워크플로 성숙도)로 본 현황. 도메인 적합 방법론은 모두 구현 완료이며, 남은 항목은 선택적 점검 수준이다.

| 항목 | 렌즈 A | 렌즈 B | 상태 |
|------|:---:|:---:|------|
| #5 ReAct closed-loop (`agent_react`, bounded verifier retry) | ●●● | ●● | **구현됨** (ADR 0040/0041) |
| #11 retrieval invariant property/metamorphic test | ●●● | ●●● | **구현됨** (#1826) |
| #1·6·7·8·9·10 "방법론 ↔ 레포 표면" 명문화 | ○ | ●●● | **본 문서가 충족** |
| #4 online-ToT / #11 proof-assistant non-goal 기록 | ○ | ●● | **본 문서 §Non-goals가 충족** |
| #3 독립 검증기 다양성 충분성 점검 | ●● | ● | 선택(점검 수준) |
| #10 context compaction 자동화 점검 | ● | ●● | 선택(빈도 측정 후 결정, 빈도≠가치) |

### 선택적 점검 (Tier 3)

- **#3 — 검증기 다양성.** 원전은 *무작정 N↑보다 후보 다양성 + 독립 검증기*를 강조한다. 현 ablation이 진짜 독립적 접근 다양성을 갖는지(아니면 파라미터 변형만인지) 1회 점검할 수 있다. 강제 아님.
- **#10 — context compaction.** memory/queue는 STRONG이나 자동 compaction은 수동이다. 장기 세션 context pollution 빈도가 실제 문제인지 측정한 뒤 결정한다(빈도 ≠ 가치).

## Non-Goals (명시적 배제 + 사유)

이 레포는 RFP/입찰 문서 인텔리전스 전용이며 범용 AI 실험장이 아니다([`CLAUDE.md`](../CLAUDE.md)). 다음은 의식적으로 배제하며, 미래 agent의 무비판 도입을 차단하기 위한 명시적 방어선이다.

- **online Tree-of-Thoughts / MCTS 답변 탐색** — 근거 기반 RFP 답변에 트리 탐색은 latency·복잡도 대비 ROI가 없다. 오프라인 전략 비교는 [`eval/config.yaml`](../eval/config.yaml) ablation이 이미 충족한다.
- **proof assistant(Lean/Coq/Isabelle), SAT/SMT solver** — RFP 자연어 근거 도메인에 형식 증명은 부적합하다. #11의 가치는 *property/metamorphic/statistical test* 의 좁은 형태에 한정하며, 그 형태는 이미 구현되어 있다.
- **무비판 신규 외부 의존성** — [ADR 0061](adr/0061-external-and-paid-api-dependencies-allowed.md)의 3조건(opt-in / baseline byte-identical 보존 / 데이터 경계) 동시 충족 시에만 허용한다.

## 메타 — 이 매핑 자체가 4원칙의 시연

이 진단과 정정 과정 자체가 "검증 가능한 문제풀이"의 4대 원칙을 실행했다: **Decompose**(방법론을 11종으로 분해), **Diversify**(자동 분류 + 도메인 렌즈 재분류 = 2 관점), **Verify**(각 항목에 검증 신호 = ADR/파일 경로 + 코드 반증), **Manage context**(진단 상태를 외부 spec으로 분리 → 본 문서로 영구화). 특히 1차 진단이 #5를 "갭"으로 오판한 것을 별도 lane review가 `rag_graph_react.py`/`rag_planner.py` 코드 반증으로 정정한 것은 Evaluator-Optimizer(#8) 원칙 그 자체다 — **권고를 무비판 수용하지 않고 코드로 반증한다**는 이 레포의 작업 규율을 그대로 적용한 결과다.

## 관련 문서

- [`docs/engineering-governance.md`](engineering-governance.md) — 워크플로 맵
- [`docs/agent-utilization.md`](agent-utilization.md) — 5축 × 4-pillar agent 활용 매핑
- [`docs/multi-agent-ownership.md`](multi-agent-ownership.md) — 다중 agent 조율 모델
- [`docs/reviews/ai-review-checklists.md`](reviews/ai-review-checklists.md) — normal/adversarial/benchmark/regression review 체크리스트
- [`docs/evaluation/surface-map.md`](evaluation/surface-map.md) — smoke / synthetic benchmark / private real-eval 경계
