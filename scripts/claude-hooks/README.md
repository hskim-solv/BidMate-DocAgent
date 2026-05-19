# scripts/claude-hooks/

Claude Code 의 PreToolUse / Stop / UserPromptSubmit 훅 모음. `.claude/settings.json` 의 `hooks` 섹션에서 각 스크립트가 어떤 matcher (e.g. `Edit|MultiEdit|Write`, `Bash`, `.*`) 로 trigger 되는지 정의.

거버넌스 비판 보고서 (2026-05-19, issue #1033) 후속: 각 hook 의 실제 강제력이 자유 표현으로 흩어져 있던 것을 5개 표준 라벨로 통일.

## Enforcement 분류

| 라벨 | 의미 | 정확한 효과 |
|---|---|---|
| **block** | tool 호출 거부 | exit 2 + stderr 사유. Claude 가 해당 도구 사용 못 함 |
| **awareness** | 도구 사용은 허용, 인식만 | exit 0 + stderr 경고. Claude 가 메시지 보고 결정 가능 |
| **nudge** | 다음 턴 context 에 힌트 주입 | exit 0 + stdout. UserPromptSubmit 전용 |
| **graduated** | 임계값 따라 awareness → block 단계 상승 | 동일 hook 내 2-stage 분기 |
| **pipeline** | Stop-hook 시점의 외부 명령 orchestration | tool 호출 gate 아님; 실패 시 disarm + stderr |

**왜 이 분류?** Q2-2026 self-review 의 거버넌스 ROI 측정이 `aware` 와 `blocked` 를 구분 못 하던 문제 (`.hook-fires.log` 57/58 줄이 `aware|*`, 0줄이 `blocked|*`) — PR4 의 outcome telemetry 가 정확한 outcome 카테고리를 emit 하려면 각 hook 의 의도된 강제력이 명시되어야 함.

## 현재 hook 인벤토리

| Hook | Enforcement | Matcher | 주 기능 |
|---|---|---|---|
| [`plan-slug-race.sh`](./plan-slug-race.sh) | block | `Write` | `~/.claude/plans/<slug>.md` 5-min 내 cross-worktree race 차단 (issue #779) |
| [`pretooluse-adr-template.sh`](./pretooluse-adr-template.sh) | block | `Edit\|MultiEdit\|Write` | 신규 ADR 의 Verification section + verifies-key marker 누락 차단 (issue #826/#866) |
| [`pretooluse-bash-guard.sh`](./pretooluse-bash-guard.sh) | block | `Bash` | (1) stacked-dependent 있을 때 `gh pr merge --delete-branch` 차단, (2) `gh pr create` 시 stacked-base mismatch 차단 (PR #423→#431, #470 incident) |
| [`pretooluse-loadbearing.sh`](./pretooluse-loadbearing.sh) | awareness | `Edit\|MultiEdit\|Write` | load-bearing 파일 편집 시 ADR / PR §5b 영향 환기 (CLAUDE.md) |
| [`pretooluse-memory-lines.sh`](./pretooluse-memory-lines.sh) | graduated | `Edit\|MultiEdit\|Write` | MEMORY.md 라인 수 ≥AWARE 경고 / ≥BLOCK 차단 (issue #720) |
| [`stop-ship.sh`](./stop-ship.sh) | pipeline | Stop | armed 상태일 때 commit→push→PR→CI→squash-merge 5-stage 자동 실행 (auto-ship) |
| [`userpromptsubmit-delegation-gate.sh`](./userpromptsubmit-delegation-gate.sh) | nudge | UserPromptSubmit `.*` | non-trivial 변경 키워드 감지 시 Plan/Explore 위임 힌트 주입 (issue #1014) |

## 새 hook 추가 시

1. 헤더 docstring 둘째 줄에 **`# Enforcement: <label>`** 1줄 + **`# Classification rationale: <한 문장>`** 1줄 추가.
2. 위 인벤토리 표에 row 추가 (matcher + 1줄 설명 + 관련 issue/PR).
3. `.claude/settings.json` 의 hooks 섹션에 등록.
4. (PR4 outcome telemetry 머지 후) `.claude/.hook-fires.log` 에 emit 하는 outcome 카테고리가 위 enforcement 와 일치하는지 회귀 테스트로 확인.

## Supporting helpers (hook 아님)

다음 파일은 hook 자체가 아닌 hook/CLI 가 import 하는 helper 모듈. enforcement 라벨 부여 대상 아님:

- `_self_review.py` — `make hook-fires-weekly` + `/self-review-quarterly` 의 raw signal collector
- `_ship_arm.py` — `make ship-arm` 의 arm-file 생성 로직
- `_ship_lock_check.py` — ship 표면 lock 검사 (PR6 후 본격 활용 예정)
- `_ship_pr_body.py` — stop-ship 의 PR body 빌드 헬퍼

## Telemetry 포맷

현재 `.hook-fires.log` 포맷이 hook 마다 다름 (3-field `<ts>|<category>|<path>` vs 4-field `<ts>|<action>|<reason>|<path>`). PR4 (outcome telemetry, issue 별도) 에서 통일 예정. PR4 이전에는 hook 별 docstring 의 telemetry 섹션 참조.

## 우회 정책

- `--no-verify` (git): pre-commit/pre-push 만. PreToolUse/Stop hook 은 영향 없음.
- `claude --dangerously-skip-permissions`: PreToolUse 전체 skip. **위험 — 사용자 명시 의도일 때만.**
- 개별 hook 우회: hook 코드 안의 환경 변수 (e.g. `PLAN_SLUG_RACE_THRESHOLD`, `MEMORY_AWARE_OVERRIDE`) — 각 hook docstring 참조.
