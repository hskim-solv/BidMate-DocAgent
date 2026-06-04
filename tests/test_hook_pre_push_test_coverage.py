"""Regression: pre-push test-coverage gate (issue #1052).

Pins the soft-warn contract (always exit 0; warning only on stderr) for
`.githooks/_pre-push-test-coverage.sh`:

  1. behavior-code change + zero tests/ change → exit 0, stderr warns
  2. behavior-code change + a tests/ change    → exit 0, stderr quiet
  3. docs-only change                          → exit 0, stderr quiet
  4. no origin/main ref (fresh branch)         → exit 0, stderr quiet

Each scenario runs in an isolated temp git repo. The hook calls
`python3 scripts/_governance.py --any-match` relative to cwd, so the real
governance module is copied into the temp repo's scripts/ dir — its
matching is pure string logic (no file existence check), so a copied
module against fake-named diffs is faithful.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).parents[1]
HOOK = REPO / ".githooks" / "_pre-push-test-coverage.sh"
GOVERNANCE = REPO / "scripts" / "_governance.py"


class TestPrePushTestCoverage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="pre-push-test-cov-")
        self.repo = Path(self._tmp) / "repo"
        self.repo.mkdir(parents=True)
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "tester")
        self._git("config", "commit.gpgsign", "false")
        # The hook resolves `scripts/_governance.py` relative to cwd.
        (self.repo / "scripts").mkdir()
        shutil.copy(GOVERNANCE, self.repo / "scripts" / "_governance.py")
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "base")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=False,
        )

    def _pin_origin_main(self) -> None:
        head = self._git("rev-parse", "HEAD").stdout.strip()
        self._git("update-ref", "refs/remotes/origin/main", head)

    def _commit(self, *paths: str) -> None:
        for path in paths:
            f = self.repo / path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", f"add {' '.join(paths)}")

    def _run_hook(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(HOOK)],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_behavior_change_without_test_warns(self) -> None:
        self._pin_origin_main()
        self._commit("rag_core.py")
        r = self._run_hook()
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("without an accompanying test", r.stderr)
        self.assertIn("rag_core.py", r.stderr)

    def test_behavior_change_with_test_is_quiet(self) -> None:
        self._pin_origin_main()
        self._commit("rag_core.py", "tests/test_rag_core_regression.py")
        r = self._run_hook()
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("", r.stderr.strip(), r.stderr)

    def test_docs_only_change_is_quiet(self) -> None:
        self._pin_origin_main()
        self._commit("docs/note.md")
        r = self._run_hook()
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("", r.stderr.strip(), r.stderr)

    def test_non_load_bearing_code_path_is_quiet(self) -> None:
        self._pin_origin_main()
        self._commit("scripts/non_loadbearing_helper.py")
        r = self._run_hook()
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("", r.stderr.strip(), r.stderr)

    def test_no_origin_main_ref_is_quiet(self) -> None:
        # No origin/main ref and no upstream → base diff is empty → quiet.
        self._commit("rag_core.py")
        r = self._run_hook()
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("", r.stderr.strip(), r.stderr)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
