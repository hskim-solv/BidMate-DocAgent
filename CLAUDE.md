# CLAUDE.md

RFP-focused DocAgent system. **Bid/RFP document intelligence, not a generic AI playground.**

Pipeline: ingestion → metadata normalization → chunking → retrieval →
reranking/planning → evidence aggregation → grounded answer → verification →
evaluation → reviewer-facing docs.

Automation surface: `.gitignore`,
CI ([`pr-eval.yml`](.github/workflows/pr-eval.yml),
[`branch-and-issue-check.yml`](.github/workflows/branch-and-issue-check.yml)),
`.githooks/`,
[`scripts/check_branch_and_issue.py`](scripts/check_branch_and_issue.py)
(single-source regex for branch + issue convention, ADR 0007),
[`.github/pull_request_template.md`](.github/pull_request_template.md),
[`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/),
[`.claude/settings.json`](.claude/settings.json) (PreToolUse awareness hook
for load-bearing edits). This file captures the principles and pointers
that aren't auto-enforced.

## Start here

- [`docs/engineering-governance.md`](docs/engineering-governance.md) — workflow map.
- [`docs/adr/README.md`](docs/adr/README.md) — decision index.
- [`docs/multi-agent-ownership.md`](docs/multi-agent-ownership.md) — coordination model when multiple agents work in parallel.
- If touching retrieval / answer / eval, also read:
  [ADR 0001](docs/adr/0001-preserve-naive-baseline.md) (naive baseline),
  [ADR 0003](docs/adr/0003-structured-answer-citation-contract.md) (answer contract),
  [ADR 0005](docs/adr/0005-eval-split-public-synthetic-private-local.md) (eval split),
  [ADR 0012](docs/adr/0012-llm-judge-on-public-synthetic.md) (synthetic LLM-judge).

## Repository map

Load-bearing — changes here require PR template **item 5b (real-data delta)** filled in. Canonical machine-readable list lives in [`scripts/_governance.py`](scripts/_governance.py) `LOAD_BEARING_PATHS` (single source of truth read by `.githooks/pre-push`, `scripts/claude-hooks/pretooluse-loadbearing.sh`, and the `--check-5b` CI gate); add or remove entries there first so the three consumers pick it up automatically. The bullets below are the human reading guide.

- `rag_core.py` — core RAG pipeline (retrieval, verifier, answer generation).
- `ingestion.py`, `visual_ingestion.py` — document loading + parsing.
- `eval/` — eval scripts and configs (`eval/config.yaml` defines the `naive_baseline` ablation preset).
- `api/main.py` — FastAPI demo server (the whole `api/` directory is in the SSoT).
- `docs/adr/` — accepted decision records.
- `scripts/build_index.py` — index builder; downstream of `ingestion` + `rag_core`, surfaces ablation regressions before they reach eval.

Supporting:

- `app.py` — CLI query entry point.
- `rag_vector_store.py` — `VectorStore` Protocol behind the embeddings sidecar (issue #232, Stage 1 of #176). `BIDMATE_INDEX_BACKEND=memory` is the only supported value today; `qdrant` / `pgvector` are reserved for follow-up PRs.
- `rag_reranker.py` — `Reranker` Protocol + default `CrossEncoderReranker` adapter (issue #345, follow-up to #332). Wraps `rag_rerank.rerank` so future HyDE / LLM-as-reranker impls plug in without touching `rag_retrieval.apply_fusion_and_reranking`.
- `rag_retrieval.py` — post-retrieval fusion / comparison balance / hierarchical reassembly extracted from `rag_core.py` (issue #459, PR-H1a). Owns `apply_fusion_and_reranking` (RRF + cross-encoder dispatch), `apply_comparison_balance` (coverage-aware top-k), and `reassemble_parent_sections` (hierarchical mode). Late-imports `comparison_targets_for_analysis` / `normalize_regions` / `normalize_page_span` from `rag_core` to avoid circular imports.
- `rag_query_expansion.py` — `QueryExpander` Protocol + default `IdentityExpander` + opt-in `HyDEExpander` (issue #396, ADR 0023). Plugs in before the dense-embedding call in `rag_core.retrieve_candidates`; BM25 / lexical / metadata paths consume `analysis.tokens` and remain invariant. Identity default preserves the ADR 0001 `naive_baseline` bit-identical golden.
- `scripts/` — `build_index.py`, `update_readme_metrics.py`, `run_real_eval_delta.py`, etc.
- `data/raw/` → `data/index/` → `outputs/` → `reports/` (pipeline artifacts).
- `docs/` — design notes, ADRs, failure analyses, reviewer artifacts.

## Core principles

- **Issue first; convention-matched branch.** Every PR must reference an issue (`Closes #N` in body) and its branch must match `<type>/issue-<N>[-<slug>]` (ADR 0007). The CI workflow `branch-and-issue-check.yml` enforces both at PR time.
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

- `make install-hooks` — one-time per clone: activates `.githooks/` (pre-commit ADR 0005 boundary, pre-push branch/eval checks).
- `make smoke` — quick sanity check (few minutes, `EMBEDDING_BACKEND=hashing`).
- `bash scripts/test.sh` — `pytest -q`; same as the CI gate.
- `make check-branch` — ad-hoc validation of the current branch against ADR 0007.
- `make real-eval` + `make real-eval-delta` — private 100-doc eval; required when load-bearing files change.
- `make ship-arm` — Stop-hook–driven auto-ship pipeline (commit → push → PR → CI → squash-merge). See [`docs/auto-ship.md`](docs/auto-ship.md) for gates, stages, and `STACKED=ack` discipline.
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
