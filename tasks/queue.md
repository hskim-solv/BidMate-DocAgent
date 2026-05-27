# Persistent Task Queue

이 queue는 장기 AI-agent 작업의 operational state를 저장한다. 실제 GitHub issue와
PR이 생기면 각 task에 링크를 추가한다. 예제 task는 `tasks/examples/`에 있고,
아래 queue에는 현재 운영체계 도입 이후 실제로 수행할 수 있는 seed task만 둔다.

## Ready Order

새 세션은 이 표에서 위에서부터 첫 `ready` task를 선택한다. `backlog`는 ready
조건이 부족한 작업이고, `review`는 구현보다 검토가 우선이다.

| Order | ID | Status | Owner role | Why ready / not ready |
|---:|---|---|---|---|
| 1 | `T-2026-0001` | `done` | Implementer -> Benchmark Auditor -> Reviewer | merged in PR #1481. |
| 2 | `T-2026-0002` | `done` | Implementer -> Reviewer | merged in PR #1481. |
| 3 | `T-2026-0003` | `done` | Implementer -> Reviewer | merged in PR #1483. |
| 4 | `T-2026-0004` | `done` | Implementer -> Reviewer | merged in PR #1494. |
| 5 | `T-2026-0005` | `done` | Implementer -> Benchmark Auditor -> Reviewer | merged in PR #1499. |
| 6 | `T-2026-0006` | `done` | Implementer -> Reviewer | merged in PR #1509. |
| 7 | `T-2026-0007` | `done` | Implementer -> Reviewer | merged in PR #1511. |
| 8 | `T-2026-0008` | `done` | Implementer -> Reviewer | merged in PR #1515. |
| 9 | `T-2026-0009` | `done` | Implementer -> Reviewer | merged in PR #1517. |
| 10 | `T-2026-0010` | `done` | Implementer -> Reviewer | merged in PR #1519. |
| 11 | `T-2026-0011` | `done` | Implementer -> Reviewer | merged in PR #1521. |
| 12 | `T-2026-0012` | `done` | Implementer -> Reviewer | merged in PR #1523. |
| 13 | `T-2026-0013` | `done` | Maintainer -> Reviewer | merged in PR #1530. |
| 14 | `T-2026-0014` | `done` | Maintainer -> Reviewer | merged in PR #1532. |
| 15 | `T-2026-0015` | `done` | Maintainer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | merged in PR #1536. |
| 16 | `T-2026-0016` | `review` | Maintainer -> Reviewer | overlap preflight implemented; PR #1543. |
| 17 | `T-2026-0017` | `review` | Maintainer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | v0-b manifest automation ready for review; PR #1545. |
| 18 | `T-2026-0018` | `review` | Maintainer -> Reviewer | issue #1547 implemented; draft PR #1548. |
| 19 | `T-2026-0019` | `review` | Maintainer -> CI Reviewer -> Reviewer | local implementation ready on issue #1549 branch. |
| 20 | `T-2026-0020` | `review` | Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | issue #1544; v0 metric-suite report implementation ready for review. |
| 21 | `T-2026-0021` | `review` | Maintainer -> CI Reviewer -> Reviewer | issue #1551 implemented; draft PR #1552. |
| 22 | `T-2026-0022` | `backlog` | Planner -> Implementer -> Reviewer | issue #1563; choose one scoped multi-chunk retrieval measurement follow-up. |
| 23 | `T-2026-0023` | `ready` | Planner -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Deep Reviewer -> Reviewer | issue #1569; long-running RAG performance goal with 8 agent operating principles. |

## Examples

- [`tasks/examples/benchmark-hardening.md`](examples/benchmark-hardening.md): benchmark hardening task 작성 예시.
- [`tasks/examples/eval-regression-safety.md`](examples/eval-regression-safety.md): eval regression safety task 작성 예시.

## T-2026-0016 — Agent worktree overlap preflight

- ID: T-2026-0016
- Title: Agent worktree overlap preflight
- Status: review
- Owner role: Maintainer -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Prevent duplicate Codex sessions from starting on an issue, branch, PR, or
worktree that is already in flight.

### Scope

- Add `overlap-preflight` to `scripts/agent_loop.py`.
- Check issue state, target branch, open PRs, branch PR history, local worktrees,
  remote branch leftovers, and current checkout freshness.
- Write local report artifacts under `reports/agent_loop/`.
- Document that agents should run overlap preflight before editing files.

### Non-Goals

- Do not add a CI gate.
- Do not switch branches, push, create/merge/close PRs, close issues, or delete branches.
- Do not change RAG runtime or eval behavior.

### Acceptance Criteria

- [x] Same issue branch in another worktree blocks.
- [x] Same issue open PR blocks.
- [x] Closed issue with merged branch history blocks as completed.
- [x] Detached or stale current checkout blocks.
- [x] Clean ADR 0007 branch/issue with no overlap reports clear.
- [x] Start-of-task docs mention overlap preflight.

### Validation Commands

```bash
python3 -m pytest tests/test_agent_loop.py -q
python3 -m py_compile scripts/agent_loop.py
python3 scripts/agent_loop.py overlap-preflight --issue 1541 --branch chore/issue-1541-overlap-preflight
python3 scripts/check_doc_links.py --check-all --paths tasks/README.md docs/operations/ai-codex-workflow.md docs/plans/T-2026-0016-agent-worktree-overlap-preflight.md tasks/queue.md
git diff --check
make check-branch
```

### Evidence Required

- Focused pytest output.
- Py compile output.
- Overlap preflight smoke output.
- Targeted doc link check output.
- Diff whitespace and branch checks.

### Failure Conditions

- Stop if the command mutates tracked docs, branches, PRs, issues, or remote state.
- Stop if a blocked overlap returns clear.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0016-agent-worktree-overlap-preflight.md`](../docs/plans/T-2026-0016-agent-worktree-overlap-preflight.md)
- Issue: [#1541](https://github.com/hskim-solv/BidMate-DocAgent/issues/1541)
- PR: [#1543](https://github.com/hskim-solv/BidMate-DocAgent/pull/1543)

### Handoff Notes

```markdown
## Session Handoff — 2026-05-27 KST

- Role: Maintainer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1541-overlap-preflight / /Users/hskim/.codex/worktrees/43e3/BidMate-DocAgent
- Issue / PR: #1541 / PR #1543
- Task: T-2026-0016
- Current status: overlap preflight implemented; focused validation passed; PR #1543 open.
- Files touched: scripts/agent_loop.py, tests/test_agent_loop.py, tasks/README.md, docs/operations/ai-codex-workflow.md, docs/plans/T-2026-0016-agent-worktree-overlap-preflight.md, tasks/queue.md
- Decisions made: keep this as a local report-only pre-edit check, not a CI gate.
- Eval surface: workflow/tooling only; no metric or performance claim.
- Commands run: python3 -m pytest tests/test_agent_loop.py -q; python3 -m py_compile scripts/agent_loop.py; python3 scripts/agent_loop.py overlap-preflight --issue 1541 --branch chore/issue-1541-overlap-preflight; python3 scripts/check_doc_links.py --check-all --paths tasks/README.md docs/operations/ai-codex-workflow.md docs/plans/T-2026-0016-agent-worktree-overlap-preflight.md tasks/queue.md; git diff --check; make check-branch
- Results: passed
- Next safe command: git diff --stat
- Reviewer focus: false-clear risk, report-only behavior, GitHub/Git failures fail closed.
```

## T-2026-0017 — v0-b offline/online run manifest

- ID: T-2026-0017
- Title: v0-b offline/online run manifest
- Status: review
- Owner role: Maintainer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Close the v0-b milestone from the agent-gated RFP eval loop by automating a
privacy-safe offline/online run manifest for eval provenance.

### Scope

- Add offline/online environment sections to `eval/run_eval.py` `run_manifest`.
- Add `scripts/agent_loop.py eval-run-manifest` for standalone handoff artifacts.
- Preserve only safe scalar manifest sections in real-eval aggregate extraction.
- Document the schema and link it from v0-b docs.

### Non-Goals

- Do not run private real-eval.
- Do not change retrieval, scoring, ranking, or answer behavior.
- Do not make a benchmark, metric, regression, or RFP quality claim.

### Acceptance Criteria

- [x] Offline and online manifest examples share one section schema.
- [x] Offline manifests force `private_data_egress=none`.
- [x] Online manifests record provider/model/payload class/egress mode.
- [x] Privacy tests prevent raw private text and exact local path leakage.
- [x] Existing run manifest reproducibility fields remain present.

### Validation Commands

```bash
python3 -m pytest tests/test_agent_loop.py tests/test_run_manifest_versioning_regression.py tests/test_eval_metrics.py tests/test_run_real_eval_delta.py -q
python3 -m py_compile scripts/agent_loop.py eval/run_eval.py scripts/run_real_eval_delta.py
python3 scripts/agent_loop.py eval-run-manifest --mode offline --payload-class none --egress-mode none --provider local --model local-judge-v1 --judge-backend local-llm
python3 scripts/check_doc_links.py --check-all --paths docs/evaluation/agent-gated-rfp-eval-loop.md docs/evaluation/offline-online-run-manifest.md docs/evaluation/v0-metric-suite-inventory.md docs/plans/T-2026-0017-v0-b-offline-online-run-manifest.md tasks/queue.md
git diff --check
make check-branch
```

### Evidence Required

- Focused pytest and py_compile output.
- CLI-generated manifest artifact.
- Targeted doc link check.
- Branch/issue convention check.

### Failure Conditions

- Stop if committed manifest output includes raw private question, answer,
  evidence, `doc_id`, `chunk_id`, filename, or exact local path.
- Stop if wording implies performance improvement or private real-eval success.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0017-v0-b-offline-online-run-manifest.md`](../docs/plans/T-2026-0017-v0-b-offline-online-run-manifest.md)
- Issue: [#1542](https://github.com/hskim-solv/BidMate-DocAgent/issues/1542)
- PR: [#1545](https://github.com/hskim-solv/BidMate-DocAgent/pull/1545)

### Handoff Notes

```markdown
## Session Handoff — 2026-05-27 KST

- Role: Maintainer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1542-offline-online-manifest / /Users/hskim/.codex/worktrees/1542/BidMate-DocAgent
- Issue / PR: #1542 / #1545
- Task: T-2026-0017
- Current status: implementation validated; draft PR #1545 open.
- Files touched: eval/run_eval.py, scripts/agent_loop.py, scripts/run_real_eval_delta.py, docs/evaluation/offline-online-run-manifest.md, docs/evaluation/agent-gated-rfp-eval-loop.md, docs/evaluation/v0-metric-suite-inventory.md, docs/plans/T-2026-0017-v0-b-offline-online-run-manifest.md, tasks/queue.md, tests/test_agent_loop.py, tests/test_eval_metrics.py, tests/test_run_manifest_versioning_regression.py, tests/test_run_real_eval_delta.py
- Decisions made: use additive `run_manifest` sections plus standalone `eval-run-manifest`; keep private real-eval unrun and no performance claim.
- Eval surface: provenance plumbing only; no metric claim.
- Commands run: python3 -m pytest tests/test_agent_loop.py tests/test_run_manifest_versioning_regression.py tests/test_eval_metrics.py tests/test_run_real_eval_delta.py -q; python3 -m py_compile scripts/agent_loop.py eval/run_eval.py scripts/run_real_eval_delta.py; python3 scripts/agent_loop.py eval-run-manifest --mode offline --payload-class none --egress-mode none --provider local --model local-judge-v1 --judge-backend local-llm; python3 scripts/check_doc_links.py --check-all --paths docs/evaluation/agent-gated-rfp-eval-loop.md docs/evaluation/offline-online-run-manifest.md docs/evaluation/v0-metric-suite-inventory.md docs/plans/T-2026-0017-v0-b-offline-online-run-manifest.md tasks/queue.md; git diff --check; make check-branch; python3 scripts/_governance.py --check-eval-privacy.
- Results: passed.
- Next safe command: git diff --stat
- Reviewer focus: privacy-safe scalar whitelist, backward-compatible manifest fields, no performance claim.
```

## T-2026-0018 — Codex-runnable auto-ship

- ID: T-2026-0018
- Title: Codex-runnable auto-ship
- Status: review
- Owner role: Maintainer -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Make the existing auto-ship pipeline usable from Codex/non-Claude sessions
without relying on a Claude Stop-hook event.

### Scope

- Add a direct runner that reuses `_ship_arm.py` and `stop-ship.sh`.
- Add `make ship-run` and `make codex-ship`.
- Preserve `make ship-arm` as arm-only.
- Let clean branches with an existing PR resume CI/review/merge instead of
  exiting before Stage 1.

### Non-Goals

- Do not relax review, CI, merge, branch deletion, or §5b policy.
- Do not introduce a scheduler or background daemon.
- Do not run private real-eval.

### Acceptance Criteria

- [x] `make ship-run` arms and immediately dispatches the existing pipeline.
- [x] `USE_EXISTING_ARM=1 make ship-run` dispatches an existing arm.
- [x] Existing arm files fail closed by default.
- [x] Focused tests cover runner behavior and clean existing-PR resume.
- [x] Operations docs distinguish Stop-hook arming from direct Codex runs.

### Validation Commands

```bash
python3 -m pytest tests/test_ship_run.py tests/test_ship_dispatcher_gates.py tests/test_ship_arm_mutex.py -q
python3 -m py_compile scripts/claude-hooks/_ship_run.py scripts/claude-hooks/_ship_arm.py
python3 scripts/check_doc_links.py --check-all --paths docs/operations/auto-ship.md docs/plans/T-2026-0018-codex-runnable-auto-ship.md tasks/queue.md scripts/claude-hooks/README.md
git diff --check
make check-branch
```

### Links

- Issue: #1547
- PR: #1548
- Plan: [`docs/plans/T-2026-0018-codex-runnable-auto-ship.md`](../docs/plans/T-2026-0018-codex-runnable-auto-ship.md)

## T-2026-0019 — Agent loop continuation repair

- ID: T-2026-0019
- Title: Agent loop continuation repair
- Status: review
- Owner role: Maintainer -> CI Reviewer -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Make `loop-state` expose the next automatic continuation step when branch,
manifest, or task linkage is incomplete, so the loop can recover without
removing conservative gates.

### Scope

- Add a machine-readable `continuation` block to `scripts/agent_loop.py`
  `loop-state` output.
- Surface continuation status in the generated dashboard.
- Document the continuation block in the agent operating-system doc.
- Cover detached HEAD repair and ready issue-branch continuation with focused
  tests.

### Non-Goals

- Do not auto-push, create PRs, merge, delete branches, force-push, or run
  private real-eval.
- Do not remove `make ship-arm` single-shot behavior.
- Do not make missing task/plan linkage invisible.

### Acceptance Criteria

- [x] Detached HEAD loop state contains a concrete issue+branch recovery command.
- [x] Issue-linked branch with fresh manifest can report `can_auto_continue`.
- [x] Dashboard renders continuation status and next command.
- [x] Branch is issue-linked to #1549 and passes branch check.

### Validation Commands

```bash
python3 -m py_compile scripts/agent_loop.py
python3 -m pytest tests/test_agent_loop.py -q
python3 -m pytest tests/test_agent_loop_claude_integration.py -q
python3 scripts/check_doc_links.py --check-all --paths docs/operations/ai-engineering-operating-system.md tasks/queue.md docs/plans/T-2026-0019-agent-loop-continuation-repair.md
git diff --check
make check-branch
```

### Evidence Required

- Focused pytest output.
- Py compile output.
- Doc link check output.
- Branch check output.
- `loop-state` continuation sample.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0019-agent-loop-continuation-repair.md`](../docs/plans/T-2026-0019-agent-loop-continuation-repair.md)
- Issue: [#1549](https://github.com/hskim-solv/BidMate-DocAgent/issues/1549)
- PR: [#1550](https://github.com/hskim-solv/BidMate-DocAgent/pull/1550)

### Handoff Notes

```markdown
## Session Handoff — 2026-05-27 KST

- Role: Maintainer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1549-agent-loop-continuation / /Users/hskim/.codex/worktrees/380f/BidMate-DocAgent
- Base branch: main
- Issue / PR: #1549 / PR #1550
- Task: T-2026-0019
- Plan: docs/plans/T-2026-0019-agent-loop-continuation-repair.md
- Current status: local implementation complete; focused validation passed; draft PR #1550 open.
- Files touched: scripts/agent_loop.py, tests/test_agent_loop.py, docs/operations/ai-engineering-operating-system.md, tasks/queue.md, docs/plans/T-2026-0019-agent-loop-continuation-repair.md
- Decisions made: keep Stop hook report-only; expose continuation commands in loop-state/dashboard instead of mutating automatically from the hook.
- Commands run: python3 -m py_compile scripts/agent_loop.py; python3 -m pytest tests/test_agent_loop.py -q; python3 -m pytest tests/test_agent_loop_claude_integration.py -q; python3 scripts/check_doc_links.py --check-all --paths docs/operations/ai-engineering-operating-system.md tasks/queue.md docs/plans/T-2026-0019-agent-loop-continuation-repair.md; git diff --check; make check-branch.
- Results: passed.
- Validation evidence: focused tests and branch check passed; loop-state reports branch issue #1549 with can_auto_continue true after manifest refresh.
- Eval surface: tooling/governance only; no benchmark or performance claim.
- Evidence artifacts: reports/agent_loop/loop_state.json, reports/agent_loop/manifest.json, reports/agent_loop/branch_issue_hygiene.md.
- Blockers: none.
- Open risks: task/plan linkage remains explicit so automation still needs a task id for preflight prompts.
- Next action: reviewer check.
- Next safe command: python3 scripts/agent_loop.py loop-state --task T-2026-0019 --from-git --out reports/agent_loop/loop_state.json
- Reviewer focus: continuation command safety, no hidden remote mutation, dashboard clarity, branch/manifest/task state semantics.
```

## T-2026-0020 — v0 metric suite report

- ID: T-2026-0020
- Title: v0 metric suite report
- Status: review
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Turn the v0 metric-suite inventory into an executable aggregate-only report
surface and add the missing numeric/date/condition slot exactness metric.

### Scope

- Add `eval/scorers/slot_metrics.py` and wire its aggregate into
  `eval/run_eval.py`.
- Extend commit-safe extraction for numeric/date/condition and comparison
  coverage scalars.
- Add `scripts/render_v0_metric_suite_report.py` with optional local
  judge/human agreement CSV aggregation.
- Update v0 metric-suite docs and focused tests.

### Non-Goals

- Do not claim RFP QA quality improved.
- Do not synthesize `human_status` labels for judge agreement.
- Do not commit raw private questions, answers, evidence, document IDs, chunk
  IDs, filenames, paths, or per-case rows.

### Acceptance Criteria

- [x] Numeric/date/condition slot exactness appears in per-case and run-level
  metrics.
- [x] v0 report renders all eight metric families and marks data-dependent
  gaps.
- [x] Privacy-safe aggregate/report generation is tested.
- [x] Branch and issue convention pass.

### Validation Commands

```bash
python3 -m pytest tests/test_slot_metrics.py tests/test_v0_metric_suite_report.py tests/test_extract_aggregate_metadata_field_calibration.py -q
python3 -m py_compile eval/scorers/slot_metrics.py scripts/render_v0_metric_suite_report.py eval/scorers/case.py eval/run_eval.py scripts/run_real_eval_delta.py
python3 scripts/render_v0_metric_suite_report.py --aggregate reports/real100_v2/baseline.aggregate.json --question-distribution reports/real100_v2/question_distribution.aggregate.json --out-json reports/real100_v2/metric_suite.aggregate.json --out-md reports/real100_v2/metric_suite.md
python3 scripts/check_doc_links.py --check-all --paths docs/evaluation/agent-gated-rfp-eval-loop.md docs/evaluation/v0-metric-suite-inventory.md docs/plans/T-2026-0020-v0-metric-suite-report.md tasks/queue.md reports/real100_v2/README.md reports/real100_v2/metric_suite.md
git diff --check
make check-branch
```

### Evidence Required

- Focused pytest output.
- Py compile output.
- Generated `reports/real100_v2/metric_suite.*` output.
- Targeted doc link check.

### Failure Conditions

- Stop if wording implies a performance claim.
- Stop if generated artifacts contain raw private payload or exact local paths.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0020-v0-metric-suite-report.md`](../docs/plans/T-2026-0020-v0-metric-suite-report.md)
- Issue: [#1544](https://github.com/hskim-solv/BidMate-DocAgent/issues/1544)
- PR: [#1546](https://github.com/hskim-solv/BidMate-DocAgent/pull/1546)

### Handoff Notes

```markdown
## Session Handoff — 2026-05-27 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: feat/issue-1544-v0-metric-suite-report / /Users/hskim/.codex/worktrees/e622/BidMate-DocAgent
- Issue / PR: #1544 / PR #1546
- Task: T-2026-0020
- Current status: implementation complete; ready for review.
- Files touched: .gitignore, eval/scorers/slot_metrics.py, eval/scorers/__init__.py, eval/scorers/case.py, eval/run_eval.py, scripts/_utils.py, scripts/run_real_eval_delta.py, scripts/render_v0_metric_suite_report.py, docs/evaluation/v0-metric-suite-inventory.md, docs/evaluation/agent-gated-rfp-eval-loop.md, reports/real100_v2/README.md, reports/real100_v2/baseline.aggregate.json, reports/real100_v2/metric_suite.aggregate.json, reports/real100_v2/metric_suite.md, tests.
- Decisions made: implement metric coverage, not performance movement; keep human/judge labels local-only.
- Eval surface: private real-eval aggregate-only; no performance claim.
- Commands run: gh issue create; git switch -c feat/issue-1544-v0-metric-suite-report; python3 -m pytest tests/test_slot_metrics.py tests/test_v0_metric_suite_report.py tests/test_extract_aggregate_metadata_field_calibration.py -q; python3 -m py_compile eval/scorers/slot_metrics.py scripts/render_v0_metric_suite_report.py eval/scorers/case.py eval/run_eval.py scripts/run_real_eval_delta.py; python3 scripts/render_v0_metric_suite_report.py --aggregate reports/real100_v2/baseline.aggregate.json --question-distribution reports/real100_v2/question_distribution.aggregate.json --out-json reports/real100_v2/metric_suite.aggregate.json --out-md reports/real100_v2/metric_suite.md; python3 scripts/check_doc_links.py --check-all --paths docs/evaluation/agent-gated-rfp-eval-loop.md docs/evaluation/v0-metric-suite-inventory.md docs/plans/T-2026-0020-v0-metric-suite-report.md tasks/queue.md reports/real100_v2/README.md reports/real100_v2/metric_suite.md; git diff --check; make check-branch.
- Results: all validation commands passed; generated metric suite report shows 7 present, 1 partial, 0 missing after private real100_v2 aggregate regeneration.
- Next safe command: git diff --stat
- Reviewer focus: no raw private content, no performance claim, present/partial boundary for data-dependent families.
```

## T-2026-0021 — PR corpus workset planning

- ID: T-2026-0021
- Title: PR corpus workset planning
- Status: review
- Owner role: Maintainer -> CI Reviewer -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Make `next-from-prs` plan the next task/workset from the full open PR corpus,
then let `batch-plan`, `role-dispatch`, and `continue-loop` carry that work
into queue/plan state without asking a person to pick a PR.

### Scope

- Reframe `scripts/ai_next_actions.py` PR handling from PR selection to PR
  corpus planning.
- Add `Source PRs`, `Workset`, `Lane`, `Role Hints`, and `Completion Proof`
  to generated task briefs and HTML/Markdown summaries.
- Extend `batch-plan` JSON for workset-level role dispatch.
- Let `role-dispatch` consume batch/workset metadata as subagent prompt source.
- Add `continue-loop` to run PR scan, PR-corpus planning, batch plan,
  role dispatch, queue/plan draft/application, and loop-state in one local
  continuation command.
- Bridge the draft PR -> ready PR gap for ready-mode ship gates so an existing
  draft PR can continue through review gate and merge after CI passes.
- Document the new operating contract.

### Non-Goals

- Do not push, create/merge/close PRs, close issues, delete branches, force-push,
  run private real-eval, or approve benchmark/performance claims from
  `continue-loop`.
- Do not change RAG runtime, eval scorer, ingestion, retrieval, or answer
  behavior.
- Do not make PR title/body raw text a committable evidence surface.

### Acceptance Criteria

- [x] Multiple PRs produce higher-level workset tasks instead of selecting one PR.
- [x] Blocked, ready, stale draft, private-delta, and draft continuation lanes
  include `Source PRs`.
- [x] Task briefs include goal, expected evidence, validation, and completion
  proof.
- [x] `batch-plan` JSON includes `workset_id`, `lane`, `source_prs`, and
  `role_hints`.
- [x] `role-dispatch` can consume a batch/workset and render role prompt inputs.
- [x] `continue-loop` advances local planning through queue/plan and loop-state
  while leaving remote mutation to existing ship gates.
- [x] Ready-mode auto-ship (`DRAFT=false`) marks an existing draft PR ready
  before review gate; draft-mode (`DRAFT=true`) still stops intentionally.

### Validation Commands

```bash
python3 -m py_compile scripts/ai_next_actions.py scripts/agent_loop.py
python3 -m pytest tests/test_ai_next_actions.py tests/test_agent_loop.py tests/test_ship_start_review_gate.py tests/test_ship_dispatcher_gates.py -q
python3 scripts/check_doc_links.py --check-all --paths docs/operations/ai-codex-workflow.md docs/operations/ai-engineering-operating-system.md docs/operations/auto-ship.md tasks/queue.md docs/plans/T-2026-0021-pr-corpus-workset-planning.md
python3 scripts/agent_loop.py continue-loop --pr-json reports/agent_loop/pr_state.json --no-apply-queue-plan
git diff --check
make check-branch
```

### Evidence Required

- Focused pytest output.
- Py compile output.
- Targeted doc link check output.
- `continue-loop` dry local smoke output with `--no-apply-queue-plan`.
- Diff whitespace and branch checks.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0021-pr-corpus-workset-planning.md`](../docs/plans/T-2026-0021-pr-corpus-workset-planning.md)
- Issue: [#1551](https://github.com/hskim-solv/BidMate-DocAgent/issues/1551)
- PR: [#1552](https://github.com/hskim-solv/BidMate-DocAgent/pull/1552)

### Handoff Notes

```markdown
## Session Handoff — 2026-05-27 KST

- Role: Maintainer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1551-pr-corpus-worksets / /Users/hskim/.codex/worktrees/5e72/BidMate-DocAgent
- Base branch: main
- Issue / PR: #1551 / PR #1552
- Task: T-2026-0021
- Plan: docs/plans/T-2026-0021-pr-corpus-workset-planning.md
- Current status: local implementation complete; focused validation passed.
- Files touched: scripts/ai_next_actions.py, scripts/agent_loop.py, tests/test_ai_next_actions.py, tests/test_agent_loop.py, docs/operations/ai-codex-workflow.md, docs/operations/ai-engineering-operating-system.md, tasks/queue.md, docs/plans/T-2026-0021-pr-corpus-workset-planning.md
- Decisions made: keep command names, change `next-from-prs` semantics to PR corpus workset planning, make `continue-loop` local-only with remote mutation delegated to existing ship gates, and renumber this task to T-2026-0021 after #1546 occupied T-2026-0020 on `main`.
- Commands run: python3 -m py_compile scripts/ai_next_actions.py scripts/agent_loop.py; python3 -m pytest tests/test_ai_next_actions.py tests/test_agent_loop.py -q; python3 scripts/check_doc_links.py --check-all --paths docs/operations/ai-codex-workflow.md docs/operations/ai-engineering-operating-system.md tasks/queue.md docs/plans/T-2026-0021-pr-corpus-workset-planning.md; python3 scripts/agent_loop.py pr-scan --limit 30 --out reports/agent_loop/pr_state.json; python3 scripts/agent_loop.py continue-loop --pr-json reports/agent_loop/pr_state.json --no-apply-queue-plan; git diff --check; make check-branch.
- Results: passed.
- Validation evidence: PR corpus planner, batch JSON, role-dispatch, and continue-loop are covered by focused tests; dry smoke wrote reports/agent_loop/continue_loop.md without applying queue/plan or mutating remote state.
- Eval surface: tooling/governance only; no benchmark, product quality, or private real-eval claim.
- Evidence artifacts: reports/agent_loop/pr_state.json, reports/agent_loop/ai_next_actions.md, reports/agent_loop/batch_plan.json, reports/agent_loop/role_dispatch.md, reports/agent_loop/continue_loop.md, reports/agent_loop/loop_state.json.
- Blockers: none.
- Open risks: `continue-loop` applies tracked queue/plan docs by default, so reviewers should confirm the internal agent-gate wording and no remote mutation behavior.
- Next action: reviewer check.
- Next safe command: git diff --stat
- Reviewer focus: PR corpus vs PR selection semantics, fail-closed missing PR fields, workset lane grouping, role-dispatch prompt source, `continue-loop` no remote mutation, privacy/claim boundary.
```

## T-2026-0014 — Agent gate surface alignment

- ID: T-2026-0014
- Title: Agent gate surface alignment
- Status: done
- Owner role: Maintainer -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Make the visible agent-loop surfaces match ADR 0079 so the loop reads as a
conservative agent-gated operating system rather than a workflow waiting for
manual human gates.

### Scope

- Update `scripts/agent_loop.py` map, gate brief, automation coverage, CLI help,
  and ship command pack wording.
- Keep legacy `human-gated-exec` command and `--confirm-human-approved` flag names
  for compatibility.
- Add concrete v0/v1/v2 metric-loop milestones to the agent-gated eval policy.
- Add a report-only `role-dispatch` command for Codex subagent role separation
  with max 12 roles and depth 2.

### Non-Goals

- Do not change remote mutation behavior.
- Do not rename CLI flags or commands.
- Do not run private real-eval.

### Acceptance Criteria

- [x] Loop map says `Agent gate` and explains legacy command naming.
- [x] Gate brief references ADR 0079 conservative defaults.
- [x] Metric-loop next milestones are visible in the eval policy.
- [x] Focused tests cover the wording shift.
- [x] Role dispatch plan is visible in the loop map, automation coverage, docs,
  and tests.

### Validation Commands

```bash
python3 -m pytest tests/test_agent_loop.py -q
python3 -m py_compile scripts/agent_loop.py
python3 scripts/agent_loop.py role-dispatch --owner-role "Implementer -> Benchmark Auditor -> Reviewer" --from-git
python3 scripts/check_doc_links.py --check-all --paths docs/evaluation/agent-gated-rfp-eval-loop.md tasks/queue.md docs/plans/T-2026-0014-agent-gate-surface-alignment.md
git diff --check
make check-branch
```

### Evidence Required

- Focused pytest output.
- Py compile output.
- Targeted doc link check.

### Failure Conditions

- Stop if compatibility command names change.
- Stop if text implies performance evidence without private real-eval aggregate.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0014-agent-gate-surface-alignment.md`](../docs/plans/T-2026-0014-agent-gate-surface-alignment.md)
- Issue: [#1531](https://github.com/hskim-solv/BidMate-DocAgent/issues/1531)
- PR: [#1532](https://github.com/hskim-solv/BidMate-DocAgent/pull/1532)

### Handoff Notes

```markdown
## Session Handoff — 2026-05-27 KST

- Role: Maintainer
- Lifecycle stage: done
- Branch / worktree: chore/issue-1531-agent-gate-surfaces / /Users/hskim/.codex/worktrees/1c21/BidMate-DocAgent
- Issue / PR: #1531 / PR #1532
- Task: T-2026-0014
- Current status: merged in PR #1532.
- Files touched: scripts/agent_loop.py, tests/test_agent_loop.py, docs/evaluation/agent-gated-rfp-eval-loop.md, docs/plans/T-2026-0014-agent-gate-surface-alignment.md, tasks/queue.md
- Decisions made: keep legacy command names but make visible policy say conservative agent gate; add report-only role dispatch for Codex subagents.
- Eval surface: governance/tooling only; no metric claim.
- Commands run: python3 -m pytest tests/test_agent_loop.py -q; python3 -m py_compile scripts/agent_loop.py; python3 scripts/agent_loop.py role-dispatch --owner-role "Implementer -> Benchmark Auditor -> Reviewer" --from-git; python3 scripts/check_doc_links.py --check-all --paths docs/evaluation/agent-gated-rfp-eval-loop.md tasks/queue.md docs/plans/T-2026-0014-agent-gate-surface-alignment.md; git diff --check; make check-branch.
- Results: passed.
- Next action: N/A; merged in PR #1532.
- Next safe command: N/A
- Reviewer focus: compatibility, no hidden remote mutation change, no subagent execution side effect, no performance claim.
```

## T-2026-0015 — v0 metric suite inventory

- ID: T-2026-0015
- Title: v0 metric suite inventory
- Status: done
- Owner role: Maintainer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Close the v0-a milestone from the agent-gated RFP eval loop by classifying
which metric families already exist in committed private real-eval aggregate
surfaces and which remain partial or missing.

### Scope

- Add `docs/evaluation/v0-metric-suite-inventory.md`.
- Link the v0-a milestone from `docs/evaluation/agent-gated-rfp-eval-loop.md`.
- Keep the inventory aggregate-only and explicitly non-claim-bearing.
- Do not change eval runner, scorer, RAG runtime, or private data.

### Non-Goals

- Do not run private real-eval.
- Do not implement new metrics.
- Do not make a performance claim.

### Acceptance Criteria

- [x] Inventory covers all eight metric families in the agent-gated eval-loop policy.
- [x] Each family is classified as present, partial, or missing with aggregate source paths.
- [x] Privacy and no-performance-claim boundaries are explicit.
- [x] Plan and queue reference issue #1535.

### Validation Commands

```bash
python3 scripts/check_doc_links.py --check-all --paths docs/evaluation/agent-gated-rfp-eval-loop.md docs/evaluation/v0-metric-suite-inventory.md docs/plans/T-2026-0015-v0-metric-suite-inventory.md tasks/queue.md
git diff --check
make check-branch
```

### Evidence Required

- Targeted doc link check output.
- Diff whitespace output.
- Branch/issue convention check.

### Failure Conditions

- Stop if wording implies RFP QA performance movement.
- Stop if any raw private identifier, filename, local path, question, answer, or evidence text is introduced.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0015-v0-metric-suite-inventory.md`](../docs/plans/T-2026-0015-v0-metric-suite-inventory.md)
- Issue: [#1535](https://github.com/hskim-solv/BidMate-DocAgent/issues/1535)
- PR: [#1536](https://github.com/hskim-solv/BidMate-DocAgent/pull/1536)

### Handoff Notes

```markdown
## Session Handoff — 2026-05-27 KST

- Role: Maintainer
- Lifecycle stage: done
- Branch / worktree: docs/issue-1535-v0-metric-inventory / /Users/hskim/.codex/worktrees/43e3/BidMate-DocAgent
- Issue / PR: #1535 / PR #1536
- Task: T-2026-0015
- Current status: merged in PR #1536.
- Files touched: docs/evaluation/v0-metric-suite-inventory.md, docs/evaluation/agent-gated-rfp-eval-loop.md, docs/plans/T-2026-0015-v0-metric-suite-inventory.md, tasks/queue.md
- Decisions made: treat grounding, comparison coverage, abstention calibration, numeric/date/condition accuracy, and human/judge agreement as partial where current artifacts expose only a narrower metric, null field, labels, or tooling.
- Eval surface: aggregate-only private real-eval inventory; no metric claim.
- Commands run: python3 scripts/check_doc_links.py --check-all --paths docs/evaluation/agent-gated-rfp-eval-loop.md docs/evaluation/v0-metric-suite-inventory.md docs/plans/T-2026-0015-v0-metric-suite-inventory.md tasks/queue.md; git diff --check; make check-branch
- Results: passed
- Next safe command: git diff --stat
- Reviewer focus: no raw private content, no performance claim, present/partial boundary.
```

## T-2026-0013 — Agent-gated offline/online RFP eval loop

- ID: T-2026-0013
- Title: Agent-gated offline/online RFP eval loop
- Status: done
- Owner role: Maintainer -> Reviewer
- Created: 2026-05-26
- Last updated: 2026-05-26

### Goal

Codify the conservative agent-gate policy for continuing RFP QA evaluation across
offline and online environments without requiring a human gate on every routine
claim, private eval, shipping, or cleanup decision.

### Context

- Surface: governance docs / eval policy.
- Relevant docs: [`docs/plans/T-2026-0013-agent-gated-rfp-eval-loop.md`](../docs/plans/T-2026-0013-agent-gated-rfp-eval-loop.md), [ADR 0079](../docs/adr/0079-agent-gated-offline-online-rfp-eval-loop.md).
- Primary risk: overbroad performance claims or private-data egress without provenance.

### Scope

- Add ADR 0079.
- Add the agent-gated RFP eval-loop policy doc.
- Update surface-map and Codex workflow docs.

### Non-Goals

- Do not change runtime RAG behavior.
- Do not run private real-eval in this docs PR.
- Do not rename legacy `human-gated-*` CLI commands.

### Acceptance Criteria

- [x] Offline/online environment assumptions are documented.
- [x] Private real-eval is mandatory for claim-bearing evidence.
- [x] RFP metric suite, adoption criteria, and loop termination are documented.
- [x] Conservative agent gate defaults are documented.

### Validation Commands

```bash
python3 scripts/_governance.py --lint-adr-consequences docs/adr/0079-agent-gated-offline-online-rfp-eval-loop.md
python3 scripts/check_doc_links.py --check-all --paths docs/adr/0079-agent-gated-offline-online-rfp-eval-loop.md docs/evaluation/agent-gated-rfp-eval-loop.md docs/evaluation/surface-map.md docs/operations/ai-codex-workflow.md docs/plans/T-2026-0013-agent-gated-rfp-eval-loop.md tasks/queue.md
git diff --check
make check-branch
```

### Evidence Required

- ADR consequence lint output.
- Targeted doc link check.
- Diff whitespace and branch checks.

### Failure Conditions

- Stop if policy text implies public synthetic benchmark can support real RFP performance claims.
- Stop if policy text permits online private-data egress without provenance.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0013-agent-gated-rfp-eval-loop.md`](../docs/plans/T-2026-0013-agent-gated-rfp-eval-loop.md)
- Issue: [#1529](https://github.com/hskim-solv/BidMate-DocAgent/issues/1529)
- PR: [#1530](https://github.com/hskim-solv/BidMate-DocAgent/pull/1530)

### Handoff Notes

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
- Decisions made: Codex acts as conservative agent gate; private real-eval is mandatory for claim-bearing evidence; metric suite beats single headline score.
- Eval surface: governance docs only; no metric claim.
- Commands run: python3 scripts/_governance.py --lint-adr-consequences docs/adr/0079-agent-gated-offline-online-rfp-eval-loop.md; python3 scripts/check_doc_links.py --check-all --paths docs/adr/0079-agent-gated-offline-online-rfp-eval-loop.md docs/evaluation/agent-gated-rfp-eval-loop.md docs/evaluation/surface-map.md docs/operations/ai-codex-workflow.md docs/plans/T-2026-0013-agent-gated-rfp-eval-loop.md tasks/queue.md; git diff --check; make check-branch
- Results: pass.
- Next safe command: git diff --check
- Reviewer focus: claim boundary, online private-data egress provenance, no runtime behavior change.
```

## T-2026-0012 — Extended HTML review boards

- ID: T-2026-0012
- Title: Extended HTML review boards
- Status: done
- Owner role: Implementer -> Reviewer
- Created: 2026-05-26
- Last updated: 2026-05-26

### Goal

Extend the local human review renderer from fifteen boards to twenty-five boards
by adding second-pass reviewer, portfolio, and governance surfaces.

### Context

- Surface: aggregate-only private real-eval, public synthetic benchmark docs,
  governance docs, portfolio docs.
- Relevant docs: [`docs/plans/T-2026-0012-extended-html-review-boards.md`](../docs/plans/T-2026-0012-extended-html-review-boards.md).
- Primary risk: generated HTML being mistaken for a new measurement surface or
  source-of-truth.

### Scope

- Add ten more local HTML boards to the existing renderer.
- Use committed aggregate/redacted JSON and docs only.
- Keep generated HTML ignored and reproducible.

### Non-Goals

- Do not change RAG runtime, parser runtime, retrieval behavior, or eval scoring.
- Do not read private raw documents or per-case payloads.
- Do not make new performance claims.

### Acceptance Criteria

- [x] One command writes twenty-five local HTML boards.
- [x] Existing fifteen output paths still render.
- [x] Tests cover all twenty-five board titles and escaping.
- [x] Generated HTML is manually smoke-checked through a local HTTP server.

### Validation Commands

```bash
python3 -m pytest tests/test_render_priority_review_boards.py -q
python3 -m py_compile scripts/render_priority_review_boards.py
python3 scripts/render_priority_review_boards.py
python3 scripts/check_doc_links.py --check-all
git diff --check
make check-branch
```

### Evidence Required

- Focused pytest output.
- Generated HTML paths.
- Browser smoke result.

### Failure Conditions

- Stop if a board needs raw private data.
- Stop if a board would introduce a new benchmark/eval claim.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0012-extended-html-review-boards.md`](../docs/plans/T-2026-0012-extended-html-review-boards.md)
- Issue: [#1522](https://github.com/hskim-solv/BidMate-DocAgent/issues/1522)
- PR: [#1523](https://github.com/hskim-solv/BidMate-DocAgent/pull/1523)

### Handoff Notes

```markdown
## Session Handoff — 2026-05-26 00:00 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1522-extended-html-boards / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Task: T-2026-0012
- Plan: docs/plans/T-2026-0012-extended-html-review-boards.md
- Current status: merged in PR #1523.
- Files touched: scripts/render_priority_review_boards.py, tests/test_render_priority_review_boards.py, tasks/queue.md, docs/plans/T-2026-0012-extended-html-review-boards.md
- Decisions made: extend the existing renderer to twenty-five boards.
- Commands run: gh issue create; git switch; python3 -m pytest tests/test_render_priority_review_boards.py -q; python3 -m py_compile scripts/render_priority_review_boards.py; python3 scripts/render_priority_review_boards.py; python3 scripts/check_doc_links.py --check-all; git diff --check; make check-branch; browser smoke via http://127.0.0.1:8765
- Results: twenty-five local HTML boards generated; focused tests, py_compile, doc links, diff check, branch check, and browser smoke pass.
- Validation evidence: local HTTP browser smoke confirmed all twenty-five board titles/cards/tables and no raw `<script>` or `/Users/hskim` text.
- Eval surface: aggregate-only private real-eval plus public/governance/portfolio docs.
- Open risks: generated HTML files remain ignored local artifacts.
- Next action: N/A; merged in PR #1523.
- Next safe command: N/A
- Reviewer focus: privacy boundary, over-claiming, generated view wording.
```

## T-2026-0011 — Remaining HTML review boards

- ID: T-2026-0011
- Title: Remaining HTML review boards
- Status: done
- Owner role: Implementer -> Reviewer
- Created: 2026-05-26
- Last updated: 2026-05-26

### Goal

Extend the local human review renderer from six boards to all fifteen candidate
boards while keeping Markdown as the AI/source-of-truth format.

### Context

- Surface: private real-eval aggregate / public synthetic benchmark docs /
  governance docs / reviewer workflow.
- Relevant docs: [`docs/plans/T-2026-0011-remaining-html-review-boards.md`](../docs/plans/T-2026-0011-remaining-html-review-boards.md),
  [`docs/evaluation/surface-map.md`](../docs/evaluation/surface-map.md).
- Primary risk: HTML summaries accidentally implying a fresh eval run or
  replacing Markdown source-of-truth.

### Scope

- Add the remaining nine local HTML boards to the existing renderer.
- Use committed aggregate/redacted JSON and docs only.
- Keep generated HTML ignored and reproducible.

### Non-Goals

- Do not change RAG runtime, parser runtime, retrieval behavior, or eval scoring.
- Do not read private raw documents or per-case payloads.
- Do not make new performance claims.

### Acceptance Criteria

- [x] One command writes fifteen local HTML boards.
- [x] Existing six output paths still render.
- [x] Tests cover all fifteen board titles and escaping.
- [x] Generated HTML is manually smoke-checked through a local HTTP server.

### Validation Commands

```bash
python3 -m pytest tests/test_render_priority_review_boards.py -q
python3 -m py_compile scripts/render_priority_review_boards.py
python3 scripts/render_priority_review_boards.py
python3 scripts/check_doc_links.py --check-all
git diff --check
make check-branch
```

### Evidence Required

- Focused pytest output.
- Generated HTML paths.
- Browser smoke result.

### Failure Conditions

- Stop if a board needs raw private data.
- Stop if a board would introduce a new benchmark/eval claim.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0011-remaining-html-review-boards.md`](../docs/plans/T-2026-0011-remaining-html-review-boards.md)
- Issue: [#1520](https://github.com/hskim-solv/BidMate-DocAgent/issues/1520)
- PR: [#1521](https://github.com/hskim-solv/BidMate-DocAgent/pull/1521)

### Handoff Notes

```markdown
## Session Handoff — 2026-05-26 00:00 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1520-remaining-html-boards / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Task: T-2026-0011
- Plan: docs/plans/T-2026-0011-remaining-html-review-boards.md
- Current status: merged in PR #1521.
- Files touched: scripts/render_priority_review_boards.py, tests/test_render_priority_review_boards.py, tasks/queue.md, docs/plans/T-2026-0011-remaining-html-review-boards.md
- Decisions made: extend the existing renderer to fifteen boards.
- Commands run: gh issue create; git switch; python3 -m pytest tests/test_render_priority_review_boards.py -q; python3 -m py_compile scripts/render_priority_review_boards.py; python3 scripts/render_priority_review_boards.py; python3 scripts/check_doc_links.py --check-all; git diff --check; browser smoke via http://127.0.0.1:8765
- Results: fifteen local HTML boards generated; focused tests, py_compile, doc links, diff check, and browser smoke pass.
- Validation evidence: local HTTP browser smoke confirmed all fifteen board titles/cards/tables and no raw `<script>` or `/Users/hskim` text.
- Eval surface: aggregate-only private real-eval plus public/governance docs.
- Open risks: generated HTML files remain ignored local artifacts.
- Next action: N/A; merged in PR #1521.
- Next safe command: N/A
- Reviewer focus: privacy boundary, over-claiming, generated view wording.
```

## T-2026-0010 — Priority HTML review boards

- ID: T-2026-0010
- Title: Priority HTML review boards
- Status: done
- Owner role: Implementer -> Reviewer
- Created: 2026-05-26
- Last updated: 2026-05-26

### Goal

Render the next six aggregate reviewer surfaces as local HTML boards so a human
can inspect current eval/retrieval/governance signals without opening several
JSON and Markdown files.

### Context

- Surface: private real-eval aggregate / public synthetic benchmark docs /
  reviewer workflow.
- Relevant docs: [`docs/evaluation/surface-map.md`](../docs/evaluation/surface-map.md),
  [`docs/plans/T-2026-0010-priority-html-review-boards.md`](../docs/plans/T-2026-0010-priority-html-review-boards.md).
- Primary risk: HTML summaries accidentally implying a fresh eval run or
  exposing private raw data.

### Scope

- Add a local renderer for six HTML boards.
- Use existing aggregate/redacted JSON and docs only.
- Add focused renderer tests.
- Preserve the operating convention that AI handoff/source-of-truth stays in
  Markdown while human review boards are rendered as HTML.

### Non-Goals

- Do not change RAG runtime, parser runtime, retrieval behavior, or eval scoring.
- Do not read private raw documents or per-case payloads.
- Do not claim performance improvement.

### Acceptance Criteria

- [x] One command writes all six local HTML boards.
- [x] Tests prove escaping and repository-relative source paths.
- [x] Generated HTML is manually smoke-checked through a local HTTP server.

### Validation Commands

```bash
python3 -m pytest tests/test_render_priority_review_boards.py -q
python3 scripts/render_priority_review_boards.py
git diff --check
```

### Evidence Required

- Focused pytest output.
- Generated HTML paths.
- Browser smoke result.

### Failure Conditions

- Stop if a board needs raw private data.
- Stop if the board would introduce a new benchmark/eval claim.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0010-priority-html-review-boards.md`](../docs/plans/T-2026-0010-priority-html-review-boards.md)
- Issue: [#1518](https://github.com/hskim-solv/BidMate-DocAgent/issues/1518)
- PR: [#1519](https://github.com/hskim-solv/BidMate-DocAgent/pull/1519)

### Handoff Notes

```markdown
## Session Handoff — 2026-05-26 00:00 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1518-priority-html-boards / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Task: T-2026-0010
- Plan: docs/plans/T-2026-0010-priority-html-review-boards.md
- Current status: merged in PR #1519.
- Files touched: CLAUDE.md, tasks/queue.md, docs/plans/T-2026-0010-priority-html-review-boards.md, scripts/render_priority_review_boards.py, tests/test_render_priority_review_boards.py
- Decisions made: presentation-only renderer; aggregate/redacted inputs only.
- Commands run: gh issue create; git switch; python3 -m pytest tests/test_render_priority_review_boards.py -q; python3 scripts/render_priority_review_boards.py; git diff --check; python3 scripts/check_doc_links.py --check-all; browser smoke via http://127.0.0.1:8765
- Results: six HTML boards generated locally; focused tests, doc links, diff check, and browser smoke pass.
- Validation evidence: local HTTP browser smoke confirmed all six board titles/cards/tables.
- Eval surface: aggregate-only private real-eval plus public docs.
- Open risks: generated HTML files remain ignored local artifacts; script regenerates them.
- Next action: N/A; merged in PR #1519.
- Next safe command: N/A
- Reviewer focus: privacy boundary, over-claiming, escaping.
```

## T-2026-0001 — Benchmark hardening against synthetic contamination

- ID: T-2026-0001
- Title: Benchmark hardening against synthetic contamination
- Status: done
- Owner role: Implementer -> Benchmark Auditor -> Reviewer
- Created: 2026-05-25
- Last updated: 2026-05-25

### Goal

Prevent public synthetic benchmark results from being inflated by leakage,
contaminated index inputs, or over-claiming.

### Context

- Surface: public synthetic benchmark.
- Relevant docs: [`docs/evaluation/surface-map.md`](../docs/evaluation/surface-map.md),
  [`docs/evaluation/synthetic_benchmark_v1_design.md`](../docs/evaluation/synthetic_benchmark_v1_design.md).
- Primary risk: synthetic-only success being read as real RFP performance.

### Scope

- Inspect benchmark validator and index builder input boundaries.
- Add focused tests or docs only if a concrete gap is found.
- Keep changes out of retrieval/answer production behavior.

### Non-Goals

- Do not improve benchmark score.
- Do not change private real-eval.
- Do not introduce a new benchmark dataset.

### Acceptance Criteria

- [x] Benchmark index build is documented/tested as corpus-only.
- [x] Benchmark claim wording is synthetic-only and links to the surface map.
- [x] Benchmark Auditor checklist is satisfied.

### Validation Commands

```bash
python3 eval/naive_rag/validate_benchmark_dataset.py \
  --config configs/eval/benchmark_naive_rag_v1.yaml \
  --report reports/benchmark/naive_rag_v1_validation.json

python3 -m pytest tests/test_naive_rag_benchmark_v1.py -q
```

### Evidence Required

- Validation report summary.
- Focused pytest output.
- Review note confirming no real-world performance claim.

### Failure Conditions

- Stop if index build reads questions/gold/expected answers.
- Stop if the task requires changing scoring semantics; that needs a new plan.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0001-benchmark-contamination-guard.md`](../docs/plans/T-2026-0001-benchmark-contamination-guard.md)
- Issue: [#1480](https://github.com/hskim-solv/BidMate-DocAgent/issues/1480)
- PR: [#1481](https://github.com/hskim-solv/BidMate-DocAgent/pull/1481)
- ADR: [ADR 0005](../docs/adr/0005-eval-split-public-synthetic-private-local.md)
- Report: TBD

### Handoff Notes

```markdown
## Session Handoff — 2026-05-25 00:00 KST

- Role: Task Queue Designer
- Branch / worktree: TBD by implementer
- Current status: ready
- Decisions made: Treat this as benchmark validity hardening, not metric improvement.
- Commands run: None yet.
- Results: Task is ready when an implementer can run validation commands or document why a command is unavailable.
- Next safe command: inspect benchmark validator and index build inputs.
- Risks: Scope creep into scoring semantics or unsupported real-eval claims.
```

```markdown
## Session Handoff — 2026-05-25 18:49 KST

- Role: Implementer
- Lifecycle stage: done
- Branch / worktree: fix/issue-1480-benchmark-eval-surface-guards / /Users/hskim/.codex/worktrees/cd0b/BidMate-DocAgent
- Task: T-2026-0001
- Plan: docs/plans/T-2026-0001-benchmark-contamination-guard.md
- Current status: merged in PR #1481.
- Files touched: eval/naive_rag/validate_benchmark_dataset.py, tests/test_naive_rag_benchmark_v1.py
- Decisions made: Additive validator report only; no benchmark scoring or retrieval behavior change.
- Commands run: python3 eval/naive_rag/validate_benchmark_dataset.py --config configs/eval/benchmark_naive_rag_v1.yaml --report reports/benchmark/naive_rag_v1_validation.json; python3 -m pytest tests/test_naive_rag_benchmark_v1.py -q; python3 -m py_compile eval/naive_rag/validate_benchmark_dataset.py scripts/compare_eval.py; git diff --check
- Results: pass; validation report index_build_boundary.status=pass; PR #1481 merged.
- Validation evidence: reports/benchmark/naive_rag_v1_validation.json generated locally.
- Eval surface: public synthetic benchmark.
- Evidence artifacts: local validation JSON only.
- Open risks: none for this task; follow-up benchmark expansion remains separate.
- Next action: N/A
- Next safe command: N/A
- Reviewer focus: corpus-only proof, prohibited label fields, no metric semantics change.
```

## T-2026-0002 — Eval regression safety surface separation

- ID: T-2026-0002
- Title: Eval regression safety surface separation
- Status: done
- Owner role: Implementer -> Reviewer
- Created: 2026-05-25
- Last updated: 2026-05-25

### Goal

Make it harder for future agents to conflate public fixture smoke,
public synthetic benchmark, and private real-eval artifacts when reporting
regression evidence.

### Context

- Surface: eval governance.
- Relevant docs: [`docs/evaluation/surface-map.md`](../docs/evaluation/surface-map.md),
  [ADR 0005](../docs/adr/0005-eval-split-public-synthetic-private-local.md).
- Primary risk: comparing incompatible `eval_summary.json` files.

### Scope

- Add docs/tests only around artifact naming, provenance, or checklist gaps.
- Verify existing doc links and PR template wording.

### Non-Goals

- Do not change eval scoring.
- Do not run or expose private raw eval data.
- Do not make private real-eval a CI requirement.

### Acceptance Criteria

- [x] Future agents can identify which `eval_summary.json` they are reading.
- [x] Smoke/synthetic/private claims are explicitly separated.
- [x] Reviewer checklist catches incompatible artifact comparisons.

### Validation Commands

```bash
python3 scripts/check_doc_links.py --check-all
python3 -m pytest tests/test_eval_artifact_privacy_regression.py -q
```

### Evidence Required

- Doc link check output.
- Focused pytest output.
- Reviewer note confirming claim boundary clarity.

### Failure Conditions

- Stop if proposed changes require private raw artifact inspection.
- Stop if this expands into metric semantics; create a separate plan.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0002-eval-artifact-surface-guard.md`](../docs/plans/T-2026-0002-eval-artifact-surface-guard.md)
- Issue: [#1480](https://github.com/hskim-solv/BidMate-DocAgent/issues/1480)
- PR: [#1481](https://github.com/hskim-solv/BidMate-DocAgent/pull/1481)
- ADR: [ADR 0005](../docs/adr/0005-eval-split-public-synthetic-private-local.md)
- Report: TBD

### Handoff Notes

```markdown
## Session Handoff — 2026-05-25 00:00 KST

- Role: Task Queue Designer
- Branch / worktree: TBD by implementer
- Current status: ready
- Decisions made: Treat smoke, synthetic benchmark, and private real-eval as separate evidence surfaces.
- Commands run: None yet.
- Results: Task is ready when an implementer can prove artifact provenance or document manual validation.
- Next safe command: inspect eval artifact docs and existing regression tests.
- Risks: Accidentally requiring private raw data or comparing incompatible summaries.
```

```markdown
## Session Handoff — 2026-05-25 18:49 KST

- Role: Implementer
- Lifecycle stage: done
- Branch / worktree: fix/issue-1480-benchmark-eval-surface-guards / /Users/hskim/.codex/worktrees/cd0b/BidMate-DocAgent
- Task: T-2026-0002
- Plan: docs/plans/T-2026-0002-eval-artifact-surface-guard.md
- Current status: merged in PR #1481.
- Files touched: scripts/compare_eval.py, tests/test_compare_eval_regression_gate.py
- Decisions made: Unknown surfaces remain visible but non-blocking by default to preserve PR eval compatibility.
- Commands run: python3 -m pytest tests/test_compare_eval_regression_gate.py -q; python3 scripts/check_doc_links.py --check-all; python3 -m pytest tests/test_eval_artifact_privacy_regression.py -q; python3 -m py_compile eval/naive_rag/validate_benchmark_dataset.py scripts/compare_eval.py; git diff --check
- Results: pass; PR #1481 merged.
- Validation evidence: focused tests, doc link check, PR Eval Delta.
- Eval surface: eval governance; no benchmark metric semantics changed.
- Evidence artifacts: none committed.
- Open risks: Reviewer should decide whether CI should enable --fail-on-surface-mismatch later.
- Next action: no action; follow-up CI wiring would be a separate task.
- Next safe command: N/A
- Reviewer focus: backward-compatible output shape, no private raw data dependency, no incompatible surface overclaim.
```

## T-2026-0003 — Desktop main auto-sync after auto-ship merge

- ID: T-2026-0003
- Title: Desktop main auto-sync after auto-ship merge
- Status: done
- Owner role: Implementer -> Reviewer
- Created: 2026-05-25
- Last updated: 2026-05-26

### Goal

After a successful auto-ship merge, make the canonical Desktop checkout's
`main` match GitHub `origin/main` without requiring a manual pull.

### Context

- Surface: developer tooling / auto-ship.
- Relevant docs: [`docs/operations/auto-ship.md`](../docs/operations/auto-ship.md).
- Primary risk: stale Desktop `main` causing follow-up work to branch from an old base.

### Scope

- Add a fail-soft sync helper.
- Call it from auto-ship Stage 5 after merge success.
- Add focused temp-repo tests.

### Non-Goals

- Do not reset or discard local Desktop work.
- Do not make Desktop sync a merge blocker.
- Do not alter eval/runtime behavior.

### Acceptance Criteria

- [x] Clean Desktop `main` fast-forwards to `origin/main`.
- [x] Dirty or divergent Desktop `main` is skipped.
- [x] Auto-ship Stage 5 invokes the helper after merge success.

### Validation Commands

```bash
python3 -m pytest tests/test_sync_desktop_main.py -q
python3 -m py_compile scripts/sync_desktop_main.py
git diff --check
```

### Evidence Required

- Focused pytest output.
- Manual note that Desktop main was synced after #1481 merge.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0003-desktop-main-auto-sync.md`](../docs/plans/T-2026-0003-desktop-main-auto-sync.md)
- Issue: [#1482](https://github.com/hskim-solv/BidMate-DocAgent/issues/1482)
- PR: [#1483](https://github.com/hskim-solv/BidMate-DocAgent/pull/1483)
- ADR: N/A

### Handoff Notes

```markdown
## Session Handoff — 2026-05-25 19:20 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1482-desktop-main-sync / /Users/hskim/.codex/worktrees/cd0b/BidMate-DocAgent
- Task: T-2026-0003
- Plan: docs/plans/T-2026-0003-desktop-main-auto-sync.md
- Current status: merged in PR #1483.
- Files touched: scripts/sync_desktop_main.py, scripts/claude-hooks/stop-ship.sh, tests/test_sync_desktop_main.py, docs/operations/auto-ship.md, tasks/queue.md
- Decisions made: dirty/divergent/missing Desktop repo skips; merge remains successful.
- Commands run: python3 -m pytest tests/test_sync_desktop_main.py -q; python3 -m py_compile scripts/sync_desktop_main.py; bash -n scripts/claude-hooks/stop-ship.sh; python3 scripts/check_doc_links.py --check-all; git diff --check; python3 scripts/sync_desktop_main.py --repo /Users/hskim/Desktop/projects/BidMate-DocAgent
- Results: pass; Desktop main already matches origin/main after manual fast-forward.
- Eval surface: none.
- Open risks: Reviewer should verify branch update cannot discard local work.
- Next action: N/A; merged in PR #1483.
- Next safe command: N/A
- Reviewer focus: no reset/destructive behavior, fail-soft Stage 5 behavior.
```

## T-2026-0004 — HWP PDF PyMuPDF4LLM opt-in loader

- ID: T-2026-0004
- Title: HWP PDF PyMuPDF4LLM opt-in loader
- Status: done
- Owner role: Implementer -> Reviewer
- Created: 2026-05-26
- Last updated: 2026-05-26

### Goal

Add an opt-in HWP parser path that converts HWP to PDF and parses the PDF with
PyMuPDF4LLM page chunks, while preserving the ADR 0049 `kordoc` default and
ADR 0001 `csv_text` fallback.

### Context

- Surface: load-bearing ingestion parser.
- Relevant docs: [ADR 0049](../docs/adr/0049-kordoc-replaces-pyhwp-backend.md),
  [HWP extraction comparison](../docs/hwp/hwp-extraction-comparison.md).
- Primary risk: historical LibreOffice HWP conversion failure being reported
  as successful parsing.

### Scope

- Add `BIDMATE_HWP_LOADER=pdf_pymupdf4llm` and matching `--hwp_loader` choice.
- Validate converter output with PyMuPDF before PyMuPDF4LLM parsing.
- Record stable fallback reason keys and redact private path/file details.
- Extend the local comparison script with a PyMuPDF4LLM path.

### Non-Goals

- Do not change the default `kordoc` loader.
- Do not auto-install H2Orestart or other LibreOffice extensions.
- Do not claim real-eval quality without a separate private run.

### Acceptance Criteria

- [x] Default HWP loader remains `HwpKordocLoader`.
- [x] Opt-in loader returns page sections with `page_span` on success.
- [x] Converter/parser failures fall back to CSV text unless required mode is set.
- [x] Required mode raises instead of falling back.
- [x] Focused regression tests cover success and failure modes.

### Validation Commands

```bash
python3 -m unittest tests.test_hwp_pdf_pymupdf4llm_loader -v
python3 -m pytest tests/test_ingestion_kordoc_regression.py tests/test_mixed_format_ingestion_regression.py tests/test_hwp_pdf_pymupdf4llm_loader.py -q
python3 -m py_compile ingestion.py scripts/build_index.py scripts/compare_hwp_extraction.py tests/test_hwp_pdf_pymupdf4llm_loader.py
```

### Evidence Required

- Focused unittest output.
- Pytest exit code 0 for existing ingestion regressions plus new loader tests.
- Manual reviewer check that fallback diagnostics do not leak private paths.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0004-hwp-pdf-pymupdf4llm-loader.md`](../docs/plans/T-2026-0004-hwp-pdf-pymupdf4llm-loader.md)
- Issue: [#1492](https://github.com/hskim-solv/BidMate-DocAgent/issues/1492)
- PR: [#1494](https://github.com/hskim-solv/BidMate-DocAgent/pull/1494)
- ADR: [ADR 0078](../docs/adr/0078-pymupdf4llm-canonical-page-citation.md)

### Handoff Notes

```markdown
## Session Handoff — 2026-05-26 00:00 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: detached HEAD / /Users/hskim/.codex/worktrees/a32e/BidMate-DocAgent
- Task: T-2026-0004
- Plan: docs/plans/T-2026-0004-hwp-pdf-pymupdf4llm-loader.md
- Current status: merged in PR #1494.
- Files touched: ingestion.py, rag_answer.py, rag_indexing.py, rag_retrieval.py, rag_provenance.py, scripts/build_index.py, eval/run_eval.py, requirements-pymupdf4llm.txt, tests, docs/plans, ADR 0078, tasks/queue.md
- Decisions made: default HWP/PDF loader is pdf_pymupdf4llm; HWP citations refer to preserved LibreOffice converted PDF artifacts; parser failures fail closed unless explicit csv_text is selected.
- Commands run: python3 -m unittest tests.test_hwp_pdf_pymupdf4llm_loader -v; python3 -m pytest tests/test_ingestion_kordoc_regression.py tests/test_mixed_format_ingestion_regression.py tests/test_hwp_pdf_pymupdf4llm_loader.py tests/test_provenance_banner.py tests/test_run_eval_by_format_text_source.py tests/test_page_aware_parser_contract.py tests/test_eval_metrics.py tests/test_answer_contract_snapshot.py tests/test_retrieval_loop_regression.py -q; python3 -m ruff check ...; python3 -m py_compile ...; git diff --check; python3 scripts/_governance.py --lint-adr-consequences docs/adr/0078-pymupdf4llm-canonical-page-citation.md; python3 scripts/check_doc_links.py --check-all --paths ...
- Results: pass.
- Eval surface: none; no real-eval quality claim.
- Open risks: actual HWP conversion quality still depends on local LibreOffice HWP filter setup.
- Next action: N/A; merged in PR #1494.
- Next safe command: N/A
- Reviewer focus: fail-closed parser policy, private path exclusion from answer citations, and page-citation-ready telemetry.
```

## T-2026-0005 — Eval-first RAG adapter hardening

- ID: T-2026-0005
- Title: Eval-first RAG adapter hardening
- Status: done
- Owner role: Implementer -> Benchmark Auditor -> Reviewer
- Created: 2026-05-26
- Last updated: 2026-05-26

### Goal

Implement the eval-first RAG hardening plan without creating a new `src/rag/*`
tree or changing the `naive_baseline` / answer schema / ADR 0005 boundary.

### Context

- Surface: public fixture smoke eval + eval governance.
- Relevant docs: [ADR 0001](../docs/adr/0001-preserve-naive-baseline.md),
  [ADR 0003](../docs/adr/0003-structured-answer-citation-contract.md),
  [ADR 0005](../docs/adr/0005-eval-split-public-synthetic-private-local.md),
  [ADR 0069](../docs/adr/0069-retrieval-aggregate-and-citation-coverage-surface.md),
  [ADR 0074](../docs/adr/0074-rfp-rag-stage-separation.md).
- Primary risk: mixing measurement additions with default behavior changes.

### Scope

- Add LLM-free context precision/recall retrieval metrics.
- Extend run/index version manifest fields additively.
- Add `EmbeddingProvider` Protocol/factory around existing `rag_embedding.py`.
- Add opt-in deterministic contextual chunking while preserving fixed/section defaults.
- Keep Qdrant/pgvector and multimodal expansion as follow-up-only surfaces.

### Non-Goals

- Do not change `naive_baseline`.
- Do not bump answer `schema_version`.
- Do not make HyDE, Self-RAG, Reflexion, CRAG, ColPali, or GPT-VL default.
- Do not send private data to external providers.

### Acceptance Criteria

- [x] `reports/eval_summary.json` can expose context precision/recall aggregates.
- [x] `run_manifest` carries index/chunking/embedding version fields.
- [x] Embedding provider swapping is tested with fake/local providers.
- [x] Contextual chunking is opt-in and regression-tested.
- [x] Focused tests and branch convention checks pass.

### Validation Commands

```bash
python3 -m pytest tests/test_chunk_metrics_regression.py tests/test_chunk_aggregate_regression.py tests/test_run_manifest_versioning_regression.py -q
python3 -m pytest tests/test_embedding_provider_protocol.py tests/test_contextual_chunking_regression.py -q
python3 -m pytest tests/test_vector_store_protocol.py tests/test_vector_store_qdrant.py -q
make check-branch
```

### Evidence Required

- Focused pytest output.
- Smoke/eval summary diff explanation.
- Review note confirming baseline and answer contract unchanged.

### Failure Conditions

- Stop if the implementation requires changing answer dict shape.
- Stop if external provider code would run by default.
- Stop if public fixture smoke is used as a real-world quality claim.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0005-rag-eval-first-adapter-hardening.md`](../docs/plans/T-2026-0005-rag-eval-first-adapter-hardening.md)
- Issue: [#1493](https://github.com/hskim-solv/BidMate-DocAgent/issues/1493)
- PR: [#1499](https://github.com/hskim-solv/BidMate-DocAgent/pull/1499)
- ADR: ADR 0001, ADR 0003, ADR 0005, ADR 0069, ADR 0074

## T-2026-0006 — Human-readable AI next actions review surface

- ID: T-2026-0006
- Title: Human-readable AI next actions review surface
- Status: done
- Owner role: Implementer -> Reviewer
- Created: 2026-05-26
- Last updated: 2026-05-26

### Goal

Give human reviewers a compact local HTML status board for the deterministic
AI next-action planner, without replacing the existing Markdown task briefs.

### Context

- Surface: workflow/reviewer tooling.
- Relevant docs: [`docs/operations/ai-codex-workflow.md`](../docs/operations/ai-codex-workflow.md),
  [`docs/reviews/README.md`](../docs/reviews/README.md).
- Primary risk: dense agent-oriented Markdown being treated as sufficient for
  human triage, or local generated HTML being mistaken for PR evidence.

### Scope

- Add `reports/ai_next_actions.html` as a generated local artifact.
- Keep `reports/ai_next_actions.md` and `reports/codex_tasks/*.md` behavior.
- Document that the HTML is a status board, not approval evidence.

### Non-Goals

- Do not change retrieval, verifier, answer, eval, or private-data behavior.
- Do not introduce JavaScript, external services, or new runtime dependencies.
- Do not publish local `reports/*` artifacts.

### Acceptance Criteria

- [x] Planner emits Markdown, task briefs, and self-contained HTML from one
  deterministic work-item model.
- [x] HTML escapes PR/user-provided text and does not leak forbidden private
  readiness fields.
- [x] HTML output can be disabled with `--out-html ""`.
- [x] Reviewer docs explain how to use the local status board.

### Validation Commands

```bash
python3 -m py_compile scripts/ai_next_actions.py
python3 -m pytest -q tests/test_ai_next_actions.py
python3 scripts/check_doc_links.py --check-all
git diff --check
make check-branch
```

### Evidence Required

- Focused pytest output.
- Doc-link check output.
- Manual note if browser visual verification is unavailable.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0006-human-review-surface.md`](../docs/plans/T-2026-0006-human-review-surface.md)
- Issue: [#1506](https://github.com/hskim-solv/BidMate-DocAgent/issues/1506)
- PR: [#1509](https://github.com/hskim-solv/BidMate-DocAgent/pull/1509)
- ADR: N/A

### Handoff Notes

```markdown
## Session Handoff — 2026-05-26 00:00 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1506-human-review-surface / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Task: T-2026-0006
- Plan: docs/plans/T-2026-0006-human-review-surface.md
- Current status: merged in PR #1509.
- Files touched: scripts/ai_next_actions.py, tests/test_ai_next_actions.py, docs/operations/ai-codex-workflow.md, docs/reviews/README.md, tasks/queue.md, docs/plans/T-2026-0006-human-review-surface.md
- Decisions made: Generate a self-contained local HTML file next to the existing Markdown output; keep source-of-truth logic in WorkItem classification and keep HTML non-evidence.
- Commands run: python3 -m py_compile scripts/ai_next_actions.py; python3 -m pytest -q tests/test_ai_next_actions.py; python3 scripts/check_doc_links.py --check-all; git diff --check; make check-branch
- Results: pass, except browser file:// visual verification was blocked by app URL policy.
- Eval surface: none.
- Open risks: reviewer should inspect whether the inline HTML/CSS is acceptable for a local-only generated report.
- Next action: N/A; merged in PR #1509.
- Next safe command: N/A
- Reviewer focus: privacy-safe rendering, deterministic output, and no evidence over-claim.
```

## T-2026-0007 — Human-readable failure case board

- ID: T-2026-0007
- Title: Human-readable failure case board
- Status: done
- Owner role: Implementer -> Reviewer
- Created: 2026-05-26
- Last updated: 2026-05-26

### Goal

Give reviewers a compact local HTML view of failure-mode distribution and
per-category slices without replacing the committed Markdown/aggregate JSON
evidence.

### Context

- Surface: private real-eval aggregate viewer.
- Relevant docs: [`docs/operations/failure-mode-harden-process.md`](../docs/operations/failure-mode-harden-process.md),
  [ADR 0005](../docs/adr/0005-eval-split-public-synthetic-private-local.md),
  [ADR 0075](../docs/adr/0075-normalized-failure-taxonomy.md).
- Primary risk: raw private query/doc strings leaking into a human-facing local
  report, or HTML being mistaken for model-quality evidence.

### Scope

- Add `reports/real100/failure_distribution.html` as a generated local artifact.
- Keep `reports/real100/failure_distribution.md` and
  `reports/real100/failure_distribution.aggregate.json` behavior unchanged.
- Add a small shared HTML report shell for future local report surfaces.

### Non-Goals

- Do not change failure classifier ordering, taxonomy, eval scoring, retrieval,
  verifier, answer generation, or private raw data.
- Do not introduce JavaScript, external services, or runtime dependencies.
- Do not publish local HTML artifacts.

### Acceptance Criteria

- [x] Renderer emits Markdown, aggregate JSON, and self-contained HTML by default.
- [x] HTML output can be disabled with `--out-html ""`.
- [x] HTML escapes dynamic text and does not leak raw query/doc strings.
- [x] Existing aggregate schema remains unchanged.
- [x] Workflow docs mention the local HTML dashboard.

### Validation Commands

```bash
python3 -m py_compile scripts/html_report.py scripts/render_failure_distribution.py
python3 -m pytest -q tests/test_render_failure_distribution.py
python3 scripts/check_doc_links.py --check-all --paths docs/plans/T-2026-0007-failure-case-board.md tasks/queue.md docs/operations/failure-mode-harden-process.md
git diff --check
make check-branch
```

### Evidence Required

- Focused pytest output.
- Doc-link check output.
- Note that no real-eval performance claim is made.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0007-failure-case-board.md`](../docs/plans/T-2026-0007-failure-case-board.md)
- Issue: [#1510](https://github.com/hskim-solv/BidMate-DocAgent/issues/1510)
- PR: [#1511](https://github.com/hskim-solv/BidMate-DocAgent/pull/1511)
- ADR: N/A

### Handoff Notes

```markdown
## Session Handoff — 2026-05-26 00:00 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1510-failure-case-board / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Task: T-2026-0007
- Plan: docs/plans/T-2026-0007-failure-case-board.md
- Current status: merged in PR #1511.
- Files touched: scripts/html_report.py, scripts/render_failure_distribution.py, tests/test_render_failure_distribution.py, docs/operations/failure-mode-harden-process.md, tasks/queue.md, docs/plans/T-2026-0007-failure-case-board.md
- Decisions made: Generate a self-contained local HTML file next to the existing Markdown/aggregate JSON output; keep source-of-truth classification in build_aggregate and failure_classifier.
- Commands run: python3 -m py_compile scripts/html_report.py scripts/render_failure_distribution.py; python3 -m pytest -q tests/test_render_failure_distribution.py; git diff --check
- Results: pass.
- Eval surface: private real-eval aggregate viewer only.
- Open risks: reviewer should inspect whether a later PR should migrate ai_next_actions HTML to the shared shell.
- Next action: N/A; merged in PR #1511.
- Next safe command: N/A
- Reviewer focus: privacy-safe rendering, aggregate-only data boundary, and no evidence over-claim.
```

## T-2026-0008 — Human-readable chunking diagnostics board

- ID: T-2026-0008
- Title: Human-readable chunking diagnostics board
- Status: done
- Owner role: Implementer -> Reviewer
- Created: 2026-05-26
- Last updated: 2026-05-26

### Goal

Give reviewers a compact local HTML view of Phase 2 chunking ablation, real100
chunk health, and multi-chunk evidence failure diagnostics without changing
retrieval or chunking behavior.

### Context

- Surface: private real-eval aggregate viewer plus existing Phase 2 retrieval
  aggregate report.
- Relevant docs: [`docs/retrieval/chunking-diagnostics.md`](../docs/retrieval/chunking-diagnostics.md),
  [ADR 0005](../docs/adr/0005-eval-split-public-synthetic-private-local.md),
  [ADR 0076](../docs/adr/0076-multi-chunk-evidence-failure-analysis-surface.md).
- Primary risk: a diagnostic board being mistaken for a chunking winner claim,
  or per-case identifiers/text leaking into local HTML.

### Scope

- Add `reports/retrieval/chunking_diagnostics.html` as a generated local artifact.
- Read existing aggregate or aggregate-derived artifacts only.
- Keep Phase 2 report files and real100 aggregate files unchanged.

### Non-Goals

- Do not change chunking defaults, retrieval, verifier, answer generation, eval
  scoring, or private raw data.
- Do not introduce JavaScript, external services, or runtime dependencies.
- Do not publish local HTML artifacts.

### Acceptance Criteria

- [x] Renderer emits a self-contained local HTML board.
- [x] HTML includes chunking variants, recall@10 deltas, chunk health, and
  multi-chunk retrieval outcome counts.
- [x] HTML does not render private case ids from per-case inputs.
- [x] Existing retrieval/chunking/eval behavior remains unchanged.

### Validation Commands

```bash
python3 -m py_compile scripts/render_chunking_diagnostics_board.py scripts/html_report.py
python3 -m pytest -q tests/test_render_chunking_diagnostics_board.py
python3 scripts/check_doc_links.py --check-all --paths docs/plans/T-2026-0008-chunking-diagnostics-board.md tasks/queue.md docs/retrieval/chunking-diagnostics.md
git diff --check
make check-branch
```

### Evidence Required

- Focused pytest output.
- Doc-link check output.
- Note that no chunking winner or RAG quality claim is made.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0008-chunking-diagnostics-board.md`](../docs/plans/T-2026-0008-chunking-diagnostics-board.md)
- Issue: [#1514](https://github.com/hskim-solv/BidMate-DocAgent/issues/1514)
- PR: [#1515](https://github.com/hskim-solv/BidMate-DocAgent/pull/1515)
- ADR: N/A

### Handoff Notes

```markdown
## Session Handoff — 2026-05-26 00:00 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1514-chunking-diagnostics-board / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Task: T-2026-0008
- Plan: docs/plans/T-2026-0008-chunking-diagnostics-board.md
- Current status: merged in PR #1515.
- Files touched: scripts/render_chunking_diagnostics_board.py, tests/test_render_chunking_diagnostics_board.py, docs/retrieval/chunking-diagnostics.md, tasks/queue.md, docs/plans/T-2026-0008-chunking-diagnostics-board.md
- Decisions made: Generate a self-contained local HTML file from existing aggregate artifacts; do not claim a chunking winner.
- Commands run: python3 -m py_compile scripts/render_chunking_diagnostics_board.py scripts/html_report.py; python3 -m pytest -q tests/test_render_chunking_diagnostics_board.py; git diff --check
- Results: pass.
- Eval surface: private real-eval aggregate viewer plus existing Phase 2 retrieval aggregate report.
- Open risks: reviewer should inspect claim wording and whether additional slices belong in a separate follow-up.
- Next action: N/A; merged in PR #1515.
- Next safe command: N/A
- Reviewer focus: claim boundary, aggregate-only rendering, and no default behavior change.
```

## T-2026-0009 — Human-readable ADR decision map

- ID: T-2026-0009
- Title: Human-readable ADR decision map
- Status: done
- Owner role: Implementer -> Reviewer
- Created: 2026-05-26
- Last updated: 2026-05-26

### Goal

Give reviewers a compact local HTML map of ADR status mix, decision areas,
recent ADRs, proposed ADRs, and superseded decisions without editing ADR source
files.

### Context

- Surface: ADR navigation/reviewer tooling.
- Relevant docs: [`docs/adr/README.md`](../docs/adr/README.md).
- Primary risk: a generated HTML view being mistaken for the ADR source of
  truth, or keyword-based area grouping being treated as governance logic.

### Scope

- Add `reports/adr_decision_map.html` as a generated local artifact.
- Parse existing `docs/adr/README.md` rows.
- Keep ADR files, statuses, numbering, and README content unchanged.

### Non-Goals

- Do not create or edit ADRs.
- Do not reserve ADR numbers.
- Do not promote/demote statuses or enforce lifecycle policy.
- Do not introduce JavaScript, external services, or runtime dependencies.

### Acceptance Criteria

- [x] Renderer emits a self-contained local HTML board.
- [x] HTML includes status mix, decision areas, recent ADRs, proposed ADRs, and
  superseded decisions.
- [x] Tests verify canonical row parsing, status counts, and escaping.
- [x] ADR source files remain unmodified.

### Validation Commands

```bash
python3 scripts/render_adr_decision_map.py
python3 -m py_compile scripts/render_adr_decision_map.py scripts/html_report.py
python3 -m pytest -q tests/test_render_adr_decision_map.py
python3 scripts/check_doc_links.py --check-all --paths docs/plans/T-2026-0009-adr-decision-map.md tasks/queue.md
git diff --check
make check-branch
```

### Evidence Required

- Focused pytest output.
- Doc-link check output.
- Note that `docs/adr/README.md` and ADR files are unchanged.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0009-adr-decision-map.md`](../docs/plans/T-2026-0009-adr-decision-map.md)
- Issue: [#1516](https://github.com/hskim-solv/BidMate-DocAgent/issues/1516)
- PR: [#1517](https://github.com/hskim-solv/BidMate-DocAgent/pull/1517)
- ADR: N/A

### Handoff Notes

```markdown
## Session Handoff — 2026-05-26 00:00 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: chore/issue-1516-adr-decision-map / /Users/hskim/.codex/worktrees/8ed1/BidMate-DocAgent
- Task: T-2026-0009
- Plan: docs/plans/T-2026-0009-adr-decision-map.md
- Current status: merged in PR #1517.
- Files touched: scripts/render_adr_decision_map.py, tests/test_render_adr_decision_map.py, tasks/queue.md, docs/plans/T-2026-0009-adr-decision-map.md
- Decisions made: Generate a self-contained local HTML file from docs/adr/README.md only; keep ADR source files unchanged.
- Commands run: python3 scripts/render_adr_decision_map.py; python3 -m py_compile scripts/render_adr_decision_map.py scripts/html_report.py; python3 -m pytest -q tests/test_render_adr_decision_map.py; git diff --check
- Results: pass.
- Eval surface: none.
- Open risks: reviewer should inspect that area grouping is navigation-only.
- Next action: N/A; merged in PR #1517.
- Next safe command: N/A
- Reviewer focus: source-of-truth wording, parser robustness, and escaping.
```

<!-- Draft generated by scripts/agent_loop.py draft-task. Review before applying. -->
## T-2026-0022 — Use multi-chunk evidence analysis for the next retrieval follow-up

- ID: T-2026-0022
- Title: Use multi-chunk evidence analysis for the next retrieval follow-up
- Status: backlog
- Owner role: Planner -> Implementer -> Reviewer

### Goal

Turn the aggregate multi-chunk evidence split into one scoped measurement follow-up.

### Context

- Classification: `next_experiment_candidate`
- Source: `reports/real100/[redacted-private-artifact]`
- Source PRs: `PR corpus`
- Workset: `general`
- Lane: `parallel-safe`
- Role hints: `Planner, Implementer, Reviewer`
- Reason: multi-chunk aggregate is available: 97/99 top-10 failures; 97 limited-depth cases
- Source brief: `reports/agent_loop/codex_tasks/001-multi-chunk-follow-up.md`
- Suggested plan path: `docs/plans/T-2026-0022-use-multi-chunk-evidence-analysis-for-the-next-retrieval-fol.md`

### Acceptance Criteria

- [ ] Scope stays limited to the cited workflow surface.
- [ ] Public-safe evidence or no-go rationale is captured without raw private data.
- [ ] Reviewer prompt covers any eval, benchmark, privacy, or architecture surface touched.

### Validation Commands

```bash
python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py
git diff --check
```

### Evidence Required

The follow-up chooses pool/rerank, decomposition, or section-expansion measurement using aggregate counts only.

### Completion Proof

Focused validation passes and the follow-up evidence is recorded.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0022-use-multi-chunk-evidence-analysis-for-the-next-retrieval-fol.md`](../docs/plans/T-2026-0022-use-multi-chunk-evidence-analysis-for-the-next-retrieval-fol.md)
- Issue: [#1563](https://github.com/hskim-solv/BidMate-DocAgent/issues/1563)
- PR: TBD

## T-2026-0023 — RAG performance agent operating goal

- ID: T-2026-0023
- Title: RAG performance agent operating goal
- Status: ready
- Owner role: Planner -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Deep Reviewer -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Make RAG system performance improvement the long-running agent-loop goal, with
the 8 operating principles written into the queue, plan, and operating docs so
future sessions do not collapse into only small local fixes.

### Context

- Issue: #1569
- Surface: docs/governance only.
- Operating principles:
  1. Hold a broad outcome scope.
  2. Maintain long sessions through queue, plan, and handoff artifacts.
  3. Keep todo state in tracked files.
  4. Invest in plan docs before broad changes.
  5. Attach adversarial, deep, benchmark, and privacy reviewers.
  6. Split Planner, Implementer, Tester/CI Reviewer, Issue Triage, Deep Reviewer,
     Benchmark Auditor, and Privacy Auditor into separate sessions when useful.
  7. Keep the human out of the execution loop except evidence double-checks and
     explicit conservative gates.
  8. Spend at least 20% of loop time on process improvement when repeated misses
     appear.

### Scope

- Add this queue entry and a self-contained plan doc.
- Link the principles from the operating-system, long-session, utilization, and
  Codex workflow docs.
- Keep the change as an operating-goal alignment PR.

### Non-Goals

- Do not change retrieval, reranking, answer, ingestion, or eval runtime behavior.
- Do not run private real-eval.
- Do not claim RAG quality, recall, latency, or production performance improved.
- Do not add new automation until a repeated omission proves it is needed.

### Acceptance Criteria

- [ ] The 8 principles are recorded as enforceable operating criteria, not a chat-only preference.
- [ ] RAG performance improvement is represented as a multi-session goal with
  role separation and reviewer escalation.
- [ ] The docs explicitly separate this governance change from any performance claim.
- [ ] Follow-up implementation work can start from `T-2026-0022` or later
  measurement tasks without rediscovering the operating model.

### Validation Commands

```bash
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0023-rag-performance-agent-operating-goal.md docs/operations/ai-engineering-operating-system.md docs/operations/long-session-workflow.md docs/operations/ai-codex-workflow.md docs/agent-utilization.md
git diff --check
make check-branch
```

### Evidence Required

- Targeted doc-link check passes.
- Branch/issue convention passes.
- PR body states: docs/governance only; no RAG runtime/eval behavior changed;
  no private real-eval run; no performance claim.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0023-rag-performance-agent-operating-goal.md`](../docs/plans/T-2026-0023-rag-performance-agent-operating-goal.md)
- Issue: [#1569](https://github.com/hskim-solv/BidMate-DocAgent/issues/1569)
- PR: TBD
