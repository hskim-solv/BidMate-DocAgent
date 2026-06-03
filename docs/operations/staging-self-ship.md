# Staging self-ship lane — 운영자 runbook (P2.0 D-minus, ADR 0088 + ADR 0090)

`make 시작-ship`은 byte-identical `make 시작` 루프(`EXECUTE_SHIP=0`, 불변)에 격리된
`scripts/_staging_ship.py` 모듈을 post step으로 결합한 **opt-in** lane이다. 장기
목표는 자율 루프가 자기 작업을 장수(long-lived) `autopilot/integration` 브랜치로
직접 머지하게 하는 것이다. **P2.0 D-minus 시점에서 이 lane은 강제(enforcement)
전제조건을 검증하고 머지를 거부한다 — 자율 머지는 P2.2다.**

**P2.0 D-minus 변경 (ADR 0090):** 이 PR은 강제 모델을 실제로 작동하게 만든다:

- P1 env-trust 플래그(`BIDMATE_SHIP_PROTECTION_VERIFIED` / `BIDMATE_SHIP_TOKEN_SEPARATED`)는
  **제거**됨 — env를 상속한 workspace-write runner가 이를 위조(spoof)할 수 있었다
  (constitutional-invariant 우회).
- `protection_verified`는 이제 **실시간 `gh api` 쿼리**다 (특정
  `staging-self-ship-guard` required check + `allow_force_pushes.enabled=false` +
  `enforce_admins.enabled=true`, 슬래시 포함 브랜치는 URL 인코딩, repo_root에 바인딩,
  gh 부재 / 타임아웃 / 에러 시 fail-closed).
- 모든 `BIDMATE_SHIP_*` env 변수는 **단일 출처 `scripts/_ship_env.py`**를 통해 모든
  runner 서브프로세스 lane에서 제거된다 (deny-by-prefix, 6개 lane 전부).
  `make 시작-ship`은 루프 sub-make 전에 `env -u`로 시크릿을 제거하고 kill-switch를
  사전 점검한다.
- `_staging_ship.py`는 **manifest CONTRACT 함수**(`write_ship_manifest` /
  `read_ship_manifest` / `archive_ship_manifest`, 단위 테스트됨)를 정의한다. `main()`은
  manifest가 **있으면** 읽고(idempotent — 소비하지 않음), 수동 실행을 위해 `--source`를
  받는다. **이 PR에서 `agent_loop.py`는 manifest를 자동 emit하지 않는다** — 루프가
  `EXECUTE_SHIP=0`으로 돌아 아무 변경도 커밋되지 않으므로 `source_sha=HEAD`는
  stale / 무의미하다. Manifest emission은 HEAD-binding이 실제가 되는 P2.2로 연기됐다.
- `_staging_ship.py main()`은 **검증-후-거부(verify-and-refuse) pre-flight harness**다:
  manifest를 읽고(있으면), constitutional 가드 + 실시간 protection 체크를 실행한 뒤
  **항상 rc 2 (blocked-on-user)를 반환**한다. `open_pr`/`merge`는 호출 시 raise하는
  명시적 P2.2-연기 stub이다.

이 lane이 항상 머지를 거부하는 것은 **올바른 D-minus 동작**이다 — 버그가 아니다.

## 강제 모델 (enforcement model — 먼저 읽을 것)

`scripts/_staging_ship.py`의 in-process 가드(force-push / staging-boundary /
data-boundary / kill-switch)는 **best-effort 1차 fast-fail에 불과**하다.
workspace-write runner는 이를 우회할 수 있다. **권한(authority)**은 외부에, 루프가
권한을 갖지 못하는 도메인에 있다:

1. `autopilot/integration`에 대한 GitHub **branch protection** — `staging-self-ship-guard`
   워크플로를 **required status check**로 지정.
2. (P2.2) branch protection을 우회할 수 없는 **권한 분리된 merge 토큰**
   (`BIDMATE_SHIP_MERGE_TOKEN`) — **runner write 도메인 밖**에 저장.

`protection_verified`는 `repos/:owner/:repo/branches/autopilot%2Fintegration/protection`에
대해 **실시간 `gh api` 쿼리**를 수행한다. `staging-self-ship-guard` required check가
존재하고 **또한** force-push가 거부되는지 확인한다. 다른 required check가 있는 것만으로는
충분하지 않다 — 이 특정 가드가 목록에 있어야 한다. 이를 override하는 env 플래그는 없다.
쿼리가 실패하거나 protection이 불충분하면 `_staging_ship.py`는 code 2 (blocked-on-user)로
종료한다.

모든 `BIDMATE_SHIP_*` env 변수는 deny-by-prefix로 **모든 runner 서브프로세스 lane에서
제거**된다 (claude write + codex patch write 2개 + read/review turn 2개 + omc lane),
단일 출처는 `scripts/_ship_env.py`. Runner 자식 프로세스는 ship 시크릿을 읽거나 위조할
수 없다 (ADR 0090).

## Constitutional-change 강제 = CODEOWNERS 리뷰 (ADR 0091)

constitutional ship-lane 파일의 변경은 PR-body 마커가 아니라 **CODEOWNERS code-owner
리뷰**로 게이팅된다. 기존의 author-writable `[constitutional-change-ack]` 마커는 자율
루프가 스스로 충족할 수 있었다 (PR author가 자기 PR body를 작성 가능) — 따라서 실제
외부 게이트가 아니었고, ADR 0090이 제거한 env-trust 플래그와 같은 ouroboros 부류였다.
ADR 0091이 그 마커 메커니즘을 supersede한다.

이제 신뢰 신호는: PR author가 **아닌** CODEOWNERS code owner가 **APPROVED** 리뷰를
제출해야 한다. GitHub는 PR author가 자기 PR을 승인하는 것을 차단하므로, 자율 루프(=
PR author)는 이 신호를 물리적으로 생성할 수 없다.

- `.github/CODEOWNERS`가 보호 경로를 owner에 매핑한다.
- `scripts/check_constitutional_review.py`가 required-check 로직이다: `gh api`로 PR의
  변경 파일 / author / 승인 리뷰어를 가져와, non-author code owner가 승인하지 않았으면
  실패(exit 1)한다. 그 `PROTECTED_PATHS` 집합은 parity 테스트
  (`tests/test_constitutional_review.py`)로 `.github/CODEOWNERS`와 동기화 유지된다.
- 보호 집합 (ADR 0091에서 확장): `scripts/_staging_ship.py`,
  `scripts/_ship_env.py`, `scripts/_ship_payload_guard.py`, `scripts/_governance.py`,
  `.github/workflows/staging-self-ship-guard.yml`, `.github/CODEOWNERS` 자신, 그리고
  `.githooks/pre-commit`. (`scripts/agent_loop.py`는 너무 자주 편집되어 의도적으로 제외.)

**운영자 blocked-on-user 단계:** 해당 브랜치(`main`과 `autopilot/integration`, 그리고
P2.2 integration 브랜치)에 branch protection **"Require review from Code Owners"**를
활성화한다. 없으면 GitHub가 code-owner 리뷰를 강제하지 않아 게이트의 1차 권한이
누락된다. 이것은 에이전트가 수행할 수 없는 GitHub admin 작업이다.

## 전제조건 — 운영자 GitHub-admin 작업 (blocked-on-user)

> 이 단계들은 GitHub admin 권한이 필요하다. 에이전트가 수행하지 않는다 (에이전트는
> 보호 브랜치를 프로비저닝할 권한이 없다). 아래 protection 설정이 `protection_verified`가
> 확인하는 대상이며 — 없으면 lane은 항상 2로 종료한다.

### 1. 보호된 integration 브랜치 생성

```bash
# main에서 장수(long-lived) integration 브랜치 생성
git switch -c autopilot/integration origin/main
git push -u origin autopilot/integration

# branch protection: staging-self-ship-guard required check + force-push 거부
#
# 경고 (ADR 0091): required_pull_request_reviews는 반드시
# require_code_owner_reviews=true 를 포함해야 한다. required_pull_request_reviews=null
# 로 설정하면 CODEOWNERS 게이트(자율 루프가 가드 파일 PR을 self-approve 하는 것을
# 막는 constitutional-change 가드)를 조용히(SILENTLY) 비활성화한다.
# 항상 아래처럼 전체 required_pull_request_reviews 객체를 전달하라.
gh api -X PUT repos/:owner/:repo/branches/autopilot%2Fintegration/protection \
  -f 'required_status_checks[strict]=true' \
  -f 'required_status_checks[checks][][context]=staging-self-ship-guard' \
  -F 'enforce_admins=true' \
  -F 'required_pull_request_reviews[require_code_owner_reviews]=true' \
  -F 'required_pull_request_reviews[dismiss_stale_reviews]=false' \
  -F 'required_pull_request_reviews[required_approving_review_count]=1' \
  -F 'restrictions=null' \
  -F 'allow_force_pushes=false' \
  -F 'allow_deletions=false'
```

### 2. P2.2: 권한 분리된 merge 토큰과 cap store (연기됨)

이들은 **D-minus에 불필요**하며 P2.2로 연기됨:

- `BIDMATE_SHIP_MERGE_TOKEN` — 이 repo로 스코프된 fine-grained PAT (또는 GitHub App
  installation 토큰), **Contents: read/write + Pull requests: read/write** 권한은 갖되
  Administration은 **갖지 않음**. branch protection을 편집할 수 없어야 한다.
- `BIDMATE_SHIP_CAP_STORE` — cross-worktree 일일 cap 트랜잭션성을 위한 T4
  self-immutable cap store 파일 경로 (runner write 도메인 밖).

## Ship manifest 흐름 (P2.0 D-minus)

`make 시작-ship`은 byte-identical `make 시작` 루프를 실행하고(`env -u`로 시크릿 제거,
kill-switch 사전 점검), 그 다음 `_staging_ship.py`를 post step으로 호출한다.

**이 PR에는 manifest 자동 emission이 없다.** `agent_loop.py`는 `ship_manifest.json`을
쓰지 않는다 — 루프가 `EXECUTE_SHIP=0`으로 돌아 게이팅된 변경이 절대 커밋되지 않으므로
`source_sha=HEAD`는 stale하다. manifest emission seam(`_maybe_write_ship_manifest`)은
실제 커밋이 존재하고 HEAD-binding이 유의미한 P2.2로 연기됐다.

manifest **contract 함수**는 `_staging_ship.py`에 정의·단위 테스트됨:
- `write_ship_manifest(state_dir, ...)` — `<state-dir>/ship_manifest.json` 작성
- `read_ship_manifest(state_dir)` — **idempotent 읽기** (소비/아카이브하지 않음)
- `archive_ship_manifest(state_dir)` — `.consumed`로 이동 (P2.2 merge 성공 경로에서
  호출)

`_staging_ship.py main()`은 manifest가 **이미 있으면** 읽고(idempotent), 운영자가
`--source`를 제공하면 그것을 사용한 뒤, constitutional 가드 + 실시간 protection 체크를
실행하고 rc 2로 종료한다.

```bash
# manifest 경로 (contract, P2.2 emission seam이 작성; 테스트용으로 운영자가 배치):
# $(ACTIVE_SHIP_STATE_DIR)/ship_manifest.json

# 오늘 실시간 protection-verify harness를 수동 실행하려면:
python scripts/_staging_ship.py --source <branch> --state-dir reports/agent_loop/active
```

## Gate 3 — 실시간 e2e (D-minus: 외부 강제 검증; P2.2: merge 검증)

운영자 branch-protection 설정 후, 이 두 adversarial 체크가 외부 권한이 실제임을
증명한다. mock할 수 없다 — 실제 GitHub 서버 상태를 동작시킨다.

1. **가드 파일 변경이 차단된다.** PR author가 아닌 CODEOWNERS code owner의 APPROVED
   리뷰 *없이* `scripts/_staging_ship.py`를 편집하는 PR을 `autopilot/integration`으로
   연다. 예상: `staging-self-ship-guard` required check가 **실패**하고 머지가 차단된다
   (아래 "Constitutional-change 강제" 참조 — ADR 0091).
2. **merge 토큰은 protection을 비활성화할 수 없다.** (P2.2, 토큰 프로비저닝 후)
   ```bash
   GH_TOKEN=$BIDMATE_SHIP_MERGE_TOKEN gh api -X PATCH \
     repos/:owner/:repo/branches/autopilot%2Fintegration/protection \
     -F 'allow_force_pushes=true'
   ```
   예상: **HTTP 403**.

Gate 3 check 1은 protection이 실제임을 검증한다. Check 2는 P2.2로 연기됨 (권한 분리
토큰이 존재해야 함).

## lane 실행

```bash
# fail-closed (blocked-on-user, exit 2) — 올바른 D-minus 동작:
make 시작-ship

# kill-switch (즉시 발동): 파일을 만들거나 env 변수를 설정.
# 파일 형태는 반드시 lane의 state dir(ACTIVE_SHIP_STATE_DIR) 아래 있어야 하며,
# 이는 `make 시작-ship`이 --state-dir로 전달하는 것 — .omc/state가 아니다.
touch reports/agent_loop/active/KILL   # 파일 형태 (= $(ACTIVE_SHIP_STATE_DIR)/KILL)
export BIDMATE_SHIP_KILL_SWITCH=1      # env 형태
```

`make 시작-ship`은 `make ship-arm`이 armed면(`.claude/.ship-armed` 존재) 또한
fail-close한다 — 두 ship 권한은 상호 배타적이다 (ADR 0088 §7).

이 lane은 `protection_verified`가 실시간 `gh api` 쿼리를 통과할 때까지 머지를 거부한다.
이는 올바른 동작이다 — 버그가 아니다. 자율 머지는 merge 토큰, cap store, 직렬화된
promotion 로직이 구현되는 P2.2에서 풀린다.

## P2.0 D-minus가 구축한 것 vs blocked-on-user / 연기

| 구축됨 (P2.0 D-minus) | Blocked-on-user (당신) | P2.2로 연기 |
|---|---|---|
| `ship_manifest.json` **contract 함수** (`_staging_ship.py`의 `write_ship_manifest` / `read_ship_manifest` / `archive_ship_manifest`, 단위 테스트됨) | `autopilot/integration` 생성 + `staging-self-ship-guard` required check를 가진 branch protection | **`agent_loop.py` manifest emission seam** (`_maybe_write_ship_manifest`) — `EXECUTE_SHIP=0`이 `source_sha=HEAD`를 stale하게 만들어 연기 |
| 실시간 `protection_verified` — `staging-self-ship-guard` required check + `allow_force_pushes=false` + `enforce_admins=true`를 확인하는 실제 `gh api` 쿼리, URL 인코딩된 슬래시 브랜치, fail-closed; env-trust 플래그 제거 | Gate-3 실시간 e2e check 1 (가드 파일 PR → required check 실패) | 실시간 `gh pr create` / `gh pr merge` (open_pr/merge는 P2.2-연기 stub) |
| `BIDMATE_SHIP_*` env 격리 — 단일 출처 `scripts/_ship_env.py`, 모든 6개 runner 서브프로세스 lane에 deny-by-prefix; `make 시작-ship`은 루프 sub-make 전에 시크릿 제거 | ADR 0090 Status `proposed → accepted` | 권한 분리 merge 토큰(`BIDMATE_SHIP_MERGE_TOKEN`) + `merge()`의 ambient-credential 제거 |
| `main()` 검증-후-거부 pre-flight harness — manifest 있으면 읽고(idempotent), `--source` 수용; 항상 rc 2 | | T4 self-immutable cap store(`BIDMATE_SHIP_CAP_STORE`) + cross-worktree 공유 lock + 일일 cap 트랜잭션성 |
| ADR 0090 + 이 갱신된 runbook | | `source_sha` → PR head binding(`--match-head-commit`) + 직렬화된 promotion |
| | | Bounded check poll(`BIDMATE_SHIP_CHECK_ATTEMPTS`/`BIDMATE_SHIP_CHECK_INTERVAL_SECONDS`) |
| | | Gate-3 실시간 e2e check 2 (merge 토큰 PUT protection → 403) |
| | | P2.1: `_ship_env.py` + manifest emission seam을 `SELF_IMMUTABLE_PATHS`에 추가 |

## 범위 경계 (scope boundary)

**P2.0 D-minus**는 강제 모델 + manifest contract 정의 레이어다. 루프 manifest emission
seam과 자율 머지 오케스트레이션은 P2.2다. 그 이상의 능력(무제한 self-modify / option 3,
main 자동 promotion, task 자동 생성)은 P2.1–P3이며 각각 자체 ADR과 명시적 승인이
필요하다.

`_ship_env.py`와 manifest emission seam은 P2.1에서 `SELF_IMMUTABLE_PATHS`에 추가돼야
한다 (현재 전체 `SELF_IMMUTABLE_PATHS` 구현과 함께 연기됨).
