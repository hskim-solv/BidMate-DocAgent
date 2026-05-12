"""Parity regression for ``arun_rag_query`` (#173 Stage 1).

``arun_rag_query`` is a thin ``asyncio.to_thread`` wrapper around
``run_rag_query`` — Stage 1 introduces the async seam without
fan-out parallelism, so the two entry points MUST produce
byte-equivalent results on the same input.
"""
from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

import pytest

from rag_core import arun_rag_query, build_index_payload, run_rag_query


ROOT_DIR = Path(__file__).resolve().parents[1]


class AsyncRagQueryParityTest(unittest.TestCase):
    """Stage 1 contract: sync and async entry points return identical dicts."""

    @pytest.fixture(autouse=True)
    def _inject_shared_index(self, shared_raw_index):
        self.index = shared_raw_index

    def _run_async(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)

    def test_arun_returns_dict_with_expected_keys(self) -> None:
        result = self._run_async(
            arun_rag_query(self.index, "기관 A의 보안 통제 요구사항은?")
        )
        self.assertIsInstance(result, dict)
        for key in ("answer", "evidence", "diagnostics", "plan"):
            self.assertIn(key, result, f"missing {key!r} in arun result")

    def test_arun_matches_run_on_single_doc_query(self) -> None:
        query = "기관 A의 보안 통제 요구사항은?"
        sync_result = run_rag_query(self.index, query)
        async_result = self._run_async(arun_rag_query(self.index, query))
        # diagnostics.latency_ms and stage_latency are wall-clock —
        # they will differ between two runs. Strip them before
        # comparing the structural payload.
        self._assert_structural_equal(sync_result, async_result)

    def test_arun_propagates_keyword_args(self) -> None:
        query = "기관 A의 보안 통제 요구사항은?"
        sync_result = run_rag_query(
            self.index, query, pipeline="naive_baseline", top_k=4
        )
        async_result = self._run_async(
            arun_rag_query(
                self.index, query, pipeline="naive_baseline", top_k=4
            )
        )
        self._assert_structural_equal(sync_result, async_result)
        # naive_baseline pipeline must surface in the diagnostics too.
        self.assertEqual(
            sync_result["diagnostics"].get("pipeline"),
            async_result["diagnostics"].get("pipeline"),
        )

    # ------------------------------------------------------------------

    def _assert_structural_equal(
        self, sync_result: dict, async_result: dict
    ) -> None:
        """Compare the answer / evidence / plan branches, ignoring
        wall-clock fields that legitimately differ between runs."""
        self.assertEqual(sync_result["answer"], async_result["answer"])
        self.assertEqual(sync_result["evidence"], async_result["evidence"])
        # ``plan`` is deterministic apart from any latency tracking —
        # compare the keys we care about explicitly.
        for key in (
            "pipeline",
            "top_k",
            "metadata_first",
            "rerank",
            "filter_stage",
        ):
            self.assertEqual(
                sync_result["plan"].get(key),
                async_result["plan"].get(key),
                f"plan[{key!r}] diverged between sync and async paths",
            )


if __name__ == "__main__":
    unittest.main()
