"""Regression guard for the phase2 structure-aware boundary detector
(issue #1364).

The inline ``_ENUM`` regex in ``scripts/phase2_chunking_ablation.py``
used to require ``숫자 → (점+숫자)* → 공백``, which silently MISSED the
most common Korean RFP top-level section form ``1. 사업개요`` — the lone
``.`` after a single-level number matched neither ``.\\d+`` nor ``\\s+``.
The numeric branch now carries an optional trailing dot (``\\.?``) so
``1. `` / ``1.1. `` join the already-matching ``1 `` / ``1.1 `` /
``(1) `` / ``가. `` forms.

No unit test covered this detector before, which is why the asymmetry
(``가. `` matched but ``1. `` did not) went unnoticed. These checks pin
both the regex and the ``detect_boundaries`` /
``split_body_into_sections`` callers.
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from phase2_chunking_ablation import (  # noqa: E402
    _ENUM,
    detect_boundaries,
    split_body_into_sections,
)


class EnumRegexTest(unittest.TestCase):
    """Direct matches on the section-enumeration regex."""

    def test_numeric_dot_top_level_headers_match(self) -> None:
        # The previously-missed case: single-level "N. " headers.
        for header in ("1. 사업개요", "2. 입찰안내", "3. 제출서류"):
            with self.subTest(header=header):
                self.assertIsNotNone(
                    _ENUM.match(header),
                    f"{header!r} should be detected as a section boundary",
                )

    def test_existing_forms_still_match(self) -> None:
        # Guard that the \.? addition did not break prior matches.
        for header in (
            "1 사업개요",  # dot-less single level
            "1.1 세부내용",  # interior dot, no trailing
            "1.1.1 항목",  # multi-level
            "1.1. 항목",  # multi-level with trailing dot
            "(1) 가목",  # paren enumeration
            "가. 일반사항",  # Korean letter + dot
        ):
            with self.subTest(header=header):
                self.assertIsNotNone(_ENUM.match(header), header)


class DetectBoundariesTest(unittest.TestCase):
    """Caller-level checks: numeric dot headers split a real body."""

    def _make_body(self) -> str:
        # >= _MIN_SPLIT_BODY (300) chars, three "N. " sections, no
        # 제N장 header / markdown / blank-gap so detection rests solely
        # on the _ENUM numeric-dot branch.
        filler = "본 항목은 입찰 참가자가 숙지해야 할 세부 내용을 담고 있습니다. " * 4
        return (
            "1. 사업개요\n" + filler + "\n"
            "2. 입찰안내\n" + filler + "\n"
            "3. 제출서류\n" + filler + "\n"
        )

    def test_numeric_dot_headers_yield_boundaries(self) -> None:
        body = self._make_body()
        offsets = detect_boundaries(body)
        # "2. 입찰안내" and "3. 제출서류" start offsets must be collected
        # (offset 0 — the "1." header — is discarded by design).
        self.assertIn(body.index("2. 입찰안내"), offsets)
        self.assertIn(body.index("3. 제출서류"), offsets)

    def test_split_engages_into_multiple_sections(self) -> None:
        body = self._make_body()
        sections, engaged = split_body_into_sections(body)
        self.assertTrue(engaged)
        self.assertGreaterEqual(len(sections), 2)
        headings = [s["heading"] for s in sections]
        self.assertTrue(any(h.startswith("2. 입찰안내") for h in headings))


if __name__ == "__main__":
    unittest.main()
