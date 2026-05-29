# 0085: `make 시작` 무한 모드 + active-auto-loop 안전 가드 + 두 레이어 기본값 통일

- Status: accepted
- Date: 2026-05-29
- Deciders: User, Claude Code as implementer
- Related: [ADR 0080](./0080-active-loop-registry-v2-dual-agent-lanes.md) (registry v2 / dual-agent lanes), [ADR 0083](./0083-local-gate-completion-and-real100-v2-judge-egress.md) (`make 시작` local-gate completion), [ADR 0082](./0082-dual-lane-adversarial-messages-api-adaptive-thinking.md) (dual-lane), [ADR 0007](./0007-issue-linked-branch-naming.md)
- Issue: #1675

## Context

[ADR 0083](./0083-local-gate-completion-and-real100-v2-judge-egress.md) 는 `make 시작`
을 기본 ship 없이 도는 **bounded** 5-task wave 로 고정했다. 운영자가 원하는 다음
단계는 "ready task 큐가 빌 때까지 도는 무한 모드" 이지만, 현재 `active-auto-loop`
의 종료 조건은 세 곳에 분산된 정수 상한이다.

1. `START_TASK_LIMIT`(완료 목표 5) / `ACTIVE_AUTO_LOOP_MAX_ITERATIONS`(5) /
   `START_TASK_ATTEMPT_LIMIT`(attempt 상한 15) 가 모두 양의 정수만 받는다
   (`--max-iterations must be at least 1`). 무한을 표현할 sentinel 이 없다.
2. **두 레이어 기본값 불일치** 가 함정이다. Makefile front door 와
   `scripts/agent_loop.py` argparse 기본값이 갈려 있어, 직접 CLI 호출과
   `make 시작` 이 다르게 동작했다 — 특히 per-session 명령 카운트 캡이 한쪽은
   유한값, 다른 쪽은 `0` 으로 어긋나 있었다.
3. **Claude write lane 900s 강제 타임아웃**: `ACTIVE_CODEX_TIMEOUT_SECONDS=0`(무제한)
   이어도 Claude write lane 은 `timeout_seconds or 900` 으로 900s 를 대입해, 긴 write
   turn 을 무한 모드 중에 조용히 죽였다.
4. **codex `login status` 무타임아웃**: ChatGPT auth guard 의 `codex login status`
   호출에 타임아웃이 없어, 행(hang) 시 루프 전체가 멈출 수 있다.
5. 무한 모드는 종료 상한이 없어지므로, 폭주를 막을 **안전 가드** 가 필요하다 —
   연속 blocker 누적, wall-clock 상한, 동일 task 재시도 방지.

bounded 동작([ADR 0083](./0083-local-gate-completion-and-real100-v2-judge-egress.md))은
운영자 기본값이므로 불변이어야 한다. 무한 모드는 그 위에 얹는 **opt-in** 이다.

## Decision

`--max-iterations 0`(또는 문자열 `infinite`/`unlimited`)를 "ready 큐가 빌 때까지
도는 무한 모드" sentinel 로 도입한다. Makefile 은 `START_INFINITE=1` 로 노출한다.

- **종료 조건**: 무한 모드는 iteration count / completed-target 상한을 버리고,
  **ready-queue 소진** + 아래 안전 가드만으로 종료한다. drained ready queue(다음
  task 없음)는 정상 종료이며 blocker 가 아니다. explicit `--target-completed-count`
  가 주어지면 그때만 target bound 가 살아난다.
- **안전 가드** (env override 가능, 무한 모드 한정):
  - `BIDMATE_AGENT_LOOP_MAX_CONSECUTIVE_BLOCKERS`(기본 3): 연속 blocked task 가
    이 수에 도달하면 중단. 완료가 한 번이라도 끼면 streak 은 0 으로 리셋되므로,
    진행과 섞인 산발적 실패로는 중단되지 않는다. **실패한 auto-repair deferral 도
    이 가드에 집계**된다 (그렇지 않으면 기본 auto-repair 경로의 반복 수리 실패가
    가드를 우회한다).
  - `BIDMATE_AGENT_LOOP_MAX_WALL_CLOCK_SECONDS`(기본 0 = 비활성): wall-clock
    상한 opt-in 이며, **per-session 캡이 모두 무제한(0)인 no-caps 기본 위에 얹는
    단일 hang backstop** 이다. **설정 시 남은 예산을 codex runner subprocess timeout
    (`proc.wait`) **과** Claude read/review lane subprocess timeout
    (`agent_loop_claude_turn.run_turn` → `subprocess.run(..., timeout=...)`) 양쪽으로
    전달**해 어느 lane 에서 hang 이 나도 끊는다 — wall-clock 검사는 cycle 사이에서만
    돌아 blocking subprocess wait 를 직접 중단하지 못하기 때문이다. 미설정(0, 기본)
    이면 `--timeout-seconds`(0=무제한, per-session 캡도 0=무제한)가 적용되는 truly
    unlimited no-caps 기본이고, codex/Claude lane 양쪽 모두 timeout 이 걸리지 않는다.
  - **동일 task 재시도 방지**: blocked task 는 `deferred_task_ids` 로 ledger 에
    기록되어 이번 run 의 fresh selection 에서 제외된다.
  - 비정상(정수 아님/음수) env 값은 무시하고 default 로 폴백한다(경고 기록) —
    오타가 큐를 좌초시키지 않는다.
- **가드 abort = blocked**: 안전 가드(연속 blocker / wall-clock) 로 중단하면 run
  decision 은 `blocked` 이다. 가드 트립은 `limit-reached`(성공) 가 아니다. wall-clock
  은 `wall_clock_exceeded` 기계 판독 플래그도 남긴다.
- **두 레이어 통일**: `active-auto-loop` argparse 기본값을 Makefile front door(SSoT)에
  맞춘다 — `--timeout-seconds 0`(무제한), `--max-commands-per-session 0`(무제한; 운영
  front door 의 per-session 명령 카운트 캡 폐지 — 루프는 timeout + attempt/queue +
  연속-blocker/wall-clock 가드로 bound), `--read-agent/--write-agent auto`. 양수 값을
  주면 캡을 다시 건다.
- **Claude write 타임아웃**: `0`(env 또는 `--timeout-seconds`)을 *무제한*(`None`)으로
  해석해 codex lane 의 `timeout_seconds or None` 계약과 맞춘다. 900s 대입을 제거한다.
- **codex auth probe 타임아웃**: `codex login status` 에 30s 타임아웃을 두고,
  초과 시 fail-closed 로 처리한다.

`quota_cap`/`workload_cap`(auto 모드의 시도 축소)은 무한 모드에서 `auto` 해석
경로 자체를 타지 않으므로(early return) 구조상 비활성이다.

`scripts/agent_loop.py` 는 본 단계에서도 `LOAD_BEARING_PATHS` 에 올리지 않는다
([ADR 0080](./0080-active-loop-registry-v2-dual-agent-lanes.md) 의 결정 유지) — 무한
모드 자체는 retrieval/verifier/answer/eval 런타임을 건드리지 않으며, ship 실행은
여전히 기존 human-gated 경로가 담당한다(`make 시작` 기본 `EXECUTE_SHIP=0`).

## Consequences

- `make 시작 START_INFINITE=1` 은 ready 큐가 빌 때까지 wave 를 돌리고, 가드 또는
  큐 소진으로 종료한다. `make 시작`(기본)의 bounded 5-task 동작은 불변이다.
- 직접 `python3 scripts/agent_loop.py active-auto-loop` 호출이 `make 시작` 과 동일하게
  동작한다(두 레이어 기본값 통일).
- 긴 Claude write turn 이 900s 에 죽지 않는다. codex auth 행이 루프를 멈추지 않는다.
- 가드 abort 가 `blocked` 로 정직하게 보고된다(성공 위장 제거).
- 무한 모드 도입은 종료 상한 제거를 동반하므로, 안전 가드 3종(연속 blocker /
  wall-clock / 동일 task 재시도 방지)이 폭주 backstop 으로 계약화된다.

## Alternatives considered

- **음수 `--max-iterations` 를 무한으로.** 기각: `0`/`infinite`/`unlimited` 가 의도가
  명확하고, 음수는 여전히 입력 오류로 거부해야 한다.
- **무한 모드 종료를 wall-clock 단일 상한으로.** 기각: wall-clock 만으로는 폭주하는
  blocker 루프를 일찍 못 끊는다. 연속-blocker 가드가 더 빠른 backstop 이고, wall-clock
  은 opt-in 보조다.
- **두 레이어 통일 대신 Makefile 만 SSoT 로 두고 argparse 는 방치.** 기각: 직접 CLI
  호출(테스트·디버그 경로)이 다르게 동작하는 함정을 남긴다.
- **Claude write 900s 유지.** 기각: 무한 모드의 긴 write turn 을 죽이는 것이 본 ADR
  이 푸는 문제의 일부다.

## Verification

```bash
python3 -m pytest -q tests/test_agent_loop.py -k 'infinite or resolve_auto_loop or claude_write_timeout or codex_auth_check or parser_defaults'
python3 scripts/_governance.py --check-adr-readme-parity docs/adr/0085-infinite-mode-active-auto-loop.md
git diff --check
```

<!-- verifies-key: scripts/agent_loop.py:INFINITE_MAX_ITERATIONS -->
<!-- verifies-key: scripts/agent_loop.py:_resolve_infinite_guard_int -->
<!-- verifies-key: scripts/agent_loop.py:_resolve_claude_write_timeout -->
<!-- verifies-key: Makefile:START_INFINITE -->
<!-- verifies-key: docs/operations/active-agent-loop.md:Infinite Mode -->
