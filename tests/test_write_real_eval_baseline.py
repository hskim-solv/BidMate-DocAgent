"""Contract test for strict mode in scripts/write_real_eval_baseline.py (#414).

Locks (a) the default warn-only behavior preserved for back-compat and
(b) the strict-mode escalation: ``--strict`` and
``BIDMATE_BASELINE_STRICT=1`` must both flip the two existing
provenance warnings to hard failures (exit 2, no baseline written).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts import write_real_eval_baseline as writer  # noqa: E402


# ---- _resolve_strict unit -------------------------------------------------


class ResolveStrictUnit(unittest.TestCase):
    def test_flag_true_returns_true(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(writer.STRICT_ENV_VAR, None)
            self.assertTrue(writer._resolve_strict(True))

    def test_flag_false_env_unset_returns_false(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(writer.STRICT_ENV_VAR, None)
            self.assertFalse(writer._resolve_strict(False))

    def test_env_truthy_values(self) -> None:
        for value in ("1", "true", "TRUE", "yes", "Yes"):
            with mock.patch.dict(os.environ, {writer.STRICT_ENV_VAR: value}):
                self.assertTrue(
                    writer._resolve_strict(False),
                    f"expected {value!r} to be truthy",
                )

    def test_env_falsy_values(self) -> None:
        for value in ("0", "false", "no", "", "off", "garbage"):
            with mock.patch.dict(os.environ, {writer.STRICT_ENV_VAR: value}):
                self.assertFalse(
                    writer._resolve_strict(False),
                    f"expected {value!r} to be falsy",
                )

    def test_flag_overrides_falsy_env(self) -> None:
        with mock.patch.dict(os.environ, {writer.STRICT_ENV_VAR: "0"}):
            self.assertTrue(writer._resolve_strict(True))


# ---- _warn_if_stale unit --------------------------------------------------


class WarnIfStaleUnit(unittest.TestCase):
    def test_default_warns_on_skew_and_returns(self) -> None:
        eval_prov = {"git_commit": "abc123"}
        baseline_prov = {"git_commit": "def456"}
        try:
            writer._warn_if_stale(eval_prov, baseline_prov)
        except SystemExit:
            self.fail("default mode must not raise on skew")

    def test_strict_raises_on_skew(self) -> None:
        eval_prov = {"git_commit": "abc123"}
        baseline_prov = {"git_commit": "def456"}
        with self.assertRaises(SystemExit) as cm:
            writer._warn_if_stale(eval_prov, baseline_prov, strict=True)
        self.assertEqual(cm.exception.code, 2)

    def test_default_warns_on_missing_eval_provenance_and_returns(self) -> None:
        baseline_prov = {"git_commit": "def456"}
        try:
            writer._warn_if_stale(None, baseline_prov)
        except SystemExit:
            self.fail("default mode must not raise on missing eval provenance")

    def test_strict_raises_on_missing_eval_provenance(self) -> None:
        baseline_prov = {"git_commit": "def456"}
        with self.assertRaises(SystemExit) as cm:
            writer._warn_if_stale(None, baseline_prov, strict=True)
        self.assertEqual(cm.exception.code, 2)

    def test_no_skew_returns_silently_in_both_modes(self) -> None:
        eval_prov = {"git_commit": "abc123"}
        baseline_prov = {"git_commit": "abc123"}
        try:
            writer._warn_if_stale(eval_prov, baseline_prov)
            writer._warn_if_stale(eval_prov, baseline_prov, strict=True)
        except SystemExit:
            self.fail("matching SHAs must not raise in either mode")


# ---- CLI integration ------------------------------------------------------


class WriterCli(unittest.TestCase):
    """End-to-end: run the writer in a tempdir layout with a synthesized
    eval_summary.json. We avoid invoking it in REPO_ROOT to keep the test
    isolated from the real reports/real100/ state."""

    def setUp(self) -> None:
        self._td = Path(tempfile.mkdtemp())
        self._reports = self._td / "reports" / "real100"
        self._reports.mkdir(parents=True)
        self._eval_summary = self._reports / "eval_summary.json"
        self._baseline = self._reports / "baseline.aggregate.json"
        self._history = self._reports / "history"

    def _write_eval_summary(self, eval_sha: str | None) -> None:
        body: dict[str, object] = {
            "num_predictions": 21,
            "accuracy": 0.47,
            "pipeline": "agentic_full",
            "latency": {"mean": 100, "p50": 90, "p95": 200},
        }
        if eval_sha is not None:
            body["provenance"] = {
                "generated_at": "2026-05-12T00:00:00.000000Z",
                "git_commit": eval_sha,
                "git_dirty": False,
            }
        self._eval_summary.write_text(
            json.dumps(body, ensure_ascii=False), encoding="utf-8"
        )

    def _invoke(
        self,
        *extra_args: str,
        env_strict: str | None = None,
    ) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.pop(writer.STRICT_ENV_VAR, None)
        if env_strict is not None:
            env[writer.STRICT_ENV_VAR] = env_strict
        # Run a small driver that points the writer at the tempdir.
        # ROOT is also rebound so the success-path `relative_to(ROOT)`
        # call (used only for the [OK] print) resolves cleanly.
        driver = (
            "import sys, os\n"
            f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
            "from scripts import write_real_eval_baseline as w\n"
            "from pathlib import Path\n"
            f"w.ROOT = Path({str(self._td)!r})\n"
            f"w.EVAL_SUMMARY = Path({str(self._eval_summary)!r})\n"
            f"w.BASELINE_PATH = Path({str(self._baseline)!r})\n"
            f"w.HISTORY_DIR = Path({str(self._history)!r})\n"
            f"w.JUDGE_LOCAL = Path({str(self._td / 'no-such-judge.json')!r})\n"
            "raise SystemExit(w.main())\n"
        )
        return subprocess.run(
            [sys.executable, "-c", driver, *extra_args],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_warn_mode_no_skew_writes_baseline(self) -> None:
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()[:12]
        self._write_eval_summary(eval_sha=head_sha)
        result = self._invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self._baseline.exists(), "baseline must be written")

    def test_warn_mode_with_skew_still_writes_baseline(self) -> None:
        # Default behavior: warn but proceed. Regression guard for back-compat.
        self._write_eval_summary(eval_sha="deadbeefcafe")
        result = self._invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[WARN] Provenance skew detected", result.stderr)
        self.assertTrue(self._baseline.exists(), "baseline must be written in warn mode")

    def test_strict_flag_with_skew_blocks_write(self) -> None:
        self._write_eval_summary(eval_sha="deadbeefcafe")
        result = self._invoke("--strict")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("[ERROR] Provenance skew detected", result.stderr)
        self.assertFalse(
            self._baseline.exists(), "baseline must NOT be written in strict-skew"
        )

    def test_strict_env_with_skew_blocks_write(self) -> None:
        self._write_eval_summary(eval_sha="deadbeefcafe")
        result = self._invoke(env_strict="1")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("[ERROR] Provenance skew detected", result.stderr)
        self.assertFalse(self._baseline.exists())

    def test_strict_env_falsy_keeps_warn_mode(self) -> None:
        self._write_eval_summary(eval_sha="deadbeefcafe")
        result = self._invoke(env_strict="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[WARN]", result.stderr)
        self.assertTrue(self._baseline.exists())

    def test_strict_blocks_when_eval_provenance_missing(self) -> None:
        self._write_eval_summary(eval_sha=None)
        result = self._invoke("--strict")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn(
            "[ERROR] eval_summary.json has no `provenance` block", result.stderr
        )
        self.assertFalse(self._baseline.exists())


if __name__ == "__main__":
    unittest.main()
