---
name: self-review-quarterly
description: |
  Produce a quarterly self-review report combining the 4-axis portfolio rubric (feedback_portfolio_evaluation.md) and the 5-axis Claude collaboration rubric (feedback_collaboration_axes.md). Outputs ✓/△/✗ verdicts per axis with metadata-only citations.

  Trigger when the user invokes `/self-review-quarterly Qx-YYYY`, types "self-review Q2-2026", or asks "지난 분기 협업 어땠어", "Claude 잘 쓰고 있는지 분기로 보자", "Q1 분기 진단", "메타 피드백 분기 보고서". Trigger even if only one rubric is mentioned — this skill always outputs both 4-axis + 5-axis in one report.

  Do NOT trigger for: single-axis question without quarter scope (use the relevant memory directly), ADR-to-signal mapping (use `adr-portfolio-signals` instead), portfolio launch checklist updates, or any per-PR retrospective.
---

# Self-Review Quarterly

Given a quarter (`Qx-YYYY`), produce a structured Markdown report with **two rubric tables** (4-axis portfolio + 5-axis collaboration), evidence citations, and a single highest-ROI improvement bullet. Writes outputs to three locations: `docs/self-review/Qx-YYYY.md` (committed), a memory summary, and the MEMORY.md index.

## Scope

- Single-quarter input only. Format: `Qx-YYYY` (e.g. `Q2-2026`). 4 ≥ x ≥ 1.
- Always outputs **both** rubrics — never one alone. The skill exists to compare portfolio progress against collaboration ROI in one frame.
- Output destinations: `docs/self-review/Qx-YYYY.md` + memory summary + MEMORY.md update. No stdout-only mode.
- Body excerpts from transcripts, tool arguments, code diffs, or memory body are **never** quoted. Metadata-only citations.

## Workflow

1. **Resolve quarter.** Validate `Qx-YYYY` format. On miss, list quarters with at least one commit (`git log --since=YYYY-01-01 --pretty=format:%ai | sort -u`) and stop.

2. **Load rubric definitions.**
   - 4-axis: `~/.claude/projects/-Users-hskim-Desktop-projects-BidMate-DocAgent/memory/feedback_portfolio_evaluation.md` (read the body, treat as source of truth)
   - 5-axis: `~/.claude/projects/-Users-hskim-Desktop-projects-BidMate-DocAgent/memory/feedback_collaboration_axes.md`
   - If either is missing or its referenced docs (e.g. `docs/senior-positioning.md`) are gone, stop and surface the broken pointer.

3. **Collect raw stats.** Invoke the driver via Bash:
   ```bash
   python scripts/claude-hooks/_self_review.py --quarter <Qx-YYYY> --emit-stats > /tmp/self-review-<Qx-YYYY>-stats.json
   ```
   Read `/tmp/.../stats.json` into the skill context. The driver guarantees body-free output by schema; trust it but spot-check (see step 8).

4. **4-axis verdict table.** For each of the 4 portfolio axes, judge `✓` / `△ — <≤30자 사유>` / `✗ — <≤30자 사유>` using the rubric's signals + the stats. Cite metadata only (see "Citation policy" below).

5. **5-axis verdict table.** Same procedure with the 5 collaboration axes.

6. **ROI bullet.** Across all 9 axes, pick the **single** highest-leverage weakness (largest improvement potential × lowest cost). One-line action recommendation for next quarter. Multiple bullets are forbidden — force the prioritization.

7. **Write outputs (three destinations).**
   - **`docs/self-review/Qx-YYYY.md`** (commit-bound) — full template below. Create parent dir if absent.
   - **Memory summary**: `~/.claude/.../memory/feedback_qX_YYYY_collaboration_review.md` (frontmatter `type: feedback`). Body ≤500 chars: one line per rubric (highest weakness + one ✓ highlight) + the ROI bullet. No body excerpts.
   - **MEMORY.md update**: append one line under existing entries: `- [Self-review Qx-YYYY](feedback_qX_YYYY_collaboration_review.md) — <ROI keyword phrase>`.

8. **Self-check before returning.**
   - Both rubric tables present (4 rows + 5 rows). No table omitted.
   - All `partial`/`fail` verdicts carry a factual reason ≤30 chars after the em-dash.
   - All cited paths exist (`ls` or `[ -f ]` each one). All cited PR / ADR / issue numbers are integers, not prose.
   - No body excerpts. Grep the report for forbidden patterns: `"사용자가 말"`, `"user said"`, `"내가 답"`, `"I answered"`, `"```python"` (code block from transcript), `"```diff"`. Any match → rewrite that cell.
   - `docs/self-review/Qx-YYYY.md` written + memory summary written + MEMORY.md updated. Verify all three before reporting completion.

## Citation policy (hard rules)

This skill writes to a **committed git file**. Privacy violations cannot be retracted. Apply both rules.

### 인용 가능 (allowed)

- Tool 이름: `Read`, `Edit`, `Bash`, `Agent`
- 호출 횟수 (숫자), 세션 수, 커밋 수
- 공개 파일 경로: `rag_core.py`, `docs/adr/0028-*.md`, `scripts/_governance.py`
- Git commit hash (≤12 chars): `f5b51fa`
- PR 번호: `PR #458`
- Issue 번호: `issue #461`
- ADR id: `ADR 0023`
- 메모리 파일명 + frontmatter 필드(`name`, `type`, `originSessionId`)
- Stats.json의 모든 값 (driver가 이미 metadata-only 보장)

### 인용 금지 (forbidden)

- 사용자 메시지 본문 (어떤 발화도 paraphrase 포함)
- Assistant 응답 본문 (skill 자기 자신 포함)
- Tool 호출 arguments: 검색 query, edit 내용, Agent prompt 본문
- 코드 diff 내용
- 메모리 본문 (frontmatter 외)
- ADR / 문서 본문 (제목 + id만 OK)
- Commit message body (subject에서 PR 번호 추출만 OK)

### 회피 표현 (selling / vague)

- 자기평가 형용사: `잘 ~`, `매우 ~`, `탄탄한`, `훌륭한`
- 단정 동사: `보장`, `증명`, `완벽`, `최고`
- 평가어 (verdict 사유에서): `좀 부족`, `약간 아쉬움` — 대신 사실: `Q2 6주 ADR 부재`

## Output template

````markdown
# Self-Review Qx-YYYY

- Date range: YYYY-MM-DD – YYYY-MM-DD
- Sessions: N | Commits: N | PRs merged: N | ADR changes: N | Load-bearing touches: N
- Source: `scripts/claude-hooks/_self_review.py` (metadata-only stats; see "Privacy" below)

## 4축 진단 (포트폴리오 진행)

| # | 축 | 평가 | 근거 | 한 줄 코멘트 |
|---|---|---|---|---|
| 1 | 엔지니어링 디스플린 | ✓ / △ — <사유> / ✗ — <사유> | `PR #458`, `docs/engineering-governance.md` | <1-line, ≤80자> |
| 2 | 아키텍처 결정 정합성 | ... | `ADR 0028`, `docs/adr/README.md` | ... |
| 3 | 평가 견고성 (LLM Ops) | ... | `eval/config.yaml`, `reports/eval_summary.json` | ... |
| 4 | 시장 가시성 | ... | `docs/portfolio-launch-checklist.md`, `docs/eval/leaderboard.md` | ... |

## 5축 진단 (Claude 협업)

| # | 축 | 평가 | 근거 (raw signal) | 한 줄 코멘트 |
|---|---|---|---|---|
| 1 | 컨텍스트 효율 | ... | `sessions.tool_call_distribution`, `sessions.agent_delegations` | ... |
| 2 | Agent 위임 패턴 | ... | `axis_2_plan_subagent_skip_rate.skip_rate` (PR #745) | ... |
| 3 | 거버넌스 자동화 ROI | ... | `governance_hooks.pretooluse_loadbearing_fires`, `governance_hooks.fires_by_action` | ... |
| 4 | 사이클 타임 | ... | `axis_4_cycle_time.adr_lag_days`, `axis_4_cycle_time.pr_turnaround_hours` (PR #748) | ... |
| 5 | 메모리 위생 | ... | #5-A `governance_hooks.fires_by_action["memory-lines"]` (PR #747) + #5-B `axis_5_memory_hygiene.content_freshness.fresh_rate` (issue #877) | ... |

## 5축 채점 임계값 (Q3-2026~)

PR #723 → #745 / #747 / #748 시퀀스로 `scripts/claude-hooks/_self_review.py` 가
raw signal을 자동 emit. 본 skill이 그 값을 ✓/△/✗ 로 결정하는 **단일 source of
truth** — collector 코드에 임계 hard-code 금지.

**코드 임계값 SSoT (issue #778)**: bash hook + python collector가 공유하는
숫자 임계 (예: `MEMORY_LINE_AWARE=20`, `AXIS_2_LOC=50`) 는 `scripts/_governance.py`
`THRESHOLDS` dict가 단일 source. `python3 scripts/_governance.py --threshold KEY`
CLI로 조회. 본 SKILL.md는 그 값들을 **밴드(✓/△/✗)로 매핑하는 결정 룰**의
SoT — 두 SoT는 직교한다 (값 vs 채점 등급).

| 축 | Signal path | ✓ | △ | ✗ |
|---|---|---|---|---|
| #1 컨텍스트 효율 | `sessions.agent_delegations["Explore"]` 호출 / 분기 | ≥ 2 + Read 평균 ≤ 메인 대화당 10회 | 둘 중 하나 미달 | 둘 다 미달 |
| #2 Agent 위임 | `axis_2_plan_subagent_skip_rate.skip_rate` | ≤ 0.2 | 0.2–0.5 | > 0.5 |
| #3 자동화 ROI | `governance_hooks.pretooluse_loadbearing_fires` + `fires_by_action` 다양성 | fires > 0 **그리고** ≥ 2개 reason 발화 (e.g. `load-bearing` + `memory-lines`) | fires > 0 그러나 1개 reason만 | fires = 0 |
| #4-A 사이클 타임 (ADR) | `axis_4_cycle_time.adr_lag_days.mean` (days) | ≤ 5 | 5–10 | > 10 |
| #4-B 사이클 타임 (PR) | `axis_4_cycle_time.pr_turnaround_hours.mean` (hours) | ≤ 48 | 48–120 | > 120 |
| #5-A 메모리 인덱스 위생 | `governance_hooks.fires_by_action["memory-lines"]` 카운트 (action="aware" / "blocked") | blocked=0 + aware ≤ 2 | aware ≥ 3 + blocked=0 | blocked ≥ 1 (편집 차단 = 인덱스 폭발) |
| #5-B 메모리 콘텐츠 신선도 | `axis_5_memory_hygiene.content_freshness.fresh_rate` (분기 내 수정된 메모리 파일 비율) | ≥ 0.5 | 0.2–0.5 | < 0.2 또는 `null` |

**판정 규칙:**
- 동일 축이 sub-signal 두 개를 가질 때(예: #4-A + #4-B), **둘 다 ✓** 이어야 ✓; 하나라도 ✗면 ✗; 그 외 △.
- raw signal 이 `null` / `count=0` 이면 측정 부재 — △ 표기 + "측정 인프라 미작동" 한 줄.
- `p90` 이 `mean` 보다 현저히 크면 (> 2×) outlier 가능성 — `pr_turnaround_hours.max` 확인 후 reopened-PR 영향 한 줄 명시.

## 최우선 개선점 (ROI)

<단 하나의 약점 축 + 다음 분기 1–3줄 action>

## Privacy

이 보고서는 `_self_review.py`가 emit한 메타데이터(tool 호출 횟수, 공개 파일 경로, git hash, PR/issue/ADR id, 메모리 frontmatter)만 인용합니다. 사용자 메시지·assistant 응답·tool arguments·코드 diff·메모리 본문은 포함되지 않습니다. 검증: 본 파일에 `user said` / `사용자가 말` / `assistant: ` / `\`\`\`python` 패턴 없음.
````

## What this skill does NOT do

- Does NOT make any decision *for* the user. The user reads the report and decides where to invest next quarter.
- Does NOT propose ADRs or implement fixes. Recommendations are 1–3 line bullets — implementation is a separate task.
- Does NOT compare quarters (Q1 vs Q2). Single-quarter only. Multi-quarter trend is a follow-up skill.
- Does NOT call MCP search tools to read transcripts. The driver parses `.jsonl` directly and emits metadata-only stats.
- Does NOT quote any body content from transcripts, code, or memory bodies. Frontmatter and identifiers only.
- Does NOT write to `docs/senior-positioning.md`. Narrative integration ("signal 6") is a separate PR.

## Failure modes to watch

- **Driver returns empty sessions**: transcripts glob mismatch. Verify path with `ls ~/.claude/projects/.../*.jsonl`. Do not invent fallback data — report "0 sessions" and stop.
- **Memory rubric file moved**: `feedback_portfolio_evaluation.md` or `feedback_collaboration_axes.md` not at expected path. Surface this; do not proceed with degraded rubric.
- **Quarter has no commits**: report "no activity this quarter" instead of fabricating axes. Both rubrics still output, but every row is `✗ — no data` with that fixed sentence.
- **Memory MEMORY.md write race**: if MEMORY.md update would create a duplicate index line, deduplicate first by reading and rewriting. Do not silently append.
