"""Regression tests for rag_metadata_extraction (issue #180, ADR 0017).

LLM-mode backends (anthropic_tool_use, openai_function_call) are
opt-in and network-bound (and marked ``# pragma: no cover - network``
in the module). These tests cover the schema contract, the regex /
stub baseline, the payload coercion, dispatch, and the
fallback-on-failure path.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from rag_metadata_extraction import (
    _BACKENDS,
    DEFAULT_BACKEND,
    ENV_BACKEND,
    FIELD_NAMES,
    MetadataExtraction,
    TOOL_DEFINITION,
    _payload_to_extraction,
    _regex_backend,
    _stub_backend,
    extract_rfp_metadata,
)


SAMPLE_DOCUMENT: dict = {
    "doc_id": "sample-rfp",
    "title": "기관 A AI 사업",
    "agency": "기관 A",
    "project": "AI 챗봇 구축 사업",
    "metadata": {
        "agency": "기관 A",
        "project": "AI 챗봇 구축 사업",
        "budget": 150_000_000,
        "bid_start_at": "2026-06-01 09:00:00",
        "bid_deadline_at": "2026-06-30 17:00:00",
    },
    "sections": [
        {
            "heading": "본문",
            "text": "본 사업은 AI 챗봇 구축 사업이다. 문의: rfp@example.com",
        }
    ],
}


class ToolSchemaTest(unittest.TestCase):
    """The tool definition is the contract reviewers and the LLM both read."""

    def test_tool_definition_lists_all_eight_fields(self) -> None:
        properties = TOOL_DEFINITION["input_schema"]["properties"]
        for field in FIELD_NAMES:
            self.assertIn(
                field, properties, f"field {field!r} missing from tool schema"
            )

    def test_no_required_fields_so_partial_extraction_is_valid(self) -> None:
        # A conservative tool: omitting a field is preferred to
        # inventing one. If we ever flip a field to required, callers
        # must be opted in explicitly.
        self.assertEqual(
            [], TOOL_DEFINITION["input_schema"].get("required", [])
        )

    def test_additional_properties_disallowed(self) -> None:
        # Guard against the LLM smuggling unstructured fields in.
        self.assertFalse(
            TOOL_DEFINITION["input_schema"].get("additionalProperties", True)
        )

    def test_field_count_matches_field_names(self) -> None:
        # If FIELD_NAMES gains an entry the schema must, too.
        properties = TOOL_DEFINITION["input_schema"]["properties"]
        self.assertEqual(set(FIELD_NAMES), set(properties.keys()))


class RegexBackendTest(unittest.TestCase):
    def test_extracts_agency_project_budget_from_existing_metadata(self) -> None:
        result = _regex_backend(SAMPLE_DOCUMENT)
        self.assertEqual("기관 A", result.agency)
        self.assertEqual("AI 챗봇 구축 사업", result.project_name)
        self.assertEqual(150_000_000.0, result.budget_amount)
        self.assertEqual("KRW", result.budget_currency)

    def test_iso_dates_normalised_from_csv_timestamp_strings(self) -> None:
        result = _regex_backend(SAMPLE_DOCUMENT)
        self.assertEqual("2026-06-30", result.deadline_iso)
        self.assertEqual("2026-06-01", result.submission_date_iso)

    def test_email_picked_from_body_text(self) -> None:
        result = _regex_backend(SAMPLE_DOCUMENT)
        self.assertEqual("rfp@example.com", result.contact_email)

    def test_missing_budget_yields_none_currency(self) -> None:
        # Currency should only be set when an amount is present, so
        # downstream consumers can rely on "amount present ↔ currency set".
        doc = dict(SAMPLE_DOCUMENT)
        doc["metadata"] = {
            k: v for k, v in SAMPLE_DOCUMENT["metadata"].items() if k != "budget"
        }
        result = _regex_backend(doc)
        self.assertIsNone(result.budget_amount)
        self.assertIsNone(result.budget_currency)

    def test_empty_document_returns_empty_extraction(self) -> None:
        result = _regex_backend({})
        self.assertEqual(MetadataExtraction().as_dict(), result.as_dict())


class StubBackendInvariantTest(unittest.TestCase):
    """Stub MUST match regex byte-for-byte (contract test for ADR 0017)."""

    def test_stub_matches_regex_baseline_on_full_document(self) -> None:
        self.assertEqual(
            _regex_backend(SAMPLE_DOCUMENT).as_dict(),
            _stub_backend(SAMPLE_DOCUMENT).as_dict(),
        )

    def test_stub_matches_regex_baseline_on_empty_document(self) -> None:
        self.assertEqual(
            _regex_backend({}).as_dict(),
            _stub_backend({}).as_dict(),
        )


class PayloadCoercionTest(unittest.TestCase):
    def test_strings_and_numbers_both_coerced(self) -> None:
        payload = {
            "agency": "기관 X",
            "project_name": "사업 X",
            "budget_amount": "500000000",  # string from some endpoints
            "budget_currency": "KRW",
            "deadline_iso": "2027-01-31",
            "submission_date_iso": "2027-01-01",
            "contact_email": "x@example.com",
            "contact_name": "홍길동",
        }
        result = _payload_to_extraction(payload)
        self.assertEqual("기관 X", result.agency)
        self.assertEqual(500_000_000.0, result.budget_amount)
        self.assertEqual("2027-01-31", result.deadline_iso)
        self.assertEqual("홍길동", result.contact_name)

    def test_invalid_date_dropped_to_none(self) -> None:
        result = _payload_to_extraction({"deadline_iso": "next Friday"})
        self.assertIsNone(result.deadline_iso)

    def test_empty_payload_yields_default_extraction(self) -> None:
        result = _payload_to_extraction({})
        self.assertEqual(MetadataExtraction().as_dict(), result.as_dict())

    def test_unparseable_budget_dropped_to_none(self) -> None:
        result = _payload_to_extraction({"budget_amount": "약 5억원"})
        self.assertIsNone(result.budget_amount)


class DispatchTest(unittest.TestCase):
    def test_default_backend_constant_is_regex(self) -> None:
        # ADR 0001 invariant: regex is the default.
        self.assertEqual("regex", DEFAULT_BACKEND)

    def test_explicit_backend_argument_wins_over_env(self) -> None:
        with patch.dict(
            os.environ, {ENV_BACKEND: "anthropic_tool_use"}, clear=False
        ):
            result = extract_rfp_metadata(SAMPLE_DOCUMENT, backend="regex")
        # Did not raise (would have on an actual anthropic call without
        # a key) — and matches the regex baseline.
        self.assertEqual("기관 A", result.agency)

    def test_env_backend_selects_stub(self) -> None:
        with patch.dict(os.environ, {ENV_BACKEND: "stub"}, clear=False):
            result = extract_rfp_metadata(SAMPLE_DOCUMENT)
        self.assertEqual("기관 A", result.agency)

    def test_unknown_backend_raises_valueerror(self) -> None:
        with self.assertRaises(ValueError):
            extract_rfp_metadata(SAMPLE_DOCUMENT, backend="bogus")


class FallbackOnBackendErrorTest(unittest.TestCase):
    """Any backend exception MUST fall back to regex, not propagate."""

    def test_runtime_failure_returns_regex_baseline(self) -> None:
        def _broken(_doc: dict) -> MetadataExtraction:
            raise RuntimeError("simulated network failure")

        original = _BACKENDS["anthropic_tool_use"]
        _BACKENDS["anthropic_tool_use"] = _broken
        try:
            result = extract_rfp_metadata(
                SAMPLE_DOCUMENT, backend="anthropic_tool_use"
            )
        finally:
            _BACKENDS["anthropic_tool_use"] = original
        # Regex baseline survived the simulated network failure.
        self.assertEqual("기관 A", result.agency)
        self.assertEqual(150_000_000.0, result.budget_amount)


if __name__ == "__main__":
    unittest.main()
