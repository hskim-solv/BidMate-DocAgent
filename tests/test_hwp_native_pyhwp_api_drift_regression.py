"""pyhwp API drift adaptation regression suite (issue #801).

PR #787 (closes #785) added ``AttributeError`` to
``_hwp_native_fallback_exceptions`` so that pyhwp 0.1b15's
``'OleStorage' object has no attribute 'section_list'`` no longer aborts
the build — but it left HWP native extraction at **0/96** native rate on
the private 100-doc corpus. The defensive layer hides the regression
behind a silent CSV fallback.

This suite pins the **active** adaptation: ``_hwp_bodytext_sections``
must accept both the legacy ``bodytext.section_list()`` method (pyhwp
≤ 0.1b13) and the 0.1b15+ ``bodytext.sections`` list attribute, so the
native loader keeps working across both API generations without further
defensive catches.
"""

from __future__ import annotations

import unittest

from ingestion import _hwp_bodytext_sections


class _FakeBodyTextB15:
    """0.1b15+ shape — ``sections`` is a plain list attribute."""

    def __init__(self, sections: list[object]) -> None:
        self.sections = sections


class _FakeBodyTextB13:
    """≤0.1b13 shape — ``section_list()`` is a method that returns the list."""

    def __init__(self, sections: list[object]) -> None:
        self._sections = sections

    def section_list(self) -> list[object]:
        return self._sections


class _FakeBodyTextBoth:
    """Defensive: when both shapes are present, the attribute wins (newer API)."""

    def __init__(
        self, attr_sections: list[object], method_sections: list[object]
    ) -> None:
        self.sections = attr_sections
        self._method_sections = method_sections

    def section_list(self) -> list[object]:
        return self._method_sections


class _FakeBodyTextNeither:
    """Incompatible upstream — neither shape is exposed."""


class _FakeHwp:
    def __init__(self, bodytext: object) -> None:
        self.bodytext = bodytext


class HwpBodytextSectionsApiDriftTest(unittest.TestCase):
    def test_pyhwp_0_1b15_sections_attribute(self) -> None:
        """pyhwp 0.1b15+: ``bodytext.sections`` list attribute is walked directly."""
        sections = [object(), object()]
        hwp = _FakeHwp(_FakeBodyTextB15(sections))
        self.assertEqual(sections, list(_hwp_bodytext_sections(hwp)))

    def test_pyhwp_legacy_section_list_method(self) -> None:
        """pyhwp ≤0.1b13: ``bodytext.section_list()`` method is called."""
        sections = [object(), object(), object()]
        hwp = _FakeHwp(_FakeBodyTextB13(sections))
        self.assertEqual(sections, list(_hwp_bodytext_sections(hwp)))

    def test_attribute_wins_when_both_shapes_present(self) -> None:
        """If an intermediate pyhwp release exposes both, prefer the newer
        attribute form so a downstream rename of ``section_list`` (already
        in motion in 0.1b15) doesn't quietly flip behaviour."""
        attr_sections = [object()]
        method_sections = [object(), object()]
        hwp = _FakeHwp(_FakeBodyTextBoth(attr_sections, method_sections))
        self.assertIs(attr_sections, _hwp_bodytext_sections(hwp))

    def test_empty_sections_list_is_returned_as_is(self) -> None:
        """An HWP with zero body sections is valid; the helper must not
        confuse an empty list with the missing-attribute case."""
        hwp = _FakeHwp(_FakeBodyTextB15([]))
        self.assertEqual([], list(_hwp_bodytext_sections(hwp)))

    def test_neither_shape_raises_attribute_error(self) -> None:
        """Incompatible upstream: helper raises ``AttributeError`` so the
        existing ``_hwp_native_fallback_exceptions`` tuple still catches it
        and the build degrades to CSV text instead of aborting."""
        hwp = _FakeHwp(_FakeBodyTextNeither())
        with self.assertRaises(AttributeError) as ctx:
            _hwp_bodytext_sections(hwp)
        # Message must name both shapes so future debugging is self-evident.
        msg = str(ctx.exception)
        self.assertIn("sections", msg)
        self.assertIn("section_list", msg)

    def test_section_list_attribute_that_is_not_callable_falls_through(self) -> None:
        """Defensive: if a future pyhwp release exposes ``section_list`` as
        a non-callable (e.g. a plain alias for ``sections``), the helper must
        treat it as a non-match and use the modern attribute path instead."""

        class _Mixed:
            def __init__(self, sections: list[object]) -> None:
                self.sections = sections
                self.section_list = sections  # non-callable alias

        sections = [object()]
        hwp = _FakeHwp(_Mixed(sections))
        self.assertIs(sections, _hwp_bodytext_sections(hwp))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
