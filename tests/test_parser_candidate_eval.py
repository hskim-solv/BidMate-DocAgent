from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "run_parser_candidate_eval.py"
SUMMARIZER_PATH = REPO_ROOT / "scripts" / "summarize_parser_candidate_eval.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("parser_candidate_eval_runner_test", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_tiny_pdf(path: Path, text: str = "사업명 테스트\n발주 기관 테스트\n예산 100원") -> None:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


class ParserCandidateEvalTest(unittest.TestCase):
    def test_pymupdf4llm_eval_ocr_defaults_off_for_control(self) -> None:
        runner = load_runner()
        with mock.patch.dict(os.environ, {}, clear=True):
            use_ocr, ocr_language = runner.resolve_pymupdf4llm_ocr_options()

        self.assertFalse(use_ocr)
        self.assertEqual("kor+eng", ocr_language)

    def test_pymupdf4llm_eval_ocr_can_be_opted_in_by_env_or_cli(self) -> None:
        runner = load_runner()
        with mock.patch.dict(
            os.environ,
            {
                runner.PYMUPDF4LLM_USE_OCR_ENV: "1",
                runner.PYMUPDF4LLM_OCR_LANGUAGE_ENV: "kor",
            },
            clear=True,
        ):
            use_ocr, ocr_language = runner.resolve_pymupdf4llm_ocr_options()

        self.assertTrue(use_ocr)
        self.assertEqual("kor", ocr_language)

        cli_use_ocr, cli_ocr_language = runner.resolve_pymupdf4llm_ocr_options(
            use_ocr=False,
            ocr_language="eng",
        )
        self.assertFalse(cli_use_ocr)
        self.assertEqual("eng", cli_ocr_language)

    def test_doc_id_keeps_duplicate_rows_distinct(self) -> None:
        runner = load_runner()
        row_a = {"csv_row": "17", "path_pdf": "same.pdf", "source_file": "same.hwp"}
        row_b = {"csv_row": "55", "path_pdf": "same.pdf", "source_file": "same.hwp"}

        self.assertNotEqual(runner.make_doc_id(row_a), runner.make_doc_id(row_b))
        self.assertIn("real100_v2:path:17:", runner.make_doc_id(row_a))
        self.assertIn("real100_v2:path:55:", runner.make_doc_id(row_b))

    def test_metrics_cover_page_spans_metadata_and_tables(self) -> None:
        runner = load_runner()
        artifact = {
            "status": "ok",
            "expected_page_count": 2,
            "metadata": {key: "값" for key in runner.REQUIRED_METADATA_KEYS},
            "provenance": {"runtime_s": 1.0},
            "pages": [
                {
                    "page": 1,
                    "markdown": "사업명 테스트",
                    "chars": 6,
                    "tables": [
                        {
                            "total_cells": 4,
                            "nonempty_cells": 3,
                        }
                    ],
                },
                {"page": 2, "markdown": "", "chars": 0, "tables": []},
            ],
            "elements": [
                {"type": "paragraph", "page_span": [1, 1], "text": "사업명 테스트"},
                {"type": "paragraph", "page_span": [3, 3], "text": "bad"},
            ],
        }

        metrics = runner.compute_artifact_metrics(artifact)

        self.assertEqual(2, metrics["pages_seen"])
        self.assertEqual(1.0, metrics["pages_seen_rate"])
        self.assertEqual(0.5, metrics["page_span_coverage"])
        self.assertEqual(1.0, metrics["metadata_required_present_rate"])
        self.assertEqual(1, metrics["total_tables"])
        self.assertEqual(0.75, metrics["table_nonempty_cell_rate"])

    def test_summary_reports_duplicate_alias_ok(self) -> None:
        runner = load_runner()
        with TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            for csv_row, agency in ((17, "기관 A"), (55, "기관 B")):
                artifact = {
                    "schema_version": 1,
                    "candidate": "unit_candidate",
                    "status": "ok",
                    "csv_row": csv_row,
                    "subset_rank": csv_row,
                    "subset_reason": "duplicate-byte-distinct-metadata",
                    "doc_id": f"real100_v2:path:{csv_row}:same",
                    "source_sha256": "same-sha",
                    "source_file": "same.hwp",
                    "path_pdf": f"{csv_row}.pdf",
                    "expected_page_count": 1,
                    "metadata": {"발주 기관": agency, **{key: "값" for key in runner.REQUIRED_METADATA_KEYS}},
                    "pages": [{"page": 1, "markdown": "본문", "chars": 2, "tables": []}],
                    "elements": [{"type": "paragraph", "page_span": [1, 1], "text": "본문"}],
                    "provenance": {"runtime_s": 0.1},
                    "failure": None,
                }
                path = run_dir / "candidates" / "unit_candidate" / f"row-{csv_row:04d}.json"
                runner.write_json(path, artifact)
            runner.write_json(run_dir / runner.RUN_MANIFEST, {"run_id": "unit"})

            summary = runner.build_run_summary(run_dir)
            candidate_summary = summary["summary"]["candidate_summaries"]["unit_candidate"]

            self.assertTrue(candidate_summary["duplicate_alias_ok"])
            self.assertEqual([[17, 55]], [check["csv_rows"] for check in candidate_summary["duplicate_alias_checks"]])

    def test_cli_runs_pdfplumber_candidate_and_summarizes(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            pdf_path = tmp / "doc.pdf"
            write_tiny_pdf(pdf_path)
            manifest_path = tmp / "manifest.json"
            subset_path = tmp / "subset.json"
            manifest = [
                {
                    "csv_row": "1",
                    "source_file": "기관_사업.hwp",
                    "source_sha256": "sha-1",
                    "path_pdf": str(pdf_path),
                    "page_count": 1,
                    "metadata": {
                        "공고 번호": "1",
                        "공고 차수": "1",
                        "사업명": "테스트 사업",
                        "사업 금액": "100원",
                        "발주 기관": "테스트 기관",
                        "공개 일자": "2026-01-01",
                        "입찰 참여 시작일": "2026-01-02",
                        "입찰 참여 마감일": "2026-01-03",
                        "파일명": "기관_사업.hwp",
                    },
                }
            ]
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            subset_path.write_text(json.dumps([{"csv_row": 1, "reason": "unit"}]), encoding="utf-8")
            run_dir = tmp / "run"
            report_dir = tmp / "report"

            run = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER_PATH),
                    "--manifest",
                    str(manifest_path),
                    "--subset",
                    str(subset_path),
                    "--candidates",
                    "pdfplumber_table_sidecar",
                    "--run-id",
                    "unit",
                    "--run-dir",
                    str(run_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, run.returncode, run.stderr)
            self.assertTrue((run_dir / "candidates" / "pdfplumber_table_sidecar" / "row-0001.json").exists())

            summarize = subprocess.run(
                [
                    sys.executable,
                    str(SUMMARIZER_PATH),
                    "--run-id",
                    "unit",
                    "--run-dir",
                    str(run_dir),
                    "--report-dir",
                    str(report_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, summarize.returncode, summarize.stderr)
            summary_path = report_dir / "parser_candidate_eval_summary.json"
            self.assertTrue(summary_path.exists())
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            candidate = summary["summary"]["candidate_summaries"]["pdfplumber_table_sidecar"]
            self.assertEqual(1, candidate["documents"])
            self.assertEqual(1.0, candidate["metadata_required_present_rate"])

    def test_unknown_candidate_exits_nonzero(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(RUNNER_PATH),
                "--manifest",
                "missing.json",
                "--subset",
                "missing-subset.json",
                "--candidates",
                "unknown_candidate",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(2, completed.returncode)
        self.assertIn("Unsupported candidate", completed.stderr)


if __name__ == "__main__":
    unittest.main()
