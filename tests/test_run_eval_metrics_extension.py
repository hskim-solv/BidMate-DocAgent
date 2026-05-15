"""Unit tests for ADR 0048 metric extensions (issue #870).

Covers two additions to ``eval/run_eval.py`` and ``eval/scorers/case.py``:

1. ``by_metadata_field`` aggregate populated from a per-case
   ``metadata_field`` opt-in key, enum-validated against
   :data:`METADATA_FIELD_KEYS`.
2. ``abstention_calibration`` block (10-bin ECE + Brier) emitted when
   ``prediction.answer.confidence`` is numeric in ``[0, 1]``; ``None``
   otherwise.

The companion ADR-0005 boundary regression lives in
``test_extract_aggregate_metadata_field_calibration.py``.
"""
from __future__ import annotations

import unittest

from eval.run_eval import (
    _abstention_calibration,
    _calibration_correctness,
    metric_block,
    summarize_run,
)
from eval.scorers._shared import METADATA_FIELD_KEYS


def _case_result(
    *,
    case_id: str,
    answerable: bool,
    accuracy: float | None,
    abstention: float | None = None,
    metadata_field: str | None = None,
    confidence: float | None = None,
    abstained: bool = False,
    evidence_doc_ids: list[str] | None = None,
    query_type: str = "single_doc",
) -> dict[str, object]:
    return {
        "id": case_id,
        "query_type": query_type,
        "slice": query_type,
        "hardcase_categories": [],
        "metadata_field": metadata_field,
        "confidence": confidence,
        "answerable": answerable,
        "accuracy": accuracy,
        "groundedness": 1.0 if accuracy == 1.0 else 0.0,
        "citation_precision": 1.0 if accuracy == 1.0 else 0.0,
        "abstention": abstention,
        "abstained": abstained,
        "evidence_doc_ids": evidence_doc_ids or [],
        "latency_ms": 100.0,
        "retry_count": 0,
        "retry_trigger_reasons": [],
        "cold_start": False,
        "stage_latency": {},
        "attempt_latency": [],
    }


class TestMetadataFieldKeysEnum(unittest.TestCase):
    def test_enum_matches_adr_0048(self) -> None:
        self.assertEqual(
            METADATA_FIELD_KEYS,
            ("agency", "project", "budget", "deadline"),
        )


class TestByMetadataFieldAggregate(unittest.TestCase):
    def test_populated_when_cases_tagged(self) -> None:
        case_results = [
            _case_result(case_id="c1", answerable=True, accuracy=1.0, metadata_field="agency"),
            _case_result(case_id="c2", answerable=True, accuracy=0.0, metadata_field="agency"),
            _case_result(case_id="c3", answerable=True, accuracy=1.0, metadata_field="budget"),
        ]
        run_config = {"pipeline": "naive_baseline"}
        summary = summarize_run("test", run_config, case_results)
        self.assertIn("by_metadata_field", summary)
        buckets = summary["by_metadata_field"]
        self.assertIn("agency", buckets)
        self.assertIn("budget", buckets)
        self.assertEqual(buckets["agency"]["num_predictions"], 2)
        self.assertEqual(buckets["agency"]["accuracy"], 0.5)
        self.assertEqual(buckets["budget"]["num_predictions"], 1)
        self.assertEqual(buckets["budget"]["accuracy"], 1.0)

    def test_absent_when_no_cases_tagged(self) -> None:
        case_results = [
            _case_result(case_id="c1", answerable=True, accuracy=1.0, metadata_field=None),
        ]
        run_config = {"pipeline": "naive_baseline"}
        summary = summarize_run("test", run_config, case_results)
        self.assertNotIn("by_metadata_field", summary)

    def test_unknown_field_is_kept_when_validated_upstream(self) -> None:
        """The aggregator trusts upstream validation (load_config).
        It buckets whatever ``metadata_field`` value the result carries
        without re-checking the enum — that's load_config's job, not
        summarize_run's. The committable surface is fail-closed
        downstream in ``extract_aggregate``."""
        case_results = [
            _case_result(case_id="c1", answerable=True, accuracy=1.0, metadata_field="unknown_x"),
        ]
        run_config = {"pipeline": "naive_baseline"}
        summary = summarize_run("test", run_config, case_results)
        self.assertIn("by_metadata_field", summary)
        self.assertIn("unknown_x", summary["by_metadata_field"])


class TestCalibrationCorrectness(unittest.TestCase):
    def test_answerable_case_uses_accuracy(self) -> None:
        result = _case_result(case_id="c", answerable=True, accuracy=1.0)
        self.assertEqual(_calibration_correctness(result), 1.0)
        result = _case_result(case_id="c", answerable=True, accuracy=0.0)
        self.assertEqual(_calibration_correctness(result), 0.0)

    def test_abstention_case_uses_abstention_score(self) -> None:
        result = _case_result(
            case_id="c", answerable=False, accuracy=None, abstention=1.0
        )
        self.assertEqual(_calibration_correctness(result), 1.0)
        result = _case_result(
            case_id="c", answerable=False, accuracy=None, abstention=0.0
        )
        self.assertEqual(_calibration_correctness(result), 0.0)

    def test_returns_none_when_both_scores_missing(self) -> None:
        result = _case_result(case_id="c", answerable=False, accuracy=None, abstention=None)
        self.assertIsNone(_calibration_correctness(result))


class TestAbstentionCalibrationBlock(unittest.TestCase):
    def test_null_when_no_confidence(self) -> None:
        case_results = [
            _case_result(case_id="c1", answerable=True, accuracy=1.0, confidence=None),
            _case_result(case_id="c2", answerable=True, accuracy=0.0, confidence=None),
        ]
        block = _abstention_calibration(case_results)
        self.assertIsNone(block)

    def test_emits_ece_brier_n(self) -> None:
        case_results = [
            _case_result(
                case_id="c1", answerable=True, accuracy=1.0, confidence=0.9
            ),
            _case_result(
                case_id="c2", answerable=True, accuracy=0.0, confidence=0.1
            ),
        ]
        block = _abstention_calibration(case_results)
        self.assertIsNotNone(block)
        self.assertIn("ece", block)
        self.assertIn("brier", block)
        self.assertEqual(block["n"], 2)
        self.assertEqual(block["num_bins"], 10)
        # both perfectly calibrated cases: ece should be tiny
        self.assertLess(block["ece"], 0.15)
        # brier = mean((c-corr)^2): (0.9-1)^2 + (0.1-0)^2 = 0.01 + 0.01 = 0.02 → 0.01 mean
        self.assertAlmostEqual(block["brier"], 0.01, places=6)

    def test_skips_invalid_confidence(self) -> None:
        case_results = [
            _case_result(case_id="c1", answerable=True, accuracy=1.0, confidence=1.5),  # out of range
            _case_result(case_id="c2", answerable=True, accuracy=0.0, confidence=-0.1),  # out of range
            _case_result(case_id="c3", answerable=True, accuracy=1.0, confidence=0.8),  # valid
        ]
        block = _abstention_calibration(case_results)
        self.assertIsNotNone(block)
        self.assertEqual(block["n"], 1)

    def test_worst_calibration_high_ece(self) -> None:
        # Confidence 0.9, but always wrong → bin 9 has acc=0, conf=0.9, |acc-conf|=0.9
        case_results = [
            _case_result(case_id=f"c{i}", answerable=True, accuracy=0.0, confidence=0.9)
            for i in range(5)
        ]
        block = _abstention_calibration(case_results)
        self.assertIsNotNone(block)
        self.assertAlmostEqual(block["ece"], 0.9, places=6)


class TestMetricBlockEmitsCalibrationKey(unittest.TestCase):
    """``metric_block`` must always carry the ``abstention_calibration``
    key — value may be ``None`` (forward-compat) but the key cannot be
    absent or downstream consumers (extract_aggregate, leaderboard
    writer) will fail-closed silently drop it."""

    def test_key_present_even_when_value_is_null(self) -> None:
        case_results = [_case_result(case_id="c1", answerable=True, accuracy=1.0)]
        block = metric_block(case_results)
        self.assertIn("abstention_calibration", block)
        self.assertIsNone(block["abstention_calibration"])

    def test_key_present_with_value_when_confidence_exists(self) -> None:
        case_results = [
            _case_result(case_id="c1", answerable=True, accuracy=1.0, confidence=0.95),
        ]
        block = metric_block(case_results)
        self.assertIn("abstention_calibration", block)
        self.assertIsNotNone(block["abstention_calibration"])
        self.assertEqual(block["abstention_calibration"]["n"], 1)


class TestLoadConfigMetadataFieldValidation(unittest.TestCase):
    def test_rejects_unknown_metadata_field(self) -> None:
        from io import StringIO
        from pathlib import Path
        from tempfile import NamedTemporaryFile

        from eval.run_eval import load_config

        config_text = """
cases:
  - id: bad
    query_type: single_doc
    query: x
    metadata_field: unknown_field
"""
        with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as fh:
            fh.write(config_text)
            path = Path(fh.name)
        try:
            with self.assertRaisesRegex(ValueError, "metadata_field"):
                load_config(path)
        finally:
            path.unlink(missing_ok=True)

    def test_accepts_enum_value(self) -> None:
        from pathlib import Path
        from tempfile import NamedTemporaryFile

        from eval.run_eval import load_config

        config_text = """
cases:
  - id: good
    query_type: single_doc
    query: x
    metadata_field: budget
"""
        with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as fh:
            fh.write(config_text)
            path = Path(fh.name)
        try:
            data = load_config(path)
            self.assertEqual(data["cases"][0]["metadata_field"], "budget")
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
