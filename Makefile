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
.PHONY: real-eval real-eval-check real-eval-inventory real-eval-semantic real-eval-delta real-eval-baseline-update real-eval-history-render real-eval-with-judge harness-real

# Real-data case proposer cycle (ADR 0029; gitignored I/O).
.PHONY: case-propose case-propose-metadata case-review case-promote

# API / demo (FastAPI + Streamlit; local + docker variants)
.PHONY: api api-docker demo demo-docker docker-publish

# Tests
.PHONY: test test-regression

# Auto-ship pipeline (Stop hook driven). See scripts/claude-hooks/stop-ship.sh
# and the plan at /Users/hskim/.claude/plans/prci-synchronous-newell.md.
.PHONY: ship-start ship-arm ship-disarm ship-status ship-review-gate

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
	@echo "Activated .githooks/ for this clone. See docs/engineering-governance.md §Hook setup."

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

# Run the private real-data eval end-to-end (build index, sample query,
# eval). Writes reports/real100/eval_summary.json locally (gitignored).
# NOTE: builds a `hashing` (feature-hashing BoW) index — deterministic +
# offline, but semantic-blind, so dense/hybrid retrieval recall is NOT
# meaningful here (issue #1295). Use `real-eval-semantic` for that.
real-eval:
	bash scripts/smoke_real.sh

# Semantic variant of real-eval (issue #1295): builds a sentence-transformers
# BGE-M3 index into a SEPARATE dir (real100_m3) so the canonical hashing
# real100 index is untouched. Requires the model to be downloadable/cached
# (not offline/CI-safe). Use this — not `real-eval` — when measuring dense or
# hybrid retrieval recall, since hashing embeddings carry no semantic signal.
real-eval-semantic:
	EMBEDDING_BACKEND=sentence-transformers MODEL=BAAI/bge-m3 \
	  REAL_EVAL_INDEX_DIR=data/index/real100_m3 \
	  OUTPUT_DIR=outputs/real100_m3 \
	  REAL_EVAL_REPORT_DIR=reports/real100_m3 \
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

# Render the chronological real-data history table into
# docs/real-data/private-100-doc-experiments.md (between the
# real-eval-history-{start,end} markers). Aggregate-only.
real-eval-history-render:
	$(PYTHON) scripts/render_real_eval_history.py

# Verify the rendered history table is up to date with committed
# aggregate snapshots. Suitable for pre-PR gating.
real-eval-history-check:
	$(PYTHON) scripts/render_real_eval_history.py --check

# Run the local real-data eval, then ask an LLM judge for a second
# opinion (ADR 0006). The judge is real-data only; never invoked from
# public CI. Default backend is `stub` (deterministic, no network);
# set BIDMATE_JUDGE_BACKEND=openai_compatible plus BIDMATE_JUDGE_*
# env vars for a real judge call.
real-eval-with-judge: real-eval
	$(PYTHON) scripts/llm_judge.py
	@echo "Run \`make real-eval-baseline-update\` to fold the judge aggregate into the committable baseline."

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
#   REAL_EVAL    auto (default), skip, async. Affects PR body §5b cascade.
#   DRAFT        true|false (default false). Open PR as draft.
#   DRY_RUN      0|1. With 1, all mutating commands are echoed to
#                .claude/.ship-dryrun.log instead of executed.
#   CROSS_OWNER  ack to bypass multi-agent lock check (logged).
#   STACKED      ack to bypass heterogeneous-prefix refusal (logged).
#
# Examples:
#   make ship-arm                       # 2h TTL, auto §5b
#   make ship-arm TTL=30m REAL_EVAL=skip
#   make ship-arm DRY_RUN=1             # safe end-to-end test
#   make ship-disarm                    # immediate kill (tier 1)
#   make ship-status                    # human-readable arm state
# ---------------------------------------------------------------------------

TTL ?= 2h
REAL_EVAL ?= auto
DRAFT ?= false
DRY_RUN ?= 0
CROSS_OWNER ?=
STACKED ?=
TYPE ?= chore
SLUG ?=
LABELS ?=

ship-start:
	@if [ -z "$(TITLE)" ]; then \
	  echo "Usage: make ship-start TITLE='Issue title' [TYPE=docs] [SLUG=short-slug] [BODY='...'] [LABELS=a,b]"; \
	  exit 1; \
	fi
	@$(PYTHON) scripts/claude-hooks/_ship_start.py \
	  --title "$(TITLE)" \
	  --body "$(BODY)" \
	  --type "$(TYPE)" \
	  --slug "$(SLUG)" \
	  --labels "$(LABELS)"

ship-arm:
	@$(PYTHON) scripts/claude-hooks/_ship_arm.py \
	  --ttl "$(TTL)" \
	  --real-eval "$(REAL_EVAL)" \
	  --draft "$(DRAFT)" \
	  --dry-run "$(DRY_RUN)" \
	  --cross-owner "$(CROSS_OWNER)" \
	  --stacked "$(STACKED)"

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
