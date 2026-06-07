"""Regression guard for the opt-in Donut vision branch added for issue #168.

These tests must pass without torch / transformers installed: real model loads
are gated by env var and only happen inside ``donut_ocr_provider``. The factory
and the str-result wrap path are pure-python and runnable in CI.
"""

from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from visual_ingestion import (
    OCR_PROVIDERS,
    OcrResultShapeError,
    OcrUnavailable,
    _make_paddleocr_engine,
    _paddleocr_raw_to_blocks,
    donut_ocr_provider,
    get_ocr_provider,
    parse_pdf_artifact,
    parse_visual_document,
    tesseract_ocr_provider,
)


class GetOcrProviderFactoryTest(unittest.TestCase):
    def test_default_returns_tesseract(self) -> None:
        self.assertIs(get_ocr_provider(), tesseract_ocr_provider)
        self.assertIs(get_ocr_provider("tesseract"), tesseract_ocr_provider)

    def test_donut_resolves_without_loading_model(self) -> None:
        self.assertIs(get_ocr_provider("donut"), donut_ocr_provider)

    def test_env_var_donut_resolves_without_loading_model(self) -> None:
        os.environ["BIDMATE_VISUAL_OCR"] = "donut"
        try:
            self.assertIs(get_ocr_provider(), donut_ocr_provider)
        finally:
            os.environ.pop("BIDMATE_VISUAL_OCR", None)

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


class PaddleOcrOutputNormalizationTest(unittest.TestCase):
    def test_paddleocr_constructor_keeps_cpu_explicit_for_3x(self) -> None:
        captured: list[dict[str, object]] = []

        class FakePaddleOCR:
            def __init__(self, **kwargs):
                captured.append(kwargs)

        _make_paddleocr_engine(FakePaddleOCR, "korean")

        self.assertEqual("cpu", captured[0]["device"])

    def test_paddleocr_constructor_keeps_cpu_explicit_for_2x_fallback(self) -> None:
        captured: list[dict[str, object]] = []

        class FakePaddleOCR:
            def __init__(self, **kwargs):
                captured.append(kwargs)
                if "use_gpu" not in kwargs:
                    raise TypeError("3.x kwargs unsupported")

        _make_paddleocr_engine(FakePaddleOCR, "korean")

        self.assertEqual(False, captured[-1]["use_gpu"])

    def test_paddleocr_3x_result_shape_normalizes_to_blocks(self) -> None:
        class FakeResult:
            @property
            def json(self):
                return {
                    "res": {
                        "rec_texts": ["TEST 123"],
                        "rec_scores": [0.973],
                        "rec_boxes": [[18, 49, 64, 61]],
                    }
                }

        blocks = _paddleocr_raw_to_blocks([FakeResult()])

        self.assertEqual(
            [{"text": "TEST 123", "bbox": [18.0, 49.0, 64.0, 61.0], "confidence": 0.973}],
            blocks,
        )

    def test_paddleocr_3x_numpy_result_shape_normalizes_to_blocks(self) -> None:
        import numpy as np

        class FakeResult:
            @property
            def json(self):
                return {
                    "res": {
                        "rec_texts": ["TEST 123", "NEXT 456"],
                        "rec_scores": np.array([0.973, 0.961]),
                        "rec_boxes": np.array([[18, 49, 64, 61], [20, 70, 80, 82]]),
                    }
                }

        blocks = _paddleocr_raw_to_blocks([FakeResult()])

        self.assertEqual(
            [
                {"text": "TEST 123", "bbox": [18.0, 49.0, 64.0, 61.0], "confidence": 0.973},
                {"text": "NEXT 456", "bbox": [20.0, 70.0, 80.0, 82.0], "confidence": 0.961},
            ],
            blocks,
        )


    def test_paddleocr_unknown_nonempty_result_fails_closed(self) -> None:
        with self.assertRaisesRegex(OcrResultShapeError, "unrecognized"):
            _paddleocr_raw_to_blocks([{"unexpected": ["TEST 123"]}])

    def test_paddleocr_recognized_empty_result_stays_empty(self) -> None:
        blocks = _paddleocr_raw_to_blocks([{"res": {"rec_texts": []}}])

        self.assertEqual([], blocks)

    def test_paddleocr_2x_result_shape_normalizes_to_blocks(self) -> None:
        raw = [
            [
                (
                    [[18, 49], [64, 49], [64, 61], [18, 61]],
                    ("TEST 123", 0.973),
                )
            ]
        ]

        blocks = _paddleocr_raw_to_blocks(raw)

        self.assertEqual(
            [{"text": "TEST 123", "bbox": [18.0, 49.0, 64.0, 61.0], "confidence": 0.973}],
            blocks,
        )

    @unittest.skipIf(importlib.util.find_spec("pymupdf") is None, "pymupdf is not installed")
    def test_pdf_ocr_shape_error_records_page_failure_without_fail_fast(self) -> None:
        import pymupdf  # type: ignore

        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "shape-error.pdf"
            doc = pymupdf.open()
            page1 = doc.new_page()
            page1.insert_text((72, 72), "This page has enough text-layer content to parse without OCR.")
            page2 = doc.new_page()
            doc.save(pdf_path)
            doc.close()

            with patch.object(
                page2.__class__,
                "get_pixmap",
                side_effect=OcrResultShapeError("unrecognized OCR result shape"),
            ):
                artifact = parse_pdf_artifact(
                    pdf_path,
                    "doc",
                    "Shape Error",
                    "",
                    "",
                    {},
                    lambda _image: [],
                )

        self.assertNotEqual("failed", artifact["diagnostics"]["status"])
        self.assertIn("ocr_result_shape_error", artifact["diagnostics"]["reasons"])
        ocr_stages = [stage for stage in artifact["diagnostics"]["stages"] if stage["name"] == "ocr"]
        self.assertEqual("failed", ocr_stages[-1]["status"])
        self.assertEqual("ocr_result_shape_error", ocr_stages[-1]["reason"])
        self.assertEqual("unrecognized OCR result shape", ocr_stages[-1]["failures"][-1]["error"])

    @unittest.skipIf(importlib.util.find_spec("pymupdf") is None, "pymupdf is not installed")
    def test_pdf_sparse_text_records_empty_ocr_partial_reason(self) -> None:
        import pymupdf  # type: ignore

        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "sparse-text.pdf"
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((72, 72), "short text")
            doc.save(pdf_path)
            doc.close()

            artifact = parse_pdf_artifact(
                pdf_path,
                "doc",
                "Sparse Text",
                "",
                "",
                {},
                lambda _image: [],
            )

        self.assertIn("ocr_empty_result", artifact["diagnostics"]["reasons"])
        ocr_stages = [stage for stage in artifact["diagnostics"]["stages"] if stage["name"] == "ocr"]
        self.assertEqual("failed", ocr_stages[-1]["status"])
        self.assertEqual("ocr_empty_result", ocr_stages[-1]["reason"])



if __name__ == "__main__":
    unittest.main()
