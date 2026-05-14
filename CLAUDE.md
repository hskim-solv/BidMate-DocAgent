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
for load-bearing edits + Bash matcher refusing `gh pr merge --delete-branch`
when stacked dependents exist). This file captures the principles and pointers
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
- `rag_retrieval.py` — retrieval pipeline extracted from `rag_core.py` across PR-H1a (issue #459) + PR-H1b (issue #461). Owns `retrieve_candidates` (candidate generation), the four similarity primitives (`embed_query_for_index`, `dense_similarity`, `lexical_similarity`, `metadata_similarity`), BM25 surface (`bm25_scores_for_index`, `get_or_build_bm25` + `_*` helpers), and the post-retrieval stack (`apply_fusion_and_reranking`, `apply_comparison_balance`, `reassemble_parent_sections`). Late-imports `tokenize` / `DEFAULT_EMBEDDING_MODEL` / `DEFAULT_HASH_DIM` / `embed_texts` / `hashing_embeddings` / `comparison_targets_for_analysis` / `normalize_regions` / `normalize_page_span` from `rag_core` to avoid circular imports — these helpers serve many non-retrieval rag_core call sites and stay there as canonical homes.
- `rag_verifier.py` — verifier path extracted from `rag_core.py` (issue #465, PR-J1). Owns `verify_evidence` (main verifier + partial-topic grounding policy per ADR 0004), the topic-extraction helpers (`verification_topics`, `specific_topics`, `metadata_terms_for_verification`), the `EVIDENCE_BOUNDARY` constant + 3 instruction-pattern regexes, `neutralize_instruction_patterns` (ADR 0008 evidence-side defense), `evidence_text_for_verification`, `evidence_has_topic`, and the `PARTIAL_TOPIC_GROUNDING_*` policy constants. Direct imports: `korean_lexicon` (METADATA_EVIDENCE_LABELS / METADATA_GENERIC_TOKENS / TOPIC_KEYWORDS / VERIFICATION_INTENT_TOKENS) + `text_normalize` (expand_forms / normalize_text). Late-imports `normalize_metadata_token` / `metadata_tokens` / `ordered_unique` from `rag_core` so the module stays a leaf in the dependency graph. `rag_core` re-exports every public name + 3 constants so `tests/test_synthetic_judge.py` / `tests/test_prompt_injection_regression.py` / `scripts/llm_judge.py` / `eval/synthetic_judge.py` (which import `EVIDENCE_BOUNDARY` and `neutralize_instruction_patterns` from `rag_core`) keep working unchanged.
- `rag_answer.py` — answer generation extracted from `rag_core.py` (issue #468, PR-J2). Owns the 20 functions that turn verified evidence into the ADR 0003 answer dict: `generate_answer` (main entry), `build_claims` / `build_comparison_claims` / `build_extract_claims`, `make_claim` / `make_citation` / `claim_target`, `answer_status` / `answer_status_reason` / `answer_query_type` / `answer_summary` / `answer_verification_reasons`, `build_insufficiency`, `render_answer_text`, `best_sentence` / `metadata_claim_sentences` / `metadata_field_requested` / `format_metadata_claim_value` / `sentence_has_verification_topic` / `select_supporting_evidence`. ADR 0003 dict contract (`schema_version: 2` literal) stays here; CLAUDE.md prohibition against parallel Pydantic models still applies. Direct imports: `korean_lexicon` (METADATA_CLAIM_*), `rag_answer_schema` (ANSWER_STATUS_* / ANSWER_SCHEMA_VERSION), `rag_verifier` (specific_topics / verification_topics / evidence_text_for_verification / PARTIAL_TOPIC_GROUNDING_REASON). Late-imports `sentence_split` / `tokenize` / `ordered_unique` / `normalize_regions` / `normalize_page_span` / `compact_metadata_text` from `rag_core` (multi-surface utilities). `rag_core` re-exports every public name so orchestration (`_phase_build_answer`) keeps working.
- `rag_query.py` — query analysis + planning extracted from `rag_core.py` (issue #478, PR-J3). Owns the 15 functions that turn the raw user query into the `plan` dict retrieval consumes: `analyze_query` (main analyzer), `resolve_conversation_context` + `make_context_resolution` + 7 query-inspection / state helpers (`is_metadata_ambiguous` / `has_implicit_reference` / `has_comparison_request` / `extract_requested_agencies` / `active_state_terms` / `active_state_size` / `inject_entities_into_query`), `comparison_targets_for_analysis` (called via re-export by rag_retrieval / rag_answer), `summarize_metadata_match` / `metadata_resolution_diagnostics`, `query_type_default_top_k` / `make_plan`. Direct imports: `korean_lexicon` (IMPLICIT_REFERENCE_PATTERNS / STOPWORDS / TOPIC_KEYWORDS), `rag_conversation_state` (CONTEXT_RESOLUTION_THRESHOLD), `rag_pipeline_presets` (preset / validation constants), `text_normalize` (normalize_text). Late-imports many `rag_core` utilities (`tokenize` / `ordered_unique` / `normalize_entity` / `normalize_metadata_token` / `metadata_tokens` / `compact_metadata_text` / `match_metadata_targets` / `metadata_ambiguity_details` / `metadata_filters_from_matches` / `metadata_matches_for_stage` / `best_metadata_doc_scores` / `coerce_string_list` / `coerce_metadata_targets` / `ENTITY_RE` / `QUERY_TYPE_TOP_K_DEFAULTS`) so the module stays a leaf in the dependency graph. `rag_core` re-exports all 15 public names.
- `rag_query_expansion.py` — `QueryExpander` Protocol + default `IdentityExpander` + opt-in `HyDEExpander` (issue #396, ADR 0023). Plugs in before the dense-embedding call in `rag_retrieval.retrieve_candidates`; BM25 / lexical / metadata paths consume `analysis.tokens` and remain invariant. Identity default preserves the ADR 0001 `naive_baseline` bit-identical golden.
- `scripts/` — `build_index.py`, `update_readme_metrics.py`, `run_real_eval_delta.py`, etc.
- `data/raw/` → `data/index/` → `outputs/` → `reports/` (pipeline artifacts).
- `docs/` — design notes, ADRs, failure analyses, reviewer artifacts.

## Communication

- **Respond in Korean when the user writes in Korean.** Reserve English for English-language prompts or an explicit "respond in English" request. Code, identifiers, commit messages, file/directory names stay in English.
- **Lead summaries with a 2-3 line TL;DR; details below.** One decision per turn — do not dump multiple PRs / issues / branches in a single message.

## Autonomy & Approvals

- **State-changing actions require explicit approval.** `git push`, `gh pr merge`, `gh pr create`, `git branch -D`, `gh issue create` only after the user gives an explicit go-ahead (e.g. "진행", "go", "merge it", "ok"). Short interrogatives like `"머지?"`, `"PR?"`, `"?"` are **questions** — answer them, do not act on them.
- **For chained side effects** (stacked-PR merge, ADR-then-PR, multi-issue triage), get a separate approval per step instead of bundling.

## Delegation defaults

- **Plan subagent before non-trivial change.** Any change touching >1 file or >50 LOC, or any plan-mode entry, dispatches a Plan subagent first. Skip only for typo / single-line fixes.
- **Explore subagent for read-heavy probes.** ≥5 Read calls accumulated, or any single-file read >200 lines, hands off to Explore so the main conversation keeps tokens free.
- **Shipping path locked at commit-0.** Decide `ship-pr` skill (manual gates, ADR reserve + stacked safety) vs `make ship-arm` (Stop-hook auto-ship). They are mutually exclusive — never arm both.
- Full 5-axis ↔ 4-pillar mapping lives in [`docs/agent-utilization.md`](docs/agent-utilization.md). `self-review-quarterly` skill scores against that table.

## Core principles

- **Issue first; convention-matched branch.** Every PR must reference an issue (`Closes #N` in body) and its branch must match `<type>/issue-<N>[-<slug>]` (ADR 0007). The CI workflow `branch-and-issue-check.yml` enforces both at PR time.
- **Reuse over invent.** Inspect existing implementation before coding. Search for reusable utilities first.
- **One PR, one concern.** Out-of-scope fixes → separate issue / follow-up PR.
- **Behavior change ↔ test change.** Behavior change without a test is presumed accidental. Regression tests go in `tests/test_*_regression.py` (pattern: `tests/test_retrieval_loop_regression.py`).
- **Backward compatibility.** Breaking changes need an explicit reason. Answer-contract break (ADR 0003) requires `schema_version` bump.
- **ADR threshold.** Removing or replacing a load-bearing decision (baseline / pipeline / answer contract / eval surface) needs an ADR. Criteria: [`docs/adr/README.md`](docs/adr/README.md).
- **Reserve ADR numbers up front.** Before drafting a new ADR, check both `ls docs/adr/` and `gh pr list --search "ADR" --state open` to find the next available number. Propose it and wait for user confirmation before creating the file — concurrent worktree work has produced repeat collisions (0022→0023, 0023→0025, 0029→0030).

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
- Running `gh pr merge --delete-branch` without first verifying `gh pr list --base <this-PR-head-branch> --state open --json number` is empty. Open results mean a stacked dependent exists — drop `--delete-branch` or rebase the children onto main first. (A follow-up PreToolUse Bash guard hook automates this; the rule is stated here so it survives even if the hook is disabled.)

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
