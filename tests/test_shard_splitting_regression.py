"""Regression: sharded pytest split must use the `least_duration` algorithm.

Issue #1281 — the committed ``.test_durations`` baseline is dominated by a
single 737s test (``test_m3_backend_regression.py::...::
test_m3_score_parts_carry_sparse_and_colbert``: BGE-M3 model download +
inference), which is ~58% of the total suite wall-clock. pytest-split's
DEFAULT ``duration_based_chunks`` algorithm walks tests in collection order
accumulating to ``total / N`` per group; on that skew it consumes the budget
before the last group and leaves it EMPTY → ``pytest`` exits 5 (no tests
collected) → the shard job fails (observed on PR #1298, shard 4).

``least_duration`` (LPT — assign each test to the currently-shortest group)
never leaves a group empty when ``n_tests >= n_splits`` and also minimises the
max-shard wall-clock. ``scripts/test.sh`` must therefore wire it whenever it
passes ``--splits``/``--group``. This test pins that so a refactor cannot
silently revert to the empty-group-prone default.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_SH = REPO_ROOT / "scripts" / "test.sh"
DURATIONS = REPO_ROOT / ".test_durations"


class ShardSplittingAlgorithmTest(unittest.TestCase):
    def test_test_sh_uses_least_duration(self) -> None:
        text = TEST_SH.read_text(encoding="utf-8")
        self.assertIn(
            "--splitting-algorithm least_duration",
            text,
            "scripts/test.sh must pass `--splitting-algorithm least_duration` "
            "to pytest-split. The default `duration_based_chunks` leaves a "
            "trailing group empty under the .test_durations skew (issue #1281, "
            "pytest exit 5).",
        )

    def test_least_duration_flag_is_inside_the_split_branch(self) -> None:
        # The flag is meaningless unless it accompanies --splits/--group.
        text = TEST_SH.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            re.compile(r"--splits.*--group.*least_duration", re.S),
            "the least_duration flag must sit alongside --splits/--group "
            "in SPLIT_FLAGS, not as an orphaned line.",
        )


class DurationsBaselineTest(unittest.TestCase):
    def test_durations_file_present_and_parseable(self) -> None:
        self.assertTrue(
            DURATIONS.exists(),
            ".test_durations must be committed for pytest-split to balance "
            "shards by measured wall-clock (issue #1281).",
        )
        data = json.loads(DURATIONS.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)
        self.assertGreater(len(data), 100, "durations baseline looks truncated")

    def test_least_duration_yields_no_empty_group_for_4_shards(self) -> None:
        # Replicate pytest-split's least_duration partition over the committed
        # baseline and assert every shard receives at least one test — the
        # exact invariant whose violation produced the exit-5 shard failure.
        data = json.loads(DURATIONS.read_text(encoding="utf-8"))
        n_splits = 4
        self.assertGreaterEqual(len(data), n_splits)
        sums = [0.0] * n_splits
        counts = [0] * n_splits
        for dur in sorted(data.values(), reverse=True):
            i = min(range(n_splits), key=lambda j: sums[j])
            sums[i] += dur
            counts[i] += 1
        self.assertTrue(
            all(c > 0 for c in counts),
            f"least_duration left an empty shard: per-shard counts={counts}",
        )


if __name__ == "__main__":
    unittest.main()
