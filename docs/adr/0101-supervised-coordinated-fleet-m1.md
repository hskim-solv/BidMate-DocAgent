# ADR 0101: Supervised Coordinated Fleet — worktree-per-team + cross-process 예약(M1) + cross-family review 토글(M2)

## Status

- **Status**: proposed
- **Date**: 2026-06-04
- **Deciders**: User, Claude Code

**Accepted 전제**: 이 ADR은 새 *조율(coordination) 측정/계약 표면*을 고정한다 (reviewer·spawn-track·fleet-status 가 의존). **e2e 실측 전까지 Accepted 로 승격하지 않는다** — (M1) 독립 worktree 팀 ≥2 개가 동시에 `reserve` → 겹치는 load-bearing 파일 claim 이 BLOCK → `status` 단일 관측 → `release` 되는 것, 그리고 (M2) candidate-family 산출을 opposite-family 가 리뷰 → verdict 가 `fleet-status` 에 표시 → same-family 거부(fail-closed)가 실제로 작동하는 것까지 실제로 관측해야 한다. (교훈: 설정·코드 존재 ≠ 강제 작동 — ADR 0099 / staging self-ship 6라운드 self-catch.)

## Context

운영자는 12+ 독립 cmux 창(`claude-teams` / `codex-teams`)을 병렬 가동한다. 각 창은 같은 repo 에 대해 **독립 OS 프로세스**로 동작한다. 통증:

1. 창 간 "지금 무엇이 작업 중인지" 단일 관측이 불가.
2. 독립 창들이 같은 **load-bearing 파일**을 동시 수정 → 머지 충돌 / silent overwrite.
3. 기존 조율 인프라(`LeaseManager`, ADR 0094)는 **single-process 가정** — flock 이 non-POSIX 에서 no-op, `reject_on_overlap` 기본 off, 활성 자율 루프 STALE. N 독립창에 재사용 = category error.

토폴로지 조사 결론(공식 문서 + 실측):

- **claude-teams** = **leader 세션당 1팀**(머신 전역 아님; 독립 세션마다 팀 가능, `team-name` = 세션 UUID — `~/.claude/teams/{uuid}/` 에 다중 공존 실측). **shared working tree**, 수평 SendMessage 협업, claude 전용. 파일 충돌 방지 **없음**(공식: "two teammates editing the same file leads to overwrites. Break the work so each teammate owns a different set of files").
- **codex-teams** = root Codex + thread-spawn subagent(depth 2), private app-server **동적 포트**(멀티 인스턴스 공존 실측: omx 세션 3+ 가 각자 포트), 위계 협업, codex 전용.
- 두 네이티브 팀 모두 **shared working tree** → "독립 task N개"(N 브랜치/PR)가 아니라 **"한 브랜치 협업"**에 적합.
- **omc / omx team** = worker 별 worktree 격리 오케스트레이션이나, worker **sandbox 없음**(ADR 0087: 비공개 RFP egress 위험) + 이 repo 미검증 + 거버넌스 10라운드 부담.
- **OMC 고급 워크플로**(`interop` / `mission-board` / `ralphthon`, oh-my-claude-sisyphus v4.14.4 소스 대조): 각각 **2-party tmux 협업 채널** / **단일-cwd omc-team 진행률 대시보드** / **단일-pane 자율 hackathon loop** — **N-worktree cross-process 파일경합 조정은 셋 다 비제공**(상세 Alternatives 5).

## Decision

### D1. 단위 = worktree-per-team

각 worktree(독립 ADR 0007 브랜치/issue)에서 **팀 1개**를 띄운다:

- **팀끼리** = worktree 격리 → **독립 task N개** (각자 브랜치/PR).
- **팀 내부** = shared tree → teammate(claude) / subagent(codex) 협업. **각 런타임 native** (claude task list·SendMessage / codex thread-spawn)가 팀 내부 파일 분담을 관할.

### D2. M1 = 팀↔팀(worktree↔worktree) 조율 substrate

`scripts/fleet_coordination.py` 가 소유:

1. **cross-process 파일 예약**: **worktree 공유 anchor** 경로의 `reservations.json` + `.lock` sidecar. CHECK→RESERVE **first-writer-wins**. 두 worktree 가 같은 load-bearing 파일을 claim 하면 **BLOCK**(reservation 거부). **경로 해석 = `_resolve_fleet_dir`**: `git rev-parse --git-common-dir`(모든 worktree 가 공유하는 main `.git`)의 부모 = main worktree root 의 `.omc/state/fleet/` 에 store 고정 — per-worktree `repo_root/.omc` 가 **아니다**. per-worktree `.omc` 는 worktree 마다 별개 파일이라 두 독립 창이 같은 파일을 claim 해도 서로 다른 `reservations.json` 에 써서 **BLOCK 이 영영 발생 안 함**(M1 존재 이유 무효 — Codex adversarial review 가 첫 commit 에서 freq 2/2 critical 로 차단한 결함). `FLEET_STATE_DIR` env override(테스트·비표준 레이아웃), git 부재 시 `repo_root/.omc/state/fleet` 로 degrade(단일 checkout 일관, cross-worktree 비공유).
2. **단일 fleet-status monitor**: **lockless read**, 전 창의 claim + liveness 를 한 화면, **exit 0**(순수 관측; `--check` 모드만 stale/overlap 에 non-zero gating).
3. **flock engine 재사용**: ADR 0094 `LeaseManager` 를 **고정 fleet 경로에 재인스턴스화**(생성자 경로 파라미터화 확인). `_exclusive()`(stable sidecar flock-EX, O_CLOEXEC), `_atomic_write_text`(temp + `os.replace`), `assert_claimed_files_disjoint`(lock 내 disjoint). **새 flock engine 빌드 금지** — ADR 0094 가 닫은 footgun(inode-vs-path, TOCTOU) 재발 방지.

### D3. window_id = branch 명

worktree-per-team 이라 **branch 가 곧 팀 식별자**(ADR 0007 `<type>/issue-<N>`, worktree 당 유일·비민감·재유도 가능). spawn-track 이 child worktree 의 `repo_root/.omc/state/fleet/window-id` 에 persist — **window-id 는 per-worktree**(각 창의 정체성)인 반면 reservations/reviews store 는 **worktree 공유**(D2.1). 둘 다 `.omc/state/fleet/` 하위지만 root 가 다르다(window-id = 각 worktree root, store = main worktree root 의 git-common-dir anchor). teammate 구분은 **팀 내부(native) 관할**이라 M1 은 보지 않는다.

### D4. runtime = cc | codex

cross-runtime parity. `claude-teams` = `cc`, `codex-teams` = `codex`. 같은 substrate 에 두 런타임이 동등 참여 → Codex 창도 조율 대상.

### D5. 엮기 토글 (coupling is opt-in, never enforced)

- **보완(complementary)** = reservation (M1).
- **적대(adversarial)** = cross-family review (M2 — **본 ADR 에 포함**, 상세 D7). ADR 0064 `reviewer_family != candidate_family`, ADR 0066 codex review 의 **양방향** 확장. **verdict 는 advisory**(fleet-status 표시 전용, `--check` 게이트 아님 — D7-4·AC16): supervised 전제상 자동 verdict 가 다른 창 ship 을 막지 않는다.
- 기본은 **N 독립 창**, 결합은 opt-in. `FLEET_COUPLING=off|reserve|adversarial` 전역 env + 창별 override 로 단계 게이팅: **off**=조율 없음, **reserve**=M1 예약만, **adversarial**=M1+M2.

### D6. merge = ship-arm 안전 게이트

CI green + review gate(requested-changes / unresolved-thread block) → squash-merge `--admin`. omc `--auto-merge`(privacy/scope/Conservative Gate 우회) **금지**(ADR 0087).

### D7. cross-family review = 얇은 라우터 + 기존 dual-lane 엔진 재사용 (M2)

`fleet_coordination.py` 는 **라우팅·토글·verdict 가시성만** 소유하고, review 실행은 기존 active-loop dual-lane 을 재사용한다. **신규 review 엔진 빌드 금지** (양방향 cc↔codex review primitive 가 이미 존재 — 조사로 확인):

1. **방향 + fail-closed**: candidate_family = 현재 window 의 runtime(M1 reservation 의 `cc|codex` — `reserve --runtime` 은 required 라 cc 기본 stamping 없음, Codex info 1311). reviewer_family = **opposite**. `reviewer_family == candidate_family` 면 **거부**(명시 비교로 fail-closed — 현재 `agent_loop.py` 의 암묵 이항 선택 `other = "codex" if first.agent=="claude" else "claude"` 를 명시 assert 로 승격; ADR 0064 정신의 코드화). claude-teams 산출 → codex 리뷰, codex-teams 산출 → claude 리뷰.
2. **엔진 재사용** (신규 review 엔진 0): cc→codex = `scripts/agent_loop_codex_turn.run_turn`, codex→cc = `scripts/agent_loop_claude_turn.run_turn`(역방향 이미 구현). **diff 수집기는 lane 별로 다름**(보안 리뷰 L2): claude lane 은 `agent_loop._agent_turn_diff`(tracked-only + 60KB cap), codex lane 은 codex companion 자체 collector(`git diff merge-base..HEAD`, tracked-only, cap 은 companion `maxInlineDiffBytes`). **두 lane 다 tracked-only**(gitignored `data/` 비공개 corpus 제외)지만 수집 주체가 비대칭. **`agent-turn` 진입점(`write_agent_turn`)은 fleet review 에 직접 경유 불가** (구현 시 확인): `--session-id`(active-loop registry 검증) + `--role`(read-only review role enum — fleet window=branch명은 role 아님) + WU ledger/session heartbeat 기록을 요구해, fleet 가 호출하면 ADR 0001 byte-identity 대상인 active-loop ledger 를 오염시킨다. 따라서 **정규 경로 = `run_turn` 직접 호출 + privacy 헬퍼 명시 재사용**(경계 재구현 아님 — 기존 헬퍼 호출): `strip_ship_secret_env`(ADR 0090; 각 turn `_default_runner` 내장, 자동 상속) + `_redact_private_json` + `audit_privacy_output`(`write_agent_turn` 과 **동일** fail-closed backstop). residual 비공개 span survive 시 verdict=`error` collapse.
3. **ADR 0005 egress 경계**: codex/claude review 는 **외부 egress**(로컬 아님 — codex=OpenAI, claude=구독 OAuth; `--sandbox read-only` 는 FS write 차단이지 network 차단 아님). 기존 3중 보호 상속 — ① path-block 먼저(private staged 파일이 prompt 에 안 감) ② tracked diff 만(gitignored `data/` 비공개 corpus 제외) ③ secret-strip(`strip_ship_secret_env`) + `audit_privacy_output` fail-closed. **정직한 경계 framing(보안 리뷰 M1)**: ③의 audit backstop 은 **structural-pattern-only**(field-prefixed value: `question:`/`answer:`/`evidence:`/`doc_id:` 등 + 절대 로컬 경로 매칭)이라 **자유형 RFP prose 는 scrub 하지 않는다**. 따라서 실질 보장은 **"tracked-only diff"**(gitignored 비공개 corpus 제외)이지 **"비공개 데이터 egress 불가"가 아니다** — tracked source 의 RFP 인용 주석/fixture 는 외부 reviewer 로 전송된다(기존 `write_agent_turn` 의 상속 속성, fleet 신규 회귀 아님). 더 강한 보장이 필요하면 pre-egress diff structural screen(`_privacy_findings_for_text(diff)` → 적중 시 verdict=error)을 opt-in 추가(M2 follow-up). **diff 는 fleet 파일에 안 올림** — review lane 이 자체 수집(claude=`_agent_turn_diff`, codex=companion). fleet `reviews.json` 레코드엔 `{window_id, candidate_family, reviewer_family, base, verdict, severity_counts, reviewed_at}` **메타만**(코드·findings 텍스트 없음; 상세는 `.omc/` gitignore artifacts_dir). M1 의 positive-shape allowlist 를 review 레코드로 확장.
4. **트리거 = 수동 opt-in + verdict advisory** (supervised): `make fleet-review BASE=<ref>`. 자동 폴링·release-시-자동-트리거 **없음**(자율=비목표). verdict 는 fleet-status 에 **표시만**(advisory) — `--check` 게이트도, 다른 창 ship auto-block 도 아니다(AC16). merge 게이트는 D6 ship-arm + 운영자. 자동 verdict 게이팅(verdict↔revision binding)은 M3 follow-up 후보.

## Topology

```
worktree A (issue-X) ─ claude-teams 팀A   (leader + teammates, shared tree W_A, native 협업)
worktree B (issue-Y) ─ claude-teams 팀B
worktree C (issue-Z) ─ codex-teams        (root + depth-2 subagents)
       │
       └─ M1: 팀(=worktree=window) 간 load-bearing 파일 예약(first-writer-wins BLOCK)
              + fleet-status 단일 화면(lockless read, exit 0)
팀 내부 협업 = 각 런타임 native        엮기 = reservation(보완) / cross-family review(적대, M2)
merge = ship-arm 안전 게이트
```

## Alternatives considered

1. **claude-teams/codex-teams shared-tree only** — 독립 task N개 불가(브랜치 1개, git index 1개 공유). 한 작업 협업엔 맞으나 *함대 단위*로 부적합. → 팀 내부 레이어로만 채택, 함대 단위는 worktree.
2. **omc / omx team 오케스트레이션** — worktree 격리는 주나 worker **sandbox 없음**(ADR 0005 egress 위험) + 이 repo 미검증 + 거버넌스 10라운드 부담(ADR 0087). **거부**(네이티브 팀 + 수동 worktree + M1 이 더 가볍고 통제 가능).
3. **중앙 daemon** — SPOF, N창 생존성 위배. **거부**(고정 on-disk 파일 rendezvous, no long-lived daemon).
4. **LeaseManager 신규 포크** — DRY 위배, ADR 0094 검증된 footgun fix 재발 위험. **거부**(재인스턴스화 재사용 선택; 대안으로 `scripts/_lease_core.py` leaf 추출은 fallback).
5. **OMC 고급 워크플로 재사용**(`interop` / `mission-board` / `ralphthon`) — 소스 대조(oh-my-claude-sisyphus v4.14.4): 셋 다 본 substrate 의 두 핵심 능력((A) cross-process 파일예약 BLOCK, (B) N 독립창 단일 관측)을 **비제공**. **거부(직교-갭, 중복 아님)**:
   - `interop` = OMC↔OMX **2-party 고정** 채널(`tmux split-window -h` 단일 분할, target `enum(['omc','omx'])` 하드코딩, `TMUX` 강제). MCP `interop_send_task` 의 `files` 필드는 **inert 메타** — 충돌 검사·BLOCK 없음. N-worktree 함대 아님.
   - `mission-board` = **단일 cwd × omc-team** 진행률 대시보드(`refreshMissionBoardState(process.cwd())` 1회, `{cwd}/.omc/state/team` 만 스캔). native claude-teams(`~/.claude/teams/`)·타 worktree 미관측. liveness 는 omc-team `heartbeat.json` 의존 → omc team 미경유 순수 claude-teams/codex-teams 세션은 표시 대상 아님.
   - `ralphthon` = **단일 leader pane** 자율 hackathon loop(`tmux send-keys` 직렬 큐, worktree 격리·병렬 없음) → 본 ADR 의 **supervised·비자율 전제와 상충**.
   - 공통: cross-process 파일 reservation(first-writer BLOCK) 시맨틱이 코드 전역 부재(`dist/lib/file-lock.js` 는 cross-process advisory lock 을 구현하나 전 caller 가 자기 상태 JSON 직렬화 보호 한정 — 소스파일 claim 시맨틱 0). → M1 은 **빈 공간**을 메움.

## Consequences

**긍정**:
- 독립 task(worktree 격리) + 협업(팀 내부 native) **동시 충족** — 운영자의 "각각 따로 + 엮기 토글" 멘탈모델과 일치.
- 네이티브 팀 기능(SendMessage·idle notif·thread-spawn) 그대로 보존.
- 검증된 flock engine 재사용 → footgun 재발 위험 최소.
- ADR 0005 경계 **구조적 보존**(`.omc/` gitignore + positive-shape relative-path allowlist + `data/` 거부).
- runtime-agnostic → Codex 창 동등 참여.

**부정 / 비용**:
- 독립 세션 다중 claude 팀은 **공식 미보증**(문서 "a lead" 단위만 명시; 디스크 공존은 실측) → **e2e 실측 게이트 필수**(Status).
- worktree-per-team 은 운영자가 worktree 를 띄우는 **규율에 의존**(M1 은 강제 못 함, spawn-track 와이어링이 권장 경로).
- M1 은 load-bearing 파일 claim 을 **운영자/spawn-track 이 선언**해야 효력 — 미선언 시 inert(measurement-surface inert pattern). 와이어링 필수.

## Verification

<!-- verifies-key: scripts/fleet_coordination.py:def reserve -->
<!-- verifies-key: scripts/fleet_coordination.py:_ALLOWED_RECORD_KEYS -->
<!-- verifies-key: scripts/_governance.py:FLEET_TTL_MINUTES -->
<!-- verifies-key: scripts/fleet_coordination.py:def review -->
<!-- verifies-key: scripts/fleet_coordination.py:FLEET_COUPLING -->
<!-- verifies-key: scripts/fleet_coordination.py:def _resolve_fleet_dir -->
<!-- verifies-key: scripts/fleet_coordination.py:def _paths_conflict -->
<!-- verifies-key: scripts/fleet_coordination.py:def _load_reviews_strict -->

Acceptance Criteria (plan `.omc/plans/supervised-fleet-coordination-m1.md` 와 1:1):

- **AC1a** substrate 배타성: ≥8 contender 동시 `reserve` 중 정확히 1 승, 나머지 BLOCK(겹치는 claim) — `tests/test_fleet_coordination.py`.
- **AC1b** 파일 레벨 disjoint 자동 BLOCK(같은 파일 다른 window). **경로 overlap = ancestor/descendant**(Codex high): 디렉토리 claim(`eval/`)은 그 하위 파일 claim(`eval/config.yaml`)과 충돌, 역방향(`api/main.py` vs `api/`)도 충돌 — exact-set 교집합이 아니라 path-segment 경계 overlap(`_paths_conflict`; `eval/` 가 `evaluation/foo.py` 를 삼키지 않음). load-bearing 집합이 실제 디렉토리 엔트리(`eval/`·`api/`·`docs/adr/`)를 담으므로 필수. 회귀: `test_group_d_path_overlap_*`.
- **AC2** 고정 경로 + no-daemon(독립 프로세스 on-disk rendezvous).
- **AC3** TTL(`FLEET_TTL_MINUTES`=30m) 만료 prune / release / orphan 정리.
- **AC4** monitor lockless read + exit 0(순수 관측), `--check` 만 gating. **`--check` 는 corrupt store 에 fail-closed**(Codex high): plain `status` 는 tolerant([], non-raise)지만 `--check` 는 `_load_records_strict`/`_load_reviews_strict` 로 reservation·review store 를 검사해 unreadable 이면 non-zero(monitor 의 lockless tolerant 경로로 fail-open 금지). 회귀: `test_group_d_status_check_fails_closed_on_corrupt_*`.
- **AC5a** CHECK→RESERVE + lock 순서(reserve→release→spawn, flock 을 subprocess spawn 너머로 유지 금지).
- **AC5b** cleanup release 와이어링.
- **AC6** fail-closed: `fcntl is None` 거부 + **two-open honesty probe**(같은 `.lock` 두 번 LOCK_EX|NB → 둘째 실패해야 정직한 FS; 둘 다 성공 = NFS/synced 거짓 → 거부). **errno 판별**(Codex high): probe 의 첫 LOCK_EX|NB 가 던지는 OSError 중 **`BlockingIOError`(진짜 경합)만 통과**(경합 자체가 FS 의 배타성 강제 증거) — `ENOLCK`/`EINVAL`/`EOPNOTSUPP` 등 비경합 OSError 는 lock 불가 substrate 이므로 **fail-closed**(거짓 정직 오인 금지).
- **AC7** ADR 0005 positive-shape allowlist(`_ALLOWED_RECORD_KEYS`) + relative-path(`data/` 거부) + schema_version 자체 검증(`_cmd_check_eval_privacy` 위임 금지).
- **AC8** runtime-agnostic CLI(`--runtime cc|codex`). `reserve --runtime` 은 **required**(cc 기본 제거 — Codex info 1311: cc 기본이면 codex window 가 cc 로 stamped 되어 same-family 리뷰될 위험). `make fleet-reserve` 도 `RUNTIME` 필수. 회귀: `test_group_d_reserve_cli_requires_runtime`.
- **AC9** 이 ADR.
- **AC10** 회귀 테스트(`tests/test_fleet_coordination.py`).
- **AC15** RMW fail-closed(Codex high): reserve/heartbeat/release/review-write 의 read-modify-write 임계영역은 store 가 garbled 면 **`FleetError` fail-closed + 파일 무변경**(blind overwrite 로 live claim/verdict 삭제 금지). lockless monitor read(status)만 garble 에 tolerant([], non-raise — gating 안 하므로). `_load_records_strict`/`_load_reviews_strict`(RMW) vs `_load_records`/`_load_reviews`(monitor) 분리. **malformed review store(Codex medium)**: `_load_reviews_strict` 는 `{'reviews': [...]}` dict 도 bare list-of-dict 도 아닌 payload(예: dict without `reviews` list, 문자열)에 `FleetError` fail-closed + 보존 레코드는 `assert_review_privacy_safe` 통과 후에만 재기록(prior verdict blind erase 금지). 회귀: `test_group_d_load_reviews_strict_rejects_*`.

**M2 (cross-family review 토글):**

- **AC11** cross-family fail-closed: reviewer_family = opposite(candidate). `reviewer_family == candidate_family` 면 거부(명시 비교). cc 산출 → codex, codex 산출 → claude 만 허용.
- **AC12** `FLEET_COUPLING` 토글: `off`(review 안 함) / `reserve`(M1 만) / `adversarial`(review 실행) 게이팅. 미설정 기본 = `reserve`(M2 opt-in).
- **AC13** verdict 레코드 ADR 0005 경계: `reviews.json` 은 positive-shape allowlist(메타만) — diff/findings 텍스트 없음, `data/` 경로 거부, schema_version 자체검증. 상세 findings 는 `.omc/` gitignore artifacts_dir.
- **AC14** 엔진 재사용: review lane 이 `run_turn` **직접 호출**(`agent-turn` 진입점은 active-loop session/role/ledger 결합으로 비경유 — D7-2) + privacy 헬퍼(`strip_ship_secret_env`/`_redact_private_json`/`audit_privacy_output`) 명시 재사용. 단위 테스트는 injectable `runner` 로 외부 codex/claude 호출 0. `fleet-status` 가 reservation + review verdict 를 한 화면에 표시.
- **AC16** verdict **ADVISORY** (option B — Codex round-2 high "verdict-to-revision binding" 해소 경로): cross-family review verdict 는 `fleet-status` review 테이블에 **표시만** 되고 `--check` 를 **게이트하지 않는다**. `fleet-review` CLI 도 review 가 실행 성공이면 verdict 무관 **exit 0**(실행 실패=`FleetError` 만 non-zero). 자동 cross-family verdict 가 다른 창의 ship 을 auto-block 하지 않으며, merge 게이트는 **D6 ship-arm review-gate + 사람 운영자**다. 근거: verdict 를 게이트하려면 verdict↔리뷰된 revision binding(cross-worktree git lookup·TOCTOU)이 필요해 **supervised 전제(자율 비목표)와 상충** — advisory 로 두면 binding 이 무의미해지고(게이트가 없어 poison 대상도 없음) 경계가 단순해진다. pass-class 분할(`_PASS_CLASS_VERDICTS`)·`has_review_problem` 게이트 **제거**. 회귀: `test_ac16_blocked_verdict_does_not_gate_check`/`test_ac16_error_verdict_does_not_gate_check`(게이트 안 함) + `test_ac16_blocked_verdict_is_still_rendered`(표시는 됨).

검증 명령:
```
python3 scripts/fleet_coordination.py status            # 단일 화면, exit 0
python3 scripts/fleet_coordination.py reserve --runtime cc --issue 2236 --files scripts/agent_loop.py
bash scripts/test.sh -k fleet                           # AC 회귀
```

## Follow-ups (M3+)

- **적대 토글 자동화 + verdict 게이팅(M3 후보)**: 현재 M2 는 수동 `fleet-review` + **advisory verdict**(AC16). 승격 경로 둘: (a) reservation release 시 자동 cross-family review 트리거, (b) verdict↔리뷰된 revision binding(claimed files + HEAD SHA/diff hash 같은 비민감 fingerprint, cross-worktree git lookup) 후 `--check` 게이팅으로 승격 — Codex round-2 의 "verdict-to-revision binding" high 는 게이팅을 전제로 한 지적이라, advisory 로 둔 현 설계에선 **의도적 보류**(게이트가 없어 stale-verdict poison 대상도 없음). 둘 다 자율 영역이라 신중(supervised 기본 유지, e2e 실측 후).
- **pre-egress diff structural screen(보안 M1, opt-in)**: review runner 호출 전 `_privacy_findings_for_text(diff)` 로 structural 패턴 적중 시 verdict=error 차단. backstop 이 content-blind 이므로 defense-in-depth (단 여전히 structural-only — 자유형 prose 는 못 막음, tracked-only diff 가 1차 경계).
- **codex self-collect egress 한계(보안 L1)**: 큰 diff 시 codex companion 이 self-collect 모드로 전환하면 read-only codex 가 git 명령으로 working tree(gitignored 포함)를 읽을 수 있음 — codex 에 bounded inline-diff 강제 전달로 self-collect 회피 또는 잔여 리스크 명시. 현재는 tracked-diff + gitignore 레이어링 + 수동 opt-in 으로 bounded.
- worktree-per-team 격리 심화(팀별 git-index 분리 검증).
- depth-priority queue field.
- 독립 세션 다중 claude 팀 동시 활성 e2e 실증(공식 미보증 영역).
- **OMC 통합 여지**(중복 아닌 흡수, 선택): (a) `mission-board` 데이터 모델 정렬 → fleet-status 를 mission-board 가 cross-worktree aggregator 로 흡수하거나 병행 렌더; (b) `interop` MCP message-passing 을 적대 토글(cc↔codex review)의 전송 계층으로 재사용; (c) `OMC_TEAM_WORKTREE_MODE` worker 에 reservation 적용. 셋 다 **신규 기능**이지 기존 중복 아님.

## References

- ADR 0094 (LeaseManager — flock engine, 재사용 원천)
- ADR 0005 (public/private eval 경계 — reservation 페이로드 제약)
- ADR 0001 (naive baseline byte-identity — 별도 fleet 경로라 leases.json 불변)
- ADR 0087 (omc team no-auto-merge — worker sandbox 부재 근거)
- ADR 0064 (cross-family reviewer), ADR 0066 (codex adversarial review — 적대 토글 원천)
- ADR 0079 (overlap-preflight — spawn gate 보완)
- Plan: `.omc/plans/supervised-fleet-coordination-m1.md`
- Issue: #2236
