"""Snapshot regression guard for `naive_baseline` retrieval ranking (ADR 0001).

The Phase 3 stack (#173 NumPy vectorize, #176 VectorStore abstraction,
#179 LoRA, #207 embedding externalization, ...) touches retrieval-path
code that must NOT change the `naive_baseline` ablation's chunk
ordering. ADR 0001 commits us to preserving the baseline alongside the
agentic pipeline so reviewers can diff features 1:1 against a stable
floor; a silent ranking drift in the baseline would invalidate every
ablation comparison that uses it.

This test runs a small fixed query set through the `naive_baseline`
pipeline against a freshly built hashing-backend index (deterministic
across machines) and asserts the top-K chunk_ids + scores match a
committed golden file (`tests/data/naive_baseline_top_k.json`).

If a later PR legitimately needs to change `naive_baseline` ranking
(e.g. a chunking-strategy default change), regenerate the golden
intentionally inside that PR and call it out in the PR body.
"""

import json
import unittest
from pathlib import Path

from rag_core import build_index_payload, run_rag_query


GOLDEN_PATH = Path(__file__).parent / "data" / "naive_baseline_top_k.json"


class NaiveBaselineRankingInvarianceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Hashing backend + fixed chunking = deterministic across machines
        # and across the Phase 3 stack — every PR's CI run reproduces the
        # same vectors.
        cls.index = build_index_payload(
            Path("data/raw"),
            embedding_backend="hashing",
            chunking_strategy="fixed",
        )
        cls.golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

    def test_top_k_chunk_ids_match_golden(self) -> None:
        for query, golden_top in self.golden.items():
            with self.subTest(query=query):
                result = run_rag_query(self.index, query, pipeline="naive_baseline")
                citations = result.get("citations") or result.get("evidence") or []
                observed = [[c.get("chunk_id"), c.get("score")] for c in citations[: len(golden_top)]]
                self.assertEqual(
                    golden_top,
                    observed,
                    f"naive_baseline ranking drifted for query: {query!r}.\n"
                    f"  golden:   {golden_top}\n"
                    f"  observed: {observed}\n"
                    f"If this drift is intentional, regenerate "
                    f"{GOLDEN_PATH} inside the PR and explain in the PR body.",
                )


if __name__ == "__main__":
    unittest.main()
