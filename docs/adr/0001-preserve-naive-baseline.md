# 0001: Preserve a naive baseline alongside the agentic pipeline

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: [`CLAUDE.md`](../../CLAUDE.md), [`docs/ablation-results.md`](../ablation-results.md), [`eval/config.yaml`](../../eval/config.yaml)

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

## Alternatives considered

- **Drop the baseline once the agentic pipeline ships.** Rejected:
  there would be no defensible answer to *"is the extra complexity
  earning its keep?"* on any future change.
- **Keep the baseline in code but stop running it in eval.** Rejected:
  silent baselines rot. If we are not measuring it, we are not
  preserving it.
