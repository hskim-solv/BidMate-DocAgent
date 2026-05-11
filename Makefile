.PHONY: setup index ask eval benchmark benchmark-check check smoke harness-smoke test test-regression api api-docker demo demo-docker real-eval real-eval-delta real-eval-baseline-update real-eval-history-render real-eval-history-check real-eval-with-judge synthetic-judge clean

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

index:
	$(PYTHON) scripts/build_index.py --input_dir data/raw --output_dir data/index

ask:
	$(PYTHON) app.py --input_dir data/index --output_dir outputs --query "기관 A와 기관 B의 AI 요구사항 차이 알려줘"

eval:
	$(PYTHON) eval/run_eval.py --index_dir data/index --output_dir reports --config eval/config.yaml

benchmark:
	$(PYTHON) scripts/run_benchmark.py --suite benchmarks/suites/public_synthetic_rfp.yaml --ablations benchmarks/ablations/rag_quality_axes.yaml

benchmark-check:
	$(PYTHON) scripts/summarize_benchmark.py --manifest $${MANIFEST:?set MANIFEST=artifacts/benchmarks/<run_id>/run_manifest.json} --check

check:
	$(PYTHON) scripts/update_readme_metrics.py --report reports/eval_summary.json --readme README.md --check

smoke:
	bash scripts/smoke.sh

harness-smoke:
	$(PYTHON) scripts/run_harness.py --config harness/smoke.yaml

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
real-eval-baseline-update:
	$(PYTHON) scripts/write_real_eval_baseline.py

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

clean:
	rm -rf data/index outputs reports
