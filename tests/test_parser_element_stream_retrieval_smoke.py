from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util
import subprocess
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "run_parser_element_stream_retrieval_smoke.py"


def load_runner_module():
    spec = importlib.util.spec_from_file_location("parser_element_retrieval_smoke", RUNNER_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def element(element_type: str, source_role: str, text: str, page: int | None = 1) -> dict:
    return {
        "element_id": f"doc:unit:{element_type}:{source_role}:{abs(hash(text)) % 9999}",
        "element_type": element_type,
        "source_role": source_role,
        "page_span": [page, page] if page else None,
        "bbox": None,
        "text": text,
        "structured_payload": None,
        "confidence": None,
        "citation_ready": True,
        "merge_priority": 10,
        "route_labels": [],
        "provenance": {"candidate": source_role},
    }


class ParserElementStreamRetrievalSmokeTest(unittest.TestCase):
    def test_cli_builds_index_and_textless_smoke_report(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            stream = tmp / "element_stream.json"
            queries = tmp / "queries.json"
            out_dir = tmp / "out"
            report_dir = tmp / "report"
            write_json(
                stream,
                {
                    "schema_version": 1,
                    "mode": "parser_element_stream_run",
                    "run": {"run_id": "unit-stream"},
                    "documents": [
                        {
                            "doc_id": "doc-1",
                            "csv_row": 1,
                            "source_file": "unit.hwp",
                            "path_pdf": "unit.pdf",
                            "source_sha256": "sha1",
                            "metadata": {"csv": {"사업명": "alpha metadata project"}},
                            "elements": [
                                element("metadata_fact", "metadata", "alpha metadata project", None),
                                element("table", "sidecar", "invoice table total budget zebra"),
                                element("ocr_text", "routed_ocr", "cover OCR signature kangaroo"),
                            ],
                        },
                        {
                            "doc_id": "doc-2",
                            "csv_row": 2,
                            "source_file": "alias.hwp",
                            "path_pdf": "alias.pdf",
                            "source_sha256": "sha1",
                            "metadata": {"csv": {"사업명": "alias metadata project"}},
                            "elements": [
                                element("table", "sidecar", "alias unique platypus table"),
                            ],
                        },
                    ],
                },
            )
            write_json(
                queries,
                [
                    {
                        "name": "metadata",
                        "source": "metadata_fact",
                        "query": "alpha metadata project",
                        "expected_rows": [1],
                        "expected_element_types": ["metadata_fact"],
                    },
                    {
                        "name": "table",
                        "source": "table",
                        "query": "invoice table budget zebra",
                        "expected_rows": [1],
                        "expected_element_types": ["table"],
                    },
                    {
                        "name": "ocr",
                        "source": "ocr_text",
                        "query": "OCR signature kangaroo",
                        "expected_rows": [1],
                        "expected_element_types": ["ocr_text"],
                    },
                    {
                        "name": "alias",
                        "source": "table",
                        "query": "alias unique platypus",
                        "expected_rows": [1],
                        "allow_source_sha256_alias": True,
                        "expected_element_types": ["table"],
                    },
                ],
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER_PATH),
                    "--element-stream",
                    str(stream),
                    "--queries-json",
                    str(queries),
                    "--run-id",
                    "unit-smoke",
                    "--out-dir",
                    str(out_dir),
                    "--report-dir",
                    str(report_dir),
                    "--top-k",
                    "3",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            report_text = (report_dir / "retrieval_smoke.aggregate.json").read_text(encoding="utf-8")
            self.assertNotIn("alpha metadata project", report_text)
            self.assertNotIn("invoice table total budget zebra", report_text)
            self.assertNotIn("cover OCR signature kangaroo", report_text)
            report = json.loads(report_text)
            self.assertIn("query_set_hash", report["run"])
            self.assertEqual(4, report["summary"]["queries"])
            self.assertEqual(4, report["summary"]["passed"])
            self.assertEqual(4, report["summary"]["top1_hits"])
            self.assertEqual(4, report["summary"]["top1_row_hits"])
            self.assertEqual(1.0, report["summary"]["mrr"])
            self.assertEqual(4, report["summary"]["chunks"])
            self.assertEqual(1, report["summary"]["element_type_counts"]["metadata_fact"])
            self.assertEqual(2, report["summary"]["element_type_counts"]["table"])
            self.assertEqual(1, report["summary"]["element_type_counts"]["ocr_text"])
            self.assertEqual(1, report["summary"]["by_expected_element_type"]["metadata_fact"]["passed"])
            self.assertEqual(2, report["summary"]["by_expected_element_type"]["table"]["passed"])
            self.assertEqual(1, report["summary"]["by_expected_element_type"]["ocr_text"]["passed"])
            alias_result = next(result for result in report["queries"] if result["name"] == "alias")
            self.assertEqual([1], alias_result["declared_expected_rows"])
            self.assertEqual([1, 2], alias_result["expected_rows"])
            self.assertEqual([2], alias_result["alias_rows"])
            index_text = (out_dir / "index" / "index.json").read_text(encoding="utf-8")
            self.assertIn("alpha metadata project", index_text)

    def test_row_and_element_type_must_match_same_hit(self) -> None:
        runner = load_runner_module()
        hits = [
            {"csv_row": 1, "element_type": "text_layer"},
            {"csv_row": 2, "element_type": "table"},
        ]

        self.assertIsNone(runner.first_matching_hit_rank(hits, {1}, {"table"}))
        self.assertFalse(runner.expected_hit_matches(hits[0], {1}, {"table"}))
        self.assertEqual(2, runner.first_matching_hit_rank(hits, {2}, {"table"}))
        self.assertTrue(runner.expected_hit_matches(hits[1], {2}, {"table"}))

    def test_query_config_validation_rejects_ambiguous_reviewer_surface(self) -> None:
        runner = load_runner_module()
        with self.assertRaisesRegex(ValueError, "duplicate query name"):
            runner.validate_smoke_queries(
                [
                    {
                        "name": "same",
                        "query": "alpha",
                        "expected_rows": [1],
                        "expected_element_types": ["text_layer"],
                    },
                    {
                        "name": "same",
                        "query": "beta",
                        "expected_rows": [1],
                        "expected_element_types": ["text_layer"],
                    },
                ]
            )
        with self.assertRaisesRegex(ValueError, "must declare expected_rows"):
            runner.validate_smoke_queries(
                [
                    {
                        "name": "missing_rows",
                        "query": "alpha",
                        "expected_element_types": ["text_layer"],
                    }
                ]
            )
        with self.assertRaisesRegex(ValueError, "allow_source_sha256_alias must be boolean"):
            runner.validate_smoke_queries(
                [
                    {
                        "name": "bad_alias_flag",
                        "query": "alpha",
                        "expected_rows": [1],
                        "expected_element_types": ["text_layer"],
                        "allow_source_sha256_alias": "true",
                    }
                ]
            )


if __name__ == "__main__":
    unittest.main()
