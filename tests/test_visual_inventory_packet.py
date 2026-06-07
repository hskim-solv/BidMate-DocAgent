from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "build_visual_inventory_packet.py"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class VisualInventoryPacketTest(unittest.TestCase):
    def test_cli_writes_textless_aggregate_from_page_audit(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            page_audit = tmp / "page_audit.json"
            out_dir = tmp / "private"
            report_dir = tmp / "report"
            write_json(
                page_audit,
                {
                    "run": {"run_id": "audit-unit"},
                    "documents": [
                        {
                            "csv_row": 62,
                            "subset_rank": 1,
                            "doc_id": "doc-62",
                            "source_sha256": "sha62",
                            "source_file": "unit.hwp",
                            "path_pdf": "unit.pdf",
                            "expected_page_count": 2,
                            "pages": [
                                {
                                    "page": 1,
                                    "text_chars": 120,
                                    "hangul_ratio": 0.5,
                                    "mojibake_count": 0,
                                    "image_count": 5,
                                    "image_area_ratio": 0.5,
                                    "table_count": None,
                                    "warnings": ["pymupdf_find_tables_skipped_by_cap"],
                                    "labels": ["text_layer", "vlm_needed"],
                                    "primary_route": "vlm_needed",
                                    "reasons": ["large_image_area"],
                                },
                                {
                                    "page": 2,
                                    "text_chars": 500,
                                    "hangul_ratio": 0.5,
                                    "mojibake_count": 0,
                                    "image_count": 0,
                                    "image_area_ratio": 0.0,
                                    "table_count": 0,
                                    "warnings": [],
                                    "labels": ["text_layer"],
                                    "primary_route": "text_layer",
                                    "reasons": ["text_chars_above_threshold"],
                                },
                            ],
                        }
                    ],
                },
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER_PATH),
                    "--page-audit",
                    str(page_audit),
                    "--csv-rows",
                    "62",
                    "--primary-routes",
                    "vlm_needed",
                    "--max-pages",
                    "5",
                    "--no-render-images",
                    "--run-id",
                    "unit-visual-inventory",
                    "--out-dir",
                    str(out_dir),
                    "--report-dir",
                    str(report_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            private_packet = json.loads((out_dir / "visual_inventory.json").read_text(encoding="utf-8"))
            aggregate_text = (report_dir / "visual_inventory.aggregate.json").read_text(encoding="utf-8")
            aggregate = json.loads(aggregate_text)
            self.assertEqual(1, len(private_packet["pages"]))
            self.assertEqual(1, aggregate["summary"]["pages"])
            self.assertEqual({"vlm_needed": 1}, aggregate["summary"]["route_counts"])
            self.assertEqual(1, aggregate["summary"]["visual_need_tag_counts"]["large_image_area"])
            self.assertEqual(1, aggregate["summary"]["visual_need_tag_counts"]["image_rich"])
            self.assertEqual(1, aggregate["summary"]["visual_need_tag_counts"]["visual_layout"])
            self.assertIn("image_relpath", aggregate["pages"][0])
            self.assertNotIn("raw page text", aggregate_text)


if __name__ == "__main__":
    unittest.main()
