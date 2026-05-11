# 0017: LLM Metadata Extraction as Additive Backend (extends 0011)

- **Status**: proposed
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [#180](https://github.com/hskim-solv/BidMate-DocAgent/issues/180), [ADR 0001](./0001-preserve-naive-baseline.md), [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md)

## Context

The metadata available to the retrieval / answer path today comes
from [`ingestion.normalize_metadata`](../../ingestion.py), which
reads structured CSV columns plus deterministic regex parsing
(budget normalization, ISO date coercion). For documents whose CSV
row is incomplete or whose body carries unstructured fields
(`contact_email`, `contact_name`), the regex path has a hard
ceiling — there is no signal to give it.

[ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) already
established the additive-LLM-backend pattern in
[`rag_synthesis.py`](../../rag_synthesis.py): a deterministic stub
default, an opt-in `anthropic` tool-use backend, an
openai-compatible alternative, prompt caching on tools + system,
and a graceful fallback when SDKs or keys are missing. Issue #180
needs the same shape for metadata extraction so we can compare
LLM-extracted metadata to the regex baseline on the existing eval
surface without breaking [ADR 0001](./0001-preserve-naive-baseline.md)'s
naive-baseline invariant.

## Decision

Add a new [`rag_metadata_extraction`](../../rag_metadata_extraction.py)
module mirroring `rag_synthesis` one-for-one:

- Public entry point `extract_rfp_metadata(document, backend=...)`
  returns a typed `MetadataExtraction` dataclass with the eight
  fields named in #180: `agency`, `project_name`, `budget_amount`,
  `budget_currency`, `deadline_iso`, `submission_date_iso`,
  `contact_email`, `contact_name`.
- Backends (`BIDMATE_METADATA_BACKEND`): `regex` (default —
  preserves the ADR 0001 invariant), `stub` (delegates to `regex`
  so stub-mode runs are byte-for-byte identical), `anthropic_tool_use`,
  `openai_function_call`.
- The `stub` ↔ `regex` byte-equivalence is a **contract unit test**.
  It guarantees stub-mode runs produce zero LLM cost AND zero schema
  drift, so downstream consumers (eval ablation rows, dashboards)
  stay stable when the LLM path is not enabled.
- Tool definition `extract_rfp_metadata` is conservative: every
  field is optional and `additionalProperties: false` so the LLM
  cannot smuggle unstructured payloads through.
- On any backend exception, `extract_rfp_metadata` falls back to
  `_regex_backend`. The pipeline never silently loses metadata
  because of an SDK or network failure.
- Body text is truncated to ~8000 chars before being sent to an
  LLM. For very long RFPs the truncation may drop late-section
  contacts; this is acceptable for the first iteration and is
  revisited only if the eval shows non-trivial regression vs
  regex on the truncation cohort.

## Consequences

- A reader familiar with `rag_synthesis` understands
  `rag_metadata_extraction` in one pass: same env-keyed activation,
  same `# pragma: no cover - network` isolation on real backends,
  same stub-matches-baseline contract test, same eight-field schema
  surfaced as a dataclass.
- Locks the metadata vocabulary at the eight #180 fields. Adding a
  new field is a schema change — it needs an ADR revision because
  the eval comparison table downstream of #180 is keyed on this
  exact shape.
- LLM extraction is opt-in by env var, never automatic. The
  ingestion path is unchanged; the LLM path is invoked only by the
  eval ablation row that asks for it (`agentic_full_llm_metadata`,
  added in a follow-up PR).
- Cost surface follows ADR 0011's pricing card pattern: when the
  LLM ablation runs, it inherits the same `compute_cost_usd` hook
  in `rag_synthesis` (Sonnet 4.6 default) so a refactor that 10×s
  metadata-extraction token spend would be flagged the same way as
  one that 10×s answer-synthesis spend.

## Alternatives considered

- **Bury the LLM call inside `ingestion.normalize_metadata`.**
  Rejected — couples a deterministic CSV reader to a network
  backend and breaks the ADR 0001 invariant by default. Any opt-in
  surface that depends on `normalize_metadata` would have a
  conditional import path, which is exactly the smell ADR 0011
  avoided.
- **Skip the stub backend and gate tests on a mock `anthropic`
  client.** Rejected — the same approach in `rag_synthesis` is
  proven to keep CI deterministic without mocking SDKs. Mocks
  drift; the stub-matches-baseline invariant is checked every PR.
- **JSON-mode (no tool / function call) on OpenAI.** Rejected —
  the tool / function-call surface gives a structured schema
  contract. Raw JSON mode is fragile to model-side hallucinations
  and would duplicate the `additionalProperties: false`
  enforcement at the parser layer.
