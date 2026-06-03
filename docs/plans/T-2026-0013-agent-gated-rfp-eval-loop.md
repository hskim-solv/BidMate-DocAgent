# T-2026-0013 — Agent-gated offline/online RFP eval loop

- Status: review
- Owner role: Maintainer -> Reviewer
- Related ADR: [ADR 0079](../adr/0079-agent-gated-offline-online-rfp-eval-loop.md)

## Goal

Codify the conservative agent-gate policy for continuing RFP QA evaluation across
offline and online environments without requiring a human gate on every routine
claim, current `real100_v2` private eval, shipping, or cleanup decision.

## Scope

- Add ADR 0079 for the durable policy decision.
- Add an evaluation policy document defining the environment axis, RFP success,
  metric suite, adoption criteria, loop termination, and agent gate defaults.
- Update the surface map and Codex workflow docs to point at the new policy.
- Update the task queue handoff.

## Non-Goals

- Do not change RAG runtime behavior.
- Do not run current `real100_v2` private real-eval in this documentation PR.
- Do not rename legacy `human-gated-*` CLI commands.

## Acceptance Criteria

- [x] ADR 0079 exists and has verification markers.
- [x] The policy defines offline/online environment assumptions.
- [x] The policy makes current `real100_v2` aggregate-only private real-eval mandatory for claim-bearing evidence.
- [x] The policy defines metric-suite adoption and loop termination criteria.
- [x] Existing surface map links the new policy.

## Validation Commands

```bash
python3 scripts/_governance.py --lint-adr-consequences docs/adr/0079-agent-gated-offline-online-rfp-eval-loop.md
python3 scripts/check_doc_links.py --check-all --paths docs/adr/0079-agent-gated-offline-online-rfp-eval-loop.md docs/evaluation/agent-gated-rfp-eval-loop.md docs/evaluation/surface-map.md docs/operations/ai-codex-workflow.md docs/plans/T-2026-0013-agent-gated-rfp-eval-loop.md tasks/queue.md
git diff --check
make check-branch
```

## Handoff Notes

```markdown
## Session Handoff — 2026-05-26 KST

- Role: Maintainer
- Lifecycle stage: review
- Branch / worktree: docs/issue-1529-agent-gated-eval-loop / /Users/hskim/.codex/worktrees/1c21/BidMate-DocAgent
- Issue / PR: #1529 / PR TBD
- Task: T-2026-0013
- Plan: docs/plans/T-2026-0013-agent-gated-rfp-eval-loop.md
- Current status: policy docs implemented; focused validation passed.
- Files touched: docs/adr/0079-agent-gated-offline-online-rfp-eval-loop.md, docs/evaluation/agent-gated-rfp-eval-loop.md, docs/evaluation/surface-map.md, docs/operations/ai-codex-workflow.md, docs/adr/README.md, tasks/queue.md, docs/plans/T-2026-0013-agent-gated-rfp-eval-loop.md
- Decisions made: Codex acts as conservative agent gate; current `real100_v2` aggregate-only private real-eval is mandatory for claim-bearing evidence; metric suite beats single headline score.
- Eval surface: governance docs only; no metric claim.
- Commands run: python3 scripts/_governance.py --lint-adr-consequences docs/adr/0079-agent-gated-offline-online-rfp-eval-loop.md; python3 scripts/check_doc_links.py --check-all --paths docs/adr/0079-agent-gated-offline-online-rfp-eval-loop.md docs/evaluation/agent-gated-rfp-eval-loop.md docs/evaluation/surface-map.md docs/operations/ai-codex-workflow.md docs/plans/T-2026-0013-agent-gated-rfp-eval-loop.md tasks/queue.md; git diff --check; make check-branch
- Results: pass.
- Next safe command: git diff --check
- Reviewer focus: claim boundary, online private-data egress provenance, no runtime behavior change.
```
