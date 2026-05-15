# 0001: Preserve a naive baseline alongside the agentic pipeline

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: [`CLAUDE.md`](../../CLAUDE.md), [`docs/eval/ablation-results.md`](../eval/ablation-results.md), [`eval/config.yaml`](../../eval/config.yaml)

## Context

The system ships an "agentic" full pipeline (metadata-first retrieval,
reranker, verifier-driven retry, structured answer/citation contract).
Every advanced component adds latency, complexity, and a surface for
regressions. Without a side-by-side comparison run on the same cases,
it is impossible to tell whether the extra machinery actually improves
quality on a given query slice — or just shifts the failure mode.

## Decision

Keep a runnable `naive_baseline` pipeline preset alongside
`agentic_full` for the lifetime of the project. The CLI default
remains `naive_baseline` so that the most reproducible path is the
simplest one. Both presets appear as ablation runs in
[`eval/config.yaml`](../../eval/config.yaml) and are measured on
every eval invocation.

The knob: `pipeline_cli_choices()` in
[`rag_core.py`](../../rag_core.py) is the source of truth for which
presets exist; removing `naive_baseline` from that list is the
explicit signal that this ADR is being revisited.

## Consequences

**Wins**

- Every ablation report includes a baseline column, so quality wins
  from advanced components are demonstrable, not asserted.
- Reviewers can run the simplest path (`make ask`) end-to-end without
  understanding the agentic stack.
- Regressions in the agentic pipeline that drag it below baseline are
  detected by the eval delta job, not by anecdote.
- Issue triage gains a fast question: *does it reproduce on
  `naive_baseline`?*

**Costs**

- Two code paths must keep working. The CLI surface (`app.py`), the
  API surface (`api/main.py`), and `eval/run_eval.py` all carry the
  abstraction.
- The README's headline metrics need to make the baseline-vs-full gap
  explicit, or the system looks weaker than it is.

## Default-choice re-evaluation criteria (ADR 0019, consolidated)

ADR 0019 established the pattern for when a "default stays as-is" decision may be revisited. That ADR is Superseded here; the re-open conditions are the load-bearing part.

**Current default kept**: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` as the embedding model.

**Re-open conditions** (all four must hold before flipping the default):
1. `requirements.txt` upgrade resolves `torch >= 2.6` and `huggingface-hub < 1.0` blockers.
2. `python3 scripts/run_embedding_ablation.py --models <miniLM> BAAI/bge-m3 intfloat/multilingual-e5-large-instruct` runs to completion on the public synthetic corpus (n=42).
3. At least one candidate shows a **`full` pipeline** lift of ≥ +5pp on accuracy or groundedness with non-overlapping bootstrap 95% CIs vs MiniLM. (*Lifts on `naive_baseline` only do NOT count.*)
4. A follow-up ADR documents the replacement candidate.

**Phase 1.3 update (issue #389, 2026-05-12):** Conditions 1 and 2 are met for all four candidates (BGE-M3 measurement closed the last gap). Condition 3 is NOT triggered — the `0pp-on-full` pattern holds across all five embeddings. This ADR stays accepted.

## Alternatives considered

- **Drop the baseline once the agentic pipeline ships.** Rejected:
  there would be no defensible answer to *"is the extra complexity
  earning its keep?"* on any future change.
- **Keep the baseline in code but stop running it in eval.** Rejected:
  silent baselines rot. If we are not measuring it, we are not
  preserving it.
