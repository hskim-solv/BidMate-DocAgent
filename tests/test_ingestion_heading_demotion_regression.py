"""Regression: kordoc HWP bullet-heading demotion (issue #904).

Pins the heuristic that strips ``#+`` from over-promoted HWP bullet headings
(``# ㅇ ...`` / ``# □ ...`` / ``# ❍ ...``) when they appear in runs of 3+
separated only by blank lines. Without demotion, chunk-boundary detection
treats every bullet item as a heading split point, fragmenting the index.

The bar is bidirectional:
1. Real bullet-runs ARE demoted (the kordoc gap we're fixing).
2. Standalone bullet-prefixed headings + numbered / bracketed / Korean-prefix
   headings are NOT demoted (false-positive guard for legitimate sections).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingestion import (  # noqa: E402
    _BULLET_HEADING_RE,
    _MIN_RUN_LENGTH_FOR_DEMOTION,
    _demote_over_promoted_bullet_headings,
)


class BulletHeadingRegexTest(unittest.TestCase):
    def test_matches_korean_hwp_bullets(self):
        # Glyphs observed in real100 (sorted by frequency):
        # □(2208), ❍(2033), -(2807), ㅇ(1146), ○(512)
        for glyph in ["□", "❍", "○", "◦", "●", "▪", "■", "◆", "▶", "·", "ㅇ", "-"]:
            with self.subTest(glyph=glyph):
                self.assertIsNotNone(
                    _BULLET_HEADING_RE.match(f"# {glyph} 사업 개요"),
                    f"Expected bullet glyph {glyph!r} to match",
                )

    def test_matches_at_any_heading_depth(self):
        self.assertIsNotNone(_BULLET_HEADING_RE.match("# ㅇ x"))
        self.assertIsNotNone(_BULLET_HEADING_RE.match("## ❍ x"))
        self.assertIsNotNone(_BULLET_HEADING_RE.match("### □ x"))

    def test_does_not_match_legitimate_headings(self):
        # Numbered / Korean-prefix / bracketed headings stay headings.
        for line in [
            "# 1. 사업 개요",
            "## 제1조 (목적)",
            "### 제3장 사업 범위",
            "## [부록 A] 제출서류",
            "# 사업 개요",
            "## 본문",
        ]:
            with self.subTest(line=line):
                self.assertIsNone(
                    _BULLET_HEADING_RE.match(line),
                    f"Expected legitimate heading not to match: {line!r}",
                )

    def test_requires_space_after_glyph(self):
        # ``# ㅇ`` (glyph then space or EOL) matches; ``# ㅇabc`` (no space)
        # does not — guards against false positives like ``# 0xff`` or
        # ``# -infinity`` words that happen to start with one of the glyphs.
        self.assertIsNotNone(_BULLET_HEADING_RE.match("# ㅇ"))
        self.assertIsNotNone(_BULLET_HEADING_RE.match("# ㅇ "))
        self.assertIsNotNone(_BULLET_HEADING_RE.match("# ㅇ 텍스트"))
        self.assertIsNone(_BULLET_HEADING_RE.match("# ㅇ가나다"))


class DemoteBulletHeadingsRunDetectionTest(unittest.TestCase):
    def test_demotes_run_of_three_or_more_bullet_headings(self):
        # Real pattern from 한국한의학연구원_*.md lines 48-60.
        md = "\n".join(
            [
                "# ㅇ 임상연구 심의, 심의결과 통보",
                "",
                "",
                "# □ 동물실험계획 업무 프로세스 구축",
                "",
                "",
                "# ㅇ 기관 동물실험운영규정에 위한 동물실험 업무",
            ]
        )
        result = _demote_over_promoted_bullet_headings(md)
        # All three demoted — bullet glyph + text preserved, leading `#+ ` gone.
        self.assertIn("ㅇ 임상연구 심의, 심의결과 통보", result)
        self.assertIn("□ 동물실험계획 업무 프로세스 구축", result)
        self.assertIn("ㅇ 기관 동물실험운영규정에 위한 동물실험 업무", result)
        # `# ` prefix removed on the demoted lines.
        self.assertNotIn("# ㅇ", result)
        self.assertNotIn("# □", result)

    def test_preserves_run_below_threshold(self):
        # 2 bullet headings (< 3) → both stay headings.
        md = "\n".join(
            [
                "# ㅇ 항목 1",
                "",
                "# □ 항목 2",
            ]
        )
        result = _demote_over_promoted_bullet_headings(md)
        self.assertEqual(result, md)

    def test_body_paragraph_breaks_the_run(self):
        # The 2nd bullet group is interrupted by a body paragraph, so each
        # sub-run is length 2 (< 3) → no demotion anywhere.
        md = "\n".join(
            [
                "# ㅇ A",
                "",
                "# ㅇ B",
                "사업 개요 본문 단락이다.",
                "# ❍ C",
                "",
                "# ❍ D",
            ]
        )
        result = _demote_over_promoted_bullet_headings(md)
        self.assertEqual(result, md)

    def test_threshold_constant_is_three(self):
        # Pin the contract so future tuning is intentional, not accidental.
        self.assertEqual(_MIN_RUN_LENGTH_FOR_DEMOTION, 3)

    def test_real_headings_in_run_not_demoted(self):
        # Numbered headings adjacent to bullet headings: the numbered ones
        # are not bullet-prefixed, so they don't extend the run AND they
        # are not demoted themselves.
        md = "\n".join(
            [
                "# ㅇ A",
                "",
                "# 1. 진짜 섹션",
                "",
                "# ㅇ B",
            ]
        )
        result = _demote_over_promoted_bullet_headings(md)
        # Each bullet run is length 1, so nothing changes.
        self.assertEqual(result, md)
        # And the numbered heading is preserved either way.
        self.assertIn("# 1. 진짜 섹션", result)


class DemoteBulletHeadingsTransformTest(unittest.TestCase):
    def test_preserves_inline_html_tables_and_other_content(self):
        # The transform only touches qualifying heading lines. HTML tables,
        # body paragraphs, and code blocks must round-trip unchanged.
        md = "\n".join(
            [
                "# ㅇ A",
                "# ㅇ B",
                "# ㅇ C",
                "",
                "<table>",
                "<tr><td>cell</td></tr>",
                "</table>",
                "",
                "본문 단락이 여기 있습니다.",
            ]
        )
        result = _demote_over_promoted_bullet_headings(md)
        self.assertIn("<table>", result)
        self.assertIn("<tr><td>cell</td></tr>", result)
        self.assertIn("</table>", result)
        self.assertIn("본문 단락이 여기 있습니다.", result)
        # Headings demoted.
        self.assertIn("ㅇ A", result)
        self.assertIn("ㅇ B", result)
        self.assertIn("ㅇ C", result)
        self.assertNotIn("# ㅇ", result)

    def test_idempotent_on_normalized_input(self):
        # Running twice produces the same output — important because the
        # function is called once per kordoc batch, but a re-build of the
        # same source should never accumulate transforms.
        md = "\n".join(
            [
                "# ❍ A",
                "",
                "# ❍ B",
                "",
                "# ❍ C",
            ]
        )
        first = _demote_over_promoted_bullet_headings(md)
        second = _demote_over_promoted_bullet_headings(first)
        self.assertEqual(first, second)

    def test_returns_unchanged_when_no_bullet_headings(self):
        md = "# 사업 개요\n\n본문 단락입니다.\n\n## 제1조"
        self.assertEqual(_demote_over_promoted_bullet_headings(md), md)

    def test_empty_input_safe(self):
        self.assertEqual(_demote_over_promoted_bullet_headings(""), "")

    def test_mixed_depth_run_all_demoted(self):
        # ``# ㅇ`` + ``## ❍`` + ``### □`` in a run — all bullet-style at
        # any depth count toward the run, all get demoted.
        md = "\n".join(
            [
                "# ㅇ A",
                "",
                "## ❍ B",
                "",
                "### □ C",
            ]
        )
        result = _demote_over_promoted_bullet_headings(md)
        self.assertIn("ㅇ A", result)
        self.assertIn("❍ B", result)
        self.assertIn("□ C", result)
        for prefix in ("# ㅇ", "## ❍", "### □"):
            self.assertNotIn(prefix, result, f"Prefix {prefix!r} should be stripped")


if __name__ == "__main__":
    unittest.main()
