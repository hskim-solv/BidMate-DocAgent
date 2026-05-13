# Self-Review Quarterly Reports

분기마다 한 번씩 산출되는 메타-피드백 보고서가 이 디렉토리에 누적된다. 각 파일 `Qx-YYYY.md`는 두 rubric을 한 묶음으로 평가한다.

## 두 rubric

| Rubric | 평가 대상 | 정의 위치 |
|---|---|---|
| **4축 — 포트폴리오 진행** | 엔지니어링 디스플린 / 아키텍처 정합성 / 평가 견고성 / 시장 가시성 | `memory/feedback_portfolio_evaluation.md` |
| **5축 — Claude 협업** | 컨텍스트 효율 / Agent 위임 / 거버넌스 자동화 ROI / 사이클 타임 / 메모리 위생 | `memory/feedback_collaboration_axes.md` |

4축은 *프로젝트가 어떻게 굴러가는가*, 5축은 *Claude와의 협업이 어떻게 굴러가는가*. 두 진단이 한 보고서에 나란히 들어가야 ROI 비교가 가능하다.

## 생성 방법

1. **Raw skeleton** — `make self-review-quarterly QUARTER=Qx-YYYY`
   - 호출 대상: [`scripts/claude-hooks/_self_review.py`](../../scripts/claude-hooks/_self_review.py)
   - 산출물: `Qx-YYYY.md`에 counts/identifiers만 (메타데이터 only)

2. **Verdict tables** — Claude Code 내에서 `/self-review-quarterly Qx-YYYY`
   - 호출 대상: [`.claude/skills/self-review-quarterly/SKILL.md`](../../.claude/skills/self-review-quarterly/SKILL.md)
   - 산출물: 4축 + 5축 ✓/△/✗ 평가표 + ROI 1개 추천

두 단계 모두 동일 driver를 호출하지만, 단계 1은 raw counts만, 단계 2는 LLM이 rubric을 적용해 판정한다.

## Privacy 경계 (commit policy)

이 디렉토리의 모든 파일은 **git에 commit되어 공개된다**. 따라서 driver와 skill 모두 다음 원칙을 따른다.

### 인용 가능
- Tool 이름 (`Read`, `Edit`, `Bash`, `Agent`)
- 호출 횟수, 세션 수, 커밋 수
- 공개 파일 경로 (`rag_core.py`, `docs/adr/...`)
- Git commit hash (≤12 chars)
- PR 번호, Issue 번호, ADR id
- 메모리 파일명 + frontmatter 필드 (name, type, originSessionId)

### 인용 금지 (privacy violation)
- 사용자 메시지 본문 (paraphrase 포함)
- Assistant 응답 본문
- Tool 호출 arguments (검색 query, edit 내용, Agent prompt)
- 코드 diff 내용
- 메모리 본문 (frontmatter 외)
- ADR / 문서 본문 (제목/id만 OK)
- Commit message body (subject의 PR 번호만 OK)

위반 검출: 보고서 self-check 단계에서 `사용자가 말`, `user said`, `assistant: `, ``` ```python ``` 같은 패턴 grep. 매치 발견 시 해당 cell 재작성.

## 파일 명명 규칙

- 분기 단위: `Q1-2026.md`, `Q2-2026.md`, ...
- 한 분기 = 3개월 (Q1: 1–3월, Q2: 4–6월, Q3: 7–9월, Q4: 10–12월)
- 같은 분기 재생성 시 덮어쓰기 (driver 동작) — 분기 도중 진척이 반영됨

## 메모리 연동

각 보고서는 메모리에 요약본을 적재한다:
- 파일명: `feedback_qX_YYYY_collaboration_review.md`
- 위치: `~/.claude/projects/-Users-hskim-Desktop-projects-BidMate-DocAgent/memory/`
- 내용: ≤500자 요약 + ROI bullet (본문 인용 없음)
- MEMORY.md 인덱스에 한 줄 자동 추가

이는 다음 세션부터 "지난 분기 협업 어땠어" 질문이 들어왔을 때 메모리가 자동 적용되게 한다.

## 비-목표

- **Per-PR 후고**: 본 보고서는 분기 단위. PR마다 retrospective가 필요하면 별도 도구 필요.
- **Multi-quarter trend**: Q1 vs Q2 비교는 별도 skill로 분리할 수 있다 (현재 미구현).
- **`docs/senior-positioning.md` 자동 갱신**: 시그널 narrative에 6번째 축("협업 측정")을 추가하는 작업은 별도 PR로 분리. 본 디렉토리는 그 narrative 갱신의 *증거 자료*가 된다.
