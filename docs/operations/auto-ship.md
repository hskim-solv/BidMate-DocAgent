# Auto-ship 파이프라인

auto-ship 파이프라인은 Stop-hook 가 구동하는 시퀀스로, feature 브랜치를
로컬 커밋에서 `main` 의 squash-merge 된 PR 까지 한 번의 ack 으로
가져간다: `make ship-arm`. 이슈와 브랜치 생성까지 포함한 시작점은
`make ship-start TITLE="..."` 이다. 모든 ship-arm 사이클은
단발성(single-shot) — 성공이든 실패든 트리거를 해제(disarm)한다.

이 페이지는 운영 계약을 문서화한다: 어떻게 arm 하는지, 각 게이트 / 스테이지가
무엇을 강제하는지, 안전망(safety net)이 어디에 있는지, 그리고 우회할 때
반드시 지켜야 하는 규율 규칙(특히 stacked-PR 게이트)이 무엇인지.
구현은
[`scripts/claude-hooks/stop-ship.sh`](../../scripts/claude-hooks/stop-ship.sh)
(Stop hook 진입점)과
[`scripts/claude-hooks/_ship_pr_body.py`](../../scripts/claude-hooks/_ship_pr_body.py)
(PR body 생성기),
[`scripts/claude-hooks/_ship_start.py`](../../scripts/claude-hooks/_ship_start.py)
(issue-linked branch 생성기), 그리고
[`scripts/claude-hooks/_ship_review_gate.py`](../../scripts/claude-hooks/_ship_review_gate.py)
(merge 전 review gate)에 있다. 등록 위치:
[`.claude/settings.json`](../../.claude/settings.json) 의 `Stop` hook.

## Start: `make ship-start`

새 작업은 먼저 이슈와 ADR 0007 브랜치를 만든다:

```bash
make ship-start TITLE="자동화 범위 설명" TYPE=chore SLUG=short-slug
```

동작:

1. dirty worktree 를 거부한다. 이 명령은 편집 전 front door 다.
2. `gh issue create` 로 이슈를 만든다.
3. 제목 또는 `SLUG` 로 `<type>/issue-<N>-<slug>` 브랜치를 만든다.
4. `origin/main` 을 fetch 한 뒤 새 브랜치로 switch 한다.

그 다음 파일을 수정하고 focused test 를 실행한 뒤 `make ship-arm` 한다.

## Arming: `make ship-arm`

이 Makefile 타깃은 [`.claude/.ship-armed`](../Makefile)(JSON
상태 파일)를 쓰고 종료한다; 실제 파이프라인은 다음 Claude Stop
이벤트에서 실행된다. 노브(env-var override):

| Var | Default | Effect |
|---|---|---|
| `TTL` | `2h` | Arm 수명. `30m`, `90m`, `1d` 허용. 만료 → 조용히 disarm. |
| `REAL_EVAL` | `auto` | §5b cascade 모드. `skip` 은 escape 강제; `async` 는 지연; `auto` 는 delta-or-full 실행. |
| `DRAFT` | `false` | PR 을 draft 로 연다. |
| `DRY_RUN` | `0` | `1` 일 때, 모든 mutating 명령이 실행 대신 `.claude/.ship-dryrun.log` 로 echo 된다. |
| `CROSS_OWNER` | _(empty)_ | `ack` 은 multi-agent lock 검사([`docs/multi-agent-ownership.md`](../multi-agent-ownership.md))를 우회한다. |
| `STACKED` | _(empty)_ | `ack` 은 heterogeneous-prefix 거부를 우회한다(아래 [Stacked-PR 규율](#stacked-pr-discipline-tier-7) 참조). |
| `BIDMATE_DESKTOP_REPO` | `/Users/hskim/Desktop/projects/BidMate-DocAgent` | Stage 5 merge 직후 fast-forward 동기화할 canonical Desktop checkout. |

`make ship-disarm` 은 arm 파일과 pid 파일을 제거한다. `make ship-status`
는 사람이 읽을 수 있는 요약을 출력한다.
[`Makefile:289-339`](../Makefile) 와
[`scripts/claude-hooks/_ship_arm.py`](../../scripts/claude-hooks/_ship_arm.py) 참조.

`make ship-arm` 은 승인된 end-to-end shipping 경로다. Agent-loop 의
`auto-ship-prepare` / `auto-ship-plan` 은 이 경로를 준비·설명하는 명시적
planning command 이며, local Stop hook 의 lightweight status refresh 는 이
auto-ship 준비 리포트를 자동 갱신하지 않는다. 개별 push / PR 생성 / 머지 /
브랜치 삭제가 필요할 때만 `human-gated-exec` 를 수동 fallback 으로 사용한다.

## 파이프라인 개요

```
make ship-start TITLE="..." TYPE=chore  (issue + branch)
    ↓
edit + local verification
    ↓
make ship-arm  (writes .claude/.ship-armed)
    ↓
Claude Stop event  →  scripts/claude-hooks/stop-ship.sh fires
    ↓
Gate 0 — 8 pre-checks (silent exit on any failure)
    ↓
Stage 1: commit   (private-path filter → multi-agent lock → tier-7 prefix gate → bash scripts/test.sh → git commit)
Stage 2: push     (ADR 0007 branch check → git push)
Stage 3: PR       (_ship_pr_body.py → §5b cascade → gh pr create)
Stage 4: CI/review gate  (gh pr checks --watch → requested-changes/unresolved-thread gate)
Stage 5: merge    (gh pr merge --squash --admin → git push origin --delete <branch> → checkout main → disarm)
```

단발성 disarm: 성공은 Stage 5 끝에서 arm 파일을 삭제한다;
실패는 어느 스테이지에서든 `abort_disarm` 으로 삭제한다. 파이프라인은
또 다른 명시적 `make ship-arm` 으로만 재무장(re-arm)된다.

## Gate 0 — 여덟 개의 조용한 사전 검사

Stop hook 은 모든 Claude 턴마다 발화한다. 지배적 케이스는 no-op
(`.claude/.ship-armed` 부재)이다. 각 게이트는 실패 시 조용히 종료하므로
무장되지 않은 턴은 100ms 미만으로 유지된다:

| # | Gate | Behaviour | Source |
|---|---|---|---|
| 1 | armed 파일 존재 | 파일 없음 → `exit 0` | [`stop-ship.sh:39-41`](../../scripts/claude-hooks/stop-ship.sh) |
| 2 | armed 파일 파싱 | malformed JSON → 조용히 disarm | [`stop-ship.sh:43-69`](../../scripts/claude-hooks/stop-ship.sh) |
| 3 | 만료되지 않음 | TTL 초과 → 조용히 disarm | [`stop-ship.sh:71-81`](../../scripts/claude-hooks/stop-ship.sh) |
| 4 | 브랜치가 arm 과 일치 | 브랜치 전환됨 → 조용히 disarm | [`stop-ship.sh:83-91`](../../scripts/claude-hooks/stop-ship.sh) |
| 5 | 보호 브랜치가 아님 | main/master/develop/HEAD/release/* → **hard abort** (tier-3 firewall) | [`stop-ship.sh:93-98`](../../scripts/claude-hooks/stop-ship.sh) |
| 6 | ship 할 작업이 있음 | clean tree + unpushed 커밋 없음 → 조용히 exit | [`stop-ship.sh:100-108`](../../scripts/claude-hooks/stop-ship.sh) |
| 7 | 진행 중인 git transition 없음 | merge / rebase / cherry-pick / revert 감지 → 조용히 exit | [`stop-ship.sh:110-119`](../../scripts/claude-hooks/stop-ship.sh) |
| 8 | live pid 없음 | 이전 실행이 아직 살아있음 → 조용히 exit | [`stop-ship.sh:121-131`](../../scripts/claude-hooks/stop-ship.sh) |

"조용한(silent)" 처리가 중요하다: 한 번 arm 하고 무관한 브랜치에서
계속 작업하는 기여자는 실수로 ship 을 트리거하지 않으며 — 경고도
받지 않는데, arm 이 사실상 자가 정리(self-clean)되었기 때문이다.

## Stage 1–5

### Stage 1 — commit ([`stop-ship.sh:183-279`](../../scripts/claude-hooks/stop-ship.sh))

1. **private 경로 필터링** — staging 후보 집합에서 제외:
   `data/files/`, `data/data_list.{csv,xlsx}`, `eval/*.local.yaml`,
   `reports/real*/`. pre-commit hook (`.githooks/pre-commit`)이
   2차 게이트다; 이 필터는 그것들을 제안하는 것을 막을 뿐이다.
   제외된 untracked private-path 파일은
   [`_ship_private_preserve.py`](../../scripts/claude-hooks/_ship_private_preserve.py)
   가 `SHIP_PRIVATE_PRESERVE_ROOT` 로 지정한 canonical local checkout 의
   같은 상대 경로로 이동한다. 이 변수가 없으면 이동하지 않고 skip한다.
   tracked 수정 파일은 삭제 위험 때문에 이동하지 않는다.
2. [`_ship_lock_check.py`](../../scripts/claude-hooks/_ship_lock_check.py)
   를 통한 **multi-agent lock 검사**.
   cross-owner 편집은 `CROSS_OWNER=ack` 가 아니면 abort 한다.
3. **Tier-7 heterogeneous-prefix 게이트** — [Stacked-PR 규율](#stacked-pr-discipline-tier-7) 참조.
4. `bash scripts/test.sh` 실행; PR body §4 용으로 요약을
   `/tmp/ship-test-summary.txt` 에 캐시한다.
5. 살아남은 각 파일을 `git add`; 생성된 subject
   `<type>: <issue title> (#<N>)` 로 커밋하며, body 에는 `Closes #<N>` 과
   Co-Authored-By footer 를 담는다.

### Stage 2 — push ([`stop-ship.sh:285-297`](../../scripts/claude-hooks/stop-ship.sh))

`python3 scripts/check_branch_and_issue.py --branch <X> --check-issue`
(ADR 0007 + issue-exists 검사)를 실행한 뒤 `git push` (upstream 이
아직 없으면 `-u` 와 함께)한다.

### Stage 3 — PR create ([`stop-ship.sh:303-346`](../../scripts/claude-hooks/stop-ship.sh))

멱등(idempotent): 이미 head 브랜치를 타깃하는 PR 이 있으면 재사용한다.
그렇지 않으면
[`_ship_pr_body.py`](../../scripts/claude-hooks/_ship_pr_body.py) 를 호출해
body 를 생성하고(template §1–§7, 아래 §5b cascade 포함),
`gh pr create --base main --head <branch> --title ... --body-file ...`
(추가로 `DRAFT=true` 이면 `--draft`)을 호출한다. PR title 은 squash-merge
커밋 subject 이므로, `main` 에 머지된 커밋은 title 을 첫 줄로 하여
landing 된다.

### Stage 4 — CI wait + review gate ([`stop-ship.sh`](../../scripts/claude-hooks/stop-ship.sh))

`timeout 1800 gh pr checks <N> --watch --interval 30`. 타임아웃 시
(rc 124): PR 코멘트를 달고 abort 하며, **PR 을 열린 채로 둔다**. 0 이 아닌
rc 시: comment + abort. 파이프라인은 red 상태에서 절대 머지하지 않는다.

CI 가 green 이면
[`_ship_review_gate.py`](../../scripts/claude-hooks/_ship_review_gate.py) 가
merge 직전에 다음을 fail-closed 로 검사한다:

- PR 이 open 이고 draft 가 아님.
- `reviewDecision` 이 `CHANGES_REQUESTED` 가 아님.
- unresolved 이고 outdated 가 아닌 review thread 가 없음.

review gate 가 막으면 PR 을 열린 채로 두고 disarm 한다. 그 상태에서 Codex 의
GitHub review-fix 루프를 실행해 코멘트를 처리하고, fix 커밋을 push 한 뒤
다시 `make ship-arm` 한다. Shell hook 은 reviewer 코멘트를 임의로 수정하지
않는다; patch 선택은 코드 맥락과 reviewer 의도를 읽어야 하므로 agent 판단
단계로 남긴다.

### Stage 5 — squash-merge ([`stop-ship.sh:374-424`](../../scripts/claude-hooks/stop-ship.sh))

`gh pr merge <N> --squash --admin` (의도적으로 `--delete-branch` **없음** — issue #1283).
머지 후 상태가 `MERGED` 인지 검증한다(아니면 검사를 위해 arm 파일을 그대로 둔다).
그런 다음 [`scripts/sync_desktop_main.py`](../../scripts/sync_desktop_main.py)로
canonical Desktop checkout의 `main`을 `origin/main`에 맞게 fast-forward 한다.
이 동기화는 fail-soft다: 대상이 없거나 dirty/divergent 상태면 로그만 남기고
merge 성공을 되돌리지 않는다. 이어서 `git push origin --delete <branch>` 로
**원격 브랜치를 삭제**하고, `git checkout main && git pull --ff-only`, 로컬 브랜치
삭제, `S5_OK` 라인을 `.claude/.ship-history.log` 에 기록, arm 파일 제거.

`--delete-branch` 를 쓰지 않는 이유: gh 의 `--delete-branch` 는 원격 삭제를
로컬 checkout-to-default + 로컬 브랜치 삭제와 한 명령에 묶는다. 이 repo 는
상시 20~30 worktree 가동이라 `main` 이 다른 worktree 에 체크아웃돼 있고,
gh 의 로컬 checkout 이 `fatal: 'main' is already checked out` 로 실패하면서
**원격 삭제 전에 명령 전체를 abort** 한다 — 서버 머지는 성공하지만 원격
브랜치가 남는다. `git push origin --delete` 는 순수 원격 연산이라 로컬
체크아웃이 필요 없어 worktree 와 무관하게 동작한다 (memory
`feedback_merge_admin_gate` §2).

**Worktree 자동 정리 (issue #520):** 파이프라인이
linked worktree 에서 실행되었다면(즉 `git rev-parse --git-dir` 가 `/worktrees/` 를 포함),
Stage 5 는 disarm 후 `git worktree remove --force <path>` 를 호출한다.
이는 머지된 worktree 가 누적되어 세션당 base-load 비용을 부풀리는 것을
방지한다. 실패는 non-blocking — 경고가 로깅되고 호출자가 수동으로
정리해야 한다(`git worktree prune`).

<a id="stacked-pr-discipline-tier-7"></a>

## Stacked-PR 규율 (tier 7)

[`CLAUDE.md`](../../CLAUDE.md) 의 "one PR, one concern" 규칙은 브랜치의
고유 커밋 prefix 개수를 세어 Stage 1 에서 기계적으로 강제된다:

```bash
# scripts/claude-hooks/stop-ship.sh:221-227
if [[ "$ARM_STACKED" != "ack" ]]; then
  local prefixes
  prefixes=$(git log "@{upstream}..HEAD" --format=%s 2>/dev/null | \
             sed -E 's/^([a-z]+)(\(.*\))?:.*/\1/' | sort -u | wc -l | tr -d ' ')
  if [[ "${prefixes:-0}" -gt 1 ]]; then
    abort_disarm "s1" "heterogeneous commit prefixes (one PR per concern); bypass with STACKED=ack"
  fi
fi
```

브랜치가 ≥2 개의 구별되는 conventional prefix(예: `feat:` 하나와
`fix:` 하나)를 가진 커밋을 지니면, 파이프라인은 거부한다. 우회는
명시적이며 감사(audit)된다:

```
make ship-arm STACKED=ack
```

`STACKED=ack` 가 사이클에 속하는 경우:

- **정당한 stacked 작업.** downstream 의 fix 나 follow-up 이 아직 머지되지
  않은 upstream feature 에 의존한다; fix 를 `main` 위로 rebase 하는 것이
  불가능하거나 diff 를 churn 시킬 것이다. 예:
  커밋 `127a9a1` (`feat(eval): close ADR 0019 with BGE-M3 Phase 1.3
  measurement + ADR 0021 (#392)`)은 `eval` measurement closure 와
  새 ADR 을 함께 묶었다 — 하나의 논리적 "close out ADR 0019" concern,
  두 개의 prefix.
- **두 이슈 종료.** 단일 PR 이 둘 이상의 관련 이슈를 정당하게 닫고
  커밋 히스토리가 이를 반영한다.

`STACKED=ack` 가 **틀린** 경우:

- 리뷰 중 "온 김에(while I'm here)" 정리. follow-up 이슈 + 브랜치를 연다.
- 무관한 typo + feature. 두 PR 로 분할(저렴하다).
- 두 번 push 하기 싫어서 하는 선제적 묶음. tier-7
  게이트는 바로 이를 표면화하기 위해 존재한다.

우회는 `.claude/.ship-armed` 에 로깅되고
`make ship-status` 가 출력하므로, 감사 추적(audit trail)이 사이클을
넘어 보존된다.

## §5b real-data delta cascade

[`_ship_pr_body.py:126-162`](../../scripts/claude-hooks/_ship_pr_body.py)
의 `render_5b()` 는 PR body 의 "### 5b. Real-data delta" 아래에 무엇을
쓸지 결정한다. 결정 트리:

| Condition | Output |
|---|---|
| load-bearing 경로가 변경되지 않음 | `No behavior change in retrieval / verifier path. (no load-bearing path changed)` |
| `REAL_EVAL=skip` | 동일 escape, suffix `(REAL_EVAL=skip)` |
| Real-eval 실행 불가 (private `data/files/` 또는 `eval/real_config.local.yaml` 부재) | 사유와 함께 escape |
| `REAL_EVAL=async` | escape + `<!-- real-eval-pending -->` |
| 캐시 유효 (`provenance.git_commit` 이후 load-bearing diff 없음) | `make real-eval-delta` (120 s timeout) |
| 캐시 stale | `make real-eval` (1800 s) → `make real-eval-delta` |

PR body 는 CI 게이트
(`scripts/check_branch_and_issue.py --check-5b` regex:
`FIVE_B_TABLE_RE`, `FIVE_B_ESCAPE_RE`)에 대해 round-trip 검증된다;
생성기는 CI 가 거부할 body 를 emit 하기를 거부한다([`_ship_pr_body.py:266-278`](../../scripts/claude-hooks/_ship_pr_body.py)).

load-bearing 경로는
[`scripts/_governance.py`](../../scripts/_governance.py) 의 `LOAD_BEARING_PATHS`
에서 한 번 정의된다 — `CLAUDE.md`,
`.githooks/pre-push`, pre-commit hook, `_ship_pr_body.py` 가 참조하는
단일 진실 출처(single source of truth).

## Squash-merge & multi-concern 추적

Stage 5 는 `gh pr merge --squash --admin` (그 뒤 별도 `git push origin --delete`)
를 사용하므로, `main` 의 최종 커밋은 하나의 squash 된 커밋이며 그 subject 는 PR
title 이고 body 는 각 구성 커밋의 원본 `Closes #<N>` 마커를 담는다.

PR 이 둘 이상의 이슈를 정당하게 닫는다면(`STACKED=ack` 사이클에서
전형적), PR body 에서 각 종료를 별도의 줄에 둔다:

```
Closes #N
Closes #M
Closes #L
```

squash 가 landing 되면 GitHub 이 셋 모두를 자동으로 닫는다.

ADR 을 도입하는 커밋의 경우, 두 개의 분리된 PR 보다 같은 PR 에 "issue + ADR"
을 두는 것을 선호한다 —
[`docs/adr/README.md`](../adr/README.md) 의 cluster 내러티브는 ADR 과
그것을 가능케 한 코드 변경을 하나의 결정으로 취급한다.

## 실패 모드 & 안전망

| Failure | Stage | Behaviour |
|---|---|---|
| Tier-3 firewall 적중 (main/master/develop/release/* 에서 ship) | Gate 0 | hard abort, 검사를 위해 arm 보존 |
| Pre-commit hook 차단 | Stage 1 | `git commit` non-zero → stage-1 로그 라인과 함께 abort |
| Multi-agent lock 위반 | Stage 1 | `CROSS_OWNER=ack` 가 아니면 abort |
| Tier-7 heterogeneous prefix | Stage 1 | `STACKED=ack` 가 아니면 abort |
| 브랜치 컨벤션 위반 또는 이슈 누락 | Stage 2 | push 전 abort |
| §5b 검증 실패 (load-bearing 변경, body 에 delta 없음) | Stage 3 | `_ship_pr_body.py` exit 1, Stage 3 abort |
| CI red 또는 timeout | Stage 4 | PR 코멘트 게시, abort, PR 열린 채 유지 |
| requested changes / unresolved review thread | Stage 4 | PR 코멘트 게시, abort, PR 열린 채 유지 |
| `gh pr merge` 거부 (admin merge 불가, branch protection) | Stage 5 | abort, PR 열린 채 유지 |
| 머지 후 상태 ≠ `MERGED` | Stage 5 | arm 파일 그대로 두고 exit 1 |

arm 파일의 `dry_run: 1` 모드는 `origin` 을 건드리지 않고 새 파이프라인
구성을 end-to-end 로 검증하는 권장 방법이다. 모든
mutating 명령은 `.claude/.ship-dryrun.log` 로 echo 된다.

## 관련 문서

- [`CLAUDE.md`](../../CLAUDE.md) — "자주 쓰는 명령", "핵심 원칙" (one PR per concern), 금지 목록.
- [`docs/engineering-governance.md`](../engineering-governance.md) — 내비게이션 허브.
- [`docs/multi-agent-ownership.md`](../multi-agent-ownership.md) — Stage 1 이 소비하는 owner lock 맵.
- [ADR 0007](../adr/0007-issue-linked-branch-naming.md) — Gate 0 / Stage 2 에서 강제되는 브랜치 컨벤션.
- [`.github/pull_request_template.md`](../../.github/pull_request_template.md) — `_ship_pr_body.py` 가 채우는 템플릿.
- [`scripts/_governance.py`](../../scripts/_governance.py) — load-bearing SSoT.
