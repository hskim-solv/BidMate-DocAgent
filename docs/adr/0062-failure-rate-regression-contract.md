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

세 부분으로 구성된 **failure-rate regression contract** 를 도입한다:

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

3. `scripts/check_branch_and_issue.py --check-ceiling-ratchet` (CI 의
   `branch-and-issue-check.yml` 에 wired) 가 커밋된 ceiling 을 base 브랜치와
   diff 하여, gate 대상 ceiling 을 **상향**하거나 gated 카테고리를 **제거**하는
   PR 을 PR 본문에 명시적 `[ALLOW_REGRESSION: <category> ...]` 토큰이 없으면
   실패시킨다. 이것이 "정당화 없이는 절대 올라가지 않는다" 를 운영자 규율이
   아닌 실제 gate 로 만든다. in-test `test_ceilings_are_monotone_sane` 은
   ceiling 을 현재 rate *아래로* 두는 역전(inversion)만 가드하며 상향 자체는
   잡지 못하므로, 이 CI gate 가 그 갭을 닫는다 (issue #1150).

테스트는 또한 ADR 0059 first-match 계약
(`verifier_false_negative == abstention_outcomes.incorrect_answer`) 을 재단언하여
이를 깨뜨리는 향후 ordering 변경도 regression gate 를 실패시키도록 한다.

**CI 강제 vs 운영자(operator) 실행 (정직한 경계).** CI 가 강제하는 것:
(i) 커밋된 baseline 의 rate ≤ ceiling (위 pytest gate — 커밋된 aggregate 를
읽으므로 private 데이터 없이 CI 에서 실행), (ii) ceiling ratchet (위 #3 CI gate
— 정당화 없는 ceiling 상향/제거 차단). CI 가 강제하지 **못하는** 것:
head-vs-baseline 회귀 탐지 — "이 코드 변경이 *실제로* failure mode 를
악화시켰는가". real-eval 은 private-local (ADR 0005) 이라 CI 에 head eval 을
실행할 수 없다. 그 탐지는 운영자가 `make real-eval` + `make real-eval-delta` 를
돌리는 단계이며, delta 는 `failure_category_counts` 도 표면화한다
(`scripts/run_real_eval_delta.py`). load-bearing 변경의 §5b 요구가 운영자에게
그 실행을 촉구하는 discipline hook 이다. **잔여 갭(residual gap)**: failure mode 를
악화시키지만 baseline 을 regen 하지 않는 코드 변경은 CI 에 보이지 않는다 —
폐루프는 운영자가 real-eval 을 돌려 회귀가 커밋된 baseline 에 반영될 때 비로소
ceiling 테스트가 발화하는 것에 의존한다.

production code path 변경 없음 (`rag_*.py`, `api/`, `eval/config.yaml`
미터치). 테스트는 커밋된 baseline 의 read-only consumer 이며, private 데이터
없이 CI 에서 실행된다. ceiling-ratchet gate 도 커밋된 ceiling 소스만 비교하므로
마찬가지로 private 데이터 없이 동작한다.

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
  명시적 `[ALLOW_REGRESSION]` ceiling bump 중 하나가 필요하고, ceiling 상향/제거는
  PR 본문의 `[ALLOW_REGRESSION: <category> ...]` 토큰을 CI 가 확인한다
  (issue #1150) — 설계상 regen PR 에 약간 더 많은 마찰.
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
<!-- verifies-key: tests/test_failure_rate_regression.py:def test_adr_0075_first_match_contract -->
<!-- verifies-key: docs/operations/failure-mode-harden-process.md:monotone-harden -->
<!-- verifies-key: scripts/_governance.py:def ceiling_ratchet_violations -->
<!-- verifies-key: scripts/check_branch_and_issue.py:def check_ceiling_ratchet_mode -->
<!-- verifies-key: .github/workflows/branch-and-issue-check.yml:check-ceiling-ratchet -->
