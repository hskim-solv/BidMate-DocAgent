"""Unit tests for ``eval/scorers/chunk_health.py`` (issue #715).

Pins the shape of ``compute_chunk_health`` so the structure folded into
``ingestion_report.json`` (``summary.chunk_health``) stays stable. The
metric is observability-only — no retrieval / answer surface depends on
it — so the regression bar here is "field names and rough semantics",
not bit-identical numbers.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.scorers.chunk_health import (  # noqa: E402
    _is_hwp_table_chunk,
    _is_mid_sentence_cut,
    _percentile,
    compute_chunk_health,
)


def _hwp_chunk(text: str, section: str = "본문") -> dict:
    return {"text": text, "metadata": {"file_format": "hwp"}, "section": section}


def _pdf_chunk(text: str, section: str = "Section 1") -> dict:
    return {"text": text, "metadata": {"file_format": "pdf"}, "section": section}


def _hwp_table_chunk(text: str, idx: int = 1) -> dict:
    return {
        "text": text,
        "metadata": {"file_format": "hwp"},
        "section": f"표 {idx} (HWP native)",
    }


class TestComputeChunkHealth(unittest.TestCase):
    EXPECTED_KEYS = {
        "total_chunks",
        "by_format",
        "length_chars",
        "empty_chunks",
        "near_empty_chunks",
        "mid_sentence_cut_ratio",
        "hwp_table_chunks",
        "hwp_table_chunk_ratio",
        "nested_table_loss_count",
        "nested_table_loss_files",
        "nested_table_loss_samples",
    }
    EXPECTED_LENGTH_KEYS = {"p50", "p95", "max", "min", "mean"}

    def test_empty_input_is_safe_and_returns_full_shape(self):
        result = compute_chunk_health([])
        self.assertEqual(set(result.keys()), self.EXPECTED_KEYS)
        self.assertEqual(result["total_chunks"], 0)
        self.assertEqual(result["by_format"], {})
        self.assertEqual(set(result["length_chars"].keys()), self.EXPECTED_LENGTH_KEYS)
        # All length stats zero on empty input (avoid raising on a degenerate
        # ingest before the operator can read the report).
        self.assertEqual(result["length_chars"]["p50"], 0.0)
        self.assertEqual(result["length_chars"]["p95"], 0.0)
        self.assertEqual(result["length_chars"]["max"], 0.0)
        self.assertEqual(result["length_chars"]["min"], 0.0)
        self.assertEqual(result["length_chars"]["mean"], 0.0)
        self.assertEqual(result["empty_chunks"], 0)
        self.assertEqual(result["near_empty_chunks"], 0)
        self.assertEqual(result["mid_sentence_cut_ratio"], 0.0)
        self.assertEqual(result["hwp_table_chunks"], 0)
        self.assertEqual(result["hwp_table_chunk_ratio"], 0.0)
        self.assertEqual(result["nested_table_loss_count"], 0)
        self.assertEqual(result["nested_table_loss_files"], 0)
        self.assertEqual(result["nested_table_loss_samples"], [])

    def test_by_format_counts(self):
        chunks = [
            _hwp_chunk("이 사업은 RFP 입찰 대상입니다."),
            _hwp_chunk("예산은 5억 원입니다."),
            _pdf_chunk("The deliverable is a final report."),
        ]
        result = compute_chunk_health(chunks)
        self.assertEqual(result["by_format"], {"hwp": 2, "pdf": 1})
        self.assertEqual(result["total_chunks"], 3)

    def test_empty_vs_near_empty_distinct(self):
        chunks = [
            _hwp_chunk(""),  # empty
            _hwp_chunk("short"),  # near-empty (< 50 chars, non-zero)
            _hwp_chunk("a" * 60 + "."),  # neither
        ]
        result = compute_chunk_health(chunks)
        self.assertEqual(result["empty_chunks"], 1)
        self.assertEqual(result["near_empty_chunks"], 1)

    def test_mid_sentence_cut_excludes_table_and_empty(self):
        chunks = [
            # Eligible chunks (non-empty, non-table):
            _hwp_chunk("이 사업은 RFP 입찰 대상입니다."),  # clean (. ending)
            _hwp_chunk("예산은 5억 원이며"),  # mid-cut (ends with 며)
            _pdf_chunk("The deliverable is a final report."),  # clean
            _pdf_chunk("Budget is allocated to"),  # mid-cut (ends with `to`)
            # Excluded:
            _hwp_chunk(""),  # empty — not counted in eligible
            _hwp_table_chunk("입찰 마감일 | 2026-06-01"),  # table — excluded
        ]
        result = compute_chunk_health(chunks)
        # eligible = 4, mid = 2 → ratio 0.5
        self.assertAlmostEqual(result["mid_sentence_cut_ratio"], 0.5)

    def test_mid_sentence_cut_ratio_zero_when_no_eligible_chunks(self):
        # All chunks are tables → eligible_for_cut == 0 → ratio defaults to 0.0
        chunks = [_hwp_table_chunk("cell"), _hwp_table_chunk("cell", idx=2)]
        result = compute_chunk_health(chunks)
        self.assertEqual(result["mid_sentence_cut_ratio"], 0.0)

    def test_hwp_table_chunk_ratio(self):
        chunks = [
            _hwp_chunk("narrative"),
            _hwp_chunk("more narrative"),
            _hwp_table_chunk("table cell A"),
            _hwp_table_chunk("table cell B", idx=2),
            _pdf_chunk("pdf body"),  # PDF chunks don't count toward hwp totals
        ]
        result = compute_chunk_health(chunks)
        self.assertEqual(result["hwp_table_chunks"], 2)
        # 2 table chunks / 4 hwp chunks = 0.5; PDF excluded from denom.
        self.assertAlmostEqual(result["hwp_table_chunk_ratio"], 0.5)

    def test_hwp_table_chunk_ratio_zero_when_no_hwp(self):
        chunks = [_pdf_chunk("only pdf")]
        result = compute_chunk_health(chunks)
        self.assertEqual(result["hwp_table_chunks"], 0)
        self.assertEqual(result["hwp_table_chunk_ratio"], 0.0)

    def test_length_stats_sorted_correctly(self):
        # Lengths: 10, 50, 100, 500. p50 ≈ 75 (linear interp between 50 and 100).
        chunks = [
            _hwp_chunk("a" * 10),
            _hwp_chunk("b" * 50),
            _hwp_chunk("c" * 100),
            _hwp_chunk("d" * 500),
        ]
        result = compute_chunk_health(chunks)
        self.assertEqual(result["length_chars"]["min"], 10.0)
        self.assertEqual(result["length_chars"]["max"], 500.0)
        # p50 at index 1.5 (between 50 and 100) → 75.0
        self.assertAlmostEqual(result["length_chars"]["p50"], 75.0)
        # mean = (10 + 50 + 100 + 500) / 4 = 165
        self.assertAlmostEqual(result["length_chars"]["mean"], 165.0)


class TestIsHwpTableChunk(unittest.TestCase):
    def test_requires_both_prefix_and_marker(self):
        # Both → table
        self.assertTrue(_is_hwp_table_chunk(_hwp_table_chunk("x")))
        # PDF format, even if section looks tabular → not a table
        pdf_table_lookalike = {
            "text": "x",
            "metadata": {"file_format": "pdf"},
            "section": "표 1 (HWP native)",
        }
        self.assertFalse(_is_hwp_table_chunk(pdf_table_lookalike))
        # HWP but section is plain "표 5" without the native marker → not a table
        plain_table_heading = {
            "text": "x",
            "metadata": {"file_format": "hwp"},
            "section": "표 5",
        }
        self.assertFalse(_is_hwp_table_chunk(plain_table_heading))

    def test_handles_missing_metadata(self):
        self.assertFalse(_is_hwp_table_chunk({"text": "x"}))


class TestIsMidSentenceCut(unittest.TestCase):
    def test_ascii_terminators(self):
        self.assertFalse(_is_mid_sentence_cut("This is a complete sentence."))
        self.assertFalse(_is_mid_sentence_cut("Is it?"))
        self.assertFalse(_is_mid_sentence_cut("Wow!"))
        self.assertFalse(_is_mid_sentence_cut("끝났습니다。"))
        # Trailing whitespace stripped before check
        self.assertFalse(_is_mid_sentence_cut("Done.   "))

    def test_korean_terminators(self):
        self.assertFalse(_is_mid_sentence_cut("입찰 대상입니다"))  # ends with 다
        self.assertFalse(_is_mid_sentence_cut("규정에 의함"))  # ends with 함
        self.assertFalse(_is_mid_sentence_cut("주의 사항이 있음"))  # ends with 음

    def test_mid_cut(self):
        self.assertTrue(_is_mid_sentence_cut("This is incomplete"))
        self.assertTrue(_is_mid_sentence_cut("예산은 5억 원이며"))  # 며 not in enders
        self.assertTrue(_is_mid_sentence_cut("Budget is allocated to"))

    def test_closing_brackets_stripped_before_check(self):
        # Common ending: ``이다."`` / ``이다.)`` → still clean
        self.assertFalse(_is_mid_sentence_cut('대상입니다."'))
        self.assertFalse(_is_mid_sentence_cut("의함)"))

    def test_empty_string_is_not_mid_cut(self):
        # Empty chunks are handled by the empty_chunks metric; this fn
        # returns False so they don't double-count.
        self.assertFalse(_is_mid_sentence_cut(""))
        self.assertFalse(_is_mid_sentence_cut("   "))


class TestPercentile(unittest.TestCase):
    def test_empty_returns_zero(self):
        self.assertEqual(_percentile([], 0.5), 0.0)

    def test_clamps_at_endpoints(self):
        values = [10, 20, 30]
        self.assertEqual(_percentile(values, -0.1), 10.0)
        self.assertEqual(_percentile(values, 1.5), 30.0)

    def test_linear_interpolation(self):
        # [10, 20, 30] — p50 is the middle value 20
        self.assertEqual(_percentile([10, 20, 30], 0.5), 20.0)
        # [0, 10] — p50 interpolates to 5
        self.assertEqual(_percentile([0, 10], 0.5), 5.0)


if __name__ == "__main__":
    unittest.main()
