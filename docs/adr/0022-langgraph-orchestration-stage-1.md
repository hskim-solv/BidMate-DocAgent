# 0022: LangGraph orchestrator path for agentic_full presets — stages 1 (passthrough) & 2 (multi-node)

- **Status**: accepted
- **Date**: 2026-05-12 (stage 1) / 2026-05-13 (stage 2)
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (naive_baseline reserved as direct-path ablation), [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) (agentic_full_llm under same retrieval surface), [ADR 0013](./0013-observability-as-additive-pluggable-surface.md) (trace backend additivity pattern this ADR reuses), issue #401 (stage 1) / PR [#404](https://github.com/hskim-solv/BidMate-DocAgent/pull/404) (stage 1 implementation) / issue #453 (stage 1 status flip), issue #457 (stage 2) / PR [#458](https://github.com/hskim-solv/BidMate-DocAgent/pull/458) (stage 2 implementation)
- **Update (status flip, 2026-05-12, issue #453)**: Status promoted `proposed` → `accepted`. The stage-1 implementation merged via PR [#404](https://github.com/hskim-solv/BidMate-DocAgent/pull/404) (commit `349dd08`) lands all four sub-items from the Decision section: `requirements-graph.txt`, [`rag_graph_agentic_full.py`](../../rag_graph_agentic_full.py) (`AgenticFullState` TypedDict + `run_via_langgraph` entry point + process-cached compiled graph), [`rag_core.py:3673-3690`](../../rag_core.py) (env-var dispatch + `_skip_graph` recursion guard + `naive_baseline` bypass), and [`tests/test_langgraph_orchestrator_regression.py`](../../tests/test_langgraph_orchestrator_regression.py) (JSON-identity over `(agentic_full, agentic_full_llm) × (single-doc, comparison)` modulo timing fields, ADR 0001 invariant gate, module import smoke).
- **Update (stage 2 land, 2026-05-13, issue #457)**: Stage-2 multi-node decomposition merged. `rag_graph_agentic_full.py` now compiles a three-node StateGraph (analyze / retrieve_loop / build_answer) with a conditional edge after analyze. `rag_core.py` exposes `_RunContext` + `_build_run_context` + `_phase_analyze` / `_phase_retrieve_loop` / `_phase_build_answer` extracted from the legacy `run_rag_query` body; both the direct path and the graph nodes call the same `_phase_*` helpers so JSON-identity holds by construction. `tests/test_langgraph_orchestrator_regression.py` adds `GraphStructureStage2Test` (3-node assertion + conditional-edge router contract + phase-helper public surface) and `test_phase_analyze_short_circuits_for_context_clarification`. Existing 4 JSON-identity tests continue to pass without modification — confirming the by-construction claim.

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

## Decision (stage 2)

Split the single passthrough node into three phase nodes that mirror
the analyze / retrieve / build phases inside the legacy
`run_rag_query` body. Crucially, the nodes do **not** re-implement the
orchestration in the graph module — that would carry exactly the
JSON-identity regression risk this ADR's two-stage split exists to
avoid. Instead, three private helpers extracted from `run_rag_query`'s
body in `rag_core.py` become the single source of truth, and both the
direct path and the graph nodes call them:

- `rag_core._RunContext` — a private mutable dataclass that carries
  every cross-phase field (`retrieval_query`, `analysis`,
  `stage_sequence`, `evidence`, `verified`, `verification_reasons`,
  `retrieved_chunk_ids`, `plan`, trace handle, timings, ...) so the
  three phases can run either inline or threaded through LangGraph
  state.
- `rag_core._build_run_context(...)` — moves the `params=` bundle
  normalization, pipeline-preset resolution, `_PROCESS_WARM`
  cold-start flag, query hashing, `query_start` log, and
  trace-backend startup out of `run_rag_query`'s body. The LangGraph
  entry point calls this *before* graph invocation so all three nodes
  see the same context.
- `rag_core._phase_analyze(ctx) -> dict | None` — runs the two
  `analyze_query` iterations, conversation-context resolution, and the
  metadata-ambiguity / needs-clarification short-circuit checks.
  Returns a final result dict if the phase short-circuits, otherwise
  `None` after mutating `ctx`. The LangGraph router
  (`_route_after_analyze`) reads this signal and routes to `END`
  (early return) or `retrieve_loop` (continue) via a conditional edge.
- `rag_core._phase_retrieve_loop(ctx)` — runs the
  `metadata_stage_sequence` strict → reduced → relaxed retry loop with
  `make_plan` + `retrieve` + `verify_evidence` per attempt, then
  applies `select_supporting_evidence` and computes
  `retrieved_chunk_ids`.
- `rag_core._phase_build_answer(ctx) -> dict` — runs `generate_answer`
  (plus `synthesize_answer` under `agentic_full_llm`), updates
  conversation state, assembles `diagnostics` and the final `result`
  dict in the same key order as the legacy body, attaches trace
  diagnostics, and emits the `query_complete` log line.

The new `run_rag_query` body is:

```python
ctx = _build_run_context(...)
early_result = _phase_analyze(ctx)
if early_result is not None:
    return early_result
_phase_retrieve_loop(ctx)
return _phase_build_answer(ctx)
```

…and the LangGraph nodes are thin wrappers around the same three
phase calls. JSON-identity is therefore preserved by construction —
the phase functions are literally the moved-out blocks of the legacy
body, executed in the same order with the same inputs. The regression
test `tests/test_langgraph_orchestrator_regression.py` (which compares
`json.dumps(..., sort_keys=True)` byte-equality between
`BIDMATE_ORCHESTRATOR=direct` and `=langgraph` for two queries × two
presets) keeps passing without modification.

`AgenticFullState` was a small TypedDict in stage 1 (`index`,
`query`, `pipeline_kwargs`, `result`); stage 2 replaces those fields
with a single mutable `ctx` slot plus the same terminal `result` slot.
The intermediate fields all live on `_RunContext`, so the TypedDict
stays minimal even as the orchestration becomes explicit.

The stage-1 recursion guard (`_skip_graph` kwarg) is no longer needed
for correctness — stage 2 nodes call `_phase_*` directly, not back
into `run_rag_query` — but the kwarg is retained as a private "force
direct path" override for callers that need deterministic dispatch
independent of the environment variable.

Stage-2 specific tests added alongside the stage-1 JSON-identity ones:

- `GraphStructureStage2Test.test_graph_has_three_phase_nodes` — pins
  that the compiled graph carries `analyze` / `retrieve_loop` /
  `build_answer` so a future refactor cannot silently collapse it
  back to a passthrough.
- `GraphStructureStage2Test.test_route_after_analyze_branches_on_result_presence`
  — pins the conditional-edge contract: `result` present ⇒ END,
  otherwise ⇒ `retrieve_loop`.
- `GraphStructureStage2Test.test_phase_helpers_exposed_from_rag_core`
  — `rag_core` keeps exposing `_build_run_context`, `_phase_analyze`,
  `_phase_retrieve_loop`, `_phase_build_answer`; a rename would
  surface here instead of at first dispatch.
- `test_phase_analyze_short_circuits_for_context_clarification` —
  whichever path the phase takes (short-circuit or continue), the
  state it hands off matches the contract the next phase or the
  caller expects.

## Consequences

Easier:

- The "Agentic RAG" label gets a concrete operational meaning that
  matches the code: `BIDMATE_ORCHESTRATOR=langgraph` now runs a
  three-node StateGraph (not a one-node passthrough) where every node
  is inspectable, and per-stage latencies in LangSmith / Langfuse map
  cleanly to the three phases.
- Single source of truth for orchestration: `_phase_*` helpers run
  whether the caller used the direct path or the graph path, so the
  two cannot drift.
- The risky JSON-identity work was bounded to the dispatch + harness
  work in stage 1; stage 2 needed zero changes to the regression
  test contract.
- ADR 0001 invariant for `naive_baseline` is pinned by an explicit
  test, not just doc convention.

Costs / honesty:

- `_RunContext` is a 30+ field private dataclass — large, but each
  field is one that the legacy body already carried as a local
  variable. The dataclass makes the cross-phase contract *explicit*
  rather than *implicit* in the function-scoped locals.
- LangGraph version range (`>=0.6,<2.0`) is broad. If LangGraph 2.x
  introduces a breaking API, the dispatch table in `_build_graph` and
  the conditional-edges call site are the only places to re-pin.
- The `_skip_graph` kwarg is now a soft override (stage 1 needed it
  for recursion safety; stage 2 doesn't). Removing it would be a
  follow-up cleanup.
- The phase helpers are private (`_`-prefixed). External code that
  wants a phase-level surface should request a public API via a
  follow-up ADR rather than relying on the internal contract.

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
  stage-2 three-node graph module (analyze / retrieve_loop /
  build_answer with a conditional edge).
- [`rag_core.py`](../../rag_core.py) — `_RunContext`,
  `_build_run_context`, and the `_phase_*` helpers that both the
  direct path and the LangGraph nodes call.
- [`requirements-graph.txt`](../../requirements-graph.txt) — the
  opt-in LangGraph dependency.
- [`tests/test_langgraph_orchestrator_regression.py`](../../tests/test_langgraph_orchestrator_regression.py)
  — JSON-identity + ADR-0001 dispatch tests (stage 1) plus the
  multi-node graph-structure tests (stage 2).
- [ADR 0001](./0001-preserve-naive-baseline.md) — naive_baseline policy
  this ADR explicitly preserves.
- [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) — the
  additive opt-in pattern this ADR reuses.
- [ADR 0013](./0013-observability-as-additive-pluggable-surface.md) —
  the trace-backend additivity pattern; per-stage latencies in
  LangSmith / Langfuse map cleanly to the three stage-2 nodes.
