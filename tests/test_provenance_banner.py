"""Effective-config provenance banner regression suite (issue #1212).

Pins the observation surface shared by ``scripts/build_index.py`` and
``eval/run_eval.py``:

* hashing embedding → ``[WARN]`` row (the 의미-맹목 artifact class).
* CSV-fallback ingestion text_source → ``[WARN]`` row (the #1129 artifact).
* PyMuPDF4LLM text_source → no WARN; HWP kordoc/csv text_source → WARN.
* opt-out honored via ``--no-config-banner`` flag AND
  ``BIDMATE_NO_CONFIG_BANNER`` env.
* banner writes to the chosen stream (default stderr) and never raises on
  missing ingestion_report.json.

READ-ONLY module — these tests assert formatting/classification only; no
retrieval/answer surface is exercised.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path

import rag_provenance as p


class _Args:
    """Minimal argparse.Namespace stand-in for build_index_rows."""

    def __init__(self, **kw):
        self.embedding_backend = kw.get("embedding_backend", "sentence-transformers")
        self.model = kw.get("model", "BAAI/bge-m3")
        self.metadata_csv = kw.get("metadata_csv", "data/data_list.csv")
        self.files_dir = kw.get("files_dir", "data/files")
        self.hwp_loader = kw.get("hwp_loader", None)
        self.pdf_loader = kw.get("pdf_loader", None)
        self.hwp_pdf_artifact_dir = kw.get("hwp_pdf_artifact_dir", "data/index/hwp_pdf_artifacts")
        self.ingestion_mode = kw.get("ingestion_mode", "csv-text")
        self.chunking_strategy = kw.get("chunking_strategy", "fixed")
        self.no_config_banner = kw.get("no_config_banner", False)


class BannerOptOutTest(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop(p.OPT_OUT_ENV, None)

    def tearDown(self):
        os.environ.pop(p.OPT_OUT_ENV, None)
        if self._saved is not None:
            os.environ[p.OPT_OUT_ENV] = self._saved

    def test_disabled_via_cli_flag(self):
        self.assertTrue(p.banner_disabled(cli_flag=True))

    def test_disabled_via_env(self):
        os.environ[p.OPT_OUT_ENV] = "1"
        self.assertTrue(p.banner_disabled())

    def test_enabled_by_default(self):
        self.assertFalse(p.banner_disabled())

    def test_emit_build_suppressed_by_flag(self):
        stream = io.StringIO()
        p.emit_build_banner(_Args(no_config_banner=True), stream=stream)
        self.assertEqual(stream.getvalue(), "")

    def test_emit_eval_suppressed_by_env(self):
        os.environ[p.OPT_OUT_ENV] = "true"
        stream = io.StringIO()
        p.emit_eval_banner({"embedding": {"backend": "hashing"}}, {}, None, stream=stream)
        self.assertEqual(stream.getvalue(), "")


class EmbeddingClassificationTest(unittest.TestCase):
    def test_hashing_backend_warns(self):
        rows = p.build_index_rows(_Args(embedding_backend="hashing", model="local-hashing-bow"))
        emb = [r for r in rows if r[0] == "embedding"][0]
        self.assertEqual(emb[2], p.WARN)
        self.assertIn("feature-hashing", emb[3] or "")

    def test_sentence_transformers_ok(self):
        rows = p.build_index_rows(_Args(embedding_backend="sentence-transformers"))
        emb = [r for r in rows if r[0] == "embedding"][0]
        self.assertEqual(emb[2], p.OK)

    def test_openai_backend_info(self):
        rows = p.build_index_rows(_Args(embedding_backend="openai", model="text-embedding-3-small"))
        emb = [r for r in rows if r[0] == "embedding"][0]
        self.assertEqual(emb[2], p.INFO)


class IngestionLoaderTest(unittest.TestCase):
    def test_csv_text_hwp_loader_warns(self):
        rows = p.build_index_rows(_Args(hwp_loader="csv_text"))
        hwp = [r for r in rows if r[0] == "hwp_loader"][0]
        self.assertEqual(hwp[2], p.WARN)

    def test_default_hwp_loader_ok(self):
        rows = p.build_index_rows(_Args())
        hwp = [r for r in rows if r[0] == "hwp_loader"][0]
        self.assertEqual(hwp[2], p.OK)
        self.assertEqual(hwp[1], "pdf_pymupdf4llm")

    def test_kordoc_hwp_loader_warns(self):
        rows = p.build_index_rows(_Args(hwp_loader="kordoc"))
        hwp = [r for r in rows if r[0] == "hwp_loader"][0]
        self.assertEqual(hwp[2], p.WARN)

    def test_no_metadata_csv_skips_loader_rows(self):
        rows = p.build_index_rows(_Args(metadata_csv=None))
        labels = {r[0] for r in rows}
        self.assertNotIn("hwp_loader", labels)
        self.assertIn("embedding", labels)


class EvalTextSourceTest(unittest.TestCase):
    def _write_report(self, tmp: Path, counts: dict) -> None:
        (tmp / "ingestion_report.json").write_text(
            json.dumps({"summary": {"text_source_counts": counts}}, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_pymupdf_text_source_no_warn(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self._write_report(tmp, {"hwp": {"pdf_pymupdf4llm": 96}, "pdf": {"pdf_pymupdf4llm": 4}})
            rows = p.eval_rows({"embedding": {"backend": "hashing"}}, {}, tmp)
            ts = [r for r in rows if r[0] == "index.text_source"][0]
            self.assertEqual(ts[2], p.OK)
            self.assertIn("pdf_pymupdf4llm", ts[1])

    def test_hwp_kordoc_text_source_warns(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self._write_report(tmp, {"hwp": {"kordoc": 96}, "pdf": {"pdf_pymupdf4llm": 4}})
            rows = p.eval_rows({"embedding": {"backend": "hashing"}}, {}, tmp)
            ts = [r for r in rows if r[0] == "index.text_source"][0]
            self.assertEqual(ts[2], p.WARN)

    def test_csv_fallback_text_source_warns(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self._write_report(tmp, {"hwp": {"data_list_csv_text": 100}})
            rows = p.eval_rows({"embedding": {"backend": "sentence-transformers"}}, {}, tmp)
            ts = [r for r in rows if r[0] == "index.text_source"][0]
            self.assertEqual(ts[2], p.WARN)

    def test_missing_report_omits_text_source_row(self):
        with tempfile.TemporaryDirectory() as d:
            rows = p.eval_rows({"embedding": {"backend": "hashing"}}, {}, Path(d))
            labels = {r[0] for r in rows}
            self.assertNotIn("index.text_source", labels)
            # core rows still present
            self.assertIn("index.embedding", labels)
            self.assertIn("retrieval", labels)


class EvalRetrievalBackendTest(unittest.TestCase):
    def test_distinct_ablation_backends_listed(self):
        config = {
            "ablation_runs": [
                {"name": "full", "retrieval_backend": "hybrid"},
                {"name": "nb", "retrieval_backend": "dense"},
                {"name": "dup", "retrieval_backend": "hybrid"},
            ]
        }
        rows = p.eval_rows({"embedding": {"backend": "hashing"}}, config, None)
        retr = [r for r in rows if r[0] == "retrieval"][0]
        self.assertEqual(retr[1], "dense, hybrid")

    def test_flat_config_defaults_to_dense(self):
        rows = p.eval_rows({"embedding": {"backend": "hashing"}}, {}, None)
        retr = [r for r in rows if r[0] == "retrieval"][0]
        self.assertEqual(retr[1], "dense")


class RenderFormatTest(unittest.TestCase):
    def test_warn_row_renders_warn_marker(self):
        stream = io.StringIO()
        p.render("test", [("embedding", "hashing", p.WARN, "보류")], stream=stream)
        out = stream.getvalue()
        self.assertIn("[CONFIG]", out)
        self.assertIn("[WARN: 보류]", out)

    def test_info_note_renders_in_brackets(self):
        stream = io.StringIO()
        p.render("test", [("synthesis", "stub", p.INFO, "LLM 0")], stream=stream)
        self.assertIn("[LLM 0]", stream.getvalue())

    def test_ok_row_has_no_marker(self):
        stream = io.StringIO()
        p.render("test", [("vector_store", "memory", p.OK, None)], stream=stream)
        out = stream.getvalue()
        self.assertNotIn("[WARN", out)
        self.assertIn("memory", out)


if __name__ == "__main__":
    unittest.main()
