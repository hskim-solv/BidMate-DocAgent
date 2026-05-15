# 0011: LLM answer synthesis as additive ablation

(Originally landed as ADR 0007 in [#142](https://github.com/hskim-solv/BidMate-DocAgent/pull/142); renumbered to 0011 to resolve a filesystem collision with the foundational [`0007-issue-linked-branch-naming.md`](./0007-issue-linked-branch-naming.md) governance ADR which landed first.)

- **Status**: proposed
- **Date**: 2026-05-11
- **Related**: extends [ADR 0001](./0001-preserve-naive-baseline.md); preserves [ADR 0003](./0003-structured-answer-citation-contract.md); reuses backend pattern from [ADR 0006](./0006-llm-judge-on-real-data-only.md); **complemented by** [ADR 0024](./0024-agentic-full-llm-as-api-default.md) (API preset default flips to `agentic_full_llm`; backend default stays `stub`); implementation walkthrough in [`docs/agentic/answer-policy.md`](../agentic/answer-policy.md#계약-강제-메커니즘)
- **Deciders**: hskim
- **Update (PR-I, issue #405, 2026-05-12)**: the API surface default preset flips from `agentic_full` to `agentic_full_llm` ([ADR 0024](./0024-agentic-full-llm-as-api-default.md)). The *backend* additivity contract this ADR established stays unchanged — `BIDMATE_SYNTHESIS_BACKEND=stub` is still the default, so a public API call runs the LLM synthesis preset under the deterministic stub renderer. CLI (`naive_baseline`, ADR 0001) and function-level (`agentic_full`) defaults are untouched.

## Context

The pipeline is extractive end-to-end: `generate_answer` in
[`rag_core.py:L2242`](../../rag_core.py) builds `claims` from retrieved
sentences and renders `answer_text` by concatenating those claims with
their chunk-id suffixes (`render_answer_text` at `L2494`). The design
keeps the public demo deterministic, free, and hallucination-bounded —
every cited string is verbatim from an evidence chunk.

That trade-off is correct for grounding rigor, but it leaves three gaps
visible to a reader of the system:

1. **Read flow is mechanical.** `render_answer_text` joins claim
   strings with `[chunk_id]` suffixes; the prose does not read like an
   answer a human would write, and comparison answers in particular
   read as parallel bullet lists rather than as analysis.
2. **No LLM surface exists in the pipeline at all.** Prompt
   engineering, structured output, tool use, and prompt caching —
   table-stakes skills for an AI-engineer surface in 2026 — have
   nowhere to live. The system can be evaluated as a retrieval system
   but not as an LLM application.
3. **Cost / latency / model trade-offs are not part of the eval
   matrix.** ADR 0006 introduced an LLM on the real-data eval surface
   as a *judge*; there is no comparable surface for the system itself.

Reversing the extractive default would conflict with ADR 0001 (preserve
the simpler-path baseline) and put the ADR 0003 citation contract at
risk. The right move is the same shape as ADR 0001's defense of the
naive baseline: **keep the extractive path as a first-class baseline
and add LLM synthesis alongside it.**

## Decision

LLM answer synthesis is permitted as an **additive** ablation path,
not a replacement. Specifically:

- A new `prompt_profile` value, `llm_synthesis`, is introduced in
  [`rag_core.py`](../../rag_core.py) alongside `minimal_grounded_extractive`
  (naive) and `structured_grounded_claims` (agentic_full extractive).
- A new `PIPELINE_PRESETS` entry, `agentic_full_llm`, sets
  `prompt_profile=llm_synthesis` and inherits the rest of `agentic_full`'s
  retrieval / verifier configuration.
- Both `agentic_full` (extractive) and `agentic_full_llm` (LLM) appear
  as ablation runs in [`eval/config.yaml`](../../eval/config.yaml), so
  every eval invocation produces a side-by-side comparison. `agentic_full`
  remains the regression guard; `agentic_full_llm` is the new column.
- `naive_baseline` is **unchanged**. ADR 0001's invariant is preserved.

### Contract preserved (ADR 0003)

`generate_answer` continues to return the `schema_version: 2` JSON.
The LLM synthesis path:

- **Reuses** `build_claims` to produce the claim list. Claims and
  citations are still extractive — `chunk_id` references resolve into
  the same `evidence` list.
- **Rewrites only `summary` and `answer_text`.** The LLM is given
  `(query, analysis, claims, evidence_chunks)` and produces a
  human-readable summary plus a longer-form `answer_text`. Both are
  outside the verifiable contract per ADR 0003 ("`answer_text` is …
  not part of the verifiable contract; tooling must not key off it").
- **Cannot introduce new citations.** If the LLM emits a chunk id not
  present in `evidence`, the synthesis is rejected and the renderer
  falls back to the extractive `render_answer_text`. This guard is a
  hard postcondition, not a soft check.
- **Cannot change `status`, `claims`, `insufficiency`, or
  `status_reason`.** Those are computed by the deterministic verifier
  *before* synthesis runs, and synthesis sees them as inputs only.

If `status != supported`, synthesis is skipped entirely and the
extractive path runs as today. Abstention messages remain deterministic.

### Backend pluggability

Reuses the ADR 0006 pattern: `BIDMATE_SYNTHESIS_BACKEND`:

- `stub` (default) — deterministic fixture; concatenates claims into a
  templated paragraph. No network. Used by `make smoke`, `pr-eval.yml`,
  and tests.
- `anthropic` — Claude API (Sonnet 4.6 default, Haiku 4.5 opt-in via
  `BIDMATE_SYNTHESIS_MODEL`). Requires `ANTHROPIC_API_KEY`. Uses prompt
  caching for the system prompt + few-shot examples (≥ 80% token
  reduction across a real-eval run). Tool use is used to enforce the
  output shape `{summary: str, answer_text: str, used_chunk_ids: list[str]}`.
- `openai_compatible` — generic OpenAI-compatible endpoint; same
  shape, same guard. Lets vLLM / llama.cpp / Solar / KURE-finetuned
  models be swapped in for the Korean-stack story without touching
  the pipeline.

### Cadence

- **Public synthetic CI**: `BIDMATE_SYNTHESIS_BACKEND=stub`. Eval delta
  job continues to compare `naive_baseline` vs `agentic_full` (both
  deterministic) and reports `agentic_full_llm` as an *additional*
  column with the stub backend. The stub is enough to exercise the
  plumbing and lock the contract; it is not a quality claim about the
  real LLM.
- **Real-data eval**: `BIDMATE_SYNTHESIS_BACKEND=anthropic`. Aggregate
  metrics for the LLM column cross the ADR 0005 commit boundary; raw
  prompts and raw model responses stay local. Token counts and
  per-query cost are aggregated and committable.
- **Live demo**: `anthropic` backend, rate-limited, prompt-cached.

## Consequences

**Wins**

- The system gains an LLM surface (prompt engineering, structured
  output, tool use, prompt cache, streaming) without putting ADR 0003
  at risk. The citation contract is mechanically preserved by the
  "no new chunk_ids" guard.
- The eval matrix grows by one column. `agentic_full` (extractive,
  deterministic) and `agentic_full_llm` (LLM, stub or live) sit side
  by side, so the LLM path has to *earn* its slot the same way the
  agentic pipeline had to under ADR 0001.
- A latency / cost frontier becomes legible: extractive is ~ms,
  stub-LLM adds negligible overhead, anthropic-LLM adds tokens + ms.
  Future ADRs on caching / model choice have a measurable baseline.
- Reuses the ADR 0006 backend pattern, so there is one consistent
  "how to add an LLM" idiom in the codebase.

**Costs**

- Three answer-rendering paths to keep working: extractive,
  stub-LLM, live-LLM. Mitigated by the shared input contract — all
  three consume the same `(answer_dict, evidence)` and produce
  `answer_text`. A single regression test exercises all three.
- Token spend per live-eval run. Bounded by manual cadence on
  real-data (~ 100 cases × cached prompt) and by `stub` default on
  public CI. Cost numbers go in `reports/real100/aggregate.json` so
  the spend is visible.
- One more environment variable family for users to understand.
  Mitigated by the default being `stub` (works offline, no key).

**Constraints (unchanged)**

- ADR 0001: `naive_baseline` stays in
  [`pipeline_cli_choices()`](../../rag_core.py) and remains the CLI
  default.
- ADR 0003: `schema_version: 2`, `status` values, `claims[].citations`,
  and `evidence[]` are unchanged. `schema_version` does **not** bump.
- ADR 0005: real-data per-case LLM outputs stay local. Aggregates
  (mean cost, mean latency, citation_precision delta) commit.

## Additive opt-in pattern (generalization)

ADR 0011 established a recurring pattern that later ADRs 0015, 0017, and 0027 reused verbatim. Those ADRs are consolidated here as Superseded; their decisions remain unchanged. The pattern is:

1. **Default is deterministic and free.** A `stub` (or `regex`) backend runs on every CI invocation — no network, no cost, reproducible.
2. **Opt-in via a single env-var.** `BIDMATE_<FEATURE>_BACKEND` dispatches: `stub` (default) | `anthropic` | `openai_compatible`. Unknown/failing backend silently degrades to stub.
3. **Never changes upstream contract.** The feature writes to a *diagnostics* or *additive ablation row* surface; it cannot modify `answer.status`, `claims`, `citations`, or `naive_baseline` metrics.
4. **One new ablation row in `eval/config.yaml`.** The feature is measurable as a column, not just a code path.
5. **Stub-matches-baseline invariant is a contract test.** `test_*_baseline_invariant.py` verifies byte-equality between stub-backend output and the deterministic baseline.

**Instances consolidated here:**

| ADR | Feature | Env-var | Stub invariant |
|-----|---------|---------|---------------|
| 0015 | Cost telemetry (tokens, USD estimate) | n/a — diagnostics only | `SYNTHESIS_SCHEMA_VERSION` bump; unknown model → `None` |
| 0017 | LLM metadata extraction | `BIDMATE_METADATA_BACKEND` | `stub` delegates to `regex`; byte-equal |
| 0027 | LoRA embedding adapter | `BIDMATE_EMBEDDING_LORA_ADAPTER` | unset = pre-#434 byte-identical; lazy PEFT import |

## Alternatives considered

- **Replace the extractive path with LLM synthesis entirely.**
  Rejected: conflicts with ADR 0001's preservation argument and
  removes the regression guard against LLM-introduced citation
  drift. Loses the deterministic CI surface.
- **Add LLM synthesis only behind a CLI flag, not as a named
  preset.** Rejected: ADR 0001's argument applies — silent paths
  rot. If LLM synthesis is worth shipping it should be a named
  preset that runs on every eval invocation, so its delta against
  `agentic_full` is always visible.
- **Let the LLM also rewrite `claims` and `citations`.**
  Rejected for now: violates ADR 0003 by construction (citations
  would no longer be guaranteed to resolve into `evidence`). Revisit
  as a follow-up ADR with a stricter citation-validation pass
  (every emitted chunk_id must resolve; every claim must cite ≥ 1
  chunk) and `schema_version: 3`.
- **Use a free-text LLM endpoint without tool use / structured
  output.** Rejected: the postcondition that `used_chunk_ids ⊆
  evidence.chunk_ids` becomes brittle to parse. Tool use makes the
  guard a simple set-membership check.
