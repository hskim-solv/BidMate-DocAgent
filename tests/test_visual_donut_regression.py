"""Regression guard for the opt-in Donut vision branch added for issue #168.

These tests must pass without torch / transformers installed: real model loads
are gated by env var and only happen inside ``donut_ocr_provider``. The factory
and the str-result wrap path are pure-python and runnable in CI.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from visual_ingestion import (
    OCR_PROVIDERS,
    donut_ocr_provider,
    get_ocr_provider,
    parse_visual_document,
    tesseract_ocr_provider,
)


class GetOcrProviderFactoryTest(unittest.TestCase):
    def test_default_returns_tesseract(self) -> None:
        self.assertIs(get_ocr_provider(), tesseract_ocr_provider)
        self.assertIs(get_ocr_provider("tesseract"), tesseract_ocr_provider)

    def test_donut_resolves_without_loading_model(self) -> None:
        self.assertIs(get_ocr_provider("donut"), donut_ocr_provider)

    def test_unknown_name_lists_valid_options(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            get_ocr_provider("bogus")
        message = str(ctx.exception)
        for name in OCR_PROVIDERS:
            self.assertIn(name, message)

    def test_case_insensitive(self) -> None:
        self.assertIs(get_ocr_provider("DONUT"), donut_ocr_provider)


class DonutStringOutputNormalizationTest(unittest.TestCase):
    @unittest.skipIf(importlib.util.find_spec("pymupdf") is None, "pymupdf is not installed")
    def test_donut_string_output_wrapped_to_block_via_existing_pipeline(self) -> None:
        """Donut returns a single text blob per image; ensure it lands as a block."""
        import pymupdf  # type: ignore

        donut_text = "Project: Donut Spike\nRequirement: Layout-aware extraction"

        def fake_donut(_image):
            return donut_text

        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "donut_sample.pdf"
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((72, 72), "")
            doc.save(pdf_path)
            doc.close()

            document, artifact = parse_visual_document(
                pdf_path,
                doc_id="donut-regression",
                title="Donut Spike",
                ocr_provider=fake_donut,
            )

        self.assertIsNotNone(document)
        self.assertEqual("parsed", artifact["diagnostics"]["status"])
        all_text = "\n".join(b["text"] for p in artifact["pages"] for b in p["blocks"])
        self.assertIn("Donut Spike", all_text)
        self.assertIn("Layout-aware extraction", all_text)


if __name__ == "__main__":
    unittest.main()
