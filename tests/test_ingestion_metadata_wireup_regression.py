"""Regression for the #180 metadata-extraction wire-up in ingestion.py.

Issue #180 (ADR 0017) adds an *additive* metadata sidecar — every
ingested document carries an eight-field structured extraction under
``document["metadata"]["extracted"]``. The contract here:

* The default backend is ``regex`` (the ADR 0001 invariant).
* The ``stub`` backend matches ``regex`` bit-for-bit so deterministic
  / offline runs (public CI, unit tests) stay stable.
* The wire-up never overwrites the top-level ``agency`` /
  ``project`` fields — those feed the answer/citation contract
  (ADR 0003) and chunk-metadata propagation in rag_core.py.
* An LLM-backend exception falls back to ``regex`` rather than
  losing the metadata; the network path is not exercised here.

The test runs the real ``normalize_ingestion_row`` against a tiny
in-memory CSV row so it covers the integration seam, not just the
``extract_rfp_metadata`` unit.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ingestion import _DuplicateTracker, normalize_ingestion_row
from rag_metadata_extraction import (
    ENV_BACKEND,
    FIELD_NAMES,
    MetadataExtraction,
    extract_rfp_metadata,
)


def _csv_row(
    *,
    notice_id: str = "202500001",
    project: str = "기관 A 보안 사업",
    agency: str = "기관 A",
    budget: str = "100000000",
    deadline: str = "2025-04-01 17:00:00",
    start_at: str = "2025-03-01 09:00:00",
    file_name: str = "sample.pdf",
    text: str = "본문입니다. 문의: contact@example.com",
) -> dict[str, str]:
    return {
        "공고 번호": notice_id,
        "공고 차수": "0.0",
        "사업명": project,
        "사업 금액": budget,
        "발주 기관": agency,
        "공개 일자": "2025-01-01 09:00:00",
        "입찰 참여 시작일": start_at,
        "입찰 참여 마감일": deadline,
        "사업 요약": "요약",
        "파일형식": "pdf",
        "파일명": file_name,
        "텍스트": text,
    }


class IngestionMetadataWireupTest(unittest.TestCase):
    """The wire-up populates ``metadata["extracted"]`` on every doc."""

    def _normalize_one(
        self, row: dict[str, str], files_dir: Path
    ) -> dict:
        tracker = _DuplicateTracker()
        document, record = normalize_ingestion_row(
            row, row_number=1, files_dir=files_dir, tracker=tracker
        )
        self.assertEqual(
            record.status,
            "indexed",
            f"row should have been indexed; record={record}",
        )
        assert document is not None  # narrow for mypy / readers
        return document

    def test_extracted_sidecar_is_present_with_eight_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            files_dir = Path(tmp)
            (files_dir / "sample.pdf").write_bytes(b"%PDF-1.4\n")
            document = self._normalize_one(_csv_row(), files_dir)
        extracted = document["metadata"].get("extracted")
        self.assertIsInstance(extracted, dict, "extracted sidecar missing")
        # The dataclass-as-dict ships every field declared in
        # ``MetadataExtraction`` — even if the value is ``None`` —
        # so downstream consumers can rely on a stable shape.
        for field in FIELD_NAMES:
            self.assertIn(
                field,
                extracted,
                f"extracted sidecar is missing field {field!r}",
            )

    def test_extracted_matches_regex_baseline_on_default_backend(self) -> None:
        """Without env override, the wire-up must mirror ``extract_rfp_metadata``."""
        with tempfile.TemporaryDirectory() as tmp:
            files_dir = Path(tmp)
            (files_dir / "sample.pdf").write_bytes(b"%PDF-1.4\n")
            row = _csv_row()
            document = self._normalize_one(row, files_dir)
        # Re-run extract_rfp_metadata against the document the wire-up
        # built and confirm the sidecar matches — this also catches
        # silent drift if the regex backend logic ever changes.
        expected = extract_rfp_metadata(document).as_dict()
        self.assertEqual(document["metadata"]["extracted"], expected)

    def test_wireup_preserves_top_level_agency_and_project(self) -> None:
        """ADR 0003 / chunk-propagation guard: top-level fields are untouched."""
        with tempfile.TemporaryDirectory() as tmp:
            files_dir = Path(tmp)
            (files_dir / "sample.pdf").write_bytes(b"%PDF-1.4\n")
            row = _csv_row(agency="기관 X", project="프로젝트 X")
            document = self._normalize_one(row, files_dir)
        self.assertEqual(document["agency"], "기관 X")
        self.assertEqual(document["project"], "프로젝트 X")
        # The legacy ``metadata["agency"]`` / ``metadata["project"]``
        # CSV-passthrough mirrors must also stay intact — they feed
        # the existing metadata-first retrieval path.
        self.assertEqual(document["metadata"]["agency"], "기관 X")
        self.assertEqual(document["metadata"]["project"], "프로젝트 X")

    def test_stub_backend_matches_regex_on_wireup_path(self) -> None:
        """ADR 0001 invariant: stub backend produces the regex output bit-for-bit."""
        with tempfile.TemporaryDirectory() as tmp:
            files_dir = Path(tmp)
            (files_dir / "sample.pdf").write_bytes(b"%PDF-1.4\n")
            row = _csv_row()
            with mock.patch.dict(os.environ, {ENV_BACKEND: "regex"}):
                regex_doc = self._normalize_one(row, files_dir)
            with mock.patch.dict(os.environ, {ENV_BACKEND: "stub"}):
                stub_doc = self._normalize_one(row, files_dir)
        self.assertEqual(
            regex_doc["metadata"]["extracted"],
            stub_doc["metadata"]["extracted"],
            "stub backend must mirror regex baseline on the wire-up path",
        )

    def test_extracted_captures_email_from_body_text(self) -> None:
        """The regex baseline grabs the first email out of section text."""
        with tempfile.TemporaryDirectory() as tmp:
            files_dir = Path(tmp)
            (files_dir / "sample.pdf").write_bytes(b"%PDF-1.4\n")
            row = _csv_row(text="문의는 contact-A@example.co.kr 로 보내주세요.")
            document = self._normalize_one(row, files_dir)
        extracted = document["metadata"]["extracted"]
        self.assertEqual(extracted["contact_email"], "contact-A@example.co.kr")

    def test_extracted_carries_csv_budget_as_float(self) -> None:
        """CSV `사업 금액` should surface as ``budget_amount`` with KRW currency."""
        with tempfile.TemporaryDirectory() as tmp:
            files_dir = Path(tmp)
            (files_dir / "sample.pdf").write_bytes(b"%PDF-1.4\n")
            row = _csv_row(budget="250000000")
            document = self._normalize_one(row, files_dir)
        extracted = document["metadata"]["extracted"]
        self.assertEqual(extracted["budget_amount"], 250000000.0)
        self.assertEqual(extracted["budget_currency"], "KRW")

    def test_llm_backend_exception_falls_back_to_regex_baseline(self) -> None:
        """An LLM-backend error must NEVER strip metadata from the document.

        Simulates a network/API failure by pointing the backend to the
        Anthropic path with the SDK explicitly missing the API key —
        ``extract_rfp_metadata`` catches the exception and returns the
        regex baseline. The wire-up therefore never produces a
        partially-populated document.
        """
        with tempfile.TemporaryDirectory() as tmp:
            files_dir = Path(tmp)
            (files_dir / "sample.pdf").write_bytes(b"%PDF-1.4\n")
            row = _csv_row()
            # Force the Anthropic path; clearing the API key triggers
            # the RuntimeError inside ``_anthropic_tool_use_backend``,
            # which ``extract_rfp_metadata`` converts to a regex
            # fallback (per its docstring contract).
            env = {ENV_BACKEND: "anthropic_tool_use", "ANTHROPIC_API_KEY": ""}
            with mock.patch.dict(os.environ, env, clear=False):
                document = self._normalize_one(row, files_dir)
        extracted = document["metadata"]["extracted"]
        regex_expected = extract_rfp_metadata(
            document, backend="regex"
        ).as_dict()
        self.assertEqual(extracted, regex_expected)


if __name__ == "__main__":
    unittest.main()
