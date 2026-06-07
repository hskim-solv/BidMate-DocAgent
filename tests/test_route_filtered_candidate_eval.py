from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "run_route_filtered_candidate_eval.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("route_filtered_candidate_eval_runner_test", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def page_audit_fixture() -> dict:
    return {
        "run": {"run_id": "page-audit-unit"},
        "documents": [
            {
                "schema_version": 1,
                "csv_row": 17,
                "subset_rank": 1,
                "subset_reason": "unit",
                "doc_id": "real100_v2:path:17:doc",
                "source_sha256": "sha-17",
                "source_file": "doc.hwp",
                "path_pdf": "missing.pdf",
                "expected_page_count": 3,
                "pages": [
                    {
                        "page": 1,
                        "text_chars": 100,
                        "image_count": 0,
                        "image_area_ratio": 0.0,
                        "table_count": 0,
                        "labels": ["text_layer"],
                        "primary_route": "text_layer",
                        "reasons": ["text_chars_above_threshold"],
                        "warnings": [],
                    },
                    {
                        "page": 2,
                        "text_chars": 10,
                        "image_count": 1,
                        "image_area_ratio": 0.1,
                        "table_count": 0,
                        "labels": ["ocr_needed"],
                        "primary_route": "ocr_needed",
                        "reasons": ["low_text_with_image_signal"],
                        "warnings": [],
                    },
                    {
                        "page": 3,
                        "text_chars": 20,
                        "image_count": 5,
                        "image_area_ratio": 0.0,
                        "table_count": 0,
                        "labels": ["ocr_needed", "vlm_needed"],
                        "primary_route": "vlm_needed",
                        "reasons": ["image_rich_low_or_moderate_text"],
                        "warnings": [],
                    },
                ],
            }
        ],
    }


class RouteFilteredCandidateEvalTest(unittest.TestCase):
    def test_selects_pages_by_label_or_primary_route(self) -> None:
        runner = load_runner()
        documents = page_audit_fixture()["documents"]

        selected_by_label = runner.selected_documents(
            documents,
            labels=["ocr_needed"],
            primary_routes=[],
        )
        self.assertEqual([2, 3], [page["page"] for page in selected_by_label[0]["selected_pages"]])

        selected_by_primary_route = runner.selected_documents(
            documents,
            labels=[],
            primary_routes=["vlm_needed"],
        )
        self.assertEqual([3], [page["page"] for page in selected_by_primary_route[0]["selected_pages"]])

    def test_cli_dry_run_writes_private_artifact_and_textless_aggregate(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            page_audit = tmp / "page_audit.json"
            run_dir = tmp / "run"
            report_dir = tmp / "report"
            page_audit.write_text(json.dumps(page_audit_fixture(), ensure_ascii=False), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER_PATH),
                    "--page-audit",
                    str(page_audit),
                    "--candidates",
                    "paddleocr_classic,tesseract_baseline",
                    "--labels",
                    "ocr_needed",
                    "--run-id",
                    "unit",
                    "--run-dir",
                    str(run_dir),
                    "--report-dir",
                    str(report_dir),
                    "--dry-run",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            artifact_path = run_dir / "candidates" / "paddleocr_classic" / "row-0017.json"
            self.assertTrue(artifact_path.exists())
            aggregate_path = report_dir / "route_candidate_eval.aggregate.json"
            self.assertTrue(aggregate_path.exists())
            aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
            summary = aggregate["summary"]["candidate_summaries"]["paddleocr_classic"]
            self.assertEqual(2, summary["selected_pages"])
            self.assertEqual({"skipped": 2}, summary["page_status_counts"])
            tesseract_summary = aggregate["summary"]["candidate_summaries"]["tesseract_baseline"]
            self.assertEqual(2, tesseract_summary["selected_pages"])
            self.assertEqual({"skipped": 2}, tesseract_summary["page_status_counts"])
            aggregate_text = aggregate_path.read_text(encoding="utf-8")
            self.assertNotIn("recognized OCR text", aggregate_text)

    def test_page_retry_records_failed_attempt_before_success(self) -> None:
        runner = load_runner()
        doc = page_audit_fixture()["documents"][0]
        doc["selected_pages"] = [doc["pages"][1]]
        attempts = []
        original_run_candidate_page = runner.run_candidate_page
        original_candidate_versions = runner.candidate_versions
        try:
            runner.candidate_versions = lambda _candidate: {"pytesseract": "0.3.13", "tesseract": "tesseract 5.5.2"}

            def fake_run_candidate_page(*_args, **_kwargs):
                attempts.append("called")
                if len(attempts) == 1:
                    raise TimeoutError("timeout after 1s")
                return {
                    "blocks": [{"text": "재시도 성공", "bbox": [0, 0, 1, 1], "confidence": 0.9}],
                    "text_chars": 6,
                    "block_count": 1,
                    "avg_confidence": 0.9,
                }

            runner.run_candidate_page = fake_run_candidate_page
            args = SimpleNamespace(
                labels=["ocr_needed"],
                primary_routes=[],
                page_audit="unit-page-audit.json",
                render_dpi=72,
                page_timeout_s=1.0,
                page_retries=1,
                tesseract_lang="kor+eng",
                dry_run=False,
            )

            artifact = runner.run_ocr_document("tesseract_baseline", doc, args)
        finally:
            runner.run_candidate_page = original_run_candidate_page
            runner.candidate_versions = original_candidate_versions

        self.assertEqual("ok", artifact["status"])
        self.assertEqual(["failed", "ok"], [attempt["status"] for attempt in artifact["pages"][0]["attempts"]])
        self.assertEqual(2, len(attempts))

    def test_vlm_skeleton_candidate_records_explicit_skip_reason(self) -> None:
        runner = load_runner()
        doc = page_audit_fixture()["documents"][0]
        doc["selected_pages"] = [doc["pages"][2]]
        args = SimpleNamespace(
            labels=[],
            primary_routes=["vlm_needed"],
            page_audit="unit-page-audit.json",
            render_dpi=72,
            page_timeout_s=1.0,
            page_retries=0,
            tesseract_lang="kor+eng",
            dry_run=False,
        )

        artifact = runner.run_candidate("paddleocr_vl_local", doc, args)

        self.assertEqual("skipped", artifact["status"])
        self.assertEqual("candidate_not_enabled", artifact["failure"]["code"])
        self.assertEqual("candidate_not_enabled", artifact["pages"][0]["failure"]["code"])
        self.assertEqual("paddleocr_vl_local", artifact["candidate"])

    def test_enabled_local_vlm_requires_cache_without_download_opt_in(self) -> None:
        runner = load_runner()
        doc = page_audit_fixture()["documents"][0]
        doc["selected_pages"] = [doc["pages"][2]]
        args = SimpleNamespace(
            labels=[],
            primary_routes=["vlm_needed"],
            page_audit="unit-page-audit.json",
            render_dpi=72,
            page_timeout_s=1.0,
            page_retries=0,
            tesseract_lang="kor+eng",
            dry_run=False,
            enable_local_vlm=True,
            allow_model_download=False,
            local_vlm_device="cpu",
            paddleocr_vl_pipeline_version="v1.6",
        )
        original_candidate_versions = runner.candidate_versions
        try:
            runner.candidate_versions = lambda _candidate: {
                "paddleocr": "3.6.0",
                "class": "PaddleOCRVL",
                "class_available": True,
                "models": [],
            }

            artifact = runner.run_candidate("paddleocr_vl_local", doc, args)
        finally:
            runner.candidate_versions = original_candidate_versions

        self.assertEqual("skipped", artifact["status"])
        self.assertEqual("model_cache_missing", artifact["failure"]["code"])
        self.assertEqual("model_cache_missing", artifact["pages"][0]["failure"]["code"])
        self.assertFalse(artifact["provenance"]["allow_model_download"])

    def test_enabled_hosted_api_requires_token_without_calling_api(self) -> None:
        runner = load_runner()
        doc = page_audit_fixture()["documents"][0]
        doc["selected_pages"] = [doc["pages"][2]]
        args = SimpleNamespace(
            labels=[],
            primary_routes=["vlm_needed"],
            page_audit="unit-page-audit.json",
            render_dpi=72,
            page_timeout_s=1.0,
            page_retries=0,
            tesseract_lang="kor+eng",
            dry_run=False,
            enable_hosted_api=True,
            paddleocr_api_model="PaddleOCR-VL-1.6",
            paddleocr_api_request_timeout_s=300.0,
            paddleocr_api_poll_timeout_s=600.0,
            paddleocr_api_base_url=None,
        )
        original_candidate_versions = runner.candidate_versions
        try:
            runner.candidate_versions = lambda _candidate: {
                "paddleocr": "3.6.0",
                "class": "PaddleOCRClient",
                "class_available": True,
                "access_token_present": False,
            }
            with mock.patch.dict("os.environ", {"PADDLEOCR_ACCESS_TOKEN": ""}, clear=False):
                artifact = runner.run_candidate("paddleocr_official_api", doc, args)
        finally:
            runner.candidate_versions = original_candidate_versions

        self.assertEqual("skipped", artifact["status"])
        self.assertEqual("credential_unavailable", artifact["failure"]["code"])
        self.assertEqual("credential_unavailable", artifact["pages"][0]["failure"]["code"])
        self.assertFalse(artifact["provenance"]["paddleocr_access_token_present"])

    def test_unknown_candidate_exits_nonzero(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            page_audit = Path(tmp_dir) / "page_audit.json"
            page_audit.write_text(json.dumps(page_audit_fixture(), ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER_PATH),
                    "--page-audit",
                    str(page_audit),
                    "--candidates",
                    "bogus",
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
