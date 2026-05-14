# Agent Utilization Strategy

> Q3-2026 KPI: Claude 협업 5축 중 ≥3축을 ✓로 끌어올린다. Q2-2026 self-review 결과는 1✓4△ — 컨텍스트 효율만 ✓.
>
> 이 문서는 `self-review-quarterly` skill이 다음 분기에 5축을 채점할 때 직접 참조한다. 트리거·도구·측정이 빠짐없이 명시돼야 평가 가능하다.

## TL;DR

- 도구 면적은 이미 풍부하다 — PreToolUse 훅 3개, git 훅 2개, CI 2개, Make 타깃 10+, 프로젝트 skill 3개, 시스템 서브에이전트 5종. **문제는 카탈로그·트리거 부재**라서 호출되지 않는다.
- 이 문서는 4 pillar(룰/스킬/서브에이전트/커맨드)을 5축 KPI에 reverse-mapping한 운영 가이드다. 새 코드 0줄.
- 측정 인프라(`.hook-fires.log` 활성화 등 follow-up issues #718–#720)는 별도 PR이지만, 이 PR 머지 직후 `make install-hooks` 1회로 자동화 ROI 측정이 시작된다.

## 4 Pillar — 책임 분담

| Pillar | 정의 | 강제력 | 예 |
|---|---|---|---|
| **규칙(Rules)** | 자동 강제 invariant | 훅·CI 차단 | PreToolUse load-bearing edit, branch naming, ADR 0005 경계 |
| **스킬(Skills)** | workflow 묶음 + 승인 게이트 | 사람·Claude 수동 호출 | `ship-pr`, `self-review-quarterly`, `adr-portfolio-signals` |
| **커맨드(Commands)** | 수동 트리거(평가·shipping·검증) | Make 타깃 / 스크립트 | `make smoke`, `make real-eval`, `make ship-arm`, `make governance-check` |
| **서브에이전트(Subagents)** | 컨텍스트 격리(읽기 전용 탐색·설계 외주) | 메인 컨버세이션에서 위임 | Explore, Plan, general-purpose |

원칙: **규칙은 자동, 나머지 셋은 트리거 조건이 만족될 때만 호출.** 트리거가 모호하면 도구는 사장된다.

## 5축 × 4 Pillar 매핑

| 축 | Q2 | 트리거 조건 | 도구 조합 (4 pillar) | 측정 지표 | Follow-up |
|---|---|---|---|---|---|
| **#1 컨텍스트 효율** | ✓ | Read 5회 누적 / 단일 파일 200줄↑ | **서브에이전트:** Explore 위임 (병렬 ≤3) · **커맨드:** `/clear` 후 작업 분리 | 대화당 평균 token, Explore 호출 수/분기 | — |
| **#2 Agent 위임** | △ | 비-trivial 변경(>1 파일 or >50 LOC) 시작 전 · plan mode 진입 | **서브에이전트:** Plan 기본 호출 · **규칙:** `## Delegation defaults` (CLAUDE.md) · **스킬:** multi-agent-ownership 역할 분담 | PR diff>50 LOC 중 Plan 호출 0회 비율 | #718 |
| **#3 자동화 ROI** | △ | worktree clone 직후 · 분기 시작 | **커맨드:** `make install-hooks` · `make ship-arm` · `make governance-check` · **규칙:** PreToolUse 훅 3개 · **스킬:** `ship-pr` | `.hook-fires.log` 라인 수, ship-* 경유 PR 비율 | #719 |
| **#4 사이클 타임** | △ | ADR proposed→accepted >7일 · PR open→merge >3일 | **스킬:** `ship-pr`(ADR 번호 예약 + stacked 안전) · **커맨드:** `make ship-arm`(Stop훅 자동 배송) | ADR lag 평균, PR turnaround p90 | 추후 신규 (collector 미생성) |
| **#5 메모리 위생** | △ | memory 파일 추가·수정 · 인덱스 라인 >20 | **스킬:** `anthropic-skills:consolidate-memory` · `productivity:memory-management` · **규칙:** PreToolUse Edit 매처 (예정) | 인덱스 라인 수, stale(>2분기 미참조) 비율 | #720 |

## Shipping 경로 — `ship-pr` skill vs `make ship-arm`

둘은 **mutually exclusive**. PR 시작 시(commit-0) 결정해서 commit message에 명시한다:

- **`ship-pr` skill** — 수동 게이트. push와 merge 각 단계에서 명시적 승인. ADR 번호 예약·stacked-PR 감사 포함. **결정이 무겁거나 stacked PR이면 이쪽**.
- **`make ship-arm`** — Stop훅 기반 자동 배송. 8-step 사전검사 통과 시 commit → push → PR → CI 대기 → squash-merge까지 자동. **소형/독립 PR이면 이쪽**.

동시 사용 금지(skill 설명 `ship-pr` 트리거 조항 명시). 자세한 단계는 [`auto-ship.md`](auto-ship.md) 참조.

## Follow-up Issues

- **#718** — `scripts/_self_review.py`에 "diff>50 LOC + Plan 호출 0회" 카운터 (축 #2)
- **#719** — `Makefile` `smoke` 타깃의 `install-hooks` prerequisite (축 #3)
- **#720** — `.claude/settings.json` PreToolUse Edit 매처(MEMORY.md 인덱스 라인 수) (축 #5)
- **TBD** — `scripts/_cycle_time.py` ADR lag + PR turnaround collector (축 #4) — 추후 별도 issue

각 follow-up은 1 PR / 1 concern 원칙에 따라 분리한다. 이번 PR은 **전략 + 활성화 가이드**까지만.

## References

- [`docs/self-review/Q2-2026.md`](self-review/Q2-2026.md) — 5축 진단 원본
- [`docs/multi-agent-ownership.md`](multi-agent-ownership.md) — 7역할 owner 모델
- [`docs/auto-ship.md`](auto-ship.md) — `make ship-arm` 8-step 파이프라인
- [`docs/engineering-governance.md`](engineering-governance.md) — workflow map
- `MEMORY.md` 항목: `feedback_collaboration_axes.md`, `feedback_agent_delegation.md`, `feedback_q2_2026_collaboration_review.md`
