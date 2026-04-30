.PHONY: setup index ask eval check smoke test clean

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

check:
	$(PYTHON) scripts/update_readme_metrics.py --report reports/eval_summary.json --readme README.md --check

smoke:
	bash scripts/smoke.sh

test:
	bash scripts/test.sh

clean:
	rm -rf data/index outputs reports
