"""E2E regression for the #237 harness observability auto-append.

Each successful ``scripts/run_harness.py`` run must:

1. Write an ``observability`` block into ``run_manifest.json`` carrying
   ``backend`` / ``trace_url`` / ``unavailable_reason`` / ``schema_version``.
2. Append a chronological aggregate snapshot to
   ``reports/harness_history/`` whose on-disk shape mirrors
   ``scripts/write_synthetic_history.py`` (so
   ``scripts/leaderboard.py:load_history`` can be retargeted to
   harness runs without code changes).
3. Honour ``--no-observability``: no trace setup, no history file,
   manifest still carries an ``observability`` block with
   ``unavailable_reason == "disabled"`` so downstream consumers can
   distinguish "tracing turned off" from "tracing failed".

The tests do **not** require a live LangFuse instance — the default
backend (``none``) is exercised, which is the realistic CI path. The
manifest contract is identical regardless of which backend resolves;
backend selection itself is covered by ``test_observability_tracing.py``.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


class HarnessObservabilityE2ETest(unittest.TestCase):
    """E2E: invoke ``scripts/run_harness.py`` and inspect the manifest contract."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp_root = Path(__file__).resolve().parent / "_tmp_observability_artifacts"
        if cls.tmp_root.exists():
            shutil.rmtree(cls.tmp_root)
        cls.tmp_root.mkdir(parents=True)
        # Quarantine reports/harness_history side effects so a CI box
        # doesn't accumulate junk and a developer's working tree stays
        # clean. The harness writes into ROOT_DIR/reports/harness_history,
        # so we capture its pre-test snapshot and restore the diff later.
        cls.harness_history_dir = ROOT_DIR / "reports" / "harness_history"
        cls._pre_existing = (
            {p.name for p in cls.harness_history_dir.iterdir()}
            if cls.harness_history_dir.exists()
            else set()
        )

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.tmp_root.exists():
            shutil.rmtree(cls.tmp_root)
        if cls.harness_history_dir.exists():
            for p in cls.harness_history_dir.iterdir():
                if p.name not in cls._pre_existing:
                    p.unlink(missing_ok=True)

    def _run_harness(
        self,
        run_id: str,
        *,
        extra_args: tuple[str, ...] = (),
        env_overrides: dict[str, str] | None = None,
    ) -> dict:
        env = os.environ.copy()
        # The test must drive its own observability behavior; clear any
        # outer-scope BIDMATE_TRACE_BACKEND so we know the default
        # ``none`` resolves cleanly.
        env.pop("BIDMATE_TRACE_BACKEND", None)
        if env_overrides:
            env.update(env_overrides)
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
                *extra_args,
            ],
            cwd=ROOT_DIR,
            env=env,
            text=True,
            capture_output=True,
            timeout=180,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout={result.stdout}\nstderr={result.stderr}",
        )
        manifest_path = self.tmp_root / run_id / "run_manifest.json"
        self.assertTrue(manifest_path.exists(), "manifest not written")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    # --- Default-on observability ------------------------------------

    def test_default_run_has_observability_block_with_none_backend(self) -> None:
        manifest = self._run_harness("obs_default")
        self.assertIn("observability", manifest, "manifest missing observability block")
        block = manifest["observability"]
        self.assertEqual(block["backend"], "none")
        # Without ``BIDMATE_TRACE_BACKEND`` set, the resolver returns
        # the noop backend "cleanly" — ``unavailable_reason`` is None.
        self.assertIsNone(block["unavailable_reason"])
        self.assertIsNone(block["trace_url"])
        self.assertIn("schema_version", block)

    def test_default_run_writes_harness_history_aggregate(self) -> None:
        manifest = self._run_harness("obs_history")
        block = manifest["observability"]
        self.assertIn("history_path", block, "history snapshot was not written")
        history_path = ROOT_DIR / block["history_path"]
        self.assertTrue(history_path.exists(), f"missing {history_path}")
        snapshot = json.loads(history_path.read_text(encoding="utf-8"))
        # Mirror the public synthetic-history schema so the
        # leaderboard loader is reusable on this directory.
        for key in (
            "schema_version",
            "source",
            "run_id",
            "provenance",
            "metrics",
            "observability",
        ):
            self.assertIn(key, snapshot, f"history snapshot missing key {key!r}")
        self.assertEqual(snapshot["source"], "run_harness")
        self.assertEqual(snapshot["run_id"], "obs_history")
        # Provenance must carry git_commit / generated_at so the
        # leaderboard can sort chronologically and link back to a sha.
        for key in ("git_commit", "generated_at"):
            self.assertIn(key, snapshot["provenance"])

    def test_history_filename_uses_timestamp_and_sha_prefix(self) -> None:
        manifest = self._run_harness("obs_filename")
        history_path = ROOT_DIR / manifest["observability"]["history_path"]
        name = history_path.name
        # ``<YYYYMMDDTHHMMSSZ>_<sha12>.aggregate.json`` — mirrors
        # write_synthetic_history.py so the loader's filename parser
        # works on both directories.
        self.assertTrue(name.endswith(".aggregate.json"))
        stem = name.removesuffix(".aggregate.json")
        self.assertIn("_", stem)
        ts, sha = stem.split("_", 1)
        self.assertEqual(len(ts), len("YYYYMMDDTHHMMSSZ"))
        self.assertEqual(ts[-1], "Z")
        self.assertTrue(sha, "sha portion of filename is empty")

    # --- --no-observability ------------------------------------------

    def test_no_observability_flag_disables_history_and_marks_reason(self) -> None:
        manifest = self._run_harness(
            "obs_disabled", extra_args=("--no-observability",)
        )
        block = manifest["observability"]
        self.assertEqual(block["backend"], "none")
        self.assertEqual(
            block["unavailable_reason"],
            "disabled",
            "--no-observability must mark the reason so downstream consumers "
            "can distinguish opt-out from a failed backend resolve",
        )
        self.assertIsNone(block["trace_url"])
        self.assertNotIn(
            "history_path",
            block,
            "--no-observability must NOT write a history snapshot",
        )

    # --- Backwards compatibility with existing manifest contract -----

    def test_existing_manifest_fields_unchanged(self) -> None:
        manifest = self._run_harness("obs_compat")
        # Non-observability fields must keep the schema_version=1 shape
        # so consumers reading the prior manifest layout continue to work.
        for key in (
            "schema_version",
            "run_id",
            "generated_at",
            "git_commit",
            "config_hash",
            "artifacts",
            "commands",
            "status",
            "metrics",
        ):
            self.assertIn(key, manifest, f"manifest missing legacy key {key!r}")
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["status"], "passed")


if __name__ == "__main__":
    unittest.main()
