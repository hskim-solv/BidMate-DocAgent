# 0086: active-loop lane Tool/Sandbox 정책 (safe core) — write-lane 샌드박스 단일 출처 + Claude write-lane fail-closed, read lane 불변

- Status: accepted
- Date: 2026-05-29
- Deciders: User, Claude Code as implementer
- Related: [ADR 0085](./0085-infinite-mode-active-auto-loop.md) (무한 모드 / unlimited caps), [ADR 0080](./0080-active-loop-registry-v2-dual-agent-lanes.md) (registry v2 / dual-agent lanes), [ADR 0082](./0082-dual-lane-adversarial-messages-api-adaptive-thinking.md) (dual-lane), [ADR 0066](./0066-codex-pr-adversarial-review.md) (trust contract = user CLI install + auth = explicit egress consent), [ADR 0061](./0061-external-and-paid-api-dependencies-allowed.md) (외부 API 데이터-경계 3조건), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) (private 데이터 경계), [ADR 0007](./0007-issue-linked-branch-naming.md)
- Issue: #1677

## Context

[ADR 0085](./0085-infinite-mode-active-auto-loop.md) 는 active-auto-loop 의 per-session
캡을 unlimited 기본으로 통일해 긴 자율 작업을 풀어줬다. 남은 병목은 **lane 별 TOOL /
SANDBOX 제약**이었다. 초안(Option C)은 두 가지를 함께 풀려 했다: (1) write lane 샌드박스를
단일 출처로 모으고, (2) Claude read/review lane 에 검증 러너(`make smoke`/`pytest`/
`bash scripts/test.sh`)를 allowlist 해 reviewer 가 verify-by-execution 하게 한다.

Codex adversarial review 가 (2)를 **unsafe** 로 판정했다: 이 검증 명령들은 **tracked 공유
상태**(`data/index`, `outputs/answer.json`)를 쓴다. review lane 이 공유 worktree 에서
이들을 돌리면 worktree 를 더럽히고 동시에 도는 implementer 와 race 한다. 또한 review 는
**Claude write lane 이 codex 의 OS 샌드박스를 강제할 수 없다**는 별도 결함도 지적했다
(`scripts/agent_loop.py` patch dispatch): write 경로의 Claude lane 은 bypass-style 권한으로
돌아, 기본 `workspace-write` 에서도 광고된 no-egress / no-out-of-scratch 정책보다 넓게
(조용히) 돌면서 state 는 `workspace-write` 로 보고한다.

유지보수자는 **safe core 만** 지금 ship 하고 나머지는 follow-up 으로 미루기로 했다.

## Decision

- **(a) Write-lane 샌드박스 → 단일 출처 + 안전 기본.** patch/write lane 의 샌드박스를
  `DEFAULT_PATCH_SANDBOX` 단일 출처(env `ACTIVE_PATCH_SANDBOX`)로 모은다. 모든 patch/write
  사이트(`run_repair_apply` 의 `run_patch`, codex exec patch 호출, patch-mode state/event/
  render 보고 필드)가 이 상수를 읽는다 — 리터럴 산재 대신 단일 출처. **기본값은
  `workspace-write`**: lane 은 scratch worktree 편집 + 명령 실행(실제 코딩 작업)을 하되
  네트워크 egress 가 없어 scope/privacy gate 가 scratch diff 로 mutation 을 계속 관측하고
  **load-bearing ADR 0005 데이터 경계가 유지**된다. **`danger-full-access`(codex no-sandbox:
  네트워크·의존성 설치·임의 명령·scratch 밖 쓰기)는 `ACTIVE_PATCH_SANDBOX` 명시 per-run
  opt-in** — gate 의 mutation 관측성과 ADR 0005 경계를 완화하므로 기본이 아니라 opt-in 으로
  둔다 (ADR 0061 데이터-경계 조건).
- **(b) Claude write lane fail-closed (full-access opt-in 한정).** write 경로는 `write_agent`
  ∈ {codex, claude, auto} 를 지원하나, Claude Code CLI write lane 은 bypass-style 권한으로
  돌아 codex OS 샌드박스(`DEFAULT_PATCH_SANDBOX`)를 **강제할 수 없다**. patch 모드에서
  resolved write agent = `claude` 이고 `DEFAULT_PATCH_SANDBOX != danger-full-access` 면
  **fail-closed 로 차단**한다 (Claude write lane 미spawn, blocked verdict + 명시 메시지
  `CLAUDE_WRITE_LANE_REQUIRES_FULL_ACCESS_MESSAGE`). 운영자가 명시적으로 `danger-full-access`
  로 opt-in 했을 때만(어차피 OS 샌드박스를 기대하지 않는 상태) Claude write lane 이 허용된다.
  **codex write lane 동작은 변경 없음.**
- **(c) READ / review lane 은 불변 (read-only review).** claude·codex read/review lane 의
  allowlist 는 `Read`/`Grep`/`Glob` + git-read(`Bash(git diff:*)`/`Bash(git log:*)`/
  `Bash(git status:*)`)뿐이고, denylist 는 모든 mutation/ship(`Edit`/`Write`/`NotebookEdit`/
  `Bash(git push:*)`/`Bash(git commit:*)`/`Bash(git merge:*)`/`Bash(gh:*)`) + blanket
  `Bash(make:*)` 를 차단한다 (= main 의 read-only review lane 그대로). `active-codex-runner`
  read 경로 / `--sandbox` argparse 기본값은 `read-only` 로 유지한다. 샌드박스 validator
  집합 `{read-only, workspace-write, danger-full-access}` 는 그대로 유지한다.

**lease/gate write 분리 보존**: 오직 Implementer write-lane 만 (정책에 맞는 샌드박스로)
편집하고, 오직 orchestrator apply 단계만 commit 한다. review lane(claude/codex) 에는 git
commit/push/gh 도구가 없으므로 conservative gate 가 그대로 유지된다.

`scripts/agent_loop.py` 는 본 단계에서도 `LOAD_BEARING_PATHS` 에 올리지 않는다
([ADR 0080](./0080-active-loop-registry-v2-dual-agent-lanes.md)/[ADR 0085](./0085-infinite-mode-active-auto-loop.md)
의 결정 유지) — Tool/Sandbox 정책 자체는 retrieval/verifier/answer/eval 런타임을 건드리지
않으며, ship 실행은 여전히 기존 human-gated 경로가 담당한다.

## Consequences

- 자율 write lane(codex)이 기본 `workspace-write` 로 scratch 편집 + 명령 실행을 하되
  network egress 가 없어 ADR 0005 경계가 유지되고, 필요한 드문 작업만 `ACTIVE_PATCH_SANDBOX
  =danger-full-access` 로 opt-in 한다.
- Claude write lane 은 OS 샌드박스를 강제 못 하므로 full-access opt-in 없이는 fail-closed
  차단 — 광고된 정책보다 넓게 도는 silent over-privilege 가 막힌다.
- read/review lane 은 read-only 라 공유 worktree 를 더럽히지 않고 concurrent-lane race 가 없다.
- patch lane 샌드박스가 `DEFAULT_PATCH_SANDBOX` 단일 출처로 모여, 향후 재조임/override 가
  한 곳에서 가능하다.

## Deferred / follow-up

- **in-lane review verification (verify-by-execution) 은 보류.** review lane 이 직접
  `make smoke`/`pytest`/`bash scripts/test.sh` 를 돌려 검증하는 기능은 초안에 있었으나,
  이 검증 명령들이 **tracked 공유 상태**(`data/index`, `outputs/answer.json`)를 mutate 해
  공유 worktree 를 더럽히고 implementer 와 race 하므로 (Codex finding) 제외했다. 안전한
  in-lane 검증은 **output isolation**(검증 산출물을 mktemp 로 격리 + git-diff dirty check 로
  공유 worktree 무변경 보장)이 선행돼야 한다 — 본 ADR 범위 밖, 별도 follow-up PR 로 추적한다.

## Alternatives considered

- **초안 Option C = read lane 에 검증 러너 allowlist + Claude write lane 무조건 허용.**
  기각: 위 Deferred 참조(검증 명령이 tracked 공유 상태를 mutate → race) + Claude write lane
  이 OS 샌드박스를 강제 못 함.
- **모든 lane 을 write 로 (all-lanes-write).** 기각: review lane 까지 편집/commit 권한을
  주면 "오직 Implementer 가 write-lease, 오직 orchestrator 가 commit" 인 conservative gate 의
  read-write 분리가 깨지고, 여러 lane 이 같은 worktree 를 편집하면 충돌/비결정성이 생긴다.
- **Claude write lane 을 기본 `workspace-write` 에서도 허용.** 기각: Claude CLI write lane 은
  codex OS 샌드박스를 강제할 수 없어 광고된 no-egress 정책보다 넓게 (조용히) 돈다 → state 는
  `workspace-write` 라 보고하면서 실제는 더 넓은 silent over-privilege. full-access opt-in
  한정으로 둔다.

## Verification

```bash
python3 -m pytest -q tests/test_agent_loop.py -k 'patch_lane or patch_mode or claude_turn or claude_lane or claude_write'
python3 scripts/_governance.py --check-adr-readme-parity docs/adr/0086-lane-tool-sandbox-policy-option-c.md
git diff origin/main -- scripts/agent_loop_claude_turn.py   # empty (read lane reverted to main)
git diff --check
```

<!-- verifies-key: scripts/agent_loop.py:DEFAULT_PATCH_SANDBOX -->
<!-- verifies-key: scripts/agent_loop.py:_claude_write_lane_sandbox_blocker -->
<!-- verifies-key: scripts/agent_loop.py:CLAUDE_WRITE_LANE_REQUIRES_FULL_ACCESS_MESSAGE -->
<!-- verifies-key: docs/operations/active-agent-loop.md:Tool/Sandbox Policy -->
