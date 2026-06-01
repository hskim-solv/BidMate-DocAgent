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
| 22 | `T-2026-0022` | `done` | Planner -> Implementer -> Reviewer | merged in PR #1576; retrieval change deferred until page-aware re-index evidence. |
| 23 | `T-2026-0023` | `done` | Planner -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Deep Reviewer -> Reviewer | merged in PR #1570. |
| 24 | `T-2026-0024` | `done` | Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | merged in PR #1577; page metadata recovery landed. |
| 25 | `T-2026-0025` | `done` | Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | merged in PR #1579; named MiniLM target landed. |
| 26 | `T-2026-0026` | `in_progress` | Planner -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | issue #1580; Chroma-backed `naive_baseline` canonical switch, separated from embedding-model baselines. |
| 27 | `T-2026-0027` | `review` | Planner -> Benchmark Auditor -> Privacy Auditor -> Reviewer | issue #1584; prioritized RAG performance experiment stack captured. |
| 28 | `T-2026-0028` | `done` | Evaluator -> Benchmark Auditor -> Privacy Auditor -> Reviewer | merged in PR #1619; real100_v2-only guard and aggregate packet landed. |
| 29 | `T-2026-0029` | `ready` | Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | reopened after naive baseline remeasurement: rerun retrieval diagnostics on the MiniLM page-aware v2 index before using prior conclusions. |
| 30 | `T-2026-0030` | `ready` | Implementer -> CI Reviewer -> Benchmark Auditor -> Reviewer | reopened after naive baseline remeasurement: rerender latency/cost envelope against the MiniLM page-aware v2 aggregate. |
| 31 | `T-2026-0031` | `ready` | Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | MiniLM page-aware checkpoint index now has non-zero page_span coverage; rerun only after refreshed baseline aggregate is available. |
| 32 | `T-2026-0032` | `ready` | Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | reopened after naive baseline remeasurement: rerun BGE-KO screening on the MiniLM page-aware v2 index before keeping no-winner status. |
| 33 | `T-2026-0033` | `ready` | Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | reopened after naive baseline remeasurement: rerun context-packing screening on the MiniLM page-aware v2 index before keeping latency_regression status. |
| 34 | `T-2026-0034` | `backlog` | Planner -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | P1; blocked on query-slice attribution from T-2026-0029. |
| 35 | `T-2026-0035` | `backlog` | Security Reviewer -> Implementer -> Privacy Auditor -> Reviewer | P1 guardrail; should run before agentic/tool-using retrieval. |
| 36 | `T-2026-0036` | `backlog` | Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | P2; blocked on stable retrieval/context evidence from P0/P1 tasks. |
| 37 | `T-2026-0037` | `backlog` | Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | P2; blocked on metadata coverage evidence from T-2026-0028. |
| 38 | `T-2026-0038` | `backlog` | Planner -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | P2; blocked on small-to-big retrieval evidence from T-2026-0031. |
| 39 | `T-2026-0039` | `backlog` | Planner -> Architect -> Benchmark Auditor -> Privacy Auditor -> Deep Reviewer -> Reviewer | P3; advanced architecture feasibility after P0/P1 evidence. |
| 40 | `T-2026-0040` | `done` | Implementer -> Reviewer | issue #1588 PR1 (#1589 merged); active-loop registry v2 + per-session Claude/Codex lanes scaffold. |
| 41 | `T-2026-0041` | `review` | Implementer -> Reviewer | issue #1590 PR2; read-only Claude/Codex lane adapters + WU accounting; in review. |
| 42 | `T-2026-0042` | `backlog` | Implementer -> Reviewer | issue #1588 PR3; patch-proposal + lease active_agent borrow + scratch worktree; re-confirm scope after Phase 1-2. |
| 43 | `T-2026-0043` | `backlog` | Implementer -> Reviewer | issue #1588 PR4; mutating-writer + claimed-files enforcement hook; blocked on T-2026-0042. |
| 44 | `T-2026-0044` | `backlog` | Implementer -> Deep Reviewer -> Reviewer | issue #1588 PR5; Orchestrator-only ship-executor + gate evidence (promote agent_loop.py to LOAD_BEARING); blocked on T-2026-0043. |
| 45 | `T-2026-0045` | `backlog` | Implementer -> Reviewer | issue #1588 PR6; full active-agent-loop.md ops-doc rewrite; blocked on T-2026-0044. |
| 46 | `T-2026-0046` | `review` | Planner -> Benchmark Auditor -> Privacy Auditor -> Reviewer | issue #1627; expands the RAG experiment task stack and inserts measurement-driven replanning gates. |
| 47 | `T-2026-0047` | `review` | Evaluator -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | issue #1645; hashing/page-0 real100_v2 index now fails v2 readiness, and affected optimization reports are invalidated until a MiniLM page-aware v2 rebuild. |
| 48 | `T-2026-0048` | `backlog` | Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | P0; candidate-depth and fusion-budget sweep for the `not_observable_limited_depth` retrieval failure bucket. |
| 49 | `T-2026-0049` | `backlog` | Planner -> Benchmark Auditor -> Privacy Auditor -> Reviewer | P0 replanning gate after T-2026-0030, T-2026-0032, T-2026-0047, and T-2026-0048 evidence. |
| 50 | `T-2026-0050` | `backlog` | Evaluator -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | P1; parser/layout/table coverage experiment for RFP evidence that is not text-searchable enough. |
| 51 | `T-2026-0051` | `backlog` | Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | P1; controlled embedding and representation sweep without mixing vector DB backend effects. |
| 52 | `T-2026-0052` | `backlog` | Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | P1; generator grounding, citation, prompt, and model-choice calibration after retrieval/context evidence stabilizes. |
| 53 | `T-2026-0053` | `backlog` | Planner -> Benchmark Auditor -> Privacy Auditor -> Reviewer | P1 replanning gate after context, query, metadata, parser, embedding, and generator experiments. |
| 54 | `T-2026-0054` | `backlog` | Implementer -> Architect -> Benchmark Auditor -> Privacy Auditor -> Deep Reviewer -> Reviewer | P2; end-to-end bakeoff of the best isolated experiment winners under one aggregate guardrail. |
| 55 | `T-2026-0055` | `backlog` | Benchmark Auditor -> Privacy Auditor -> Deep Reviewer -> Reviewer | P2; final optimization decision packet and default-change or no-go proposal. |
| 56 | `T-2026-0056` | `backlog` | Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | P1; Ollama local OpenAI-compatible provider spike for synthesis/judge cost, privacy, and latency evidence. |
| 57 | `T-2026-0057` | `review` | Planner -> Privacy Auditor -> Reviewer | issue #1651; real100_v2 portfolio wording cleanup and legacy current-claim wording removal. |
| 58 | `T-2026-0058` | `review` | Planner -> Reviewer | issue #1651; Multimodal Agent/Product positioning map added as a docs-only stack. |
| 59 | `T-2026-0059` | `backlog` | Planner -> Reviewer | External source and citation audit before framework/vendor claims enter portfolio wording. |
| 60 | `T-2026-0060` | `backlog` | Evaluator -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | Visual evidence contract hardening for OCR/layout/table/image citation readiness. |
| 61 | `T-2026-0061` | `backlog` | Implementer -> Privacy Auditor -> Reviewer | Opt-in VLM captioning spike on public fixtures only; no private egress by default. |
| 62 | `T-2026-0062` | `backlog` | Implementer -> Reviewer | Agent tool-state-trace contract for tool calls, state, retry/fallback, and permissions. |
| 63 | `T-2026-0063` | `backlog` | Security Reviewer -> Implementer -> Privacy Auditor -> Reviewer | Agent security and human-in-the-loop guardrail before tool-using multimodal workflows. |
| 64 | `T-2026-0064` | `backlog` | Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | Multimodal troubleshooting vertical slice after visual evidence and agent contracts. |
| 65 | `T-2026-0065` | `backlog` | Evaluator -> Benchmark Auditor -> Privacy Auditor -> Reviewer | Agent trajectory evaluation across tool calls, retries, fallbacks, latency, and cost. |
| 66 | `T-2026-0066` | `backlog` | Implementer -> Reviewer | Product API/demo integration for the chosen multimodal agent workflow. |
| 67 | `T-2026-0067` | `backlog` | Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer | Self-hosted OpenAI-compatible serving demo as auxiliary product/ops evidence. |
| 68 | `T-2026-0068` | `backlog` | Planner -> Architect -> Benchmark Auditor -> Privacy Auditor -> Deep Reviewer -> Reviewer | Knowledge/Graph RAG feasibility for relation-structured RFP evidence. |
| 69 | `T-2026-0069` | `backlog` | Planner -> Reviewer | Interview and resume evidence pack mapping repo artifacts to target roles. |
| 70 | `T-2026-0070` | `backlog` | Implementer -> Privacy Auditor -> Reviewer | Portfolio review board refresh after the new positioning artifacts settle. |
| 71 | `T-2026-0071` | `ready` | Implementer -> Reviewer | issue #1703; P2.0/P2.1 landed (#1698/#1700/#1702, ADR 0088/0090/0091) + operator branch-protection DONE (integration+main, `protection_verified` VERIFIED). 2026-06-01: AR1 dedup #1706 + verdict cache #1713 merged; cascade 8->3 WITHDRAWN + manifest seam + cap store all DEFERRED via codex self-catch (plan "P2.2 첫 시도 결과" + #1720). Follow-up 3건 마감(머지): escalation #1728->PR #1734 (ADR 0066 Proposed) + ADR-clarify #1727->PR #1735 + agent-isolation guards #1719->PR #1736 => **P2.2 single-writer lane 격리 전제조건 충족**. Remaining (전부 maintainer 결정/운영 대기): plan Open Questions 4건 + cap store 재설계 (ADR 0093+, 1-lane) + manifest seam (PR-4와 함께) + P2.2 live merge e2e (integration 레인 운영 시). Deep context: issue #1703 + plan #1708 ("P2.2 재개 준비 상태" 섹션) + `docs/operations/staging-self-ship.md`. |

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
- Status: done
- Owner role: Planner -> Implementer -> Reviewer

### Goal

Turn the aggregate multi-chunk evidence split into one scoped measurement
follow-up without mistaking a stale `real100/` aggregate for current
`real100_v2` retrieval evidence.

### Context

- Classification: `next_experiment_candidate`
- Source: `reports/real100/[redacted-private-artifact]`
- Source PRs: `PR corpus`
- Workset: `general`
- Lane: `parallel-safe`
- Role hints: `Planner, Implementer, Reviewer`
- Reason: multi-chunk aggregate is available: 97/99 top-10 failures; 97 limited-depth cases; source SHA-256 prefix `714c08f9996d` is the older `real100/` aggregate, not a fresh `real100_v2` multi-chunk measurement.
- Freshness check: `real100_v2` has 100 parsed Markdown exports and 94 converted PDFs in ignored private storage, but the current `real100_v2` index has 21,800 `pdf_pymupdf4llm` chunks with 0.0 chunk page metadata / `page_span` / `regions.page_number` coverage.
- Source brief: `reports/agent_loop/codex_tasks/001-multi-chunk-follow-up.md`
- Suggested plan path: `docs/plans/T-2026-0022-use-multi-chunk-evidence-analysis-for-the-next-retrieval-fol.md`

### Acceptance Criteria

- [x] Scope stays limited to the cited workflow surface.
- [x] Public-safe evidence or no-go rationale is captured without raw private data.
- [x] Reviewer prompt covers any eval, benchmark, privacy, or architecture surface touched.
- [x] Strategy report exposes source provenance so stale aggregate use is visible.

### Validation Commands

```bash
python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py tests/test_render_multi_chunk_retrieval_strategy.py
python3 scripts/render_multi_chunk_retrieval_strategy.py
export REAL_EVAL_ROOT=/path/to/private/BidMate-DocAgent
python3 scripts/page_metadata_recovery_audit.py --index-dir "$REAL_EVAL_ROOT/data/index/real100_v2" --format markdown
git diff --check
```

### Evidence Required

The follow-up chooses `defer_until_page_metadata_recovery` using aggregate counts
only. Pool/rerank, decomposition, and section expansion remain unsupported until
a page-aware `real100_v2` aggregate can distinguish same-document versus
multi-document evidence splits.

### Completion Proof

Focused validation passes and the follow-up evidence is recorded in
`docs/evaluation/multi_chunk_retrieval_strategy.md` plus
`reports/real100/multi_chunk_retrieval_strategy.aggregate.json`.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0022-use-multi-chunk-evidence-analysis-for-the-next-retrieval-fol.md`](../docs/plans/T-2026-0022-use-multi-chunk-evidence-analysis-for-the-next-retrieval-fol.md)
- Issue: [#1563](https://github.com/hskim-solv/BidMate-DocAgent/issues/1563)
- PR: [#1576](https://github.com/hskim-solv/BidMate-DocAgent/pull/1576)

### Session Handoff

- Role: Planner -> Implementer
- Lifecycle stage: review
- Branch / worktree: `eval/issue-1563-multi-chunk-followup-implementation` / Codex worktree
- Current status: merged in PR #1576; concrete retrieval change deferred until
  page-aware re-index evidence exists.
- Files touched: `.githooks/pre-commit`,
  `scripts/render_multi_chunk_retrieval_strategy.py`,
  `tests/test_render_multi_chunk_retrieval_strategy.py`,
  `docs/evaluation/multi_chunk_retrieval_strategy.md`,
  `reports/real100/multi_chunk_retrieval_strategy.aggregate.json`,
  `docs/plans/T-2026-0022-use-multi-chunk-evidence-analysis-for-the-next-retrieval-fol.md`,
  `tasks/queue.md`.
- Commands run: `python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py tests/test_render_multi_chunk_retrieval_strategy.py`; `python3 scripts/render_multi_chunk_retrieval_strategy.py`; `export REAL_EVAL_ROOT=/path/to/private/BidMate-DocAgent`; `python3 scripts/page_metadata_recovery_audit.py --index-dir "$REAL_EVAL_ROOT/data/index/real100_v2" --format markdown`; `python3 scripts/check_doc_links.py --check-all --paths docs/plans/T-2026-0022-use-multi-chunk-evidence-analysis-for-the-next-retrieval-fol.md docs/evaluation/multi_chunk_retrieval_strategy.md tasks/queue.md`; `bash -n .githooks/pre-commit`; `git diff --check`; `make check-branch`.
- Results: strategy recommendation is `defer_until_page_metadata_recovery`; `real100_v2` has 100 parsed Markdown exports, but current index page metadata coverage is 0.0.
- Validation evidence: focused tests, doc-link check, whitespace check, branch check, and page metadata recovery audit completed.
- Blockers: concrete retrieval implementation is blocked on page-aware re-index evidence, not on missing Markdown conversion.
- Open risks: MiniLM semantic baseline evidence is absent from this task; keep #1575 separate.
- Next action: start a separate page-aware retrieval follow-up after refreshed
  aggregate evidence exists.
- Next safe command: `git status --short`
- Reviewer focus: source freshness, privacy-safe aggregate-only wording, and no RAG performance claim.
- Eval surface: report/measurement decision only; no retrieval, reranker, verifier, prompt, answer, or eval runtime behavior change.

## T-2026-0023 — RAG performance agent operating goal

- ID: T-2026-0023
- Title: RAG performance agent operating goal
- Status: done
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

- [x] The 8 principles are recorded as enforceable operating criteria, not a chat-only preference.
- [x] RAG performance improvement is represented as a multi-session goal with
  role separation and reviewer escalation.
- [x] The docs explicitly separate this governance change from any performance claim.
- [x] Follow-up implementation work can start from `T-2026-0022` or later
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
- PR: [#1570](https://github.com/hskim-solv/BidMate-DocAgent/pull/1570)

## T-2026-0024 — Recover PyMuPDF4LLM page metadata at index build

- ID: T-2026-0024
- Title: Recover PyMuPDF4LLM page metadata at index build
- Status: done
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Fix the page metadata recovery blocker before multi-chunk retrieval changes:
PyMuPDF4LLM parser checkpoints already contain section-level `page_span`, but
the current fixed-chunk build drops page-span-only metadata before chunks reach
the index.

### Context

- Issue: #1573
- Related blocker: T-2026-0022 deferred retrieval changes until page-aware
  evidence exists.
- Discovery: `real100_v2` has 100 parsed Markdown exports, 94 converted PDFs,
  and 100 parse checkpoints. The checkpoints already contain page-aware
  `document.sections[].page_span`; `parsed_md` is text-only and not the recovery
  source.
- Current stale index symptom: `text_source=pdf_pymupdf4llm`, but chunk
  `page_span` / `regions.page_number` coverage is 0.0.

### Scope

- Preserve explicit section-level `page_span` when fixed chunking builds a
  document-wide parent section.
- Add an isolated `real-eval-page-aware` local target that reuses private
  converted PDFs and writes to separate local output paths.
- Keep canonical `make real-eval` default hashing/fixed behavior unchanged
  except for additive page metadata fields on chunks.
- Record aggregate-only validation evidence; do not commit raw private
  checkpoints, converted PDFs, indexes, reports, doc IDs, filenames, or paths.

### Non-Goals

- Do not change retrieval, reranking, prompt, verifier, answer, or eval scoring
  behavior.
- Do not claim RAG quality, recall, latency, or production performance improved.
- Do not switch the canonical baseline to MiniLM or BGE-M3; issue #1575 tracks
  embedding baseline separation.

### Acceptance Criteria

- [x] Fixed chunking preserves explicit parser-owned page spans from sections.
- [x] `scripts/smoke_real.sh` exposes `CHUNKING_STRATEGY` and optional
  `HWP_PDF_ARTIFACT_DIR` without changing defaults.
- [x] `make real-eval-page-aware` writes to isolated local paths and enables
  converted-PDF reuse.
- [x] Synthetic tests cover fixed page-span propagation and script wiring.
- [x] Local aggregate-only page metadata audit reports 1.0 page-span coverage on
  isolated section and fixed rebuilds.

### Validation Commands

```bash
bash -n scripts/smoke_real.sh
python3 -m pytest -q tests/test_smoke_real_script.py tests/test_page_aware_parser_contract.py tests/test_page_metadata_recovery_audit.py tests/test_build_private_real100_v2_parallel.py tests/test_hwp_pdf_pymupdf4llm_loader.py tests/test_export_private_index_markdown.py
python3 -m py_compile ingestion.py rag_metadata_processing.py rag_indexing.py scripts/build_private_real100_v2_parallel.py scripts/build_index.py
python3 scripts/page_metadata_recovery_audit.py --index-dir "$REAL_EVAL_ROOT/data/index/real100_pageaware" --format markdown
python3 scripts/page_metadata_recovery_audit.py --index-dir "$REAL_EVAL_ROOT/data/index/real100_fixed_pageaware" --format markdown
git diff --check
make check-branch
```

### Evidence Required

- Local page-aware rebuild uses cached private parse checkpoints, not raw
  reparse, unless checkpoint fingerprints miss.
- Audit output stays aggregate-only: document/chunk counts, source groups, and
  coverage rates only.

### Completion Proof

Focused tests and syntax checks pass; local audits report citation page claim
`GO` and chunk page-span coverage 1.0 for both isolated section
`real100_pageaware` and fixed `real100_fixed_pageaware` rebuilds.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0024-page-metadata-reindex.md`](../docs/plans/T-2026-0024-page-metadata-reindex.md)
- Issue: [#1573](https://github.com/hskim-solv/BidMate-DocAgent/issues/1573)
- PR: [#1577](https://github.com/hskim-solv/BidMate-DocAgent/pull/1577)

### Session Handoff

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: `fix/issue-1573-page-metadata-reindex` / Codex worktree
- Current status: merged in PR #1577.
- Files touched: `Makefile`, `scripts/smoke_real.sh`,
  `rag_metadata_processing.py`, `tests/test_page_aware_parser_contract.py`,
  `tests/test_smoke_real_script.py`, `docs/plans/T-2026-0024-page-metadata-reindex.md`,
  `tasks/queue.md`.
- Results: section page-aware local rebuild from checkpoints reports 100
  documents / 24,613 chunks / 1.0 chunk page-span coverage. Fixed rebuild
  reports 100 documents / 21,800 chunks / 1.0 chunk page-span coverage.
- Blockers: none known.
- Open risks: fixed chunking produces coarse document-range page spans; precise
  page citation quality still needs section/page-aware evaluation before
  performance claims.
- Next action: use page-aware aggregate evidence for follow-up retrieval
  diagnostics.
- Next safe command: `git status --short`
- Reviewer focus: no private path/raw text leakage, no performance claim, and
  explicit distinction between coarse fixed spans and section page spans.
- Eval surface: ingestion/index metadata propagation and private real-eval
  readiness; no retrieval ranking or answer behavior change intended.

## T-2026-0025 — Separate hashing, MiniLM, and BGE-M3 real-eval surfaces

- ID: T-2026-0025
- Title: Separate hashing, MiniLM, and BGE-M3 real-eval surfaces
- Status: done
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Remove the ambiguity where operators saw the MiniLM default model name but the
actual canonical private run used `EMBEDDING_BACKEND=hashing` and therefore
produced `local-hashing-bow` vectors.

### Context

- Issue: #1575
- `make real-eval` is deterministic/offline hashing and should be treated as a
  workflow-validation surface, not semantic retrieval evidence.
- `make real-eval-semantic` currently means BGE-M3 comparison.
- There was no named MiniLM private real-eval target even though
  `DEFAULT_EMBEDDING_MODEL` is MiniLM.

### Scope

- Add `make real-eval-minilm` as the named sentence-transformers MiniLM private
  baseline target.
- Keep `make real-eval` hashing/offline and `make real-eval-semantic` BGE-M3.
- Update private workflow/inventory docs so backend/model surfaces are explicit.
- Add focused tests for target wiring and comments.
- Preserve `embedding_backend`, `embedding_model_id`, and `embedding_dim` in
  aggregate `run_manifest` extraction so reviewers can see what actually ran.

### Non-Goals

- Do not run MiniLM or BGE-M3 private eval in this PR.
- Do not update committed baselines or performance numbers.
- Do not expose private paths or raw private artifacts in aggregate reports.
- Do not change retrieval, reranking, verifier, prompt, answer, or eval scoring.

### Acceptance Criteria

- [x] `make real-eval-minilm` writes to separate local paths:
  `data/index/real100_minilm`, `outputs/real100_minilm`,
  `reports/real100_minilm`.
- [x] Docs state that `make real-eval` is hashing/offline and not MiniLM.
- [x] Docs distinguish MiniLM baseline from BGE-M3 comparison.
- [x] Aggregate run-manifest extraction keeps embedding backend/model/dim while
  still dropping local config paths and redacting local model paths.
- [x] No performance claim is made from hashing runs.

### Validation Commands

```bash
bash -n scripts/smoke_real.sh
python3 -m pytest -q tests/test_smoke_real_script.py tests/test_provenance_banner.py
python3 -m pytest -q tests/test_run_real_eval_delta.py -k run_manifest
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0025-minilm-baseline-target.md docs/evaluation/private_real_eval_workflow.md docs/private-real-eval-inventory.md docs/evaluation/surface-map.md
git diff --check
make check-branch
```

### Evidence Required

- Focused tests pass.
- Docs and Makefile name actual backend/model surfaces.
- Aggregate reports retain embedding provenance without private path leakage.
- PR body says no private real-eval was run and no performance claim is made.

### Completion Proof

Focused tests and doc-link checks pass; `make real-eval-minilm` exists as the
named MiniLM sentence-transformers target, and aggregate `run_manifest`
extraction preserves embedding provenance without local model path leakage.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0025-minilm-baseline-target.md`](../docs/plans/T-2026-0025-minilm-baseline-target.md)
- Issue: [#1575](https://github.com/hskim-solv/BidMate-DocAgent/issues/1575)
- PR: [#1579](https://github.com/hskim-solv/BidMate-DocAgent/pull/1579)

### Session Handoff

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: `eval/issue-1575-minilm-baseline-target` / Codex worktree
- Current status: merged in PR #1579.
- Files touched: `Makefile`, `scripts/smoke_real.sh`,
  `scripts/run_real_eval_delta.py`,
  `docs/evaluation/private_real_eval_workflow.md`,
  `docs/evaluation/surface-map.md`, `docs/private-real-eval-inventory.md`,
  `tests/test_smoke_real_script.py`, `tests/test_run_real_eval_delta.py`,
  `docs/plans/T-2026-0025-minilm-baseline-target.md`, `tasks/queue.md`.
- Commands run: `bash -n scripts/smoke_real.sh`; `python3 -m pytest -q tests/test_smoke_real_script.py tests/test_provenance_banner.py`; `python3 -m pytest -q tests/test_run_real_eval_delta.py -k run_manifest`; `python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0025-minilm-baseline-target.md docs/evaluation/private_real_eval_workflow.md docs/private-real-eval-inventory.md docs/evaluation/surface-map.md`; `git diff --check`; `make check-branch`.
- Results: named MiniLM target added; docs now state `make real-eval` is
  hashing/offline and not MiniLM; aggregate run-manifest extraction preserves
  embedding provenance without private path leakage, including local model paths.
- Blockers: none known.
- Open risks: target existence does not prove MiniLM model cache/download or
  performance; actual MiniLM private eval remains a separate run.
- Next action: run the named MiniLM/BGE-M3 surfaces only in a separate
  aggregate-only eval task.
- Next safe command: `git status --short`
- Reviewer focus: baseline wording, no performance claim, and actual
  backend/model naming.
- Eval surface: workflow/docs only; no retrieval or eval runtime behavior change
  except new opt-in target.

## T-2026-0026 — Add Chroma vector-store baseline with parity guard

- ID: T-2026-0026
- Title: Add Chroma vector-store baseline with parity guard
- Status: in_progress
- Owner role: Planner -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-29

### Goal

Add Chroma as the canonical `naive_baseline` vector DB backend and include a
local-small LLM synthesis baseline in the same measurement task, without
mixing vector DB effects with embedding-model effects.

### Context

- Issue: #1580
- Current `BIDMATE_INDEX_BACKEND` support becomes `chroma`, `memory`, and
  `qdrant`.
- Chroma is the zero-env baseline backend. `memory` and `qdrant` are explicit
  control/ops backends.
- Chroma/memory/Qdrant are intended to be ranking bit-identical; vector DB
  comparison should mainly be latency/scale/ops unless measured ranking drift
  is explicitly documented.
- This is separate from MiniLM/BGE-M3 work: embedding backend/model and vector
  DB backend must remain independent provenance axes.

### Scope

- Add a `ChromaVectorStore` adapter behind `BIDMATE_INDEX_BACKEND=chroma`.
- Make `BIDMATE_INDEX_BACKEND=chroma` the default and add
  `vector_store_backend: chroma` to `naive_baseline`.
- Document Chroma install, connection, and persistence settings.
- Add memory-vs-Chroma ranking parity tests, including tie-break behavior.
- Add a reproducible Chroma baseline command or make target.
- Add a reproducible local loopback LLM synthesis baseline command or make
  target; the deterministic `stub` row remains a diagnostic control, not the
  headline answer-quality baseline.
- Record vector DB backend provenance separately from embedding provenance in
  eval/report artifacts.

### Non-Goals

- Do not refresh committed private real-eval aggregate baselines in this PR.
- Do not combine Chroma with MiniLM/BGE-M3 embedding changes in one PR.
- Do not claim quality improvement unless paired same-embedding same-corpus
  deltas prove it.

### Acceptance Criteria

- [x] `BIDMATE_INDEX_BACKEND=chroma` builds/loads through the existing
  `VectorStore` protocol.
- [x] `naive_baseline` resolves to `vector_store_backend: chroma`.
- [x] Memory and Chroma rankings are bit-identical in tests, or ranking drift is
  measured and documented as a backend effect.
- [x] Chroma eval path records vector DB backend provenance separately from
  embedding backend/model provenance.
- [x] Docs explain when Chroma is a latency/ops baseline versus a quality
  changing surface.
- [x] `make real-eval-v2-chroma` provides a reproducible Chroma private-v2
  command without refreshing committed baseline aggregates.
- [ ] `make real-eval-v2-chroma-llm` provides a reproducible LLM synthesis
  baseline using the same checkpoint MiniLM page-aware index, with loopback by
  default and explicit egress profile support for approved external API runs.

### Validation Commands

```bash
python3 -m pytest -q tests/test_vector_store_chroma.py tests/test_vector_store_protocol.py
python3 -m pytest -q tests/test_naive_baseline_ranking_invariance.py tests/test_api_default_pipeline_regression.py
python3 -m pytest -q tests/test_vector_store_qdrant.py tests/test_qdrant_integration.py -m "not qdrant_integration"
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0026-chroma-vector-baseline.md
git diff --check
make check-branch
REAL_EVAL_ROOT=<private-real-eval-root> make real-eval-v2-chroma
BIDMATE_SYNTHESIS_BASE_URL=http://127.0.0.1:11434/v1 BIDMATE_SYNTHESIS_API_KEY=ollama BIDMATE_SYNTHESIS_MODEL=<local-model> REAL_EVAL_ROOT=<private-real-eval-root> make real-eval-v2-chroma-llm
```

### Evidence Required

- Parity test output or explicit ranking-drift report.
- Backend provenance sample that separates `embedding_backend/model` from
  vector DB backend.
- Chroma private-v2 run command writes to `reports/real100_v2_chroma/` unless
  `REAL100_V2_CHROMA_REPORT_DIR` is overridden.
- LLM synthesis run writes to `reports/real100_v2_chroma_llm/` unless
  `REAL100_V2_CHROMA_LLM_REPORT_DIR` is overridden.
- `naive_stub_control` is reported as a retrieval/control floor; the LLM row is
  the answer-synthesis baseline candidate.
- No private raw artifact or exact local path in committed reports.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0026-chroma-vector-baseline.md`](../docs/plans/T-2026-0026-chroma-vector-baseline.md)
- Issue: [#1580](https://github.com/hskim-solv/BidMate-DocAgent/issues/1580)
- PR: TBD

### Session Handoff

- Role: Implementer
- Lifecycle stage: in_progress
- Branch / worktree: `feat/issue-1580-chroma-canonical-baseline` / Codex worktree
- Current status: implementation in progress for Chroma-backed `naive_baseline`.
- Files touched: implementation, tests, ADR/docs, queue.
- Commands run: `make -n real-eval-v2-chroma`; `python3 -m py_compile rag_vector_store.py rag_indexing.py rag_pipeline_presets.py rag_core.py eval/run_eval.py scripts/run_real_eval_delta.py scripts/compare_eval.py app.py api/main.py`; `python3 -m pytest -q tests/test_vector_store_chroma.py tests/test_vector_store_protocol.py tests/test_full_dense_control_row_regression.py tests/test_eval_metrics.py`; `python3 -m pytest -q tests/test_naive_baseline_ranking_invariance.py tests/test_api_default_pipeline_regression.py`; `python3 -m pytest -q tests/test_vector_store_qdrant.py tests/test_qdrant_integration.py -m "not qdrant_integration"`; `python3 -m pytest -q tests/test_run_real_eval_delta.py tests/test_compare_eval_regression_gate.py tests/test_run_manifest_versioning_regression.py tests/test_provenance_banner.py`; `python3 scripts/check_doc_links.py --check-all --paths docs/plans/T-2026-0026-chroma-vector-baseline.md tasks/queue.md docs/evaluation/surface-map.md docs/evaluation/private_real_eval_workflow.md docs/adr/README.md docs/adr/0081-chroma-backed-naive-baseline.md CLAUDE.md AGENTS.md`; `REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent make real-eval-v2-check`; `make real-eval-v2-guard`; `git diff --check`; `make check-branch`.
- Results: focused tests and docs/branch gates passed; private v2 path check and guard passed. Full `make real-eval-v2-chroma` was later completed against the checkpoint MiniLM page-aware index; the LLM synthesis baseline remains to run with a local loopback model.
- Blockers: local OpenAI-compatible model/server must be available for `make real-eval-v2-chroma-llm`.
- Open risks: dependency/install cost may affect CI or local developer setup.
- Next action: run `make real-eval-v2-chroma-llm` with a local loopback model,
  then render the baseline decision packet from aggregate-only evidence.
- Next safe command: `git status --short`
- Reviewer focus: backend axis separation, parity guard, no mixed embedding
  claim.

## T-2026-0027 — RAG performance experiment stack

- ID: T-2026-0027
- Title: RAG performance experiment stack
- Status: review
- Priority: P0 planning
- Owner role: Planner -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Convert the broad RAG performance checklist into a repo-native, prioritized
experiment stack that future sessions can execute one task and one PR at a
time.

### Context

- Issue: #1584
- Current branch: `docs/issue-1584-rag-performance-experiment-stack`
- Current main already has page metadata recovery and named MiniLM/BGE-M3
  private real-eval surfaces.
- Existing hybrid sweep evidence says recall-only gains are not enough when
  MRR, nDCG, citation, or latency regress.

### Scope

- Add a durable evaluation note that selects and defers RAG techniques.
- Add concrete queue tasks for P0/P1/P2/P3 experiment execution.
- Link the stack from the evaluation surface map.
- Keep existing runtime, eval, retrieval, reranking, and answer behavior
  unchanged.

### Non-Goals

- Do not implement retrieval, reranking, context packing, generator, security,
  or advanced architecture behavior in this PR.
- Do not run private real-eval.
- Do not claim RAG quality, latency, citation, or production performance
  improved.
- Do not create all future GitHub issues before each task starts.

### Acceptance Criteria

- [x] Experiment tasks are ordered by priority and dependency.
- [x] Each task states surface, validation, evidence, and no-claim boundary.
- [x] Advanced techniques are explicitly deferred behind feasibility gates.
- [x] The stack starts with private coverage and baseline refresh rather than
  speculative architecture work.

### Validation Commands

```bash
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0027-rag-performance-experiment-stack.md docs/evaluation/rag-performance-experiment-stack.md docs/evaluation/surface-map.md
git diff --check
make check-branch
```

### Evidence Required

- Doc-link check, whitespace check, and branch/issue check pass.
- PR body says docs/planning only, no private real-eval run, and no performance
  claim.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0027-rag-performance-experiment-stack.md`](../docs/plans/T-2026-0027-rag-performance-experiment-stack.md)
- Evaluation note: [`docs/evaluation/rag-performance-experiment-stack.md`](../docs/evaluation/rag-performance-experiment-stack.md)
- Issue: [#1584](https://github.com/hskim-solv/BidMate-DocAgent/issues/1584)
- PR: [#1587](https://github.com/hskim-solv/BidMate-DocAgent/pull/1587)

### Session Handoff

- Role: Planner
- Lifecycle stage: review
- Branch / worktree: `docs/issue-1584-rag-performance-experiment-stack` / Codex worktree
- Current status: task stack implemented and validation passed.
- Files touched: `tasks/queue.md`,
  `docs/plans/T-2026-0027-rag-performance-experiment-stack.md`,
  `docs/evaluation/rag-performance-experiment-stack.md`,
  `docs/evaluation/surface-map.md`.
- Decisions made: prioritize measurement readiness, retrieval diagnostics,
  latency/cost guardrails, and small-to-big retrieval before GraphRAG/Agentic
  RAG.
- Commands run: `python3 scripts/agent_loop.py overlap-preflight --issue 1584 --branch docs/issue-1584-rag-performance-experiment-stack`; `python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0027-rag-performance-experiment-stack.md docs/evaluation/rag-performance-experiment-stack.md docs/evaluation/surface-map.md`; `git diff --check`; `make check-branch`.
- Results: passed.
- Next safe command: `git diff --stat`
- Reviewer focus: priority order, no-claim wording, and private boundary.

## T-2026-0028 — Refresh private coverage and semantic baselines

- ID: T-2026-0028
- Title: Refresh private coverage and semantic baselines
- Status: review
- Priority: P0
- Owner role: Evaluator -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-28

### Goal

Create the first current aggregate-only `real100_v2` baseline packet after page
metadata recovery and MiniLM target separation, so later experiments compare
against the right corpus, index, backend, and metric surface.

### Scope

- Run or document the local-only `real100_v2` sequence: v2 inventory/check,
  v2-only guard, parse/data audit, and aggregate packet review.
- Preserve aggregate-only outputs that summarize case counts, evidence coverage,
  page metadata coverage, retrieval metrics, answer metrics, abstention, stage
  latency, embedding backend/model/dim, and vector DB backend.
- Produce a no-go/go note naming which P0/P1 task should run next.

### Non-Goals

- Do not change ingestion, retrieval, reranking, answer, prompt, verifier, or
  eval scoring behavior.
- Do not commit raw private outputs.
- Do not claim performance improvement from a single run without paired delta.
- Do not use stale `real100`/221 aggregate evidence, `data/index/real100`,
  `reports/real100`, `outputs/real100`, or default `make real-eval` for this
  task.

### Acceptance Criteria

- [x] Aggregate packet reports answerable/unanswerable counts, explicit gold
  evidence coverage, multi-document/multi-chunk counts, page/page_span coverage,
  and embedding/backend provenance.
- [x] Hashing, MiniLM, and BGE-M3 surfaces are not compared unless dataset,
  config, index, command, and provenance match the claim wording.
- [x] `make real-eval-v2-guard` passes and blocks stale `real100`/221 evidence
  from the task scope.
- [x] Any committed artifact passes privacy checks and omits raw questions,
  answers, evidence, filenames, local paths, `doc_id`, and `chunk_id`.
- [x] The handoff names the next task: `T-2026-0029`, `T-2026-0030`, or a no-go
  blocker.

### Validation Commands

```bash
REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent make real-eval-v2-inventory
REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent make real-eval-v2-check
make real-eval-v2-guard
python3 scripts/audit_private_data_readiness.py --config /Users/hskim/Desktop/projects/BidMate-DocAgent/data/private/real100_v2/real_config_v2.local.yaml --out-dir experiments/private_runs/readiness_audit
python3 scripts/run_real_eval_delta.py --base <aggregate-baseline> --head <aggregate-head>
git diff --check
make check-branch
```

### Evidence Required

- Aggregate-only baseline packet and command transcript summary.
- Explicit statement whether real private eval ran and whether any paired delta
  is valid.
- Privacy audit result for any committed aggregate.
- V2-only guard result proving legacy `real100`/221 evidence is not used.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0028-refresh-private-coverage-semantic-baselines.md`](../docs/plans/T-2026-0028-refresh-private-coverage-semantic-baselines.md)
- Issue: [#1618](https://github.com/hskim-solv/BidMate-DocAgent/issues/1618)
- PR: [#1619](https://github.com/hskim-solv/BidMate-DocAgent/pull/1619)

### Handoff Notes

```markdown
## Session Handoff - 2026-05-28 KST

- Role: Evaluator
- Lifecycle stage: review
- Branch / worktree: eval/issue-1618-refresh-private-coverage-and-semantic-baselines / /Users/hskim/.codex/worktrees/0ebc/BidMate-DocAgent
- Issue / PR: #1618 / N/A
- Task: T-2026-0028
- Current status: real100_v2-only private eval policy enforced; aggregate packet ready for review.
- Files touched: Makefile, CLAUDE.md, scripts/check_real100_v2_only.py, tests/test_real100_v2_guard.py, tests/test_smoke_real_script.py, docs/evaluation/private_real_eval_workflow.md, docs/evaluation/surface-map.md, docs/evaluation/real100_v2-baseline-refresh.md, docs/plans/T-2026-0028-refresh-private-coverage-semantic-baselines.md, tasks/queue.md
- Decisions made: legacy real100/v1/221/kordoc evidence is banned for future tasks until explicit maintainer re-enable; T-2026-0029 can proceed only as diagnostic work unless v2 page metadata is repaired or explicitly scoped out.
- Commands run: make ship-start TITLE="Refresh private coverage and semantic baselines" TYPE=eval; make check-branch; make agent-loop-active-start ISSUE=1618 ACTIVE_START_RUNNER=0; REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent make real-eval-v2-check; make real-eval-v2-guard; make real-eval
- Results: branch/issue setup passed; v2 path check passed; v2 guard passed; default legacy make real-eval intentionally fails closed.
- Merge result: PR #1619 merged; issue #1618 closed.
- Validation evidence: real-eval-v2-check found v2 config/data/docs/index/report/eval summary/baseline present; v2 guard passed; legacy real-eval/minilm/semantic targets fail closed; privacy and claim audits passed.
- Blockers: claim-bearing page/citation work remains blocked by real100_v2 page metadata ready rate 0.0.
- Next safe command: python3 -m pytest tests/test_real100_v2_guard.py tests/test_smoke_real_script.py -q
- Next action: benchmark/privacy reviewer should verify v2-only policy and decide whether T-2026-0029 is diagnostic-only or a v2 page-metadata repair task is needed first.
- Open risks: historical real100 artifacts still exist as archive-only files; future agents must not use them for new work.
- Reviewer focus: v2-only policy, no stale real100/221 evidence, aggregate-only privacy boundary, no performance-improvement claim.
- Eval surface: private real-eval aggregate-only, real100_v2 only.
```

## T-2026-0029 — Build retrieval diagnostic workbench

- ID: T-2026-0029
- Title: Build retrieval diagnostic workbench
- Status: ready
- Priority: P0
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-29

### Goal

Make `real100_v2` retrieval failures explainable before changing retrieval
behavior. This is diagnostic-only until the v2 page metadata blocker is repaired
or explicitly scoped out.

### Scope

- Add or harden an aggregate-only diagnostic that reports Recall@K, Hit@K, MRR,
  nDCG, candidate-pool coverage, same-document versus multi-document evidence
  split, rank-too-low cases, not-in-pool cases, duplicate/near-duplicate
  candidate counts, and query-type slices.
- Separate retrieval misses from evaluation-label gaps and answer-generation
  failures.
- Use only `real100_v2` aggregate/index evidence. Legacy `real100`/v1/221/kordoc
  evidence remains banned.
- Preserve the known `real100_v2` page metadata ready-rate 0.0 blocker instead
  of filling it with old evidence.

### Non-Goals

- Do not change ranking behavior.
- Do not add reranking, query rewrite, or context packing.
- Do not expose private case text or raw identifiers.
- Do not use legacy `real100`/v1/221/kordoc aggregate evidence.
- Do not claim page/citation readiness while v2 page metadata coverage is 0.0.

### Acceptance Criteria

- [x] Diagnostics distinguish not-in-candidate-pool, ranked-too-low,
  boundary/window, duplicate, metadata-filter, and multi-evidence failures.
- [x] Output is aggregate-only and commit-safe.
- [x] The report can decide whether `T-2026-0031` or `T-2026-0032` is the next
  best experiment.
- [x] The report explicitly carries forward the v2 page metadata blocker and
  does not use old `real100` evidence as a substitute.

### Validation Commands

```bash
python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py tests/test_render_multi_chunk_retrieval_strategy.py
make real-eval-v2-guard
REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent python3 scripts/render_real100_v2_retrieval_diagnostics.py
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0029-real100-v2-retrieval-diagnostic-workbench.md docs/evaluation/real100_v2-retrieval-diagnostics.md reports/real100_v2/README.md
git diff --check
make check-branch
```

### Evidence Required

- Aggregate diagnostic report with no raw private text, IDs, filenames, or
  paths.
- Reviewer note explaining which failure bucket is dominant.
- Explicit statement that `real100_v2` page metadata coverage is a blocker for
  claim-bearing page/citation work.
- Reopened follow-up: the 2026-05-28 diagnostic conclusions are invalid for new
  optimization decisions until rerun against the MiniLM page-aware v2 index.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0029-real100-v2-retrieval-diagnostic-workbench.md`](../docs/plans/T-2026-0029-real100-v2-retrieval-diagnostic-workbench.md)
- Issue: [#1622](https://github.com/hskim-solv/BidMate-DocAgent/issues/1622)
- PR: TBD

### Handoff Notes

```markdown
## Session Handoff - 2026-05-28 09:35 KST

- Role: Implementer
- Branch / worktree: eval/issue-1622-build-real100-v2-retrieval-diagnostic-workbench / /Users/hskim/.codex/worktrees/0ebc/BidMate-DocAgent
- Issue / PR: issue #1622 / PR TBD
- Task: T-2026-0029
- Current status: real100_v2 retrieval diagnostics rendered and ready for benchmark/privacy review.
- Files touched: .gitignore, .githooks/pre-commit, scripts/render_real100_v2_retrieval_diagnostics.py, scripts/check_real100_v2_only.py, tests/test_render_real100_v2_retrieval_diagnostics.py, docs/evaluation/real100_v2-retrieval-diagnostics.md, reports/real100_v2/retrieval_diagnostics.aggregate.json, reports/real100_v2/README.md, docs/plans/T-2026-0029-real100-v2-retrieval-diagnostic-workbench.md, tasks/queue.md
- Decisions made: dominant exclusive retrieval status is not_observable_limited_depth; T-2026-0031 remains blocked by real100_v2 page metadata coverage 0.0; next experiment candidate is T-2026-0032.
- Commands run: REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent python3 scripts/render_real100_v2_retrieval_diagnostics.py; python3 -m pytest -q tests/test_render_real100_v2_retrieval_diagnostics.py.
- Results: aggregate JSON and Markdown report generated; focused renderer tests passed.
- Next safe command: python3 -m py_compile scripts/render_real100_v2_retrieval_diagnostics.py scripts/check_real100_v2_only.py && python3 -m pytest -q tests/test_render_real100_v2_retrieval_diagnostics.py tests/test_real100_v2_guard.py tests/test_render_multi_chunk_evidence_failures.py tests/test_render_multi_chunk_retrieval_strategy.py && bash -n .githooks/pre-commit
- Open questions: none.
- Risks: duplicate/near-duplicate signal counts repeated top documents as aggregate near-duplicates, not semantic duplicates.
```

## T-2026-0030 — Define latency and cost budget envelope

- ID: T-2026-0030
- Title: Define latency and cost budget envelope
- Status: ready
- Priority: P0
- Owner role: Implementer -> CI Reviewer -> Benchmark Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-29

### Goal

Set the latency/cost guardrails that every multi-query, reranker, compression,
or long-context experiment must satisfy.

Current trigger: `T-2026-0032` is planned but blocked until this envelope exists.
Use `real100_v2` aggregate latency/stage evidence only; do not use
legacy `real100`/v1/221/kordoc evidence.

### Scope

- Use existing `stage_latency`, p50/p95/p99, token counts, reranker candidate
  counts, context token counts, and cache indicators where available.
- Add a report or gate that classifies quality-only gains as no-go when latency
  or cost exceeds the agreed envelope.
- Keep the report aggregate-only and hardware-caveated.

### Non-Goals

- Do not optimize latency yet.
- Do not introduce caching behavior.
- Do not infer production SLOs from public fixture smoke.

### Acceptance Criteria

- [x] Budget report names p50/p95/p99 and stage-level components.
- [x] Candidate-pool, reranker, query-rewrite, and context-packing tasks can cite
  the same latency/cost envelope.
- [x] The report states warm/cold and local hardware caveats.

### Validation Commands

```bash
python3 scripts/render_real100_v2_latency_budget.py
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0030-real100-v2-latency-cost-budget-envelope.md docs/evaluation/real100_v2-latency-cost-budget.md reports/real100_v2/README.md
git diff --check
make check-branch
```

### Evidence Required

- Aggregate latency/cost budget report.
- Explicit guardrail thresholds or no-go classification rules.
- Reopened follow-up: the 2026-05-28 envelope must be rerendered from the
  MiniLM page-aware v2 aggregate before downstream experiment no-go decisions
  cite it.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0030-real100-v2-latency-cost-budget-envelope.md`](../docs/plans/T-2026-0030-real100-v2-latency-cost-budget-envelope.md)
- Issue: [#1626](https://github.com/hskim-solv/BidMate-DocAgent/issues/1626)
- PR: TBD

### Handoff Notes

```markdown
## Session Handoff - 2026-05-28 10:15 KST

- Role: Implementer
- Branch / worktree: eval/issue-1626-define-real100-v2-latency-and-cost-budget-envelo / /Users/hskim/.codex/worktrees/0ebc/BidMate-DocAgent
- Issue / PR: issue #1626 / PR TBD
- Task: T-2026-0030
- Current status: real100_v2 latency/cost budget envelope rendered and ready for review.
- Files touched: .gitignore, .githooks/pre-commit, scripts/render_real100_v2_latency_budget.py, scripts/check_real100_v2_only.py, tests/test_render_real100_v2_latency_budget.py, docs/evaluation/real100_v2-latency-cost-budget.md, reports/real100_v2/latency_cost_budget.aggregate.json, reports/real100_v2/README.md, docs/plans/T-2026-0030-real100-v2-latency-cost-budget-envelope.md, tasks/queue.md
- Decisions made: p99 and cost are named but not observable in committed aggregate; quality-only gains are no-go without latency/cost evidence.
- Commands run: python3 scripts/render_real100_v2_latency_budget.py; python3 -m pytest -q tests/test_render_real100_v2_latency_budget.py.
- Results: aggregate JSON and Markdown report generated; focused renderer tests passed.
- Next safe command: python3 -m py_compile scripts/render_real100_v2_latency_budget.py scripts/check_real100_v2_only.py && python3 -m pytest -q tests/test_render_real100_v2_latency_budget.py tests/test_real100_v2_guard.py
- Open questions: none.
- Risks: cost and p99 require fresh aggregate fields before they can be enforced quantitatively.
```

## T-2026-0031 — Parent and section-window retrieval experiment

- ID: T-2026-0031
- Title: Parent and section-window retrieval experiment
- Status: ready
- Priority: P1
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-29

### Goal

Test whether small-to-big retrieval improves multi-chunk and same-document
evidence failures now that page-aware metadata exists.

Current gate: the MiniLM page-aware checkpoint index has non-zero chunk
`page_span` coverage, so page/window work may proceed after the refreshed
`real100_v2` baseline aggregate is generated from that index.

### Scope

- Add an opt-in experiment preset that retrieves small chunks but expands
  selected hits to parent section, page window, or sentence window context.
- Deduplicate parent expansions and cap token/context growth.
- Compare against the refreshed private baseline with paired aggregate delta.

### Non-Goals

- Do not change default `naive_baseline`.
- Do not combine with reranker or query rewrite changes.
- Do not claim improvement unless private paired delta shows primary metric
  movement without guardrail regressions.

### Acceptance Criteria

- [x] real100_v2 page metadata blocker is cleared or this task is explicitly
  rescoped before implementation.
- [ ] Opt-in preset leaves ADR 0001 baseline byte-identical.
- [ ] Aggregate delta reports Recall@K, MRR, nDCG, citation/page coverage,
  answer quality, abstention, and latency.
- [ ] Same-document multi-chunk cases are reported separately from
  multi-document cases.

### Validation Commands

```bash
python3 -m pytest -q tests/test_naive_baseline_ranking_invariance.py <focused-new-tests>
python3 <experiment-runner> --variant parent_section_window --summary-out <aggregate-output>
python3 scripts/run_real_eval_delta.py --base <baseline-aggregate> --head <variant-aggregate>
git diff --check
make check-branch
```

### Evidence Required

- Paired private aggregate delta or explicit no-go.
- Token/latency guardrail result.
- Fresh MiniLM page-aware `real100_v2` baseline aggregate before any
  parent/window winner or no-go claim.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0031-parent-section-window-retrieval-experiment.md`](../docs/plans/T-2026-0031-parent-section-window-retrieval-experiment.md)
- Issue: [#1667](https://github.com/hskim-solv/BidMate-DocAgent/issues/1667)
- PR: TBD

## T-2026-0032 — Reranker candidate-budget experiment

- ID: T-2026-0032
- Title: Reranker candidate-budget experiment
- Status: ready
- Priority: P1
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-29

### Goal

Measure whether reranking improves early precision without hiding candidate-pool
recall or causing unacceptable latency.

Current trigger: `T-2026-0029` real100_v2 diagnostics selected this as the next
experiment candidate because T-2026-0031 remains blocked by page metadata 0.0.
Run with or after the latency/cost guardrail from `T-2026-0030`.

### Scope

- Sweep retriever candidate counts and reranker top-N limits.
- Keep reranker model/provider provenance explicit.
- Report rank movement, answer containment, citation effect, and stage latency.

### Non-Goals

- Do not increase candidate pools blindly.
- Do not use LLM reranking until cross-encoder budget is measured.
- Do not mix reranking with query rewrite, parent expansion, or prompt changes.

### Acceptance Criteria

- [x] Sweep output classifies winner, recall-only gain, ranking regression,
  citation regression, latency regression, or failed experiment.
- [x] Candidate-pool recall and reranker precision are reported separately.
- [x] Reranker provenance is present in aggregate output.
- [x] Latency/cost guardrail from `T-2026-0030` is present or this task remains
  blocked.

### Validation Commands

```bash
python3 -m pytest -q tests/test_reranker*.py <focused-new-tests>
python3 scripts/run_real100_v2_reranker_budget_sweep.py --config <local-v2-config> --index-dir <local-v2-index> --cases-subset-n 3 --candidate-pools 30 --reranker-top-ns 10 --reranker-backend bge_ko
python3 scripts/run_real_eval_delta.py --base <baseline-aggregate> --head <variant-aggregate>  # optional only when paired full aggregate exists
git diff --check
make check-branch
```

### Evidence Required

- Aggregate sweep summary with no raw private content.
- Latency/cost guardrail from `T-2026-0030`.
- Current committed result: `reports/real100_v2/reranker_candidate_budget.aggregate.json`
  classifies the BGE-KO screening variant as `latency_regression` with
  `paired_delta_valid=false`; this is a no-winner screening result, not a
  private eval improvement claim.
- Reopened follow-up: rerun the screening on the MiniLM page-aware v2 index;
  the prior hashing/page-0 baseline cannot support the retained no-winner
  conclusion.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0032-reranker-candidate-budget-experiment.md`](../docs/plans/T-2026-0032-reranker-candidate-budget-experiment.md)
- Issue: [#1624](https://github.com/hskim-solv/BidMate-DocAgent/issues/1624) (plan), [#1629](https://github.com/hskim-solv/BidMate-DocAgent/issues/1629) (implementation)
- PR: TBD

### Handoff Notes

```markdown
## Session Handoff - 2026-05-28 12:30 KST

- Role: Implementer
- Branch / worktree: eval/issue-1629-run-real100-v2-reranker-candidate-budget-experim / /Users/hskim/.codex/worktrees/0ebc/BidMate-DocAgent
- Issue / PR: issue #1629 / PR TBD
- Task: T-2026-0032
- Current status: runner/report implemented; 3-case `real100_v2` BGE-KO screening classifies `latency_regression`.
- Files touched: scripts/run_real100_v2_reranker_budget_sweep.py, tests/test_real100_v2_reranker_budget_sweep.py, reports/real100_v2/reranker_candidate_budget.aggregate.json, docs/evaluation/real100_v2-reranker-candidate-budget.md, reports/real100_v2/README.md, .gitignore, .githooks/pre-commit, scripts/check_real100_v2_only.py, docs/plans/T-2026-0032-reranker-candidate-budget-experiment.md, tasks/queue.md
- Decisions made: no winner and no headline improvement claim; paired_delta_valid=false because this was a 3-case screening run; local BGE-KO reranker latency exceeds the 4799 ms hard no-go ceiling by a large margin.
- Commands run: make ship-start TITLE="Run real100 v2 reranker candidate budget experiment" TYPE=eval; make check-branch; python3 -m py_compile scripts/run_real100_v2_reranker_budget_sweep.py; python3 -m pytest -q tests/test_real100_v2_reranker_budget_sweep.py; python3 scripts/run_real100_v2_reranker_budget_sweep.py --config <external_private_real100_v2_config> --index-dir <external_private_real100_v2_index> --cases-subset-n 3 --candidate-pools 30 --reranker-top-ns 10 --reranker-backend bge_ko.
- Results: aggregate/report written; candidate-pool recall and reranker precision separated; reranker provenance captured as backend bge_ko and model safe label dragonkue__bge-reranker-v2-m3-ko.
- Next safe command: make real-eval-v2-guard && python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0032-reranker-candidate-budget-experiment.md docs/evaluation/real100_v2-reranker-candidate-budget.md reports/real100_v2/README.md
- Open questions: whether to run any further reranker backend requires a GPU or explicit latency budget exception; current CPU local backend is no-go.
- Risks: subset run is screening evidence only, not paired full private eval delta.
```

```markdown
## Session Handoff - 2026-05-28 09:55 KST

- Role: Planner
- Branch / worktree: eval/issue-1624-plan-reranker-candidate-budget-experiment / /Users/hskim/.codex/worktrees/0ebc/BidMate-DocAgent
- Issue / PR: issue #1624 / PR TBD
- Task: T-2026-0032
- Current status: plan drafted; implementation blocked on T-2026-0030 latency/cost guardrail.
- Files touched: docs/plans/T-2026-0032-reranker-candidate-budget-experiment.md, tasks/queue.md
- Decisions made: no reranker candidate-budget claim without paired real100_v2 delta and latency/cost envelope.
- Commands run: make ship-start TITLE="Plan reranker candidate budget experiment" TYPE=eval; make check-branch; python3 scripts/agent_loop.py next.
- Results: issue #1624 and branch created; branch gate passed; T-2026-0032 plan drafted.
- Next safe command: python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0032-reranker-candidate-budget-experiment.md
- Open questions: none.
- Risks: implementing the sweep before a latency/cost envelope would produce unusable review evidence.
```

## T-2026-0033 — Context packing and citation ordering experiment

- ID: T-2026-0033
- Title: Context packing and citation ordering experiment
- Status: ready
- Priority: P1
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-29

### Goal

Improve how selected evidence is assembled for generation without changing the
retriever.

Current trigger: `T-2026-0032` produced a no-winner reranker screening result
because local BGE-KO reranking breached the `T-2026-0030` latency hard ceiling.
The next experiment should improve evidence assembly while holding retrieval and
reranker behavior fixed.

### Scope

- Test evidence-first ordering, duplicate suppression, conflicting evidence
  grouping, page/section citation formatting, and lost-in-the-middle mitigation.
- Measure token count, citation grounding, completeness, abstention, and
  latency.
- Preserve ADR 0003 answer contract unless an ADR explicitly changes it.

### Non-Goals

- Do not change retrieval ranking or reranker behavior.
- Do not summarize private context into committed artifacts.
- Do not increase context length without a token/latency budget.

### Acceptance Criteria

- [x] Context assembly variant is opt-in and separately named.
- [x] Retrieval and reranker behavior are explicitly unchanged in the aggregate.
- [x] Citation and answer metrics are evaluated together; citation regression is no-go.
- [x] Token/cost status is reported as present, absent, or not applicable.
- [ ] Conflict grouping is visible to the generator without raw conflict text in
  committed reports.

### Validation Commands

```bash
python3 -m pytest -q tests/test_real100_v2_context_packing_experiment.py
python3 scripts/run_real100_v2_context_packing_experiment.py --config <local-v2-config> --index-dir <local-v2-index> --cases-subset-n 3 --variant evidence_first
make real-eval-v2-guard
python3 scripts/agent_loop.py privacy-audit-output
python3 scripts/agent_loop.py claim-audit --from-git
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0033-context-packing-citation-ordering-experiment.md docs/evaluation/real100_v2-context-packing.md reports/real100_v2/README.md
git diff --check
make check-branch
```

### Evidence Required

- Screening aggregate for citation, answer, abstention, token, and latency
  metrics; paired_delta_valid is false until a full comparable run exists.
- Explicit no-change statement for retrieval behavior.
- Aggregate-only privacy boundary, no raw private content.
- Reopened follow-up: rerun the screening on the MiniLM page-aware v2 index;
  the prior hashing/page-0 baseline cannot support the retained
  `latency_regression` conclusion.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0033-context-packing-citation-ordering-experiment.md`](../docs/plans/T-2026-0033-context-packing-citation-ordering-experiment.md)
- Issue: plan [#1638](https://github.com/hskim-solv/BidMate-DocAgent/issues/1638), implementation [#1641](https://github.com/hskim-solv/BidMate-DocAgent/issues/1641)
- PR: TBD

### Handoff Notes

```markdown
## Session Handoff - 2026-05-28 13:45 KST

- Role: Implementer
- Branch / worktree: eval/issue-1641-run-real100-v2-context-packing-citation-ordering / /Users/hskim/.codex/worktrees/0ebc/BidMate-DocAgent
- Issue / PR: plan issue #1638, implementation issue #1641 / PR TBD
- Task: T-2026-0033
- Current status: opt-in context-packing runner/report implemented; 3-case real100_v2 screening classifies evidence_first as latency_regression.
- Files touched: scripts/run_real100_v2_context_packing_experiment.py, tests/test_real100_v2_context_packing_experiment.py, reports/real100_v2/context_packing.aggregate.json, docs/evaluation/real100_v2-context-packing.md, reports/real100_v2/README.md, .gitignore, .githooks/pre-commit, scripts/check_real100_v2_only.py, docs/plans/T-2026-0033-context-packing-citation-ordering-experiment.md, tasks/queue.md
- Decisions made: do not promote evidence_first context packing; paired_delta_valid=false and both observed p95 values breach the T-2026-0030 hard ceiling.
- Commands run: make ship-start TITLE="Run real100 v2 context packing citation ordering experiment" TYPE=eval; make check-branch; python3 -m py_compile scripts/run_real100_v2_context_packing_experiment.py; python3 -m pytest -q tests/test_real100_v2_context_packing_experiment.py; python3 scripts/run_real100_v2_context_packing_experiment.py --config <external_private_real100_v2_config> --index-dir <external_private_real100_v2_index> --cases-subset-n 3 --variant evidence_first.
- Results: control p95 46589.662 ms; evidence_first p95 12946.188 ms; response/citation metrics did not improve; overall classification latency_regression because the variant still breaches the hard ceiling.
- Next safe command: make real-eval-v2-guard && python3 scripts/agent_loop.py privacy-audit-output && python3 scripts/agent_loop.py claim-audit --from-git
- Open questions: none.
- Risks: no full paired delta; this artifact is screening evidence only and not a headline improvement claim.
```

## T-2026-0034 — Query rewrite and decomposition experiment

- ID: T-2026-0034
- Title: Query rewrite and decomposition experiment
- Status: backlog
- Priority: P1
- Owner role: Planner -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Test query rewrite, multi-query, and decomposition only on slices where query
form is the measured bottleneck.

### Scope

- Target comparison, multi-hop, abbreviation, typo, mixed Korean/English, and
  date/entity questions.
- Keep rewrite outputs local-only for private cases.
- Measure extra LLM/API calls, latency, rewrite drift, retrieval delta, and
  answer delta.

### Non-Goals

- Do not turn on rewrite globally.
- Do not send private queries to external providers without an approved online
  payload boundary.
- Do not combine with reranker or context-packing changes in the same PR.

### Acceptance Criteria

- [ ] Query-slice report justifies which slices receive rewrite/decomposition.
- [ ] Identity expansion remains the default for `naive_baseline`.
- [ ] Multi-query is no-go if recall gains are erased by reranking budget,
  context truncation, latency, or answer regressions.

### Validation Commands

```bash
python3 -m pytest -q tests/test_query_expansion*.py tests/test_naive_baseline_ranking_invariance.py <focused-new-tests>
python3 <query-experiment-runner> --variant rewrite_or_decompose --summary-out <aggregate-output>
python3 scripts/run_real_eval_delta.py --base <baseline-aggregate> --head <variant-aggregate>
git diff --check
make check-branch
```

### Evidence Required

- Aggregate slice deltas and provider/payload provenance.
- Explicit private egress statement.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: TBD
- PR: TBD

## T-2026-0035 — Prompt-injection and data boundary guardrail

- ID: T-2026-0035
- Title: Prompt-injection and data boundary guardrail
- Status: backlog
- Priority: P1 guardrail
- Owner role: Security Reviewer -> Implementer -> Privacy Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Ensure retrieved text is treated as data, not instructions, before adding more
agentic retrieval, tool routing, or external provider workflows.

### Scope

- Add or extend red-team fixtures for indirect prompt injection, instruction
  override strings, secret/PII leakage attempts, and citation-only answer
  constraints.
- Verify retrieval context isolation, verifier neutralization, and tool-call
  policy boundaries.
- Record false positive/false negative counts without private raw payloads.

### Non-Goals

- Do not add broad new security architecture.
- Do not block legitimate RFP text with overbroad filters without measuring
  false positives.
- Do not expose private documents in red-team artifacts.

### Acceptance Criteria

- [ ] Security fixtures cover malicious retrieved-document instructions.
- [ ] Tests verify system/developer instructions remain higher priority than
  retrieved data.
- [ ] Aggregate report separates detection, neutralization, and answer behavior.

### Validation Commands

```bash
python3 -m pytest -q tests/test_verifier*.py tests/test_security*.py <focused-new-tests>
python3 <security-redteam-runner> --out <aggregate-output>
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md <plan-path> <report-path>
git diff --check
make check-branch
```

### Evidence Required

- Focused security test output.
- Aggregate red-team report with false positive and false negative counts.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: TBD
- PR: TBD

## T-2026-0036 — Abstention, conflict, and freshness calibration

- ID: T-2026-0036
- Title: Abstention, conflict, and freshness calibration
- Status: backlog
- Priority: P2
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Improve no-answer, conflicting evidence, and effective-date behavior after the
retrieval evidence surface is stable.

### Scope

- Add or harden evaluation slices for unanswerable questions, stale/deprecated
  documents, conflicting policy versions, and freshness/authority precedence.
- Measure false abstention, missed abstention, citation support, and freshness
  precedence accuracy.
- Keep policy precedence rules explicit and testable.

### Non-Goals

- Do not mask retrieval misses as answer abstention improvements.
- Do not change answer contract without ADR review.
- Do not claim production policy correctness from synthetic-only cases.

### Acceptance Criteria

- [ ] Abstention and conflict metrics are reported separately from retrieval
  recall.
- [ ] Freshness/authority rules use metadata fields with missing-field behavior
  defined.
- [ ] Private aggregate evidence is required before real-world claim wording.

### Validation Commands

```bash
python3 -m pytest -q tests/test_answer_contract_snapshot.py tests/test_eval_metrics.py <focused-new-tests>
python3 <abstention-conflict-runner> --summary-out <aggregate-output>
python3 scripts/run_real_eval_delta.py --base <baseline-aggregate> --head <variant-aggregate>
git diff --check
make check-branch
```

### Evidence Required

- Aggregate no-answer/conflict/freshness report.
- Clear separation between answer behavior and retrieval availability.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: TBD
- PR: TBD

## T-2026-0037 — Metadata, authority, and freshness ranking experiment

- ID: T-2026-0037
- Title: Metadata, authority, and freshness ranking experiment
- Status: backlog
- Priority: P2
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Measure whether document metadata can improve ranking for RFP-specific
questions without excluding valid evidence through missing or stale fields.

### Scope

- Audit metadata coverage for document type, issue date, effective date,
  expiry/deprecated state, section title, page number, authority/source class,
  customer/region/product fields when available.
- Add opt-in freshness/authority boosts or filters only after coverage supports
  them.
- Report missing-field effects separately from ranking effects.

### Non-Goals

- Do not require metadata fields that private corpus does not reliably contain.
- Do not change ACL or permission behavior in this task.
- Do not introduce a vector DB payload-index dependency unless scoped as a
  separate backend task.

### Acceptance Criteria

- [ ] Metadata coverage report determines which fields are safe to rank/filter
  on.
- [ ] Ranking variant has fail-open/fail-closed behavior documented for missing
  fields.
- [ ] Paired aggregate delta includes freshness, citation, retrieval, and
  latency metrics.

### Validation Commands

```bash
python3 <metadata-coverage-script> --index-dir <private-index> --out <aggregate-output>
python3 -m pytest -q <focused-metadata-tests>
python3 <metadata-ranking-experiment> --summary-out <aggregate-output>
python3 scripts/run_real_eval_delta.py --base <baseline-aggregate> --head <variant-aggregate>
git diff --check
make check-branch
```

### Evidence Required

- Metadata coverage aggregate.
- Ranking delta with missing-field analysis.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: TBD
- PR: TBD

## T-2026-0038 — Contextual retrieval and sentence-window proof of concept

- ID: T-2026-0038
- Title: Contextual retrieval and sentence-window proof of concept
- Status: backlog
- Priority: P2
- Owner role: Planner -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Test chunk-context enrichment and sentence-window retrieval after simpler
parent/section-window retrieval has been measured.

### Scope

- Prototype an opt-in contextual chunk prefix or sentence-window replacement
  surface.
- Record how contextual text was generated, whether external providers were
  used, payload class, and private egress mode.
- Compare against parent/section-window results before choosing a larger
  ingestion/index rebuild.

### Non-Goals

- Do not rewrite the default ingestion pipeline.
- Do not generate contextual prefixes for private chunks with an external model
  unless explicitly approved under the online payload boundary.
- Do not combine with GraphRAG/RAPTOR.

### Acceptance Criteria

- [ ] POC is opt-in and has isolated index/report paths.
- [ ] Contextual text provenance and private egress mode are recorded.
- [ ] Aggregate delta beats or clearly fails against the simpler small-to-big
  retrieval baseline.

### Validation Commands

```bash
python3 -m pytest -q <focused-contextual-retrieval-tests> tests/test_naive_baseline_ranking_invariance.py
python3 <contextual-retrieval-experiment> --summary-out <aggregate-output>
python3 scripts/run_real_eval_delta.py --base <baseline-aggregate> --head <variant-aggregate>
git diff --check
make check-branch
```

### Evidence Required

- Aggregate POC report and provenance.
- Explicit go/no-go recommendation for broader contextual retrieval work.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: TBD
- PR: TBD

## T-2026-0039 — Advanced architecture feasibility gate

- ID: T-2026-0039
- Title: Advanced architecture feasibility gate
- Status: backlog
- Priority: P3
- Owner role: Planner -> Architect -> Benchmark Auditor -> Privacy Auditor -> Deep Reviewer -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Decide whether RAPTOR, GraphRAG, LightRAG, Agentic RAG, Self-RAG, CRAG, FLARE,
late chunking, multi-vector retrieval, or long-context RAG is justified for
BidMate-DocAgent.

### Scope

- Use P0/P1/P2 aggregate evidence to identify bottlenecks that simpler changes
  could not solve.
- Produce a feasibility matrix with build cost, index size, latency, privacy
  risk, evaluation burden, rollback plan, and expected failure mode reduction.
- Recommend at most one advanced architecture follow-up issue.

### Non-Goals

- Do not implement advanced architecture in this task.
- Do not create a new graph/tree/index contract without ADR reservation.
- Do not replace the existing RAG pipeline or baseline.

### Acceptance Criteria

- [ ] Feasibility report compares advanced options against measured bottlenecks,
  not generic industry trend value.
- [ ] Any recommended architecture names the exact eval surface and ADR need.
- [ ] No-go is acceptable and preferred when evidence is weak.

### Validation Commands

```bash
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md <plan-path> <feasibility-report-path>
git diff --check
make check-branch
```

### Evidence Required

- Feasibility matrix and one recommended next issue or explicit no-go.
- Reviewer notes for architecture, privacy, eval, and rollback risk.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: TBD
- PR: TBD

## T-2026-0040 — Active-loop registry v2 + dual-agent lanes scaffold

- ID: T-2026-0040
- Title: Active-loop registry v2 + dual-agent lanes scaffold
- Status: review
- Priority: P1
- Owner role: Implementer -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Layer per-session Claude/Codex lanes onto the merged `four-role`/`expanded-eight`
active-loop topologies via registry `schema_version: 2`, as a dual-agent **lane
policy** (no new topology enum). Dry-run scaffold only.

### Scope

- `scripts/agent_loop.py`: per-session `lanes`/`write_lease_owner`/`ship_gate`,
  top-level `gate_policy`/`agent_mix`, v1->v2 lift, `--agent-mix`, `--agent` lane
  heartbeat, `agent_mix.json` ledger, topology-aware `active_loop.md`.
- `tests/test_agent_loop.py`: pin v2 contract + four-role parity.
- `docs/operations/active-agent-loop.md` + `docs/adr/0080-*.md`.

### Non-Goals

- No lane execution, no writes, no ship (Phase 2+).
- No new topology enum; no `LOAD_BEARING_PATHS` change this phase.

### Acceptance Criteria

- [ ] expanded-eight dry-run: 8 sessions w/ claude+codex lanes; 1 Implementer
  write lease (`lease_type:"write"`, `active_agent:null`).
- [ ] registry `schema_version==2`, `gate_policy=="conservative"`, agent_mix
  reflects `--agent-mix`; four-role behavior unchanged.
- [ ] `tests/test_agent_loop.py` green; ADR 0080 verifies-key clean.

### Validation Commands

```bash
python3 -m pytest tests/test_agent_loop.py -q
python3 scripts/agent_loop.py active-loop --mode full-ship --topology expanded-eight --agent-mix claude=5,codex=5 --dry-run --from-git
make check-branch
```

### Evidence Required

- Test output (105 merged + new v2 tests pass) + v2 ledger shape.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0040-active-dual-agent-lanes.md`](../docs/plans/T-2026-0040-active-dual-agent-lanes.md)
- Issue: [#1588](https://github.com/hskim-solv/BidMate-DocAgent/issues/1588)
- PR: [#1589](https://github.com/hskim-solv/BidMate-DocAgent/pull/1589)

## T-2026-0041 — Read-only Claude/Codex lane adapters + WU accounting

- ID: T-2026-0041
- Title: Read-only Claude/Codex lane adapters + WU accounting
- Status: review
- Priority: P1
- Owner role: Implementer -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Add `agent-turn` verb + flat-sibling `agent_loop_claude_turn.py` /
`agent_loop_codex_turn.py` read-only adapters (review/analysis roles), plus Work
Unit accounting (`agent-mix-report`, deterministic `choose_agent`).

### Scope

- Claude lane: `claude -p ... --permission-mode plan` + denylist; Codex lane:
  reuse `adversarial-review` (ADR 0066) + `render_codex_review.py`.
- Privacy scrub every artifact via `audit_privacy_output` (fail-closed).

### Non-Goals

- No writes/patches/ship (Phase 3+).

### Acceptance Criteria

- [x] Read-only reviewer artifacts produced + privacy-clean; WU recorded per lane;
  skew>threshold -> rebalance recommendation.

### Validation Commands

```bash
python3 -m pytest tests/test_agent_loop.py -q
python3 scripts/agent_loop.py agent-mix-report
```

### Evidence Required

- Lane artifact + WU ledger; blocked-on T-2026-0040.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0040-active-dual-agent-lanes.md`](../docs/plans/T-2026-0040-active-dual-agent-lanes.md) (umbrella roadmap; PR2 = Phase 2).
- Issue: [#1590](https://github.com/hskim-solv/BidMate-DocAgent/issues/1590) (umbrella [#1588](https://github.com/hskim-solv/BidMate-DocAgent/issues/1588)).
- PR: [#1594](https://github.com/hskim-solv/BidMate-DocAgent/pull/1594)

## T-2026-0042 — Patch-proposal + lease active_agent borrow + scratch worktree

- ID: T-2026-0042
- Title: Patch-proposal + lease active_agent borrow + scratch worktree
- Status: backlog
- Priority: P2
- Owner role: Implementer -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Let a lane borrow the write lease `active_agent` (claude XOR codex) and produce a
patch in a scratch worktree that the Orchestrator applies to integration.

### Scope

- Scratch worktree create/teardown; patch artifact; `git apply --check` -> apply.

### Non-Goals

- No direct mutation of integration branch by lanes; no ship.

### Acceptance Criteria

- [ ] `active_agent` is claude XOR codex (never both); patch applies cleanly.

### Validation Commands

```bash
python3 -m pytest tests/test_agent_loop.py -q
```

### Evidence Required

- Patch artifact + lease borrow trace. Re-confirm scope after Phase 1-2.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: [#1588](https://github.com/hskim-solv/BidMate-DocAgent/issues/1588)
- PR: TBD

## T-2026-0043 — Mutating-writer + claimed-files enforcement hook

- ID: T-2026-0043
- Title: Mutating-writer + claimed-files enforcement hook
- Status: backlog
- Priority: P2
- Owner role: Implementer -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Enable mutating turns inside claimed files only, enforced by extending
`pretooluse-bash-guard.sh` + a claimed-files edit guard; Codex via wrapper +
post-run `git diff` check.

### Scope

- Block push/merge/branch-del/ship when a lane env is active; block edits outside
  `claimed_files`.

### Non-Goals

- No ship-executor (Phase 5).

### Acceptance Criteria

- [ ] Mutating turn outside claimed_files is rejected; hook regression tests pass.

### Validation Commands

```bash
python3 -m pytest tests/test_agent_loop.py -q
```

### Evidence Required

- Hook regression test + denied-edit trace. Blocked on T-2026-0042.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: [#1588](https://github.com/hskim-solv/BidMate-DocAgent/issues/1588)
- PR: TBD

## T-2026-0044 — Orchestrator-only ship-executor + gate evidence

- ID: T-2026-0044
- Title: Orchestrator-only ship-executor + gate evidence
- Status: backlog
- Priority: P2
- Owner role: Implementer -> Deep Reviewer -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Only the Orchestrator may call `make ship-run`, after the Conservative Gate passes
and `gate_evidence/<task>/*.json` is recorded. Promote `scripts/agent_loop.py` to
`LOAD_BEARING_PATHS` here (real ship blast radius).

### Scope

- Ship-executor isolation; gate evidence artifacts; stacked-dependent remote-delete
  skip rule preserved.

### Non-Goals

- No new ship semantics beyond `make ship-run`.

### Acceptance Criteria

- [ ] Ship runs only via Orchestrator after gate pass; agent_loop.py LB + §5b wired.

### Validation Commands

```bash
python3 -m pytest tests/test_agent_loop.py -q
make check-branch
```

### Evidence Required

- gate_evidence artifact + LOAD_BEARING_PATHS diff. Blocked on T-2026-0043.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: [#1588](https://github.com/hskim-solv/BidMate-DocAgent/issues/1588)
- PR: TBD

## T-2026-0045 — Full active-agent-loop.md ops-doc rewrite

- ID: T-2026-0045
- Title: Full active-agent-loop.md ops-doc rewrite
- Status: backlog
- Priority: P3
- Owner role: Implementer -> Reviewer
- Created: 2026-05-27
- Last updated: 2026-05-27

### Goal

Rewrite `docs/operations/active-agent-loop.md` end-to-end covering topology,
Conservative Gate, lanes, WU, lease, worktree model, and privacy.

### Scope

- Ops doc only (small surface).

### Non-Goals

- No code change.

### Acceptance Criteria

- [ ] Ops doc reflects shipped Phase 1-5 behavior; no stale "4-session" framing.

### Validation Commands

```bash
make check-branch
```

### Evidence Required

- Doc diff. Blocked on T-2026-0044.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: [#1588](https://github.com/hskim-solv/BidMate-DocAgent/issues/1588)
- PR: TBD

## T-2026-0046 — Expand RAG experiment task stack and replanning gates

- ID: T-2026-0046
- Title: Expand RAG experiment task stack and replanning gates
- Status: review
- Priority: P0 planning
- Owner role: Planner -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Turn the broad RAG optimization backlog into executable experiment tasks that
can reach a final performance decision through measured iteration rather than a
single fixed implementation plan.

### Scope

- Add experiment tasks for page metadata unblock, retrieval depth/fusion,
  parser/layout coverage, embedding/representation, generator grounding,
  end-to-end bakeoff, and final decision.
- Insert explicit replanning gates after early retrieval/latency evidence and
  after the first full P1 experiment round.
- Keep this PR docs/planning only: no runtime, eval, retrieval, prompt, parser,
  or index behavior changes.

### Non-Goals

- Do not run private real-eval.
- Do not claim performance, latency, citation, or production quality improved.
- Do not create all future GitHub issues before each implementation task starts.

### Acceptance Criteria

- [x] `tasks/queue.md` names concrete experiment tasks and replanning gates.
- [x] `docs/evaluation/rag-performance-experiment-stack.md` explains the
  experiment cadence and go/no-go rules.
- [x] Every new task keeps private outputs aggregate-only and explicitly
  separates isolated experiment wins from final default-change evidence.

### Validation Commands

```bash
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/evaluation/rag-performance-experiment-stack.md docs/plans/T-2026-0046-rag-experiment-task-expansion.md
git diff --check
make check-branch
```

### Evidence Required

- Doc-link validation.
- Whitespace validation.
- Branch/issue validation.
- PR body says planning only, no private real-eval run, and no performance
  claim.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0046-rag-experiment-task-expansion.md`](../docs/plans/T-2026-0046-rag-experiment-task-expansion.md)
- Issue: [#1627](https://github.com/hskim-solv/BidMate-DocAgent/issues/1627)
- PR: TBD

### Handoff Notes

```markdown
## Session Handoff - 2026-05-28 KST

- Role: Planner
- Branch / worktree: docs/issue-1627-rag-experiment-task-stack / /Users/hskim/.codex/worktrees/de70/BidMate-DocAgent
- Issue / PR: issue #1627 / PR TBD
- Task: T-2026-0046
- Current status: experiment task expansion drafted for review.
- Files touched: tasks/queue.md, docs/evaluation/rag-performance-experiment-stack.md, docs/plans/T-2026-0046-rag-experiment-task-expansion.md
- Decisions made: keep existing implementation backlog, add explicit experiment execution tasks and replanning gates before final default-change decisions.
- Commands run: python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/evaluation/rag-performance-experiment-stack.md docs/plans/T-2026-0046-rag-experiment-task-expansion.md; git diff --check; make check-branch.
- Results: passed.
- Next safe command: python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/evaluation/rag-performance-experiment-stack.md docs/plans/T-2026-0046-rag-experiment-task-expansion.md
- Open questions: none.
- Risks: future agents may skip replanning gates and combine isolated experiment winners prematurely.
```

## T-2026-0047 — Repair or rescope real100_v2 page metadata blocker

- ID: T-2026-0047
- Title: Repair or rescope real100_v2 page metadata blocker
- Status: review
- Priority: P0
- Owner role: Evaluator -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Unblock or explicitly stop claim-bearing private experiments by proving whether
the current `real100_v2` index is valid for baseline evidence. Any hashing-backed
or page-metadata-0.0 index must be blocked before naive/private eval execution.

### Scope

- Audit why `reports/real100_v2/retrieval_diagnostics.aggregate.json` reports
  page-span coverage `0.0`.
- Reject hashing-backed private eval indexes and indexes with zero chunk page
  metadata coverage in the v2 readiness gate.
- Record whether a private v2 index rebuild is required; do not perform the
  rebuild in this PR.
- Emit a page metadata readiness packet with counts for page span, section, and
  citation-ready evidence coverage.
- Mark historical optimization reports as invalid for claims until rerun on a
  MiniLM page-aware v2 index.

### Non-Goals

- Do not change retrieval ranking.
- Do not use legacy `real100`/v1/221/kordoc evidence as a substitute.
- Do not claim answer quality improved from metadata repair alone.

### Acceptance Criteria

- [x] The task either clears the page/window blocker or records an explicit
  no-go/rescope decision for `T-2026-0031`.
- [x] Page metadata coverage is reported as aggregate counts only.
- [x] Required index rebuild is recorded as a future repair path, not a
  completed behavior change.
- [x] Hashing-backed private real-eval indexes fail closed before experiment
  execution.
- [x] 0.0-coverage page metadata indexes fail closed before experiment
  execution.

### Validation Commands

```bash
REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent make real-eval-v2-check  # expected failure for the current invalid hashing/page-0 index
python3 scripts/page_metadata_recovery_audit.py --index-dir <private-v2-index> --out-json reports/real100_v2/page_metadata_readiness.aggregate.json --out-md docs/evaluation/real100_v2-page-metadata-readiness.md --format markdown
python3 -m pytest -q tests/test_real_eval_paths.py tests/test_page_metadata_recovery_audit.py tests/test_real100_v2_guard.py
make real-eval-v2-guard
python3 scripts/agent_loop.py privacy-audit-output
python3 scripts/agent_loop.py claim-audit --from-git
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0047-repair-or-rescope-real100-v2-page-metadata-blocker.md docs/evaluation/real100_v2-page-metadata-readiness.md docs/evaluation/real100_v2-retrieval-diagnostics.md docs/evaluation/real100_v2-latency-cost-budget.md docs/evaluation/real100_v2-reranker-candidate-budget.md docs/evaluation/real100_v2-context-packing.md reports/real100_v2/README.md
git diff --check
make check-branch
```

### Evidence Required

- Aggregate page metadata readiness report:
  `reports/real100_v2/page_metadata_readiness.aggregate.json`.
- Explicit `T-2026-0031` keep-blocked recommendation: page/window claims remain
  NO-GO until a page-aware rebuild produces non-zero chunk page metadata
  coverage.
- Explicit baseline guard evidence: the current index is not valid for private
  optimization evidence because it is hashing-backed and has zero chunk page
  metadata coverage.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0047-repair-or-rescope-real100-v2-page-metadata-blocker.md`](../docs/plans/T-2026-0047-repair-or-rescope-real100-v2-page-metadata-blocker.md)
- Issue: [#1645](https://github.com/hskim-solv/BidMate-DocAgent/issues/1645)
- PR: TBD

### Handoff Notes

```markdown
## Session Handoff - 2026-05-28 14:25 KST

- Role: Evaluator / Implementer
- Branch / worktree: eval/issue-1645-repair-real100-v2-page-metadata-blocker / /Users/hskim/.codex/worktrees/0ebc/BidMate-DocAgent
- Issue / PR: issue #1645 / PR TBD
- Task: T-2026-0047
- Current status: fail-closed guard implemented; aggregate readiness packet generated; current real100_v2 page/window and optimization claims remain NO-GO.
- Files touched: scripts/real_eval_paths.py, tests/test_real_eval_paths.py, scripts/page_metadata_recovery_audit.py, tests/test_page_metadata_recovery_audit.py, reports/real100_v2/page_metadata_readiness.aggregate.json, docs/evaluation/real100_v2-page-metadata-readiness.md, docs/evaluation/real100_v2-retrieval-diagnostics.md, docs/evaluation/real100_v2-latency-cost-budget.md, docs/evaluation/real100_v2-reranker-candidate-budget.md, docs/evaluation/real100_v2-context-packing.md, reports/real100_v2/README.md, .gitignore, .githooks/pre-commit, scripts/check_real100_v2_only.py, docs/plans/T-2026-0047-repair-or-rescope-real100-v2-page-metadata-blocker.md, tasks/queue.md
- Decisions made: no parser/index rebuild in this PR; T-2026-0031 remains blocked; T-2026-0029/T-2026-0030/T-2026-0032/T-2026-0033 optimization conclusions must be rerun on a MiniLM page-aware v2 index.
- Commands run: make ship-start TITLE="Repair real100 v2 page metadata blocker" TYPE=eval; make check-branch; python3 scripts/page_metadata_recovery_audit.py --index-dir <external_private_real100_v2_index> --out-json reports/real100_v2/page_metadata_readiness.aggregate.json --out-md docs/evaluation/real100_v2-page-metadata-readiness.md --format markdown; REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent REAL100_V2_CONFIG=data/private/real100_v2/real_config_v2.local.yaml REAL100_V2_INDEX_DIR=data/index/real100_v2 REAL100_V2_REPORT_DIR=reports/real100_v2 make real-eval-v2-check.
- Results: current real100_v2 index has 100 docs, 21800 chunks, 100 parent sections, hashing embeddings, chunk page metadata coverage 0.0, page_span coverage 0.0, regions.page_number coverage 0.0; readiness is NO-GO and `make real-eval-v2-check` fails as intended.
- Next safe command: python3 -m pytest -q tests/test_real_eval_paths.py tests/test_page_metadata_recovery_audit.py tests/test_real100_v2_guard.py
- Open questions: none.
- Risks: current readiness packet must not be read as a behavior or quality improvement.
```

## T-2026-0048 — Candidate-depth and fusion-budget retrieval experiment

- ID: T-2026-0048
- Title: Candidate-depth and fusion-budget retrieval experiment
- Status: backlog
- Priority: P0
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Measure whether the dominant `not_observable_limited_depth` failure bucket is
fixed by candidate-pool depth, dense/BM25 fusion parameters, or retrieval
budget, before adding more expensive reranking or query expansion.

### Scope

- Sweep `dense_top_k`, `bm25_top_k`, RRF/fusion parameters, final candidate
  pool size, and duplicate caps on `real100_v2`.
- Report Recall@K, Hit@K, all-gold coverage, MRR, nDCG, duplicate rate,
  metadata-filter candidates, and stage latency.
- Compare against `T-2026-0032` reranker evidence without combining both changes
  in one experiment.

### Non-Goals

- Do not reopen hybrid retrieval as a broad "add BM25" claim.
- Do not change default retrieval behavior.
- Do not hide citation or answer regressions behind recall-only gains.

### Acceptance Criteria

- [ ] Output classifies each sweep cell as winner, recall-only gain, rank
  regression, duplicate regression, metadata-filter regression, latency
  regression, or no-go.
- [ ] The recommended candidate budget is usable by reranker, query rewrite, and
  context-packing experiments.
- [ ] Paired aggregate delta uses only comparable `real100_v2` inputs.

### Validation Commands

```bash
python3 -m pytest -q tests/test_retrieval*.py tests/test_naive_baseline_ranking_invariance.py <focused-new-tests>
python3 <candidate-depth-sweep-script> --config <local-v2-config> --out <aggregate-output>
python3 scripts/run_real_eval_delta.py --base <real100_v2-base-aggregate> --head <variant-aggregate>
make real-eval-v2-guard
git diff --check
make check-branch
```

### Evidence Required

- Aggregate sweep matrix and go/no-go classification.
- Explicit latency/cost result from `T-2026-0030`.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: TBD
- PR: TBD

## T-2026-0049 — Round 1 experiment synthesis and plan adjustment

- ID: T-2026-0049
- Title: Round 1 experiment synthesis and plan adjustment
- Status: backlog
- Priority: P0 replanning
- Owner role: Planner -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Reorder the experiment stack after the first measurement round instead of
blindly executing every backlog item in its original order.

### Scope

- Synthesize evidence from `T-2026-0030`, `T-2026-0032`, `T-2026-0047`, and
  `T-2026-0048`.
- Decide whether to run `T-2026-0031`, `T-2026-0033`, `T-2026-0034`,
  `T-2026-0035`, `T-2026-0037`, or `T-2026-0050` next.
- Update queue statuses, blockers, and next-safe commands without changing
  runtime behavior.

### Non-Goals

- Do not average incompatible experiment outputs.
- Do not promote a default behavior.
- Do not treat no-go results as failures; they are valid pruning evidence.

### Acceptance Criteria

- [ ] The synthesis identifies the dominant remaining bottleneck and the next
  two executable experiments.
- [ ] Any blocked task names its exact missing evidence.
- [ ] Queue and experiment-stack docs are updated with no performance claim.

### Validation Commands

```bash
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/evaluation/rag-performance-experiment-stack.md <synthesis-report-path>
git diff --check
make check-branch
```

### Evidence Required

- Aggregate-only synthesis report.
- Queue diff that promotes, blocks, or retires follow-up experiments.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: TBD
- PR: TBD

## T-2026-0050 — Parser, layout, and table coverage experiment

- ID: T-2026-0050
- Title: Parser, layout, and table coverage experiment
- Status: backlog
- Priority: P1
- Owner role: Evaluator -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Test whether answer misses are caused by parser/layout/table extraction limits
rather than retriever or generator behavior.

### Scope

- Audit private aggregate slices for table-heavy, clause-numbered, multi-column,
  scanned/OCR, and attachment-like RFP evidence.
- Compare current parser/index output against one opt-in parser or layout
  extraction variant.
- Record coverage, citation-readiness, retrieval metrics, answer metrics,
  parser latency, and failure-mode movement.

### Non-Goals

- Do not replace the default ingestion pipeline.
- Do not commit raw private document text, filenames, page images, or local
  paths.
- Do not combine parser changes with reranking, query rewrite, or prompt
  changes.

### Acceptance Criteria

- [ ] Aggregate report separates parser coverage failures from retrieval ranking
  failures.
- [ ] Any parser variant is opt-in and has isolated index/report paths.
- [ ] If parser evidence is weak, the task records no-go and returns focus to
  retrieval/context experiments.

### Validation Commands

```bash
python3 <parser-coverage-audit> --config <local-v2-config> --out <aggregate-output>
python3 -m pytest -q <focused-parser-tests>
python3 <parser-variant-runner> --variant <name> --summary-out <aggregate-output>
python3 scripts/run_real_eval_delta.py --base <real100_v2-base-aggregate> --head <variant-aggregate>
git diff --check
make check-branch
```

### Evidence Required

- Parser/layout aggregate report.
- Privacy audit result for any committed aggregate.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: TBD
- PR: TBD

## T-2026-0051 — Embedding and representation controlled sweep

- ID: T-2026-0051
- Title: Embedding and representation controlled sweep
- Status: backlog
- Priority: P1
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Measure embedding and retrieval representation effects without mixing them with
vector DB backend, parser, reranker, or prompt changes.

### Scope

- Compare approved embedding surfaces such as hashing, MiniLM, BGE-M3, and one
  explicitly approved additional model or sparse representation when available.
- Rebuild isolated indexes with matched corpus/config and record model,
  dimension, instruction prefix, similarity metric, normalization, and backend.
- Report Recall@K, MRR, nDCG, citation, answer, abstention, build time, index
  size, and query latency.

### Non-Goals

- Do not change the canonical baseline.
- Do not compare different vector DB backends in this task.
- Do not use external/private egress without an approved payload boundary.

### Acceptance Criteria

- [ ] Every compared index has matched dataset/config and explicit provenance.
- [ ] Ranking deltas are separated from backend latency/ops deltas.
- [ ] The result recommends keep-current, adopt-new-model, or no-go with
  guardrail rationale.

### Validation Commands

```bash
python3 -m pytest -q tests/test_embedding*.py tests/test_naive_baseline_ranking_invariance.py <focused-new-tests>
python3 <embedding-sweep-runner> --config <local-v2-config> --out <aggregate-output>
python3 scripts/run_real_eval_delta.py --base <real100_v2-base-aggregate> --head <variant-aggregate>
make real-eval-v2-guard
git diff --check
make check-branch
```

### Evidence Required

- Aggregate embedding sweep report.
- Provenance table for model/backend/index dimensions and cost/latency.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: TBD
- PR: TBD

## T-2026-0052 — Generator grounding and citation calibration experiment

- ID: T-2026-0052
- Title: Generator grounding and citation calibration experiment
- Status: backlog
- Priority: P1
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Measure whether answer quality is limited by generator evidence-use behavior
after retrieval, reranking, and context packing evidence is stable enough to
avoid masking retrieval misses.

### Scope

- Test opt-in prompt, decoding, citation formatting, answer-structure, and
  approved model/provider variants.
- Measure answer correctness, groundedness, citation accuracy, no-answer,
  conflict handling, token count, latency, and cost.
- Keep ADR 0003 answer schema stable unless a separate ADR is reserved.

### Non-Goals

- Do not repair retrieval misses through prompt wording.
- Do not send private context to external providers without approved online
  payload provenance.
- Do not change default answer behavior from a synthetic-only result.

### Acceptance Criteria

- [ ] Generator improvements are reported separately from retrieval/context
  availability.
- [ ] Citation regression, missed abstention, or privacy risk is a no-go even if
  answer correctness improves.
- [ ] The result recommends a default-change candidate, a follow-up slice, or
  no-go.

### Validation Commands

```bash
python3 -m pytest -q tests/test_answer_contract_snapshot.py tests/test_eval_metrics.py <focused-new-tests>
python3 <generator-calibration-runner> --variant <name> --summary-out <aggregate-output>
python3 scripts/run_real_eval_delta.py --base <real100_v2-base-aggregate> --head <variant-aggregate>
python3 scripts/agent_loop.py privacy-audit-output
python3 scripts/agent_loop.py claim-audit --from-git
git diff --check
make check-branch
```

### Evidence Required

- Aggregate generator calibration report.
- Explicit provider/payload and decoding provenance.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: TBD
- PR: TBD

## T-2026-0053 — Round 2 experiment synthesis and plan adjustment

- ID: T-2026-0053
- Title: Round 2 experiment synthesis and plan adjustment
- Status: backlog
- Priority: P1 replanning
- Owner role: Planner -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Recompute the optimization roadmap after the second experiment round, when
retrieval, context, query, metadata, parser, embedding, and generator evidence
can be compared as separate bottleneck surfaces.

### Scope

- Synthesize `T-2026-0031` through `T-2026-0038` plus `T-2026-0050` through
  `T-2026-0052` when available.
- Retire experiments whose guardrails failed, promote the strongest isolated
  winners to end-to-end bakeoff, and decide whether `T-2026-0039` advanced
  architecture feasibility is justified.
- Update queue status and next-safe commands.

### Non-Goals

- Do not merge isolated winners into a runtime default.
- Do not create a new metric surface without ADR review.
- Do not keep running low-signal experiments just because they were listed.

### Acceptance Criteria

- [ ] Synthesis report names no more than three variants for end-to-end bakeoff.
- [ ] Any advanced architecture recommendation cites measured residual
  bottlenecks and expected failure-mode reduction.
- [ ] Queue updates make the next task unambiguous.

### Validation Commands

```bash
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/evaluation/rag-performance-experiment-stack.md <synthesis-report-path>
python3 scripts/agent_loop.py claim-audit --from-git
git diff --check
make check-branch
```

### Evidence Required

- Aggregate-only round-2 synthesis.
- Explicit go/no-go list for bakeoff and advanced architecture.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: TBD
- PR: TBD

## T-2026-0054 — End-to-end winning-variant bakeoff

- ID: T-2026-0054
- Title: End-to-end winning-variant bakeoff
- Status: backlog
- Priority: P2
- Owner role: Implementer -> Architect -> Benchmark Auditor -> Privacy Auditor -> Deep Reviewer -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Test whether the best isolated experiment winners still improve the full RAG
pipeline when combined under one latency, cost, privacy, and answer-contract
guardrail.

### Scope

- Build at most three integrated opt-in variants from `T-2026-0053` outputs.
- Run paired `real100_v2` aggregate deltas against the canonical baseline.
- Report interaction effects: retrieval gain lost by reranking, context gain
  lost by token budget, prompt gain lost by citation regression, or latency
  overrun.

### Non-Goals

- Do not flip defaults.
- Do not combine more than three moving parts in one variant.
- Do not include advanced architecture unless `T-2026-0039` and `T-2026-0053`
  recommend it.

### Acceptance Criteria

- [ ] Bakeoff compares baseline, isolated winners, and integrated variants with
  matched provenance.
- [ ] Winner requires answer/citation/abstention improvement and latency/cost
  guardrail pass.
- [ ] Negative interaction effects are recorded as follow-up blockers or no-go.

### Validation Commands

```bash
python3 -m pytest -q <focused-integration-tests>
python3 <end-to-end-bakeoff-runner> --config <local-v2-config> --out <aggregate-output>
python3 scripts/run_real_eval_delta.py --base <real100_v2-base-aggregate> --head <variant-aggregate>
make real-eval-v2-guard
python3 scripts/agent_loop.py privacy-audit-output
python3 scripts/agent_loop.py claim-audit --from-git
git diff --check
make check-branch
```

### Evidence Required

- Aggregate bakeoff report.
- Integrated variant provenance and rollback plan.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: TBD
- PR: TBD

## T-2026-0055 — Final optimization decision packet

- ID: T-2026-0055
- Title: Final optimization decision packet
- Status: backlog
- Priority: P2 decision
- Owner role: Benchmark Auditor -> Privacy Auditor -> Deep Reviewer -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Convert the experiment program into a final optimization decision: default
change proposal, additional targeted experiment, or explicit no-go.

### Scope

- Summarize the full evidence chain from baseline, diagnostics, latency/cost,
  isolated experiments, replanning gates, and end-to-end bakeoff.
- If a default change is recommended, name required ADR updates, load-bearing
  paths, rollout flags, rollback command, and PR body §5b evidence.
- If no-go, identify the residual blocker and next evidence needed.

### Non-Goals

- Do not implement the default flip in this task.
- Do not weaken ADR 0001 baseline protections.
- Do not hide failed experiments; failed/no-go evidence is part of the decision.

### Acceptance Criteria

- [ ] Decision packet makes one of three calls: default-change-ready,
  more-experiment-needed, or no-go.
- [ ] Any default-change-ready call cites paired private aggregate delta,
  latency/cost guardrail, privacy audit, claim audit, and rollback plan.
- [ ] Reviewer can trace every claim to aggregate-safe evidence.

### Validation Commands

```bash
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/evaluation/rag-performance-experiment-stack.md <decision-packet-path>
python3 scripts/agent_loop.py claim-audit --from-git
git diff --check
make check-branch
```

### Evidence Required

- Final decision packet.
- Explicit follow-up issue recommendation for implementation or no-go.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: TBD
- PR: TBD

## T-2026-0056 — Ollama local OpenAI-compatible provider spike

- ID: T-2026-0056
- Title: Ollama local OpenAI-compatible provider spike
- Status: backlog
- Priority: P1
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Measure whether Ollama is useful as a local `openai_compatible` provider for
LLM synthesis and judge surfaces, focusing on privacy, cost, latency, JSON
compliance, and grounded citation behavior rather than retrieval quality.

### Scope

- Add a small, documented Ollama run path for existing `openai_compatible`
  surfaces such as `BIDMATE_SYNTHESIS_*` and `BIDMATE_JUDGE_*`.
- Run a local smoke or small `real100_v2` screening slice when an Ollama server
  and model are available.
- Record provider provenance, model name, context-size setting, latency,
  fallback behavior, malformed-JSON rate, and aggregate-only quality signals.

### Non-Goals

- Do not change default CI, API, or eval behavior away from `stub`.
- Do not change retrieval, reranking, embedding, parser, or answer schema
  behavior.
- Do not commit raw private prompts, raw completions, or per-case private
  verdicts.
- Do not claim answer-quality improvement without paired `real100_v2`
  aggregate evidence.

### Acceptance Criteria

- [ ] The task documents exact Ollama environment variables and a local health
  check without requiring code-path duplication.
- [ ] If Ollama is unavailable, the report says exactly what is missing and how
  to verify it.
- [ ] Any live run records aggregate-only latency/cost/privacy evidence and
  separates provider/runtime effects from retrieval effects.
- [ ] JSON/citation guard failures fall back safely and are counted rather than
  hidden.

### Validation Commands

```bash
python3 -m pytest -q tests/test_llm_synthesis.py tests/test_external_payload_boundary_regression.py tests/test_self_review_judge.py
BIDMATE_SYNTHESIS_BACKEND=openai_compatible BIDMATE_SYNTHESIS_BASE_URL=http://localhost:11434/v1 BIDMATE_SYNTHESIS_API_KEY=ollama BIDMATE_SYNTHESIS_MODEL=<local-model> python3 <ollama-synthesis-smoke-runner>
BIDMATE_JUDGE_BACKEND=openai_compatible BIDMATE_JUDGE_BASE_URL=http://localhost:11434/v1 BIDMATE_JUDGE_API_KEY=ollama BIDMATE_JUDGE_MODEL=<local-model> python3 <ollama-judge-smoke-runner>
make real-eval-v2-guard
python3 scripts/agent_loop.py privacy-audit-output
python3 scripts/agent_loop.py claim-audit --from-git
git diff --check
make check-branch
```

### Evidence Required

- Ollama setup and health-check note.
- Aggregate-only screening report with provider/model/context provenance.
- Explicit go/no-go recommendation for using Ollama in later generator or judge
  experiments.

### Related Plan / Issue / PR Links

- Plan: TBD - create when the task starts.
- Issue: #1649
- PR: TBD

## T-2026-0057 — real100_v2 portfolio wording cleanup

- ID: T-2026-0057
- Title: real100_v2 portfolio wording cleanup
- Status: review
- Priority: P0 positioning
- Owner role: Planner -> Privacy Auditor -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Remove legacy private-eval wording from current portfolio claims so README and
interview-facing docs use only the `real100_v2` aggregate-only evidence lane for
new claims.

### Scope

- Update README and portfolio pitch language that currently presents
  earlier-generation private-eval wording as current evidence.
- Preserve archive references only when they are explicitly historical and not
  used as current claim support.
- State that raw private questions, answers, evidence text, filenames, local
  paths, `doc_id`, and `chunk_id` remain uncommitted.

### Non-Goals

- Do not run private eval.
- Do not change scoring, retrieval, answer, API, or runtime behavior.
- Do not claim quality improved because wording changed.

### Acceptance Criteria

- [ ] README and portfolio pitch name `real100_v2` as the current private
  evidence lane.
- [ ] Earlier-generation private-eval wording is not used for a new claim.
- [ ] Claim audit and `real100_v2` guard pass.

### Validation Commands

```bash
python3 scripts/check_doc_links.py --check-all --paths README.md docs/portfolio-pitch.md tasks/queue.md docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md
make real-eval-v2-guard
python3 scripts/agent_loop.py claim-audit --from-git
git diff --check
make check-branch
```

### Evidence Required

- Doc-link check output.
- `real100_v2` guard output.
- Claim audit output.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md`](../docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md)
- Issue: [#1651](https://github.com/hskim-solv/BidMate-DocAgent/issues/1651)
- PR: TBD

## T-2026-0058 — Multimodal Agent positioning map

- ID: T-2026-0058
- Title: Multimodal Agent positioning map
- Status: review
- Priority: P0 positioning
- Owner role: Planner -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Convert the career positioning strategy into an executable repo task map:
RAG as foundation, Agent as primary direction, VLM/multimodal as
differentiator, evaluation/LLMOps and productization as proof, and vLLM-style
serving as auxiliary evidence.

### Scope

- Add a queue stack for visual evidence, VLM captioning, agent state/security,
  trajectory evaluation, product API/demo integration, self-hosted serving,
  Graph RAG feasibility, interview evidence, and review board refresh.
- Keep the existing RAG performance experiment stack intact.
- Record that `T-2026-0056` is already occupied by the Ollama provider spike, so
  this positioning stack starts at `T-2026-0057`.

### Non-Goals

- Do not implement multimodal or agent runtime features in this task.
- Do not add new external dependencies.
- Do not create a new benchmark or metric surface.

### Acceptance Criteria

- [ ] Queue rows and detailed task sections exist for `T-2026-0057` through
  `T-2026-0070`.
- [ ] Each follow-up task has an evidence boundary, privacy boundary, and
  validation route.
- [ ] Existing optimization tasks `T-2026-0028` through `T-2026-0056` are not
  reordered or redefined.

### Validation Commands

```bash
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md docs/portfolio-pitch.md README.md
python3 scripts/agent_loop.py claim-audit --from-git
git diff --check
make check-branch
```

### Evidence Required

- Queue diff.
- Plan doc.
- Claim audit output.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md`](../docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md)
- Issue: [#1651](https://github.com/hskim-solv/BidMate-DocAgent/issues/1651)
- PR: TBD

## T-2026-0059 — External source and citation audit

- ID: T-2026-0059
- Title: External source and citation audit
- Status: backlog
- Priority: P0 positioning
- Owner role: Planner -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Ensure external framework and vendor claims used in portfolio wording are
current, cited, and grounded in either official documentation or existing repo
ADR/implementation evidence.

### Scope

- Audit references to LlamaIndex, LangGraph, OpenAI Agents SDK, RAGAS,
  LangSmith, MCP/A2A, vLLM, TEI, CrewAI, AutoGen, and related frameworks before
  using them as portfolio claims.
- Prefer repo-internal evidence when implementation already exists, such as
  LangGraph ADRs, OpenAI-compatible provider support, MCP helper tooling,
  FastAPI docs, and observability docs.
- Produce a small source map that distinguishes implemented, planned, and
  external-background-only claims.

### Non-Goals

- Do not add new framework dependencies.
- Do not rewrite README around trend keywords.
- Do not cite third-party docs as proof that this repo implements a capability.

### Acceptance Criteria

- [ ] Every external framework mention in positioning docs is marked as
  implemented, planned, or background-only.
- [ ] Official docs are used for external claims when needed.
- [ ] Unverified or low-value framework references are removed.

### Validation Commands

```bash
python3 scripts/check_doc_links.py --check-all --paths docs/portfolio-pitch.md README.md <source-map-path>
python3 scripts/agent_loop.py claim-audit --from-git
git diff --check
make check-branch
```

### Evidence Required

- Source map or audit note.
- Claim audit output.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md`](../docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md)
- Issue: TBD
- PR: TBD

## T-2026-0060 — Visual evidence contract hardening

- ID: T-2026-0060
- Title: Visual evidence contract hardening
- Status: backlog
- Priority: P1 multimodal
- Owner role: Evaluator -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Define how OCR/layout/table/image evidence becomes retrieval-ready and
citation-ready before adding VLM captioning or multimodal agent behavior.

### Scope

- Extend or document the visual artifact contract for text blocks, page spans,
  table cells, region metadata, image captions, and citation anchors.
- Connect the contract to existing parser/layout/table coverage work rather than
  bypassing `T-2026-0050`.
- Add focused public-fixture or aggregate-only checks for visual evidence
  readiness.

### Non-Goals

- Do not add VLM provider calls.
- Do not change default ingestion behavior.
- Do not commit private page images, raw OCR text, filenames, or local paths.

### Acceptance Criteria

- [ ] Visual evidence fields needed by retrieval and citation are documented.
- [ ] Parser/layout/table readiness is separated from VLM captioning.
- [ ] Private evidence remains aggregate-only.

### Validation Commands

```bash
python3 -m pytest -q tests/test_visual_ingestion.py tests/test_page_aware_parser_contract.py <focused-new-tests>
python3 scripts/check_doc_links.py --check-all --paths docs/vision/visual-ingestion-v2.md tasks/queue.md <contract-doc-path>
python3 scripts/agent_loop.py privacy-audit-output
git diff --check
make check-branch
```

### Evidence Required

- Contract doc or focused test output.
- Privacy audit output when aggregate artifacts are added.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md`](../docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md)
- Issue: TBD
- PR: TBD

## T-2026-0061 — Opt-in VLM captioning spike

- ID: T-2026-0061
- Title: Opt-in VLM captioning spike
- Status: backlog
- Priority: P1 multimodal
- Owner role: Implementer -> Privacy Auditor -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Test whether VLM captioning can add useful public visual evidence without
changing default ingestion or sending private RFP data to external providers.

### Scope

- Add a public-fixture-only spike path for image/page captioning.
- Record provider, model, payload class, egress mode, latency, cost, and caption
  failure rate.
- Keep caption output isolated from canonical private indexes unless a later ADR
  and privacy boundary approve it.

### Non-Goals

- Do not use private documents or private page images.
- Do not change retrieval defaults.
- Do not claim multimodal retrieval quality from a public-only spike.

### Acceptance Criteria

- [ ] Spike can run on public fixtures with explicit provider/payload
  provenance.
- [ ] Captions are tagged as experimental and isolated.
- [ ] Missing provider credentials produce a clear skip/no-go report.

### Validation Commands

```bash
python3 -m pytest -q tests/test_external_payload_boundary_regression.py <focused-vlm-tests>
python3 <vlm-caption-spike-runner> --input <public-fixture-path> --out <public-output>
python3 scripts/agent_loop.py privacy-audit-output
git diff --check
make check-branch
```

### Evidence Required

- Public-fixture spike report.
- Provider/payload provenance.
- Privacy audit output.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md`](../docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md)
- Issue: TBD
- PR: TBD

## T-2026-0062 — Agent tool-state-trace contract

- ID: T-2026-0062
- Title: Agent tool-state-trace contract
- Status: backlog
- Priority: P1 agent
- Owner role: Implementer -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Make tool calling, state transitions, retry/fallback behavior, and permission
boundaries inspectable before expanding agent workflows.

### Scope

- Define a minimal tool-state-trace shape for agent steps.
- Reuse existing LangGraph/agentic docs and trace conventions when possible.
- Include timeout, retry, fallback, user-escalation, and tool-denial states.

### Non-Goals

- Do not replace existing answer dict contract.
- Do not add CrewAI/AutoGen or another orchestration framework.
- Do not expose mutating tools without a permission policy.

### Acceptance Criteria

- [ ] Tool call, observation, retry, fallback, and stop states are documented or
  serialized.
- [ ] Permission boundary is explicit.
- [ ] Existing direct and LangGraph paths remain backward compatible.

### Validation Commands

```bash
python3 -m pytest -q tests/test_langgraph_orchestrator_regression.py tests/test_agent_react_regression.py <focused-agent-trace-tests>
python3 scripts/check_doc_links.py --check-all --paths docs/agentic/agent-system-design-case-study.md docs/agentic/agent-failure-modes-analysis.md tasks/queue.md <contract-doc-path>
git diff --check
make check-branch
```

### Evidence Required

- Contract doc or trace fixture.
- Focused regression tests.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md`](../docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md)
- Issue: TBD
- PR: TBD

## T-2026-0063 — Agent security and human-in-the-loop guardrail

- ID: T-2026-0063
- Title: Agent security and human-in-the-loop guardrail
- Status: backlog
- Priority: P1 security
- Owner role: Security Reviewer -> Implementer -> Privacy Auditor -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Prevent multimodal/tool-using agent work from expanding before prompt
injection, tool permission, escalation, and manual review boundaries are
explicit.

### Scope

- Extend the existing prompt-injection and evidence-boundary guardrails to
  multimodal and tool-call settings.
- Define when the agent must ask a user, stop, or route to human review.
- Add red-team fixtures for tool misuse, indirect instruction injection, and
  unsafe visual/document content.

### Non-Goals

- Do not add broad new security architecture.
- Do not enable mutating tools by default.
- Do not weaken existing verifier/evidence-boundary behavior.

### Acceptance Criteria

- [ ] Tool-call permission failures are fail-closed.
- [ ] Human review checkpoints are explicit for risky operations.
- [ ] Security tests cover prompt/document/tool boundary attacks.

### Validation Commands

```bash
python3 -m pytest -q tests/test_security*.py tests/test_prompt_injection_regression.py tests/test_evidence_boundary_attack_vectors.py <focused-agent-security-tests>
python3 <security-redteam-runner> --out <aggregate-output>
python3 scripts/agent_loop.py privacy-audit-output
git diff --check
make check-branch
```

### Evidence Required

- Focused security test output.
- Red-team aggregate report if added.
- Privacy audit output.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md`](../docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md)
- Issue: TBD
- PR: TBD

## T-2026-0064 — Multimodal troubleshooting vertical slice

- ID: T-2026-0064
- Title: Multimodal troubleshooting vertical slice
- Status: backlog
- Priority: P2 product
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Build an opt-in vertical slice that demonstrates image/document analysis,
manual retrieval, cause ranking, action recommendation, uncertainty handling,
and trace capture as one product workflow.

### Scope

- Use public fixtures or approved redacted examples only.
- Connect visual evidence, RAG retrieval, agent state, and answer/citation
  output through an isolated workflow.
- Produce a trace and evaluation packet that separates visual, retrieval,
  tool-call, and answer failures.

### Non-Goals

- Do not change default BidMate RFP query behavior.
- Do not use private images or private RFP pages without a new approved
  boundary.
- Do not claim production readiness.

### Acceptance Criteria

- [ ] The vertical slice runs end-to-end on approved public/redacted inputs.
- [ ] Failure modes are separated by visual, retrieval, agent, and answer stage.
- [ ] Output includes confidence/uncertainty and citation/evidence references.

### Validation Commands

```bash
python3 -m pytest -q <focused-vertical-slice-tests>
python3 <multimodal-troubleshooting-runner> --input <public-or-redacted-input> --out <aggregate-output>
python3 scripts/agent_loop.py privacy-audit-output
python3 scripts/agent_loop.py claim-audit --from-git
git diff --check
make check-branch
```

### Evidence Required

- Public/redacted vertical-slice output.
- Stage-separated trace or aggregate.
- Privacy and claim audit output.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md`](../docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md)
- Issue: TBD
- PR: TBD

## T-2026-0065 — Agent trajectory evaluation

- ID: T-2026-0065
- Title: Agent trajectory evaluation
- Status: backlog
- Priority: P2 eval
- Owner role: Evaluator -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Evaluate agent behavior beyond final-answer correctness by measuring trajectory
quality, tool-call success, retry/fallback behavior, latency, cost, and
human-review triggers.

### Scope

- Define trajectory metrics that complement existing answer/retrieval metrics.
- Reuse existing rationality judge and trace conventions where they fit.
- Report aggregate-only results with no raw private trace leakage.

### Non-Goals

- Do not replace existing answer-quality metrics.
- Do not create a new metric surface without ADR review if the metric becomes
  claim-bearing.
- Do not average incompatible public and private surfaces.

### Acceptance Criteria

- [ ] Metrics separate final answer outcome from process quality.
- [ ] Tool-call and retry failures are visible.
- [ ] Aggregate output is privacy-safe.

### Validation Commands

```bash
python3 -m pytest -q tests/test_rationality_judge.py tests/test_trace_schema_v2.py <focused-trajectory-tests>
python3 <trajectory-eval-runner> --out <aggregate-output>
python3 scripts/agent_loop.py privacy-audit-output
python3 scripts/agent_loop.py claim-audit --from-git
git diff --check
make check-branch
```

### Evidence Required

- Trajectory metric spec or aggregate.
- Focused tests.
- Privacy and claim audit output.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md`](../docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md)
- Issue: TBD
- PR: TBD

## T-2026-0066 — Product API/demo integration

- ID: T-2026-0066
- Title: Product API/demo integration
- Status: backlog
- Priority: P2 product
- Owner role: Implementer -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Expose the selected multimodal agent workflow through a restrained FastAPI/demo
surface that proves product integration without changing core RAG defaults.

### Scope

- Add opt-in API/demo entrypoints for the approved workflow.
- Preserve existing FastAPI query schemas and default behavior.
- Record latency, trace id, failure status, and user-facing uncertainty.

### Non-Goals

- Do not turn the demo into a broad product rebuild.
- Do not require frontend work unless the API surface is stable.
- Do not add auth/rate-limit/security claims unless implemented and tested.

### Acceptance Criteria

- [ ] Existing API tests pass unchanged.
- [ ] New workflow is opt-in and documented.
- [ ] Demo/API output exposes traceability and safe failure states.

### Validation Commands

```bash
python3 -m pytest -q tests/test_api.py tests/test_api_default_pipeline_regression.py <focused-api-tests>
python3 scripts/check_doc_links.py --check-all --paths docs/operations/api-demo.md README.md tasks/queue.md <api-doc-path>
git diff --check
make check-branch
```

### Evidence Required

- Focused API tests.
- API docs.
- Manual smoke result if a UI/demo path is changed.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md`](../docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md)
- Issue: TBD
- PR: TBD

## T-2026-0067 — Self-hosted OpenAI-compatible serving demo

- ID: T-2026-0067
- Title: Self-hosted OpenAI-compatible serving demo
- Status: backlog
- Priority: P3 serving
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Show service/ops awareness by connecting an opt-in OpenAI-compatible local
serving endpoint, such as vLLM or llama.cpp, without making serving the primary
positioning.

### Scope

- Document one self-hosted OpenAI-compatible server path and connect it to
  existing synthesis or judge provider configuration.
- Measure latency, throughput/concurrency, JSON compliance, memory/runtime
  constraints when locally available.
- Position this as auxiliary product/ops evidence, complementary to the Ollama
  spike in `T-2026-0056`.

### Non-Goals

- Do not require GPU infrastructure in CI.
- Do not replace default offline/stub behavior.
- Do not claim platform/serving specialization as the repo's main positioning.

### Acceptance Criteria

- [ ] The demo has exact setup and skip/no-go instructions.
- [ ] Provider/runtime effects are separated from retrieval and answer effects.
- [ ] No private payload leaves approved local boundaries.

### Validation Commands

```bash
python3 -m pytest -q tests/test_llm_synthesis.py tests/test_external_payload_boundary_regression.py <focused-serving-tests>
python3 <openai-compatible-serving-smoke> --base-url <local-url> --model <model> --out <aggregate-output>
python3 scripts/agent_loop.py privacy-audit-output
python3 scripts/agent_loop.py claim-audit --from-git
git diff --check
make check-branch
```

### Evidence Required

- Local serving setup note.
- Aggregate smoke output or explicit unavailable/no-go report.
- Privacy and claim audit output.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md`](../docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md)
- Issue: TBD
- PR: TBD

## T-2026-0068 — Knowledge/Graph RAG feasibility

- ID: T-2026-0068
- Title: Knowledge/Graph RAG feasibility
- Status: backlog
- Priority: P3 architecture
- Owner role: Planner -> Architect -> Benchmark Auditor -> Privacy Auditor -> Deep Reviewer -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Decide whether relation-structured evidence such as agency, requirement,
deadline, symptom, cause, procedure, table, and visual region justifies a
Knowledge/Graph RAG follow-up.

### Scope

- Use measured residual bottlenecks from retrieval, parser/layout, metadata, and
  advanced architecture gates.
- Compare simple metadata/entity retrieval, graph retrieval, ontology work, and
  no-go.
- Recommend at most one follow-up implementation issue.

### Non-Goals

- Do not build a graph database in this task.
- Do not introduce Graph RAG because it is trendy.
- Do not bypass `T-2026-0039` advanced architecture feasibility evidence.

### Acceptance Criteria

- [ ] Feasibility matrix names expected failure-mode reduction.
- [ ] Build cost, privacy risk, eval burden, latency, and rollback are covered.
- [ ] Recommendation is implement-one, defer, or no-go.

### Validation Commands

```bash
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/evaluation/rag-performance-experiment-stack.md <feasibility-report-path>
python3 scripts/agent_loop.py claim-audit --from-git
git diff --check
make check-branch
```

### Evidence Required

- Feasibility report.
- Explicit next issue or no-go rationale.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md`](../docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md)
- Issue: TBD
- PR: TBD

## T-2026-0069 — Interview and resume evidence pack

- ID: T-2026-0069
- Title: Interview and resume evidence pack
- Status: backlog
- Priority: P2 positioning
- Owner role: Planner -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Convert the repo evidence into interview-ready and resume-ready artifacts for
Multimodal Agentic AI Product Engineer, LLM/Agent Engineer, AI Product Engineer,
LLMOps/Evaluation Engineer, and serving-adjacent roles.

### Scope

- Produce STAR answers, role-specific pitch variants, and a repo evidence link
  map.
- Separate implemented evidence from planned tasks.
- Keep exact private metrics out unless they are `real100_v2` aggregate-safe and
  current.

### Non-Goals

- Do not create a separate private portfolio repo artifact in this task unless a
  follow-up issue is opened.
- Do not include unsupported claims about VLM/Agent/serving implementation.
- Do not expose private eval payloads.

### Acceptance Criteria

- [ ] Evidence pack maps each role claim to repo files, ADRs, tests, reports, or
  explicit planned tasks.
- [ ] Resume/interview wording distinguishes "implemented" from "planned".
- [ ] Legacy private-eval wording is absent from current claims.

### Validation Commands

```bash
python3 scripts/check_doc_links.py --check-all --paths docs/portfolio-pitch.md tasks/queue.md <evidence-pack-path>
python3 scripts/agent_loop.py claim-audit --from-git
git diff --check
make check-branch
```

### Evidence Required

- Interview/resume evidence pack.
- Claim audit output.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md`](../docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md)
- Issue: TBD
- PR: TBD

## T-2026-0070 — Portfolio review board refresh

- ID: T-2026-0070
- Title: Portfolio review board refresh
- Status: backlog
- Priority: P2 positioning
- Owner role: Implementer -> Privacy Auditor -> Reviewer
- Created: 2026-05-28
- Last updated: 2026-05-28

### Goal

Refresh reviewer-facing generated HTML boards after the Markdown positioning
docs settle, while keeping Markdown as the source of truth.

### Scope

- Update the portfolio review board inputs to reflect real100_v2-only wording
  and the Multimodal Agent/Product positioning stack.
- Keep generated HTML ignored/local and reproducible.
- Verify no raw private data, local paths, or unsupported claims appear in the
  generated boards.

### Non-Goals

- Do not make generated HTML canonical.
- Do not add a new measurement surface.
- Do not change runtime or eval behavior.

### Acceptance Criteria

- [ ] Portfolio board renders current positioning and evidence links.
- [ ] Generated HTML contains no raw private payloads or exact local paths.
- [ ] Tests cover board title/content changes if renderer behavior changes.

### Validation Commands

```bash
python3 -m pytest -q tests/test_render_priority_review_boards.py
python3 scripts/render_priority_review_boards.py
python3 scripts/agent_loop.py privacy-audit-output
python3 scripts/check_doc_links.py --check-all --paths docs/portfolio-pitch.md tasks/queue.md
git diff --check
make check-branch
```

### Evidence Required

- Focused renderer test output.
- Local generated board path and privacy audit result.

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md`](../docs/plans/T-2026-0056-multimodal-agent-positioning-stack.md)
- Issue: TBD
- PR: TBD
