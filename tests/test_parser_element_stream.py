from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "build_parser_element_stream.py"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def candidate_artifact(candidate: str, *, element_type: str, text: str) -> dict:
    raw_type = "table" if element_type == "table" else "paragraph"
    return {
        "schema_version": 1,
        "candidate": candidate,
        "candidate_version": "unit",
        "provider": "local",
        "status": "ok",
        "csv_row": 1,
        "doc_id": "real100_v2:path:1:unit",
        "source_file": "unit.hwp",
        "source_sha256": "sha1",
        "path_pdf": "unit.pdf",
        "metadata": {"사업명": "테스트"},
        "elements": [{"type": raw_type, "page_span": [1, 1], "text": text, "bbox": None, "table_id": "t1"}],
        "provenance": {"runtime_s": 1.0, "cost_usd": 0.0},
    }


class ParserElementStreamTest(unittest.TestCase):
    def test_cli_builds_private_stream_and_textless_aggregate(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            manifest = tmp / "manifest.json"
            subset = tmp / "subset.json"
            page_audit = tmp / "page_audit.json"
            parser_run = tmp / "parser_run"
            ocr_review = tmp / "ocr_review.json"
            out_dir = tmp / "out"
            report_dir = tmp / "report"
            write_json(
                manifest,
                [
                    {
                        "csv_row": "1",
                        "source_file": "unit.hwp",
                        "source_sha256": "sha1",
                        "path_pdf": str(tmp / "unit.pdf"),
                        "page_count": 1,
                        "metadata": {"사업명": "테스트 사업"},
                    }
                ],
            )
            (tmp / "unit.pdf").write_bytes(b"%PDF-1.4\n%unit\n")
            write_json(subset, [{"csv_row": 1, "rank": 1, "reason": "unit"}])
            write_json(
                page_audit,
                {
                    "run": {"run_id": "audit-unit"},
                    "documents": [
                        {
                            "csv_row": 1,
                            "route_counts": {"ocr_needed": 1},
                            "label_counts": {"ocr_needed": 1},
                            "pages": [{"page": 1, "labels": ["ocr_needed"], "primary_route": "ocr_needed"}],
                        }
                    ],
                },
            )
            write_json(
                parser_run / "candidates" / "pymupdf4llm_current" / "row-0001.json",
                candidate_artifact("pymupdf4llm_current", element_type="text", text="private text layer"),
            )
            write_json(
                parser_run / "candidates" / "pdfplumber_table_sidecar" / "row-0001.json",
                candidate_artifact("pdfplumber_table_sidecar", element_type="table", text="private table text"),
            )
            write_json(
                ocr_review,
                {
                    "run": {"run_id": "ocr-review-unit"},
                    "pages": [
                        {
                            "csv_row": 1,
                            "page": 1,
                            "doc_id": "real100_v2:path:1:unit",
                            "audit": {"labels": ["ocr_needed"]},
                            "review": {"winner": "paddleocr_classic", "status": "draft_ai_visual_review"},
                            "candidates": [
                                {
                                    "candidate": "paddleocr_classic",
                                    "text": "private ocr text",
                                    "avg_confidence": 0.9,
                                    "runtime_s": 2.0,
                                    "provenance": {"cost_usd": 0.0},
                                }
                            ],
                        }
                    ],
                },
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER_PATH),
                    "--manifest",
                    str(manifest),
                    "--subset",
                    str(subset),
                    "--page-audit",
                    str(page_audit),
                    "--parser-run-dir",
                    str(parser_run),
                    "--ocr-review-packet",
                    str(ocr_review),
                    "--run-id",
                    "unit-element-stream",
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
            stream_text = (out_dir / "element_stream.json").read_text(encoding="utf-8")
            aggregate_text = (report_dir / "element_stream.aggregate.json").read_text(encoding="utf-8")
            self.assertIn("private text layer", stream_text)
            self.assertIn("private table text", stream_text)
            self.assertIn("private ocr text", stream_text)
            self.assertNotIn("private text layer", aggregate_text)
            self.assertNotIn("private table text", aggregate_text)
            self.assertNotIn("private ocr text", aggregate_text)
            aggregate = json.loads(aggregate_text)
            self.assertEqual(1, aggregate["summary"]["documents"])
            self.assertEqual(8, aggregate["summary"]["elements"])
            self.assertEqual(1, aggregate["summary"]["element_type_counts"]["text_layer"])
            self.assertEqual(1, aggregate["summary"]["element_type_counts"]["table"])
            self.assertEqual(1, aggregate["summary"]["element_type_counts"]["ocr_text"])
            self.assertEqual(5, aggregate["summary"]["element_type_counts"]["metadata_fact"])


if __name__ == "__main__":
    unittest.main()
