# 0089: pre-commit Codex adversarial review — infra 실패는 비차단 (amends 0066)

- **Status**: proposed
- **Date**: 2026-05-31
- **Amends**: [0066](./0066-codex-pr-adversarial-review.md) (local Codex adversarial pre-commit review)
- **Related**: [0086](./0086-lane-tool-sandbox-policy-option-c.md) (lane sandbox), [scripts/run_codex_adversarial_precommit.py](../../scripts/run_codex_adversarial_precommit.py)

## TL;DR

- load-bearing 변경의 pre-commit Codex adversarial review가 codex의 **실행 실패(infra)**와 **실제 적대적 verdict**를 구분 못 하고 둘 다 커밋을 hard-block 했다.
- **infra 실패**(auth/refresh-token race, network, timeout, 파싱 불가, companion 부재 = verdict 못 얻음)는 이제 **WARN + 커밋 허용** — 적대 리뷰는 CI/pre-push에 위임.
- **실제 non-approve verdict**(codex가 정상 실행되어 이슈 발견)만 차단 유지.
- **phase는 pre-commit 유지** (pre-push 이동은 검토했으나 비차단화로 핵심 고통 해소 → 보류).

## Context

ADR 0066은 load-bearing staged 변경에 대해 로컬 Codex adversarial review를 pre-commit에서 실행한다. `scripts/run_codex_adversarial_precommit.py`는 codex companion(node)을 호출하고 `proc.returncode != 0`이면 무조건 "failed to run" → `return 1`로 커밋을 차단했다.

실측 인시던트(#1688 작업 중): 멀티 worktree 동시 codex 호출이 단일-사용 ChatGPT refresh token을 race 하여 `parseError: "Your access token could not be refreshed because your refresh token was already used"` 발생. codex는 verdict를 내지 못했고(result=None), 스크립트는 이를 "리뷰가 이슈 발견"과 동일하게 취급해 **모든 load-bearing 커밋을 차단**. 운영자는 `--no-verify` 강제 + 부수적으로 worktree index 복구까지 필요했다. 즉 **외부 CLI 인증 상태에 fail-closed로 결합**된 것이 문제다 — 리뷰 신호가 아니라 인프라 신호에 커밋이 막혔다.

## Decision

`run_precommit_review`에서 **infra 실패와 review verdict를 분리**한다:

- `infra_failure = (proc.returncode != 0) or (verdict == "error")` — companion/codex가 정상 verdict를 못 낸 모든 경우(인증 race, network, timeout rc=124, 파싱 불가). `_payload_verdict`가 parseError/result 부재를 이미 `"error"`로 매핑하므로 이 한 줄이 모든 infra 케이스를 덮는다.
- infra 실패 → **WARN + 비차단**(다음 attempt 시도, 전 attempt가 infra면 `return 0` + "deferred to CI/pre-push" 경고). 커밋 허용.
- `rc == 0` + 실제 verdict:
  - `approve` → 통과.
  - non-approve → **차단(`return 1`)** (ADR 0066 핵심 보존).
- `main()`의 companion 미해석(codex 미설치)도 동일하게 비차단(WARN + `return 0`).
- **phase는 pre-commit 유지.** 적대 리뷰의 *권위*는 CI(PR gate)가 계속 담당하고, 로컬 pre-commit은 빠른 피드백 + 비차단 1차 신호.

## Consequences

**Wins**
- codex 인증 lapse / 동시성 race가 더 이상 load-bearing 커밋을 차단하지 않는다(`--no-verify` 강제 제거).
- 실제 적대적 발견(non-approve verdict)은 그대로 차단 — 리뷰 가치 보존.
- 인프라 결함(infra)과 콘텐츠 결함(verdict)이 로그·동작에서 명확히 구분된다.

**Costs / Trade-offs**
- infra 실패 시 그 커밋은 로컬 적대 리뷰를 건너뛴다 — **CI/pre-push가 backstop**(적대 리뷰의 권위는 원래 CI). 일시적 infra 창에서 일부 커밋이 로컬 리뷰 없이 진행될 수 있으나, 푸시 전 CI가 잡는다.
- "조용한 skip"을 막기 위해 모든 infra 비차단은 WARN을 stderr로 남긴다(no silent cap).

## Alternatives considered

- **pre-push로 이동.** 검토함 — push당 1회 실행(비용↓), 실패가 commit 아닌 push만 차단. 그러나 비차단화 fix 하나가 핵심 고통(헛차단)을 phase 무관하게 해소하고, pre-push 이동은 훅 재배선 + scope 변경(staged→`origin/main..HEAD`) 비용이 있어 ROI 낮음. (초기에 "pre-commit이 index를 손상시킨다"는 논거가 있었으나 재현 실패로 **철회** — index 손상은 codex 훅 탓이라는 증거 없음.) → 보류.
- **hard-block 유지 + codex auth race 근본 수정.** Reject: auth race는 환경적·반복적이라 커밋 게이트를 그것에 hard-couple하는 것이 brittle. 근본 수정(토큰 직렬화/upstream)은 별도 작업이며 게이트 결합과 무관해야 한다.

## Verification

<!-- verifies-key: scripts/run_codex_adversarial_precommit.py:infra_failure -->

- 위 marker: `run_precommit_review`의 `infra_failure` 분기가 infra 실패를 verdict와 분리함을 lint가 확인.
- 회귀 테스트(`tests/test_codex_adversarial_precommit.py`):
  - `test_run_precommit_review_nonblocking_on_auth_parse_error` — refresh-token parseError(인시던트 재현) → `rc == 0`.
  - `test_run_precommit_review_nonblocking_on_companion_failure` — rc=127 → `rc == 0`.
  - `test_run_precommit_review_nonblocking_on_timeout` — timeout → `rc == 0`.
  - `test_run_precommit_review_blocks_on_needs_attention` — 실제 non-approve verdict → `rc == 1` (차단 보존).
