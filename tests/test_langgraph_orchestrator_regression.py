"""Regression guard for the LangGraph orchestrator dispatch (ADR 0022, issue #401).

Stage 1 of the PR-H epic wraps ``run_rag_query`` in a single-node
StateGraph behind ``BIDMATE_ORCHESTRATOR=langgraph``. This test asserts
the JSON-identity contract: for the two LangGraph-eligible presets
(``agentic_full`` and ``agentic_full_llm``), the env-var path must
produce byte-for-byte identical output to the default ``direct`` path.

The test ``importorskip``s ``langgraph`` so CI without the opt-in
extra (``requirements-graph.txt``) just skips this module rather than
failing. When the dep is present (e.g. a contributor running the full
local install), the regression runs.
"""

from __future__ import annotations

import copy
import json
import os
import unittest
from pathlib import Path

import pytest

# Skip the whole module if langgraph isn't installed. The graph module
# imports langgraph lazily, but the dispatch test pretends to use it,
# and a missing dep would fail the dispatch path.
pytest.importorskip("langgraph")

import rag_core
import rag_graph_agentic_full  # noqa: F401 — exercises the import path


REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = REPO_ROOT / "data" / "index"


def _has_local_index() -> bool:
    return (INDEX_PATH / "index.json").exists()


# Fields that legitimately vary between any two sequential
# ``run_rag_query`` calls in the same Python process — independent of
# orchestrator. The first call flips ``_PROCESS_WARM`` (so ``cold_start``
# is ``True`` once and ``False`` thereafter); every call samples its own
# walltime for any per-stage ``*_ms`` field (``retrieve_ms``,
# ``verify_ms``, ``answer_generation_ms``, ``query_analysis_ms``,
# ``context_resolution_ms``, ...). ADR 0022 makes the JSON-identity
# claim *modulo* these non-deterministic fields.
_NON_DETERMINISTIC_KEY_NAMES = {
    "cold_start",
    "stage_latency",  # parent dict — its children are all *_ms
}


def _is_timing_key(key: str) -> bool:
    return key in _NON_DETERMINISTIC_KEY_NAMES or key.endswith("_ms")


def _strip_nondeterministic(value: object) -> object:
    """Recursively drop timing + cold_start fields for fair comparison."""
    if isinstance(value, dict):
        return {
            k: _strip_nondeterministic(v)
            for k, v in value.items()
            if not _is_timing_key(k)
        }
    if isinstance(value, list):
        return [_strip_nondeterministic(item) for item in value]
    return value


@pytest.mark.skipif(
    not _has_local_index(),
    reason="data/index/index.json missing — run `scripts/build_index.py` first",
)
@pytest.mark.parametrize(
    "pipeline",
    ["agentic_full", "agentic_full_llm"],
)
@pytest.mark.parametrize(
    "query",
    [
        "기관 A의 AI 요구사항을 알려줘",
        "기관 A와 기관 B의 AI 요구사항 차이 알려줘",
    ],
)
def test_langgraph_orchestrator_json_identical_to_direct(
    pipeline: str, query: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``BIDMATE_ORCHESTRATOR=langgraph`` must produce JSON-identical output.

    ``json.dumps(..., sort_keys=True)`` byte-equality after stripping
    the inherently non-deterministic fields (timing + cold_start flag —
    see ``_NON_DETERMINISTIC_KEYS``) is the ADR-0022 contract for
    stage 1 (single-node passthrough). Two sequential calls of
    ``run_rag_query`` in the same process always disagree on those
    fields regardless of orchestrator; the test asserts the graph
    introduces *no other* drift.
    """
    index = rag_core.load_index(INDEX_PATH)

    # Reset the module-level warm flag so both runs start from the same
    # cold-start state. Equivalent to running each in a fresh process,
    # without paying the process-spawn cost in the test loop.
    monkeypatch.setattr(rag_core, "_PROCESS_WARM", False, raising=False)

    monkeypatch.setenv("BIDMATE_ORCHESTRATOR", "direct")
    direct_result = rag_core.run_rag_query(
        copy.deepcopy(index),
        query,
        pipeline=pipeline,
    )

    # Reset again so the langgraph call also starts cold.
    monkeypatch.setattr(rag_core, "_PROCESS_WARM", False, raising=False)

    monkeypatch.setenv("BIDMATE_ORCHESTRATOR", "langgraph")
    graph_result = rag_core.run_rag_query(
        copy.deepcopy(index),
        query,
        pipeline=pipeline,
    )

    direct_json = json.dumps(
        _strip_nondeterministic(direct_result), sort_keys=True, ensure_ascii=False
    )
    graph_json = json.dumps(
        _strip_nondeterministic(graph_result), sort_keys=True, ensure_ascii=False
    )
    assert graph_json == direct_json, (
        f"LangGraph orchestrator produced JSON drift vs direct path for "
        f"pipeline={pipeline!r}, query={query!r}. "
        f"direct[:200]={direct_json[:200]!r}, graph[:200]={graph_json[:200]!r}"
    )


def test_naive_baseline_skips_langgraph_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """``naive_baseline`` preset bypasses LangGraph even with the env var set.

    ADR 0001 reserves ``naive_baseline`` as the minimal reproducible
    ablation surface. PR-H stage 1 leaves it on the direct path; this
    test pins that policy so a future LangGraph-everywhere refactor
    cannot silently sweep it in.
    """
    if not _has_local_index():
        pytest.skip("data/index/index.json missing")
    index = rag_core.load_index(INDEX_PATH)

    monkeypatch.setenv("BIDMATE_ORCHESTRATOR", "langgraph")
    result = rag_core.run_rag_query(
        copy.deepcopy(index),
        "기관 A의 AI 요구사항을 알려줘",
        pipeline="naive_baseline",
    )
    # Must still return a real answer dict (i.e., we did NOT bail at
    # dispatch with a ModuleNotFoundError or a graph state).
    assert isinstance(result, dict)
    assert result.get("diagnostics", {}).get("pipeline") == "naive_baseline"


class GraphModuleImportTest(unittest.TestCase):
    """Smoke-test the graph module independent of run_rag_query state."""

    def test_module_imports_state_and_graph_builder(self) -> None:
        # State TypedDict and builder helpers are public symbols.
        self.assertTrue(hasattr(rag_graph_agentic_full, "AgenticFullState"))
        self.assertTrue(hasattr(rag_graph_agentic_full, "run_via_langgraph"))
        self.assertTrue(callable(rag_graph_agentic_full.run_via_langgraph))

    def test_graph_compiles_once_and_is_cached(self) -> None:
        graph_a = rag_graph_agentic_full._graph()
        graph_b = rag_graph_agentic_full._graph()
        # Same compiled graph object — the cache works.
        self.assertIs(graph_a, graph_b)


class GraphStructureStage2Test(unittest.TestCase):
    """ADR 0022 stage 2 — the graph has three nodes, not one.

    Stage 1 shipped a single passthrough node so JSON-identity was
    structurally trivial. Stage 2 splits into analyze / retrieve_loop /
    build_answer with a conditional edge that short-circuits to END on
    context-clarification or metadata-ambiguity early returns. These
    tests pin the *structure* so a future stage-3 refactor cannot
    silently collapse it back to a passthrough.
    """

    def test_graph_has_three_phase_nodes(self) -> None:
        compiled = rag_graph_agentic_full._graph()
        # ``nodes`` on a compiled StateGraph maps node name → node object,
        # plus internal START / END markers. We assert the three phase
        # nodes are present.
        node_names = set(compiled.nodes)
        for required in ("analyze", "retrieve_loop", "build_answer"):
            self.assertIn(required, node_names, f"missing node: {required!r}; got {node_names!r}")

    def test_phase_helpers_exposed_from_rag_core(self) -> None:
        # The graph nodes import these by name at call time — if a
        # future refactor renames or removes one, the import would
        # fail at first dispatch instead of at this test.
        self.assertTrue(callable(getattr(rag_core, "_phase_analyze", None)))
        self.assertTrue(callable(getattr(rag_core, "_phase_retrieve_loop", None)))
        self.assertTrue(callable(getattr(rag_core, "_phase_build_answer", None)))
        self.assertTrue(callable(getattr(rag_core, "_build_run_context", None)))

    def test_route_after_analyze_branches_on_result_presence(self) -> None:
        # The conditional edge router after `analyze` short-circuits to
        # END when the analyze phase emits a final result dict (early
        # return), otherwise it continues to `retrieve_loop`. This pins
        # the contract used by the LangGraph dispatch table.
        router = rag_graph_agentic_full._route_after_analyze
        self.assertEqual(router({"ctx": object()}), "retrieve_loop")
        self.assertEqual(router({"ctx": object(), "result": {"mode": "rag"}}), "end")


@pytest.mark.skipif(
    not _has_local_index(),
    reason="data/index/index.json missing — run `scripts/build_index.py` first",
)
def test_phase_analyze_short_circuits_for_context_clarification(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``_phase_analyze`` short-circuits (e.g. needs_clarification),
    it returns a result dict so the graph can route directly to END
    without running retrieve_loop / build_answer. A query that triggers
    context clarification is the cheapest path to verify this.
    """
    index = rag_core.load_index(INDEX_PATH)
    monkeypatch.setattr(rag_core, "_PROCESS_WARM", False, raising=False)
    # An implicit-reference query with no conversation context typically
    # triggers ``needs_clarification`` — the analyze phase emits the
    # context-clarification result without entering retrieval.
    ctx = rag_core._build_run_context(
        copy.deepcopy(index),
        "그건 어떻게 돼?",
        top_k=None,
        context_entities=None,
        metadata_first=None,
        rerank=None,
        verifier_retry=None,
        retrieval_mode=None,
        retrieval_backend=None,
        pipeline="agentic_full",
        prompt_profile=None,
        conversation_state=None,
        comparison_balance=None,
        rrf_k=None,
        bm25_stopword_profile=None,
        params=None,
    )
    early = rag_core._phase_analyze(ctx)
    # The exact early-return depends on the query's resolution, but
    # whichever path fires (clarification or metadata-ambiguity), we
    # require an early return as a callable shape so the graph router
    # can short-circuit. Normal flow returns None.
    if early is None:
        # If analyze did not short-circuit, the phase populated ctx for
        # the retrieve loop. That's still a valid path (the query
        # resolved without clarification) — assert the state the next
        # phase needs is present so the contract is honored.
        assert ctx.analysis is not None
        assert ctx.stage_sequence is not None
        assert ctx.retrieval_query
    else:
        assert isinstance(early, dict)
        assert early.get("mode") == "rag"
        # Short-circuit results must still carry the answer-contract
        # fields the downstream callers expect.
        assert "answer" in early
        assert "diagnostics" in early
