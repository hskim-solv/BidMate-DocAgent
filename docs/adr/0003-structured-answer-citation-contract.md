# 0003: Structured answer / citation contract (`schema_version: 2`)

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: [`docs/answer-policy.md`](../answer-policy.md), [`docs/citation-grounding-eval.md`](../citation-grounding-eval.md), [`eval/run_eval.py`](../../eval/run_eval.py)

## Context

A grounded RAG system is only as trustworthy as its citations. Early
iterations returned free-text answers with informal "(see chunk 3)"
references; this was fine for a demo and useless for evaluation.
Anything we wanted to measure — citation precision, claim alignment,
correct abstention — required parsing those informal answers heuristically,
which made every metric brittle and every regression invisible.

The system also needs a clear way to say *"I do not have evidence"*
without producing a plausible-sounding hallucination. That signal must
be a value in the response, not absence of text, so callers can act on
it programmatically.

## Decision

Every answer is a JSON object with `schema_version: 2`. The contract:

- `status` is one of `supported`, `partial`, `insufficient`. Other
  values are not permitted.
- `claims` is a list of `{target, claim, support, citations[]}`.
  Each `citation` has a `doc_id` and `chunk_id` that points back into
  the `evidence` list at the top level. Without those, the claim is
  unsupported by construction.
- `status_reason` is machine-readable: `{code, verified,
  verification_reasons[]}`. The eval pipeline keys off these.
- `evidence` at the top level holds the actual retrieved chunks with
  `doc_id`, `chunk_id`, `text`, and the metadata used to resolve
  them. Citations resolve into this list.
- `answer_text` is a human-readable summary. It is **not** part of
  the verifiable contract; tooling must not key off it.
- Insufficient answers carry an `insufficiency` block with
  `missing_targets` and a human-readable message, instead of a fake
  answer.

[`docs/answer-policy.md`](../answer-policy.md) is the working
reference; this ADR is the load-bearing decision behind it.

## Consequences

**Wins**

- Eval metrics (`citation_grounding`, `claim_citation_alignment`,
  `answer_format_compliance`) can be computed mechanically; the
  numbers in `reports/eval_summary.json` are real, not best-effort.
- The API demo can return `run_rag_query`'s dict verbatim
  (ADR-aligned with the FastAPI surface) because the response *is*
  the contract.
- Abstention becomes a first-class signal. Issue #69's work on
  partial-topic grounding has somewhere to put its decision
  (`partial` vs `insufficient`).

**Costs**

- Every behavior change that touches answers must consider whether
  it breaks this contract. The `schema_version` bump exists exactly
  so that incompatible changes are explicit.
- Free-text-only models cannot be dropped in without a wrapper that
  emits this shape.

## Alternatives considered

- **Free-text answer with inline citations parsed by regex.**
  Rejected: every metric becomes brittle and every reviewer
  inspection becomes manual.
- **Use a generic LangChain / agent-framework response model.**
  Rejected: those models change on someone else's schedule, and we
  need stability for the eval delta job to mean anything.
