"""Regression: kordoc ToC leader-dot + page-footer noise stripping (issue #906).

Pins ``_strip_kordoc_toc_noise`` against two HWP-origin noise patterns:

1. Leader-dot runs (middle dot ``·`` chains of length 8+; ASCII period chains
   of length 15+) — ToC alignment artifacts that survive as raw text inside
   table cells. Top 3 files in real100: 고려대(27), 서울시립대(23), 서울지도(21).
2. Page-footer lines (``|+-N-|+`` shape) — page numbers wrapped in pipe
   glyphs that kordoc emits as standalone lines.

Both transforms are intentionally conservative: false positives (damaging
real content) are far worse than false negatives (a few residual dots).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingestion import _strip_kordoc_toc_noise  # noqa: E402


class StripLeaderDotsTest(unittest.TestCase):
    def test_collapses_middle_dot_run_to_space(self):
        # 8+ middle dots is the threshold; below stays.
        md = "Ⅰ.사업개요································Ⅱ.범위"
        result = _strip_kordoc_toc_noise(md)
        # Run collapsed to single space — word boundaries preserved.
        self.assertEqual(result, "Ⅰ.사업개요 Ⅱ.범위")

    def test_preserves_short_middle_dot_runs(self):
        # 7 or fewer middle dots: legitimate punctuation (e.g. ranges, lists).
        # Must not be touched — only ToC-style chains of 8+.
        md = "1·2·3·4·5"
        self.assertEqual(_strip_kordoc_toc_noise(md), md)

    def test_collapses_ascii_period_run_above_threshold(self):
        # 15+ ASCII periods: ToC leader; collapsed.
        md = "사업개요" + ("." * 30) + "1"
        result = _strip_kordoc_toc_noise(md)
        self.assertEqual(result, "사업개요 1")

    def test_preserves_ascii_period_runs_below_threshold(self):
        # Ellipses, IP-like fragments, decimal numbers stay intact.
        for sample in ["......", "1.1.1.1", "1.2.3.4.5", "section 3.4.5"]:
            with self.subTest(sample=sample):
                self.assertEqual(_strip_kordoc_toc_noise(sample), sample)

    def test_handles_table_embedded_leader_dots(self):
        # Real pattern from 고려대학교_*.md line 11.
        md = "| 사업개요|································| 22 |"
        result = _strip_kordoc_toc_noise(md)
        self.assertEqual(result, "| 사업개요| | 22 |")


class StripPageFooterTest(unittest.TestCase):
    def test_drops_standalone_page_footer_line(self):
        # Footer line removed entirely (not blanked) so surrounding paragraphs
        # join naturally — a page break is metadata, not a paragraph divider.
        md = "본문 내용\n|||-3-||\n다음 단락"
        result = _strip_kordoc_toc_noise(md)
        self.assertEqual(result, "본문 내용\n다음 단락")

    def test_handles_varying_pipe_count(self):
        # Real samples: |||||-2-|||| (5 pipes), ||||-3-||| (4), |||-3-|| (3)
        for footer in ["|||||-2-||||", "||||-3-|||", "|||-3-||"]:
            with self.subTest(footer=footer):
                md = f"before\n{footer}\nafter"
                result = _strip_kordoc_toc_noise(md)
                self.assertEqual(result, "before\nafter")

    def test_preserves_partial_match_in_middle_of_line(self):
        # Footer pattern embedded in a longer line (real example: a ToC cell
        # ending with the footer marker). Must not be stripped — only
        # standalone full-line matches.
        md = "|......22|-1-||"  # leader-dots stripped by ASCII rule, footer NOT stripped
        result = _strip_kordoc_toc_noise(md)
        # Line itself stays (footer regex requires full-line match).
        self.assertIn("22|-1-||", result)

    def test_pipe_run_without_digits_not_stripped(self):
        # ``||||||||`` alone is NOT a page footer — keep as-is.
        md = "before\n||||||||\nafter"
        result = _strip_kordoc_toc_noise(md)
        self.assertEqual(result, md)


class CombinedStripTest(unittest.TestCase):
    def test_both_patterns_in_same_document(self):
        md = "\n".join(
            [
                "# 목차",
                "| 사업개요|································| 22 |",
                "|||-3-||",
                "본문 시작",
            ]
        )
        result = _strip_kordoc_toc_noise(md)
        self.assertNotIn("········", result)
        self.assertNotIn("|||-3-||", result)
        # Surrounding content preserved.
        self.assertIn("# 목차", result)
        self.assertIn("| 사업개요|", result)
        self.assertIn("| 22 |", result)
        self.assertIn("본문 시작", result)

    def test_idempotent(self):
        md = "\n".join(
            [
                "사업명································내용",
                "|||-3-||",
                "다음",
            ]
        )
        first = _strip_kordoc_toc_noise(md)
        second = _strip_kordoc_toc_noise(first)
        self.assertEqual(first, second)

    def test_empty_input_safe(self):
        self.assertEqual(_strip_kordoc_toc_noise(""), "")

    def test_returns_unchanged_when_no_noise(self):
        md = "# 사업 개요\n\n본문 단락입니다.\n\n## 제1조"
        self.assertEqual(_strip_kordoc_toc_noise(md), md)


if __name__ == "__main__":
    unittest.main()
