.PHONY: setup index ask eval benchmark benchmark-check check smoke harness-smoke test test-regression clean

PYTHON ?= python3
VENV ?= .venv
ACTIVATE = . $(VENV)/bin/activate

setup:
	$(PYTHON) -m venv $(VENV)
	$(ACTIVATE) && pip install -r requirements.txt

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

clean:
	rm -rf data/index outputs reports
