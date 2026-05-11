"""Tests for the multi-turn turn-depth derivation (issue #125).

Aggregation in :mod:`eval.evaluate_dev_results` is pandas-backed and
covered indirectly via end-to-end use of the dev evaluator. Here we
test the pandas-free derivation surface — :func:`derive_turn_depth`
and :func:`build_qid_parent_map`.
"""

from __future__ import annotations

import unittest

from eval.multiturn_eval import build_qid_parent_map, derive_turn_depth


class TestBuildQidParentMap(unittest.TestCase):
    def test_empty_parent_normalised_to_none(self) -> None:
        rows = [
            {"qid": "Q1", "parent_qid": ""},
            {"qid": "Q2", "parent_qid": None},
            {"qid": "Q3", "parent_qid": "null"},
            {"qid": "Q4", "parent_qid": "None"},
        ]
        mapping = build_qid_parent_map(rows)
        self.assertEqual(mapping, {"Q1": None, "Q2": None, "Q3": None, "Q4": None})

    def test_real_parent_chain(self) -> None:
        rows = [
            {"qid": "Q1", "parent_qid": ""},
            {"qid": "Q2", "parent_qid": "Q1"},
            {"qid": "Q3", "parent_qid": "Q2"},
        ]
        mapping = build_qid_parent_map(rows)
        self.assertEqual(mapping, {"Q1": None, "Q2": "Q1", "Q3": "Q2"})

    def test_drops_rows_without_qid(self) -> None:
        rows = [{"qid": "Q1", "parent_qid": ""}, {"qid": "", "parent_qid": "Q1"}]
        self.assertEqual(build_qid_parent_map(rows), {"Q1": None})


class TestDeriveTurnDepth(unittest.TestCase):
    def test_root_is_turn_one(self) -> None:
        self.assertEqual(derive_turn_depth("Q1", None, {"Q1": None}), 1)
        self.assertEqual(derive_turn_depth("Q1", "", {"Q1": None}), 1)
        self.assertEqual(derive_turn_depth("Q1", "null", {"Q1": None}), 1)

    def test_two_turn_chain(self) -> None:
        mapping = {"Q1": None, "Q2": "Q1"}
        self.assertEqual(derive_turn_depth("Q2", "Q1", mapping), 2)

    def test_three_turn_chain(self) -> None:
        mapping = {"Q1": None, "Q2": "Q1", "Q3": "Q2"}
        self.assertEqual(derive_turn_depth("Q3", "Q2", mapping), 3)

    def test_five_turn_chain(self) -> None:
        mapping = {
            "Q1": None,
            "Q2": "Q1",
            "Q3": "Q2",
            "Q4": "Q3",
            "Q5": "Q4",
        }
        self.assertEqual(derive_turn_depth("Q5", "Q4", mapping), 5)

    def test_cycle_is_bounded(self) -> None:
        # Defensive: a malformed graph that points back to the qid
        # itself must terminate rather than infinite-loop.
        mapping = {"Q1": "Q2", "Q2": "Q1"}
        depth = derive_turn_depth("Q1", "Q2", mapping)
        self.assertLessEqual(depth, 16)
        self.assertGreaterEqual(depth, 2)

    def test_max_depth_cap(self) -> None:
        # A 20-deep chain is capped at the max_depth bound.
        mapping = {f"Q{i}": f"Q{i - 1}" for i in range(1, 20)}
        mapping["Q0"] = None
        depth = derive_turn_depth(
            "Q19", mapping["Q19"], mapping, max_depth=8
        )
        self.assertEqual(depth, 8)


if __name__ == "__main__":
    unittest.main()
