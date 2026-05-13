# 0035: Answer dict — no parallel Pydantic / TypedDict shadow model

- **Status**: accepted
- **Date**: 2026-05-13
- **Related**: [ADR 0003](0003-structured-answer-citation-contract.md) (answer contract, `schema_version: 2`), [`CLAUDE.md` §Prohibited](../../CLAUDE.md), [`api/schemas.py`](../../api/schemas.py) (boundary-only Pydantic usage), [issue #451](https://github.com/hskim-solv/BidMate-DocAgent/issues/451)

## Context

`run_rag_query` returns a plain Python `dict` pinned by ADR 0003 (`schema_version: 2`,
`status`, `claims[{target, claim, support, citations[]}]`, `evidence[…]`).
`CLAUDE.md` §"Prohibited" states: *"Adding a parallel pydantic / TypedDict model that shadows `run_rag_query`'s answer dict — the dict is the contract."*

This prohibition existed as a single prose line. External senior review (2026-05, §A2-S4)
re-raised Pydantic v2 validation, citing runtime safety and IDE ergonomics. Without
a written ADR the prohibition cannot survive repeated questioning — this document
converts the one-liner into an explicit trade-off record.

Two pressures collide:
1. **Single source of truth**: ADR 0003 already pins the contract. A parallel model
   creates two authoritative definitions that can silently diverge.
2. **Validation safety**: callers may want type-checked access; raw dict access is
   error-prone. The right answer is *where* validation lives, not whether it exists.

## Decision

The answer dict produced by `run_rag_query` is the internal contract.
No Pydantic / TypedDict / dataclass model may shadow it *inside the pipeline*.

**What is allowed:**

- `api/schemas.py` may define a Pydantic model that validates the dict at the
  FastAPI response boundary (`Answer.model_validate(result)`). This is downstream
  of `run_rag_query` — never inside retrieval, verification, or answer-generation.
- Internal helper functions may use `TypedDict` for IDE hints, provided the type
  annotation is never load-bearing at runtime (no `isinstance` checks, no
  `.model_dump()` round-trips through the pipeline).

**Schema change protocol**: any new field in the answer dict first lands in the
dict (with a default for backward compat), then in `api/schemas.py`, then in the
eval runner. Never the reverse.

## Consequences

**Easier:**
- One change to add or rename a field: edit `run_rag_query`'s return block and the
  eval runner. No model sync step.
- CI eval stays bit-identical: no serialization round-trip can silently drop a field.
- `schema_version` bumps stay meaningful — they track the dict contract, not model
  version drift.

**Harder / constrained:**
- No auto-generated OpenAPI schema from the pipeline layer. `api/schemas.py` must
  be kept in sync manually when the dict evolves.
- IDE autocomplete on raw dict keys is weaker than on a typed model. The TypedDict
  escape hatch addresses this without polluting the runtime contract.

**Contract locked in:**
- `schema_version: 2` literal in `rag_answer.py` (`ANSWER_SCHEMA_VERSION`).
- `status` enum: `supported | partial | insufficient` — callers must not branch on
  any other string.
- Eval pipeline (`eval/run_eval.py`) keys off `status_reason.code` and
  `claims[].citations[].chunk_id` — changes here require a version bump and eval
  regression check.

## Alternatives considered

- **Full Pydantic v2 internal model**: rejected. Every `run_rag_query` call would
  carry a `.model_validate()` + `.model_dump()` round-trip. More critically, the
  dict and the model become two sources of truth — a schema change touches both,
  and a merge conflict silently produces a stale model while the dict is correct.
- **JSON Schema external validation**: tracked as eval-side contract check, not
  runtime pipeline guard. Does not conflict with this ADR; orthogonal to internal
  typing.
- **Pydantic at API boundary only (chosen pattern)**: validates the output exactly
  once, at the surface exposed to external callers. No dual contract inside the
  pipeline; runtime cost is O(1) per request at the FastAPI layer, not per
  internal function call.
