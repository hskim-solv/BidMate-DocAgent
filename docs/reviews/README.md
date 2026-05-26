# Reviewer System

AI-agent PR의 reviewer system은 [`ai-review-checklists.md`](./ai-review-checklists.md)가
단일 출처(source of truth)다. 이 README는 어떤 checklist를 고를지 알려주는 얇은
라우터다.

## Review Mode Routing

| Mode | Required when |
|---|---|
| Normal Code Review | 모든 non-trivial 코드·설정·테스트·문서 변경 |
| Adversarial Review | AI-agent 생성 PR, load-bearing path, 큰 refactor, claim-heavy PR |
| Benchmark Validity Audit | `eval/`, benchmark, metric, leaderboard, README metric snapshot, performance claim, private aggregate 변경 |
| Regression Review | bug fix, behavior change, RAG pipeline, verifier, answer contract, eval runner, 과거 incident 재발 가능 변경 |
| Documentation / Governance Review | ADR, governance, review, task/process docs, claim boundary 문서, root docs reference 변경 |

## Evidence Standard

Reviewer는 PR 설명을 근거(evidence)로 취급하지 않는다. 승인 가능한 claim은 diff,
실행된 command 결과, test/eval artifact, 관련 ADR/source-of-truth와의 일치 중
하나로 뒷받침되어야 한다.

근거가 없으면 claim은 없는 것으로 처리한다. green CI, synthetic-only success,
깔끔한 agent 요약은 private real-eval 또는 architecture safety 증거가 아니다.

## Fast Triage Surface

현재 open PR, readiness aggregate, private delta 필요 여부를 먼저 좁힐 때는
[`scripts/ai_next_actions.py`](../../scripts/ai_next_actions.py)가 생성하는
`reports/ai_next_actions.html`을 본다. 사용법과 해석 기준은
[`docs/operations/ai-codex-workflow.md`](../operations/ai-codex-workflow.md)에 둔다.

이 HTML은 사람용 상태판이지 승인 근거(evidence)가 아니다. reviewer는 상태판이
가리키는 source artifact와 command 결과를 따로 확인해야 한다.
