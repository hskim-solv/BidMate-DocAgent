# Multi-agent ownership model

> **Tracked in [#245](https://github.com/hskim-solv/BidMate-DocAgent/issues/245).**
> Owner roles: [#238](https://github.com/hskim-solv/BidMate-DocAgent/issues/238) · [#239](https://github.com/hskim-solv/BidMate-DocAgent/issues/239) · [#240](https://github.com/hskim-solv/BidMate-DocAgent/issues/240) · [#241](https://github.com/hskim-solv/BidMate-DocAgent/issues/241) · [#242](https://github.com/hskim-solv/BidMate-DocAgent/issues/242) · [#243](https://github.com/hskim-solv/BidMate-DocAgent/issues/243) · [#244](https://github.com/hskim-solv/BidMate-DocAgent/issues/244)

## Why this exists

The RAG pipeline is logically staged (ingestion → retrieval → planning → verification → answer → eval), but the hub module [`rag_core.py`](../rag_core.py) (~4,227 LOC) concentrates retrieval, planning, verification, chunking, and answer assembly into one file imported by 26 other files. Fourteen ADRs lock specific contracts (answer schema, naive baseline preservation, eval split, evidence boundary). [`CLAUDE.md`](../CLAUDE.md) insists on "one PR, one concern" with stacked-PR discipline.

When several agents work in parallel, three collision points emerge:

1. The single file `rag_core.py`.
2. The answer-dict schema (ADR 0003) — every consumer in `eval/`, `api/`, `demo/` depends on it.
3. `eval/config.yaml` — the `naive_baseline` preset must be preserved (ADR 0001).

The split below resolves these by combining **ADR ownership** with a **hub lock-holder**: one agent per ADR cluster, with `rag_core.py` changes routed through a single owner.

## Principles

1. **ADR ownership.** One agent = the sole author of one or more ADR contracts. That ADR can only be amended through that agent's PR.
2. **Hub lock holder.** `rag_core.py` is modified by the Pipeline Core owner only. Other owners affect it via hooks, callbacks, or the `run_rag_query` public surface.
3. **Additive only.** New features ship as ablation or extension presets (see ADRs 0001 / 0011 / 0014). The extractive baseline is never replaced.
4. **Stacked PRs.** Dependent work is rebased onto an upstream PR with `gh pr create --base <upstream>`. Independent work targets `main` directly.

## The seven ownership roles

### 1. Pipeline Core — [#238](https://github.com/hskim-solv/BidMate-DocAgent/issues/238)

- **Files:** [`rag_core.py`](../rag_core.py)
  - chunking: lines 889–1100
  - planning: lines 1750–2025
  - retrieval: lines 2027–2320
  - verification: lines 2528–2750
  - answer assembly: lines 2749–2950, 4155–4190
- **ADRs owned:** 0001 (naive baseline), 0002 (metadata-first), 0003 (answer contract), 0004 (verifier-retry), 0008 (evidence boundary), 0010 (hybrid retrieval).
- **Don'ts.** Remove `naive_baseline` from `pipeline_cli_choices()`; silently change keys in the `run_rag_query` return dict; skip `schema_version` bumps when the answer contract changes.

### 2. Ingestion — [#239](https://github.com/hskim-solv/BidMate-DocAgent/issues/239)

- **Files:** [`ingestion.py`](../ingestion.py), [`visual_ingestion.py`](../visual_ingestion.py), [`rag_normalize.py`](../rag_normalize.py), [`text_normalize.py`](../text_normalize.py).
- **ADRs owned:** 0008 (evidence boundary — input side).
- **Examples of in-scope work.** New document formats (HWPX, etc.), OCR / visual extraction improvements, Korean normalization rules, parser metrics.

### 3. Synthesis — [#240](https://github.com/hskim-solv/BidMate-DocAgent/issues/240)

- **Files:** [`rag_synthesis.py`](../rag_synthesis.py); one synthesis hook inside `rag_core.py` (changes routed through Pipeline Core).
- **ADRs owned:** 0011 (LLM synthesis as additive).
- **Don'ts.** Generate `claims` / `citations` from the LLM — they must stay extractive (ADR 0003 + ADR 0011). Synthesis must remain opt-in, not on by default.

### 4. Evaluation — [#241](https://github.com/hskim-solv/BidMate-DocAgent/issues/241)

- **Files:** [`eval/`](../eval/) (entire directory), [`scripts/run_real_eval_delta.py`](../scripts/run_real_eval_delta.py), [`scripts/compare_eval.py`](../scripts/compare_eval.py), [`scripts/compare_external_baselines.py`](../scripts/compare_external_baselines.py), [`scripts/leaderboard.py`](../scripts/leaderboard.py), [`scripts/update_readme_metrics.py`](../scripts/update_readme_metrics.py), [`scripts/write_real_eval_baseline.py`](../scripts/write_real_eval_baseline.py), [`scripts/write_synthetic_history.py`](../scripts/write_synthetic_history.py).
- **ADRs owned:** 0005 (eval split), 0006 (real-only judge), 0009 (external baseline), 0012 (synthetic judge stub-default), 0014 (RAGAS additive).
- **Don'ts.** Remove the `naive_baseline` ablation preset from `eval/config.yaml` (ADR 0001); enable a live LLM judge by default in public CI (ADR 0012); commit private real-data artifacts (ADR 0005).

### 5. Observability — [#242](https://github.com/hskim-solv/BidMate-DocAgent/issues/242)

- **Files:** [`rag_observability.py`](../rag_observability.py); trace-hook insertion points inside `rag_core.py` (changes routed through Pipeline Core).
- **ADRs owned:** 0013 (pluggable observability).
- **Examples of in-scope work.** New trace backends (Otel exporters, custom sinks), redaction policy, span enrichment.

### 6. API & Demo — [#243](https://github.com/hskim-solv/BidMate-DocAgent/issues/243)

- **Files:** [`api/main.py`](../api/main.py), [`app.py`](../app.py), [`demo/`](../demo/).
- **ADRs owned:** none — this layer only consumes the `run_rag_query` public surface.
- **Constraint.** Use the `run_rag_query` return-dict keys only. Do not import internal helpers from `rag_core.py`; any new interface need is routed through the Pipeline Core owner.

### 7. Infra & CI — [#244](https://github.com/hskim-solv/BidMate-DocAgent/issues/244)

- **Files:** [`.github/workflows/`](../.github/workflows), [`.githooks/`](../.githooks), [`scripts/check_branch_and_issue.py`](../scripts/check_branch_and_issue.py), [`.github/pull_request_template.md`](../.github/pull_request_template.md), [`.github/ISSUE_TEMPLATE/`](../.github/ISSUE_TEMPLATE), [`.claude/settings.json`](../.claude/settings.json).
- **ADRs owned:** 0007 (issue-linked branch naming).
- **Examples of in-scope work.** New CI gates (e.g. `schema_version` assertions), pre-commit / pre-push hook additions, PR / issue template updates.

## Conflict-resolution rules

- **`rag_core.py` concurrent edits.** Pipeline Core owner is the sole lock holder. When another owner needs hub changes that don't fit a hook or public-surface extension, they open an interface-change PR via Pipeline Core first; their downstream PR stacks on top with `gh pr create --base`.
- **Answer-dict schema change (ADR 0003).** Always shipped as a standalone PR — ADR amendment + `schema_version` bump + broadcast to eval / api / demo consumers. Never bundled with feature work.
- **`eval/config.yaml`.** Evaluation owner only. Other owners request new ablation presets; they do not edit the file directly.
- **`docs/adr/` files.** The relevant area owner authors new ADRs. Existing ADR files are never deleted or renamed — they are marked **Superseded** in the Status block.

## Scenario → owner mapping

| Scenario | Owner(s) | Stacking |
| --- | --- | --- |
| New retrieval backend (e.g. ColBERT) | Pipeline Core + Evaluation | Eval PR stacked on Pipeline Core PR |
| New document format (e.g. HWPX) | Ingestion | Standalone |
| LLM-judge / RAGAS metric improvement | Evaluation | Standalone |
| New demo screen or Colab notebook | API & Demo | Standalone |
| New CI gate (e.g. `schema_version` assertion) | Infra & CI | Standalone |
| Answer-schema extension | Pipeline Core → API & Demo + Evaluation | Consumer PRs stacked on the schema PR |
| New Otel exporter | Observability | Standalone |

## Verification

Before every PR:

- `make smoke` — fast end-to-end sanity check (`EMBEDDING_BACKEND=hashing`).
- `bash scripts/test.sh` — `pytest -q` (the CI gate).

When load-bearing files (`rag_core.py`, `ingestion.py`, `visual_ingestion.py`, `eval/`, `api/main.py`) change:

- `make real-eval` + `make real-eval-delta`.
- Fill in PR-template item 5b (real-data delta).

All PRs pass the standing CI gates:

- [`pr-eval.yml`](../.github/workflows/pr-eval.yml)
- [`branch-and-issue-check.yml`](../.github/workflows/branch-and-issue-check.yml)

Answer-contract PRs additionally verify a `schema_version` increment and an updated ADR 0003 entry.

## See also

- [`docs/engineering-governance.md`](engineering-governance.md) — broader workflow map.
- [`docs/adr/README.md`](adr/README.md) — ADR index.
- [`CLAUDE.md`](../CLAUDE.md) — repository conventions.
