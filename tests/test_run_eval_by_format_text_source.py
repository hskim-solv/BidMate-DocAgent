"""eval/run_eval.py by_format text_source pass-through regression (issue #769).

PR #744 (issue #715) wrote ``text_source_counts`` to
``ingestion_report.json``; this test pins the consumer side — that
``summarize_run`` reads it back into ``by_format`` and derives
``kordoc_rate`` / ``hwp_fallback_rate`` without altering any existing
metric block field.

The tests use direct dict fixtures (no full RAG pipeline) because the
contract under test is the JSON shape of ``by_format``, not the eval logic.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eval.run_eval import (
    _inject_text_source_rates,
    _load_text_source_counts,
    summarize_run,
)


def _case(query_type: str, fmt: str) -> dict:
    """Minimal case_result shape that ``metric_block`` and ``summarize_run`` accept.

    Only the fields read via ``r["..."]`` (non-``.get``) are required; everything
    else falls back to ``None``.  Keeping this list short is intentional — the
    contract under test is text_source pass-through, not metric_block internals.
    """
    return {
        "query_type": query_type,
        "case_source_format": fmt,
        "accuracy": 1.0,
        "groundedness": 1.0,
        "citation_precision": 1.0,
        "abstention": 1.0,
        "latency_ms": 0.0,
        "retry_count": 0,
    }


def _write_report(index_dir: Path, text_source_counts: dict | None) -> None:
    summary = {"schema_version": 3}
    if text_source_counts is not None:
        summary["text_source_counts"] = text_source_counts
    (index_dir / "ingestion_report.json").write_text(
        json.dumps({"summary": summary}), encoding="utf-8"
    )


class LoadTextSourceCountsTest(unittest.TestCase):
    def test_returns_empty_when_index_dir_is_none(self) -> None:
        self.assertEqual({}, _load_text_source_counts(None))

    def test_returns_empty_when_report_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual({}, _load_text_source_counts(Path(tmp)))

    def test_returns_empty_when_report_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "ingestion_report.json").write_text("not json", encoding="utf-8")
            self.assertEqual({}, _load_text_source_counts(Path(tmp)))

    def test_returns_empty_when_summary_missing_text_source_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_report(Path(tmp), text_source_counts=None)
            self.assertEqual({}, _load_text_source_counts(Path(tmp)))

    def test_returns_per_format_counts_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_report(
                Path(tmp),
                text_source_counts={
                    "hwp": {"kordoc": 4, "data_list_csv_text": 1},
                    "pdf": {"data_list_csv_text": 3},
                },
            )
            self.assertEqual(
                {
                    "hwp": {"kordoc": 4, "data_list_csv_text": 1},
                    "pdf": {"data_list_csv_text": 3},
                },
                _load_text_source_counts(Path(tmp)),
            )


class InjectTextSourceRatesTest(unittest.TestCase):
    def test_kordoc_and_fallback_rates_split_correctly(self) -> None:
        by_format = {"hwp": {}, "pdf": {}}
        _inject_text_source_rates(
            by_format,
            {
                "hwp": {"kordoc": 3, "data_list_csv_text": 1},
                "pdf": {"data_list_csv_text": 2},
            },
        )
        self.assertAlmostEqual(0.75, by_format["hwp"]["kordoc_rate"])
        self.assertAlmostEqual(0.25, by_format["hwp"]["hwp_fallback_rate"])
        self.assertEqual(
            {"kordoc": 3, "data_list_csv_text": 1},
            by_format["hwp"]["text_source_counts"],
        )

    def test_pdf_gets_passthrough_but_no_native_rate(self) -> None:
        by_format = {"pdf": {}}
        _inject_text_source_rates(
            by_format, {"pdf": {"data_list_csv_text": 2}}
        )
        self.assertEqual(
            {"data_list_csv_text": 2}, by_format["pdf"]["text_source_counts"]
        )
        self.assertNotIn("kordoc_rate", by_format["pdf"])
        self.assertNotIn("hwp_fallback_rate", by_format["pdf"])

    def test_skips_formats_absent_in_text_source_counts(self) -> None:
        by_format = {"doc": {"accuracy": 1.0}}
        _inject_text_source_rates(by_format, {"hwp": {"kordoc": 1}})
        self.assertEqual({"accuracy": 1.0}, by_format["doc"])

    def test_hwp_all_fallback_yields_zero_native_rate(self) -> None:
        by_format = {"hwp": {}}
        _inject_text_source_rates(by_format, {"hwp": {"data_list_csv_text": 5}})
        self.assertEqual(0.0, by_format["hwp"]["kordoc_rate"])
        self.assertEqual(1.0, by_format["hwp"]["hwp_fallback_rate"])

    def test_hwp_all_native_yields_one_native_rate(self) -> None:
        by_format = {"hwp": {}}
        _inject_text_source_rates(by_format, {"hwp": {"kordoc": 5}})
        self.assertEqual(1.0, by_format["hwp"]["kordoc_rate"])
        self.assertEqual(0.0, by_format["hwp"]["hwp_fallback_rate"])


class SummarizeRunEndToEndTest(unittest.TestCase):
    """summarize_run integrates the loader + injector. We supply a synthetic
    case_results list and a temp index_dir holding the ingestion report."""

    def _run_with(self, index_dir: Path | None) -> dict:
        case_results = [
            _case("single_doc", "hwp"),
            _case("single_doc", "hwp"),
            _case("comparison", "pdf"),
        ]
        return summarize_run(
            "test-run",
            {"pipeline": "naive_baseline"},
            case_results,
            include_cases=False,
            index_dir=index_dir,
        )

    def test_by_format_carries_rates_when_report_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_report(
                Path(tmp),
                text_source_counts={
                    "hwp": {"kordoc": 2, "data_list_csv_text": 1},
                    "pdf": {"data_list_csv_text": 1},
                },
            )
            summary = self._run_with(Path(tmp))
            self.assertIn("by_format", summary)
            hwp_block = summary["by_format"]["hwp"]
            self.assertAlmostEqual(2 / 3, hwp_block["kordoc_rate"])
            self.assertAlmostEqual(1 / 3, hwp_block["hwp_fallback_rate"])
            self.assertEqual(
                {"kordoc": 2, "data_list_csv_text": 1},
                hwp_block["text_source_counts"],
            )
            pdf_block = summary["by_format"]["pdf"]
            self.assertEqual(
                {"data_list_csv_text": 1}, pdf_block["text_source_counts"]
            )
            self.assertNotIn("kordoc_rate", pdf_block)

    def test_by_format_unchanged_when_report_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = self._run_with(Path(tmp))
            self.assertIn("by_format", summary)
            self.assertNotIn("kordoc_rate", summary["by_format"]["hwp"])
            self.assertNotIn("text_source_counts", summary["by_format"]["hwp"])

    def test_by_format_unchanged_when_index_dir_is_none(self) -> None:
        summary = self._run_with(None)
        self.assertNotIn("kordoc_rate", summary["by_format"]["hwp"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
