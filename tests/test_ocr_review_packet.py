from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "build_ocr_review_packet.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("ocr_review_packet_runner_test", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def artifact_fixture(candidate: str, text: str, *, status: str = "ok") -> dict:
    return {
        "schema_version": 1,
        "mode": "route_filtered_candidate_eval",
        "candidate": candidate,
        "status": status,
        "csv_row": 16,
        "doc_id": "real100_v2:path:16:unit",
        "source_sha256": "sha16",
        "source_file": "unit.hwp",
        "path_pdf": "unit.pdf",
        "pages": [
            {
                "page": 1,
                "audit": {"primary_route": "ocr_needed", "labels": ["ocr_needed"]},
                "status": status,
                "blocks": [{"text": text, "bbox": [0, 0, 1, 1], "confidence": 0.9}] if status == "ok" else [],
                "avg_confidence": 0.9 if status == "ok" else None,
                "runtime_s": 1.25,
                "failure": None if status == "ok" else {"code": "page_inference_failed", "message": "boom"},
                "attempts": [],
            }
        ],
        "elements": [
            {"type": "ocr_text", "page_span": [1, 1], "text": text, "bbox": [0, 0, 1, 1], "confidence": 0.9}
        ]
        if status == "ok"
        else [],
        "provenance": {"runtime_s": 1.25},
    }


class OcrReviewPacketTest(unittest.TestCase):
    def test_groups_candidate_outputs_by_page(self) -> None:
        runner = load_runner()
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            first = tmp / "first.json"
            second = tmp / "second.json"
            first.write_text(json.dumps(artifact_fixture("tesseract_baseline", "정답 후보")), encoding="utf-8")
            second.write_text(json.dumps(artifact_fixture("paddleocr_classic", "다른 후보")), encoding="utf-8")

            groups = runner.group_artifacts([first, second])

        self.assertEqual([(16, 1)], sorted(groups))
        candidates = groups[(16, 1)]["candidates"]
        self.assertEqual(["tesseract_baseline", "paddleocr_classic"], [item["candidate"] for item in candidates])
        self.assertEqual(["정답 후보", "다른 후보"], [item["text"] for item in candidates])

    def test_cli_writes_private_raw_text_and_textless_aggregate(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            artifact = tmp / "artifact.json"
            artifact.write_text(json.dumps(artifact_fixture("tesseract_baseline", "raw recognized OCR text")), encoding="utf-8")
            out_dir = tmp / "private"
            report_dir = tmp / "report"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER_PATH),
                    "--artifacts",
                    str(artifact),
                    "--run-id",
                    "unit-ocr-review",
                    "--out-dir",
                    str(out_dir),
                    "--report-dir",
                    str(report_dir),
                    "--no-render-images",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            private_md = (out_dir / "review_packet.md").read_text(encoding="utf-8")
            aggregate_json = (report_dir / "ocr_review.aggregate.json").read_text(encoding="utf-8")
            aggregate_md = (report_dir / "ocr_review.md").read_text(encoding="utf-8")
            self.assertIn("raw recognized OCR text", private_md)
            self.assertNotIn("raw recognized OCR text", aggregate_json)
            self.assertNotIn("raw recognized OCR text", aggregate_md)
            aggregate = json.loads(aggregate_json)
            self.assertEqual(1, aggregate["summary"]["pages"])
            self.assertEqual({"ok": 1}, aggregate["summary"]["candidate_page_status_counts"]["tesseract_baseline"])


if __name__ == "__main__":
    unittest.main()
