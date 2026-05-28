# ADR 0066 — Local Codex adversarial pre-commit review loop

- **Status**: Proposed
- **Date**: 2026-05-21
- **Related**: [0007](./0007-issue-linked-branch-naming.md) (issue-first 컨벤션), [0047](./0047-solo-author-adr-governance.md) (30일 SLA), [0061](./0061-external-and-paid-api-dependencies-allowed.md) (외부 API 3조건); issue #1126

## Context

PR 리뷰 시 `/codex:adversarial-review` 슬래시 명령을 수동 호출해 외부 LLM(Codex)의 challenge framing으로 설계 가정·구현 선택을 흔드는 패턴이 자리잡았다. ADR 0066의 초기 형태는 이를 PR-time GitHub Actions workflow로 자동화했다.

그러나 PR open/synchronize마다 self-hosted Codex review가 반복되면 load-bearing 변경 PR에서 새 finding이 push마다 계속 생성된다. 특히 canonical contract 변경처럼 구현과 검증을 함께 조정하는 PR에서는 review가 CI 상태판의 일부가 되어, 실제 blocker와 모델의 후속 선호가 섞인다.

이 표면은 여전히 유용하지만, 실행 위치는 CI가 아니라 commit 전 로컬 반복 점검이 더 적합하다. 작성자는 staged diff를 고친 뒤 다시 commit을 시도할 수 있고, PR CI는 deterministic gate와 public fixture smoke에 집중한다.

## Decision

1. **`.github/workflows/codex-adversarial-review.yml` PR-time workflow를 제거한다.** Codex adversarial review는 더 이상 PR comment나 GitHub Check run을 만들지 않는다.
2. **`.githooks/pre-commit`이 load-bearing staged 변경에 한해 local Codex adversarial review를 실행한다.** 트리거 SSoT는 `scripts/_governance.py LOAD_BEARING_PATHS`이며, private eval path guard(ADR 0005)가 먼저 실행된다.
3. **review 대상은 staged diff다.** `scripts/run_codex_adversarial_precommit.py`는 Codex prompt에 `git diff --cached` / `git diff --cached --name-only`를 사용하라고 명시하고, staged file list와 load-bearing hit를 focus로 전달한다.
4. **기본 반복 횟수는 2회이며, 모든 attempt가 `approve`여야 commit을 통과한다.** `BIDMATE_CODEX_ADVERSARIAL_ATTEMPTS=<n>`으로 조정할 수 있다. 각 attempt는 기본 900초 timeout(`BIDMATE_CODEX_ADVERSARIAL_TIMEOUT_SEC=<n>`)을 갖고, `needs-attention`, parse error, companion 실행 실패, timeout은 commit을 block한다.
5. **artifact는 local-only다.** 각 attempt의 JSON/stderr/rendered markdown은 `git rev-parse --git-dir` 기준 `codex-adversarial-precommit/` 아래에 남기며 commit되지 않는다. emergency bypass는 기존 Git hook 경로와 같이 `git commit --no-verify` 또는 `BIDMATE_SKIP_CODEX_ADVERSARIAL_PRECOMMIT=1`로 가능하다.
6. **기존 수동 `/codex:adversarial-review`와 active-loop Codex lane은 유지한다.** 본 ADR은 PR-time CI surface만 local pre-commit loop로 이동한다.

## Consequences

- **CI noise 감소**: PR synchronize마다 새 adversarial review가 달리지 않으므로 deterministic CI와 LLM critique가 섞이지 않는다.
- **shift-left 유지**: load-bearing 변경자는 commit 전에 Codex challenge를 받는다. 문제를 고친 뒤 commit을 다시 시도하는 local loop가 된다.
- **commit latency 증가**: load-bearing staged 변경 commit은 기본 2회 Codex 호출 비용을 치른다. 각 attempt는 900초에서 timeout되며, 필요 시 attempt 수/timeout을 낮추거나 emergency bypass를 명시적으로 사용한다.
- **로컬 Codex 환경 의존**: Claude Codex plugin cache 또는 `CODEX_COMPANION`이 필요하다. 미설치 환경에서는 load-bearing commit이 block된다.
- **PR comment evidence 제거**: reviewer-facing artifact는 PR comment/check가 아니라 local hook stderr와 git-dir 내부 `codex-adversarial-precommit/` artifact다. PR 본문에는 필요한 finding만 사람이 요약한다.
- **비공개 데이터 경계 유지**: pre-commit은 ADR 0005 path block 이후에 Codex를 호출한다. private staged file이 있으면 Codex 호출 전에 hook이 중단된다.

## Alternatives considered

- **PR-time workflow 유지**: 호출 누락은 줄지만, push마다 모델 finding이 새로 생기며 CI 상태판이 불안정해진다. 이번 전환의 직접 반례라 기각.
- **Merge gate화**: `needs-attention`을 CI failure로 만들면 오탐이 머지를 막는다. LLM critique는 deterministic CI gate가 아니라 local authoring guard가 맞다.
- **수동 slash command만 유지**: 호출 누락 문제가 재발한다. load-bearing staged 변경에 대해서는 hook이 자동 호출한다.
- **한 번만 실행**: 비용은 낮지만 stochastic reviewer 한 번에 의존한다. 기본 2회 approve를 요구해 과도한 PR-time 반복 없이 최소 반복성을 확보한다.

## Verification

<!-- verifies-key: .githooks/pre-commit:run_codex_adversarial_precommit.py -->
<!-- verifies-key: scripts/run_codex_adversarial_precommit.py:def main -->
<!-- verifies-key: tests/test_codex_adversarial_precommit.py:test_run_precommit_review_requires_every_attempt_to_approve -->

- Hook wiring: `.githooks/pre-commit`이 staged load-bearing hit를 `scripts/_governance.py --any-match`로 찾은 뒤 `scripts/run_codex_adversarial_precommit.py`를 호출한다.
- Local runner: `scripts/run_codex_adversarial_precommit.py`는 staged file list를 focus에 포함하고, attempt별 artifact를 git-dir 내부 `codex-adversarial-precommit/`에 쓴다.
- Regression tests: `tests/test_codex_adversarial_precommit.py`가 load-bearing reuse, staged diff focus, all-attempts approve requirement, needs-attention block, companion failure block을 검증한다.
