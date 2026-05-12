# 0022: LangGraph orchestrator path for agentic_full presets — stage 1 (single-node passthrough)

- **Status**: accepted
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (naive_baseline reserved as direct-path ablation), [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) (agentic_full_llm under same retrieval surface), [ADR 0013](./0013-observability-as-additive-pluggable-surface.md) (trace backend additivity pattern this ADR reuses), issue #401, PR #404 (implementation), issue #453 (status flip)
- **Update (status flip, 2026-05-12, issue #453)**: Status promoted `proposed` → `accepted`. The stage-1 implementation merged via PR [#404](https://github.com/hskim-solv/BidMate-DocAgent/pull/404) (commit `349dd08`) lands all four sub-items from the Decision section: `requirements-graph.txt`, [`rag_graph_agentic_full.py`](../../rag_graph_agentic_full.py) (`AgenticFullState` TypedDict + `run_via_langgraph` entry point + process-cached compiled graph), [`rag_core.py:3673-3690`](../../rag_core.py) (env-var dispatch + `_skip_graph` recursion guard + `naive_baseline` bypass), and [`tests/test_langgraph_orchestrator_regression.py`](../../tests/test_langgraph_orchestrator_regression.py) (JSON-identity over `(agentic_full, agentic_full_llm) × (single-doc, comparison)` modulo timing fields, ADR 0001 invariant gate, module import smoke). The "What stage 2 will do" section below remains the unchanged forward plan and is *not* part of this status flip.

## Context

External senior review (2026-05) finding #2 argued the "Agentic RAG"
label is overstated because the pipeline is a procedural Python call —
no tool-call graph, no per-stage observability surface. The fair
critique: the agentic loop (`metadata_stage_sequence` strict → reduced
→ relaxed + verifier retry + answer build) is real but it is
*structurally* an inner for-loop inside one 426-line function in
`rag_core.py`, not a graph that an external reviewer can inspect.

Plan PR-H (Tier 3 of the project review response) calls for a
LangGraph migration that:

1. Adds `langgraph` as an opt-in dependency (CI default stays direct).
2. Wraps the `agentic_full` / `agentic_full_llm` flow in a StateGraph
   whose edges make the retry policy and the prompt-profile branch
   explicit.
3. Leaves `naive_baseline` on the direct path — ADR 0001's
   reproducibility invariant should not pay a langgraph-import cost
   for the minimal ablation surface.
4. Enables LangSmith / Langfuse multi-node traces (ADR 0013 backends)
   once the nodes are actually distinct.

The hard part is the JSON-identity guarantee. `run_rag_query` carries
dozens of cross-stage fields — `query_hash`, attempt index, timings,
stage transitions, conversation state, trace blocks, retrieved
`chunk_ids`, claims, citations, synthesis metadata — and reproducing
them through a multi-node graph risks subtle drift. A single regression
that flips a `latency_ms` ordering or a `pipeline_alias` field can
break every existing eval delta comparison and a slew of regression
tests.

## Decision (stage 1)

Land the **dispatch infrastructure and a single passthrough node**
*now*, defer the multi-node decomposition to stage 2 under its own ADR.

Concretely:

- New opt-in dependency file `requirements-graph.txt` with
  `langgraph>=0.6,<2.0`. **Not** added to `requirements.txt` — public
  CI never imports langgraph.
- New module `rag_graph_agentic_full.py` (root, flat-layout
  convention) exposing:
  - `AgenticFullState` `TypedDict` carrying inputs + the final
    `result` dict. Stage-1 schema is deliberately minimal; stage 2
    expands it as nodes split.
  - `run_via_langgraph(index, query, **kwargs) -> dict[str, Any]` —
    the entry point. Builds a one-node `StateGraph` whose single node
    calls back into `run_rag_query` with the **recursion-guard kwarg**
    `_skip_graph=True`. The graph is process-cached so successive calls
    skip the builder.
- `rag_core.run_rag_query` gains an env-var dispatch at the top:
  - `BIDMATE_ORCHESTRATOR=direct` (default) — existing call path,
    unchanged behavior.
  - `BIDMATE_ORCHESTRATOR=langgraph` + pipeline ≠ `naive_baseline` →
    delegate to `rag_graph_agentic_full.run_via_langgraph`. The
    recursion guard is the `_skip_graph` kwarg, kept private
    (underscore-prefixed) and absent from any external caller.
  - `naive_baseline` always stays on the direct path regardless of the
    env var (ADR 0001 invariant). The dispatch check inspects both
    `pipeline=` and `params.pipeline` to honor both kwarg shapes.
- New regression test `tests/test_langgraph_orchestrator_regression.py`:
  - `pytest.importorskip("langgraph")` so CI skips when the opt-in
    extra is absent.
  - Parametrized over `(pipeline, query)` for `agentic_full` and
    `agentic_full_llm` × two queries (single-doc + comparison) → asserts
    `json.dumps(..., sort_keys=True)` equality between direct and
    LangGraph paths.
  - A separate `test_naive_baseline_skips_langgraph_dispatch` pins the
    ADR 0001 policy: even with `BIDMATE_ORCHESTRATOR=langgraph` set,
    `naive_baseline` returns the direct-path result.
  - A `GraphModuleImportTest` smoke-tests the module's public symbols
    and the graph cache.

Single-node passthrough is the **JSON-identity-by-construction**
guarantee: the node literally calls the same `run_rag_query` body that
the direct path executes. Any future multi-node decomposition must
preserve that identity through explicit eval gates — this ADR is
stage 1 and intentionally postpones that work.

## What stage 2 will do (out of scope here)

Stage 2 (a separate ADR + issue) splits the single node into at least
three nodes:

- `analyze_query_node` — calls the existing `analyze_query` helper.
- `retrieve_loop_node` — wraps `metadata_stage_sequence` +
  `plan_retrieval` + `retrieve` with a conditional edge for verifier
  retry (the policy currently lives inside an inner `for stage in
  stage_sequence` loop).
- `build_answer_node` — calls `generate_answer` and, under the
  `agentic_full_llm` preset, also `synthesize_answer`.

The state schema in `AgenticFullState` is deliberately small in stage
1 so that stage 2 can expand it without breaking any field the
JSON-identity test currently checks (because stage 1 only checks the
final `result` dict, the intermediate fields are unobserved here).

## Consequences

Easier:

- The "Agentic RAG" label gets a concrete operational meaning —
  `BIDMATE_ORCHESTRATOR=langgraph` produces a StateGraph that a
  reviewer can inspect, even if stage 1's graph has one node.
- Stage 2's multi-node decomposition lands on top of an already-wired
  dispatch path. The risky JSON-identity work is bounded to the per-node
  output assembly; the dispatch + dependency + test harness are paid
  for in this ADR.
- Test coverage: ADR 0001 invariant for `naive_baseline` is now
  pinned by an explicit test, not just doc convention.

Costs / honesty:

- A single-node graph adds zero per-stage observability vs the direct
  path. Stage 1 explicitly does NOT claim a "now we can see
  per-stage latencies in LangSmith" benefit — that ships in stage 2.
- LangGraph version range (`>=0.6,<2.0`) is broad. If LangGraph 2.x
  introduces a breaking API the stage-2 ADR re-pins it.
- The `_skip_graph` kwarg is a private API contract — external
  callers must never pass it. Underscore prefix + ADR mention is the
  signal; the type signature is otherwise unchanged.

## Alternatives considered

- **Skip stage 1, ship the full multi-node decomposition.** Rejected:
  JSON-identity regression risk against `run_rag_query`'s
  ~426-line output assembly is real, and a stage-2 PR that breaks
  any of the existing 650+ regression tests would block on debugging
  rather than design. Splitting the work bounds the risk.
- **Add `langgraph` to `requirements.txt` (always-on).** Rejected:
  langgraph + its dependency tree (`langchain-core`, `pydantic`, ...)
  inflates every CI install and Docker image for what is, in stage 1,
  a pure passthrough. ADR 0011 / ADR 0013's "additive opt-in"
  pattern says opt-in extras live in their own requirements file.
- **Use a thread-local recursion guard instead of `_skip_graph`
  kwarg.** Rejected: thread-locals are invisible at the call site
  (callers can't see the contract). A private kwarg is explicit and
  testable.
- **Migrate `naive_baseline` to LangGraph too.** Rejected by ADR
  0001 — the minimal ablation surface should not depend on an opt-in
  extra. If the LangGraph dependency is missing, `naive_baseline`
  must still run.

## See also

- [`rag_graph_agentic_full.py`](../../rag_graph_agentic_full.py) — the
  stage-1 graph module.
- [`requirements-graph.txt`](../../requirements-graph.txt) — the
  opt-in dependency.
- [`tests/test_langgraph_orchestrator_regression.py`](../../tests/test_langgraph_orchestrator_regression.py)
  — the JSON-identity + ADR-0001 dispatch tests.
- [ADR 0001](./0001-preserve-naive-baseline.md) — naive_baseline policy
  this ADR explicitly preserves.
- [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) — the
  additive opt-in pattern this ADR reuses.
- [ADR 0013](./0013-observability-as-additive-pluggable-surface.md) —
  the trace-backend additivity pattern that stage 2 will reuse for
  LangSmith / Langfuse integration.
