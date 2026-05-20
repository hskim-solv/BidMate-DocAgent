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

The rebuild is delegated to `scripts.regen_naive_baseline_golden.build_golden`
— the single source of truth for *how* the golden is built — so this guard
and the `make regen-golden` regenerator can never drift apart.

If a later PR legitimately needs to change `naive_baseline` ranking
(e.g. a chunking-strategy default change), run `make regen-golden`
inside that PR and call it out in the PR body.
"""

import json
import unittest

from scripts.regen_naive_baseline_golden import GOLDEN_PATH, build_golden


class NaiveBaselineRankingInvarianceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # build_golden rebuilds with the hashing backend + fixed chunking
        # (deterministic across machines and across the Phase 3 stack), keyed
        # to the committed golden's query set.
        cls.golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        cls.rebuilt = build_golden(cls.golden)

    def test_top_k_chunk_ids_match_golden(self) -> None:
        for query, golden_top in self.golden.items():
            with self.subTest(query=query):
                self.assertEqual(
                    golden_top,
                    self.rebuilt[query],
                    f"naive_baseline ranking drifted for query: {query!r}.\n"
                    f"  golden:   {golden_top}\n"
                    f"  observed: {self.rebuilt[query]}\n"
                    f"If this drift is intentional, run `make regen-golden` "
                    f"inside the PR and explain in the PR body.",
                )


if __name__ == "__main__":
    unittest.main()
