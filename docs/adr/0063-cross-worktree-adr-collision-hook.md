# 0063: Cross-worktree ADR 번호 충돌 PreToolUse 훅

- **Status**: accepted
- **Date**: 2026-05-20
- **Deciders**: hskim
- **Related**: [ADR 0007](./0007-issue-linked-branch-naming.md) (governance gates as CI checks), [ADR 0047](./0047-solo-author-adr-governance.md) (solo-author ADR lifecycle), issue [#1069](https://github.com/hskim-solv/BidMate-DocAgent/issues/1069)

## Context

ADR 번호 충돌은 두 worktree/세션이 동시에 ADR 을 작성할 때마다 재발한다: 0022→0023, 0023→0025, 0029→0030 각각이 머지 시점 renumber (파일 + 본문 heading + cross-ref + README 인덱스 행) 를 강제했다.

기존 가드 — [`.githooks/pre-commit`](../../.githooks/pre-commit) 가 실행하는 `scripts/_governance.py --check-adr-collision` — 은 **의도적으로 filesystem-only** (오프라인 안전, `gh` 없음) 다. 다른 branch/worktree 의 open PR 이 이미 예약한 번호는 볼 수 없다. CLAUDE.md 는 작성 전 수동 `gh pr list --search "ADR" --state open` 을 요구하지만, 그 수동 단계가 바로 계속 건너뛰어지는 단계다.

## Decision

PreToolUse 훅 [`scripts/claude-hooks/pretooluse-adr-collision.sh`](../../scripts/claude-hooks/pretooluse-adr-collision.sh) (matcher `Edit|MultiEdit|Write`) 추가 — *새로운* `docs/adr/<NNNN>-*.md` Write 시점에 open PR 을 조회하고, `<NNNN>` 가 다른 PR 의 title 또는 head branch 에 이미 예약돼 있으면 거부 (exit 2) 한다.

- **Cross-worktree 한정**: 로컬 동일 번호 충돌은 pre-commit 의 몫으로 유지 — single responsibility, SSoT 중복 없음.
- **번호 출처**: PR `title` + `headRefName`, zero-pad 무관 (`ADR 0063`, `ADR-63`, `adr#63`, `…-adr-0063-…` 모두 63 으로 해석). PR body 는 무시 — body 는 *다른* ADR 을 상시 인용 ("supersedes number 0012") 하므로 false positive 를 양산한다. 매치는 로컬에서 정확한 정수로 재필터되므로 느슨한 `--search "ADR in:title"` 도 절대 over-block 할 수 없다.
- **Fail-open**: gh 부재 / 네트워크 실패 / 토큰 누락 / 빈 리스트 / 파싱 실패 모두 → exit 0. pre-commit 이 머지 시점 backstop 으로 남는다. 명시적으로 이름 붙은 충돌만 차단한다.
- **Early-exit**: non-Write / non-ADR-filename / existing-file 게이트가 어떤 `gh` 호출보다 먼저 실행되므로, 네트워크는 진짜 new-ADR Write (주당 몇 회) 에서만 건드려지고, 가능한 곳에서는 `timeout 8` 로 제한된다.

## Consequences

- 수동 `gh pr list` 규율이 write 시점에 자동화된다; 반복되던 머지 시점 renumber 비용이 머지 후가 아니라 draft commit 전에 잡힌다.
- 신규 blocking governance surface (exit 2) 가 기존 PreToolUse 훅 3개에 합류한다. 모든 인프라 모호성에서 fail-open 으로 완화됨 — 차단되는 유일한 경우는 구체적인 cross-worktree 충돌이며, 충돌 PR 번호 + renumber 교정안이 함께 출력된다.
- **이 ADR 자체가 자신이 방지하는 충돌에 걸렸다.** `--next-adr-number` 가 처음 0060 을 반환했고, `gh pr list` 는 0061 만 예약됨 (PR #1061) 으로 표시했다. branch 작업 도중 ADR 0060 (`outcome-telemetry`, issue #1039) 이 다른 worktree 에서 머지됨 — 이 훅이 막는 바로 그 cross-worktree race 다. 재확인 시 0061 (이제 머지로 filesystem 점유) 과 open PR #1061 (0061), #1073 (0062) 가 나와, 이 ADR 은 0063 에 안착했다. 이 세션에서 훅이 활성화돼 있었다면 첫 0060 Write 를 차단했을 것이다.

## Alternatives considered

- **`pretooluse-adr-template.sh` 확장**: 기각 — 불안정한 네트워크 호출을 결정론적 오프라인 template 체크에 결합하고, 서로 반대 fail-policy 를 원하는 두 체크 (template 은 fail-closed, collision 은 fail-open) 에 하나의 정책을 강제하게 된다.
- **pre-commit 가 open PR 을 조회하게 함**: 기각 — `_governance.py` 의 충돌 체크는 의도적으로 오프라인 안전하다; 거기에 `gh` 를 추가하면 그 계약이 깨지고 여전히 draft 가 완전히 작성된 후에만 발화한다.
- **Warn-only (exit 0)**: 기각 — 스크롤되는 경고는 이 작업을 촉발한 "수동 단계 건너뜀" 실패를 그대로 재현한다. 차단 정밀도가 높고 (open PR 의 title/branch 에 대한 정확한 정수 매치), 모든 모호성은 이미 fail-open 이다.

## Verification

<!-- verifies-key: scripts/claude-hooks/pretooluse-adr-collision.sh:adr-collision -->
<!-- verifies-key: tests/test_hook_pretooluse_adr_collision.py:test_collision_via_pr_title_blocks -->
<!-- verifies-key: .claude/settings.json:pretooluse-adr-collision.sh -->
