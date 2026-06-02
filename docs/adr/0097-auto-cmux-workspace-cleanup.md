# 0097: cmux orphan workspace 자동 정리 (worktree 부재 위임 + 수동 트리거)

- Status: accepted
- Date: 2026-06-02
- Deciders: User, Claude Code
- Related: [ADR 0096](./0096-auto-worktree-branch-cleanup.md) (worktree + 로컬 브랜치 정리 자매 결정 — cmux 정리가 그 위에 한 축 더 얹음), [ADR 0007](./0007-issue-linked-branch-naming.md) (orphan 누적이 위협하는 "동시 worktree → 혼란" 실패 모드)
- Issue: #1795

## Context

worktree 정리에는 세 축이 있다 — worktree, 로컬 브랜치, 원격 브랜치(ADR 0096 / ship-pr / ship-arm). 그러나 멀티 worktree 운영(상시 20-30개)에서 각 worktree 는 cmux workspace(탭)와 1:1 대응하고, worktree 가 ADR 0096 으로 정리돼도 **대응 cmux workspace 는 남는다**. 죽은 탭이 누적되면 "어느 탭이 살아있는 작업인지 분간 불가" 상태가 되며, 이는 ADR 0007 이 경계하는 "동시 worktree → 혼란" 실패 모드의 시각적 사촌이다.

스파이크로 메커니즘을 검증했다: workspace 열거(`cmux workspace list`), cwd 역추적(`cmux top --processes` → claude PID → `lsof -d cwd`), 단일 close(`cmux rpc workspace.close` — CLI `workspace-action` 엔 단일 close 가 없음). `surface.close` 는 "마지막 surface" 거부로 불가.

핵심 비대칭: **cmux workspace close 는 비가역**이다 — worktree 는 `git worktree add` 로 재생성되지만 닫힌 탭의 스크롤백/대화 맥락은 영구 소멸한다. 따라서 worktree 정리(ADR 0096, SessionStart 자동)보다 안전 여유가 훨씬 작고, 트리거와 가드를 더 보수적으로 잡아야 한다.

## Decision

1. **orphan 판정 = "worktree 부재" 위임 (머지 4신호 재발명 안 함).** workspace 의 cwd 가 현재 `git worktree list` 에 더 이상 없으면 orphan 으로 간주한다. worktree 가 현존하면 작업이 살아있다 → 탭 보호. worktree 가 사라졌다면 ADR 0096 의 4신호 머지확정이 이미 정리한 것 → 그 탭은 잔재. ADR 0096 을 transitive 신뢰한다.

2. **3가드 + 정보부족 시 전부 skip (fail-safe).** ① self-skip — `$CMUX_WORKSPACE_ID`(실측상 **UUID**)를 `workspace list` 로 ref 매핑해 자기 탭 제외(매핑 실패 시 전부 skip) ② active 보호 — `cmux tree` 의 `◀ active`/`◀ here` 마커(포커스가 **자식 surface/pane 줄**에 찍히며 번호=workspace 번호) + `workspace list` 의 `*`(현재 표시 탭). `[selected]`/`[focused]` 는 모든 pane 에 붙어 변별력이 없어 active 신호에서 제외 ③ cwd 가 현존 worktree **이거나 현존 디렉토리**면 보호(삭제된 worktree 디렉토리만 orphan — 살아있는 비-worktree 탭 보호). self 미식별 / tree 파싱 실패 / git list 실패 / cwd 불명 / PID 다중 중 하나라도 live → 전부 닫지 않는다. 닫는 칸은 진리표에서 하나뿐(자기 아님 + active 아님 + cwd 를 알아냈는데 그 디렉토리가 전부 사라짐).

3. **비가역성 때문에 이번 범위는 수동 `make` 만, dry-run 기본 권장.** `make cmux-cleanup-dry-run`(후보만 출력) / `make cmux-cleanup`(실제 close). SessionStart 자동화는 수동 dry-run 으로 3가드 실측 정확도를 신뢰한 뒤 별도 후속 issue 에서 ADR 과 함께 검토한다(점진 도입).

4. **cmux workspace 만 건드린다.** 원격 브랜치 / worktree / 로컬 브랜치는 ADR 0096 / ship-pr / ship-arm 담당. 이 결정은 cmux 표면에 국한.

5. **스크립트는 `scripts/cmux-cleanup.sh`, soft `exit 0`.** push 와 무관하므로 `.githooks/`(pre-push 가 source 하는 sub-hook 관용) 가 아닌 `scripts/`. `set -u`(NOT `set -e`), 모든 분기 끝 `exit 0` — 세션/푸시를 절대 막지 않는다. cmux 부재(CI/headless) 시 즉시 soft skip.

## Drivers

1. **판정 재사용** — 머지 4신호를 다시 구현하지 않고 worktree 존재 여부로 위임(ADR 0096 신뢰). 단일 출처 유지.
2. **비가역성 우선** — 탭/스크롤백 영구 소멸이라 worktree 보다 안전 여유가 작음 → 수동 + dry-run 기본 + 정보부족 skip.
3. **prior art 승계** — `scripts/spawn_track_session.sh` 의 `CMUX_BIN` 절대경로 규약(issue #1767), `_pre-push-worktree-hygiene.sh` 의 soft 계약.

## Alternatives considered

- **ADR 0096 확장(별도 ADR 안 만듦).** 기각: 0096 의 Decision/verifies-key 는 로컬 worktree/브랜치 한정. cmux 는 판정 메커니즘(worktree 부재 위임)·비가역성 등급(영구 소멸 vs 재생성)·트리거(수동)가 모두 독립 → 섞으면 0096 의 단일 결정이 흐려지고 verifies-key 마커가 두 표면으로 비대해진다. CLAUDE.md `## 금지`(ADR 파일 삭제/이름변경 금지, Superseded 만)와도 부합 — 0096 은 그대로 두고 새 결정은 새 파일.
- **SessionStart 자동삭제(ADR 0096 처럼).** 이번 범위에서 기각: 비가역성 여유가 작아 먼저 수동 dry-run 으로 정확도를 신뢰한 뒤 점진 도입. 설계는 확장 가능하게 둠(soft + 3가드 + early-exit).
- **머지 4신호 직접 판정.** 기각: 재발명. worktree 존재 여부가 한 단계 뒤에서 같은 결론을 준다.
- **`surface.close` 경유.** 기각: "마지막 surface" 거부(스파이크 확인). `rpc workspace.close` 만 사용.

## Consequences

- **lsof 플랫폼 의존**: cwd 매핑이 비-macOS/sandbox 에서 빈 출력이면 모든 cwd 불명 → 전부 skip = 기능이 조용히 무력화(안전엔 무해, "왜 안 닫나" 혼란 가능). cwd 불명 시 진단 로그로 완화.
- **경로 정규화 필수**: `/private/var`↔`/var`, trailing slash 미정규화 시 살아있는 worktree 를 orphan 오인 → 비가역 close. live/gone 양쪽을 정규화 + 회귀 테스트로 고정.
- **PID 귀속은 컬럼 정확매칭 필수**: `top` 행을 통째로 토큰화해 정수를 줍는 방식은 (a) `workspace:1` 이 substring 으로 `workspace:10`+ 행을 교차 수확하고 (b) 메모리/카운트 컬럼 정수를 PID 로 오인 → 살아있는 탭 false-orphan. TYPE=process 행의 ID 컬럼만, PARENT(`surface:N`/`pane:N`) 정확매칭(`==`)으로 귀속한다(회귀 #15/#16). 사용자 20-30 worktree 운영에서 두 자리 workspace 번호는 일상이라 이론적 엣지가 아니다.
- **stub 한계는 실환경 dry-run 으로 보완**: 초기 구현은 stub 이 2-컬럼 `top` + ref-형 self + 한 줄 마커를 가정했으나 실제 cmux 0.64 는 `CMUX_WORKSPACE_ID`=UUID, `top` NF=7 컬럼, `tree` 포커스 마커가 자식 surface/pane 줄에 위치. 실환경 `--dry-run` 으로 **self-close 포함 5개 가드 결함을 발견·수정**(스파이크/stub 만으론 미검출)했고 테스트 fixture 를 실제 포맷으로 고정했다. stub 회귀는 포맷 drift 를 못 잡으므로 도입 후 첫 실행·cmux 버전업 시 반드시 `--dry-run` 육안 확인을 운영 규칙으로 둔다.
- **cmux 포맷 drift**: `tree`/`top`/`workspace list` 파싱이 버전업으로 깨지면 active 오인식. 파싱 실패·빈 출력은 전부 보수 skip 으로 떨어지게 설계. 단 stub 테스트는 실제 drift 를 못 잡으므로 수동 dry-run 운영으로 보완.
- 비가역 파괴 op 자동화이지만 dry-run 기본 + 3가드 + 정보부족 skip + 수동 트리거로 안전 여유를 확보한다. soft exit 0 계약으로 세션을 절대 차단하지 않는다.

## Verification

```bash
python3 -m pytest -q tests/test_script_cmux_cleanup.py
python3 scripts/_governance.py --check-adr-readme-parity docs/adr/0097-auto-cmux-workspace-cleanup.md
bash scripts/cmux-cleanup.sh --dry-run   # cmux 부재 환경에서도 exit 0 (soft)
```

<!-- verifies-key: scripts/cmux-cleanup.sh:cmux-cleanup -->
<!-- verifies-key: tests/test_script_cmux_cleanup.py:test_orphan_only_closed -->
<!-- verifies-key: Makefile:cmux-cleanup -->
