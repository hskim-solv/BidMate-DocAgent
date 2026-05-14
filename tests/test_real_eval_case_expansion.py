"""Regression guard for real100 eval case expansion (ADR 0044, issue #732).

Verifies structural invariants of eval/real_config.local.yaml when the
file is present (operator-side private file, gitignored per ADR 0005).
Tests are skipped silently when the file does not exist — CI runs on the
public synthetic surface and has no access to the private config.

Invariants checked:
1. Case count meets the ADR 0044 minimum (≥ 25 after first expansion,
   targeting ≥ 30).
2. All case IDs are unique.
3. Each case has required fields (id, query_type, query, expected_doc_ids,
   answerable).
4. expected_terms is non-empty for answerable cases.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
REAL_CONFIG_PATH = ROOT_DIR / "eval" / "real_config.local.yaml"

# ADR 0044 minimum: at least 25 cases (first expansion target is 30+).
# This threshold is conservative so CI of other developers who may have
# older local configs still passes.
MIN_CASE_COUNT = 25


def _load_config() -> dict | None:
    """Return parsed config or None if file is absent."""
    if not REAL_CONFIG_PATH.exists():
        return None
    try:
        import yaml  # type: ignore
        with REAL_CONFIG_PATH.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


@unittest.skipUnless(REAL_CONFIG_PATH.exists(), "eval/real_config.local.yaml not present (operator-side private file)")
class TestRealConfigCaseExpansion(unittest.TestCase):
    """Structural invariants for the expanded real100 eval case set."""

    @classmethod
    def setUpClass(cls) -> None:
        cfg = _load_config()
        if cfg is None:
            raise RuntimeError(f"Failed to parse {REAL_CONFIG_PATH}")
        cls.cases: list[dict] = cfg.get("cases", [])

    def test_case_count_meets_adr0044_minimum(self) -> None:
        """ADR 0044: n ≥ 25 (near-term target 30+)."""
        self.assertGreaterEqual(
            len(self.cases),
            MIN_CASE_COUNT,
            f"real_config.local.yaml has {len(self.cases)} cases; ADR 0044 requires ≥ {MIN_CASE_COUNT}",
        )

    def test_case_ids_are_unique(self) -> None:
        ids = [c.get("id") for c in self.cases]
        duplicates = {cid for cid in ids if ids.count(cid) > 1}
        self.assertEqual(
            len(duplicates), 0,
            f"Duplicate case IDs found: {duplicates}",
        )

    def test_all_cases_have_required_fields(self) -> None:
        required = {"id", "query_type", "query", "expected_doc_ids", "answerable"}
        for case in self.cases:
            missing = required - set(case.keys())
            self.assertEqual(
                len(missing), 0,
                f"Case '{case.get('id')}' missing required fields: {missing}",
            )

    def test_answerable_cases_have_expected_terms(self) -> None:
        """Answerable cases must have at least one expected_term to be evaluable."""
        for case in self.cases:
            if not case.get("answerable", True):
                continue
            terms = case.get("expected_terms") or []
            self.assertGreater(
                len(terms), 0,
                f"Answerable case '{case.get('id')}' has no expected_terms",
            )

    def test_expected_doc_ids_non_empty_for_answerable(self) -> None:
        for case in self.cases:
            if not case.get("answerable", True):
                continue
            doc_ids = case.get("expected_doc_ids") or []
            self.assertGreater(
                len(doc_ids), 0,
                f"Answerable case '{case.get('id')}' has no expected_doc_ids",
            )


if __name__ == "__main__":
    unittest.main()
