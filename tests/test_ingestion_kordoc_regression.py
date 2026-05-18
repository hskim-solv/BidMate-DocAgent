"""Kordoc loader regression suite (ADR 0049, issues #890 + #895).

Pins the load-bearing surfaces from ADR 0049's Verification section:

* ``HwpKordocLoader`` / ``PdfKordocLoader`` invocation shape (npx + flags).
* Node-missing → ``data_list_csv_text`` fallback (CI without Node).
* Subprocess failure → ``data_list_csv_text`` fallback (offline / kordoc error).
* Telemetry-key stability (``last_text_source`` / ``last_fallback_reason``).
* Batch priming reads cache; per-row ``load_text`` consumes it.
* NFC normalization for Korean filenames (macOS HFS+ NFD round-trip).
* ``_resolve_loader`` honors ``BIDMATE_HWP_LOADER`` / ``BIDMATE_PDF_LOADER``
  ``=csv_text`` opt-out.

The subprocess is mocked end-to-end so the suite runs on CI without Node
installed — the Node-missing case explicitly checks the graceful path.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import unicodedata
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from ingestion import (
    HwpCsvTextLoader,
    HwpKordocLoader,
    PdfCsvTextLoader,
    PdfKordocLoader,
    _kordoc_output_stem,
    _read_kordoc_version_spec,
    _reset_kordoc_loaders,
    _resolve_loader,
)


class HwpKordocLoaderRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._env_backup = {
            "BIDMATE_HWP_LOADER": os.environ.get("BIDMATE_HWP_LOADER"),
            "BIDMATE_PDF_LOADER": os.environ.get("BIDMATE_PDF_LOADER"),
        }
        os.environ.pop("BIDMATE_HWP_LOADER", None)
        os.environ.pop("BIDMATE_PDF_LOADER", None)
        _reset_kordoc_loaders()

    def tearDown(self) -> None:
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _reset_kordoc_loaders()

    def test_default_loader_is_kordoc(self) -> None:
        loader = _resolve_loader("hwp")
        self.assertIsInstance(loader, HwpKordocLoader)

    def test_default_pdf_loader_is_kordoc(self) -> None:
        loader = _resolve_loader("pdf")
        self.assertIsInstance(loader, PdfKordocLoader)

    def test_csv_text_opt_out(self) -> None:
        os.environ["BIDMATE_HWP_LOADER"] = "csv_text"
        loader = _resolve_loader("hwp")
        self.assertIsInstance(loader, HwpCsvTextLoader)
        self.assertNotIsInstance(loader, HwpKordocLoader)

    def test_pdf_csv_text_opt_out(self) -> None:
        os.environ["BIDMATE_PDF_LOADER"] = "csv_text"
        loader = _resolve_loader("pdf")
        self.assertIsInstance(loader, PdfCsvTextLoader)
        self.assertNotIsInstance(loader, PdfKordocLoader)

    def test_pdf_loader_independent_of_hwp_opt_out(self) -> None:
        os.environ["BIDMATE_HWP_LOADER"] = "csv_text"
        self.assertIsInstance(_resolve_loader("hwp"), HwpCsvTextLoader)
        self.assertIsInstance(_resolve_loader("pdf"), PdfKordocLoader)

    def test_legacy_native_aliased_to_csv_with_deprecation(self) -> None:
        for legacy in ("native", "native_tables"):
            with self.subTest(legacy=legacy):
                os.environ["BIDMATE_HWP_LOADER"] = legacy
                with self.assertWarns(DeprecationWarning):
                    loader = _resolve_loader("hwp")
                self.assertIsInstance(loader, HwpCsvTextLoader)

    def test_load_text_falls_back_when_cache_empty(self) -> None:
        loader = HwpKordocLoader()
        row = {"텍스트": "csv body text"}
        result = loader.load_text(row, Path("/no/such/file.hwp"))
        self.assertEqual(result, "csv body text")
        self.assertEqual(loader.last_text_source, "data_list_csv_text")

    def test_load_text_empty_text_raises(self) -> None:
        loader = HwpKordocLoader()
        with self.assertRaises(ValueError) as ctx:
            loader.load_text({"텍스트": ""}, Path("/no/such/file.hwp"))
        self.assertEqual(str(ctx.exception), "empty_text")

    def test_load_text_reads_primed_cache_with_nfc_stem(self) -> None:
        loader = HwpKordocLoader()
        nfd_stem = unicodedata.normalize("NFD", "한국어공고")
        source_path = Path(f"/files/{nfd_stem}.hwp")
        loader._batch_cache[str(source_path)] = "kordoc markdown body"
        result = loader.load_text({"텍스트": "csv fallback"}, source_path)
        self.assertEqual(result, "kordoc markdown body")
        self.assertEqual(loader.last_text_source, "kordoc")

    def test_kordoc_version_spec_reads_pinned_version(self) -> None:
        spec = _read_kordoc_version_spec()
        self.assertTrue(
            spec == "kordoc" or spec.startswith("kordoc@"),
            f"unexpected spec: {spec!r}",
        )

    def test_kordoc_output_stem_normalizes_to_nfc(self) -> None:
        nfd_stem = unicodedata.normalize("NFD", "한국어공고")
        self.assertNotEqual(nfd_stem, "한국어공고")
        normalized = _kordoc_output_stem(Path(f"/files/{nfd_stem}.hwp"))
        self.assertEqual(normalized, "한국어공고")

    def test_prime_batch_node_missing_falls_back_gracefully(self) -> None:
        loader = HwpKordocLoader()
        with mock.patch.object(shutil, "which", return_value=None):
            with self.assertWarns(RuntimeWarning):
                loader.prime_batch([Path("/files/a.hwp")])
        self.assertEqual(loader._batch_cache, {})
        self.assertIn("node/npx", loader.last_fallback_reason or "")
        result = loader.load_text(
            {"텍스트": "csv body"}, Path("/files/a.hwp")
        )
        self.assertEqual(result, "csv body")
        self.assertEqual(loader.last_text_source, "data_list_csv_text")

    def test_prime_batch_subprocess_error_falls_back(self) -> None:
        loader = HwpKordocLoader()
        fake_error = subprocess.CalledProcessError(
            returncode=1,
            cmd=["npx"],
            output="",
            stderr="kordoc: parse error",
        )
        with mock.patch.object(shutil, "which", return_value="/usr/bin/npx"):
            with mock.patch.object(subprocess, "run", side_effect=fake_error):
                with self.assertWarns(RuntimeWarning):
                    loader.prime_batch([Path("/files/a.hwp")])
        self.assertEqual(loader._batch_cache, {})
        self.assertIn("npx exit 1", loader.last_fallback_reason or "")

    def test_prime_batch_success_populates_cache(self) -> None:
        loader = HwpKordocLoader()
        with TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "doc.hwp"
            source.write_bytes(b"\x00" * 4)
            captured_cmd: list[list[str]] = []

            def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
                captured_cmd.append(list(cmd))
                out_dir = Path(cmd[cmd.index("-d") + 1])
                (out_dir / "doc.md").write_text(
                    "# Heading\n\nkordoc body\n", encoding="utf-8"
                )
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch.object(shutil, "which", return_value="/usr/bin/npx"):
                with mock.patch.object(subprocess, "run", side_effect=fake_run):
                    loader.prime_batch([source])

        self.assertEqual(len(captured_cmd), 1)
        cmd = captured_cmd[0]
        self.assertEqual(cmd[0], "npx")
        self.assertIn("kordoc", cmd)
        self.assertIn(_read_kordoc_version_spec(), cmd)
        self.assertIn("pdfjs-dist", cmd)
        self.assertIn("--silent", cmd)
        self.assertIn(str(source), cmd)
        self.assertIsNone(loader.last_fallback_reason)
        self.assertIn(str(source), loader._batch_cache)
        result = loader.load_text({"텍스트": "csv"}, source)
        self.assertIn("kordoc body", result)
        self.assertEqual(loader.last_text_source, "kordoc")

    def test_pdf_prime_batch_success_populates_cache(self) -> None:
        loader = PdfKordocLoader()
        with TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "doc.pdf"
            source.write_bytes(b"\x00" * 4)

            def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
                out_dir = Path(cmd[cmd.index("-d") + 1])
                (out_dir / "doc.md").write_text(
                    "# Heading\n\n<table><tr><td>kordoc pdf body</td></tr></table>\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch.object(shutil, "which", return_value="/usr/bin/npx"):
                with mock.patch.object(subprocess, "run", side_effect=fake_run):
                    loader.prime_batch([source])

        self.assertIsNone(loader.last_fallback_reason)
        self.assertIn(str(source), loader._batch_cache)
        result = loader.load_text({"텍스트": "csv pdf fallback"}, source)
        self.assertIn("kordoc pdf body", result)
        self.assertEqual(loader.last_text_source, "kordoc")


class PrimeKordocBatchesTest(unittest.TestCase):
    """``_prime_kordoc_batches`` orchestration (issue #895).

    Verifies that the metadata-ingestion entry point primes HWP + PDF
    loaders together in a single ``npx kordoc`` subprocess and routes
    the resulting Markdown into each loader's cache by file extension.
    """

    def setUp(self) -> None:
        self._env_backup = {
            "BIDMATE_HWP_LOADER": os.environ.get("BIDMATE_HWP_LOADER"),
            "BIDMATE_PDF_LOADER": os.environ.get("BIDMATE_PDF_LOADER"),
        }
        os.environ.pop("BIDMATE_HWP_LOADER", None)
        os.environ.pop("BIDMATE_PDF_LOADER", None)
        _reset_kordoc_loaders()

    def tearDown(self) -> None:
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _reset_kordoc_loaders()

    def test_single_subprocess_primes_both_loaders(self) -> None:
        from ingestion import _prime_kordoc_batches

        with TemporaryDirectory() as tmpdir:
            files_dir = Path(tmpdir)
            hwp_path = files_dir / "doc_h.hwp"
            pdf_path = files_dir / "doc_p.pdf"
            hwp_path.write_bytes(b"\x00" * 4)
            pdf_path.write_bytes(b"\x00" * 4)
            rows = [
                {"파일명": "doc_h.hwp", "파일형식": "hwp"},
                {"파일명": "doc_p.pdf", "파일형식": "pdf"},
            ]
            captured_cmds: list[list[str]] = []

            def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
                captured_cmds.append(list(cmd))
                out_dir = Path(cmd[cmd.index("-d") + 1])
                (out_dir / "doc_h.md").write_text(
                    "hwp markdown body\n", encoding="utf-8"
                )
                (out_dir / "doc_p.md").write_text(
                    "pdf markdown body\n", encoding="utf-8"
                )
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch.object(shutil, "which", return_value="/usr/bin/npx"):
                with mock.patch.object(subprocess, "run", side_effect=fake_run):
                    _prime_kordoc_batches(rows, files_dir)

            self.assertEqual(len(captured_cmds), 1)
            cmd = captured_cmds[0]
            self.assertIn(str(hwp_path), cmd)
            self.assertIn(str(pdf_path), cmd)

            hwp_loader = _resolve_loader("hwp")
            pdf_loader = _resolve_loader("pdf")
            self.assertIn(
                "hwp markdown body",
                hwp_loader.load_text({"텍스트": "csv"}, hwp_path),
            )
            self.assertEqual(hwp_loader.last_text_source, "kordoc")
            self.assertIn(
                "pdf markdown body",
                pdf_loader.load_text({"텍스트": "csv"}, pdf_path),
            )
            self.assertEqual(pdf_loader.last_text_source, "kordoc")

    def test_pdf_opt_out_keeps_hwp_kordoc_path(self) -> None:
        from ingestion import _prime_kordoc_batches

        os.environ["BIDMATE_PDF_LOADER"] = "csv_text"
        with TemporaryDirectory() as tmpdir:
            files_dir = Path(tmpdir)
            hwp_path = files_dir / "only_hwp.hwp"
            pdf_path = files_dir / "only_pdf.pdf"
            hwp_path.write_bytes(b"\x00" * 4)
            pdf_path.write_bytes(b"\x00" * 4)
            rows = [
                {"파일명": "only_hwp.hwp", "파일형식": "hwp"},
                {"파일명": "only_pdf.pdf", "파일형식": "pdf"},
            ]
            captured_cmds: list[list[str]] = []

            def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
                captured_cmds.append(list(cmd))
                out_dir = Path(cmd[cmd.index("-d") + 1])
                (out_dir / "only_hwp.md").write_text(
                    "hwp body\n", encoding="utf-8"
                )
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch.object(shutil, "which", return_value="/usr/bin/npx"):
                with mock.patch.object(subprocess, "run", side_effect=fake_run):
                    _prime_kordoc_batches(rows, files_dir)

            self.assertEqual(len(captured_cmds), 1)
            cmd = captured_cmds[0]
            self.assertIn(str(hwp_path), cmd)
            self.assertNotIn(str(pdf_path), cmd)


class KordocCacheDirBypassTest(unittest.TestCase):
    """``BIDMATE_KORDOC_CACHE_DIR`` env var bypass (Phase 3.5 closeout, #957).

    Pins the cache-hit path that avoids the npx subprocess entirely when
    every source file has a matching ``<stem>.md`` in the cache dir.
    Backward-compat: cache miss + cache unset both leave subprocess
    behavior unchanged (covered by existing tests above).
    """

    def setUp(self) -> None:
        self._env_backup = {
            "BIDMATE_KORDOC_CACHE_DIR": os.environ.get("BIDMATE_KORDOC_CACHE_DIR"),
        }
        os.environ.pop("BIDMATE_KORDOC_CACHE_DIR", None)

    def tearDown(self) -> None:
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_full_cache_hit_bypasses_npx_subprocess(self) -> None:
        # When every source path's stem has a matching .md in the cache,
        # _kordoc_convert_batch returns cached content WITHOUT invoking
        # ``subprocess.run``. This is the Phase 3.5 closeout path that
        # turns 8-16h kordoc subprocess calls into a ~2-3min cache read.
        from ingestion import _kordoc_convert_batch

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cache_dir = tmp_path / "kordoc_cache"
            cache_dir.mkdir()
            # Two source files with stem-matched .md in cache.
            src_a = tmp_path / "doc_a.hwp"
            src_b = tmp_path / "doc_b.hwp"
            src_a.touch()
            src_b.touch()
            (cache_dir / "doc_a.md").write_text(
                "# Heading A\n\nBody of doc A.\n", encoding="utf-8"
            )
            (cache_dir / "doc_b.md").write_text(
                "# Heading B\n\nBody of doc B.\n", encoding="utf-8"
            )
            os.environ["BIDMATE_KORDOC_CACHE_DIR"] = str(cache_dir)

            # Sentinel: subprocess.run must NOT be called. If the bypass
            # fails, ``run`` would be invoked and raise here.
            def must_not_run(*args, **kwargs):  # type: ignore[no-untyped-def]
                raise AssertionError(
                    "subprocess.run must not be invoked on full cache hit"
                )

            with mock.patch.object(subprocess, "run", side_effect=must_not_run):
                result = _kordoc_convert_batch([src_a, src_b])

            self.assertEqual(set(result.keys()), {"doc_a", "doc_b"})
            # Content is post-processed by the same pipeline (normalize_body_text),
            # so we check the body survives (heading + body).
            self.assertIn("doc A", result["doc_a"])
            self.assertIn("doc B", result["doc_b"])

    def test_partial_cache_hit_falls_through_to_subprocess(self) -> None:
        # When the cache covers only SOME source paths, the bypass falls
        # through to the npx subprocess (which extracts ALL files; partial-
        # miss merging is not worth the complexity).
        from ingestion import _kordoc_convert_batch

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cache_dir = tmp_path / "kordoc_cache"
            cache_dir.mkdir()
            src_a = tmp_path / "cached.hwp"
            src_b = tmp_path / "not_cached.hwp"
            src_a.touch()
            src_b.touch()
            # Only cached.md is in the cache; not_cached.md is missing.
            (cache_dir / "cached.md").write_text("body", encoding="utf-8")
            os.environ["BIDMATE_KORDOC_CACHE_DIR"] = str(cache_dir)

            captured: list[list[str]] = []

            def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
                captured.append(list(cmd))
                out_dir = Path(cmd[cmd.index("-d") + 1])
                (out_dir / "cached.md").write_text("subprocess body A\n", encoding="utf-8")
                (out_dir / "not_cached.md").write_text(
                    "subprocess body B\n", encoding="utf-8"
                )
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch.object(shutil, "which", return_value="/usr/bin/npx"):
                with mock.patch.object(subprocess, "run", side_effect=fake_run):
                    result = _kordoc_convert_batch([src_a, src_b])

            # Partial cache → subprocess was invoked (which extracted both).
            self.assertEqual(len(captured), 1)
            self.assertEqual(set(result.keys()), {"cached", "not_cached"})
            # Both come from subprocess output (cache result was discarded
            # on partial-hit fallback).
            self.assertIn("subprocess body B", result["not_cached"])

    def test_unset_env_var_uses_subprocess_path(self) -> None:
        # Backward-compat: env var unset → no cache check, subprocess invoked.
        from ingestion import _kordoc_convert_batch

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "doc.hwp"
            src.touch()
            # No env var set (setUp pops it).
            self.assertNotIn("BIDMATE_KORDOC_CACHE_DIR", os.environ)

            captured: list[list[str]] = []

            def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
                captured.append(list(cmd))
                out_dir = Path(cmd[cmd.index("-d") + 1])
                (out_dir / "doc.md").write_text("subprocess body\n", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch.object(shutil, "which", return_value="/usr/bin/npx"):
                with mock.patch.object(subprocess, "run", side_effect=fake_run):
                    result = _kordoc_convert_batch([src])

            self.assertEqual(len(captured), 1)
            self.assertIn("subprocess body", result["doc"])


if __name__ == "__main__":
    unittest.main()
