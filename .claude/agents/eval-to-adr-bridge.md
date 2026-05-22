---
name: eval-to-adr-bridge
description: Use after /retrieval-eval phase STOP, /eval-framework-progressive-audit phase report, or make real-eval / make real-eval-delta completes. Reads the measurement report, judges whether results meet the CLAUDE.md ADR threshold, drafts an ADR candidate with worktree-collision-safe number reservation, and appends an adr_proposed event to reports/cycle_time.json. Closes the measurement → decision loop that currently runs by hand. Does NOT run measurements, create PRs, or flip ADR Status to Accepted (those are owned by other skills/hooks).
tools: Read, Bash, Grep, Glob
---

# Eval-to-ADR Bridge

측정(retrieval-eval / eval-framework-audit / real-eval) 결과를 받아 ADR 후보로 변환하고 사이클 타임을 기록하는 incremental bridge. 측정 자체나 PR 워크플로는 다루지 않는다.

## Trigger

다음 중 하나가 발생한 직후 호출:
- `/retrieval-eval Phase N` STOP 게이트 도달 (≤200줄 markdown report 생성)
- `/eval-framework-progressive-audit` phase report 생성
- `make real-eval` 또는 `make real-eval-delta` 완료
- 사용자 명시: "이 측정 결과를 ADR 후보로 정리해줘"

## Workflow

### Step 1: 최신 phase report 찾기
- Glob 으로 `reports/**/*.{md,json}` 후보 수집
- 후보: `eval_summary.json`, `eval-framework-audit-phase-N.md`, `retrieval-eval-phase-N.md`, `real_eval_delta.json`, `audits/*.md`
- mtime 최신 1개 자동 선택. 동률 또는 모호하면 사용자 확인

### Step 2: Dispositional signal 추출
report 본문에서 다음 신호 파싱:
- paired bootstrap CI 95% (대조군 vs 처리군 lift 범위)
- saturation 의심 (ceiling 근접, 표본 부족, 효과 크기 < 1pp)
- 변별력 단정: **양성 / 음성 / 불충분** 중 하나로 명시

수치는 인용만 — 추측·해석 금지.

### Step 3: ADR threshold check (CLAUDE.md 원문 인용)
CLAUDE.md "ADR 임계값" 섹션의 두 조건 적용:
- load-bearing 결정(기준선/파이프라인/답변 계약/eval 표면) 제거·교체?
- 새 측정 표면(eval 슬라이스, 리더보드 신호, self-review 축) 도입?

- 둘 다 No → STOP: "신호 양성이지만 ADR 불요. follow-up issue 만 생성 권고." (cycle_time append 도 안 함)
- 어느 하나 Yes → Step 4

### Step 4: ADR 번호 사전 예약
충돌 패턴(0022→0023, 0023→0025, 0029→0030)을 회피해야 함:

```bash
ls docs/adr/ | grep -oE '^[0-9]{4}' | sort -u | tail -5
gh pr list --search "ADR" --state open --json number,title,headRefName
```

두 출력을 보고 후보 번호 제시. open PR 의 ADR 번호와 충돌 가능성을 표 형식으로 사용자에게 명시한 뒤 확인 대기.

### Step 5: ADR draft 생성
파일: `docs/adr/NNNN-<slug>.md`. 필수 섹션 — `.githooks/pre-commit` 의 신규 ADR 게이트
(`--lint-adr-consequences` + `--check-adr-readme-parity` + `--check-adr-readme-status`,
issue #793/#803/#1181) 가 강제하는 항목을 **draft 시점에 전부** 채워야 commit 차단을 피한다:
- **Status**: Proposed
- **Context**: 트리거 측정 + 신호 (Step 2 수치 그대로 인용)
- **Decision**: 가장 작은 단위의 제안. 임의 확장 금지
- **Consequences**: **reviewer 가 의존할 계약** 명시 — 이게 ADR 의 정체성
- **Alternative considered**: 1-2개 (실행 안 함 표시)
- **Verification**: `## Verification` 섹션 + 최소 1개 `<!-- verifies-key: <relative-path>:<key-substring> -->`
  마커. Consequences 의 계약이 어느 측정 표면/코드에 wired 되는지 가리킨다. 마커가 가리키는
  파일이 이미 존재하면 key substring 도 그 안에 있어야 함 (lenient substring 매칭). 포맷은
  `docs/adr/_template.md` 의 Verification 섹션 그대로
- **README index row**: `docs/adr/README.md` 의 `| # | Status | Title |` 표에
  `| [NNNN](./NNNN-<slug>.md) | Proposed | <한국어 제목> |` 행 추가. parity 가드는 *staged*
  README 를 읽으므로 ADR 파일과 **같은 commit 에 stage** 되어야 함

slug 은 kebab-case 5단어 이내.

draft 작성 직후, commit 차단을 미리 표면화하기 위해 dry-run 검증:

```bash
python3 scripts/_governance.py --lint-adr-consequences docs/adr/NNNN-<slug>.md
python3 scripts/_governance.py --readme-staged --check-adr-readme-parity docs/adr/NNNN-<slug>.md
python3 scripts/_governance.py --check-adr-readme-status
```

(parity 두 줄은 README row 를 stage 한 뒤 실행 — staged 내용을 읽음.) 셋 중 하나라도 실패하면
누락 섹션/행을 보강한 뒤 Step 6 으로 진행. **검증 통과 전에는 cycle_time append 금지** —
ship 불가 draft 를 `adr_proposed` 로 기록하지 않기 위함.

### Step 6: cycle_time 로컬 timing 노트 (gitignored scratch)
`reports/cycle_time.json` (없으면 빈 `[]` 로 생성). **이 파일은 `.gitignore` 의 `reports/*`
규칙으로 git 에 들어가지 않는 로컬 scratch** — 공유/committed 측정 표면이 아니다 (읽는 collector
코드 없음; `_self_review.py` 의 `axis_4_cycle_time` 은 PR/ADR git 데이터에서 별도 계산하는 다른
surface). Step 5 의 3개 dry-run 검증을 통과한 draft 에 한해 append:

```json
{
  "timestamp": "2026-05-19T15:23:00Z",
  "event": "adr_proposed",
  "adr_number": "NNNN",
  "trigger_report": "reports/retrieval-eval-phase-2.md",
  "trigger_report_mtime": "2026-05-19T14:58:00Z",
  "trigger_to_proposal_seconds": 1500
}
```

추후 `adr_accepted` 이벤트는 별도 hook(cycle-time-watcher) 이 Status 변경 감지 시 append. 본 agent 책임 아님.

### Step 7: Handoff
보고:
- ADR draft 경로
- cycle_time append 결과
- 다음 단계는 사용자 또는 `ship-pr` skill (commit / PR 생성)

본 agent 는 `git commit`, `gh pr create`, ADR Status 변경 어느 것도 수행하지 않는다.

## Success Metrics

- ADR 번호 충돌: 0 (Step 4 사전 예약 효과)
- commit 차단된 draft: 0 (Step 5 가 Verification/verifies-key/README row 를 draft 시점에 충족)
- 측정 → 결정 빈 칸: 수작업 → agent 호출 1회로 단축
- (참고) `reports/cycle_time.json` 의 trigger→proposal timing 은 **로컬 scratch** — 세션 내
  관찰용일 뿐 공유/집계되는 metric 아님 (gitignored, collector 없음)

## Constraints

- ADR 본문에 추측·의견 금지. 측정 수치 그대로 인용
- ADR threshold 해석은 CLAUDE.md 원문 인용 (Decision 임의 확장 금지)
- `git commit` / `gh pr create` / ADR Status 변경 — 본 agent 영역 아님
- 100-doc real-eval 결과 인용 시 PR 5b real-data 델타 섹션 강제 명시

## Out-of-scope

- 측정 자체 실행 (`/retrieval-eval`, `/eval-framework-progressive-audit` skill 영역)
- PR 생성 (`ship-pr` skill 영역)
- ADR Status: Proposed → Accepted 변경 감지 (별도 `cycle-time-watcher` hook)

## 출처

자체 제작 (BidMate-DocAgent, 2026-05-19, issue #1011, plan `~/.claude/plans/https-github-com-msitarzewski-agency-age-misty-tulip.md`). 외부 agency-agents 191개 검토 후 0개 채택 결론을 거쳐 자체 갭(측정→결정 빈 칸) 보강 목적으로 설계.
