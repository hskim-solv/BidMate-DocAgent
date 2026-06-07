from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = REPO_ROOT / "scripts" / "audit_parser_pages.py"


def load_audit():
    spec = importlib.util.spec_from_file_location("parser_page_audit_test", AUDIT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_tiny_pdf(path: Path) -> None:
    import pymupdf

    doc = pymupdf.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "사업명 테스트\n발주 기관 테스트\n요구사항 본문" * 5)
    page2 = doc.new_page()
    page2.insert_text((72, 72), "쪽")
    doc.save(path)
    doc.close()


class ParserPageAuditTest(unittest.TestCase):
    def test_classifies_text_layer_page(self) -> None:
        audit = load_audit()
        result = audit.classify_page_route(
            {
                "text_chars": 300,
                "image_count": 0,
                "image_area_ratio": 0.0,
                "table_count": 0,
                "mojibake_count": 0,
            }
        )

        self.assertEqual("text_layer", result["primary_route"])
        self.assertEqual(["text_layer"], result["labels"])

    def test_classifies_table_sidecar_page(self) -> None:
        audit = load_audit()
        result = audit.classify_page_route(
            {
                "text_chars": 300,
                "image_count": 0,
                "image_area_ratio": 0.0,
                "table_count": 2,
                "mojibake_count": 0,
            }
        )

        self.assertEqual("table_sidecar", result["primary_route"])
        self.assertIn("text_layer", result["labels"])
        self.assertIn("table_sidecar", result["labels"])

    def test_classifies_vlm_and_ocr_needed_page(self) -> None:
        audit = load_audit()
        result = audit.classify_page_route(
            {
                "text_chars": 10,
                "image_count": 3,
                "image_area_ratio": 0.35,
                "table_count": 0,
                "mojibake_count": 0,
            }
        )

        self.assertEqual("vlm_needed", result["primary_route"])
        self.assertIn("ocr_needed", result["labels"])
        self.assertIn("vlm_needed", result["labels"])

    def test_image_count_needs_min_area_for_vlm_route(self) -> None:
        audit = load_audit()
        result = audit.classify_page_route(
            {
                "text_chars": 120,
                "image_count": 6,
                "image_area_ratio": 0.004,
                "table_count": 0,
                "mojibake_count": 0,
            }
        )

        self.assertEqual("text_layer", result["primary_route"])
        self.assertEqual(["text_layer"], result["labels"])

    def test_table_detection_timeout_is_advisory_warning(self) -> None:
        audit = load_audit()

        class SlowPage:
            def find_tables(self):
                time.sleep(1)
                return []

        table_count, warning = audit.find_table_count(SlowPage(), timeout_s=0.01)

        self.assertIsNone(table_count)
        self.assertEqual("pymupdf_find_tables_timeout", warning)

    def test_table_detection_cap_skips_find_tables(self) -> None:
        audit = load_audit()

        class Page:
            rect = None

            def get_text(self, _kind):
                return "" if _kind == "text" else {"blocks": []}

            def get_images(self, full=True):  # noqa: ARG002
                return []

            def find_tables(self):
                raise AssertionError("find_tables should not be called after cap")

        features = audit.extract_page_features(Page(), page_number=2, table_max_pages_per_doc=1)

        self.assertIsNone(features["table_count"])
        self.assertIn("pymupdf_find_tables_skipped_by_cap", features["warnings"])

    def test_cli_writes_aggregate_without_raw_text(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            pdf_path = tmp / "doc.pdf"
            write_tiny_pdf(pdf_path)
            manifest_path = tmp / "manifest.json"
            subset_path = tmp / "subset.json"
            audit_dir = tmp / "audit"
            report_dir = tmp / "report"
            manifest = [
                {
                    "csv_row": "1",
                    "source_file": "기관_사업.hwp",
                    "source_sha256": "sha-1",
                    "path_pdf": str(pdf_path),
                    "page_count": 2,
                    "metadata": {"발주 기관": "테스트 기관", "사업명": "테스트 사업"},
                }
            ]
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            subset_path.write_text(json.dumps([{"csv_row": 1, "reason": "unit"}]), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(AUDIT_PATH),
                    "--manifest",
                    str(manifest_path),
                    "--subset",
                    str(subset_path),
                    "--run-id",
                    "unit",
                    "--audit-dir",
                    str(audit_dir),
                    "--report-dir",
                    str(report_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            aggregate_path = report_dir / "page_audit.aggregate.json"
            self.assertTrue(aggregate_path.exists())
            aggregate_text = aggregate_path.read_text(encoding="utf-8")
            aggregate = json.loads(aggregate_text)
            self.assertEqual(2, aggregate["summary"]["pages_audited"])
            self.assertIn("route_counts", aggregate["summary"])
            self.assertNotIn("요구사항 본문", aggregate_text)
            self.assertTrue((audit_dir / "page_audit.json").exists())


if __name__ == "__main__":
    unittest.main()
