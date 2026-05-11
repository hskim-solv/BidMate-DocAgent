"""Regression tests for scripts/run_harness.py.

Covers issue #235 (Harness v2 — profile expansion + matrix/compare):

* single-run roundtrip & config_hash determinism
* matrix executor with deep-merge + ADR 0001 guard
* compare mode rendering on synthetic eval_summary.json fixtures
* errors.jsonl contract pinned (failure shape)
* validation guards (zero cells, missing naive_baseline, missing compare.base)

Pure-rendering and validation tests are fast. The end-to-end subprocess test
uses the existing hashing-backend smoke surface (data/raw committed + the
3-case harness/smoke_eval.yaml) and runs in well under a minute.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import run_harness  # noqa: E402
from harness_compare import render_matrix_compare, render_pair, resolve_summary  # noqa: E402


# ---------------------------------------------------------------------------
# Pure unit tests — no subprocess
# ---------------------------------------------------------------------------


class DeepMergeTest(unittest.TestCase):
    def test_overrides_nested_keys_only_in_whitelist(self) -> None:
        base = {
            "dataset": {"id": "x", "input_dir": "data/raw"},
            "index": {"embedding_backend": "hashing"},
        }
        override = {"index": {"embedding_backend": "openai", "chunking_strategy": "paragraph"}}
        merged = run_harness._deep_merge(base, override)
        self.assertEqual(merged["dataset"], {"id": "x", "input_dir": "data/raw"})
        self.assertEqual(
            merged["index"],
            {"embedding_backend": "openai", "chunking_strategy": "paragraph"},
        )

    def test_forbidden_top_level_override_raises(self) -> None:
        for forbidden in ("id", "description", "artifact_root", "matrix", "compare", "base"):
            with self.assertRaises(ValueError):
                run_harness._deep_merge({"index": {}}, {forbidden: "x"})

    def test_base_is_not_mutated(self) -> None:
        base = {"index": {"embedding_backend": "hashing"}}
        override = {"index": {"embedding_backend": "openai"}}
        run_harness._deep_merge(base, override)
        self.assertEqual(base["index"]["embedding_backend"], "hashing")


class MatrixValidationTest(unittest.TestCase):
    def _base_matrix(self) -> dict:
        return {
            "id": "test_matrix",
            "base": {"query": {"pipeline": "naive_baseline"}},
            "matrix": [{"name": "naive_baseline", "override": {}}],
        }

    def test_zero_cells_raises(self) -> None:
        matrix = self._base_matrix()
        matrix["matrix"] = []
        with self.assertRaises(SystemExit):
            run_harness._validate_matrix(matrix)

    def test_missing_naive_baseline_raises_adr_0001(self) -> None:
        matrix = self._base_matrix()
        matrix["matrix"] = [
            {"name": "other_cell", "override": {"query": {"pipeline": "agentic_full"}}}
        ]
        with self.assertRaises(SystemExit) as ctx:
            run_harness._validate_matrix(matrix)
        self.assertIn("ADR 0001", str(ctx.exception))

    def test_naive_baseline_with_wrong_pipeline_raises(self) -> None:
        matrix = self._base_matrix()
        matrix["matrix"] = [
            {"name": "naive_baseline", "override": {"query": {"pipeline": "agentic_full"}}}
        ]
        with self.assertRaises(SystemExit) as ctx:
            run_harness._validate_matrix(matrix)
        self.assertIn("ADR 0001", str(ctx.exception))

    def test_compare_base_must_exist(self) -> None:
        matrix = self._base_matrix()
        matrix["compare"] = {"base": "missing_cell"}
        with self.assertRaises(SystemExit) as ctx:
            run_harness._validate_matrix(matrix)
        self.assertIn("missing_cell", str(ctx.exception))

    def test_duplicate_cell_names_raise(self) -> None:
        matrix = self._base_matrix()
        matrix["matrix"] = [
            {"name": "naive_baseline", "override": {}},
            {"name": "naive_baseline", "override": {}},
        ]
        with self.assertRaises(SystemExit):
            run_harness._validate_matrix(matrix)

    def test_invalid_on_cell_failure_raises(self) -> None:
        matrix = self._base_matrix()
        matrix["on_cell_failure"] = "panic"
        with self.assertRaises(SystemExit):
            run_harness._validate_matrix(matrix)

    def test_minimal_valid_matrix_passes(self) -> None:
        run_harness._validate_matrix(self._base_matrix())  # should not raise


class CompareRenderingTest(unittest.TestCase):
    def test_pair_renders_improvement_and_regression_flags(self) -> None:
        base = {"num_predictions": 3, "accuracy": 0.5, "groundedness": 0.7, "retry": 0.0}
        head = {"num_predictions": 3, "accuracy": 0.7, "groundedness": 0.7, "retry": 0.2}
        markdown = render_pair(base, head, title="t")
        self.assertIn("| accuracy |", markdown)
        # accuracy up + higher-is-better → improvement
        self.assertIn("✅", markdown)
        # retry up + lower-is-better → regression
        self.assertIn("⚠️", markdown)

    def test_matrix_compare_renders_n_columns(self) -> None:
        cells = [
            {
                "name": "naive_baseline",
                "status": "passed",
                "eval_summary": {"accuracy": 0.5, "groundedness": 0.6},
            },
            {
                "name": "other",
                "status": "passed",
                "eval_summary": {"accuracy": 0.7, "groundedness": 0.6},
            },
        ]
        markdown = render_matrix_compare(cells, "naive_baseline", matrix_id="m")
        self.assertIn("naive_baseline", markdown)
        self.assertIn("other", markdown)
        self.assertIn("Δ other", markdown)
        self.assertIn("| accuracy |", markdown)

    def test_matrix_compare_marks_failed_cells_as_dash(self) -> None:
        cells = [
            {
                "name": "naive_baseline",
                "status": "passed",
                "eval_summary": {"accuracy": 0.5},
            },
            {"name": "broken", "status": "failed", "eval_summary": {}},
        ]
        markdown = render_matrix_compare(cells, "naive_baseline", matrix_id="m")
        self.assertIn("failed cells: broken", markdown)

    def test_matrix_compare_missing_base_raises(self) -> None:
        cells = [{"name": "a", "status": "passed", "eval_summary": {}}]
        with self.assertRaises(ValueError):
            render_matrix_compare(cells, "missing", matrix_id="m")


class ResolveSummaryTest(unittest.TestCase):
    def test_resolves_run_dir_to_eval_summary(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            (run_dir / "metrics").mkdir(parents=True)
            summary = run_dir / "metrics" / "eval_summary.json"
            summary.write_text("{}", encoding="utf-8")
            resolved = resolve_summary(run_dir)
            self.assertEqual(resolved, summary)

    def test_resolves_direct_json(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{}")
            tmp_path = Path(fh.name)
        try:
            self.assertEqual(resolve_summary(tmp_path), tmp_path)
        finally:
            tmp_path.unlink()

    def test_missing_path_raises(self) -> None:
        with self.assertRaises(SystemExit):
            resolve_summary(Path("/nonexistent/abc/xyz.json"))


class CompareCliTest(unittest.TestCase):
    def test_compare_cli_emits_delta_markdown(self) -> None:
        import tempfile

        a = {"num_predictions": 3, "accuracy": 0.5, "retry": 0.0}
        b = {"num_predictions": 3, "accuracy": 0.7, "retry": 0.2}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            a_path = tmp_path / "a.json"
            b_path = tmp_path / "b.json"
            out_path = tmp_path / "compare.md"
            a_path.write_text(json.dumps(a), encoding="utf-8")
            b_path.write_text(json.dumps(b), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT_DIR / "scripts" / "run_harness.py"),
                    "--compare",
                    "--run-a",
                    str(a_path),
                    "--run-b",
                    str(b_path),
                    "--out",
                    str(out_path),
                ],
                cwd=ROOT_DIR,
                text=True,
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("| accuracy |", result.stdout)
            self.assertTrue(out_path.exists())
            written = out_path.read_text(encoding="utf-8")
            self.assertIn("✅", written)
            self.assertIn("⚠️", written)


# ---------------------------------------------------------------------------
# End-to-end subprocess tests (slower; share the committed smoke surface)
# ---------------------------------------------------------------------------


class HarnessE2ETest(unittest.TestCase):
    """E2E: invoke run_harness.py as a subprocess against committed synthetic data.

    Runs the harness with hashing backend on the 3-case harness/smoke_eval.yaml
    fixture. Each run is ~10-15 s; total file run-time under a minute.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp_root = Path(__file__).resolve().parent / "_tmp_harness_artifacts"
        if cls.tmp_root.exists():
            import shutil

            shutil.rmtree(cls.tmp_root)
        cls.tmp_root.mkdir(parents=True)

    @classmethod
    def tearDownClass(cls) -> None:
        import shutil

        if cls.tmp_root.exists():
            shutil.rmtree(cls.tmp_root)

    def _run_smoke(self, run_id: str) -> dict:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT_DIR / "scripts" / "run_harness.py"),
                "--config",
                "harness/smoke.yaml",
                "--run_id",
                run_id,
                "--artifact_root",
                str(self.tmp_root),
                "--force",
            ],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, msg=f"stdout={result.stdout}\nstderr={result.stderr}")
        manifest_path = self.tmp_root / run_id / "run_manifest.json"
        self.assertTrue(manifest_path.exists())
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def test_smoke_roundtrip_artifact_keys_pinned(self) -> None:
        manifest = self._run_smoke("t1_keys")
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["status"], "passed")
        expected_artifact_keys = {
            "run_dir",
            "run_manifest",
            "config_snapshot",
            "summary",
            "predictions",
            "metrics",
            "errors",
            "logs",
            "index",
            "answer",
        }
        self.assertEqual(set(manifest["artifacts"].keys()), expected_artifact_keys)

    def test_config_hash_is_deterministic_across_run_ids(self) -> None:
        m_a = self._run_smoke("t2_hash_a")
        m_b = self._run_smoke("t2_hash_b")
        self.assertEqual(
            m_a["config_hash"],
            m_b["config_hash"],
            "config_hash should depend only on harness/eval YAML, not run_id",
        )

    def test_matrix_executor_writes_summary_and_compare(self) -> None:
        matrix_id = "t3_matrix"
        matrix_yaml = {
            "id": matrix_id,
            "description": "test matrix",
            "artifact_root": str(self.tmp_root),
            "base": {
                "dataset": {
                    "id": "public_synthetic_rfp_v1",
                    "input_dir": "data/raw",
                    "privacy": "public_synthetic_only",
                },
                "index": {"embedding_backend": "hashing", "chunking_strategy": "fixed"},
                "query": {
                    "text": "기관 A와 기관 B의 AI 요구사항 차이 알려줘",
                    "pipeline": "naive_baseline",
                },
                "eval": {"config": "harness/smoke_eval.yaml"},
            },
            "matrix": [
                {"name": "naive_baseline", "override": {}},
                {"name": "naive_baseline_v2", "override": {}},
            ],
            "compare": {"base": "naive_baseline"},
            "on_cell_failure": "continue",
        }
        matrix_path = self.tmp_root / "matrix.yaml"
        matrix_path.write_text(
            yaml.safe_dump(matrix_yaml, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT_DIR / "scripts" / "run_harness.py"),
                "--matrix",
                str(matrix_path),
                "--force",
            ],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            timeout=300,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout={result.stdout}\nstderr={result.stderr}",
        )
        matrix_dir = self.tmp_root / matrix_id
        summary_path = matrix_dir / "matrix_summary.json"
        compare_path = matrix_dir / "compare.md"
        self.assertTrue(summary_path.exists())
        self.assertTrue(compare_path.exists())

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["cells_passed"], 2)
        self.assertEqual(summary["cells_failed"], 0)
        cell_names = [c["name"] for c in summary["cells"]]
        self.assertEqual(cell_names, ["naive_baseline", "naive_baseline_v2"])

        compare_md = compare_path.read_text(encoding="utf-8")
        self.assertIn("| accuracy |", compare_md)
        self.assertIn("naive_baseline_v2", compare_md)

    def test_errors_jsonl_contract_on_step_failure(self) -> None:
        """Exercise the subprocess-step-failure path.

        Use a pipeline name that fails argparse 'choices' validation in app.py,
        which causes the 'query' step to exit non-zero. The harness records the
        failure in errors.jsonl with {step, returncode, log, command}.
        """
        run_id = "t4_errors"
        config = {
            "id": "t4_errors",
            "description": "failure case — invalid pipeline name",
            "dataset": {
                "id": "public_synthetic_rfp_v1",
                "input_dir": "data/raw",
                "privacy": "public_synthetic_only",
            },
            "index": {"embedding_backend": "hashing", "chunking_strategy": "fixed"},
            "query": {
                "text": "기관 A와 기관 B의 AI 요구사항 차이 알려줘",
                "pipeline": "definitely_not_a_real_pipeline_xyz",
            },
            "eval": {"config": "harness/smoke_eval.yaml"},
        }
        config_path = self.tmp_root / "fail.yaml"
        config_path.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT_DIR / "scripts" / "run_harness.py"),
                "--config",
                str(config_path),
                "--run_id",
                run_id,
                "--artifact_root",
                str(self.tmp_root),
                "--force",
            ],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            timeout=180,
        )
        self.assertEqual(
            result.returncode,
            2,
            msg=f"expected step-failure exit=2, got {result.returncode}. "
            f"stdout={result.stdout}\nstderr={result.stderr}",
        )
        run_dir = self.tmp_root / run_id
        errors_path = run_dir / "errors.jsonl"
        self.assertTrue(errors_path.exists())
        lines = [
            json.loads(line)
            for line in errors_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(lines), 1, msg=f"expected 1 failure record, got {lines}")
        record = lines[0]
        for key in ("step", "returncode", "log", "command"):
            self.assertIn(key, record)
        self.assertEqual(record["step"], "query")
        self.assertNotEqual(record["returncode"], 0)
        self.assertIsInstance(record["command"], list)


if __name__ == "__main__":
    unittest.main()
