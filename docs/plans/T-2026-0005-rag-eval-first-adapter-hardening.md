# Plan: T-2026-0005 Eval-first RAG adapter hardening

- Status: done
- Owner role: Implementer -> Benchmark Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0005`
- Related issue / PR: issue #1493 / PR #1499; refresh issue #2075
- Related ADR: ADR 0001, ADR 0003, ADR 0005, ADR 0069, ADR 0074
- Created: 2026-05-26
- Last updated: 2026-06-04

## Problem Statement

The repository already has the right flat RAG module split, but the next
improvement wave still needs safer measurement and adapter seams before more
providers or chunking variants are promoted. Without this work, future agents
can add attractive components without a stable retrieval metric, versioned run
manifest, or opt-in provider boundary.

## Current Behavior

`rag_indexing.py` supports `fixed`, `section`, and `auto` chunking. `rag_embedding.py`
exposes `embed_texts()` directly. `eval/run_eval.py` aggregates chunk recall,
MRR, nDCG, and citation coverage, while ADR 0069 explicitly leaves RAGAS
context precision/recall as a separate opt-in judge surface.

## Desired Behavior

Add LLM-free context precision/recall over gold chunk ids, expose more
index/version provenance in `run_manifest`, provide an `EmbeddingProvider`
Protocol around existing embedding code, and add deterministic contextual
chunking as an opt-in strategy. Defaults remain unchanged.

## Constraints

- Scope constraints: no `src/rag/*` tree; use existing flat modules.
- Architecture constraints: provider-specific code stays behind adapters and lazy imports.
- Compatibility constraints: no answer `schema_version` bump; no default pipeline changes.
- Eval/privacy constraints: public fixture smoke proves wiring only; no private raw data.
- Tooling/CI constraints: branch must satisfy ADR 0007 and PR template 5b.
- Non-goals: late chunking, ColPali/ColQwen, GPT-VL full OCR, Self-RAG/Reflexion/CRAG defaults.

## Architecture Impact

- Affected modules or docs: `eval/scorers/*`, `eval/run_eval.py`, `rag_embedding.py`,
  `rag_indexing.py`, `scripts/build_index.py`, tests, task/plan docs.
- Affected contracts or invariants: additive eval summary and manifest fields only.
- Load-bearing paths: `eval/`, `scripts/build_index.py`.
- ADR required: no, this implements existing ADR direction and does not create a durable default change.
- Backward compatibility expectation: existing configs and indexes keep loading; missing fields read as `None`.

## Affected Interfaces

- CLI/API/config: `scripts/build_index.py --chunking_strategy contextual` becomes valid.
- Input data: unchanged.
- Output artifacts: eval summary gains context metric keys and additional manifest fields.
- Docs/review surfaces: task queue and plan document record scope.
- Tests/eval entrypoints: focused unit tests plus optional `make smoke`.

## Data / Eval Impact

- Surface: public fixture smoke eval; not current `real100_v2` private-eval evidence.
- Data boundary: public fixture and aggregate-only eval summary fields.
- Allowed claim: metric/manifest plumbing works and defaults are preserved.
- Disallowed claim: current `real100_v2` private-eval or real RFP quality improvement.
- Baseline or control affected: no; `naive_baseline` remains dense/fixed/default.
- Benchmark/eval auditor required: yes, because eval surface keys are added.

## Task Breakdown

1. Add task queue entry and this plan doc.
2. Add context precision/recall scoring and aggregate plumbing.
3. Extend run manifest and synthesis token/cost aggregate fields additively.
4. Add embedding provider Protocol/factory around `embed_texts()`.
5. Add deterministic contextual chunking strategy and CLI choice.
6. Add focused regression tests and run validation commands.

## Acceptance Criteria

- [x] Context precision/recall keys appear in per-case and aggregate eval blocks.
- [x] Run manifest includes index schema, embedding dimension, chunking strategy, and chunker version fields.
- [x] `EmbeddingProvider` can embed documents/query and raises clear dimension mismatch errors.
- [x] `contextual` chunking emits `contextual_prefix` without changing default chunking.
- [x] Focused tests pass and branch convention check passes.

## Validation Strategy

Commands that must be run:

```bash
python3 -m pytest tests/test_chunk_metrics_regression.py tests/test_chunk_aggregate_regression.py tests/test_run_manifest_versioning_regression.py -q
python3 -m pytest tests/test_embedding_provider_protocol.py tests/test_contextual_chunking_regression.py -q
python3 -m pytest tests/test_vector_store_protocol.py tests/test_vector_store_qdrant.py -q
make check-branch
make smoke
bash scripts/test.sh
```

Expected evidence:

- Test/eval output: focused pytest pass.
- Generated or updated artifact: public fixture `data/index/index.json` carries additive chunk version fields; no generated reports committed.
- Reviewer checklist or manual inspection: confirm no default/provider behavior flip.
- Explicitly not validated, with reason: current `real100_v2` private eval was not run for this docs refresh.

## Rollback Strategy

Revert the implementation commit. No generated indexes or private reports need
to be deleted. Existing indexes without the new manifest fields remain readable.

## Failure Modes

- Failure mode: context precision is confused with RAGAS judge precision.
- Detection signal: docs/tests must name it LLM-free and gold-chunk based.
- Stop condition or fallback: keep RAGAS under `judge_ragas` only.

- Failure mode: contextual chunking changes default embeddings.
- Detection signal: fixed/default tests or smoke output changes unexpectedly.
- Stop condition or fallback: keep `contextual` opt-in only.

## Observability

`reports/eval_summary.json` aggregate keys, `run_manifest`, chunk diagnostics,
and focused regression tests show whether the work is active and bounded.

## Reviewer Notes

Attack baseline preservation, answer contract drift, metric semantics, and
provider boundary first. This PR should not claim current `real100_v2` private-eval or real RFP quality improvement.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-26 12:36 KST

- Role: Implementer
- Branch / worktree: feat/issue-1493-rag-eval-first-adapter-hardening / /Users/hskim/.codex/worktrees/be41/BidMate-DocAgent
- Issue / PR: #1493 / PR #1499
- Task: T-2026-0005
- Current status: review
- Files touched: eval/scorers/*, eval/run_eval.py, rag_embedding.py, rag_indexing.py, scripts/build_index.py, data/index/index.json, tests, tasks/queue.md, this plan doc.
- Decisions made: Keep flat layout, additive eval surfaces, opt-in contextual chunking, and existing embedding wrapper compatibility.
- Commands run: focused pytest, vector store pytest, py_compile, git diff --check, make check-branch, make smoke, bash scripts/test.sh.
- Results: pass; current `real100_v2` private eval not run.
- Next safe command: review diff and open PR.
- Open questions: none.
- Risks: load-bearing eval/index changes require precise test coverage.
```
