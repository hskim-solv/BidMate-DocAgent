# 0023: agentic_full_llm as API default (preset only; backend default stays stub)

- **Status**: accepted
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (CLI default stays naive_baseline), [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) (complemented — backend additive opt-in stays), [ADR 0022](./0022-langgraph-orchestration-stage-1.md) (orthogonal — orchestrator path also opt-in), issue #405

## Context

External senior review (2026-05) finding #1 and #2 critiqued the
mismatch between the "Agentic RAG" README label and the API surface
default. A reviewer hitting `POST /query` without specifying a
`pipeline` parameter got `agentic_full` — the extractive
`structured_grounded_claims` preset — and concluded the project is
"extractive-only by design." Technically true (ADR 0001 reserves
`naive_baseline` as the minimal ablation; ADR 0011 added `agentic_full_llm`
as additive opt-in), but the *default surface* did not match the
public framing.

[ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) lands LLM
answer synthesis as an *additive* preset that swaps the
`answer_text` / `summary` rendering under the `agentic_full_llm`
preset, with the *backend* opt-in via
`BIDMATE_SYNTHESIS_BACKEND` (default `stub`, deterministic). The "no
new chunk_ids" guard preserves the ADR 0003 citation contract; if the
LLM cites a chunk_id outside the retrieved evidence the synthesis is
rejected and the extractive renderer fallback runs.

The reviewer's critique is fair *at the API surface*: even though
`agentic_full_llm` exists, a default API call surfaces
`agentic_full`. PR-I is the "conservative absorb" — flip the API
preset default without flipping the backend default. ADR 0011 stays
accepted; this ADR is a *complement* (not supersede) and lands the
preset-level dispatch change while preserving the backend-level
additivity that ADR 0011 secured.

## Decision

**Three policy lines, three distinct defaults — pinned in code and
tests:**

1. **CLI default (`app.py`, `rag_pipeline_presets.DEFAULT_CLI_PIPELINE_NAME`)
   stays `naive_baseline`.** ADR 0001 reproducibility invariant.
2. **Function-level default
   (`rag_pipeline_presets.DEFAULT_RAG_PIPELINE_NAME`,
   `run_rag_query(pipeline=…)`) stays `agentic_full`.** Direct callers
   in `eval/run_eval.py`, `scripts/run_benchmark.py`,
   `demo/streamlit_app.py`, and the test suite keep their existing
   behavior. Anyone calling `run_rag_query(…)` without `pipeline=`
   continues to get the same preset they got before this ADR.
3. **API surface default (`api/main.py:DEFAULT_API_PIPELINE`) flips
   to `agentic_full_llm`** — this ADR's only code change.

The *backend* default stays `BIDMATE_SYNTHESIS_BACKEND=stub` (ADR 0011
unchanged). A default API call therefore runs the
`agentic_full_llm` preset's structured-grounded-claims retrieval +
the **stub synthesis** renderer, which is deterministic, token-less,
and CI-reproducible. Real LLM synthesis activates only when an
operator sets `BIDMATE_SYNTHESIS_BACKEND=anthropic` (or
`openai_compatible`) — exactly the surface ADR 0011 created.

The three boundaries are pinned by explicit regression tests
(`tests/test_api_default_pipeline_regression.py`) so a future contributor
cannot silently collapse them.

## Why the "preset only, not backend" split

Flipping the backend default to `anthropic` or `openai_compatible`
along with the preset would:

- Make `pytest` require `ANTHROPIC_API_KEY` or
  `BIDMATE_SYNTHESIS_API_KEY`. CI can't fake a key for a real API
  call, so the public test suite would skip or fail.
- Add real per-query cost on every API hit, including healthcheck
  probes and demo traffic.
- Break the public `eval/run_eval.py` ablation determinism (the
  `full_llm` row currently reports the stub-backend result; see
  `docs/embedding-ablation.md` and ADR 0012 for the same pattern).
- Erase ADR 0011's central trade-off: *the agentic synthesis preset is
  observable, but the backend is opt-in.*

Flipping the preset alone preserves all of the above. The API
consumer sees `diagnostics.pipeline == "agentic_full_llm"` (the
"Agentic" label matches the response) but the renderer still runs
deterministically. A reviewer wanting the real LLM response sets the
backend env var locally — same flow as before, just exposed via a
different default preset.

## Consequences

Easier:

- The "Agentic RAG" README label now matches the default API
  experience without paying ADR 0001's reproducibility cost. CLI
  reviewers still get the minimal extractive baseline; API consumers
  see the agentic synthesis preset.
- ADR 0011's "additive opt-in" stays meaningful at the backend
  level — the place it actually buys reproducibility / cost
  insurance.
- Three default boundaries are now individually tested
  (`test_cli_default_is_unchanged_naive_baseline`,
  `test_function_level_default_is_unchanged_agentic_full`,
  `test_module_constant_pins_agentic_full_llm`), so future silent
  drift is caught at PR-eval time.

Costs / honesty:

- `agentic_full_llm` + stub backend has the same retrieval +
  verifier surface as `agentic_full`, but a different
  `prompt_profile` (`llm_synthesis` vs `structured_grounded_claims`).
  The stub synthesis renderer produces a slightly different
  `answer_text` shape than the extractive renderer would. Consumers
  comparing API responses before / after this ADR will see a real
  textual diff in `answer_text` (the `claims` and `citations` arrays
  stay extractive by ADR 0003 contract).
- The function-level default stays `agentic_full` to bound the blast
  radius. Anyone reading the code without ADR 0024 might wonder why
  CLI / eval / API have *different* defaults — the three regression
  tests + this ADR are the answer.

## Alternatives considered

- **Flip `DEFAULT_RAG_PIPELINE_NAME` too (function-level).** Rejected:
  silently changes `eval/run_eval.py` / `scripts/run_benchmark.py` /
  `demo/streamlit_app.py` /  the regression test suite's implicit
  default. The "one PR, one concern" rule (CLAUDE.md) says these are
  separate consumer surfaces with separate justifications.
- **Flip the synthesis backend default too (stub → anthropic).**
  Rejected — see "Why the 'preset only, not backend' split" above.
  CI determinism + per-call cost are real concerns.
- **Add a query-level `default` flag instead of changing the
  constant.** Rejected: shifts the decision to every caller without
  resolving the README-vs-default mismatch the reviewer flagged.
- **Document the existing default + change the README framing only.**
  Rejected: the reviewer's critique is the *behavior*, not the prose.
  A reader who runs `curl localhost:8000/query` and sees
  `agentic_full` is not persuaded by a README clarification.
- **Supersede ADR 0011 entirely.** Rejected: ADR 0011 secures the
  *backend-level* additivity that this ADR keeps. Superseding would
  imply backend-default change too, which we explicitly do not want.
  Complement-not-supersede is the right relationship.

## See also

- [`api/main.py`](../../api/main.py) — `DEFAULT_API_PIPELINE` constant
  and `_resolve_default_pipeline()` chain.
- [`tests/test_api_default_pipeline_regression.py`](../../tests/test_api_default_pipeline_regression.py)
  — pins the three default boundaries.
- [ADR 0001](./0001-preserve-naive-baseline.md) — CLI default policy.
- [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) — the
  additive synthesis surface this ADR complements (not supersedes).
