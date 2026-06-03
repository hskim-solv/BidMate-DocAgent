# Long-Session AI Workflow

이 문서는 multi-day 또는 multi-week AI-agent 작업을 context loss 없이 이어가기 위한
운영 절차다. 목표는 agent가 같은 결정을 재탐색하지 않고, architecture consistency와
eval validity를 유지하며, reviewer가 검증 가능한 근거(evidence)를 받게 하는 것이다.

## When To Use

다음 중 하나면 long-session workflow를 사용한다.

- 작업이 하루를 넘기거나 여러 Codex/Claude 세션으로 나뉜다.
- `tasks/queue.md`의 task가 `running`, `blocked`, `review` 상태로 남는다.
- plan doc가 필요한 범위다.
- load-bearing path, eval/benchmark, ADR, private real-eval evidence가 관련된다.
- 여러 worktree 또는 여러 agent가 같은 목표를 나눠 맡는다.

## Start Checklist

1. [`CLAUDE.md`](../../CLAUDE.md)와 현재 task entry를 읽는다.
2. [`tasks/queue.md`](../../tasks/queue.md)에서 task status와 owner role을 확인한다.
3. [`docs/operations/ai-engineering-operating-system.md`](./ai-engineering-operating-system.md)에서
   role, evidence, review escalation을 확인한다.
4. plan doc가 있으면 먼저 읽고, 없는데 필요한 범위면 구현 전에 만든다.
5. `python3 scripts/agent_loop.py overlap-preflight --issue <N> --branch <type>/issue-<N>-<slug>`로
   Codex/Claude Code/외부 worktree의 같은 issue·branch·PR 진행 여부를 확인한다.
6. `git status --short --branch`로 worktree 상태를 확인한다.
7. 관련 ADR과 eval surface를 확인한다.
8. 다음 safe command를 정하고 실행한다.

## Context Preservation Rules

- 중요한 결정은 채팅 transcript에만 두지 않는다. plan doc 또는 task queue에 남긴다.
- "나중에 해야 함"은 queue의 acceptance criteria, blocked reason, next action으로
  옮긴다.
- 성능 claim은 raw memory가 아니라 dataset/config/provenance/command/result artifact로
  남긴다.
- Private raw question, answer, evidence, doc/chunk id, exact local path는 handoff에
  쓰지 않는다.
- ADR 번호, PR base, stacked dependency, private artifact 위치는 handoff마다 갱신한다.

## RAG Performance Loop Check

RAG 성능 개선 관련 long session은 handoff마다 8개 운영 원칙을 짧게 점검한다.

- Broad scope: program-level RAG outcome과 현재 PR concern이 분리되어 있는가?
- Long session: 다음 session이 queue/plan/handoff만 읽고 이어갈 수 있는가?
- File-backed todo: next action, blocker, completion proof가 tracked file에 있는가?
- Plan doc: broad, multi-file, eval, 또는 load-bearing work라면 plan이 있는가?
- Adversarial review: Reviewer, Deep Reviewer, Benchmark Auditor, Privacy Auditor 중
  필요한 역할이 지정됐는가?
- Role split: Planner, Implementer, Tester/CI Reviewer, Issue Triage 역할이 한
  session에 과하게 몰려 있지 않은가?
- Human outside loop: 사람이 직접 실행한 terminal/PR/CI 단계가 있으면 agent가
  증거를 double-check했는가?
- Process improvement: 반복 실수는 instruction, harness, review prompt, queue/plan
  개선으로 이어졌는가?

## Handoff Template

세션 종료, context compaction 전, blocked 전환, review 요청 전에 아래 block을 남긴다.
위치는 task entry 하단 또는 plan doc의 "Session Handoff" 섹션이다.

```markdown
## Session Handoff — YYYY-MM-DD HH:MM TZ

- Role:
- Lifecycle stage:
- Branch / worktree:
- Base branch:
- Overlap preflight: clear/warn/blocked + evidence path
- Issue / PR:
- Task:
- Plan:
- Current status:
- Files touched:
- Decisions made:
- Commands run:
- Results:
- Validation evidence:
- Eval surface:
- Evidence artifacts:
- Blockers:
- Open risks:
- Next action:
- Next safe command:
- Reviewer focus:
```

## Branch And Worktree Guidance

- 한 worktree는 한 task 또는 한 PR concern에 묶는다.
- Stacked PR이면 base branch와 upstream PR 번호를 handoff에 적는다.
- ADR 작성 전 `python scripts/_governance.py --next-adr-number`와
  `gh pr list --search "ADR" --state open --json number,title,headRefName`를 확인한다.
- `reports/eval_summary.json`류 산출물을 비교하기 전 dataset/config/index/provenance를
  handoff에 적는다.
- 고정 `/tmp/<name>` output path를 쓰지 않는다. 필요하면 `mktemp`를 사용한다.

## Issue Batching

Batching은 같은 failure mode 또는 같은 measurement surface 안에서만 한다.

허용:

- 하나의 benchmark hardening plan 아래 validator, docs, regression test를 나눈다.
- retrieval measurement surface를 추가하고 그 산출 report를 같은 PR에 포함한다.

금지:

- eval scorer 변경과 retrieval algorithm 변경을 같은 PR에 섞는다.
- ADR status 변경과 unrelated product fix를 묶는다.
- private real-eval aggregate 업데이트와 README narrative rewrite를 한 concern처럼 처리한다.

## ADR Usage

ADR은 큰 문서가 아니라 load-bearing decision의 고정점이다. 다음이면 ADR을 고려한다.

- baseline/pipeline/answer contract/eval surface를 제거, 교체, 의미 변경한다.
- 새 measurement surface를 도입해 reviewer가 의존할 artifact가 생긴다.
- 두 선택지 중 하나를 택했고, 나중에 그 trade-off를 방어해야 한다.

Routine bug fix, typo, small refactor는 ADR 없이 PR 설명에 남긴다.

## Preventing Rediscovery

장기 agent가 같은 결정을 반복하지 않게 하려면:

- task entry에 "Decisions already made"를 유지한다.
- plan doc에는 rejected alternatives를 적는다.
- eval surface는 [`docs/evaluation/surface-map.md`](../evaluation/surface-map.md)를 링크한다.
- reviewer가 지적한 non-blocking risk는 follow-up task로 분리한다.
- 막힌 이유는 "blocked" 상태와 unblock command로 적는다.

## Continuation Prompt

새 AI-agent 세션을 시작할 때는 아래처럼 넘긴다.

```text
Role: Implementer
Repo: BidMate-DocAgent
Task: <task id and title>
Read first:
- CLAUDE.md
- docs/operations/ai-engineering-operating-system.md
- tasks/queue.md entry <id>
- docs/plans/<plan>.md
- docs/evaluation/surface-map.md if eval/benchmark is touched
Continue from the latest Session Handoff.
Do not expand scope beyond acceptance criteria.
Before final response, update the task status and evidence.
```

## Done Criteria

Long-session task는 다음이 모두 충족되어야 done이다.

- queue status가 `done`이고 PR/commit/evidence 링크가 있다.
- plan acceptance criteria가 충족되거나 명시적으로 revised되었다.
- validation commands가 실제 실행 결과와 함께 기록됐다.
- reviewer/deep reviewer/benchmark auditor가 필요한 경우 checklist 결과가 있다.
- 남은 위험이 follow-up task 또는 PR note로 분리됐다.
