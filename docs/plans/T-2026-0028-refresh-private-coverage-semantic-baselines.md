# Plan: T-2026-0028 Refresh private coverage and semantic baselines

- Status: done
- Owner role: Evaluator -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0028`
- Related issue / PR: [#1618](https://github.com/hskim-solv/BidMate-DocAgent/issues/1618) / [#1619](https://github.com/hskim-solv/BidMate-DocAgent/pull/1619); refresh issue [#2146](https://github.com/hskim-solv/BidMate-DocAgent/issues/2146)
- Related ADR: [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md), [ADR 0048](../adr/0048-realN-metrics-extension.md), [ADR 0052](../adr/0052-real-eval-hardcase-expansion-to-200.md), [ADR 0058](../adr/0058-phase35-mode-winner.md)
- Created: 2026-05-28
- Last updated: 2026-06-04

## Problem Statement

The current RAG performance work needs a fresh aggregate-only private
`real100_v2` baseline packet after page metadata recovery and MiniLM target
separation. Without that packet, later retrieval or latency experiments can
compare against stale `real100`/v1 corpus, index, backend, or metric provenance
and overstate performance claims.

## Current Behavior

`tasks/queue.md` marks `T-2026-0028` as the first ready P0 task before behavior
changes. Downstream work such as retrieval diagnostics (`T-2026-0029`), latency
provenance (`T-2026-0030`), and metadata coverage follow-ups depend on this
baseline refresh. The task previously had no issue-linked branch, no plan, and
no v2-only guard. Older `real100` artifacts remain historical evidence only and
must not drive this task.

## Desired Behavior

Produce a reviewer-ready, aggregate-only `real100_v2` baseline packet that
records the command sequence, private eval surface, provenance, privacy result,
and go/no-go next task decision. The packet must not claim performance
improvement unless a valid paired delta exists under matching v2 dataset,
config, index, and backend conditions.

## Constraints

- Scope constraints: documentation, eval execution evidence, provenance, and
  handoff only.
- Architecture constraints: do not change ingestion, retrieval, reranking,
  answer, prompt, verifier, eval scoring, or runtime behavior.
- Compatibility constraints: preserve ADR 0001 naive baseline and ADR 0003
  answer contract.
- Eval/privacy constraints: private outputs are aggregate-only; do not commit
  raw question, answer, evidence, filename, local path, `doc_id`, or `chunk_id`.
- V2-only constraints: do not use `data/index/real100`, `reports/real100`,
  `outputs/real100`, or old 221-case aggregates for this task.
- Tooling/CI constraints: branch must pass ADR 0007; generated agent-loop
  artifacts remain ignored local state.
- Non-goals: no RAG quality improvement claim, no new benchmark surface, no
  BGE-M3 requirement if local dependencies or index provenance are unavailable.

## Architecture Impact

- Affected modules or docs: `tasks/queue.md`, this plan, aggregate-only
  evidence docs/reports, v2-only guard, and private eval workflow docs.
- Affected contracts or invariants: private real-eval claim boundary and
  aggregate-only privacy boundary.
- Load-bearing paths: none expected.
- ADR required: no, because this refreshes evidence under existing ADRs.
- Backward compatibility expectation: no behavior or public API change.

## Affected Interfaces

- CLI/API/config: `make real-eval-v2-check`, `make real-eval-v2-inventory`,
  `make real-eval-v2-guard`, and private readiness scripts only.
- Input data: local private `real100_v2` config and canonical v2 private
  data/index roots.
- Output artifacts: ignored private run outputs plus a committed aggregate-only
  summary if privacy-clean.
- Docs/review surfaces: queue entry, plan handoff, PR body, benchmark/privacy
  review notes.
- Tests/eval entrypoints: private readiness checks and real-eval make targets.

## Data / Eval Impact

- Surface: private real-eval.
- Data boundary: aggregate-only private output.
- Allowed claim: `real100_v2` baseline/provenance was refreshed; paired delta is valid only
  if base/head artifacts share comparable dataset, config, index, and backend.
- Disallowed claim: performance improvement from a single run, synthetic-only
  result, hashing path, or mismatched provenance.
- Baseline or control affected: yes, the task refreshes baseline evidence but
  does not change baseline behavior.
- Benchmark/eval auditor required: yes.

## Task Breakdown

1. Bootstrap issue-linked branch and regenerate active-loop start artifacts for
   `T-2026-0028`.
2. Run v2 inventory/check/guard and record missing config/data/index blockers if
   they appear.
3. Use existing `real100_v2` aggregate artifacts or an explicitly v2-configured
   local run only; do not run default `make real-eval`.
4. Write an aggregate-only baseline packet with command transcript summary,
   provenance, privacy result, paired-delta validity, and next-task decision.
5. Run branch, diff, privacy, and claim checks before PR preparation.

## Acceptance Criteria

- [ ] Aggregate packet reports v2 answerable/unanswerable counts, explicit gold
  evidence coverage, multi-document/multi-chunk counts, page/page_span coverage,
  retrieval/answer/abstention metrics, latency, embedding backend/model/dim, and
  vector DB backend when available.
- [ ] Hashing, MiniLM, semantic, and optional BGE-M3 surfaces are not compared
  unless dataset, config, index, command, and provenance match the claim wording.
- [ ] `make real-eval-v2-guard` passes, proving this task does not refer to
  stale `real100`/221 evidence.
- [ ] Any committed artifact passes privacy checks and omits raw private content,
  filenames, local paths, `doc_id`, and `chunk_id`.
- [x] Handoff names the next task as `T-2026-0029`, `T-2026-0030`, or an explicit
  no-go blocker with verification command.

## Validation Strategy

Commands that must be run:

```bash
make check-branch
git diff --check
REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent make real-eval-v2-inventory
REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent make real-eval-v2-check
make real-eval-v2-guard
python3 scripts/audit_private_data_readiness.py --config /Users/hskim/Desktop/projects/BidMate-DocAgent/data/private/real100_v2/real_config_v2.local.yaml --out-dir experiments/private_runs/readiness_audit
python3 scripts/agent_loop.py privacy-audit-output
python3 scripts/agent_loop.py claim-audit --from-git
```

Expected evidence:

- Test/eval output: command transcript summary with pass/fail and paths limited
  to public-safe or ignored aggregate locations.
- Generated or updated artifact:
  `docs/evaluation/real100_v2-baseline-refresh.md` and PR body draft.
- Reviewer checklist or manual inspection: Benchmark Validity Audit and privacy
  boundary review.
- Explicitly not validated, with reason: BGE-M3 comparison if dependencies or
  matching index provenance are missing.

## Rollback Strategy

Revert tracked queue/plan/evidence docs if the packet is invalid or misleading.
Do not delete private raw run artifacts automatically; leave ignored private
outputs in place for manual inspection or cleanup outside the tracked tree.

## Failure Modes

- Failure mode: private v2 config, data, or index missing.
- Detection signal: readiness script failure.
- Stop condition or fallback: record exact missing item and verification command,
  then mark the task no-go until the private root is restored.

- Failure mode: aggregate packet leaks private identifiers or local paths.
- Detection signal: privacy audit finding or reviewer inspection.
- Stop condition or fallback: remove the committed artifact, regenerate from
  aggregate-only fields, and rerun privacy checks.

- Failure mode: metric wording compares mismatched or stale v1/v2 surfaces.
- Detection signal: claim audit or benchmark auditor finding.
- Stop condition or fallback: downgrade wording to provenance refresh only.

- Failure mode: v2 page metadata remains absent.
- Detection signal: `reports/real100_v2/parse_inventory.aggregate.json` reports
  page metadata ready rate 0.0.
- Stop condition or fallback: treat claim-bearing page/citation work as no-go;
  allow `T-2026-0029` only as diagnostic work that preserves this blocker.

## Observability

- `reports/agent_loop/active/` for ignored local start/readiness artifacts.
- Readiness command output for private config/data/index availability.
- Aggregate-only packet for counts, coverage, metrics, latency, backend/model,
  privacy result, and next task.
- PR body for final claim boundary and validation summary.

## Reviewer Notes

Attack claim wording, provenance comparability, privacy boundary, and whether
the next-task decision is supported by aggregate evidence. Do not review this as
a runtime behavior change unless runtime files are unexpectedly modified.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-28 KST

- Role: Evaluator
- Lifecycle stage: done
- Branch / worktree: eval/issue-1618-refresh-private-coverage-and-semantic-baselines / PR #1619
- Issue / PR: #1618 / #1619; refresh issue #2146
- Task: T-2026-0028
- Current status: merged in PR #1619; queue marks T-2026-0028 done. The v2-only policy/guard and aggregate packet are in place, and legacy real100/v1 targets fail closed.
- Files touched: Makefile, CLAUDE.md, scripts/check_real100_v2_only.py,
  tests/test_real100_v2_guard.py, tests/test_smoke_real_script.py,
  docs/evaluation/private_real_eval_workflow.md, docs/evaluation/surface-map.md,
  docs/evaluation/real100_v2-baseline-refresh.md, this plan, tasks/queue.md
- Decisions made: all future private eval tasks use real100_v2 only until the
  maintainer explicitly re-enables legacy evidence; default legacy make targets
  fail closed.
- Commands run: make ship-start TITLE="Refresh private coverage and semantic baselines" TYPE=eval; make check-branch; make agent-loop-active-start ISSUE=1618 ACTIVE_START_RUNNER=0; REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent make real-eval-v2-check; make real-eval-v2-guard; make real-eval
- Results: branch created; branch check passed; v2 path check passed; v2 guard
  passed; legacy make real-eval failed intentionally with exit code 2.
- Validation evidence: v2 inventory/check show config, data list, source docs,
  index, report dir, eval summary, and baseline summary present; v2 guard
  passed; legacy real-eval targets fail closed; privacy and claim audits passed.
- Blockers: claim-bearing page/citation work is blocked by v2 page metadata
  ready rate 0.0.
- Next safe command: git status --short
- Next action: none for T-2026-0028; follow-on diagnostic/page-metadata work is tracked separately in T-2026-0029, T-2026-0047, and T-2026-0076.
- Open questions: none for the completed T-2026-0028 scope.
- Open risks: old `real100` aggregate files remain in the repo as historical
  artifacts, so future agents must obey the new fail-closed guard.
- Risks: aggregate wording must not imply performance improvement; stale
  real100/221 evidence is forbidden.
- Reviewer focus: v2-only enforcement, no stale real100/221 evidence, no
  performance-improvement claim, aggregate-only privacy boundary.
- Eval surface: private real-eval aggregate-only, real100_v2 only.
```
