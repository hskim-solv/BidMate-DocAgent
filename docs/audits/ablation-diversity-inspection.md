# Ablation 다양성 점검 — Self-Consistency 검증기 다양성 audit

> **목적.** `eval/config.yaml`의 ablation preset 집합이 "검증 가능한 문제풀이" #3 원칙(**무작정 N↑보다 독립 접근 다양성 + 독립 검증기**)을 충족하는지 1회 점검한다. [`docs/verification-methodology-map.md`](../verification-methodology-map.md)의 #3(Self-Consistency, STRONG·미시 갭 有) 판정을 심화하는 audit이다.
>
> **결론 미리.** ablation 집합은 단순 파라미터 스윕이 아니라 **의도된 3층 구조**(독립 접근 / 컴포넌트 ablation / floor control)를 가진다. 유일한 ablation row 부재 갭은 `full_hyde`(쿼리 확장 축)이며, floor 대조 gauge(`scripts/distinguishing_power.py`)는 이미 구현돼 있다(자동 경보 wiring만 후속).

## 점검 시점 컨텍스트 (중요)

- **시점**: 2026-06-03. 점검 당시 Codex(omx) 다수 worktree가 `eval/config.yaml`·`rag_reranker.py`·`rag_retrieval.py`를 **동시 수정 중**(reranker candidate-budget 실험군).
- **robust vs 변동**: 본 audit의 **분류 방법론(3층 구조)**과 **런타임 self-consistency non-goal 판정**은 config 세부가 바뀌어도 유효하다. 반면 아래 **preset 목록 수치·`full_hyde` 갭**은 그 시점 관찰이며 동시 작업으로 변동될 수 있다 — 사용 시 현재 `eval/config.yaml`과 대조할 것.
- 본 audit은 분석 산출물이다. `eval/config.yaml`/`run_eval.py`/ADR 변경은 동시 작업 충돌 회피를 위해 의도적으로 포함하지 않으며 §권고에서 follow-up으로 분리한다.

## TL;DR

1. 점검 시점 15개 ablation preset은 **3층 구조**다 — 독립 접근 다양성으로 "무엇이 더 나은가", 컴포넌트 ablation으로 "어느 컴포넌트가 기여하는가", floor control로 "신호 자체가 유효한가"를 각각 측정. 단순 파라미터 변형 아님.
2. **유일한 ablation row 부재 갭은 `full_hyde`** — 쿼리 확장(query_expansion) 축이 전 preset에서 `identity` 고정. [ADR 0023](../adr/0023-hyde-query-expansion-ablation.md)이 `full_hyde` row 추가를 결정했으나 status가 proposed에 머물러 미반영. never-raise fallback이 이미 있어 CI를 막지 않는다.
3. **런타임 self-consistency(단일 쿼리 N-path 다수결)는 의도적 부재 = non-goal로 타당** — RFP 근거 추출 도메인에선 [`rag_verifier.py`](../../rag_verifier.py)의 근거 충분성 판정이 단일경로 신뢰 메커니즘을 대체한다.

## 3층 구조 분류 (점검 시점 15 preset)

| 범주 | preset | 변형 축 |
|------|--------|---------|
| **독립 접근 다양성** (6) | `full` | hybrid 풀 파이프라인 (기준 비교점) |
| | `full_llm` | 답변 생성 = LLM 합성 ([ADR 0011](../adr/0011-llm-synthesis-as-additive-ablation.md) additive path) |
| | `full_llm_metadata` | metadata 추출 = anthropic_tool_use (vs regex) |
| | `agent_react` | 계획 = ReAct 루프 (vs 정적 plan) |
| | `agentic_full_finetuned` | 임베딩 공간 = KURE-v1 + LoRA |
| | `naive_baseline_finetuned` | 기준선 × 파인튜닝 교차 |
| **컴포넌트 ablation** (5) | `full_dense` | retrieval_backend hybrid→dense 단일 knob |
| | `no_metadata_first` | metadata_first 기여도 |
| | `no_rerank` | rerank 기여도 |
| | `no_verifier_retry` | verifier_retry 기여도 |
| | `retrieval_only` | rerank+verifier_retry 동시 제거 (상호작용) |
| **속도 parity** (1) | `full_bm25s` | BM25 구현체(bm25s). [ADR 0057](../adr/0057-bm25s-additive-backend.md): okapi와 **동등 품질**("개선 신호 아님") — 품질 다양성 아닌 속도/안전성 비교 |
| **floor control** (2) | `single_chunk` | top_k=1 단일 청크 하한 |
| | `random_retrieval` | 무작위 검색 하한 (SHA-256 결정적) |
| **기준선** (1) | `naive_baseline` | [ADR 0001](../adr/0001-preserve-naive-baseline.md) dense-only 불변 기준점 (floor 겸) |

직교하는 5개 독립 축(retrieval 채널 / 답변 생성 / 계획 / metadata 추출 / 임베딩 공간)에서 근본적으로 다른 방법을 비교하므로, "독립 접근 다양성"은 genuine하다.

## 관찰 1 — `full_bm25s`는 다양성이 아닌 속도 parity

[ADR 0057](../adr/0057-bm25s-additive-backend.md)은 `bm25s`와 `BM25Okapi`를 **동등 품질**로 결론낸다 — 작은 fixture에선 ranking이 완전 일치하고, 큰 corpus에선 IDF 분포 차이로 tie-break 일부가 갈리나 순서 overlap이 높게 유지된다. ADR은 이 overlap을 "swap의 **안전성** 신호이지 **개선** 신호가 아니다"로 명시하고, 결론도 "동등 품질이되 현 스케일에선 더 느림 → opt-in additive"다(정확한 측정 수치는 ADR 0057 본문 참조). 따라서 `full`과 `full_bm25s`는 품질 다양성 축이 아니라 backend 속도/안전성 비교이며, 독자가 품질 다양성 preset으로 오해하지 않도록 config 주석 명시를 권고(follow-up).

## 관찰 2 — `full_hyde` 갭 (유일한 실제 갭)

전 preset이 `query_expansion: identity`다. [ADR 0023](../adr/0023-hyde-query-expansion-ablation.md)은 `full_hyde`(`query_expansion: hyde`) row 추가를 결정으로 명시하지만 ADR status가 **proposed**에 머물러 `eval/config.yaml`에 반영되지 않았다.

"HyDE는 LLM 호출이라 deterministic CI 불가"는 근거가 되지 않는다 — `full_llm`/`agent_react` 같은 LLM 의존 preset이 이미 never-raise fallback(API key 없으면 extractive로 저하)으로 CI smoke에서 돌고 있고, HyDE도 동일한 fallback 패턴을 갖췄다. 즉 (b) 진짜 누락 갭이며, ADR 0023 status가 보류 중이라 미반영된 것이다.

단 이는 검증 *방법론*의 부재가 아니라 이미 결정된(ADR 0023) ablation row 하나의 미반영이다 — [`docs/verification-methodology-map.md`](../verification-methodology-map.md)의 "미해소 코드 갭 없음"(11종 방법론 축) 판정과 모순되지 않는다.

## 관찰 3 — floor 대조 gauge는 구현됨, run_eval.py 인라인 경보로는 미연결

`random_retrieval`/`single_chunk`는 코드 주석상 floor로 설계됐다("accuracy가 random의 noise 범위로 붕괴하면 retrieval 신호가 일을 안 하는 것"). 이 floor 대조 자체는 **이미 구현돼 있다** — `scripts/distinguishing_power.py`([ADR 0053](../adr/0053-distinguishing-power-floor-ablations.md) Implemented: #946 PR-5b + #1367 신뢰성 hardening)가 `(default − floor) / (ceiling − floor)` "신호가 살아있는가" 단일 gauge를 계산한다. 다만 두 한계가 남는다: (a) 이 gauge는 `run_eval.py` 본 파이프라인이 아닌 **별도 후처리 스크립트**이고, (b) private eval aggregate(gitignored)를 입력으로 요구해 public fixture smoke 경로에서는 자동 발화하지 않는다. 즉 floor 대조 *집계 도구*는 있으나 *run_eval.py 인라인 자동 경보*로는 wiring돼 있지 않다.

## 관찰 4 — 런타임 self-consistency는 non-goal (타당)

단일 쿼리에 N개 독립 경로를 병렬 실행해 다수결/일치도로 확신도를 측정하는 전형적 Self-Consistency(Wang et al. 2022)는 부재한다. RFP 근거 추출 도메인에서 이는 non-goal로 타당하다:

- **대체 메커니즘**: [`rag_verifier.py`](../../rag_verifier.py)의 `verify_evidence`는 "claim이 evidence text에 근거하는가"를 판정한다 — 샘플링 다양성이 아닌 근거 존재 기반 신뢰 측정.
- **도메인**: RFP 답변은 "어느 청크에 근거가 있는가"의 추출 문제이지 LLM이 다양한 추론 경로로 생성하는 문제가 아니다. 답변 계약([ADR 0003](../adr/0003-structured-answer-citation-contract.md))의 claims/citations는 extractive에서 온다.
- **비용**: N회 병렬 LLM 호출은 latency 예산(`eval/config.yaml` `latency_budgets.full` p95=2500ms)과 충돌한다.

한계: `full_llm`/`agent_react`처럼 LLM 합성이 개입하는 경로에서 답변 텍스트 variance는 단일경로 verifier가 잡지 못할 수 있다 — 다만 이는 extractive 기본 경로의 non-goal 판정과 별개다.

## 권고 (전부 follow-up — Codex eval 동시작업과 조율 필요)

1. **`full_hyde` row 추가** + ADR 0023 status 확정(accepted 또는 보류 사유 명시). config 1줄 + latency_budget 1줄. never-raise fallback 있어 CI 안전.
2. **`full_bm25s` 재분류 주석** — "속도 parity 검증, 품질 다양성 아님"을 config에 명시.
3. **floor 경보 인라인 wiring** — 이미 구현된 `distinguishing_power.py` gauge를 `run_eval.py` 경로(또는 public smoke 산출물)에 연결해, floor 대조 신호 유효성 경보가 별도 후처리 없이 자동 발화하도록.

> 위 1–3은 `eval/config.yaml`/`run_eval.py`/`docs/adr` 수정을 수반하며, 점검 시점 Codex omx가 그 영역을 다수 worktree에서 동시 수정 중이라 충돌 회피를 위해 별도 issue로 분리한다.

## 한계

`reports/eval_summary.json` 부재로 preset 간 점수 분포(진짜 독립 신호인지)는 확인하지 못했다. public fixture smoke는 n=5라 bootstrap CI가 유효하지 않아 preset 간 통계적 구분도는 논할 수 없다 — 이는 [`docs/evaluation/surface-map.md`](../evaluation/surface-map.md)의 smoke/private-eval 경계 정책상 의도된 것이며, 실제 구분도는 private real-eval에서 측정한다.

## 관련 문서

- [`docs/verification-methodology-map.md`](../verification-methodology-map.md) — 11종 방법론 × repo 매핑 (#3 Self-Consistency 본 audit의 상위)
- [`docs/evaluation/surface-map.md`](../evaluation/surface-map.md) — smoke / synthetic / private real-eval 경계
- [ADR 0023](../adr/0023-hyde-query-expansion-ablation.md) (HyDE) · [ADR 0057](../adr/0057-bm25s-additive-backend.md) (bm25s) · [ADR 0001](../adr/0001-preserve-naive-baseline.md) (기준선) · [ADR 0011](../adr/0011-llm-synthesis-as-additive-ablation.md) (LLM 합성)
