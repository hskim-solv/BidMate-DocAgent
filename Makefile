# PHONY declarations are grouped by workflow domain to mirror the recipe
# sections below. Composite gates (e.g. `governance-check`) live alongside
# their member targets. Preserve target names verbatim when adding to a
# group — downstream docs (CLAUDE.md, docs/engineering-governance.md) and
# .githooks/ reference these names directly.

# Setup / hooks
.PHONY: setup install-hooks

# Governance gates (branch + issue, fixture latency SLO, real-eval history
# freshness, benchmark manifest check). Run
# `make governance-check` to invoke the pre-PR subset in sequence.
.PHONY: check-branch governance-check check check-latency real-eval-history-check benchmark-check check-baseline-provenance check-doc-links regen-golden check-golden

# Index build + ad-hoc ask
.PHONY: index ask build-kordoc-manifest

# Public fixture smoke eval surface. Includes deterministic smoke, eval,
# harness matrix, pareto, and Korean public bench helpers. Real performance
# measurement remains on private/internal eval sets.
.PHONY: eval smoke reproduce benchmark pareto cost-frontier korean-public-fetch korean-public-eval harness-smoke harness-ablation harness-compare

# Real-data eval cycle (private; ADR 0005 commit boundary).
.PHONY: real-eval real-eval-check real-eval-inventory real-eval-v2-check real-eval-v2-inventory real-eval-v2-guard real-eval-v2-checkpoint-index real-eval-v2-chroma real-eval-v2-chroma-llm real-eval-v2-judge real-eval-v2-ragas-judge real-eval-v2-rationality-judge real-eval-minilm real-eval-semantic real-eval-page-aware real-eval-delta real-eval-baseline-update real-eval-history-render real-eval-with-judge harness-real

# Real-data case proposer cycle (ADR 0029; gitignored I/O).
.PHONY: case-propose case-propose-metadata case-review case-promote

# API / demo (FastAPI + Streamlit; local + docker variants)
.PHONY: api api-docker demo demo-docker docker-publish ui-smoke

# Tests
.PHONY: test test-regression

# Agent-loop orchestration helpers. Thin wrappers around scripts/agent_loop.py;
# they render prompts, classify surfaces, check handoffs, suggest or run
# allowlisted local validation, and write ignored local planning drafts. They
# do not perform GitHub mutations.
.PHONY: agent-loop-next agent-loop-status agent-loop-prompt agent-loop-handoff agent-loop-review agent-loop-surface agent-loop-validation agent-loop-validate agent-loop-preflight agent-loop-pr-scan agent-loop-issue-scan agent-loop-maintenance-plan agent-loop-issue-close agent-loop-next-from-prs agent-loop-pr-health agent-loop-draft-task agent-loop-draft-next agent-loop-batch-plan agent-loop-queue-parallel-plan agent-loop-queue-recommendations agent-loop-review-followup agent-loop-review-ingest agent-loop-decision-brief agent-loop-promote-draft agent-loop-gate-status agent-loop-claim-audit agent-loop-privacy-audit-output agent-loop-auto-pass agent-loop-dashboard agent-loop-mcp-config agent-loop-safe-fix agent-loop-approval-packet agent-loop-propose-queue-plan agent-loop-pr-body agent-loop-review-plan agent-loop-stale-reports agent-loop-context-pack agent-loop-architecture-brief agent-loop-ship-simulate agent-loop-auto-ship-prepare agent-loop-auto-ship-plan agent-loop-gate-brief agent-loop-manifest agent-loop-pr-body-check agent-loop-ci-ingest agent-loop-stacked-risk agent-loop-patch-proposal agent-loop-adr-reserve agent-loop-dashboard-html agent-loop-ship-command-pack agent-loop-apply-queue-plan agent-loop-review-threads agent-loop-ci-summary agent-loop-readiness-score agent-loop-artifact-freshness agent-loop-review-patch-plan agent-loop-queue-plan-sync agent-loop-dependency-graph agent-loop-branch-issue-hygiene agent-loop-integration-pack agent-loop-scheduled-status agent-loop-validation-history agent-loop-privacy-regression agent-loop-claim-policy agent-loop-architecture-decision agent-loop-workset-recommend agent-loop-automation-coverage agent-loop-active-start agent-loop-active-codex-runner agent-loop-active-auto-loop 시작 시작-ship agent-loop-human-gated-exec agent-loop-loop-state agent-loop-map agent-loop-mcp

# Auto-ship pipeline (Stop hook driven). See scripts/claude-hooks/stop-ship.sh
# and the plan at /Users/hskim/.claude/plans/prci-synchronous-newell.md.
.PHONY: ship-start ship-arm ship-run codex-ship codex-reap ship-disarm ship-status ship-review-gate worktree-cleanup-dry-run worktree-cleanup cmux-cleanup-dry-run cmux-cleanup

# Self-review (quarterly meta-feedback loop). Combines 4-axis portfolio
# rubric + 5-axis Claude collaboration rubric. See SKILL at
# .claude/skills/self-review-quarterly/SKILL.md and privacy policy at
# docs/self-review/README.md.
.PHONY: self-review-quarterly hook-fires-weekly

# Cleanup
.PHONY: clean

PYTHON ?= python3
VENV ?= .venv
ACTIVATE = . $(VENV)/bin/activate

setup:
	$(PYTHON) -m venv $(VENV)
	$(ACTIVATE) && pip install -r requirements.txt

# One-time per clone: activate the opt-in git hooks in .githooks/
# (pre-commit ADR 0005 boundary, pre-push branch/eval checks, commit-msg
# ADR 0007 issue-ref check from issue #826).
install-hooks:
	git config core.hooksPath .githooks
	@# Shared-objectstore (multi-worktree) corruption prevention (issue #1680).
	@# 20-30 worktrees share one .git/objects; automatic gc/repack/prune races with
	@# in-flight `git add`/commit and deletes blobs only an uncommitted worktree index
	@# references -> `fatal: unable to read <blob>` / invalid cache-tree. Disable all
	@# automatic pruning (run `git gc --no-detach` manually only when no session is active)
	@# and fsync loose objects so the index never references a not-yet-durable blob.
	git config gc.auto 0
	git config gc.autoDetach false
	git config maintenance.auto false
	git config fetch.writeCommitGraph false
	git config core.fsync loose-object
	git config core.fsyncMethod batch
	@echo "Activated .githooks/ + shared-objectstore corruption guards for this clone. See docs/engineering-governance.md §Hook setup."

# Ad-hoc validation of the current branch against ADR 0007.
# Useful before opening a PR; mirrors the CI check.
check-branch:
	$(PYTHON) scripts/check_branch_and_issue.py \
	  --branch "$$(git rev-parse --abbrev-ref HEAD)" --check-issue

# Composite governance gate. Runs the pre-PR checks in sequence:
# branch + issue convention (ADR 0007), real-data history-table freshness,
# baseline provenance, docs links, and fixture latency. Each sub-target is
# already wired into CI / hooks individually; this target just shortens
# the local pre-PR checklist into a single invocation. Fails on the
# first sub-target that exits non-zero.
governance-check: check-branch real-eval-history-check check-baseline-provenance check-doc-links check
	@echo "governance-check: branch + real-eval-history + baseline-provenance + doc-links + fixture-latency OK."

# Verify reports/real100/baseline.aggregate.json's provenance.git_commit is
# still reachable from origin/main (issue #413). Catches the silent-breakage
# tail of issue #160: a baseline committed at a SHA that was later
# force-pushed/rebased off main, leaving `make real-eval-delta` diffing
# against a phantom code state. For non-default refs, invoke the script
# directly: `python scripts/check_baseline_provenance.py --ref <ref>`.
check-baseline-provenance:
	$(PYTHON) scripts/check_baseline_provenance.py

# Markdown cross-reference dead-link gate (issue #1060). Scans all tracked
# `*.md` (docs/ + root README/CLAUDE.md, excluding .claude/) for relative
# links whose target file is missing, plus prose `ADR NNNN` refs with no file.
# Stdlib-only, <1s. Canonical enforcement is the pytest gate
# tests/test_doc_links.py; this target + the pre-commit hook are shift-left.
check-doc-links:
	$(PYTHON) scripts/check_doc_links.py --check-all

index:
	$(PYTHON) scripts/build_index.py --input_dir eval/fixtures/smoke_rfp/raw --output_dir data/index

# Re-prime a kordoc cache's manifest.json so ingestion can trust the bypass
# (issue #1278). Required once after this gate landed for any pre-existing
# committed cache; override SOURCE_DIR / CACHE_DIR for non-default layouts.
SOURCE_DIR ?= data/files
CACHE_DIR ?= data/files_kordoc
build-kordoc-manifest:
	$(PYTHON) scripts/build_kordoc_manifest.py --source-dir $(SOURCE_DIR) --cache-dir $(CACHE_DIR)

ask:
	$(PYTHON) app.py --input_dir data/index --output_dir outputs --query "기관 A와 기관 B의 보안 요구사항 차이를 알려줘" --pipeline agentic_full

eval:
	$(PYTHON) eval/run_eval.py --index_dir data/index --output_dir reports --config eval/config.yaml
	@$(MAKE) -s experiment-report-html

# Cost-quality Pareto frontier table (and PNG if matplotlib installed)
# from the latest reports/eval_summary.json. Read-only consumer — see
# scripts/plot_pareto.py for cost/quality axis choice (latency p95 vs
# citation_precision).
pareto:
	$(PYTHON) scripts/plot_pareto.py --summary reports/eval_summary.json --markdown-out reports/pareto.md --png-out reports/pareto.png

# Cost-accuracy frontier (ADR 0038 / issue #798). Reads local aggregate
# summaries only; private/internal eval aggregates are the intended input for
# performance claims. Writes reports/cost_frontier.md + reports/cost_frontier.png
# when enough source data is available.
cost-frontier:
	$(PYTHON) scripts/plot_cost_frontier.py

# Auto-render paired HTML next to every reports/**/*.aggregate.json,
# reports/**/eval_summary.json, and reports/retrieval/**/REPORT.md.
# Idempotent — only stale or missing pairs are rendered. Aggregate-only
# (ADR 0005); raw_results.json / data_list*.csv / data/private/** denied.
# Issue #1661. See docs/operations/experiment-report-html.md.
experiment-report-html:
	@$(PYTHON) scripts/render_experiment_report_html.py --auto-scan --quiet

# Publish the demo image to GHCR so reviewers can `docker run <image>`
# without cloning the repo (issue #123). Requires `docker login ghcr.io`
# beforehand; override IMAGE_TAG to publish to a different registry.
IMAGE_TAG ?= ghcr.io/hskim-solv/bidmate-demo:latest
docker-publish:
	docker build -t $(IMAGE_TAG) .
	docker push $(IMAGE_TAG)

benchmark:
	$(PYTHON) scripts/run_benchmark.py --suite $${SUITE:?set SUITE=benchmarks/suites/<suite>.yaml} --ablations benchmarks/ablations/rag_quality_axes.yaml

benchmark-check:
	$(PYTHON) scripts/summarize_benchmark.py --manifest $${MANIFEST:?set MANIFEST=artifacts/benchmarks/<run_id>/run_manifest.json} --check

# Fixture smoke latency gate. Run `make smoke` first so reports/eval_summary.json
# exists; this does not compare public fixture scores as benchmark evidence.
check:
	@test -f reports/eval_summary.json || { echo "reports/eval_summary.json missing — run 'make smoke' first"; exit 1; }
	$(PYTHON) scripts/check_latency_slo.py --config eval/config.yaml --summary reports/eval_summary.json

# naive_baseline ranking golden (tests/data/naive_baseline_top_k.json) regen +
# staleness check. The golden drifts when the smoke fixture corpus changes (PR #648,
# #914); content drift is hard-gated by
# tests/test_naive_baseline_ranking_invariance.py. `regen-golden` refreshes the
# committed snapshot in place (ADR 0001: pipeline code untouched); `check-golden`
# exits non-zero if the committed golden is stale (also used by the pre-push
# soft-warn reminder in .githooks/_pre-push-real-eval-reminder.sh).
regen-golden:
	$(PYTHON) scripts/regen_naive_baseline_golden.py

check-golden:
	$(PYTHON) scripts/regen_naive_baseline_golden.py --check

# Absolute p95 latency SLO gate. Reads per-ablation budgets from
# eval/config.yaml::latency_budgets and fails if any observed p95
# exceeds its ceiling. Runs are silent if no budget is declared —
# adding a new ablation does not force a budget for every one.
check-latency:
	$(PYTHON) scripts/check_latency_slo.py --config eval/config.yaml --summary reports/eval_summary.json

# Korean public RAG bench (ADR 0018) — supplementary out-of-domain
# surface. Fetches a deterministic KorQuAD 2.1 dev subset (~93 MB
# one-time download) and runs the existing pipeline against it.
# Never CI-gated; numbers describe upstream dataset distribution, not
# pipeline correctness. Output → reports/korean_public/eval_summary.json.
korean-public-fetch:
	$(PYTHON) eval/korean_public/fetch_korquad.py

korean-public-eval: korean-public-fetch
	$(PYTHON) eval/korean_public/run.py

# `install-hooks` is a prerequisite so the first `make smoke` on a fresh
# worktree activates `.githooks/` (closes #719). install-hooks is
# idempotent (`git config` only, ~5ms), so transitively re-running adds
# negligible cost. Restores axis #3 (자동화 ROI) measurement by
# guaranteeing `.hook-fires.log` is writable from the first dev action.
smoke: install-hooks
	bash scripts/smoke.sh
	@$(MAKE) -s experiment-report-html

# Cross-machine reproducibility hash. Runs the smoke eval and prints a
# SHA-256 over the environment-invariant subset of reports/eval_summary.json
# (latency/timestamps stripped). Pass BASELINE=<sha> to compare against a
# known-good hash from another machine; exit 2 on mismatch.
reproduce:
	bash scripts/reproduce_eval.sh

harness-smoke:
	$(PYTHON) scripts/run_harness.py --config harness/smoke.yaml

# Real-data harness profile. Requires harness/real.local.yaml (copied from
# harness/real.example.yaml) and the eval/*.local.yaml it points to. None
# of these resolved files are committed.
harness-real:
	$(PYTHON) scripts/run_harness.py --config harness/real.local.yaml

# Run a matrix of harness cells on the committed public fixture corpus.
# Writes artifacts/matrices/<matrix_id>/{matrix_summary.json, compare.md}.
# Pass MATRIX=harness/your.yaml to use a different matrix file.
MATRIX ?= harness/ablation.example.yaml
harness-ablation:
	$(PYTHON) scripts/run_harness.py --matrix $(MATRIX) --force

# Compare two harness runs (dirs under artifacts/runs/ or eval_summary.json).
# Example: make harness-compare RUN_A=artifacts/runs/a RUN_B=artifacts/runs/b
harness-compare:
	$(PYTHON) scripts/run_harness.py --compare \
	  --run-a $${RUN_A:?set RUN_A=<run-dir-or-eval_summary.json>} \
	  --run-b $${RUN_B:?set RUN_B=<run-dir-or-eval_summary.json>}

test:
	bash scripts/test.sh

# Fast local edit loop: the full suite minus `slow`-marked files (fixture
# corpus or real embedding-model tests — see pyproject.toml
# markers). Those few files dominate wall-clock under `--dist loadfile`
# tail latency; deselecting them keeps the local loop snappy. The CI gate
# (`make test` / scripts/test.sh) defaults to the same non-slow PR gate;
# slow tests run via `.github/workflows/slow-tests.yml` or explicit
# PYTEST_ADDOPTS.
#
# TEST_WORKERS caps xdist parallelism. Default 4 (not `-n auto`): a dev box
# hosting many git worktrees runs under memory pressure, and `-n auto`
# (one worker per logical core, 8–10 here) makes every worker re-collect +
# import simultaneously at startup, spiking free RAM to near-zero. macOS
# jetsam then OOM-kills a worker mid-schedule, and xdist references the dead
# worker → `INTERNALERROR KeyError <WorkerController gwN>` after a 20-min
# swap-thrash with zero tests run (issue #1318). Capping at 4 completes the
# same suite in ~80s on that box. Override on a roomy machine/CI:
# `make test-fast TEST_WORKERS=auto`.
TEST_WORKERS ?= 4
test-fast:
	$(PYTHON) -m pytest -m "not slow" -n $(TEST_WORKERS) --dist loadfile -q

# Fast P0 regression guards for the retrieval loop and answerable smoke path.
# Run before any change to rag_core retrieval/verification or the eval pipeline.
test-regression:
	$(PYTHON) -m pytest tests/test_retrieval_loop_regression.py -q

# ---------------------------------------------------------------------------
# Agent-loop orchestration helpers.
#
# These targets make the lightweight CLI easy to call from Codex Desktop or a
# local terminal. They intentionally stop at ignored local artifacts and
# allowlisted local validation: no Codex auto-run, no push, no PR
# creation/merge/close, no branch deletion, no force-push.
#
# Examples:
#   make agent-loop-next
#   make agent-loop-map
#   make agent-loop-mcp
#   make agent-loop-pr-scan
#   make agent-loop-issue-scan
#   make agent-loop-maintenance-plan
#   make agent-loop-issue-close ISSUE=123 COMMENT_FILE=reports/agent_loop/issue-close-123.md CONFIRM_HUMAN_APPROVED=1
#   make agent-loop-next-from-prs
#   make agent-loop-pr-health
#   make agent-loop-draft-task
#   make agent-loop-draft-next
#   make agent-loop-batch-plan
#   make agent-loop-review-followup REVIEW=reports/agent_loop/review_prompt.md
#   make agent-loop-review-ingest REVIEW=reports/agent_loop/review_prompt.md
#   make agent-loop-decision-brief TASK=T-2026-0003
#   make agent-loop-promote-draft
#   make agent-loop-gate-status TASK=T-2026-0003
#   make agent-loop-claim-audit CLAIM_TEXT=reports/agent_loop/review_prompt.txt
#   make agent-loop-privacy-audit-output
#   make agent-loop-auto-pass
#   make agent-loop-dashboard
#   make agent-loop-mcp-config
#   make agent-loop-safe-fix
#   make agent-loop-approval-packet
#   make agent-loop-propose-queue-plan
#   make agent-loop-pr-body
#   make agent-loop-review-plan REVIEW=reports/agent_loop/review_prompt.md
#   make agent-loop-stale-reports
#   make agent-loop-context-pack
#   make agent-loop-architecture-brief
#   make agent-loop-ship-simulate
#   make agent-loop-auto-ship-prepare AUTO_SHIP_ISSUE=123 AUTO_SHIP_CREATE_BRANCH=1 CONFIRM_HUMAN_APPROVED=1
#   make agent-loop-auto-ship-plan AUTO_SHIP_DRY_RUN=1
#   make agent-loop-gate-brief GATE=pr-create
#   make agent-loop-manifest
#   make agent-loop-pr-body-check
#   make agent-loop-ci-ingest CI_LOG=reports/agent_loop/ci.log
#   make agent-loop-stacked-risk BRANCH=chore/issue-123-example
#   make agent-loop-patch-proposal
#   make agent-loop-adr-reserve ADR_TITLE="New eval surface"
#   make agent-loop-dashboard-html
#   make agent-loop-ship-command-pack
#   make agent-loop-apply-queue-plan CONFIRM_HUMAN_APPROVED=1
#   make agent-loop-active-start
#   make agent-loop-loop-state TASK=T-2026-0003
#   make agent-loop-status TASK=T-2026-0003
#   make agent-loop-preflight TASK=T-2026-0003
#   make agent-loop-prompt TASK=T-2026-0003 OUT=reports/agent_loop/rendered_prompt.txt
#   make agent-loop-validation
#   make agent-loop-validate
#   make agent-loop-surface CHANGED_FILES=/path/to/changed-files.txt
#   make agent-loop-handoff TASK=T-2026-0003
#   make agent-loop-review TASK=T-2026-0003 CHANGED_FILES=/path/to/changed-files.txt
# ---------------------------------------------------------------------------

ROLE ?= Implementer
TASK ?=
PLAN ?=
PR ?=
BRANCH ?=
CHANGED_FILES ?=
OUT ?=
PR_STATE ?= reports/agent_loop/pr_state.json
ISSUE_STATE ?= reports/agent_loop/issue_state.json
ISSUE_TRIAGE_OUT ?= reports/agent_loop/issue_triage.md
MAINTENANCE_PLAN_OUT ?= reports/agent_loop/maintenance_plan.md
MAINTENANCE_PLAN_JSON ?= reports/agent_loop/maintenance_plan.json
ISSUE_QUEUE_TASKS_DIR ?= reports/agent_loop/issue_queue_tasks
COMMENT_FILE ?=
LIMIT ?= 30
STATE ?= open
TASK_BRIEF ?=
DRAFT_TASK_ID ?= T-2026-0000
READINESS_SUMMARY ?=
READINESS_REPORT ?=
REAL100_DIR ?=
PAGE_METADATA_INDEX_DIR ?=
REVIEW ?=
BATCH_OUT ?= reports/agent_loop/batch_plan.md
BATCH_JSON_OUT ?= reports/agent_loop/batch_plan.json
QUEUE_PARALLEL_PLAN_OUT ?= reports/agent_loop/queue_parallel_plan.md
QUEUE_PARALLEL_PLAN_JSON_OUT ?= reports/agent_loop/queue_parallel_plan.json
QUEUE_PARALLEL_PLAN_LIMIT ?= 12
QUEUE_RECOMMENDATIONS_OUT ?= reports/agent_loop/queue_recommendations.md
QUEUE_RECOMMENDATIONS_JSON_OUT ?= reports/agent_loop/queue_recommendations.json
QUEUE_RECOMMENDATIONS_APPLY ?= 0
REVIEW_FOLLOWUP_OUT ?= reports/agent_loop/review_followups.md
REVIEW_FOLLOWUP_DIR ?= reports/agent_loop/review_followups
DECISION_OUT ?= reports/agent_loop/decision_brief.md
DECISION_BATCH ?=
DECISION_REVIEW_FOLLOWUPS ?=
PROMOTE_OUT ?= reports/agent_loop/promote_draft.md
GATE_STATUS_OUT ?= reports/agent_loop/gate_status.md
CLAIM_TEXT ?=
CLAIM_AUDIT_OUT ?= reports/agent_loop/claim_audit.md
PRIVACY_AUDIT_PATH ?= reports/agent_loop
PRIVACY_AUDIT_OUT ?= reports/agent_loop/privacy_audit.md
AUTO_PASS_OUT ?= reports/agent_loop/auto_pass.md
AUTO_PASS_STRICT ?=
AUTO_PASS_PROFILE ?= standard
RUN_VALIDATION ?=
DASHBOARD_OUT ?= reports/agent_loop/dashboard.md
MCP_CONFIG_OUT ?= reports/agent_loop/mcp_client_config.md
REVIEW_INGEST_OUT ?= reports/agent_loop/review_ingest.md
PR_HEALTH_OUT ?= reports/agent_loop/pr_health.md
SAFE_FIX_OUT ?= reports/agent_loop/safe_fix.md
SAFE_FIX_APPLY ?=
APPROVAL_PACKET_OUT ?= reports/agent_loop/approval_packet.md
QUEUE_PLAN_PATCH_OUT ?= reports/agent_loop/queue_plan_patch.diff
PR_BODY_OUT ?= reports/agent_loop/pr_body.md
ISSUE ?=
REVIEW_PLAN_OUT ?= reports/agent_loop/review_plan.md
STALE_REPORTS_OUT ?= reports/agent_loop/stale_reports.md
STALE_MAX_AGE_DAYS ?= 7
STALE_APPLY ?=
CONTEXT_PACK_OUT ?= reports/agent_loop/context_pack.md
ARCHITECTURE_BRIEF_OUT ?= reports/agent_loop/architecture_brief.md
SHIP_SIMULATION_OUT ?= reports/agent_loop/ship_simulation.md
AUTO_SHIP_PREPARE_OUT ?= reports/agent_loop/auto_ship_prepare.md
AUTO_SHIP_ISSUE ?=
AUTO_SHIP_TARGET_BRANCH ?=
AUTO_SHIP_BRANCH_TYPE ?= chore
AUTO_SHIP_SLUG ?= agent-loop-auto-ship
AUTO_SHIP_CREATE_BRANCH ?=
AUTO_SHIP_PLAN_OUT ?= reports/agent_loop/auto_ship_plan.md
AUTO_SHIP_TTL ?= 2h
AUTO_SHIP_REAL_EVAL ?=
AUTO_SHIP_DRAFT ?=
AUTO_SHIP_DRY_RUN ?=
AUTO_SHIP_READY ?=
AUTO_SHIP_NO_DRY_RUN ?=
GATE_BRIEF_OUT ?= reports/agent_loop/gate_brief.md
MANIFEST_OUT ?= reports/agent_loop/manifest.json
MANIFEST_COMMAND ?= manual
MANIFEST_OUTPUT ?=
PR_BODY_CHECK_OUT ?= reports/agent_loop/pr_body_check.md
CI_LOG ?=
CI_INGEST_OUT ?= reports/agent_loop/ci_ingest.md
CI_FOLLOWUP_DIR ?= reports/agent_loop/ci_followups
STACKED_RISK_OUT ?= reports/agent_loop/stacked_risk.md
PATCH_PROPOSAL_OUT ?= reports/agent_loop/patch_proposal.diff
PATCH_REVIEW_PLAN ?=
ADR_TITLE ?=
ADR_RESERVATION_OUT ?= reports/agent_loop/adr_reservation.md
ADR_DRAFT_OUT ?= reports/agent_loop/adr_draft.md
DASHBOARD_HTML_OUT ?= reports/agent_loop/dashboard.html
SHIP_COMMANDS_OUT ?= reports/agent_loop/ship_commands.md
APPLY_QUEUE_PLAN_OUT ?= reports/agent_loop/apply_queue_plan.md
CONFIRM_HUMAN_APPROVED ?=
REVIEW_THREADS_JSON ?=
REVIEW_THREADS_OUT ?= reports/agent_loop/review_threads.md
CI_SUMMARY_OUT ?= reports/agent_loop/ci_summary.md
READINESS_SCORE_OUT ?= reports/agent_loop/readiness_score.md
BRANCH_ISSUE_HYGIENE_OUT ?= reports/agent_loop/branch_issue_hygiene.md
INTEGRATION_PACK_OUT ?= reports/agent_loop/integration_pack.md
SCHEDULE_CONFIG_OUT ?= reports/agent_loop/schedule_config.md
VALIDATION_HISTORY ?= reports/agent_loop/validation_history.jsonl
VALIDATION_HISTORY_OUT ?= reports/agent_loop/validation_history.md
PRIVACY_REGRESSION_OUT ?= reports/agent_loop/privacy_regression.md
CLAIM_POLICY_OUT ?= reports/agent_loop/claim_policy.md
ARCHITECTURE_DECISION_OUT ?= reports/agent_loop/architecture_decision.md
WORKSET_RECOMMENDATION_OUT ?= reports/agent_loop/workset_recommendation.md
DEPENDENCY_GRAPH_OUT ?= reports/agent_loop/dependency_graph.md
AUTOMATION_COVERAGE_OUT ?= reports/agent_loop/automation_coverage.md
ACTIVE_START_OUT ?= reports/agent_loop/active/start.md
ACTIVE_TOPOLOGY ?= expanded-eight
ACTIVE_AGENT_MIX ?= claude=5,codex=5

# ADR 0082: dual-lane model × effort × adversarial knobs (claude lane uses Messages API).
# claude lane — role 별 model + effort. Planner/Reviewer/Deep Reviewer 는 Opus 4.8
# xhigh, 나머지 Sonnet 4.6 medium. manual budget_tokens 폐기 (Opus 4.7+ adaptive effort).
BIDMATE_CLAUDE_LANE_PLANNER_MODEL ?= claude-opus-4-8
BIDMATE_CLAUDE_LANE_PLANNER_EFFORT ?= xhigh
BIDMATE_CLAUDE_LANE_MODEL ?= claude-sonnet-4-6
BIDMATE_CLAUDE_LANE_EFFORT ?= medium
# codex lane — 2026 라인업. Reviewer/Deep = gpt-5.5 frontier (high), CI Auditor = gpt-5.4-mini (medium).
# codex companion 1.0.4 의 adversarial-review subcommand 는 --effort 미지원 → env 정의만, 호출 미주입.
BIDMATE_CODEX_LANE_REVIEWER_MODEL ?= gpt-5.5
BIDMATE_CODEX_LANE_REVIEWER_EFFORT ?= high
BIDMATE_CODEX_LANE_CI_MODEL ?= gpt-5.4-mini
BIDMATE_CODEX_LANE_CI_EFFORT ?= medium
BIDMATE_CODEX_LANE_MODEL ?= gpt-5.5
BIDMATE_CODEX_LANE_EFFORT ?= high
# dual-lane 동작 — 0=병렬 독립 (backward-compat), 1=adversarial (1차 lane→2차 lane challenge).
BIDMATE_DUAL_LANE_ADVERSARIAL ?= 1
ACTIVE_LEASE_TTL_MINUTES ?= 30
ACTIVE_REPAIR_BRANCH ?= 1
ACTIVE_REPAIR_BRANCH_TYPE ?= chore
ACTIVE_REPAIR_SLUG ?= active-start
ACTIVE_REPAIR_TITLE ?= Agent loop active start
ACTIVE_START_RUNNER ?= 1
ACTIVE_START_RUNNER_EXECUTE ?= 1
ACTIVE_CODEX_RUNNER_OUT ?= reports/agent_loop/active/codex_runner.md
ACTIVE_CODEX_RUNNER_STATE ?= reports/agent_loop/active/codex_runner_state.json
ACTIVE_CODEX_RUNS_DIR ?= reports/agent_loop/active/codex_runs
ACTIVE_AUTO_LOOP_OUT ?= reports/agent_loop/active/auto_loop.md
ACTIVE_AUTO_LOOP_STATE ?= reports/agent_loop/active/auto_loop_state.json
# Parent DIRECTORY of ACTIVE_AUTO_LOOP_STATE — used by 시작-ship for the ship
# manifest dir / state-dir / kill-switch path (those expect a directory, not the
# loop's state FILE above).
ACTIVE_SHIP_STATE_DIR ?= reports/agent_loop/active
ACTIVE_AUTO_LOOP_MAX_ITERATIONS ?= 5
ACTIVE_AUTO_LOOP_AUTO_MAX_ITERATIONS ?= 5
ACTIVE_AUTO_LOOP_TARGET_COMPLETED_COUNT ?=
ACTIVE_AUTO_LOOP_EXECUTE_RUNNER ?= 1
ACTIVE_AUTO_LOOP_EXECUTE_SHIP ?= 0
ACTIVE_AUTO_LOOP_AUTO_REPAIR ?= 1
START_TASK_LIMIT ?= 5
START_TASK_ATTEMPT_LIMIT ?= 15
# ADR 0085: set START_INFINITE=1 to run `make 시작` until the ready task queue drains.
# Infinite mode drops the completed-target + attempt-cap bounds (max-iterations=0) and is
# bounded only by ready-queue exhaustion + the safety guards
# (BIDMATE_AGENT_LOOP_MAX_CONSECUTIVE_BLOCKERS / BIDMATE_AGENT_LOOP_MAX_WALL_CLOCK_SECONDS).
START_INFINITE ?=
ACTIVE_CODEX_SESSIONS ?=
ACTIVE_CODEX_MAX_PARALLEL ?= 8
ACTIVE_CODEX_TIMEOUT_SECONDS ?= 0
# ADR 0085: the Claude write lane no longer substitutes a 900s cap when the codex timeout
# is 0. 0 now means *unlimited* on both lanes (a long write must not be killed mid-flight,
# especially in infinite mode). Override ACTIVE_CLAUDE_WRITE_TIMEOUT_SECONDS to re-impose a
# bound when desired.
ACTIVE_CLAUDE_WRITE_TIMEOUT_SECONDS ?= $(ACTIVE_CODEX_TIMEOUT_SECONDS)
export ACTIVE_CLAUDE_WRITE_TIMEOUT_SECONDS
# ADR 0094 PR-C: M = global ceiling on concurrent agent-loop CLI subprocess spawns.
# Default 8; fail-closed M<=0 -> 1. Ships DARK + byte-identical at X=1/M=8 (the
# semaphore is uncontended when the loop spawns one child at a time). The runtime
# read path is os.getenv("BIDMATE_AGENT_LOOP_GLOBAL_CONCURRENCY"); ACTIVE_GLOBAL_CONCURRENCY
# is the operator front-door knob, bridged to that env var below so
# `make ... ACTIVE_GLOBAL_CONCURRENCY=N` actually reaches the runtime. A direct
# BIDMATE_AGENT_LOOP_GLOBAL_CONCURRENCY already in the env still wins (via ?=).
ACTIVE_GLOBAL_CONCURRENCY ?= 8
export ACTIVE_GLOBAL_CONCURRENCY
BIDMATE_AGENT_LOOP_GLOBAL_CONCURRENCY ?= $(ACTIVE_GLOBAL_CONCURRENCY)
export BIDMATE_AGENT_LOOP_GLOBAL_CONCURRENCY
# ADR 0095: X task-pool size (concurrent queue tasks in flight). Default 2 == X-parallel
# bounded-loop execution (PR-F flipped the operator default 1 -> 2, issue #1948). Serial (X=1,
# the ADR 0001 byte-identical path) is still available via `make ... ACTIVE_TASK_POOL=1`.
# fail-closed pool<=0 -> 1. The runtime read path is os.getenv("BIDMATE_AGENT_LOOP_TASK_POOL");
# ACTIVE_TASK_POOL is the operator front-door knob bridged to that env var below so
# `make ... ACTIVE_TASK_POOL=N` reaches the runtime. A direct BIDMATE_AGENT_LOOP_TASK_POOL already
# in the env still wins (via ?=). The global kill-switch (BIDMATE_AGENT_LOOP_PARALLELISM_KILL=1)
# forces 1 regardless (serial demotion). PR-E3c enabled the real X>1 fan-out (worktree-per-task
# isolation); PR-E2's DARK effective-pool clamp was removed there.
ACTIVE_TASK_POOL ?= 2
export ACTIVE_TASK_POOL
BIDMATE_AGENT_LOOP_TASK_POOL ?= $(ACTIVE_TASK_POOL)
export BIDMATE_AGENT_LOOP_TASK_POOL
# ADR 0095 PR-D: best-effort cap on the worker count the omc runner requests of `omc team`
# (Y default-on, omc path only). Default 3; fail-closed cap<=0 -> 1. The runtime read path is
# os.getenv("OMC_MAX_WORKERS") directly (no bridge var needed — the code reads this exact name),
# but a direct OMC_MAX_WORKERS already in the env still wins (via ?=). The effective worker
# total is min(OMC_MAX_WORKERS, --max-parallel); omc is out-of-process so this is best-effort
# (the global semaphore charges the single omc launch one permit, not each omc worker). Affects
# the omc runner path ONLY — the default codex runner is byte-identical (ADR 0001).
OMC_MAX_WORKERS ?= 3
export OMC_MAX_WORKERS
# ADR 0085: 0 == unlimited. The per-session command cap is dropped on the operator front
# door so the autonomous loop is bounded by timeout + attempt/queue + safety guards, not an
# arbitrary command count. Set a positive value to re-impose a cap.
ACTIVE_CODEX_MAX_COMMANDS_PER_SESSION ?= 0
ACTIVE_CODEX_EXECUTABLE ?= codex
ACTIVE_CODEX_MODEL ?= $(BIDMATE_CODEX_LANE_MODEL)
ACTIVE_CODEX_AUTH_MODE ?= chatgpt
ACTIVE_CODEX_SANDBOX ?= read-only
ACTIVE_READ_AGENT ?= auto
ACTIVE_WRITE_AGENT ?= auto
# Parallel-execution runner backend (ADR 0087, opt-in). Default `codex` is byte-identical to
# today (ADR 0001). `omc` delegates to `omc team` and additionally requires
# ACTIVE_OMC_RUNNER_ACK=1 (uncontrolled workers relax the ADR 0005 boundary).
ACTIVE_RUNNER ?= codex
# ADR 0092 (opt-in): per-(role,agent) lane adaptive autotune. PR1 = sense + detect +
# recommendation. PR2 = actuate: the controller steps the lane effort (claude --effort /
# codex -c model_reasoning_effort) on the next iteration, clamped to the per-agent ladder,
# with COOLDOWN iterations of suppression after each adjustment. Default empty == OFF ==
# byte-identical (no per-lane elapsed_s, no recommendations, no effort override, controller
# never invoked).
ACTIVE_LANE_AUTOTUNE ?=
ACTIVE_LANE_AUTOTUNE_K ?= 2.0
ACTIVE_LANE_AUTOTUNE_FAIL_WINDOW ?= 3
ACTIVE_LANE_AUTOTUNE_FAIL_MIN_SAMPLE ?= 2
ACTIVE_LANE_AUTOTUNE_FAIL_THRESHOLD ?= 0.5
ACTIVE_LANE_AUTOTUNE_COOLDOWN ?= 2
ACTIVE_CODEX_RECORD_GATE_HEARTBEATS ?= 1
ACTIVE_CODEX_EXECUTE ?=
HUMAN_GATED_ACTION ?=
HUMAN_GATED_EXEC_OUT ?= reports/agent_loop/human_gated_exec.md
HUMAN_GATED_DRY_RUN ?=
CONFIRM_REVIEW_GATE_PASSED ?=
CONFIRM_DEPENDENTS_REVIEWED ?=
CONFIRM_FORCE_WITH_LEASE ?=
PR_BASE ?=
PR_TITLE ?=
PR_READY ?=
LOOP_STATE_OUT ?= reports/agent_loop/loop_state.json
GATE ?= auto

agent-loop-next:
	$(PYTHON) scripts/agent_loop.py next

agent-loop-status:
	$(PYTHON) scripts/agent_loop.py status \
	  $(if $(TASK),--task "$(TASK)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git)

agent-loop-prompt:
	@if [ -z "$(TASK)" ]; then \
	  echo "Usage: make agent-loop-prompt TASK=T-2026-0003 [ROLE=Implementer] [PLAN=docs/plans/...] [OUT=reports/agent_loop/rendered_prompt.txt]"; \
	  exit 1; \
	fi
	$(PYTHON) scripts/agent_loop.py render-prompt \
	  --task "$(TASK)" \
	  --role "$(ROLE)" \
	  $(if $(PLAN),--plan "$(PLAN)",) \
	  --out "$(or $(OUT),reports/agent_loop/rendered_prompt.txt)"

agent-loop-handoff:
	@if [ -z "$(TASK)" ]; then \
	  echo "Usage: make agent-loop-handoff TASK=T-2026-0003 [PLAN=docs/plans/...]"; \
	  exit 1; \
	fi
	$(PYTHON) scripts/agent_loop.py handoff-check \
	  --task "$(TASK)" \
	  $(if $(PLAN),--plan "$(PLAN)",)

agent-loop-review:
	@if [ -z "$(TASK)" ]; then \
	  echo "Usage: make agent-loop-review TASK=T-2026-0003 [PR=123] [BRANCH=name] [CHANGED_FILES=changed.txt] [OUT=reports/agent_loop/review_prompt.txt]"; \
	  exit 1; \
	fi
	$(PYTHON) scripts/agent_loop.py review-prompt \
	  --task "$(TASK)" \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(BRANCH),--branch "$(BRANCH)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --out "$(or $(OUT),reports/agent_loop/review_prompt.txt)"

agent-loop-surface:
	$(PYTHON) scripts/agent_loop.py classify-surface \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git)

agent-loop-validation:
	$(PYTHON) scripts/agent_loop.py suggest-validation \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git)

agent-loop-validate:
	$(PYTHON) scripts/agent_loop.py validate \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  $(if $(KEEP_GOING),--keep-going,) \
	  $(if $(RECORD_HISTORY),--record-history --history "$(VALIDATION_HISTORY)",)

agent-loop-preflight:
	@if [ -z "$(TASK)" ]; then \
	  echo "Usage: make agent-loop-preflight TASK=T-2026-0003 [PR=123] [CHANGED_FILES=changed.txt]"; \
	  exit 1; \
	fi
	$(PYTHON) scripts/agent_loop.py preflight \
	  --task "$(TASK)" \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --write-prompts

agent-loop-pr-scan:
	$(PYTHON) scripts/agent_loop.py pr-scan \
	  --state "$(STATE)" \
	  --limit "$(LIMIT)" \
	  --out "$(PR_STATE)" \
	  $(if $(INCLUDE_BODY),--include-body,)

agent-loop-next-from-prs:
	$(PYTHON) scripts/agent_loop.py next-from-prs \
	  --pr-json "$(PR_STATE)" \
	  $(if $(READINESS_SUMMARY),--readiness-summary "$(READINESS_SUMMARY)",) \
	  $(if $(READINESS_REPORT),--readiness-report "$(READINESS_REPORT)",) \
	  $(if $(REAL100_DIR),--real100-dir "$(REAL100_DIR)",) \
	  $(if $(PAGE_METADATA_INDEX_DIR),--page-metadata-index-dir "$(PAGE_METADATA_INDEX_DIR)",)

agent-loop-pr-health:
	$(PYTHON) scripts/agent_loop.py pr-health \
	  --pr-json "$(PR_STATE)" \
	  --out "$(PR_HEALTH_OUT)"

agent-loop-draft-task:
	$(PYTHON) scripts/agent_loop.py draft-task \
	  --task-id "$(DRAFT_TASK_ID)" \
	  $(if $(TASK_BRIEF),--task-brief "$(TASK_BRIEF)",)

agent-loop-draft-next:
	$(PYTHON) scripts/agent_loop.py draft-next \
	  --task-id "$(DRAFT_TASK_ID)" \
	  --state "$(STATE)" \
	  --limit "$(LIMIT)" \
	  $(if $(INCLUDE_BODY),--include-body,)

agent-loop-batch-plan:
	$(PYTHON) scripts/agent_loop.py batch-plan \
	  --tasks-dir reports/agent_loop/codex_tasks \
	  --out "$(BATCH_OUT)" \
	  --json-out "$(BATCH_JSON_OUT)"

agent-loop-queue-parallel-plan:
	$(PYTHON) scripts/agent_loop.py queue-parallel-plan \
	  --max-items "$(QUEUE_PARALLEL_PLAN_LIMIT)" \
	  --out "$(QUEUE_PARALLEL_PLAN_OUT)" \
	  --json-out "$(QUEUE_PARALLEL_PLAN_JSON_OUT)"

agent-loop-queue-recommendations:
	$(PYTHON) scripts/agent_loop.py queue-recommendations \
	  --out "$(QUEUE_RECOMMENDATIONS_OUT)" \
	  --json-out "$(QUEUE_RECOMMENDATIONS_JSON_OUT)" \
	  $(if $(filter 1 true yes,$(QUEUE_RECOMMENDATIONS_APPLY)),--apply,)

agent-loop-review-followup:
	@if [ -z "$(REVIEW)" ]; then \
	  echo "Usage: make agent-loop-review-followup REVIEW=reports/agent_loop/reviewer_output.md"; \
	  exit 1; \
	fi
	$(PYTHON) scripts/agent_loop.py review-followup \
	  --review "$(REVIEW)" \
	  --out "$(REVIEW_FOLLOWUP_OUT)" \
	  --tasks-dir "$(REVIEW_FOLLOWUP_DIR)"

agent-loop-review-ingest:
	$(PYTHON) scripts/agent_loop.py review-ingest \
	  $(if $(REVIEW),--review "$(REVIEW)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  --out "$(REVIEW_INGEST_OUT)" \
	  --followup-out "$(REVIEW_FOLLOWUP_OUT)" \
	  --tasks-dir "$(REVIEW_FOLLOWUP_DIR)"

agent-loop-decision-brief:
	$(PYTHON) scripts/agent_loop.py decision-brief \
	  $(if $(TASK),--task "$(TASK)",) \
	  $(if $(DECISION_BATCH),--batch "$(DECISION_BATCH)",) \
	  $(if $(DECISION_REVIEW_FOLLOWUPS),--review-followups "$(DECISION_REVIEW_FOLLOWUPS)",) \
	  --gate "$(GATE)" \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --out "$(DECISION_OUT)"

agent-loop-promote-draft:
	$(PYTHON) scripts/agent_loop.py promote-draft \
	  --out "$(PROMOTE_OUT)"

agent-loop-gate-status:
	$(PYTHON) scripts/agent_loop.py gate-status \
	  $(if $(TASK),--task "$(TASK)",) \
	  $(if $(DECISION_BATCH),--batch "$(DECISION_BATCH)",) \
	  $(if $(DECISION_REVIEW_FOLLOWUPS),--review-followups "$(DECISION_REVIEW_FOLLOWUPS)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --out "$(GATE_STATUS_OUT)"

agent-loop-claim-audit:
	$(PYTHON) scripts/agent_loop.py claim-audit \
	  $(if $(CLAIM_TEXT),--text "$(CLAIM_TEXT)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --out "$(CLAIM_AUDIT_OUT)"

agent-loop-privacy-audit-output:
	$(PYTHON) scripts/agent_loop.py privacy-audit-output \
	  --path "$(PRIVACY_AUDIT_PATH)" \
	  --out "$(PRIVACY_AUDIT_OUT)"

agent-loop-auto-pass:
	$(PYTHON) scripts/agent_loop.py auto-pass-check \
	  $(if $(TASK),--task "$(TASK)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  $(if $(CLAIM_TEXT),--claim-text "$(CLAIM_TEXT)",) \
	  $(if $(RUN_VALIDATION),--run-validation,) \
	  $(if $(AUTO_PASS_STRICT),--strict,) \
	  --profile "$(AUTO_PASS_PROFILE)" \
	  --out "$(AUTO_PASS_OUT)"

agent-loop-dashboard:
	$(PYTHON) scripts/agent_loop.py dashboard \
	  $(if $(TASK),--task "$(TASK)",) \
	  $(if $(DECISION_BATCH),--batch "$(DECISION_BATCH)",) \
	  $(if $(DECISION_REVIEW_FOLLOWUPS),--review-followups "$(DECISION_REVIEW_FOLLOWUPS)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --out "$(DASHBOARD_OUT)"

agent-loop-mcp-config:
	$(PYTHON) scripts/agent_loop.py mcp-config \
	  --out "$(MCP_CONFIG_OUT)"

agent-loop-safe-fix:
	$(PYTHON) scripts/agent_loop.py safe-fix \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  $(if $(SAFE_FIX_APPLY),--apply,) \
	  --out "$(SAFE_FIX_OUT)"

agent-loop-approval-packet:
	$(PYTHON) scripts/agent_loop.py approval-packet \
	  $(if $(TASK),--task "$(TASK)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  $(if $(CLAIM_TEXT),--claim-text "$(CLAIM_TEXT)",) \
	  $(if $(RUN_VALIDATION),--run-validation,) \
	  --out "$(APPROVAL_PACKET_OUT)"

agent-loop-propose-queue-plan:
	$(PYTHON) scripts/agent_loop.py propose-queue-plan \
	  --task-id "$(DRAFT_TASK_ID)" \
	  $(if $(TASK_BRIEF),--task-brief "$(TASK_BRIEF)",) \
	  --out "$(QUEUE_PLAN_PATCH_OUT)"

agent-loop-issue-scan:
	$(PYTHON) scripts/agent_loop.py issue-scan \
	  --limit "$(LIMIT)" \
	  --out-json "$(ISSUE_STATE)" \
	  --out "$(ISSUE_TRIAGE_OUT)"

agent-loop-maintenance-plan:
	$(PYTHON) scripts/agent_loop.py maintenance-plan \
	  --limit "$(LIMIT)" \
	  --out "$(MAINTENANCE_PLAN_OUT)" \
	  --json-out "$(MAINTENANCE_PLAN_JSON)" \
	  --tasks-dir "$(ISSUE_QUEUE_TASKS_DIR)"

agent-loop-issue-close:
	@if [ -z "$(ISSUE)" ] || [ -z "$(COMMENT_FILE)" ]; then \
	  echo "Usage: make agent-loop-issue-close ISSUE=123 COMMENT_FILE=reports/agent_loop/issue-close-123.md CONFIRM_HUMAN_APPROVED=1"; \
	  exit 1; \
	fi
	$(PYTHON) scripts/agent_loop.py human-gated-exec \
	  --action issue-close \
	  --issue "$(ISSUE)" \
	  --comment-file "$(COMMENT_FILE)" \
	  --triage-plan "$(MAINTENANCE_PLAN_JSON)" \
	  $(if $(CONFIRM_HUMAN_APPROVED),--confirm-human-approved,) \
	  --out "$(HUMAN_GATED_EXEC_OUT)"

agent-loop-pr-body:
	$(PYTHON) scripts/agent_loop.py pr-body \
	  $(if $(TASK),--task "$(TASK)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(BRANCH),--branch "$(BRANCH)",) \
	  $(if $(ISSUE),--issue "$(ISSUE)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --out "$(PR_BODY_OUT)"

agent-loop-review-plan:
	$(PYTHON) scripts/agent_loop.py review-plan \
	  $(if $(REVIEW),--review "$(REVIEW)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  --out "$(REVIEW_PLAN_OUT)"

agent-loop-stale-reports:
	$(PYTHON) scripts/agent_loop.py stale-reports \
	  --max-age-days "$(STALE_MAX_AGE_DAYS)" \
	  $(if $(STALE_APPLY),--apply,) \
	  --out "$(STALE_REPORTS_OUT)"

agent-loop-context-pack:
	$(PYTHON) scripts/agent_loop.py context-pack \
	  $(if $(TASK),--task "$(TASK)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --out "$(CONTEXT_PACK_OUT)"

agent-loop-architecture-brief:
	$(PYTHON) scripts/agent_loop.py architecture-brief \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --out "$(ARCHITECTURE_BRIEF_OUT)"

agent-loop-ship-simulate:
	$(PYTHON) scripts/agent_loop.py ship-simulate \
	  $(if $(TASK),--task "$(TASK)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(BRANCH),--branch "$(BRANCH)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --out "$(SHIP_SIMULATION_OUT)"

agent-loop-auto-ship-prepare:
	$(PYTHON) scripts/agent_loop.py auto-ship-prepare \
	  $(if $(AUTO_SHIP_ISSUE),--issue "$(AUTO_SHIP_ISSUE)",) \
	  $(if $(AUTO_SHIP_TARGET_BRANCH),--target-branch "$(AUTO_SHIP_TARGET_BRANCH)",) \
	  --type "$(AUTO_SHIP_BRANCH_TYPE)" \
	  --slug "$(AUTO_SHIP_SLUG)" \
	  $(if $(AUTO_SHIP_CREATE_BRANCH),--create-branch,) \
	  $(if $(CONFIRM_HUMAN_APPROVED),--confirm-human-approved,) \
	  --ttl "$(AUTO_SHIP_TTL)" \
	  $(if $(AUTO_SHIP_REAL_EVAL),--real-eval "$(AUTO_SHIP_REAL_EVAL)",) \
	  $(if $(AUTO_SHIP_DRAFT),--draft,) \
	  $(if $(AUTO_SHIP_READY),--ready,) \
	  $(if $(AUTO_SHIP_DRY_RUN),--dry-run,) \
	  $(if $(AUTO_SHIP_NO_DRY_RUN),--no-dry-run,) \
	  --out "$(AUTO_SHIP_PREPARE_OUT)"

agent-loop-auto-ship-plan:
	$(PYTHON) scripts/agent_loop.py auto-ship-plan \
	  $(if $(TASK),--task "$(TASK)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(BRANCH),--branch "$(BRANCH)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --ttl "$(AUTO_SHIP_TTL)" \
	  $(if $(AUTO_SHIP_REAL_EVAL),--real-eval "$(AUTO_SHIP_REAL_EVAL)",) \
	  $(if $(AUTO_SHIP_DRAFT),--draft,) \
	  $(if $(AUTO_SHIP_DRY_RUN),--dry-run,) \
	  --out "$(AUTO_SHIP_PLAN_OUT)"

agent-loop-gate-brief:
	$(PYTHON) scripts/agent_loop.py gate-brief \
	  --gate "$(GATE)" \
	  $(if $(TASK),--task "$(TASK)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --out "$(GATE_BRIEF_OUT)"

agent-loop-manifest:
	$(PYTHON) scripts/agent_loop.py manifest \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --source-command "$(MANIFEST_COMMAND)" \
	  $(if $(MANIFEST_OUTPUT),--output "$(MANIFEST_OUTPUT)",) \
	  --out "$(MANIFEST_OUT)"

agent-loop-pr-body-check:
	$(PYTHON) scripts/agent_loop.py pr-body-check \
	  --body "$(PR_BODY_OUT)" \
	  $(if $(BRANCH),--branch "$(BRANCH)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --out "$(PR_BODY_CHECK_OUT)"

agent-loop-ci-ingest:
	$(PYTHON) scripts/agent_loop.py ci-ingest \
	  $(if $(CI_LOG),--log "$(CI_LOG)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  --out "$(CI_INGEST_OUT)" \
	  --tasks-dir "$(CI_FOLLOWUP_DIR)"

agent-loop-stacked-risk:
	@if [ -z "$(BRANCH)" ]; then \
	  echo "Usage: make agent-loop-stacked-risk BRANCH=chore/issue-123-example [PR_STATE=reports/agent_loop/pr_state.json]"; \
	  exit 1; \
	fi
	$(PYTHON) scripts/agent_loop.py stacked-risk \
	  --branch "$(BRANCH)" \
	  $(if $(PR_STATE),--pr-json "$(PR_STATE)",) \
	  --out "$(STACKED_RISK_OUT)"

agent-loop-patch-proposal:
	$(PYTHON) scripts/agent_loop.py patch-proposal \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  $(if $(PATCH_REVIEW_PLAN),--review-plan "$(PATCH_REVIEW_PLAN)",) \
	  --out "$(PATCH_PROPOSAL_OUT)"

agent-loop-adr-reserve:
	@if [ -z "$(ADR_TITLE)" ]; then \
	  echo "Usage: make agent-loop-adr-reserve ADR_TITLE='Decision title'"; \
	  exit 1; \
	fi
	$(PYTHON) scripts/agent_loop.py adr-reserve \
	  --title "$(ADR_TITLE)" \
	  --out "$(ADR_RESERVATION_OUT)" \
	  --draft-out "$(ADR_DRAFT_OUT)"

agent-loop-dashboard-html:
	$(PYTHON) scripts/agent_loop.py dashboard-html \
	  $(if $(TASK),--task "$(TASK)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --out "$(DASHBOARD_HTML_OUT)"

agent-loop-ship-command-pack:
	$(PYTHON) scripts/agent_loop.py ship-command-pack \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(BRANCH),--branch "$(BRANCH)",) \
	  --out "$(SHIP_COMMANDS_OUT)"

agent-loop-apply-queue-plan:
	$(PYTHON) scripts/agent_loop.py apply-queue-plan \
	  $(if $(CONFIRM_HUMAN_APPROVED),--confirm-human-approved,) \
	  --out "$(APPLY_QUEUE_PLAN_OUT)"

agent-loop-review-threads:
	$(PYTHON) scripts/agent_loop.py review-threads \
	  $(if $(REVIEW_THREADS_JSON),--threads-json "$(REVIEW_THREADS_JSON)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  --out "$(REVIEW_THREADS_OUT)"

agent-loop-ci-summary:
	$(PYTHON) scripts/agent_loop.py ci-summary \
	  $(if $(CI_LOG),--log "$(CI_LOG)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  --out "$(CI_SUMMARY_OUT)"

agent-loop-readiness-score:
	$(PYTHON) scripts/agent_loop.py readiness-score \
	  $(if $(TASK),--task "$(TASK)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(BRANCH),--branch "$(BRANCH)",) \
	  $(if $(PR_BODY_OUT),--body "$(PR_BODY_OUT)",) \
	  $(if $(CLAIM_TEXT),--claim-text "$(CLAIM_TEXT)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --out "$(READINESS_SCORE_OUT)"

agent-loop-artifact-freshness:
	$(PYTHON) scripts/agent_loop.py artifact-freshness \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --max-age-days "$(STALE_MAX_AGE_DAYS)" \
	  --out "$(STALE_REPORTS_OUT)"

agent-loop-review-patch-plan:
	$(PYTHON) scripts/agent_loop.py review-patch-plan \
	  $(if $(REVIEW),--review "$(REVIEW)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --review-out "$(REVIEW_PLAN_OUT)" \
	  --patch-out "$(PATCH_PROPOSAL_OUT)"

agent-loop-queue-plan-sync:
	$(PYTHON) scripts/agent_loop.py queue-plan-sync \
	  $(if $(TASK_BRIEF),--task-brief "$(TASK_BRIEF)",) \
	  --task-id "$(DRAFT_TASK_ID)" \
	  --out "$(QUEUE_PLAN_PATCH_OUT)"

agent-loop-dependency-graph:
	@if [ -z "$(BRANCH)" ]; then \
	  echo "Usage: make agent-loop-dependency-graph BRANCH=chore/issue-123-example [PR_STATE=reports/agent_loop/pr_state.json]"; \
	  exit 1; \
	fi
	$(PYTHON) scripts/agent_loop.py dependency-graph \
	  --branch "$(BRANCH)" \
	  $(if $(PR_STATE),--pr-json "$(PR_STATE)",) \
	  --out "$(DEPENDENCY_GRAPH_OUT)"

agent-loop-branch-issue-hygiene:
	$(PYTHON) scripts/agent_loop.py branch-issue-hygiene \
	  $(if $(BRANCH),--branch "$(BRANCH)",) \
	  $(if $(TASK),--task "$(TASK)",) \
	  $(if $(PR_BODY_OUT),--body "$(PR_BODY_OUT)",) \
	  --out "$(BRANCH_ISSUE_HYGIENE_OUT)"

agent-loop-integration-pack:
	$(PYTHON) scripts/agent_loop.py integration-pack \
	  --out "$(INTEGRATION_PACK_OUT)"

agent-loop-scheduled-status:
	$(PYTHON) scripts/agent_loop.py scheduled-status \
	  --out "$(SCHEDULE_CONFIG_OUT)"

agent-loop-validation-history:
	$(PYTHON) scripts/agent_loop.py validation-history \
	  --history "$(VALIDATION_HISTORY)" \
	  --out "$(VALIDATION_HISTORY_OUT)"

agent-loop-privacy-regression:
	$(PYTHON) scripts/agent_loop.py privacy-regression \
	  --out "$(PRIVACY_REGRESSION_OUT)"

agent-loop-claim-policy:
	$(PYTHON) scripts/agent_loop.py claim-policy \
	  $(if $(CLAIM_TEXT),--text "$(CLAIM_TEXT)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --out "$(CLAIM_POLICY_OUT)"

agent-loop-architecture-decision:
	$(PYTHON) scripts/agent_loop.py architecture-decision \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --out "$(ARCHITECTURE_DECISION_OUT)"

agent-loop-workset-recommend:
	$(PYTHON) scripts/agent_loop.py workset-recommend \
	  $(if $(DECISION_BATCH),--batch "$(DECISION_BATCH)",) \
	  --tasks-dir reports/agent_loop/codex_tasks \
	  --out "$(WORKSET_RECOMMENDATION_OUT)"

agent-loop-automation-coverage:
	$(PYTHON) scripts/agent_loop.py automation-coverage \
	  --out "$(AUTOMATION_COVERAGE_OUT)"

agent-loop-active-start:
	$(PYTHON) scripts/agent_loop.py active-start \
	  --topology "$(ACTIVE_TOPOLOGY)" \
	  --agent-mix "$(ACTIVE_AGENT_MIX)" \
	  --lease-ttl-minutes "$(ACTIVE_LEASE_TTL_MINUTES)" \
	  $(if $(TASK),--task "$(TASK)",) \
	  $(if $(ISSUE),--issue "$(ISSUE)",) \
	  $(if $(BRANCH),--branch "$(BRANCH)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  $(if $(CLAIM_TEXT),--claim-text "$(CLAIM_TEXT)",) \
	  $(if $(PR_BODY_OUT),--pr-body "$(PR_BODY_OUT)",) \
	  $(if $(DECISION_BATCH),--batch "$(DECISION_BATCH)",) \
	  $(if $(filter 1 true yes,$(ACTIVE_REPAIR_BRANCH)),--repair-branch,) \
	  --repair-branch-type "$(ACTIVE_REPAIR_BRANCH_TYPE)" \
	  --repair-slug "$(ACTIVE_REPAIR_SLUG)" \
	  --repair-title "$(ACTIVE_REPAIR_TITLE)" \
	  --out "$(ACTIVE_START_OUT)"
	$(if $(filter 1 true yes,$(ACTIVE_START_RUNNER)),$(MAKE) agent-loop-active-codex-runner ACTIVE_CODEX_EXECUTE="$(ACTIVE_START_RUNNER_EXECUTE)",)

agent-loop-active-codex-runner:
	$(PYTHON) scripts/agent_loop.py active-codex-runner \
	  $(if $(filter 1 true yes,$(ACTIVE_CODEX_EXECUTE)),--execute,--dry-run) \
	  --codex-executable "$(ACTIVE_CODEX_EXECUTABLE)" \
	  --auth-mode "$(ACTIVE_CODEX_AUTH_MODE)" \
	  --sandbox "$(ACTIVE_CODEX_SANDBOX)" \
	  --read-agent "$(ACTIVE_READ_AGENT)" \
	  --write-agent "$(ACTIVE_WRITE_AGENT)" \
	  --runner "$(ACTIVE_RUNNER)" \
	  --max-parallel "$(ACTIVE_CODEX_MAX_PARALLEL)" \
	  --timeout-seconds "$(ACTIVE_CODEX_TIMEOUT_SECONDS)" \
	  --max-commands-per-session "$(ACTIVE_CODEX_MAX_COMMANDS_PER_SESSION)" \
	  --model "$(ACTIVE_CODEX_MODEL)" \
	  $(if $(ACTIVE_CODEX_SESSIONS),--sessions "$(ACTIVE_CODEX_SESSIONS)",) \
	  $(if $(filter 1 true yes,$(ACTIVE_CODEX_RECORD_GATE_HEARTBEATS)),--record-gate-heartbeats,) \
	  --runs-dir "$(ACTIVE_CODEX_RUNS_DIR)" \
	  --state "$(ACTIVE_CODEX_RUNNER_STATE)" \
	  --out "$(ACTIVE_CODEX_RUNNER_OUT)"

agent-loop-active-auto-loop:
	$(PYTHON) scripts/agent_loop.py active-auto-loop \
	  --topology "$(ACTIVE_TOPOLOGY)" \
	  --agent-mix "$(ACTIVE_AGENT_MIX)" \
	  --lease-ttl-minutes "$(ACTIVE_LEASE_TTL_MINUTES)" \
	  --max-iterations "$(ACTIVE_AUTO_LOOP_MAX_ITERATIONS)" \
	  --auto-max-iterations-cap "$(ACTIVE_AUTO_LOOP_AUTO_MAX_ITERATIONS)" \
	  $(if $(ACTIVE_AUTO_LOOP_TARGET_COMPLETED_COUNT),--target-completed-count "$(ACTIVE_AUTO_LOOP_TARGET_COMPLETED_COUNT)",) \
	  $(if $(filter 1 true yes,$(ACTIVE_AUTO_LOOP_EXECUTE_RUNNER)),--execute-runner,) \
	  $(if $(filter 1 true yes,$(ACTIVE_AUTO_LOOP_EXECUTE_SHIP)),--execute-ship,) \
	  $(if $(filter 1 true yes,$(ACTIVE_AUTO_LOOP_AUTO_REPAIR)),--auto-repair,--no-auto-repair) \
	  $(if $(TASK),--task "$(TASK)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",) \
	  $(if $(CLAIM_TEXT),--claim-text "$(CLAIM_TEXT)",) \
	  $(if $(PR_BODY_OUT),--pr-body "$(PR_BODY_OUT)",) \
	  $(if $(DECISION_BATCH),--batch "$(DECISION_BATCH)",) \
	  $(if $(filter 1 true yes,$(ACTIVE_REPAIR_BRANCH)),--repair-branch,) \
	  --repair-branch-type "$(ACTIVE_REPAIR_BRANCH_TYPE)" \
	  --repair-slug "$(ACTIVE_REPAIR_SLUG)" \
	  --repair-title "$(ACTIVE_REPAIR_TITLE)" \
	  --codex-executable "$(ACTIVE_CODEX_EXECUTABLE)" \
	  --auth-mode "$(ACTIVE_CODEX_AUTH_MODE)" \
	  --sandbox "$(ACTIVE_CODEX_SANDBOX)" \
	  --read-agent "$(ACTIVE_READ_AGENT)" \
	  --write-agent "$(ACTIVE_WRITE_AGENT)" \
	  --runner "$(ACTIVE_RUNNER)" \
	  --max-parallel "$(ACTIVE_CODEX_MAX_PARALLEL)" \
	  --timeout-seconds "$(ACTIVE_CODEX_TIMEOUT_SECONDS)" \
	  --max-commands-per-session "$(ACTIVE_CODEX_MAX_COMMANDS_PER_SESSION)" \
	  --model "$(ACTIVE_CODEX_MODEL)" \
	  $(if $(filter 1 true yes on,$(ACTIVE_LANE_AUTOTUNE)),--lane-autotune --lane-autotune-k "$(ACTIVE_LANE_AUTOTUNE_K)" --lane-autotune-fail-window "$(ACTIVE_LANE_AUTOTUNE_FAIL_WINDOW)" --lane-autotune-fail-min-sample "$(ACTIVE_LANE_AUTOTUNE_FAIL_MIN_SAMPLE)" --lane-autotune-fail-threshold "$(ACTIVE_LANE_AUTOTUNE_FAIL_THRESHOLD)" --lane-autotune-cooldown "$(ACTIVE_LANE_AUTOTUNE_COOLDOWN)",) \
	  --state "$(ACTIVE_AUTO_LOOP_STATE)" \
	  --out "$(ACTIVE_AUTO_LOOP_OUT)"

시작:
	$(MAKE) agent-loop-queue-parallel-plan \
	  QUEUE_PARALLEL_PLAN_LIMIT="$(ACTIVE_AUTO_LOOP_AUTO_MAX_ITERATIONS)"
	$(MAKE) agent-loop-queue-recommendations
	$(MAKE) agent-loop-active-auto-loop \
	  ACTIVE_AUTO_LOOP_MAX_ITERATIONS="$(if $(filter 1 true yes,$(START_INFINITE)),0,$(START_TASK_LIMIT))" \
	  ACTIVE_AUTO_LOOP_AUTO_MAX_ITERATIONS="$(START_TASK_ATTEMPT_LIMIT)" \
	  ACTIVE_AUTO_LOOP_TARGET_COMPLETED_COUNT="$(if $(filter 1 true yes,$(START_INFINITE)),,$(START_TASK_LIMIT))" \
	  ACTIVE_RUNNER="$(ACTIVE_RUNNER)" \
	  ACTIVE_AUTO_LOOP_EXECUTE_RUNNER=1 \
	  ACTIVE_AUTO_LOOP_EXECUTE_SHIP=0 \
	  ACTIVE_AUTO_LOOP_AUTO_REPAIR=1

# ADR 0088 (P1) / ADR 0090 (P2.0→D-minus): opt-in staging self-ship lane. Composes
# the byte-identical `시작` loop (EXECUTE_SHIP=0, unchanged) with the ISOLATED
# staging-ship module as a post step. D-minus scope: verify the env-isolation
# enforcement model + live protection-verify + DEFINE the manifest CONTRACT only —
# _staging_ship.py reads ship_manifest.json IF one exists (single-consumption), else
# falls back to --source, else blocks on user. The manifest EMISSION (the loop
# auto-dropping a manifest at local-gate-complete) is DEFERRED to P2.2, where it
# belongs with the real ship: the D-minus loop runs EXECUTE_SHIP=0 so the gated
# change is never committed, making an emitted source_sha=HEAD meaningless. The loop
# sub-make therefore receives NO ship signal at all — a PREFIX-based strip unsets
# EVERY inherited BIDMATE_SHIP_* var (not a fixed allowlist, so a future/unknown
# BIDMATE_SHIP_* secret can never leak into the workspace-write loop process) as
# defence-in-depth, EXCEPT the control signal BIDMATE_SHIP_KILL_SWITCH which is
# pre-checked above and must stay honorable. The autonomous live MERGE orchestration
# (merge token / cap store plumbing) is DEFERRED to P2.2.
# Mutually exclusive with `make ship-arm` (fail-closed on .claude/.ship-armed).
시작-ship:
	@if [ -f .claude/.ship-armed ]; then \
	  echo "ERROR: make ship-arm is armed; 시작-ship and ship-arm are mutually exclusive (ADR 0088)"; \
	  exit 1; \
	fi
	@if { [ -n "$$BIDMATE_SHIP_KILL_SWITCH" ] && [ "$$BIDMATE_SHIP_KILL_SWITCH" != "0" ]; } || [ -f "$(ACTIVE_SHIP_STATE_DIR)/KILL" ]; then \
	  echo "ERROR: staging self-ship kill-switch engaged (BIDMATE_SHIP_KILL_SWITCH or $(ACTIVE_SHIP_STATE_DIR)/KILL); aborting before the loop phase"; \
	  exit 1; \
	fi
	@for v in $$(env | sed -n 's/^\(BIDMATE_SHIP_[A-Za-z0-9_]*\)=.*/\1/p'); do \
	  [ "$$v" = "BIDMATE_SHIP_KILL_SWITCH" ] && continue; \
	  unset "$$v"; \
	done; \
	$(MAKE) 시작
	$(PYTHON) scripts/_staging_ship.py \
	  --repo-root "." \
	  --state-dir "$(ACTIVE_SHIP_STATE_DIR)" \
	  --manifest-dir "$(ACTIVE_SHIP_STATE_DIR)" \
	  $(if $(SHIP_SOURCE),--source "$(SHIP_SOURCE)",) \
	  $(if $(SHIP_DAY),--day "$(SHIP_DAY)",)

agent-loop-human-gated-exec:
	@if [ -z "$(HUMAN_GATED_ACTION)" ]; then \
	  echo "Usage: make agent-loop-human-gated-exec HUMAN_GATED_ACTION=push|pr-create|pr-ready|pr-merge|pr-close|branch-delete|force-push CONFIRM_HUMAN_APPROVED=1"; \
	  exit 1; \
	fi
	$(PYTHON) scripts/agent_loop.py human-gated-exec \
	  --action "$(HUMAN_GATED_ACTION)" \
	  $(if $(CONFIRM_HUMAN_APPROVED),--confirm-human-approved,) \
	  $(if $(HUMAN_GATED_DRY_RUN),--dry-run,) \
	  $(if $(BRANCH),--branch "$(BRANCH)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(PR_BODY_OUT),--body "$(PR_BODY_OUT)",) \
	  $(if $(PR_BASE),--base "$(PR_BASE)",) \
	  $(if $(PR_TITLE),--title "$(PR_TITLE)",) \
	  $(if $(PR_READY),--ready,) \
	  $(if $(CONFIRM_REVIEW_GATE_PASSED),--confirm-review-gate-passed,) \
	  $(if $(CONFIRM_DEPENDENTS_REVIEWED),--confirm-dependents-reviewed,) \
	  $(if $(CONFIRM_FORCE_WITH_LEASE),--confirm-force-with-lease,) \
	  --out "$(HUMAN_GATED_EXEC_OUT)"

agent-loop-loop-state:
	$(PYTHON) scripts/agent_loop.py loop-state \
	  $(if $(TASK),--task "$(TASK)",) \
	  $(if $(DECISION_BATCH),--batch "$(DECISION_BATCH)",) \
	  $(if $(DECISION_REVIEW_FOLLOWUPS),--review-followups "$(DECISION_REVIEW_FOLLOWUPS)",) \
	  $(if $(PR),--pr "$(PR)",) \
	  $(if $(CHANGED_FILES),--changed-files "$(CHANGED_FILES)",--from-git) \
	  --out "$(LOOP_STATE_OUT)"

agent-loop-map:
	$(PYTHON) scripts/agent_loop.py map

agent-loop-mcp:
	$(PYTHON) scripts/agent_loop_mcp.py

# F2 (#853): local Qdrant container for the production HTTP server
# integration test. Image pin is in docker-compose.qdrant.yml.
# Default workflow: `make qdrant-up && make test-qdrant-integration && make qdrant-down`.
.PHONY: qdrant-up qdrant-down test-qdrant-integration
qdrant-up:
	docker compose -f docker-compose.qdrant.yml up -d
	@echo "Qdrant integration container starting; healthcheck polls /healthz on :6333."

qdrant-down:
	docker compose -f docker-compose.qdrant.yml down -v

test-qdrant-integration:
	$(PYTHON) -m pytest tests/test_qdrant_integration.py -m qdrant_integration -q

# Run the FastAPI demo locally. Requires data/index to exist
# (run `make index` first). See docs/operations/api-demo.md for details.
api:
	$(PYTHON) -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Build and run the demo container. The entrypoint builds the index on
# first start if data/index is empty inside the container.
api-docker:
	docker build -t bidmate-demo .
	docker run --rm -p 8000:8000 bidmate-demo

# Run the Streamlit live demo UI locally on http://localhost:8501.
# Requires data/index to exist (run `make index` first).
demo:
	$(PYTHON) -m streamlit run demo/streamlit_app.py

# Headless Playwright UI smoke for the Streamlit demo (issue #1790). Boots
# `streamlit run` on :8501 on the demo's real default index backend (chroma,
# ADR 0081), asserts the H1 + the three headline pipeline presets + the
# "Run query" button, and writes a full-page screenshot to
# reports/ui_smoke/demo.png (gitignored). Requires `npm install` (playwright,
# + `npx playwright install chromium`), chromadb (requirements.txt), and a
# prebuilt index (`make index`). Pass PYTHON=.venv/bin/python for a venv.
ui-smoke:
	PYTHON=$(PYTHON) node scripts/ui_smoke.mjs

# Run the demo container with the Streamlit UI on :8501 (and FastAPI on
# :8000 alongside). See docs/operations/deployment.md for Fly.io / HF Spaces.
demo-docker:
	docker build -t bidmate-demo .
	docker run --rm -p 8000:8000 -p 8501:8501 -e BIDMATE_DEMO_MODE=both bidmate-demo

# ---------------------------------------------------------------------------
# Real-data eval cycle (private; ADR 0005 commit boundary). Requires
# local/private inputs resolved by scripts/real_eval_paths.py. None of these
# private inputs, caches, indexes, or generated reports are committed.
# ---------------------------------------------------------------------------

# Show the local/private path inventory for the current environment. This is
# read-only and never prints private file contents.
real-eval-inventory:
	$(PYTHON) scripts/real_eval_paths.py inventory

# Validate required local/private inputs. Missing cache/index/report dirs are
# reported as regenerable/output, not as hard failures.
real-eval-check:
	$(PYTHON) scripts/real_eval_paths.py check

REAL_EVAL_ROOT ?= .
REAL100_V2_CONFIG ?= data/private/real100_v2/real_config_v2.local.yaml
REAL100_V2_CHECKPOINT_DIR ?= data/index/real100_v2/_parse_checkpoints
REAL100_V2_INDEX_DIR ?= data/index/real100_v2_checkpoint_minilm_pageaware
REAL100_V2_CHECKPOINT_BUILD_DIR ?= $(if $(filter /%,$(REAL100_V2_CHECKPOINT_DIR)),$(REAL100_V2_CHECKPOINT_DIR),$(REAL_EVAL_ROOT)/$(REAL100_V2_CHECKPOINT_DIR))
REAL100_V2_INDEX_BUILD_DIR ?= $(if $(filter /%,$(REAL100_V2_INDEX_DIR)),$(REAL100_V2_INDEX_DIR),$(REAL_EVAL_ROOT)/$(REAL100_V2_INDEX_DIR))
REAL100_V2_REPORT_DIR ?= reports/real100_v2
REAL100_V2_CHROMA_REPORT_DIR ?= reports/real100_v2_chroma
REAL100_V2_CHROMA_LLM_REPORT_DIR ?= reports/real100_v2_chroma_llm
REAL100_V2_JUDGE_INPUT_REPORT_DIR ?= $(REAL100_V2_CHROMA_LLM_REPORT_DIR)
REAL100_V2_RATIONALITY_INPUT_REPORT_DIR ?= $(REAL100_V2_CHROMA_LLM_REPORT_DIR)
REAL100_V2_JUDGE_BACKEND ?= stub
REAL100_V2_RAGAS_JUDGE_BACKEND ?= stub
REAL100_V2_RATIONALITY_BACKEND ?= stub
REAL100_V2_JUDGE_CACHE_DIR ?= reports/judge_cache/real100_v2
REAL100_V2_RATIONALITY_CACHE_DIR ?= reports/rationality_cache/real100_v2
REAL100_V2_RATIONALITY_EXPECT_FULL_TRACE ?= 1
REAL100_V2_EMBEDDING_BACKEND ?= sentence-transformers
REAL100_V2_EMBEDDING_MODEL ?= sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
REAL100_V2_CHUNKING_STRATEGY ?= section
REAL100_V2_SYNTHESIS_BACKEND ?= local_openai_compatible
REAL100_V2_TRACE_FULL ?= 1

# T-2026-0028 and newer claim-bearing private eval work must use the v2
# aggregate surface. These targets only inspect v2 paths; they do not rebuild or
# overwrite the private v2 index.
real-eval-v2-inventory:
	REAL_EVAL_CONFIG="$(REAL100_V2_CONFIG)" \
	  REAL_EVAL_INDEX_DIR="$(REAL100_V2_INDEX_DIR)" \
	  REAL_EVAL_REPORT_DIR="$(REAL100_V2_REPORT_DIR)" \
	  $(PYTHON) scripts/real_eval_paths.py inventory

real-eval-v2-check:
	REAL_EVAL_CONFIG="$(REAL100_V2_CONFIG)" \
	  REAL_EVAL_INDEX_DIR="$(REAL100_V2_INDEX_DIR)" \
	  REAL_EVAL_REPORT_DIR="$(REAL100_V2_REPORT_DIR)" \
	  $(PYTHON) scripts/real_eval_paths.py check
	@$(MAKE) -s experiment-report-html

real-eval-v2-guard:
	$(PYTHON) scripts/check_real100_v2_only.py

real-eval-v2-checkpoint-index:
	$(PYTHON) scripts/build_index_from_parse_checkpoints.py \
	  --checkpoint_dir "$(REAL100_V2_CHECKPOINT_BUILD_DIR)" \
	  --output_dir "$(REAL100_V2_INDEX_BUILD_DIR)" \
	  --embedding_backend "$(REAL100_V2_EMBEDDING_BACKEND)" \
	  --model "$(REAL100_V2_EMBEDDING_MODEL)" \
	  --chunking_strategy "$(REAL100_V2_CHUNKING_STRATEGY)"

real-eval-v2-chroma: real-eval-v2-checkpoint-index
	@eval "$$(REAL_EVAL_CONFIG="$(REAL100_V2_CONFIG)" \
	  REAL_EVAL_INDEX_DIR="$(REAL100_V2_INDEX_DIR)" \
	  REAL_EVAL_REPORT_DIR="$(REAL100_V2_CHROMA_REPORT_DIR)" \
	  $(PYTHON) scripts/real_eval_paths.py inventory --format shell)" && \
	mkdir -p "$$REAL_EVAL_RESOLVED_REPORT_DIR" && \
	BIDMATE_INDEX_BACKEND=chroma $(PYTHON) eval/run_eval.py \
	  --index_dir "$$REAL_EVAL_RESOLVED_INDEX_DIR" \
	  --output_dir "$$REAL_EVAL_RESOLVED_REPORT_DIR" \
	  --config "$$REAL_EVAL_RESOLVED_CONFIG"

real-eval-v2-chroma-llm:
	@test -n "$${BIDMATE_SYNTHESIS_BASE_URL:-}" || { echo "ERROR: BIDMATE_SYNTHESIS_BASE_URL must point to an OpenAI-compatible server; local runs use http://127.0.0.1:11434/v1, external runs also need BIDMATE_EGRESS_PROFILE approval." >&2; exit 2; }
	@test -n "$${BIDMATE_SYNTHESIS_MODEL:-}" || { echo "ERROR: BIDMATE_SYNTHESIS_MODEL must name the local-small synthesis model." >&2; exit 2; }
	@test -n "$${BIDMATE_SYNTHESIS_API_KEY:-}" || { echo "ERROR: BIDMATE_SYNTHESIS_API_KEY must be set; Ollama accepts a placeholder such as 'ollama'." >&2; exit 2; }
	@$(PYTHON) -c "import openai" || { echo "ERROR: openai SDK missing; run pip install -r requirements-dev.txt." >&2; exit 2; }
	@$(MAKE) -s real-eval-v2-checkpoint-index
	@eval "$$(REAL_EVAL_CONFIG="$(REAL100_V2_CONFIG)" \
	  REAL_EVAL_INDEX_DIR="$(REAL100_V2_INDEX_DIR)" \
	  REAL_EVAL_REPORT_DIR="$(REAL100_V2_CHROMA_LLM_REPORT_DIR)" \
	  $(PYTHON) scripts/real_eval_paths.py inventory --format shell)" && \
	mkdir -p "$$REAL_EVAL_RESOLVED_REPORT_DIR" && \
	$(PYTHON) scripts/make_real100_v2_llm_baseline_config.py \
	  --config "$$REAL_EVAL_RESOLVED_CONFIG" \
	  --output "$$REAL_EVAL_RESOLVED_REPORT_DIR/real_config_v2_llm.local.yaml" && \
	echo "[INFO] Running LLM synthesis baseline with BIDMATE_SYNTHESIS_BACKEND=$(REAL100_V2_SYNTHESIS_BACKEND)" && \
	BIDMATE_INDEX_BACKEND=chroma BIDMATE_SYNTHESIS_BACKEND="$(REAL100_V2_SYNTHESIS_BACKEND)" BIDMATE_TRACE_FULL="$(REAL100_V2_TRACE_FULL)" $(PYTHON) eval/run_eval.py \
	  --index_dir "$$REAL_EVAL_RESOLVED_INDEX_DIR" \
	  --output_dir "$$REAL_EVAL_RESOLVED_REPORT_DIR" \
	  --config "$$REAL_EVAL_RESOLVED_REPORT_DIR/real_config_v2_llm.local.yaml"

real-eval-v2-judge:
	@eval "$$(REAL_EVAL_CONFIG="$(REAL100_V2_CONFIG)" \
	  REAL_EVAL_INDEX_DIR="$(REAL100_V2_INDEX_DIR)" \
	  REAL_EVAL_REPORT_DIR="$(REAL100_V2_JUDGE_INPUT_REPORT_DIR)" \
	  $(PYTHON) scripts/real_eval_paths.py inventory --format shell)" && \
	test -f "$$REAL_EVAL_RESOLVED_REPORT_DIR/eval_summary.json" || { echo "ERROR: missing $$REAL_EVAL_RESOLVED_REPORT_DIR/eval_summary.json. Run make real-eval-v2-chroma-llm first, or set REAL100_V2_JUDGE_INPUT_REPORT_DIR." >&2; exit 2; } && \
	mkdir -p "$(REAL100_V2_REPORT_DIR)" && \
	$(PYTHON) scripts/llm_judge.py \
	  --eval-summary "$$REAL_EVAL_RESOLVED_REPORT_DIR/eval_summary.json" \
	  --output "$$REAL_EVAL_RESOLVED_REPORT_DIR/judge.local.json" \
	  --out-aggregate "$(REAL100_V2_REPORT_DIR)/judge.aggregate.json" \
	  --backend "$(REAL100_V2_JUDGE_BACKEND)"

real-eval-v2-ragas-judge:
	@eval "$$(REAL_EVAL_CONFIG="$(REAL100_V2_CONFIG)" \
	  REAL_EVAL_INDEX_DIR="$(REAL100_V2_INDEX_DIR)" \
	  REAL_EVAL_REPORT_DIR="$(REAL100_V2_JUDGE_INPUT_REPORT_DIR)" \
	  $(PYTHON) scripts/real_eval_paths.py inventory --format shell)" && \
	test -f "$$REAL_EVAL_RESOLVED_REPORT_DIR/eval_summary.json" || { echo "ERROR: missing $$REAL_EVAL_RESOLVED_REPORT_DIR/eval_summary.json. Run make real-eval-v2-chroma-llm first, or set REAL100_V2_JUDGE_INPUT_REPORT_DIR." >&2; exit 2; } && \
	mkdir -p "$(REAL100_V2_REPORT_DIR)" && \
	$(PYTHON) eval/judges/llm_judge.py \
	  --eval-summary "$$REAL_EVAL_RESOLVED_REPORT_DIR/eval_summary.json" \
	  --output "$$REAL_EVAL_RESOLVED_REPORT_DIR/judge_ragas.local.json" \
	  --out-aggregate "$(REAL100_V2_REPORT_DIR)/judge_ragas.aggregate.json" \
	  --cache-dir "$(REAL100_V2_JUDGE_CACHE_DIR)" \
	  --backend "$(REAL100_V2_RAGAS_JUDGE_BACKEND)"

real-eval-v2-rationality-judge:
	@eval "$$(REAL_EVAL_CONFIG="$(REAL100_V2_CONFIG)" \
	  REAL_EVAL_INDEX_DIR="$(REAL100_V2_INDEX_DIR)" \
	  REAL_EVAL_REPORT_DIR="$(REAL100_V2_RATIONALITY_INPUT_REPORT_DIR)" \
	  $(PYTHON) scripts/real_eval_paths.py inventory --format shell)" && \
	test -f "$$REAL_EVAL_RESOLVED_REPORT_DIR/eval_summary.json" || { echo "ERROR: missing $$REAL_EVAL_RESOLVED_REPORT_DIR/eval_summary.json. Run make real-eval-v2-chroma-llm with BIDMATE_TRACE_FULL=1 first, or set REAL100_V2_RATIONALITY_INPUT_REPORT_DIR." >&2; exit 2; } && \
	mkdir -p "$(REAL100_V2_REPORT_DIR)" && \
	$(PYTHON) scripts/run_rationality_judge.py \
	  --eval-summary "$$REAL_EVAL_RESOLVED_REPORT_DIR/eval_summary.json" \
	  --output "$$REAL_EVAL_RESOLVED_REPORT_DIR/rationality.local.json" \
	  --out-aggregate "$(REAL100_V2_REPORT_DIR)/rationality.aggregate.json" \
	  --out-md "$(REAL100_V2_REPORT_DIR)/rationality.md" \
	  --traces-dir "$$REAL_EVAL_RESOLVED_REPORT_DIR/traces" \
	  --cache-dir "$(REAL100_V2_RATIONALITY_CACHE_DIR)" \
	  --backend "$(REAL100_V2_RATIONALITY_BACKEND)" \
	  $(if $(filter 1 true yes,$(REAL100_V2_RATIONALITY_EXPECT_FULL_TRACE)),--expect-full-trace,)

# Legacy real100/v1 targets are disabled until explicitly re-enabled by the
# maintainer. Future private eval tasks must use real100_v2 inventory/check and
# aggregate artifacts; reports/real100 and 221-case aggregates are archive-only.
real-eval:
	@echo "ERROR: legacy real100/v1 make real-eval is disabled. Use make real-eval-v2-check and reports/real100_v2 aggregate evidence." >&2
	@exit 2

# Legacy semantic real100/v1 target disabled with the same policy.
real-eval-minilm:
	@echo "ERROR: legacy real100_minilm/v1 target is disabled. Use real100_v2-only evidence until explicitly re-enabled." >&2
	@exit 2

# Legacy BGE-M3 real100/v1 target disabled with the same policy.
real-eval-semantic:
	@echo "ERROR: legacy real100_m3/v1 target is disabled. Use real100_v2-only evidence until explicitly re-enabled." >&2
	@exit 2

# Page-aware citation readiness variant for issue #1573. Keeps the canonical
# hashing real100 index untouched while rebuilding into a separate section-
# chunked index that can preserve PyMuPDF4LLM page sections on chunks.
real-eval-page-aware:
	CHUNKING_STRATEGY=section \
	  HWP_PDF_ARTIFACT_DIR=data/private/real100_v2/converted_pdfs \
	  BIDMATE_HWP_PDF_ARTIFACT_REUSE=1 \
	  REAL_EVAL_INDEX_DIR=data/index/real100_pageaware \
	  OUTPUT_DIR=outputs/real100_pageaware \
	  REAL_EVAL_REPORT_DIR=reports/real100_pageaware \
	  bash scripts/smoke_real.sh

# Render an aggregate-only markdown delta between the current
# real-data run and the committed baseline. Aggregate-only by
# construction; no per-case data is read or printed.
real-eval-delta:
	$(PYTHON) scripts/run_real_eval_delta.py

# Deliberate baseline bump. Reads the current eval_summary.json and
# writes BOTH the current baseline AND an append-only history archive
# entry. Aggregate-only (extractor enforces ADR 0005). Intended to run
# *after* a decision is made (PR merged, threshold tightened, etc.),
# not on every eval. Diff the result with `git diff` before committing.
#
# Pass STRICT=1 (or set BIDMATE_BASELINE_STRICT=1, issue #414) to escalate
# the provenance warnings (no eval-side provenance; eval/baseline SHA skew
# per issue #160; dirty worktree per issue #1148) to hard failures — for
# CI/pre-push or any gate that requires a self-consistent baseline.
# Pass ALLOW_DIRTY=1 (or BIDMATE_BASELINE_ALLOW_DIRTY=1) to override the
# dirty-worktree gate for a deliberate dirty baseline (#1148).
real-eval-baseline-update:
	$(PYTHON) scripts/write_real_eval_baseline.py $(if $(STRICT),--strict,) $(if $(ALLOW_DIRTY),--allow-dirty,)
	@$(MAKE) -s experiment-report-html

# Render the chronological real-data history table into
# docs/real-data/private-100-doc-experiments.md (between the
# real-eval-history-{start,end} markers). Aggregate-only.
real-eval-history-render:
	$(PYTHON) scripts/render_real_eval_history.py
	@$(MAKE) -s experiment-report-html

# Verify the rendered history table is up to date with committed
# aggregate snapshots. Suitable for pre-PR gating.
real-eval-history-check:
	$(PYTHON) scripts/render_real_eval_history.py --check

# Legacy real100/v1 judge orchestration disabled with the same policy as
# `real-eval` (real100->real100_v2 migration). The real100_v2 judge surface
# is `real-eval-v2-judge` (judge.local.json + judge.aggregate.json), layered
# on `real-eval-v2-chroma-llm`.
real-eval-with-judge:
	@echo "ERROR: legacy real100/v1 make real-eval-with-judge is disabled. Use make real-eval-v2-judge (after make real-eval-v2-chroma-llm) with reports/real100_v2 evidence." >&2
	@exit 2

# Case proposer cycle (ADR 0029). Two-stage human gate:
#   case-propose -> reports/proposed/proposed_cases.local.yaml (gitignored)
#   case-review  -> interactive walk; writes reviewed_cases.local.yaml
#   case-promote -> idempotent append of approved cases into
#                   eval/real_config.local.yaml.
# Default backend is `stub` (deterministic, no network). Set
# BIDMATE_CASE_PROPOSER_BACKEND=openai_compatible + BIDMATE_JUDGE_*
# vars for the live proposer (PR3 / not in PR2 scope).
case-propose:
	$(PYTHON) -m eval.case_proposer \
	  --metadata-csv data/data_list.csv \
	  --index-dir data/index/real100 \
	  --out reports/proposed/proposed_cases.local.yaml \
	  --real-config eval/real_config.local.yaml

# CSV-metadata backend (ADR 0048): emits up to 4 single-doc cases per
# seed row (one per metadata_field ∈ {agency, project, budget, deadline})
# with expected_terms populated verbatim from data_list.csv. Each case
# carries the metadata_field tag, so `by_metadata_field` in
# eval_summary.json (ADR 0048) buckets them automatically. Default
# n-seed-docs=25 yields up to 100 candidate cases — enough to cover the
# n=50 baseline target with margin after reviewer trimming. Output yaml
# is gitignored under reports/proposed/ per ADR 0005.
case-propose-metadata:
	$(PYTHON) -m eval.case_proposer \
	  --metadata-csv data/data_list.csv \
	  --index-dir data/index/real100 \
	  --out reports/proposed/proposed_cases.local.yaml \
	  --real-config eval/real_config.local.yaml \
	  --backend csv_metadata \
	  --n-seed-docs 25

case-review:
	$(PYTHON) scripts/case_proposer_review.py \
	  --proposed reports/proposed/proposed_cases.local.yaml \
	  --reviewed reports/proposed/reviewed_cases.local.yaml

case-promote:
	$(PYTHON) scripts/case_proposer_promote.py \
	  --reviewed reports/proposed/reviewed_cases.local.yaml \
	  --real-config eval/real_config.local.yaml

clean:
	rm -rf data/index outputs reports

# ---------------------------------------------------------------------------
# Auto-ship pipeline (Stop hook driven). Single-shot: every cycle disarms.
#
# Arming variables (env):
#   TTL          duration string (default 2h). Examples: 30m, 2h, 90m.
#   REAL_EVAL    auto (default), skip, async. Deprecated no-op since the §5b
#                PR-body cascade was removed (ADR 0084); accepted for compat.
#   DRAFT        true|false (default false). Open PR as draft.
#   DRY_RUN      0|1. With 1, all mutating commands are echoed to
#                .claude/.ship-dryrun.log instead of executed.
#   CROSS_OWNER  ack to bypass multi-agent lock check (logged).
#   STACKED      ack to bypass heterogeneous-prefix refusal (logged).
#
# Examples:
#   make ship-arm                       # 2h TTL
#   make ship-arm TTL=30m REAL_EVAL=skip  # REAL_EVAL is a deprecated no-op
#   make ship-arm DRY_RUN=1             # safe end-to-end test
#   make ship-run DRY_RUN=1             # arm + immediately invoke dispatcher
#   make ship-disarm                    # immediate kill (tier 1)
#   make ship-status                    # human-readable arm state
# ---------------------------------------------------------------------------

TTL ?= 2h
REAL_EVAL ?= auto
DRAFT ?= false
DRY_RUN ?= 0
CROSS_OWNER ?=
STACKED ?=
USE_EXISTING_ARM ?= 0
TYPE ?= chore
SLUG ?=
LABELS ?=
BASE ?= origin/main
WT_PARENT ?= ..
OVERLAP ?=
NO_OVERLAP_CHECK ?= 0
OVERLAP_PATHS ?=

ship-start:
	@if [ -z "$(TITLE)" ]; then \
	  echo "Usage: make ship-start TITLE='Issue title' [TYPE=docs] [SLUG=short-slug] [BODY='...'] [LABELS=a,b] [OVERLAP=ack]"; \
	  echo "  OVERLAP=ack overrides a stale-base overlap-preflight block (issue #1836)."; \
	  exit 1; \
	fi
	@OVERLAP="$(OVERLAP)" $(PYTHON) scripts/claude-hooks/_ship_start.py \
	  --title "$(TITLE)" \
	  --body "$(BODY)" \
	  --type "$(TYPE)" \
	  --slug "$(SLUG)" \
	  --labels "$(LABELS)"

# Spawn an isolated cmux track session (issue #1767): `git worktree add` off
# origin/main + `cmux workspace create` cold-start `claude`. Thin mechanical
# helper that captures the escaping / PATH / platform traps; see
# scripts/spawn_track_session.sh. Issue creation stays with ship-start / gh.
.PHONY: spawn-track
spawn-track:
	@if [ -z "$(ISSUE)" ] || [ -z "$(PROMPT)" ]; then \
	  echo "Usage: make spawn-track ISSUE=N PROMPT='cold-start prompt' [TYPE=chore] [SLUG=slug] [BASE=origin/main] [WT_PARENT=..] [DRY_RUN=1] [OVERLAP=ack] [OVERLAP_PATHS='p1 p2']"; \
	  echo "  OVERLAP=ack overrides a stale-base overlap-preflight block; NO_OVERLAP_CHECK=1 skips it (issue #1836)."; \
	  exit 1; \
	fi
	@ISSUE="$(ISSUE)" PROMPT="$(PROMPT)" TYPE="$(TYPE)" SLUG="$(SLUG)" \
	  BASE="$(BASE)" WT_PARENT="$(WT_PARENT)" DRY_RUN="$(DRY_RUN)" \
	  OVERLAP="$(OVERLAP)" NO_OVERLAP_CHECK="$(NO_OVERLAP_CHECK)" OVERLAP_PATHS="$(OVERLAP_PATHS)" \
	  bash scripts/spawn_track_session.sh

ship-arm:
	@$(PYTHON) scripts/claude-hooks/_ship_arm.py \
	  --ttl "$(TTL)" \
	  --real-eval "$(REAL_EVAL)" \
	  --draft "$(DRAFT)" \
	  --dry-run "$(DRY_RUN)" \
	  --cross-owner "$(CROSS_OWNER)" \
	  --stacked "$(STACKED)"

ship-run:
	@$(PYTHON) scripts/claude-hooks/_ship_run.py \
	  --ttl "$(TTL)" \
	  --real-eval "$(REAL_EVAL)" \
	  --draft "$(DRAFT)" \
	  --dry-run "$(DRY_RUN)" \
	  --cross-owner "$(CROSS_OWNER)" \
	  --stacked "$(STACKED)" \
	  --use-existing-arm "$(USE_EXISTING_ARM)"

codex-ship: ship-run

# Selectively reap orphaned/stale codex adversarial-review brokers (issue #1699).
# Only touches the `cxc-*` broker run-dirs under the OS temp dir whose pid is dead
# or orphaned (ppid==1); live, parented sessions and the desktop Codex.app are
# left untouched. Operator/manual cleanup of the current backlog.
codex-reap:
	@$(PYTHON) scripts/run_codex_adversarial_precommit.py --reap-only

ship-disarm:
	@rm -f .claude/.ship-armed .claude/.ship-running.pid
	@echo "ship: disarmed."

ship-status:
	@if [ -f .claude/.ship-armed ]; then \
	  echo "ship: ARMED"; \
	  cat .claude/.ship-armed; \
	else \
	  echo "ship: not armed"; \
	fi
	@if [ -f .claude/.ship-running.pid ]; then \
	  echo "ship: pipeline running (pid=$$(cat .claude/.ship-running.pid))"; \
	fi

ship-review-gate:
	@$(PYTHON) scripts/claude-hooks/_ship_review_gate.py $(if $(PR),--pr "$(PR)",)

worktree-cleanup-dry-run:
	@bash .githooks/_pre-push-worktree-hygiene.sh --clean --dry-run --delete-branches

worktree-cleanup:
	@bash .githooks/_pre-push-worktree-hygiene.sh --clean --prune --delete-branches

# cmux orphan workspace (tab) cleanup — symmetric to worktree-cleanup (ADR
# 0096). Closes cmux tabs whose worktree is gone. close is irreversible (tab +
# scrollback destroyed), so run cmux-cleanup-dry-run FIRST to confirm the
# candidates. See docs/plans/cmux-workspace-cleanup.md.
cmux-cleanup-dry-run:
	@bash scripts/cmux-cleanup.sh --dry-run

cmux-cleanup:
	@bash scripts/cmux-cleanup.sh

# ---------------------------------------------------------------------------
# Self-review quarterly: meta-feedback loop over the past quarter.
# Emits a Markdown skeleton at docs/self-review/$(QUARTER).md containing
# metadata-only counts (sessions, tool calls, ADR/PR changes, memory
# frontmatter). The 4-axis + 5-axis verdict tables are filled by running
# `/self-review-quarterly $(QUARTER)` in Claude Code. Body excerpts from
# transcripts are never read — see scripts/claude-hooks/_self_review.py
# and docs/self-review/README.md for the privacy boundary.
#
# Example:
#   make self-review-quarterly QUARTER=Q2-2026
# ---------------------------------------------------------------------------

self-review-quarterly:
	@if [ -z "$(QUARTER)" ]; then \
	  echo "Usage: make self-review-quarterly QUARTER=Q2-2026"; \
	  exit 1; \
	fi
	@$(PYTHON) scripts/claude-hooks/_self_review.py \
	  --quarter "$(QUARTER)" \
	  --emit-report \
	  --output "docs/self-review/$(QUARTER).md"
	@echo "Run /self-review-quarterly $(QUARTER) in Claude Code to fill verdict tables."

# Rolling-window hook-fires summary (issue #716). Emits last N-day governance
# hook stats as JSON to stdout. Q3 self-review #3·#4 (automation ROI / rule-to-
# automation lag) progress gauge — daily-runnable companion to the quarterly
# report.
#
# Example:
#   make hook-fires-weekly           # last 7 days (default)
#   make hook-fires-weekly DAYS=30   # last 30 days
hook-fires-weekly:
	@$(PYTHON) scripts/claude-hooks/_self_review.py --window-days $(or $(DAYS),7) --repo .
