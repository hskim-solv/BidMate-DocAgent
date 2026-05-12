"""Opt-in PII redaction at ingestion time (issue #455, ADR 0028).

`BIDMATE_INGEST_REDACT_PII=true` flips the redaction pass on. Default
off keeps ADR 0001 `naive_baseline` byte-identical.
"""

from __future__ import annotations

import unittest

from ingestion import _pii_redaction_enabled


class PiiRedactionEnvFlagTest(unittest.TestCase):
    """The env-var gate is the single switch operators flip."""

    def test_default_off(self) -> None:
        # No env var set → off. The test runner does not export the var.
        import os

        os.environ.pop("BIDMATE_INGEST_REDACT_PII", None)
        self.assertFalse(_pii_redaction_enabled())

    def test_true_values_enable(self) -> None:
        import os

        for value in ("1", "true", "TRUE", "yes", "Yes"):
            os.environ["BIDMATE_INGEST_REDACT_PII"] = value
            try:
                self.assertTrue(_pii_redaction_enabled(), f"expected enabled for {value!r}")
            finally:
                os.environ.pop("BIDMATE_INGEST_REDACT_PII", None)

    def test_false_values_disabled(self) -> None:
        import os

        for value in ("", "0", "false", "no", "  ", "random"):
            os.environ["BIDMATE_INGEST_REDACT_PII"] = value
            try:
                self.assertFalse(
                    _pii_redaction_enabled(),
                    f"expected disabled for {value!r}",
                )
            finally:
                os.environ.pop("BIDMATE_INGEST_REDACT_PII", None)


if __name__ == "__main__":
    unittest.main()
