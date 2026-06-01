# 0090: P2.0 (D-minus) — staging self-ship 강제모델 실측 + manifest 계약 정의 (emission·머지는 P2.2)

- **Status**: proposed (D-minus code · manifest 계약 · `protection_verified` 구현은 #1698로 완료, branch protection 설정 VERIFIED; **full accept는 Gate-3 e2e 후** — Verification 참조)
- **Date**: 2026-05-31
- **Issue**: [#1697](https://github.com/hskim-solv/BidMate-DocAgent/issues/1697)
- **Related**: [0088](0088-opt-in-staging-self-ship-external-enforcement.md) (P1 opt-in stub lane), [0085](0085-infinite-mode-active-auto-loop.md) (`EXECUTE_SHIP=0` 기본), [0086](0086-lane-tool-sandbox-policy-option-c.md) (lane sandbox), [0087](0087-opt-in-omc-team-parallel-runner.md) (opt-in omc runner)

## TL;DR

- ADR 0088 P1 fail-closed stub 레인의 **강제 모델을 실측 코드로 구현**한다 (P2.0 D-minus).
- P1의 env-trust(`BIDMATE_SHIP_PROTECTION_VERIFIED` / `BIDMATE_SHIP_TOKEN_SEPARATED`) 플래그를 **제거**하고, `protection_verified`를 실제 `gh api` 브랜치 보호 쿼리로 교체한다.
- `ship_manifest.json` **계약 함수**(`write_ship_manifest` / `read_ship_manifest` / `archive_ship_manifest`, `_staging_ship.py`, 유닛 테스트 포함)를 정의한다. 루프가 manifest를 **자동 기록하는 seam은 이 PR에 없다** — `EXECUTE_SHIP=0`으로 루프는 게이트된 변경을 커밋하지 않으므로 `source_sha=HEAD`가 stale/무의미해진다. manifest emission seam은 실제 커밋/HEAD-binding이 의미 있는 P2.2에서 구현한다.
- `scripts/_ship_env.py` 단일 출처로 모든 runner subprocess 레인의 env 격리를 통일한다.
- `_staging_ship.py`의 `main()`은 **verify-and-refuse pre-flight 하네스**: manifest가 있으면 읽고(idempotent, 소비 아님), 헌법불변 가드 + 라이브 protection 검증을 실행한 뒤, **항상 rc 2(blocked-on-user)를 반환한다** — 이 PR에서 PR 열기·머지는 일어나지 않는다.
- 자율 머지 오케스트레이션(PR 생성·병합, 권한분리 토큰, cap 스토어 트랜잭션, cross-worktree 잠금, 직렬 promotion) 및 **manifest 자동 emission seam**은 **P2.2로 유보**한다.

## 배경

ADR 0088은 `make 시작-ship`을 도입하되 실제 ship()을 **실행하지 않는** fail-closed stub로 P1을 마쳤다. P1 시점에 외부 강제(branch protection + 권한분리 토큰)가 아직 운영자 준비 단계였기 때문이다.

P1 stub의 검증 플래그 구조는 다음 취약점을 내포했다:

1. **Env-trust 우회(ouroboros).** `BIDMATE_SHIP_PROTECTION_VERIFIED=1` / `BIDMATE_SHIP_TOKEN_SEPARATED=1`을 환경변수로 두면, `workspace-write` ~ `danger-full-access` 권한으로 subprocess를 생성하는 runner의 자식 에이전트가 동일 env를 상속해 보호 검증을 우회할 수 있다. 헌법불변의 강제가 in-process env에 의존하면 자기 안전장치를 스스로 해체하는 경로가 열린다.
2. **단일-프로세스 ship() 호출.** P1은 `agent_loop.py` 안에서 ship()을 직접 호출하는 경로를 예비 설계로 남겼다. 루프 프로세스가 ship() 권한을 직접 보유하면 분리 토큰의 격리 효과가 무너진다.

P2.0 D-minus 목표: 외부 강제를 코드에 실제로 경유하게 하고, env-trust를 제거하며, manifest 계약 함수와 verify-and-refuse pre-flight 하네스를 정의한다. 루프의 manifest 자동 emission seam은 `EXECUTE_SHIP=0` 때문에 게이트된 변경이 커밋되지 않아 `source_sha=HEAD`가 stale해지므로 이 PR에 포함하지 않는다 — HEAD-binding이 의미 있는 P2.2에서 구현한다. 자율 머지 자체는 이 PR에 없다.

적대리뷰에서 멀티 worktree 환경의 안전한 자율 머지를 위해서는 트랜잭션 cap 강제 + cross-worktree 공유 잠금 + 직렬 promotion이 함께 필요하다는 점이 확인됐다. 이는 P2.0보다 P2.2에 적합한 결합 단위다.

## 결정

**P2.0 D-minus — 강제모델 실측 + manifest 계약 정의:**

1. **`ship_manifest.json` 계약 함수 정의 (신규 측정/계약 표면).** `_staging_ship.py`에 `write_ship_manifest()` / `read_ship_manifest()` / `archive_ship_manifest()` 세 함수를 구현하고 유닛 테스트로 계약을 고정한다. `_staging_ship.py`의 `main()`은 manifest 파일이 있으면 `read_ship_manifest()`로 **idempotent하게 읽는다** — 소비/아카이브하지 않는다(`.consumed` 아카이브는 P2.2 머지 성공 후). 운영자가 `--source` 인자를 전달해 live protection-verify 하네스를 수동으로 실행할 수 있다. **`agent_loop.py`에 manifest 자동 기록 seam(= `_maybe_write_ship_manifest`)은 이 PR에 없다**: 루프는 `EXECUTE_SHIP=0`으로 실행되므로 게이트된 변경이 커밋되지 않아 `source_sha=HEAD`가 stale/무의미해진다. manifest emission은 실제 커밋이 일어나는 P2.2에서 구현한다. `agent_loop.py`는 ship()을 직접 호출하지 않는다.

2. **라이브 protection_verified (`_RealGitOps`).** P1의 `BIDMATE_SHIP_PROTECTION_VERIFIED` env-trust는 **제거**한다. `_staging_ship.py`는 `gh api repos/:owner/:repo/branches/autopilot/integration/protection`을 실제 호출해 **특정 required-check `staging-self-ship-guard`의 존재**(`required_status_checks.contexts` 또는 `.checks[].context`에 포함) + force-push deny 여부를 검증한다. 슬래시 포함 브랜치명은 URL-encode된다. **아무 required-check나가 아니라 그 가드 워크플로가 반드시 required여야** True. 검증 실패 시 `exit 2`(blocked-on-user). `BIDMATE_SHIP_TOKEN_SEPARATED` env-trust도 동시에 제거한다.

3. **`BIDMATE_SHIP_*` env 격리 — 단일 출처 `scripts/_ship_env.py`.** `strip_ship_secret_env()` 단일 함수(프리픽스 deny)가 **모든 runner subprocess 레인을 경유**한다: claude write + codex patch ×2 write 레인, read/review 레인 2곳(`agent_loop_codex_turn.py` / `agent_loop_claude_turn.py`), omc 레인(`_OMC_ENV_ALLOWLIST` positive allowlist로 이미 제외). 프리픽스 literal `"BIDMATE_SHIP_"`은 `_ship_env.py` 한 곳에만 존재(whack-a-mole 방지). PATH/HOME/auth는 보존(over-tight 아님).

4. **Makefile `시작-ship` 업데이트.** loop sub-make 호출 전에 (a) kill-switch(`BIDMATE_SHIP_KILL_SWITCH` env 또는 `$(ACTIVE_SHIP_STATE_DIR)/KILL` 파일)를 **사전 검사**하고, (b) **prefix-strip 셸 루프**로 `BIDMATE_SHIP_*` 전부(control signal `BIDMATE_SHIP_KILL_SWITCH` 제외 — 미래/미지 `BIDMATE_SHIP_*`도 포함)를 `unset`한 뒤 `$(MAKE) 시작`을 실행한다. D-minus에서는 manifest 자동 emission이 없으므로 `BIDMATE_SHIP_MANIFEST_DIR`을 sub-make에 주입하지 않는다(emission은 P2.2). 머지 토큰·cap 스토어·시크릿은 workspace-write 루프에 주입하지 않는다. 기본 `make 시작` 타겟은 불변 — byte-identical 보존.

5. **`main()` = verify-and-refuse pre-flight 하네스.** `_staging_ship.py`의 `main()`은 manifest를 읽고, 헌법불변 가드를 실행하고, 라이브 protection 쿼리를 수행한 뒤 **항상 rc 2를 반환**한다. `_RealGitOps.open_pr`/`merge`는 명시적 P2.2-deferred stub으로, 호출 시 raise한다. cap 스토어, 머지 토큰 처리, cross-worktree 잠금, bounded check poll은 이 PR에 없다.

### P2.2 유보 사항

다음은 P2.0 D-minus에서 **구현하지 않으며** P2.2에서 별도 ADR이 필요하다. 적대리뷰에서 멀티 worktree 환경의 안전한 자율 머지는 이 항목들이 트랜잭션 단위로 묶여야 한다는 점이 확인됐다:

- **`agent_loop.py` manifest emission seam (`_maybe_write_ship_manifest`).** 루프가 `local-gate-complete` 완료 시 `<state-dir>/ship_manifest.json`을 자동 기록하는 seam. `EXECUTE_SHIP=0`으로 루프가 실행되는 한 게이트된 변경이 커밋되지 않아 `source_sha=HEAD`가 stale/무의미해진다. emission seam은 실제 커밋/HEAD-binding이 의미 있는 P2.2 머지 오케스트레이션과 함께 구현한다.
- **자율 PR 생성·병합.** 라이브 `gh pr create` / `gh pr merge` 호출 — 현재 `open_pr`/`merge`는 P2.2-deferred stub(호출 시 raise).
- **권한분리 머지 토큰.** `BIDMATE_SHIP_MERGE_TOKEN` — runner workspace-write 도메인 밖 별도 프로비저닝. ambient `GH_TOKEN`/`GITHUB_TOKEN` 차단 후 이 토큰만 사용하는 `merge()` 구현.
- **Daily-cap 트랜잭션 + cross-worktree 공유 잠금.** `_FileMergeCapStore` (`BIDMATE_SHIP_CAP_STORE`) + T4 self-immutable cap 스토어 하드닝. malformed cap 파일 → fail-closed. 동시 실행 worktree 간 직렬 카운터.
- **직렬 promotion + source_sha→PR head binding.** `source_sha`를 PR head에 묶어 게이트된 커밋의 귀속을 1:1 강제(`--match-head-commit`). serialized promotion과 함께 구현.
- **Bounded check poll.** `BIDMATE_SHIP_CHECK_ATTEMPTS`/`BIDMATE_SHIP_CHECK_INTERVAL_SECONDS`로 PR 생성 후 체크 대기 재시도.
- **PR idempotency.** `open_pr`에서 동일 `source→base` 오픈 PR 재사용(중복 PR 방지).

### P2.1+ 예약

- `SELF_IMMUTABLE_PATHS` eligibility 이중차단: T4 self-immutable cap 스토어 경로가 ship 대상 PR에 포함되면 lane 차단 (P2.3). **`_ship_env.py`와 manifest seam도 P2.1의 `SELF_IMMUTABLE_PATHS`에 추가할 것.**
- SLA 카운터 표면: 일일 merge count / revert rate / main-green rate (P2.2).

## 결과

**Wins**
- env-trust 우회 경로 제거 — ouroboros 차단이 in-process가 아닌 실제 GitHub 서버 상태에서 경유됨.
- manifest **계약**(`write_ship_manifest` / `read_ship_manifest` / `archive_ship_manifest`)과 verify-and-refuse pre-flight 하네스가 실코드로 정의됨 — `agent_loop.py`는 manifest를 emit하지 않으며(emission seam = `_maybe_write_ship_manifest`는 P2.2) ship()도 직접 호출하지 않아 2-프로세스 권한 분리 구조의 기반이 마련됨.
- 모든 runner 레인의 `BIDMATE_SHIP_*` env 격리가 단일 출처로 통일 — whack-a-mole 누락 경로 차단.
- 기본 `make 시작`(`EXECUTE_SHIP=0`) byte-identical 보존 — CI/데모/멀티 worktree 회귀 0.
- manifest 계약 + live protection 검증이 실코드로 존재 — P2.2 머지 오케스트레이션의 기반.

**Costs**
- 현재 레인은 항상 rc 2로 종료한다. 실제 PR 생성·머지는 P2.2 전까지 일어나지 않는다.
- manifest 자동 기록 seam이 없으므로 `_staging_ship.py main()`을 exercise하려면 `--source` 인자를 수동으로 전달해야 한다.
- `gh api` 호출은 네트워크 의존 — rate-limit / API 장애 시 fail-closed(verify 안 됨).

**blocked-on-user (이 ADR의 PR에서 명시적으로 하지 않는 것)**
- 권한분리 머지 토큰 provisioning (`BIDMATE_SHIP_MERGE_TOKEN`, runner write domain 밖). (P2.2)
- T4 self-immutable cap 스토어 하드닝 (`BIDMATE_SHIP_CAP_STORE`). (P2.2)
- 자율 PR 생성·병합 — P2.2 구현 전까지 `open_pr`/`merge` stub은 호출 시 raise.
- **Gate-3 라이브 e2e (① 헌법불변 파일 변경 PR → required check fail; ② 토큰 PUT protection → 403) — full accept 조건.**

(완료: `autopilot/integration` 브랜치 보호 실설정 = 2026-06-01 설정 VERIFIED; 이 ADR Status `proposed → accepted` 전환 = Gate-3 e2e 후. Verification 참조.)

**Supersession / 관계**
- ADR 0088 P1 env-trust 조항을 **부분 supersede** — `BIDMATE_SHIP_PROTECTION_VERIFIED` / `BIDMATE_SHIP_TOKEN_SEPARATED` 제거. P1의 나머지 불변(staging-only / force-push 금지 / ship-arm 상호배제 / 데이터 경계)은 보존.
- ADR 0085(`EXECUTE_SHIP=0` 기본)는 보완 — 기본 `시작`은 불변, opt-in lane만 활성화.
- ADR 0001·0003·0005는 보존.

## 검토한 대안

- **env-trust 유지 (P1 그대로).** Reject: workspace-write runner 자식이 env를 상속해 보호 검증 우회 가능 — 헌법불변 강제의 근거가 될 수 없음. ouroboros와 구조적으로 동일.
- **P2.0에서 자율 머지까지 한 번에 구현.** Reject: 멀티 worktree 환경에서 안전한 자율 머지는 트랜잭션 cap + cross-worktree 잠금 + 직렬 promotion이 함께 필요하다. 이 세 가지가 분리된 채 머지 오케스트레이션만 도입하면 cap racing / ambient-credential spoof / 중복 PR 문제가 잔존한다. D-minus에서 기반(env 격리 + manifest 계약 정의 + live verify)을 굳히고 P2.2에서 emission seam + 트랜잭션 단위로 묶는 것이 안전하다.
- **manifest emission seam을 D-minus에 포함.** Reject: `EXECUTE_SHIP=0`으로 루프는 게이트된 변경을 커밋하지 않는다. 이 상태에서 `source_sha=HEAD`를 기록하면 stale commit을 가리킨다. manifest가 가리키는 SHA는 실제로 병합할 커밋과 1:1로 binding되어야 한다 — 이 binding은 P2.2의 source_sha→PR head 묶음과 함께 구현해야 의미가 있다.
- **단일 env var로 protection 스킵 허용.** Reject: 외부 강제의 의미를 무력화. fail-closed가 올바른 동작.

## Verification

<!-- verifies-key: scripts/_staging_ship.py:read_ship_manifest -->

`write_ship_manifest` / `read_ship_manifest` / `archive_ship_manifest` 세 함수가 `scripts/_staging_ship.py`에 존재하며, manifest 계약을 유닛 테스트로 고정한다. `read_ship_manifest`는 **idempotent하게 읽는다** — D-minus에서는 파일을 소비/아카이브하지 않는다(단일-소비는 P2.2 머지 성공 후 `archive_ship_manifest` 호출 시). manifest path: `$(ACTIVE_SHIP_STATE_DIR)/ship_manifest.json`.

manifest emission seam의 **의도된 부재**(P2.2 유보)는 다음으로 확인한다:
- `grep -n "_maybe_write_ship_manifest" scripts/agent_loop.py` 결과가 비어 있어 루프에 자동 기록 seam이 없음을 보인다.
- `git diff origin/main -- scripts/agent_loop.py` 에서 `local-gate-complete` 완료 블록(`cycle["completion_decision"] = "local-gate-complete"` 부근)이 변경되지 않아 origin/main과 byte-identical임을 보인다 — 루프는 게이트된 변경을 기록만 하고 manifest를 emit하지 않는다.
- `make -n 시작-ship` 출력의 loop sub-make(`make 시작`) 라인에 `BIDMATE_SHIP_MANIFEST_DIR=` 주입이 없음을 확인한다(emission이 없으므로 sub-make에 manifest dir을 주입하지 않는다).

반면 manifest path 와이어링은 **post-step** `_staging_ship.py` 호출에만 존재한다: `make -n 시작-ship` 출력에 `scripts/_staging_ship.py ... --manifest-dir "$(ACTIVE_SHIP_STATE_DIR)"` 가 포함됨을 확인할 수 있다(verify-and-refuse 하네스가 manifest가 있으면 idempotent하게 읽는 경로 — 루프 emission이 아님).

추가 검증 표면 (운영자 준비 완료 후):
- `make 시작`(인자 없음) 출력이 변경 전후 byte-identical (BIDMATE_SHIP_MANIFEST_DIR unset → no-op).
- `gh api` 보호 쿼리가 required-check 부재 시 `exit 2` 반환 확인.
- `_staging_ship.py main()` 이 manifest/source 없이 또는 protection 미검증 상태에서 항상 rc 2(blocked-on-user)를 반환하고 PR 생성·머지를 하지 않는 것을 확인.
- `bash scripts/test.sh` 통과.

### 구현 완료 현황 + full accept 잔여 조건 (2026-06-01)

**구현 완료 (코드·설정)**: P2.0 D-minus 강제모델 + manifest 계약 함수 + `protection_verified` 구현 코드가 #1698로 안착했고, operator branch protection **설정이 실존**함을 `gh api`로 확인했다(설정 **존재** VERIFIED, 2026-06-01): `staging-self-ship-guard` required check + `enforce_admins=true`는 **`autopilot/integration` 한정**(워크플로가 `on: pull_request: branches: ["autopilot/**"]` 전용 → main은 이 check를 리포트할 수 없으므로 미적용, 의도된 설계); `require_code_owner_reviews` + `allow_force_pushes=false`는 **integration + main 양쪽**(main은 `required_checks=null`).

**full accept 잔여 조건 (Status가 proposed인 이유)**: 이 ADR의 핵심인 **live enforcement 작동** — Gate-3 e2e(① 헌법불변 파일 변경 PR → required check fail로 실제 머지 차단; ② 머지 토큰 PUT protection → 403)는 아직 실증되지 않았다. **설정 존재 ≠ 강제 작동**이므로 Status는 proposed로 유지하며, Gate-3 e2e를 integration 레인 운영 중 캡처(명령/결과 artifact 기록)한 뒤 accepted로 승격한다. P2.2 유보분(loop emission seam, 자율 머지, 권한분리 토큰, cap 스토어)도 후속 ADR 0093+가 이어받는다. codex adversarial pre-commit(freq 3/8, 2/3)이 "accepted가 미검증 강제를 숨긴다"고 지적해 proposed로 유지하고 완료 현황만 본문에 기록한다.
