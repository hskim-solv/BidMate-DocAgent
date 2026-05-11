# CLAUDE.md

RFP-focused DocAgent system. **Bid/RFP document intelligence, not a generic AI playground.**

Pipeline: ingestion → metadata normalization → chunking → retrieval →
reranking/planning → evidence aggregation → grounded answer → verification →
evaluation → reviewer-facing docs.

Deterministic rules live in `.gitignore` / CI (`pr-eval.yml`) / `.githooks/` /
[`.github/pull_request_template.md`](.github/pull_request_template.md). This
file captures the principles and pointers that aren't auto-enforced.

## Start here

- [`docs/engineering-governance.md`](docs/engineering-governance.md) — workflow map.
- [`docs/adr/README.md`](docs/adr/README.md) — decision index.
- If touching retrieval / answer / eval, also read:
  [ADR 0001](docs/adr/0001-preserve-naive-baseline.md) (naive baseline),
  [ADR 0003](docs/adr/0003-structured-answer-citation-contract.md) (answer contract),
  [ADR 0005](docs/adr/0005-eval-split-public-synthetic-private-local.md) (eval split).

## Repository map

Load-bearing — changes here require PR template **item 5b (real-data delta)** filled in:

- `rag_core.py` — core RAG pipeline (retrieval, verifier, answer generation).
- `ingestion.py`, `visual_ingestion.py` — document loading + parsing.
- `eval/` — eval scripts and configs (`eval/config.yaml` defines the `naive_baseline` ablation preset).
- `api/main.py` — FastAPI demo server.
- `docs/adr/` — accepted decision records.

Supporting:

- `app.py` — CLI query entry point.
- `scripts/` — `build_index.py`, `update_readme_metrics.py`, `run_real_eval_delta.py`, etc.
- `data/raw/` → `data/index/` → `outputs/` → `reports/` (pipeline artifacts).
- `docs/` — design notes, ADRs, failure analyses, reviewer artifacts.

## Core principles

- **Reuse over invent.** Inspect existing implementation before coding. Search for reusable utilities first.
- **One PR, one concern.** Out-of-scope fixes → separate issue / follow-up PR.
- **Behavior change ↔ test change.** Behavior change without a test is presumed accidental. Regression tests go in `tests/test_*_regression.py` (pattern: `tests/test_retrieval_loop_regression.py`).
- **Backward compatibility.** Breaking changes need an explicit reason. Answer-contract break (ADR 0003) requires `schema_version` bump.
- **ADR threshold.** Removing or replacing a load-bearing decision (baseline / pipeline / answer contract / eval surface) needs an ADR. Criteria: [`docs/adr/README.md`](docs/adr/README.md).

## PR description

Fill in [`.github/pull_request_template.md`](.github/pull_request_template.md).
Every section is required — write "N/A" with a reason rather than deleting.
When load-bearing files change, **item 5b (real-data delta)** is the most
important — the synthetic CI delta alone missed #69's intended-abstention regression.

## Frequently used commands

- `make smoke` — quick sanity check (few minutes, `EMBEDDING_BACKEND=hashing`).
- `bash scripts/test.sh` — `pytest -q`; same as the CI gate.
- `make real-eval` + `make real-eval-delta` — private 100-doc eval; required when load-bearing files change.
- Latency numbers come from `reports/eval_summary.json` `stage_latency` block — not ad-hoc measurement.

## Prohibited (not enforced by automation)

- Deleting or renaming ADR files. Mark **Superseded** in the Status block; keep the file.
- Adding a parallel pydantic / TypedDict model that shadows `run_rag_query`'s answer dict — the dict is the contract (ADR 0003).
- Removing the `naive_baseline` preset from `eval/config.yaml` (ADR 0001).
- Adding unrelated commits mid-review — open a follow-up PR.

## Non-goals (unless explicitly requested)

- UI additions, web-service productization.
- Large architectural rewrites.
- New paid-API dependencies.
- Reconstructing private RFP data.

## When blocked

Don't guess large. Instead:

1. State 2-3 failure hypotheses.
2. Summarize the repro command + observed error.
3. Propose a minimal fix.
4. Describe a fallback path if the minimal fix doesn't apply.

## Domain glossary

- **Evidence** — retrieved chunk(s) cited as support for a claim.
- **Grounding** — the claim ↔ evidence ↔ source-document linkage requirement.
- **Abstention** — first-class answer status (ADR 0003 `status: insufficient`) when retrieved evidence is inadequate; not a fallback or error.
- **Naive baseline** — minimal-pipeline ablation preset preserved alongside `agentic_full` for side-by-side comparison (ADR 0001).
