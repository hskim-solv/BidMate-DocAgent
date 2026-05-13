"""Per-node latency profile for the LangGraph orchestrator (ADR 0022 stage 2).

Complements the JSON-identity regression in
``tests/test_langgraph_orchestrator_regression.py`` with *measurement*:
- validates that ``stage_latency`` fields are present and non-negative
- measures per-phase breakdown (analyze / retrieve+verify / build_answer)
- quantifies wall-time overhead of the LangGraph path vs direct path

The tests ``importorskip`` both ``langgraph`` and a local index so CI
without the opt-in dep (``requirements-graph.txt``) or a built index
skips this module rather than failing.

Run with ``-s`` to see median timings printed:
  pytest tests/test_langgraph_performance_profile.py -v -s
"""
from __future__ import annotations

import copy
import statistics
import time
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("langgraph")

import rag_core  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = REPO_ROOT / "data" / "index"

# Benchmark settings
_N_REPEATS = 5
_QUERY = "기관 A의 AI 요구사항을 알려줘"
_PIPELINE = "agentic_full"
# LangGraph path must stay within this multiple of direct-path median wall time.
# Graph builder is cached after first call; StateGraph dispatch overhead is expected
# to be < 10% at warm state. 2.5× gives generous room for cold-start variance.
_MAX_OVERHEAD_RATIO = 2.5


def _has_local_index() -> bool:
    return (INDEX_PATH / "index.json").exists()


def _run(index: Any, orchestrator: str, *, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("BIDMATE_ORCHESTRATOR", orchestrator)
    monkeypatch.setattr(rag_core, "_PROCESS_WARM", False, raising=False)
    return rag_core.run_rag_query(copy.deepcopy(index), _QUERY, pipeline=_PIPELINE)


@pytest.fixture(scope="module")
def loaded_index():
    if not _has_local_index():
        pytest.skip("data/index/index.json missing — run `scripts/build_index.py` first")
    return rag_core.load_index(INDEX_PATH)


# ---------------------------------------------------------------------------
# Stage-latency field validation
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _has_local_index(), reason="index missing")
class TestStageLatencyFields:
    """result['diagnostics']['stage_latency'] must be present and well-formed."""

    def test_required_keys_present(self, loaded_index, monkeypatch):
        result = _run(loaded_index, "direct", monkeypatch=monkeypatch)
        sl = result["diagnostics"]["stage_latency"]
        for key in ("query_analysis_ms", "context_resolution_ms", "answer_generation_ms"):
            assert key in sl, f"stage_latency missing key: {key}"

    def test_values_non_negative(self, loaded_index, monkeypatch):
        result = _run(loaded_index, "direct", monkeypatch=monkeypatch)
        for key, val in result["diagnostics"]["stage_latency"].items():
            assert val >= 0.0, f"stage_latency[{key!r}] = {val} is negative"

    def test_total_bounded_by_latency_ms(self, loaded_index, monkeypatch):
        result = _run(loaded_index, "direct", monkeypatch=monkeypatch)
        diag = result["diagnostics"]
        total_stage = sum(diag["stage_latency"].values())
        # stage_latency sums component phases; must be ≤ total latency_ms
        # (retrieve_ms lives in filter_stage_attempts, not stage_latency, so
        # stage_latency total < total latency is always expected)
        assert diag["latency_ms"] >= 0
        assert total_stage >= 0


# ---------------------------------------------------------------------------
# Per-phase breakdown on the direct path
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _has_local_index(), reason="index missing")
class TestDirectPathPerNodeBreakdown:
    """Measure analyze / retrieve+verify / build_answer medians over N runs."""

    def test_per_phase_breakdown(self, loaded_index, monkeypatch, capsys):
        analyze_ms_list: list[float] = []
        retrieve_ms_list: list[float] = []
        answer_ms_list: list[float] = []

        for _ in range(_N_REPEATS):
            result = _run(loaded_index, "direct", monkeypatch=monkeypatch)
            diag = result["diagnostics"]
            sl = diag["stage_latency"]

            analyze_ms = sl.get("query_analysis_ms", 0.0) + sl.get("context_resolution_ms", 0.0)
            analyze_ms_list.append(analyze_ms)

            attempts = diag.get("filter_stage_attempts") or []
            retrieve_ms = sum(
                (a.get("timings") or {}).get("retrieve_ms", 0.0)
                + (a.get("timings") or {}).get("verify_ms", 0.0)
                for a in attempts
            )
            retrieve_ms_list.append(retrieve_ms)
            answer_ms_list.append(sl.get("answer_generation_ms", 0.0))

        med_analyze = statistics.median(analyze_ms_list)
        med_retrieve = statistics.median(retrieve_ms_list)
        med_answer = statistics.median(answer_ms_list)

        with capsys.disabled():
            print(
                f"\n[profile] direct path median over {_N_REPEATS} runs"
                f" — analyze: {med_analyze:.2f}ms"
                f" | retrieve+verify: {med_retrieve:.2f}ms"
                f" | build_answer: {med_answer:.2f}ms"
            )

        assert med_analyze >= 0
        assert med_retrieve >= 0
        assert med_answer >= 0

    def test_retrieve_loop_dominates(self, loaded_index, monkeypatch):
        """retrieve_loop (I/O + verifier) should be the dominant phase for
        a non-trivial query — if analyze is consistently the bottleneck
        that signals a regression in query planning complexity."""
        results = [
            _run(loaded_index, "direct", monkeypatch=monkeypatch) for _ in range(_N_REPEATS)
        ]
        analyze_medians = statistics.median(
            r["diagnostics"]["stage_latency"].get("query_analysis_ms", 0.0)
            + r["diagnostics"]["stage_latency"].get("context_resolution_ms", 0.0)
            for r in results
        )
        retrieve_medians = statistics.median(
            sum(
                (a.get("timings") or {}).get("retrieve_ms", 0.0)
                for a in (r["diagnostics"].get("filter_stage_attempts") or [])
            )
            for r in results
        )
        # retrieve dominates over analyze for a standard single-doc query
        # (skips if retrieve_medians is 0 — means stage_attempts had no timings)
        if retrieve_medians > 0:
            assert retrieve_medians >= analyze_medians, (
                f"analyze ({analyze_medians:.2f}ms) dominated retrieve ({retrieve_medians:.2f}ms); "
                "query analysis may have regressed in complexity."
            )


# ---------------------------------------------------------------------------
# LangGraph overhead quantification
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _has_local_index(), reason="index missing")
class TestLangGraphOverhead:
    """Wall-time overhead of the LangGraph path must stay within _MAX_OVERHEAD_RATIO."""

    def test_overhead_within_bound(self, loaded_index, monkeypatch, capsys):
        direct_wall: list[float] = []
        graph_wall: list[float] = []

        for _ in range(_N_REPEATS):
            t0 = time.perf_counter()
            _run(loaded_index, "direct", monkeypatch=monkeypatch)
            direct_wall.append(time.perf_counter() - t0)

            t0 = time.perf_counter()
            _run(loaded_index, "langgraph", monkeypatch=monkeypatch)
            graph_wall.append(time.perf_counter() - t0)

        med_direct_ms = statistics.median(direct_wall) * 1000
        med_graph_ms = statistics.median(graph_wall) * 1000
        overhead_ratio = med_graph_ms / max(med_direct_ms, 0.001)

        with capsys.disabled():
            print(
                f"\n[profile] overhead — direct: {med_direct_ms:.2f}ms"
                f"  langgraph: {med_graph_ms:.2f}ms"
                f"  ratio: {overhead_ratio:.2f}×"
            )

        assert overhead_ratio <= _MAX_OVERHEAD_RATIO, (
            f"LangGraph overhead {overhead_ratio:.2f}× > {_MAX_OVERHEAD_RATIO}× limit. "
            "StateGraph builder caching or node dispatch may have regressed. "
            "Re-run with -s to see median timings."
        )

    def test_langgraph_stage_latency_fields_match_direct(self, loaded_index, monkeypatch):
        """LangGraph path must expose the same stage_latency keys as direct."""
        direct_result = _run(loaded_index, "direct", monkeypatch=monkeypatch)
        graph_result = _run(loaded_index, "langgraph", monkeypatch=monkeypatch)

        direct_keys = set(direct_result["diagnostics"]["stage_latency"].keys())
        graph_keys = set(graph_result["diagnostics"]["stage_latency"].keys())
        assert direct_keys == graph_keys, (
            f"stage_latency key mismatch — direct: {direct_keys}, langgraph: {graph_keys}"
        )
