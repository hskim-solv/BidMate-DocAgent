# cmux orphan workspace 자동 정리 — 설계 plan (issue #1795)

이 문서는 cmux orphan workspace(탭) 자동 정리 기능의 **설계 핸드오프 plan** 이다.
worktree hygiene 자동화(`docs/plans/worktree-cleanup-automation.md`, ADR 0096)와 **대칭**으로
설계하며, 그 문서의 형식(목표 / 안전 모델 / 영향 파일 / 단계별 구현 / 테스트 계획 / ADR 결정 /
범위 외)을 따른다. 구현은 별도 단계에서 한다 — 이 문서는 설계·근거·테스트 전략·ADR 권고까지만.

---

## 0. 한 줄 요약

worktree + 로컬 브랜치는 ADR 0096 SessionStart 훅이 다음 세션에 자동 정리하지만, 그에 대응하는
**cmux workspace(탭)는 수동으로 닫아야 해서 orphan 이 쌓인다.** 이 작업은 `make cmux-cleanup` /
`make cmux-cleanup-dry-run` 으로 그 정리를 자동화한다. 3가드(① self-skip ② active/focus 보호
③ 현존 worktree 보호)로 살아있는 작업의 workspace 는 절대 닫지 않고, dry-run 을 기본 권장 흐름으로,
실제 close 는 비가역(탭/스크롤백 소멸)이므로 명시적으로만 수행한다.

---

## 1. 배경 / 발견 (왜 이 범위인가)

### 1a. gap 의 정확한 위치

ADR 0096 이 닫은 것: **로컬 worktree + 로컬 브랜치** 정리(SessionStart 자동). 닫지 **못한** 것:
그 worktree 와 1:1 대응하는 **cmux workspace(탭)**. worktree 가 사라져도 탭은 그대로 남아
누적된다. 화면에 죽은 탭이 쌓이고, "동시 worktree → ADR 번호 충돌"의 시각적 사촌 격인 "어느 탭이
살아있는 작업인지 분간 불가" 상태가 된다.

| 축 | 무엇 | 언제(트리거) | 담당 |
|---|---|---|---|
| 로컬 worktree | `git worktree remove` | SessionStart 자동(ADR 0096) | `make worktree-cleanup` |
| 로컬 브랜치 | `git branch -D` | SessionStart 자동(ADR 0096) | `make worktree-cleanup` |
| 원격 브랜치 | `git push origin --delete` | 머지 시 수동 게이트 | ship-pr / ship-arm |
| **cmux workspace(탭)** | **`rpc workspace.close`** | **(이번 작업)** | **`make cmux-cleanup`** |

### 1b. orphan 판정의 핵심 = "workspace 의 cwd 가 현존 worktree 목록에 없다"

worktree hygiene 은 "브랜치가 머지됐나"를 4신호로 판정한다. cmux cleanup 은 그 판정을 **재발명하지
않는다.** 대신 한 단계 뒤에서: workspace 의 cwd(=그 탭의 claude 가 일하던 worktree 경로)가
**현재 `git worktree list` 에 더 이상 없으면** orphan 으로 간주한다.

근거: worktree 가 현존하면(`git worktree list` 에 있으면) 그 작업은 아직 살아있다 → 탭도 살아있어야
한다. worktree 가 사라졌다면(머지 후 ADR 0096 이 정리했다면) 그 탭은 죽은 작업의 잔재 → orphan.
**머지 판정을 cmux cleanup 이 직접 하지 않고 worktree 존재 여부로 위임**하는 게 이 설계의 중심.
worktree hygiene 의 4신호 머지확정을 그대로 신뢰(transitive trust)한다.

### 1c. 스파이크로 검증된 메커니즘 (재조사 불필요 — 사실로 수용)

1. **workspace 목록**: `cmux workspace list --id-format both` → ref(`workspace:N`) + uuid + 제목.
2. **cwd 매핑**: `cmux top --all --processes --format tsv` 가 workspace 별 하위 claude 프로세스
   PID 노출 → `lsof -a -p <pid> -d cwd -Fn | grep '^n'` 로 cwd(worktree 절대경로) 역추적.
   (실증: PID 63967 → `/Users/.../BidMate-DocAgent`)
3. **단일 close**: CLI `workspace-action` 엔 단일 close 없음. **`cmux rpc workspace.close
   '{"workspace_id":"workspace:N"}'`** 가 ref 를 받아 닫는다(실증 완료). `surface.close` 는
   "마지막 surface" 거부로 불가.
4. **self 식별**: `$CMUX_WORKSPACE_ID` env 가 현재 세션 workspace.
5. **active/focus**: `cmux tree` 출력의 `active` / `[selected]` / `◀here` 마커.
6. **soft skip**: `command -v cmux` 없으면(CI/headless) 즉시 skip.

### 1d. cmux 호출 규약 (기존 prior art = `scripts/spawn_track_session.sh`)

기존 cmux 호출 스크립트가 이미 두 함정을 캡처했다 — 그대로 승계:

- **cmux 절대경로**: 서브프로세스/eval 컨텍스트에서 bare `cmux` 는 PATH 에 없다(issue #1767 실증).
  `CMUX_BIN="${CMUX_BIN:-/Applications/cmux.app/Contents/Resources/bin/cmux}"` env 로 두고
  테스트가 stub 으로 override. **단, `command -v cmux` soft-skip(요구사항 6)과 절대경로 default
  의 상호작용에 주의**: §3a 에서 "cmux 탐지" 규칙으로 통합 결정.
- **detect 패턴**: spawn 은 `"$CMUX_BIN" identify --json` 으로 in-cmux 판정. cleanup 도 동일
  detect 후 부재 시 fallback(여기선 spawn 처럼 "수동 안내"가 아니라 그냥 soft-skip exit 0).

---

## 2. 영향 파일

| 파일 | 신규/수정 | 역할 |
|---|---|---|
| `scripts/cmux-cleanup.sh` | **신규** | 본체. workspace 열거 → cwd 매핑 → 3가드 → dry-run/close. soft `exit 0`. |
| `Makefile` | 수정 | `cmux-cleanup` + `cmux-cleanup-dry-run` 타겟 2개 추가(worktree-cleanup 과 대칭 배치). |
| `tests/test_script_cmux_cleanup.py` | **신규** | fake cmux 스텁 + 실제 git worktree temp repo. 3가드 경계 단위 검증. |
| `docs/adr/NNNN-*.md` 또는 `docs/adr/0096-*.md` | (ADR 결정 §6 참조) | ADR 권고에 따라 분기. |
| `docs/plans/cmux-workspace-cleanup.md` | 본 문서 | 설계 기록(구현 PR 에 포함). |

**경로 결정 근거 (스크립트 위치/이름)**: worktree hygiene 은 `.githooks/_pre-push-worktree-hygiene.sh`
에 산다 — pre-push 훅이 source 하기 때문(push 사건에 결합). **cmux cleanup 은 push 와 무관**하다
(탭 정리는 git push 사건과 아무 관계 없음). 그래서 `.githooks/` 가 아니라 **`scripts/`** 가 맞다.
이름은 `_pre-push-` 접두 의미(특정 훅의 sub-hook)가 없으므로 일반 스크립트로 `scripts/cmux-cleanup.sh`.
(언더스코어 접두는 "다른 스크립트가 source 하는 비공개 sub-hook" 관용이므로 붙이지 않음 —
직접 실행되는 `scripts/spawn_track_session.sh` 와 같은 급.)

---

## 3. 단계별 구현

### 3a. `scripts/cmux-cleanup.sh` (신규 — 본체)

**계약 / 골격** (worktree hygiene 과 대칭):

- 첫 줄 `#!/usr/bin/env bash`, `set -u` (NOT `set -e` — soft-warn 은 중간 실패에도 진행).
- arg 파싱 루프: `--dry-run`(=close 호출 안 함, 후보만 출력), `-h|--help`. 알 수 없는 옵션은
  worktree hygiene 처럼 stderr 경고 후 `exit 0`(절대 hard fail 안 함).
- **soft 계약**: 어떤 분기에서도 마지막은 `exit 0`. 세션/푸시를 절대 막지 않음(요구사항).

**Step 1 — cmux 탐지 (soft skip)**:
- `command -v cmux` 와 `CMUX_BIN` 절대경로를 함께 고려. 결정: **`CMUX_BIN` 을 먼저 해석**
  (env override > 절대경로 default > PATH 의 `cmux`), 그 다음 `"$CMUX_BIN" --version`(또는
  spawn 과 동일하게 `identify`) 가 비0이면 → "cmux 없음/headless" 로 보고 즉시 `exit 0`.
- 이렇게 하면 (a) CI/headless 에서 cmux 부재 → 즉시 skip(요구사항 6), (b) 테스트가
  `CMUX_BIN=<stub>` 으로 주입 가능(spawn 테스트와 동일 패턴).
- **경계**: 절대경로 default 파일이 존재하지 않고 PATH 에도 cmux 없으면 → skip. (CI 정상 경로)

**Step 2 — self workspace 식별 (가드 ①)**:
- `self_ws="${CMUX_WORKSPACE_ID:-}"`. 비어있으면(=cmux 밖에서 실행) Step 1 에서 이미 걸러졌거나,
  cmux 안인데 env 미설정인 비정상 — 후자 대비해 self 가 비면 **보수적으로 전부 skip**(아무것도
  안 닫음, exit 0). 안전 우선 원칙(close 는 비가역).

**Step 3 — active/focus workspace 수집 (가드 ②)**:
- `cmux tree` 출력 파싱 → `active` / `[selected]` / `◀here` 마커가 붙은 workspace ref 집합
  `protected_active` 로 모은다. 파싱 실패(빈 출력/포맷 변동) → **보수적으로 전부 skip**(닫을 후보
  0). 마커를 못 읽으면 무엇이 active 인지 모르므로 닫지 않는 게 안전.

**Step 4 — 현존 worktree 목록 수집 (가드 ③의 기준)**:
- `git worktree list --porcelain` → `worktree ` 줄에서 절대경로 집합 `live_worktrees` 수집.
  worktree hygiene 의 porcelain 파싱과 동일 방식. (이 스크립트는 메인 repo 안에서 돌므로 git 사용 가능.)

**Step 5 — workspace → cwd 매핑**:
- `cmux workspace list --id-format both` 로 (ref, uuid, title) 목록.
- `cmux top --all --processes --format tsv` 로 workspace↔하위 PID 매핑.
- 각 PID 에 `lsof -a -p <pid> -d cwd -Fn | grep '^n'` → cwd(절대경로). `^n` 라인에서 선행 `n`
  제거가 cwd.
- workspace 하나에 여러 PID 가능 → cwd 후보가 여럿일 수 있음. **결정 규칙**: 그 workspace 의
  PID 들 중 **하나라도** cwd 가 `live_worktrees` 에 속하면 → "살아있는 worktree 의 탭" → 보호
  (가드 ③, 절대 닫지 않음). 모든 PID 의 cwd 가 `live_worktrees` 에 **없을 때만** orphan 후보.
  (보수적 OR: 살아있을 가능성이 조금이라도 있으면 보호.)
- **경계 — cwd 를 못 구한 workspace**: PID 가 안 잡히거나 lsof 실패로 cwd 불명 → **skip**(닫지
  않음). 정보 부족 시 보수.

**Step 6 — 3가드 종합 후 후보 확정**:
workspace 가 orphan 후보가 되려면 **세 가드를 모두 통과**:
1. ref != `self_ws` (가드 ①: 자기 탭 아님)
2. ref ∉ `protected_active` (가드 ②: active/focus 아님)
3. 그 workspace 의 알려진 모든 cwd 가 `live_worktrees` 에 없음 + cwd 를 최소 1개는 알아냄
   (가드 ③: 현존 worktree 의 탭 아님 + cwd 불명이면 보수 skip)

**Step 7 — dry-run / close 분기**:
- `--dry-run`: 후보 ref + 매핑된 (사라진) cwd 경로를 stderr 에 "would close workspace:N (cwd
  <gone-path>)" 로 출력. **`rpc workspace.close` 호출 안 함.**
- 실제 모드: 각 후보에 `"$CMUX_BIN" rpc workspace.close '{"workspace_id":"<ref>"}'`. 실패해도
  `|| true` 로그 후 계속(soft). 닫은 개수 1줄 요약.
- **JSON 페이로드 escaping**: ref 는 `workspace:N` 형태(영숫자+콜론)이므로 따옴표 안전. 그래도
  `printf` 로 안전하게 조립.

**금지 사항 준수 (CLAUDE.md `## 금지`)**:
- 출력 redirect 는 `/tmp/<고정이름>` 금지 → 임시 파일 필요 시 `mktemp`. (이 스크립트는 임시 파일
  거의 불필요 — 변수/파이프로 처리. 쓰더라도 `mktemp`.)
- 성공 판정은 명령 종료코드/직접 조회로. close 후 검증이 필요하면 `cmux workspace list` 재조회로
  사라졌는지 확인(파일 내용 신뢰 금지).

### 3b. `Makefile`

worktree-cleanup 바로 아래(대칭)에 배치:

```make
cmux-cleanup-dry-run:
	@bash scripts/cmux-cleanup.sh --dry-run

cmux-cleanup:
	@bash scripts/cmux-cleanup.sh
```

- `.PHONY` 라인에 `cmux-cleanup cmux-cleanup-dry-run` 추가(worktree-cleanup 이 있는 줄, line 43 근처).
- **dry-run 을 기본 권장**: 타겟 주석/문서에 "먼저 `make cmux-cleanup-dry-run` 으로 확인하라" 명시.
  close 는 비가역이므로.

### 3c. SessionStart 자동화 여부 — **이번 범위에서 제외(권고)**

ADR 0096 의 worktree 정리는 SessionStart 자동삭제다. cmux cleanup 도 같은 SessionStart 훅에서
부를지 고민했으나 **이번 PR 에서는 수동(make 타겟)만** 제공하기를 권고한다. 근거:

- **비가역성 비대칭**: worktree 삭제는 재생성 가능(`git worktree add` 다시). **cmux workspace
  close 는 탭+스크롤백이 영구 소멸** — 그 세션의 대화 맥락이 사라진다. 자동 트리거의 안전 여유가
  worktree 보다 훨씬 작다.
- **점진 도입**: 먼저 수동 dry-run/close 로 3가드의 실측 정확도를 신뢰한 뒤, 별도 후속 issue 에서
  SessionStart 자동화를 ADR 과 함께 검토하는 게 안전(요구사항 "안전 최우선" 부합).
- 단, 설계는 SessionStart 자동화로 확장 가능하게 둔다(스크립트가 이미 soft+3가드+early-exit).
  후속 자동화는 ADR 0096 패턴(`make` 위임 훅)을 그대로 복제하면 됨 — §6 ADR 결정에서 이 확장 경로를
  명시.

---

## 4. 안전 모델 (3가드 상세 — 경계 조건 포함)

close 는 **비가역**(탭/스크롤백 소멸)이므로, 세 가드는 모두 **"확실히 orphan 일 때만 닫는다"**
방향으로 fail-safe 한다. 정보가 부족하면 항상 **닫지 않는** 쪽(skip)으로 기운다.

### 가드 ① self-skip (`$CMUX_WORKSPACE_ID`)

- **무엇**: 현재 cleanup 을 실행 중인 세션 자신의 workspace 는 절대 후보가 아니다.
- **경계**: `CMUX_WORKSPACE_ID` 가 비어있으면(cmux 밖 또는 env 누락) → **전부 skip**(보수).
  자기를 식별 못 하면 자기를 닫을 위험 → 아무것도 안 닫는다.
- **worktree hygiene 대응**: `self_top`(현재 cwd worktree) self-skip 과 동형.

### 가드 ② active/focus 보호 (`cmux tree` 마커)

- **무엇**: `active` / `[selected]` / `◀here` 마커가 붙은 workspace 는 사용자가 지금 보거나 막
  작업한 탭 → 닫지 않는다.
- **경계 1**: `cmux tree` 출력이 비거나 파싱 실패 → **전부 skip**(active 집합을 모르면 닫지 않음).
- **경계 2**: 마커 문법 변동(cmux 버전업)으로 active 를 일부만 인식하면 → 인식 못 한 active 가
  닫힐 위험. 완화: 마커 정규식을 관대하게(`active|\[selected\]|◀here` 중 하나라도) 매칭하고,
  tree 파싱이 0개 active 를 내면 self 외 전부 skip 으로 떨어지는 보수 분기(위 경계 1)가 안전망.

### 가드 ③ 현존 worktree 보호 (살아있는 worktree 의 탭 절대 보호)

- **무엇**: workspace 의 cwd 가 **현재 `git worktree list` 에 있으면** 그 작업은 살아있음 →
  닫지 않는다. cwd 가 목록에 **없을 때만**(머지돼 ADR 0096 이 정리한 worktree) orphan.
- **경계 1 (가장 중요) — cwd 불명**: workspace 의 PID 를 못 찾거나 lsof 가 cwd 를 못 주면
  → **skip**(닫지 않음). "cwd 모름"을 "orphan"으로 오인하면 살아있는 탭을 죽인다. 정보 부족 =
  보호.
- **경계 2 — 다중 PID/다중 cwd**: 한 workspace 의 여러 자식 PID 의 cwd 가 섞이면(예: 하나는
  worktree A, 다른 하나는 어디 다른 곳) → **OR 보호**: 하나라도 `live_worktrees` 에 속하면 보호.
  전부 없을 때만 orphan.
- **경계 3 — 경로 정규화**: `git worktree list` 경로와 `lsof` cwd 경로의 표기 차이(심볼릭 링크,
  `/private/var` vs `/var` on macOS, 후행 슬래시). **비교 전 양쪽을 정규화**(예: 둘 다 실제 경로
  resolve, trailing slash 제거). 이 정규화 누락이 가장 흔한 false-orphan 원인 → 테스트로 고정.
- **경계 4 — main worktree**: 메인 repo 자체의 workspace 도 cwd 가 `git worktree list` 에
  (main 엔트리로) 있으므로 가드 ③에 의해 자동 보호됨. 별도 처리 불요.

### 가드 종합 진리표

| self | active | cwd 상태 | 결과 |
|---|---|---|---|
| 자기 탭 | — | — | skip (가드 ①) |
| 타 | active | — | skip (가드 ②) |
| 타 | 비active | cwd 불명 | skip (가드 ③ 경계 1) |
| 타 | 비active | cwd ∈ live | skip (가드 ③, 살아있는 worktree) |
| 타 | 비active | 모든 cwd ∉ live | **close 후보** (진짜 orphan) |

핵심: **닫는 칸은 단 하나** — 자기 아님 + active 아님 + cwd 를 알아냈는데 그 worktree 들이 전부
사라진 경우. 나머지 전부 보호.

---

## 5. 테스트 계획 (fake cmux 모킹 설계 — 핵심)

실제 cmux 소켓은 CI 에 없다. 그러므로 **`cmux` 를 fake 스텁으로 PATH/`CMUX_BIN` 주입**하고,
worktree 목록은 **실제 `git worktree` temp repo** 로 만든다(hygiene 테스트와 동일 철학:
git 은 진짜, cmux 는 가짜). 파일: `tests/test_script_cmux_cleanup.py`.

### 5a. fake cmux 스텁 설계 (`_write_fake_cmux`)

기존 두 패턴 결합:
- `tests/test_hook_pre_push_worktree_hygiene.py::_write_fake_gh` — PATH 앞에 stub bindir 추가,
  argv 분기.
- `tests/test_spawn_track_session_script.py::_stub` — `#!/bin/sh` + `$1` subcommand 분기 +
  `chmod +x` + `CMUX_BIN` env 주입.

fake cmux 가 흉내내야 할 4개 표면 + 각 **고정 출력**:

1. **`cmux --version`** (또는 `identify`) → `exit 0` (cmux "있음" 신호; 부재 테스트는 stub 자체를
   PATH 에서 빼거나 `CMUX_BIN` 을 없는 경로로).
2. **`cmux tree`** → active 마커가 든 **고정 텍스트**를 stdout 으로. 테스트별로 어떤 workspace 에
   `active`/`[selected]`/`◀here` 가 붙는지 fixture 로 제어(예: `workspace:1 ◀here`,
   `workspace:2 [selected]`, `workspace:3` (마커 없음)).
3. **`cmux workspace list --id-format both`** → (ref, uuid, title) **고정 TSV/텍스트**. 테스트가
   다루는 workspace 집합 정의.
4. **`cmux top --all --processes --format tsv`** → workspace↔PID **고정 TSV**. PID 는 가짜 정수.
5. **`cmux rpc workspace.close ...`** → **argv 를 캡처 파일에 append**(예:
   `echo "$@" >> "$CMUX_CLOSE_LOG"`) 후 `exit 0`. 이 캡처가 "어떤 ref 를 닫으려 했나"의 단위
   검증 지점. dry-run 테스트는 이 로그가 **비어있어야** 통과.

**lsof 모킹이 핵심 난점**: cwd 매핑은 `lsof -a -p <pid> -d cwd -Fn` 을 부른다. cmux stub 만으로는
부족 — `lsof` 자체도 stub 해야 PID→cwd 를 제어할 수 있다. 두 방안:

- **방안 A (권장) — `lsof` 도 PATH stub**: fake `lsof` 를 같은 bindir 에 두고, `-p <pid>` 의
  pid 에 따라 미리 정한 cwd 를 `n<path>` 형식(lsof `-Fn` 출력)으로 echo. PID→cwd 매핑을 stub 에
  하드코딩하거나 env(예: `LSOF_PID_63967=/path/...`)로 주입. 이렇게 하면 "PID 의 cwd 가 사라진
  worktree" / "현존 worktree" / "cwd 불명(빈 출력)" 세 경우를 정밀 제어.
- **방안 B — 스크립트에 cwd-resolver 간접화 hook**: 스크립트가 cwd 조회를 한 함수
  (`_pid_cwd <pid>`)로 격리하고, 테스트에서 env(`CMUX_CLEANUP_PID_CWD_CMD`)로 그 함수의 백엔드를
  교체. 스크립트에 테스트 전용 seam 이 생기지만 lsof stub 보다 견고(플랫폼 lsof 차이 회피).

→ **결정: 방안 A 우선**(외부 의존 stub 이 spawn/gh stub 과 일관, 스크립트에 테스트 seam 안 남김).
방안 B 는 lsof stub 이 macOS/Linux 출력차로 깨지면 fallback.

**경로 정규화 테스트 고정**: temp repo 의 worktree 경로는 macOS 에서 `/var/folders/...` ↔
`/private/var/folders/...` 심링크가 흔하다. fake lsof 가 일부러 `/private/...` 형태로 cwd 를 주고,
`git worktree list` 는 `/var/...` 로 나오는 케이스를 한 테스트로 만들어 **정규화 누락 시 false
orphan** 회귀를 잡는다(가드 ③ 경계 3).

### 5b. 검증할 동작 (각 가드 → 테스트 1+개)

| # | 테스트 | 셋업 | 기대 |
|---|---|---|---|
| 1 | `test_cmux_absent_soft_skips` | `CMUX_BIN`=없는 경로 + PATH 에 cmux 없음 | exit 0, close 로그 빈 채, "skip" 로그 |
| 2 | `test_self_workspace_never_closed` | `CMUX_WORKSPACE_ID=workspace:2`, ws2 cwd 도 사라진 worktree | exit 0, close 로그에 `workspace:2` **없음** (가드 ①) |
| 3 | `test_self_unset_skips_all` | `CMUX_WORKSPACE_ID` unset, orphan 후보 존재 | exit 0, close 로그 빈 채(보수 skip) |
| 4 | `test_active_marker_protected` | ws1 `◀here`, ws1 cwd 도 사라진 worktree | exit 0, `workspace:1` 닫지 않음 (가드 ②) |
| 5 | `test_selected_marker_protected` | ws3 `[selected]` + cwd gone | exit 0, `workspace:3` 보호 |
| 6 | `test_tree_parse_empty_skips_all` | `cmux tree` 빈 출력 | exit 0, 후보 0(active 모름 → 보수) |
| 7 | `test_live_worktree_tab_protected` | ws4 cwd = 현존 worktree(temp repo 가 실제 add) | exit 0, `workspace:4` 보호 (가드 ③) |
| 8 | `test_orphan_only_closed` | ws5 cwd = 사라진 worktree, self/active 아님 | exit 0, close 로그에 `workspace:5` **정확히** 들어감 |
| 9 | `test_dry_run_never_calls_close` | #8 과 동일 셋업 + `--dry-run` | exit 0, "would close" stderr, **close 로그 빈 채** |
| 10 | `test_cwd_unknown_skips` | ws6 PID 없음(top 에 미등장) 또는 lsof 빈 출력 | exit 0, `workspace:6` 보호 (가드 ③ 경계 1) |
| 11 | `test_multi_pid_or_protection` | ws7 두 PID: 하나 cwd∈live, 하나 cwd gone | exit 0, `workspace:7` 보호 (OR 규칙) |
| 12 | `test_path_normalization_no_false_orphan` | live worktree 가 `/var/...`, lsof cwd `/private/var/...` | exit 0, 해당 ws 보호(정규화 동작) |
| 13 | `test_soft_exit_zero_on_internal_error` | rpc close stub 이 exit 1 반환 | 스크립트는 여전히 exit 0(soft) |
| 14 | `test_unknown_flag_is_soft` | `scripts/cmux-cleanup.sh --bogus` | exit 0, stderr 경고(hard fail 아님) |

**정적 가드(소스 스캔)** — spawn 테스트의 `TestSpawnTrackStatic` 패턴 차용:
- `set -u` 존재, `set -e` **부재**(soft).
- `exit 0` 가 최종 분기에 존재.
- `CMUX_WORKSPACE_ID` self-skip 토큰 존재.
- `workspace.close` 호출이 dry-run 분기 **밖**에만 있음(grep 으로 dry-run 가드 확인).
- `/tmp/` 고정경로 redirect **부재**(CLAUDE.md 금지), `mktemp` 사용 시에만 임시파일.

### 5c. temp repo 빌더 (hygiene 테스트 재사용)

`tests/test_hook_pre_push_worktree_hygiene.py` 의 `setUp`/`_add_worktree`/`tearDown` 패턴 복제:
- `git init` temp repo + main 커밋.
- `_add_worktree(name, branch)` 로 **현존** worktree 생성(가드 ③ "live" 케이스).
- "사라진 worktree" 케이스는 worktree 를 add 했다가 `git worktree remove` 로 지워, fake lsof 가
  그 (이제 없는) 경로를 cwd 로 반환하게 함 → "cwd 가 live 목록에 없음" 재현.
- `tearDown` 에서 `git worktree prune` + temp 삭제.

---

## 6. ADR 결정 (권고만 — 번호 예약/작성은 사용자)

**후보**: (a) ADR 0096 확장 / (b) 신규 ADR / (c) ADR 불필요.

### 권고: **(b) 신규 ADR** — 단, 이번 PR 이 "수동 make 타겟"만 출하한다면 **약(weak) 권고**,
SessionStart 자동화까지 포함한다면 **강(strong) 권고**.

근거:

- **ADR 임계값(CLAUDE.md)**: "새 측정 표면 / 자동화 표면 도입" + "load-bearing 결정 제거·교체"가
  기준. cmux workspace 정리는 **새 자동화 표면**(reviewer 가 의존할 비가역 파괴 op 의 계약 — 무엇을
  닫나/언제/3가드)이다. 특히 SessionStart 자동화를 붙이는 순간 ADR 0096 과 동급의 "자동 파괴적
  트리거"가 되어 ADR 이 **필수**.
- **(a) 0096 확장을 기각하는 이유**: ADR 0096 의 제목·Decision·Verification(verifies-key 마커)은
  **로컬 worktree/브랜치 정리에 한정**된 계약이다. cmux 는 (i) 판정 메커니즘이 다르고(머지 4신호가
  아니라 "현존 worktree 부재"로 위임), (ii) 비가역성 등급이 다르며(탭/스크롤백 영구 소멸 vs
  재생성 가능 worktree), (iii) 트리거 시점 결정이 독립적(이번 PR 은 수동 권고). 한 ADR 에 섞으면
  0096 의 깔끔한 단일 결정이 흐려지고 verifies-key 마커가 두 표면으로 비대해진다. CLAUDE.md `## 금지`
  의 "ADR 파일 삭제/이름변경 금지, Status 로 Superseded 표시"와도 부합 — 0096 은 그대로 두고 새
  결정은 새 파일.
- **(c) 불필요를 기각하는 이유**: "0096 의 구현 세부"로 보기엔 표면이 명확히 다르다(다른 메커니즘·
  다른 트리거·다른 비가역성). reviewer 가 "왜 머지 판정 안 하고 worktree 존재로 위임하나",
  "왜 비가역인데 자동 아닌가" 같은 결정을 나중에 추적하려면 ADR 이 있어야 한다.

### 신규 ADR 에 담을 결정 (작성 시 참고)

1. **orphan 판정 = worktree 부재 위임**(머지 4신호 재발명 안 함; worktree hygiene 신뢰).
2. **3가드**(self-skip / active 보호 / 현존 worktree 보호) + **모든 정보부족은 skip(보수)**.
3. **비가역성 때문에 이번 범위는 수동(make) 만; dry-run 기본 권장**. SessionStart 자동화는 후속
   issue + (필요시) 본 ADR 의 후속 결정 / Consequences 에 확장 경로 명시.
4. **원격/worktree/브랜치는 범위 밖**(ADR 0096 / ship-pr / ship-arm 담당). 이 결정은 **cmux
   workspace 만** 건드린다.
5. **스크립트 위치 = `scripts/`**(push 무관, `.githooks/` 아님) + soft `exit 0` 계약.

### ADR 작성 절차 (사용자가 진행 — CLAUDE.md 강제)

- 번호 예약: `ls docs/adr/` + `gh pr list --search "ADR" --state open` 양쪽 확인. 현재 최대
  0096 → 다음 후보 **0097**(`scripts/_governance.py --next-adr-number` 도 0097 확인). 단 동시
  worktree 충돌 빈발 → 작성 직전 재확인 필수.
- 형식: Status / Date / Deciders / Related([ADR 0096], [ADR 0007]) / Issue(#1795) / Context /
  Decision / Drivers / Alternatives considered / Consequences / **Verification**(verifies-key
  마커 — `scripts/cmux-cleanup.sh:workspace.close`, `tests/test_script_cmux_cleanup.py:...`).
- `scripts/_governance.py --check-adr-readme-parity` 통과 + `docs/adr/README.md` 인덱스 추가.

---

## 7. 범위 외 (non-goals)

- **원격 브랜치 / worktree / 로컬 브랜치 정리** — ADR 0096 / ship-pr / ship-arm 담당. 이 작업은
  cmux workspace 만.
- **SessionStart 자동화** — 이번 PR 권고는 수동 make 타겟. 자동화는 별도 후속 issue(비가역성
  점진 도입).
- **머지 판정 재발명** — worktree 존재 여부로 위임. 4신호 머지확정을 다시 구현하지 않음.
- **`surface.close` 경유 정리** — "마지막 surface" 거부로 불가(스파이크 확인). `rpc
  workspace.close` 만 사용.
- **cmux 버전 협상 / 마커 문법 자동 적응** — 마커 정규식은 현재 cmux 출력 기준. 변동 시 보수
  skip 으로 안전, 적응은 후속.
- **다른 worktree 의 파일 수정** — 이 worktree 안에서만 작업(작업 지시 준수).

---

## 8. 리스크 / 미해결

1. **lsof cwd 매핑의 플랫폼/권한 취약성** (최상위 리스크): `lsof -a -p <pid> -d cwd -Fn` 가
   권한/플랫폼(특히 비-macOS, sandbox)에서 빈 출력이면 **모든 cwd 불명 → 전부 skip** = 기능이
   조용히 무력화. 안전엔 문제없으나(아무것도 안 닫음) "왜 안 닫나" 혼란 가능. 완화: cwd 불명 시
   진단 로그("cwd 불명으로 skip") 출력.
2. **경로 정규화 false-orphan** (안전 직결): `/private/var` ↔ `/var` 심링크, trailing slash 를
   정규화 안 하면 **살아있는 worktree 를 orphan 으로 오인** → 비가역 close. 가드 ③ 경계 3 +
   테스트 #12 로 고정 필수. dry-run 기본 권장이 추가 안전망.
3. **cmux 출력 포맷 변동**(`tree` 마커 / `top` TSV / `workspace list`): cmux 버전업으로 파싱이
   깨지면 active 오인식 위험. 완화: 파싱 실패·빈 출력은 전부 보수 skip 으로 떨어지게 설계(가드 ②
   경계 1) + 정적/behavioral 테스트로 현재 포맷 고정. 단 테스트는 **stub 의 고정 출력**을 검증하므로
   실제 cmux 포맷 drift 는 못 잡음 — 이건 수동 dry-run 운영으로 보완(한계 명시).

---

## 9. 권장 구현 순서

1. 본 plan 을 `docs/plans/cmux-workspace-cleanup.md` 로 커밋(구현 PR 에 포함, 설계 기록).
2. `scripts/cmux-cleanup.sh` 작성(§3a: soft 골격 → cmux 탐지 → 3가드 → dry-run/close).
3. `tests/test_script_cmux_cleanup.py` 작성(§5: fake cmux + fake lsof stub + temp git worktree).
   가드별 14개 + 정적 가드. **테스트가 close 로그를 캡처**하는 게 close 비호출 검증의 핵심.
4. `Makefile` 에 `cmux-cleanup` / `cmux-cleanup-dry-run` + `.PHONY` 추가(worktree-cleanup 대칭).
5. 로컬 게이트: `python3 -m pytest -q tests/test_script_cmux_cleanup.py` + `ruff check .` +
   `bash scripts/cmux-cleanup.sh --dry-run`(실제 cmux 환경에서 후보 출력 sanity).
6. ADR 0097(권고 (b)) 번호 예약 후 작성(§6) — **사용자 진행**. README 인덱스 + verifies-key.
7. `/ship-pr`(issue #1795) — ADR 예약·stacked 감사·게이트.

> **참고**: §3c 권고대로 이번 PR 이 수동 make 타겟만 출하하면, ADR 은 "수동 + dry-run 기본 +
> SessionStart 확장 경로 명시" 결정으로 가볍게 쓸 수 있다. SessionStart 자동화를 같은 PR 에
> 넣기로 사용자가 바꾸면 ADR 은 ADR 0096 급 "자동 파괴 트리거" 강도가 되며 `.claude/settings.json`
> SessionStart 훅 + 별도 훅 스크립트(`scripts/claude-hooks/sessionstart-cmux-hygiene.sh`)가
> 영향 파일에 추가된다.
