# Staging self-ship lane — 운영자 runbook (P1, ADR 0088)

`make 시작-ship` 은 자율 루프가 자기 작업을 장수(long-lived) `autopilot/integration`
브랜치로 머지하게 해주는 **opt-in** lane 이다 (`main` 직접 머지·force-push 절대 안 함).
byte-identical `make 시작` 루프(`EXECUTE_SHIP=0`, 불변)에 격리(isolated) 모듈
`scripts/_staging_ship.py` 를 post step 으로 합성하며, `scripts/agent_loop.py` 는
건드리지 않는다.

## 강제(enforcement) 모델 — 먼저 읽을 것

`scripts/_staging_ship.py` 의 in-process 가드(force-push / staging-boundary /
data-boundary / kill-switch / cap)는 **best-effort 1차 fast-fail 일 뿐**이다.
workspace-write runner 는 이를 우회할 수 있다. **권위(authority)** 는 루프가 권한을
갖지 못하는 외부 영역에 있다:

1. `autopilot/integration` 에 대한 GitHub **branch protection** — `staging-self-ship-guard`
   워크플로를 **required status check** 로 등록.
2. branch protection 을 우회할 수 없는 **권한분리 머지 토큰(permission-separated merge token)**.

이 둘이 검증되기 전까지 `scripts/_staging_ship.py` 는 **fail closed**
(`blocked-on-user`)로 ship 을 거부한다. 게이트 3 을 위장 통과시키지 않는다.

## 사전조건(prerequisites) — 운영자 GitHub-admin 작업 (blocked-on-user)

> ⚠️ 아래 단계는 GitHub admin 권한 + 토큰/App 생성이 필요하다. 에이전트/ralph 가
> 수행하지 **않는다**(에이전트는 보호 브랜치나 scoped 토큰을 발급할 권한이 없다).
> 직접 실행하라.

### 1. 보호된(protected) integration 브랜치 생성

먼저 `main` 을 그대로 새 원격 ref 로 push 한다. **`--no-verify` 필수** — `autopilot/integration`
은 issue 없는 구조적 타겟이라 ADR 0007 branch-name 체크에 걸리며, 이 면제는 P3 lane
설계 시 정식화 예정(현재 deferred, issue #1696). 인라인 주석을 셸에 붙여넣지 말 것.

```bash
git push --no-verify origin origin/main:refs/heads/autopilot/integration
```

branch protection 은 nested object(`required_status_checks`)라 `-f/-F` 플래그로는
타입(boolean/null)이 깨진다(`-f` 는 문자열 → `"true" is not a boolean` 422). **JSON body
(`--input -`)로 보낸다.** `{owner}/{repo}` 는 gh 가 현재 repo 로 치환한다.

```bash
gh api -X PUT repos/{owner}/{repo}/branches/autopilot/integration/protection --input - <<'JSON'
{
  "required_status_checks": {"strict": true, "checks": [{"context": "staging-self-ship-guard"}]},
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

확인: `gh api repos/{owner}/{repo}/branches/autopilot/integration/protection --jq '{strict: .required_status_checks.strict, force: .allow_force_pushes}'`

### 2. 권한분리 머지 토큰(permission-separated merge token) 발급
- 이 저장소로 scope 를 한정한 **fine-grained PAT**(또는 GitHub App installation token)을
  생성하되 **Contents: read/write + Pull requests: read/write** 만 부여하고
  **Administration 은 제외**한다. branch protection 을 수정할 수 없어야 한다.
- 이를 루프의 머지 자격증명으로 보관한다(루프가 쓸 수 있는 workspace 바깥에).

### 3. 게이트 3 통과 후에만 검증 플래그를 켠다
```bash
export BIDMATE_SHIP_PROTECTION_VERIFIED=1
export BIDMATE_SHIP_TOKEN_SEPARATED=1
```

## 게이트 3 — 라이브 e2e (mock 불가, 설정 후 1회 실행)

아래 두 적대적(adversarial) 검사는 외부 권위가 실재함을 증명한다. mock 으로 대체할 수
없다 — 실제 GitHub 서버 상태를 행사하기 때문이다.

1. **가드 파일 변경이 차단된다.** `autopilot/integration` 으로 들어가는 PR 에서
   `scripts/_staging_ship.py` 를 body 에 `[constitutional-change-ack]` 마커 *없이* 수정해
   연다. 기대: `staging-self-ship-guard` required check 가 **실패**하고 머지가 차단된다.
2. **머지 토큰이 protection 을 끌 수 없다.** 권한분리 토큰으로 동일 protection 을 다시
   PUT 해본다(멱등 — 권한만 검사, 성공해도 같은 protection 재적용이라 무해):
   ```bash
   GH_TOKEN=$MERGE_TOKEN gh api -X PUT repos/{owner}/{repo}/branches/autopilot/integration/protection --input - <<'JSON'
   {
     "required_status_checks": {"strict": true, "checks": [{"context": "staging-self-ship-guard"}]},
     "enforce_admins": true,
     "required_pull_request_reviews": null,
     "restrictions": null,
     "allow_force_pushes": false,
     "allow_deletions": false
   }
   JSON
   ```
   기대: **HTTP 403**(토큰이 Administration 권한 없음). 200 이면 토큰이 너무 넓다 — 재발급.

두 검사가 모두 기대대로 동작할 때에만 외부 강제(external enforcement)가 검증된 것이다.

## lane 실행

```bash
# 사전조건 + 게이트 3 가 끝나기 전까지는 fail closed (blocked-on-user, exit 2):
make 시작-ship

# kill-switch (즉시 발동): 파일 생성 또는 env var 설정
touch .omc/state/KILL                 # 파일 형태
export BIDMATE_SHIP_KILL_SWITCH=1     # env 형태
```

`make 시작-ship` 은 `make ship-arm` 이 armed 상태(`.claude/.ship-armed` 존재)이면
fail-close 한다 — 두 ship 권위자는 상호배제(mutually exclusive)다 (ADR 0088 §7).

## P1(ralph)이 만든 것 vs blocked-on-user

| 로컬에서 만든 것 (이 PR 묶음) | Blocked-on-user (당신 차례) |
|---|---|
| `_ship_payload_guard.py` 자유텍스트 데이터경계 스캐너 + 테스트 | `autopilot/integration` + branch protection 생성 |
| `_staging_ship.py` 가드 + breaker(T1/T4) + lane(CI-green 게이트, fail-closed) + 테스트 | 권한분리 머지 토큰 발급 |
| `시작-ship` Makefile 타겟 (`시작` byte-identical) | 게이트 3 라이브 e2e (위 두 검사) |
| `staging-self-ship-guard` CI 워크플로 (required-check 후보) | `BIDMATE_SHIP_*` 검증 플래그 켜기 |
| 이 runbook | |

이 lane 은 GitHub-admin 단계를 끝낼 때까지 의도적으로 ship 을 거부한다 — 그 거부는
버그가 아니라 올바른 동작이다.

## 범위 경계(scope boundary)

이것은 **P1 한정**이다: 외부 강제를 갖춘 단일 staging-ship 데모. spec 의 더 공격적인
능력들(무제한 self-modify / 옵션 3, main 자동 승격, 무한 모드, task 자동생성, 멀티워커
조율)은 P2/P3 이며 각각 별도 ADR(G1-G4) + 명시 승인이 필요하다. consensus plan
`.omc/plans/make-sijak-full-automation-consensus.md` 참조 (로컬 planning 아티팩트,
gitignore — 미커밋).
