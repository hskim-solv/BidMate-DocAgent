# ADR 0060 — Outcome telemetry as governance measurement surface

- Status: Proposed
- Date: 2026-05-19
- Authors: Hyunsoo Kim
- Related: ADR 0007 (issue-first + branch convention), ADR 0030 (leaderboard surface), CLAUDE.md "거버넌스 ROI" + Q2-2026 self-review 5축 #3
- Issue: #1039
- Augments: governance critique 2026-05-19 (plan file `parsed-rolling-liskov-governance.md`) 메타 발견 + 약점 #1·#4·#7·#8 동시 해소

## Context

거버넌스 표면 (`.githooks/`, `scripts/claude-hooks/` 8 hook, CI workflows, ship surfaces, PR template) 이 3+ 개월간 unbounded 하게 grow. 그러나 **자기 효과성을 평가하지 못한다**:

- `.claude/.hook-fires.log` 58줄 직접 확인: 57줄 `aware|load-bearing|...`, 1줄 `ok|memory-lines|...`, **0줄 `blocked|*`**. 강제력 있는 hook (bash-guard, adr-template, plan-slug-race, memory-lines BLOCK) 의 block 이벤트가 telemetry 자체에 부재.
- `scripts/claude-hooks/pretooluse-bash-guard.sh:131-133` 은 이미 5-field `blocked|gh-pr-create-stacked|...` 포맷을 emit 하지만, 2024-06-06 deploy 이후 fire 한 적 0번 → "훅이 사고를 막았다" 검증 불가.
- `scripts/_self_review.py` 가 emit 하는 5축 #3 raw signal 은 fire count + memory line 같은 **input metric**. **outcome metric** (실제 block 횟수, bypass 횟수, false-positive 횟수, friction latency) 미수집.
- 귀결: Q2-2026 self-review 5축 #3 △→✓ 회복은 **ADR 0038 / PR #449 / PR #177 추가** 라는 input 으로 받음. 기존 거버넌스가 사고를 막았다는 outcome 데이터 부재. ADR 0041/0042/0043 가 만들어낸 Decision Theatre 와 동일 패턴이 거버넌스 평가 자체에 적용됨.

`scripts/_governance.py:175-204` 의 ADR Verification lint 가 ADR 약속에 verifies-key 마커를 강제하지만, 거버넌스 평가에는 같은 회로 부재 — 본 ADR 이 그 회로.

## Decision

1. **`.claude/.hook-fires.log` 5-field+ 표준 포맷 확립** — `pretooluse-bash-guard.sh:131` 이 이미 사용하는 포맷을 canonical 로 promote:
   ```
   <ts>|<outcome>|<hook>|<category>|<path>[|<extra>]
   ```
   - `outcome` ∈ {aware, blocked, bypassed, false_positive, false_negative, nudged, pipeline_start, pipeline_end, ok}
   - `hook` ∈ {bash-guard, loadbearing, memory-lines, adr-template, plan-slug-race, delegation-gate, stop-ship} (SSoT: `scripts/claude-hooks/README.md`)
   - `category`: hook-internal sub-classification (예: memory-lines 의 aware vs block sub-level)
   - `path`: 영향 받은 파일/브랜치 (옵션)
   - `extra`: 자유 메타데이터 (옵션, e.g. `on=other-branch`)

2. **`scripts/_governance.py` 에 emit_hook_fire() Python 헬퍼 + `--emit-fire` CLI subcommand** — bash + Python hook 양쪽이 호출. 표준 포맷 한 곳에서 보장.
   ```python
   def emit_hook_fire(outcome: str, hook: str, category: str = "",
                      path: str = "", extra: str = "") -> None: ...
   ```
   ```bash
   python3 scripts/_governance.py --emit-fire \
     --outcome blocked --hook bash-guard --category gh-pr-create-stacked \
     --path "$current_branch" --extra "on=$stacked_on" 2>/dev/null || true
   ```
   `outcome` 가 `KNOWN_OUTCOMES` 미포함이면 raise (typo guard).

3. **5 hook 의 emit 코드 통일** (PR4 본체):
   - `pretooluse-loadbearing.sh`: 3-field → `--outcome aware --hook loadbearing --category file-edit --path <p>`
   - `pretooluse-memory-lines.sh`: 4-field → `--outcome ok|aware|blocked --hook memory-lines --category <line-count-bin>` + `--path <p>`
   - `userpromptsubmit-delegation-gate.sh`: 4-field → `--outcome nudged --hook delegation-gate --category <keyword-bin>`
   - `pretooluse-adr-template.sh`: 신규 emit → `--outcome blocked --hook adr-template --category missing-verification --path <p>`
   - `plan-slug-race.sh`: 신규 emit → `--outcome blocked --hook plan-slug-race --category cross-worktree-window --path <p>`

4. **`pretooluse-bash-guard.sh`, `stop-ship.sh` 는 변경 최소**:
   - bash-guard: 이미 5-field 포맷 emit → CLI 헬퍼 사용으로 통일만 (동일 라인 출력).
   - stop-ship: `.ship-history.log` 별도 telemetry 유지 — pipeline outcome 은 hook gate outcome 과 의미 달라 별도 표면 합리. 통합은 별도 ADR 후보.

5. **Legacy entries grandfathered** — 기존 `.hook-fires.log` 58줄의 v1-3field / v1-4field 형식은 그대로 두고, 신규 entries 만 5-field. `scripts/analyze_hook_outcomes.py` (PR #1038) 가 세 포맷 모두 parse.

## Why these specific choices

| 결정 | 근거 |
|---|---|
| outcome enum 9개 | `aware/blocked/bypassed/false_*/nudged/pipeline_*/ok` — 거버넌스 4-pillar (catch / nudge / measure / pipeline) 의 union. 9개가 최소 covering set |
| `_governance.py` 단일 헬퍼 | bash hook 7개 + Python `_self_review.py` 가 동일 포맷 보장. drift 위험 제거. bash-guard 의 기존 5-field 직접 printf 도 같은 헬퍼로 점진 migrate |
| Legacy grandfathered | 58 줄의 v1 entries 를 v2 로 rewrite 시 history 손실. parse 호환만 보장 |
| pipeline outcome 별도 | stop-ship 의 `pipeline_start`/`pipeline_end` 가 hook gate 와 의미 달라 — `.ship-history.log` 분리 유지 |
| outcome 미정의 typo → raise | 새 hook 작성자가 outcome 자유 입력 시 silent drift. CLI 가 enum 검증 |

## Consequences

**이득**:
- 거버넌스 비판 보고서 (2026-05-19) **메타 발견 직접 해소** — `blocked` outcome 이 telemetry 에 entry. "X 훅이 Y 사고를 막는다" 주장 검증 가능.
- **약점 #1 효과측정 unlock**: required check 가 켜진 후 admin force-merge 시도가 발생하면 측정 가능 (별도 surface 필요 — 이 ADR scope 외).
- **약점 #4 효과측정 unlock**: hook 별 enforcement label (PR #1036) ↔ 실제 outcome 분포 사이의 일관성을 90일 후 자동 검증 가능.
- **약점 #7 효과측정 unlock**: memory-lines AWARE/BLOCK threshold (20/30) 가 실제 데이터로 정당화 또는 조정 가능 (analyze script PR #1038 의 threshold_recommendation 함수).
- **약점 #8 해소 경로**: 90일 후 fire 0회 hook 식별 → surface 30% 축소 결정 (사용자 영역).
- 다음 분기 self-review 5축 #3 채점이 input metric ("ADR/PR 추가") 에서 outcome metric ("blocked 이벤트 - false_positive 이벤트") 으로 전환 가능 (사용자 메모 수정 필요 — 본 PR scope 외).

**비용 + 잠재 위험**:
- 8 hook + helper 모두 수정 → 회귀 위험. 회귀 테스트 (`tests/test_hook_telemetry.py`) 가 각 hook 의 emit contract lock-in.
- emit_hook_fire() 가 매 hook fire 마다 python3 fork → ~30ms 추가. hook 자체가 비동기 (PreToolUse) 라 사용자 perception 영향 미미.
- Decision Theatre 재발 가능성 — 이 ADR 도 "측정 표면 추가" 라는 input metric. **자기 일관성 보장 메커니즘**: 본 ADR 의 verifies-key 마커가 90일 후 `.hook-fires.log` 의 실제 `blocked|*` entries 로 backed 되는지 자동 lint (`_governance.py --lint-adr-consequences`). 자동 lint 실패 시 ADR 0060 자체가 invalidated.

## Invariance check

- **ADR 0001** (naive baseline byte-identical): hook telemetry 는 production code path 0 변경 → 합성 baseline 영향 없음.
- **ADR 0003** (answer dict schema_version=2): hook 표면이지 answer contract 아님.
- **ADR 0005** (public synthetic / private real 분리): `.claude/.hook-fires.log` 가 이미 `.claude/*` gitignore (issue #495) — 동일 boundary.
- **ADR 0007** (issue-first + branch convention): 본 ADR 은 issue #1039 + branch `feat/issue-1039-outcome-telemetry` 자체가 ADR 0007 준수.

## Alternatives considered

- **별도 telemetry DB** (SQLite / event log service): 1-day 작업이 1-week 로 확대. fire-log = append-only text 가 사용자 환경 (단일 머신) 에 충분. 데이터 수집 layer 와 분석 layer 분리는 PR #1038 의 `analyze_hook_outcomes.py` 가 이미 담당.
- **포맷 빅뱅 (legacy entries 모두 rewrite)**: 58줄 history 손실 + 미래 신규 hook 추가 시 다시 위험. v2 만 새로 emit, v1 parse 호환 (PR #1038) 으로 transition 부담 분산.
- **stop-ship 의 .ship-history.log 도 합치기**: pipeline outcome 의미가 gate outcome 과 달라 — `pipeline_start` 와 `blocked` 를 같은 분석 함수가 처리하면 hook ROI 측정에 noise. 별도 표면 유지 합리.
- **outcome 분류를 5개로 축소**: aware/blocked/ok 만 두면 bypass / false-positive / nudge 의 fine-grained ROI 측정 불가. 9 enum 의 최소 covering set 선택.

## Verification

<!-- verifies-key: scripts/_governance.py:def emit_hook_fire -->
<!-- verifies-key: scripts/_governance.py:--emit-fire -->
<!-- verifies-key: tests/test_hook_telemetry.py:def test_emit_hook_fire_v2_5field -->
<!-- verifies-key: scripts/claude-hooks/pretooluse-loadbearing.sh:--emit-fire -->
<!-- verifies-key: scripts/claude-hooks/pretooluse-memory-lines.sh:--emit-fire -->
<!-- verifies-key: scripts/claude-hooks/userpromptsubmit-delegation-gate.sh:--emit-fire -->
<!-- verifies-key: scripts/claude-hooks/pretooluse-adr-template.sh:--emit-fire -->
<!-- verifies-key: scripts/claude-hooks/plan-slug-race.sh:--emit-fire -->

90일 후 자기-검증 (ADR 0060 본문이 약속한 outcome 측정이 실제로 일어났는지):
- `python3 scripts/analyze_hook_outcomes.py --window 90d` 의 `blocked` 카운트가 ≥ 1 이면 약속 충족.
- 0 이면 거버넌스 surface 가 fire 안 한 것 — surface 30% 축소 결정 트리거.
