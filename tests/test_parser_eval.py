import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from eval.run_parser_eval import (
    build_report,
    load_gold,
    score_document,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT_DIR / "eval" / "fixtures" / "parser_visual_v2"
GOLD_PATH = ROOT_DIR / "eval" / "parser_visual_v2_gold.yaml"


class ParserEvalTest(unittest.TestCase):
    def test_scores_clean_fixture_without_errors(self) -> None:
        gold = load_gold(GOLD_PATH)
        artifact_path = FIXTURE_DIR / "parser-fixture-doc.visual.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

        result = score_document(gold["documents"][0], artifact, artifact_path)

        self.assertEqual("parser-fixture-doc", result["doc_id"])
        self.assertEqual([], result["errors"])
        self.assertEqual(1.0, result["metrics"]["ocr_text_recall"])
        self.assertEqual(1.0, result["metrics"]["ocr_char_f1"])
        self.assertEqual(1.0, result["metrics"]["layout_block_f1"])
        self.assertEqual(1.0, result["metrics"]["field_f1"])
        self.assertEqual(1.0, result["metrics"]["bbox_alignment_rate"])

    def test_scores_missing_field_and_bbox_errors(self) -> None:
        gold = {
            "doc_id": "broken-doc",
            "ocr_text": {"snippets": ["사업명: 오류 사례"]},
            "layout_blocks": [{"text": "사업명: 오류 사례", "type": "text", "page_number": 1}],
            "fields": [{"key": "사업명", "value": "오류 사례"}],
            "bbox_anchors": [{"text": "사업명: 오류 사례", "page_number": 1}],
        }
        artifact = {
            "doc_id": "broken-doc",
            "pages": [
                {
                    "page_number": 1,
                    "blocks": [
                        {
                            "text": "사업명: 오류 사례",
                            "type": "text",
                            "page_number": 1,
                            "bbox": None,
                        }
                    ],
                }
            ],
            "field_candidates": [],
            "sections": [],
            "tables": [],
            "diagnostics": {"status": "parsed"},
        }

        result = score_document(gold, artifact, Path("broken-doc.visual.json"))
        codes = {error["code"] for error in result["errors"]}

        self.assertIn("field_missing", codes)
        self.assertIn("bbox_missing", codes)
        self.assertEqual(0.0, result["metrics"]["field_recall"])
        self.assertEqual(0.0, result["metrics"]["bbox_alignment_rate"])

    def test_build_report_includes_summary_and_taxonomy(self) -> None:
        gold = load_gold(GOLD_PATH)
        report = build_report(FIXTURE_DIR, GOLD_PATH, gold, "unit", "2")

        self.assertEqual("parser", report["mode"])
        self.assertEqual(1, report["summary"]["num_documents"])
        self.assertEqual(0, report["summary"]["num_documents_with_errors"])
        self.assertEqual(1.0, report["summary"]["metrics"]["field_f1"])
        self.assertIn("ocr_missing_text", report["failure_taxonomy"])
        self.assertIn("bbox_misaligned", report["failure_taxonomy"])

    def test_cli_writes_parser_eval_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT_DIR / "eval" / "run_parser_eval.py"),
                    "--artifact_dir",
                    str(FIXTURE_DIR),
                    "--gold",
                    str(GOLD_PATH),
                    "--output_dir",
                    tmp_dir,
                    "--run_name",
                    "fixture",
                    "--parser_version",
                    "2",
                ],
                cwd=ROOT_DIR,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            out_path = Path(tmp_dir) / "parser_eval_summary.json"
            self.assertTrue(out_path.exists())
            report = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual("fixture", report["run"]["name"])
            self.assertEqual({}, report["summary"]["failure_counts"])


if __name__ == "__main__":
    unittest.main()
