# Agent Utilization Strategy

> **Q3-2026 KPI**: Claude 협업 5축 중 ≥3축을 ✓로 끌어올린다. Q2-2026 self-review = 1✓4△ (컨텍스트 효율만 ✓).
>
> 이 문서는 `self-review-quarterly` skill 이 다음 분기 5축을 채점할 때 직접 참조 — 트리거·도구·측정이 모두 명시돼야 평가 가능.

## TL;DR

- 도구 면적은 풍부 (PreToolUse 훅 3, git 훅 2, CI 2, Make 타깃 10+, 프로젝트 skill 3, 시스템 서브에이전트 5). **문제는 카탈로그·트리거 부재**라 호출되지 않음
- 본 문서 = 4 pillar (룰/스킬/서브에이전트/커맨드) 를 5축 KPI 에 reverse-mapping 한 운영 가이드. 신규 코드 0줄
- 측정 인프라 (`.hook-fires.log` 활성화 등 follow-up #718–#720) 는 별도 PR; 머지 직후 `make install-hooks` 1회로 자동화 ROI 측정 시작

## 4 Pillar — 책임 분담

| Pillar | 정의 | 강제력 | 예 |
|---|---|---|---|
| **규칙(Rules)** | 자동 강제 invariant | 훅·CI 차단 | PreToolUse load-bearing edit, 브랜치 명명, ADR 0005 경계 |
| **스킬(Skills)** | workflow 묶음 + 승인 게이트 | 사람·Claude 수동 호출 | `ship-pr`, `self-review-quarterly`, `adr-portfolio-signals` |
| **커맨드(Commands)** | 수동 트리거 (평가·shipping·검증) | Make 타깃 / 스크립트 | `make smoke`, `make real-eval`, `make ship-arm`, `make governance-check` |
| **서브에이전트(Subagents)** | 컨텍스트 격리 (읽기 전용 탐색·설계 외주) | 메인 대화에서 위임 | Explore, Plan, general-purpose |

원칙: **규칙은 자동, 나머지 셋은 트리거 만족 시만 호출.** 트리거가 모호하면 도구는 사장.

## 5축 × 4 Pillar 매핑

| 축 | Q2 | 트리거 조건 | 도구 조합 (4 pillar) | 측정 지표 | Follow-up |
|---|---|---|---|---|---|
| **#1 컨텍스트 효율** | ✓ | Read 5회 누적 / 단일 파일 200줄↑ | **서브에이전트:** Explore 위임 (병렬 ≤3) · **커맨드:** `/clear` 후 작업 분리 | 대화당 평균 token, Explore 호출 수/분기 | — |
| **#2 Agent 위임** | △ | 비-trivial 변경 (>1 파일 or >50 LOC) 시작 전 · plan mode 진입 | **서브에이전트:** Plan 기본 호출 · **규칙:** `## Delegation defaults` (CLAUDE.md) · **스킬:** multi-agent-ownership 역할 분담 | PR diff>50 LOC 중 Plan 호출 0회 비율 | #718 |
| **#3 자동화 ROI** | △ | worktree clone 직후 · 분기 시작 | **커맨드:** `make install-hooks` · `make ship-arm` · `make governance-check` · **규칙:** PreToolUse 훅 3 · **스킬:** `ship-pr` | `.hook-fires.log` 라인 수, ship-* 경유 PR 비율 | #719 |
| **#4 사이클 타임** | △ | ADR proposed→accepted >7일 · PR open→merge >3일 | **스킬:** `ship-pr` (ADR 번호 예약 + stacked 안전) · **커맨드:** `make ship-arm` (Stop훅 자동 ship) | ADR lag 평균, PR turnaround p90 | #724 |
| **#5 메모리 위생** | △ | memory 파일 추가·수정 · 인덱스 라인 >20 | **스킬:** `anthropic-skills:consolidate-memory` · `productivity:memory-management` · **규칙:** PreToolUse Edit matcher (예정) | 인덱스 라인 수, stale (>2분기 미참조) 비율 | #720 |

## Shipping 경로 — `ship-pr` skill vs `make ship-arm`

둘은 **mutually exclusive**. PR commit-0 에 결정 + commit message 명시.

- **`ship-pr` skill** — 수동 게이트. push/merge 각 단계 명시 승인. ADR 번호 예약·stacked-PR 감사 포함. **결정이 무겁거나 stacked PR 이면 이쪽**
- **`make ship-arm`** — Stop훅 기반 자동 ship. 8-step 사전검사 통과 시 commit → push → PR → CI 대기 → squash-merge 자동. **소형/독립 PR 이면 이쪽**

자세한 단계: [`auto-ship.md`](operations/auto-ship.md).

## Follow-up Issues

- **#718** — `scripts/_self_review.py` "diff>50 LOC + Plan 호출 0회" 카운터 (축 #2)
- **#719** — `Makefile` `smoke` 타깃의 `install-hooks` prerequisite (축 #3)
- **#720** — `.claude/settings.json` PreToolUse Edit matcher (MEMORY.md 인덱스 라인 수) (축 #5)
- **#724** — `scripts/_cycle_time.py` ADR lag + PR turnaround collector (축 #4)

각 follow-up = 1 PR / 1 concern. 본 PR 은 **전략 + 활성화 가이드**까지만.

> **Status (2026-05-19)**: 위 4개 follow-up 은 PR #745-#748 로 모두 머지. 측정 인프라 가동 중. Q3-2026 보강은 아래 섹션.

## Q3-2026 보강 컴포넌트

외부 `agency-agents` (191개, MIT) 평가 결과 **0개 채택** 결론을 거쳐 자체 갭만 보강. PR #1013 (PR-A agent 2개) + PR #1015 (PR-B hook 1개) + 본 PR (PR-C 문서) 묶음.

### 컴포넌트 × 5축 cover

| 컴포넌트 | 종류 | 5축 cover | 트리거 | 위치 |
|---|---|---|---|---|
| `eval-to-adr-bridge` | agent | #3 (부분) + #4 (trigger→proposed lag) | `/retrieval-eval` Phase STOP / `/eval-framework-progressive-audit` phase / `make real-eval` 후 | [`.claude/agents/eval-to-adr-bridge.md`](../.claude/agents/eval-to-adr-bridge.md) |
| `memory-curator` | agent | #5 (incremental gate) | 메모리 저장 직전 / `MEMORY.md` ≥180줄 / 사용자 명시 | [`.claude/agents/memory-curator.md`](../.claude/agents/memory-curator.md) |
| `agent-delegation-gate` | hook | #2 (prompt-time delegation nudge) | UserPromptSubmit (모든 prompt, 키워드 매치 시 메시지 emit + fires.log append) | [`scripts/claude-hooks/userpromptsubmit-delegation-gate.sh`](../scripts/claude-hooks/userpromptsubmit-delegation-gate.sh) |

### 갭 분석 (왜 이 3개만)

외부 191개 검토 결과 채택 0개. 근본 원인은 enterprise persona vs research 1인 RAG 결 미스매치. 보편 원칙은 이미 `karpathy-guidelines` skill + CLAUDE.md 로 cover. 자체 갭만 1:1 보강:

- **#2 위임 부족**: UserPromptSubmit hook 0개였음 → prompt 시점 위임 권유 강제 (CLAUDE.md "위임 기본값" 인용). `_self_review.py` `collect_governance_hooks` 가 4-field 포맷의 `agent-delegation` reason 카운터를 기존 `memory-lines` / `load-bearing` 옆에 자동 인식
- **#3 자동화 ROI 일부 + #4 사이클 타임 trigger→proposed**: 측정 결과 → ADR 후보 변환 빈 칸. `reports/cycle_time.json` 에 `adr_proposed` 이벤트 + `trigger_to_proposal_seconds` append 로 정량화. PR open→merge / ADR proposed→accepted lag 는 `_self_review.py` git history 기반 사후 측정으로 이미 가동
- **#5 메모리 위생**: `anthropic-skills:consolidate-memory` skill 은 batch consolidation (주기적). per-save dedup / type 균형 / stale 판단은 LLM judgment 필요한 incremental gate → agent 영역

### 사용 가이드

- `eval-to-adr-bridge`: 측정 후 ADR 작성 결정 단계에서 호출. commit / PR / Status 변경은 영역 외 (`ship-pr` skill 영역)
- `memory-curator`: 메모리 저장 결정 게이트. batch 정리는 `consolidate-memory` skill 영역 (호출 권유만)
- `agent-delegation-gate`: 자동 (사용자 prompt 시점). 항상 exit 0, fail-safe. 트리거 키워드 false-positive 시 description 어휘 조정

### 30일 monitoring 항목

- 각 컴포넌트 호출 빈도 — 0회 시 제거 검토, 양성 시 효과 검증
- agent-delegation-gate false-positive 비율 (트리거 키워드 정확성)
- Q3 self-review 5축 재진단 — 4△ → ✓ 회복 측정 (`/self-review-quarterly Q3-2026`)

### Out-of-scope (별도 작업)

- Agent/Skill 호출도 `.hook-fires.log` 에 기록 (PreToolUse matcher 를 `Agent|Skill|Task` 까지 확장) — 별도 PR
- 트리거 키워드 어휘 조정 — 30일 monitoring 데이터 기반 별도 PR
- ADR 작성 — 새 측정 표면 아님 (기존 surface 위 추가 컴포넌트)

## References

- [`docs/self-review/Q2-2026.md`](self-review/Q2-2026.md) — 5축 진단 원본
- [`docs/multi-agent-ownership.md`](multi-agent-ownership.md) — 7역할 owner 모델
- [`docs/operations/auto-ship.md`](operations/auto-ship.md) — `make ship-arm` 8-step 파이프라인
- [`docs/engineering-governance.md`](engineering-governance.md) — 워크플로 맵
- `MEMORY.md` 항목: `feedback_collaboration_axes.md`, `feedback_agent_delegation.md`, `feedback_q2_2026_collaboration_review.md`
