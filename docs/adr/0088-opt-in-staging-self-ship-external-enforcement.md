# 0088: Opt-in staging self-ship lane (P1) — 외부 경계 강제 헌법불변

- **Status**: proposed
- **Date**: 2026-05-31
- **Related**: [0001](0001-preserve-naive-baseline.md) (baseline byte-identical), [0003](0003-structured-answer-citation-contract.md) (답변 계약), [0005](0005-eval-split-public-synthetic-private-local.md) (데이터 경계), [0085](0085-infinite-mode-active-auto-loop.md) (`EXECUTE_SHIP=0` 기본), [0086](0086-lane-tool-sandbox-policy-option-c.md) (lane sandbox), [0087](0087-opt-in-omc-team-parallel-runner.md) (opt-in omc runner, no-auto-merge); deep-interview/consensus 산출물 `.omc/specs/deep-interview-make-sijak-full-automation.md` · `.omc/plans/make-sijak-full-automation-consensus.md` (로컬 planning 아티팩트, gitignore — 미커밋)

## TL;DR

- `make 시작`(현 `EXECUTE_SHIP=0` fail-closed)에 **opt-in staging self-ship lane**을 추가한다(P1). 루프는 `autopilot/integration` 장수 브랜치에만 무인 머지하고, main 직접 머지·force-push는 영구 금지한다.
- 헌법불변(force-push 금지·staging 경계·circuit breaker·root kill-switch·데이터 경계)의 **권위 강제는 루프가 권한을 못 갖는 외부 경계**(GitHub branch protection required check + 권한분리 머지 토큰)에 둔다. in-process 가드는 1차 fast-fail 보조다.
- 기본 `make 시작`(`EXECUTE_SHIP=0`)·ADR 0001 baseline은 byte-identical 보존. self-ship은 신규 opt-in 진입점으로만 활성화.
- 이 ADR은 **P1 한정**. 무제한 self-modify(옵션 3)·main 자동 승격·무한 모드·task 자동생성 등 더 공격적 능력은 P2/P3의 별도 ADR(G1-G4)로 분리하며 본 ADR 범위 밖이다.

## 배경

`make 시작`([Makefile:1085](../../Makefile))은 자율 agent-loop의 운영자 front door다. 현재 runner는 실행하되 ship하지 않는다 — `ACTIVE_AUTO_LOOP_EXECUTE_SHIP=0`이 기본이라, local conservative gate 통과 시 task를 `local-gate-complete`로 완료 마킹만 하고 push/PR/merge는 하지 않는다([scripts/agent_loop.py:10734](../../scripts/agent_loop.py)). ship은 오직 `make agent-loop-human-gated-exec ... CONFIRM_HUMAN_APPROVED=1` 수동 호출로만 가능하다([agent_loop.py:7783](../../scripts/agent_loop.py), fail-closed).

운영자가 "사람 개입 0의 무인 운영"을 요구했다(deep-interview 10라운드, spec 참조). 그러나 무인 self-ship을 단순히 `EXECUTE_SHIP=1`로 여는 것은 두 가지 비가역 위험을 연다.

1. **Governance ouroboros.** runner는 `claude -p`/`codex exec` subprocess를 `workspace-write`([agent_loop.py:218](../../scripts/agent_loop.py)) ~ `danger-full-access`(ADR 0086)로 실행한다. 즉 루프 안의 에이전트는 임의의 git/파일 작업을 할 수 있는 신뢰되지 않은 코드다. 안전 가드를 in-process Python 함수로 두면, 루프가 가드를 직접 우회하거나 가드 파일을 편집할 수 있어 자기 안전장치를 스스로 해체하는 경로가 열린다.
2. **비가역 손상.** main 직접 머지 + force-push 자동화는 shared object store 손상(install-hooks gc/fsync 가드, issue #1681)·history 재작성·비공개 데이터 외부 유출(ADR 0005) 등 되돌릴 수 없는 결과를 낼 수 있다.

consensus 검토(Planner/Architect/Critic, deliberate)에서 두 결함이 코드로 입증되어, 안전 강제를 루프 권한 밖으로 외부화하고 첫 증분을 staging-안전형으로 좁히는 결정에 도달했다.

## 결정

**P1 — opt-in staging self-ship lane, 외부 경계 강제:**

1. **opt-in 활성화.** 기본 `make 시작`은 `EXECUTE_SHIP=0` 불변(ADR 0085 보완). self-ship은 신규 opt-in 진입점(`make 시작-ship` 또는 전용 env)으로만 활성화. ADR 0001 baseline byte-identical 보존.
2. **Staging-only ship.** 루프는 `autopilot/integration` 장수 통합 브랜치에만 머지한다. **main 직접 머지·push 금지.** main 승격은 본 ADR 범위 밖(P3, 자동 게이트).
3. **force-push / history-rewrite 영구 금지.** 어떤 단계에서도 금지. 롤백은 `git revert`(append-only)만.
4. **헌법불변의 권위 강제 = 외부 경계.** force-push 금지·staging 경계·circuit breaker·root kill-switch·데이터 경계는 루프가 권한을 못 갖는 곳에서 강제한다:
   - `autopilot/integration` **branch protection + required status checks** (헌법불변 파일 변경·force-push 거부).
   - **권한분리 머지 토큰** (branch protection bypass/admin 불가).
   - self-ship 진입 전 `gh api`로 protection 상태 **read-verify** (drift 시 fail-closed).
   - in-process 가드는 **1차 fast-fail 보조** — 안전 주장의 근거가 아니다.
5. **데이터 경계(ADR 0005).** PR body/커밋/외부 알림은 raw private RFP 원문·per-case output 금지. 외부 알림 payload는 **숫자/카운트 allowlist만**. 로컬 보관·분석은 전면 허용(막은 외부 전송/커밋 경계에만). `scripts/_governance.py`의 JSON 스캐너는 구조화 artifact 전용이며, 자유텍스트(PR body/알림) 검출은 **신규** 스캐너로 구현한다.
6. **Circuit breaker (defense-in-depth).** T1(연속 실패) / T2(revert율·CI red, P2) / T3(cost, P2) / T4(하루 머지 cap). T4 카운터는 루프가 리셋 못 하는 위치(self-immutable). breaker·kill-switch는 self-modify 불가.
7. **ship-arm 상호배제.** `make 시작-ship`은 `make ship-arm`과 동시 활성화 금지(`.claude/.ship-armed` 존재 시 fail-closed) — 자율 ship 권위자 1개.

## 결과

**Wins**
- `make 시작` 기본 동작·ADR 0001 baseline byte-identical 보존 — CI/데모/멀티 worktree 회귀 0.
- ouroboros가 루프 권한 밖 경계(branch protection + 분리 토큰)에서 차단됨 — in-process 가드 우회해도 backstop 존재.
- 비가역 위험 봉쇄: main 무관(staging만), force-push 금지, 데이터 유출은 숫자-only allowlist로 원천 차단.
- ADR 0087의 "신뢰 안 되는 runner → 외부 게이트 재부과" 패턴([0087:207-209](0087-opt-in-omc-team-parallel-runner.md))과 정합.

**Costs**
- GitHub branch protection·권한분리 토큰 등 **운영 설정 의존**(코드 밖). P1 closing 시 라이브 e2e로 1회 실증 필수, drift 방어는 진입 전 read-verify.
- `agent_loop.py`(~19k줄) 분기 복잡도 증가.
- 무인 self-ship lane은 데이터 경계 자유텍스트 검출의 본질적 한계(영문 raw 미검출 등)를 안는다 — 외부 알림 숫자-only allowlist로 backstop.

**Supersession / 관계**
- **ADR 0087 (d) 조항([0087:199-201](0087-opt-in-omc-team-parallel-runner.md), "`agent_loop.py`는 `LOAD_BEARING_PATHS` 비승격 + ship 실행은 기존 human-gated 경로가 담당")을 부분 supersede** — opt-in staging self-ship lane 추가로 "ship은 human-gated만" 명제를 staging 브랜치 한정 완화. main에 대한 no-auto-merge(0087)는 보존.
- **ADR 0085**(`EXECUTE_SHIP=0` 기본)는 보완 — 기본은 불변, opt-in lane만 추가.
- ADR 0001·0003·0005는 보존(역전 아님). 옵션 3의 baseline/답변계약/ADR 자동수정 허용(G1-G4)은 본 ADR에 **포함되지 않으며** P2/P3 별도 ADR로만 다룬다.

## 검토한 대안

- **`EXECUTE_SHIP=1` 단순 개방 + in-process 가드.** Reject: runner와 같은 권한 도메인이라 self-referential 강제 불가(ouroboros). 안전 주장의 근거가 될 수 없음.
- **main 직접 머지 + force-push 자동화 (옵션 1).** Reject: 복구 불가능한 꼬리위험(shared object store 손상, history 파괴). staging-안전형으로 대체.
- **격리 신규 ship 게이트 모듈 (Option B).** 신뢰경계는 가장 명확하나 runner 로직 재구성 노력 큼. Option A가 외부 강제를 채택하면 핵심 이점 대부분 흡수 — 차선으로 보류.
- **`make ship-arm` 확장 (Option C).** Reject: ship-arm과 `make 시작`은 mutually exclusive — 합치면 그 불변 위반.

## Verification

<!-- verifies-key: Makefile:ACTIVE_AUTO_LOOP_EXECUTE_SHIP -->

이 ADR은 proposed(plan-only)이다. P1 구현 전 검증 가능한 단 하나의 불변은 **기본 경로 보존**이다: `Makefile`의 `시작:` 타겟이 `ACTIVE_AUTO_LOOP_EXECUTE_SHIP=0`을 넘긴다는 사실(위 marker로 lint). self-ship은 이를 바꾸지 않고 신규 opt-in 진입점으로만 추가되어야 한다.

P1 구현이 진행되면 다음 검증 표면이 추가된다 (구현 PR에서 marker 갱신):
- `make 시작`(인자 없음) 출력이 변경 전후 byte-identical (회귀 테스트). `EXECUTE_SHIP=0` 기본 분기 보존.
- 라이브 e2e(mock 불가): 실제 `autopilot/integration`에 ① 헌법불변 파일 변경 PR → required check fail로 머지 거부, ② 머지 토큰의 protection PATCH → 403.
- 적대 테스트: force-push 차단, main target deny, raw payload(한/영) 차단·aggregate 허용, T4 cap+1 정지·카운터 리셋 차단, kill-switch 정지, ship-arm 동시 fail-closed, required-check 부재 PR green 오판 안 함.
- `bash scripts/test.sh` 통과.
