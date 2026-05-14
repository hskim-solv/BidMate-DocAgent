"""Regression tests for scripts/dump_judge_disagreements.py (closes #677).

Guards the disagreement analysis logic:
  - analyze_disagreements: correct filtering, aggregate shape
  - Edge cases: all-agree, all-disagree, empty input
  - ADR 0005: local payload fields (no raw query/answer text)
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.dump_judge_disagreements import (
    analyze_disagreements,
    main,
)


def _make_case(
    *,
    id_: str = "c1",
    query_type: str = "single_doc",
    verifier_status: str = "supported",
    judge_status: str = "supported",
    judge_reason_short: str = "ok",
    faithfulness: float = 0.9,
    answer_relevance: float = 0.85,
) -> dict:
    return {
        "id": id_,
        "query_type": query_type,
        "verifier_status": verifier_status,
        "judge_status": judge_status,
        "judge_grounded": judge_status == "supported",
        "judge_reason_short": judge_reason_short,
        "faithfulness": faithfulness,
        "answer_relevance": answer_relevance,
    }


class AnalyzeDisagreementsTest(unittest.TestCase):
    """analyze_disagreements: filtering, aggregate shape, by_query_type."""

    def test_agree_case_not_in_disagreements(self) -> None:
        cases = [_make_case(verifier_status="supported", judge_status="supported")]
        disagree, agg = analyze_disagreements(cases)
        self.assertEqual([], disagree)
        self.assertEqual(0, agg["n_disagree"])
        self.assertEqual(1, agg["n_total"])

    def test_disagree_case_included(self) -> None:
        cases = [_make_case(verifier_status="supported", judge_status="partial")]
        disagree, agg = analyze_disagreements(cases)
        self.assertEqual(1, len(disagree))
        self.assertEqual(1, agg["n_disagree"])

    def test_disagreement_rate_correct(self) -> None:
        cases = [
            _make_case(id_="a", verifier_status="supported", judge_status="supported"),
            _make_case(id_="b", verifier_status="supported", judge_status="partial"),
        ]
        _, agg = analyze_disagreements(cases)
        self.assertAlmostEqual(0.5, agg["disagreement_rate"])

    def test_all_agree_rate_zero(self) -> None:
        cases = [
            _make_case(id_=f"c{i}", verifier_status="supported", judge_status="supported")
            for i in range(5)
        ]
        _, agg = analyze_disagreements(cases)
        self.assertAlmostEqual(0.0, agg["disagreement_rate"])

    def test_all_disagree_rate_one(self) -> None:
        cases = [
            _make_case(id_=f"c{i}", verifier_status="supported", judge_status="insufficient")
            for i in range(4)
        ]
        _, agg = analyze_disagreements(cases)
        self.assertAlmostEqual(1.0, agg["disagreement_rate"])

    def test_empty_input(self) -> None:
        disagree, agg = analyze_disagreements([])
        self.assertEqual([], disagree)
        self.assertEqual(0, agg["n_total"])
        self.assertIsNone(agg["disagreement_rate"])

    def test_non_dict_items_skipped(self) -> None:
        cases = [None, "string", _make_case(verifier_status="supported", judge_status="partial")]
        disagree, agg = analyze_disagreements(cases)
        self.assertEqual(1, len(disagree))

    def test_by_query_type_counts(self) -> None:
        cases = [
            _make_case(id_="a", query_type="comparison", verifier_status="supported", judge_status="partial"),
            _make_case(id_="b", query_type="abstention", verifier_status="insufficient", judge_status="supported"),
            _make_case(id_="c", query_type="comparison", verifier_status="partial", judge_status="insufficient"),
        ]
        _, agg = analyze_disagreements(cases)
        self.assertEqual(2, agg["by_query_type"].get("comparison", 0))
        self.assertEqual(1, agg["by_query_type"].get("abstention", 0))

    def test_top_status_pairs_most_common_first(self) -> None:
        cases = [
            _make_case(id_=f"s{i}", verifier_status="supported", judge_status="partial")
            for i in range(3)
        ] + [
            _make_case(id_="x", verifier_status="supported", judge_status="insufficient"),
        ]
        _, agg = analyze_disagreements(cases)
        top = agg["top_status_pairs"]
        # Most common pair should be first
        self.assertEqual("supported→partial", top[0]["pair"])
        self.assertEqual(3, top[0]["count"])

    def test_top_status_pairs_at_most_top_n(self) -> None:
        # Create 4 different pairs; top_status_pairs should cap at TOP_N_PATTERNS (3)
        cases = [
            _make_case(id_="a", verifier_status="supported", judge_status="partial"),
            _make_case(id_="b", verifier_status="supported", judge_status="insufficient"),
            _make_case(id_="c", verifier_status="partial", judge_status="insufficient"),
            _make_case(id_="d", verifier_status="partial", judge_status="supported"),
        ]
        _, agg = analyze_disagreements(cases)
        self.assertLessEqual(len(agg["top_status_pairs"]), 3)

    def test_aggregate_has_required_keys(self) -> None:
        _, agg = analyze_disagreements([])
        for key in ("schema_version", "generated_at", "n_total", "n_disagree",
                    "disagreement_rate", "by_query_type", "top_status_pairs"):
            self.assertIn(key, agg, f"missing key: {key}")

    def test_schema_version_is_one(self) -> None:
        _, agg = analyze_disagreements([])
        self.assertEqual(1, agg["schema_version"])

    def test_missing_judge_status_case_skipped(self) -> None:
        cases = [
            {"id": "x", "verifier_status": "supported"},  # no judge_status
            _make_case(id_="y", verifier_status="supported", judge_status="partial"),
        ]
        disagree, agg = analyze_disagreements(cases)
        # Only the valid disagreement case should appear
        self.assertEqual(1, len(disagree))


class CommitBoundaryTest(unittest.TestCase):
    """ADR 0005: local payload must not contain raw query / answer text."""

    def test_local_payload_case_fields_safe(self) -> None:
        # The _build_local_payload function should only include safe fields.
        from scripts.dump_judge_disagreements import _build_local_payload

        disagree_case = _make_case(
            verifier_status="supported",
            judge_status="partial",
            judge_reason_short="reason here",
        )
        # Inject hypothetical query/answer (should NOT appear in output)
        disagree_case["query"] = "SECRET QUERY"
        disagree_case["answer"] = "SECRET ANSWER"
        payload = _build_local_payload([disagree_case], {})
        serialised = json.dumps(payload)
        self.assertNotIn("SECRET QUERY", serialised)
        self.assertNotIn("SECRET ANSWER", serialised)


class CLITest(unittest.TestCase):
    """CLI: exit codes, file I/O, missing input."""

    def test_missing_local_file_returns_exit_2(self) -> None:
        import sys
        from io import StringIO
        from unittest.mock import patch

        with patch.object(sys, "argv", ["dump_judge_disagreements.py",
                                         "--local", "/nonexistent/path.json"]):
            with self.assertRaises(SystemExit) as ctx:
                raise SystemExit(main())
        self.assertEqual(2, ctx.exception.code)

    def test_writes_output_file(self) -> None:
        cases = [
            _make_case(id_="a", verifier_status="supported", judge_status="partial"),
            _make_case(id_="b", verifier_status="supported", judge_status="supported"),
        ]
        local_payload = {
            "schema_version": 1,
            "backend": "openai_compatible",
            "model": "test-model",
            "generated_at": "2026-01-01T00:00:00Z",
            "cases": cases,
        }
        with TemporaryDirectory() as tmpdir:
            local_file = Path(tmpdir) / "synthetic_judge.local.json"
            output_file = Path(tmpdir) / "judge_disagreements.local.json"
            local_file.write_text(json.dumps(local_payload), encoding="utf-8")

            import sys
            from unittest.mock import patch

            with patch.object(sys, "argv", [
                "dump_judge_disagreements.py",
                "--local", str(local_file),
                "--output", str(output_file),
                "--quiet",
            ]):
                exit_code = main()

            self.assertEqual(0, exit_code)
            self.assertTrue(output_file.exists())
            result = json.loads(output_file.read_text(encoding="utf-8"))
            # Only disagree case in output
            self.assertEqual(1, len(result["cases"]))
            self.assertEqual("a", result["cases"][0]["id"])


if __name__ == "__main__":
    unittest.main()
