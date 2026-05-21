# 0062: Failure-rate regression contract (Phase 5 supply 3)

- Status: proposed
- Date: 2026-05-19
- Deciders: Hyunsoo Kim
- Related: ADR 0059 (failure-mode classifier), Phase 5 audit (#992) item 3, supply 2 dashboard (PR #1004), audits #1005 / #1020 / #1025, issue #1066

## Context

ADR 0059 (PR #1001) 가 7-카테고리 `failure_classifier.py` 를 도입했고
supply 2 dashboard (PR #1004) 가 그 분포를 렌더링한다. 이어 3건의 감사(audit)가
지배적 mode 를 정량화 — `retrieval_miss=83` (#1005),
`verifier_false_negative=76` (#1020), 그리고 cross-HEAD 분산(variance) 출처
(#1025). 그러나 Phase 5 audit (#992) item 3 "closed error loop" 는
**여전히 absent**: 이 mode 들의 *silent 회귀(regression)를 막는 것이 없다*.
audit 가 표현했듯이 (`docs/audits/eval-framework-phase5-audit.md`), finding 이
"어디에도 누적 안 됨 — 다음 분기에 같은 신호가 나와도 다시 raw inspection으로
발견" — 신호가 ratchet 되지 않으므로 같은 회귀가 탐지되지 않은 채
재발할 수 있다.

variance audit (#1025) 는 또한 절대 failure count 가
*HEAD 별로는* deterministic 이지만 cross-HEAD 로는 변동함을 확립했다(verifier_false_negative
가 PR #1001 / #1004 / #1018 에 걸쳐 49 ↔ 65 ↔ 76 범위). 어떤 ceiling 계약이든
매 baseline regen 마다 flap 하는 대신 그 문서화된 cross-HEAD 분산을 흡수해야 한다.

## Decision

두 부분으로 구성된 **failure-rate regression contract** 를 도입한다:

1. `tests/test_failure_rate_regression.py` 가 커밋된
   `reports/real100/baseline.aggregate.json` (aggregate-only, ADR 0005
   경계) 를 읽고, gate 대상 각 카테고리의 failure RATE
   (`count / num_predictions`) 가 **monotone-ratchet ceiling** 아래에
   머무는지 단언(assert)한다. 현재 gate 대상: `total_failure_rate ≤ 0.86`,
   `verifier_false_negative ≤ 0.40`, `retrieval_miss ≤ 0.34`. ceiling 은
   #1025 가 측정한 cross-HEAD 분산을 흡수하도록 현재 커밋된 rate 위에
   margin 을 둔다. Issue F/G/A-class 수정이 land 함에 따라 **아래로만**
   ratchet 가능 — gate 대상 rate 를 ceiling 너머로 악화시키는 baseline regen 은
   tighten-or-justify 해야 한다(테스트가 실패해 인지를 강제), 절대
   silent 회귀하지 않는다.

2. `docs/operations/failure-mode-harden-process.md` 가
   monotone-harden 워크플로를 문서화한다: audit 가 새 failure mode 를 표면화하면 →
   (a) `failure_classifier.py` 에 그 카테고리 추가/확인 + lock 테스트,
   (b) real-eval set 에 대표 예시 ≥5 추가, (c) `test_failure_rate_regression.py` 에서
   그 ceiling 설정 또는 tighten, (d) supply 2 dashboard 가 렌더링. 이것이 closed loop 다.

테스트는 또한 ADR 0059 first-match 계약
(`verifier_false_negative == abstention_outcomes.incorrect_answer`) 을 재단언하여
이를 깨뜨리는 향후 ordering 변경도 regression gate 를 실패시키도록 한다.

production code path 변경 없음 (`rag_*.py`, `api/`, `eval/config.yaml`
미터치). 테스트는 커밋된 baseline 의 read-only consumer 이며, private 데이터
없이 CI 에서 실행된다.

## Consequences

- **Phase 5 audit item 3 (✗ absent → ✓ present)** — closed error loop:
  지배적 failure mode 가 이제 측정만 되는 게 아니라 gate 된다. `verifier_false_negative`
  또는 `retrieval_miss` 가 ceiling 을 넘는 silent 회귀는 Pytest gate 를
  red 로 만든다.
- Phase 5 supply trilogy (1 classifier / 2 dashboard / 3 regression
  contract) 가 완성됨; portfolio narrative 가 "측정 → 분류
  → dashboard → ceiling 잠금" loop 를 닫는다.
- 향후 수정 PR (Issue F verifier hardening / Issue A top_k ablation /
  Issue G multi-doc topic spread) 은 구체적 ratchet 목표를 가진다: 커밋된
  rate 를 낮추고, 같은 PR 에서 ceiling 을 tighten.
- 비용: gate 대상 rate 를 악화시키는 baseline regen 은 이제 수정이나
  명시적 `[ALLOW_REGRESSION]` ceiling bump 중 하나가 필요 — 설계상 regen PR 에
  약간 더 많은 마찰.
- ADR 0001 (naive_baseline byte-identical) / 0003 (answer dict) / 0005
  (eval-split aggregate-only) / 0059 (classifier additive) 불변식 모두
  보존.

## Alternatives considered

- **절대 count 로 gate** — 기각: variance audit (#1025) 가
  count 는 cross-HEAD 로 이동함을 보임; 문서화된 margin 을 가진 rate 가 더 안정적.
- **모든 카테고리 gate** — v1 에서는 기각: planner/generator/context
  카테고리는 near-zero 이고 noisy 함; 2개 지배적 mode + total 을 gate 하는 것이
  high-signal subset. audit 가 표면화함에 따라 카테고리 추가 (그것이
  바로 harden process).
- **테스트 내에서 real-eval 실행** — 기각: private 데이터는 CI 에 들어올 수 없음
  (ADR 0005). 커밋된 aggregate 를 읽으면 gate 가 CI-runnable 하고
  deterministic 하게 유지된다.

## Verification

<!-- verifies-key: tests/test_failure_rate_regression.py:CEILING_RATE_BY_CATEGORY -->
<!-- verifies-key: tests/test_failure_rate_regression.py:def test_gated_category_rates_under_ceiling -->
<!-- verifies-key: tests/test_failure_rate_regression.py:def test_adr_0059_first_match_contract -->
<!-- verifies-key: docs/operations/failure-mode-harden-process.md:monotone-harden -->
