# PHONY declarations are grouped by workflow domain to mirror the recipe
# sections below. Composite gates (e.g. `governance-check`) live alongside
# their member targets. Preserve target names verbatim when adding to a
# group — downstream docs (CLAUDE.md, docs/engineering-governance.md) and
# .githooks/ reference these names directly.

# Setup / hooks
.PHONY: setup install-hooks

# Governance gates (branch + issue, README metrics, latency SLO, leaderboard
# freshness, real-eval history freshness, benchmark manifest check). Run
# `make governance-check` to invoke the pre-PR subset in sequence.
.PHONY: check-branch governance-check check check-latency leaderboard-check real-eval-history-check benchmark-check check-baseline-provenance

# Index build + ad-hoc ask
.PHONY: index ask

# Synthetic eval surface (public corpus). Includes smoke, full eval, harness
# matrix, judges, leaderboard render, pareto, korean public bench, external
# baselines.
.PHONY: eval smoke smoke-with-judge reproduce benchmark synthetic-judge leaderboard pareto korean-public-fetch korean-public-eval external-baselines-stub external-baselines-langchain external-baselines-llamaindex harness-smoke harness-ablation harness-compare

# Real-data eval cycle (private; ADR 0005 commit boundary).
.PHONY: real-eval real-eval-delta real-eval-baseline-update real-eval-history-render real-eval-with-judge harness-real

# Real-data case proposer cycle (ADR 0029; gitignored I/O).
.PHONY: case-propose case-review case-promote

# API / demo (FastAPI + Streamlit; local + docker variants)
.PHONY: api api-docker demo demo-docker docker-publish

# Tests
.PHONY: test test-regression

# Auto-ship pipeline (Stop hook driven). See scripts/claude-hooks/stop-ship.sh
# and the plan at /Users/hskim/.claude/plans/prci-synchronous-newell.md.
.PHONY: ship-arm ship-disarm ship-status

# Cleanup
.PHONY: clean

PYTHON ?= python3
VENV ?= .venv
ACTIVATE = . $(VENV)/bin/activate

setup:
	$(PYTHON) -m venv $(VENV)
	$(ACTIVATE) && pip install -r requirements.txt

# One-time per clone: activate the opt-in git hooks in .githooks/
# (pre-commit ADR 0005 boundary, pre-push branch/eval checks).
install-hooks:
	git config core.hooksPath .githooks
	@echo "Activated .githooks/ for this clone. See docs/engineering-governance.md §Hook setup."

# Ad-hoc validation of the current branch against ADR 0007.
# Useful before opening a PR; mirrors the CI check.
check-branch:
	$(PYTHON) scripts/check_branch_and_issue.py \
	  --branch "$$(git rev-parse --abbrev-ref HEAD)" --check-issue

# Composite governance gate. Runs the three pre-PR freshness checks in
# sequence: branch + issue convention (ADR 0007), leaderboard render
# freshness, and real-data history-table freshness. Each sub-target is
# already wired into CI / hooks individually; this target just shortens
# the local pre-PR checklist into a single invocation. Fails on the
# first sub-target that exits non-zero.
governance-check: check-branch leaderboard-check real-eval-history-check check-baseline-provenance
	@echo "governance-check: branch + leaderboard + real-eval-history + baseline-provenance OK."

# Verify reports/real100/baseline.aggregate.json's provenance.git_commit is
# still reachable from origin/main (issue #413). Catches the silent-breakage
# tail of issue #160: a baseline committed at a SHA that was later
# force-pushed/rebased off main, leaving `make real-eval-delta` diffing
# against a phantom code state. For non-default refs, invoke the script
# directly: `python scripts/check_baseline_provenance.py --ref <ref>`.
check-baseline-provenance:
	$(PYTHON) scripts/check_baseline_provenance.py

index:
	$(PYTHON) scripts/build_index.py --input_dir data/raw --output_dir data/index

ask:
	$(PYTHON) app.py --input_dir data/index --output_dir outputs --query "기관 A와 기관 B의 AI 요구사항 차이 알려줘"

eval:
	$(PYTHON) eval/run_eval.py --index_dir data/index --output_dir reports --config eval/config.yaml

# Cost-quality Pareto frontier table (and PNG if matplotlib installed)
# from the latest reports/eval_summary.json. Read-only consumer — see
# scripts/plot_pareto.py for cost/quality axis choice (latency p95 vs
# citation_precision).
pareto:
	$(PYTHON) scripts/plot_pareto.py --summary reports/eval_summary.json --markdown-out reports/pareto.md --png-out reports/pareto.png

# Publish the demo image to GHCR so reviewers can `docker run <image>`
# without cloning the repo (issue #123). Requires `docker login ghcr.io`
# beforehand; override IMAGE_TAG to publish to a different registry.
IMAGE_TAG ?= ghcr.io/hskim-solv/bidmate-demo:latest
docker-publish:
	docker build -t $(IMAGE_TAG) .
	docker push $(IMAGE_TAG)

benchmark:
	$(PYTHON) scripts/run_benchmark.py --suite benchmarks/suites/public_synthetic_rfp.yaml --ablations benchmarks/ablations/rag_quality_axes.yaml

benchmark-check:
	$(PYTHON) scripts/summarize_benchmark.py --manifest $${MANIFEST:?set MANIFEST=artifacts/benchmarks/<run_id>/run_manifest.json} --check

check:
	$(PYTHON) scripts/update_readme_metrics.py --report reports/eval_summary.json --readme README.md --check

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

# External baseline comparison (ADR 0009 / issue #157).
# Stub backend is deterministic and free — exercises the comparison
# infrastructure without API cost. Live backends require ANTHROPIC_API_KEY
# and a one-time install of the SDK extras (~$2 / 42 cases at Sonnet 4.6).
external-baselines-stub:
	BIDMATE_EXTERNAL_BACKEND=stub $(PYTHON) scripts/compare_external_baselines.py

external-baselines-langchain:
	@if [ -z "$$ANTHROPIC_API_KEY" ]; then \
		echo "ANTHROPIC_API_KEY not set. Live LangChain run needs an Anthropic key (~\$$2 / 42 cases)."; \
		exit 1; \
	fi
	BIDMATE_EXTERNAL_BACKEND=langchain $(PYTHON) scripts/compare_external_baselines.py

external-baselines-llamaindex:
	@if [ -z "$$ANTHROPIC_API_KEY" ]; then \
		echo "ANTHROPIC_API_KEY not set. Live LlamaIndex run needs an Anthropic key (~\$$2 / 42 cases)."; \
		exit 1; \
	fi
	BIDMATE_EXTERNAL_BACKEND=llamaindex $(PYTHON) scripts/compare_external_baselines.py

smoke:
	bash scripts/smoke.sh

# Cross-machine reproducibility hash. Runs the smoke eval and prints a
# SHA-256 over the environment-invariant subset of reports/eval_summary.json
# (latency/timestamps stripped). Pass BASELINE=<sha> to compare against a
# known-good hash from another machine; exit 2 on mismatch.
reproduce:
	bash scripts/reproduce_eval.sh

# Run the synthetic smoke eval, then ask a RAGAS-style LLM judge for
# enrichment metrics (ADR 0012). Opt-in additive only — never replaces
# the deterministic verifier. Default backend is `stub` (zero-cost,
# deterministic); set BIDMATE_JUDGE_BACKEND=openai_compatible plus
# BIDMATE_JUDGE_* env vars for a paid judge call. Pass --fold-aggregate
# to merge the judge_ragas block into reports/eval_summary.json.
smoke-with-judge: smoke
	$(PYTHON) eval/llm_judge.py --fold-aggregate
	@echo "RAGAS scores written. Per-case verdicts in reports/eval_summary.judge.local.json (gitignored)."

harness-smoke:
	$(PYTHON) scripts/run_harness.py --config harness/smoke.yaml

# Real-data harness profile. Requires harness/real.local.yaml (copied from
# harness/real.example.yaml) and the eval/*.local.yaml it points to. None
# of these resolved files are committed.
harness-real:
	$(PYTHON) scripts/run_harness.py --config harness/real.local.yaml

# Run a matrix of harness cells on the committed public synthetic corpus.
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

# Fast P0 regression guards for the retrieval loop and answerable smoke path.
# Run before any change to rag_core retrieval/verification or the eval pipeline.
test-regression:
	$(PYTHON) -m pytest tests/test_retrieval_loop_regression.py -q

# Run the FastAPI demo locally. Requires data/index to exist
# (run `make index` first). See docs/api-demo.md for details.
api:
	$(PYTHON) -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Build and run the demo container. The entrypoint builds the index on
# first start if data/index is empty inside the container.
api-docker:
	docker build -t bidmate-demo .
	docker run --rm -p 8000:8000 bidmate-demo

# Run the Streamlit live demo UI locally on http://localhost:8501.
# Requires data/index to exist (run `make index` first) — the app will
# rebuild from data/raw on first invocation if it does not.
demo:
	$(PYTHON) -m streamlit run demo/streamlit_app.py

# Run the demo container with the Streamlit UI on :8501 (and FastAPI on
# :8000 alongside). See docs/deployment.md for Fly.io / HF Spaces.
demo-docker:
	docker build -t bidmate-demo .
	docker run --rm -p 8000:8000 -p 8501:8501 -e BIDMATE_DEMO_MODE=both bidmate-demo

# ---------------------------------------------------------------------------
# Real-data eval cycle (private; ADR 0005 commit boundary). Requires
# eval/real_config.local.yaml + data/files/ + data/data_list.csv to
# exist locally. None of these are committed.
# ---------------------------------------------------------------------------

# Run the private real-data eval end-to-end (build index, sample query,
# eval). Writes reports/real100/eval_summary.json locally (gitignored).
real-eval:
	bash scripts/smoke_real.sh

# Render an aggregate-only markdown delta between the current
# real-data run and the committed baseline. Aggregate-only by
# construction; no per-case data is read or printed.
real-eval-delta:
	$(PYTHON) scripts/run_real_eval_delta.py \
	  --head reports/real100/eval_summary.json \
	  --base reports/real100/baseline.aggregate.json

# Deliberate baseline bump. Reads the current eval_summary.json and
# writes BOTH the current baseline AND an append-only history archive
# entry. Aggregate-only (extractor enforces ADR 0005). Intended to run
# *after* a decision is made (PR merged, threshold tightened, etc.),
# not on every eval. Diff the result with `git diff` before committing.
#
# Pass STRICT=1 (or set BIDMATE_BASELINE_STRICT=1, issue #414) to escalate
# the two existing provenance warnings (no eval-side provenance; eval/
# baseline SHA skew per issue #160) to hard failures — for CI/pre-push
# or any gate that requires a self-consistent baseline.
real-eval-baseline-update:
	$(PYTHON) scripts/write_real_eval_baseline.py $(if $(STRICT),--strict,)

# Render the chronological real-data history table into
# docs/private-100-doc-experiments.md (between the
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
	  --out reports/proposed/proposed_cases.local.yaml

case-review:
	$(PYTHON) scripts/case_proposer_review.py \
	  --proposed reports/proposed/proposed_cases.local.yaml \
	  --reviewed reports/proposed/reviewed_cases.local.yaml

case-promote:
	$(PYTHON) scripts/case_proposer_promote.py \
	  --reviewed reports/proposed/reviewed_cases.local.yaml \
	  --real-config eval/real_config.local.yaml

# Run the LLM judge over the public synthetic eval summary (ADR 0012).
# Default backend `stub` is deterministic and runs in CI; set
# BIDMATE_SYNTHETIC_JUDGE_BACKEND=openai_compatible plus the shared
# BIDMATE_JUDGE_* credentials for a live RAGAS-style signal. Writes a
# committable aggregate and a git-ignored per-case file.
synthetic-judge:
	$(PYTHON) -m eval.synthetic_judge \
	  --summary reports/eval_summary.json \
	  --aggregate reports/synthetic_judge.aggregate.json \
	  --local reports/synthetic_judge.local.json

# Append a history snapshot of the current eval_summary.json + render
# the leaderboard markdown table and the docs/leaderboard.md Chart.js
# page. Mirrors the real-data history pattern but for the public
# synthetic surface (issue #166). CI runs this automatically on every
# merge to main via .github/workflows/leaderboard.yml.
leaderboard:
	$(PYTHON) scripts/write_synthetic_history.py
	$(PYTHON) scripts/leaderboard.py

# Verify the rendered leaderboard artifacts are up to date with the
# current reports/history/ contents. Suitable for pre-PR gating.
leaderboard-check:
	$(PYTHON) scripts/leaderboard.py --check

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
