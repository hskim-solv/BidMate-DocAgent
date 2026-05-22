"""Contract test for the baseline provenance reachability gate (issue #413).

Locks the semantics so silent regressions (dangling SHAs, run_manifest
mismatch, malformed baseline) cannot ship a green real-eval-delta gate.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_baseline_provenance import check  # noqa: E402


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def _init_repo(td: Path) -> dict[str, str]:
    """Build a tempdir git repo with a known commit graph.

    Layout::

        main ── A ── B   (HEAD on `feature`)
                 \\
                  └── C  (on `feature`, NOT yet on main)

        D                 (orphan commit, not on any ref)

    Returns shas: ``{"a": A12, "b": B12, "c": C12, "d_orphan": D12}``.
    """
    _git(["init", "--initial-branch=main"], cwd=td)
    _git(["config", "user.email", "test@example.com"], cwd=td)
    _git(["config", "user.name", "Test"], cwd=td)
    _git(["commit", "--allow-empty", "-m", "A"], cwd=td)
    sha_a = _git(["rev-parse", "HEAD"], cwd=td)
    _git(["commit", "--allow-empty", "-m", "B"], cwd=td)
    sha_b = _git(["rev-parse", "HEAD"], cwd=td)
    _git(["checkout", "-b", "feature", sha_a], cwd=td)
    _git(["commit", "--allow-empty", "-m", "C"], cwd=td)
    sha_c = _git(["rev-parse", "HEAD"], cwd=td)

    empty_tree = subprocess.run(
        ["git", "mktree"],
        cwd=td,
        input="",
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    sha_d = subprocess.run(
        ["git", "commit-tree", empty_tree, "-m", "D-orphan"],
        cwd=td,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()

    _git(["checkout", "main"], cwd=td)

    return {
        "a": sha_a[:12],
        "b": sha_b[:12],
        "c": sha_c[:12],
        "d_orphan": sha_d[:12],
    }


def _write_baseline(
    path: Path,
    provenance_sha: str,
    run_manifest_sha: str | None = "match",
    provenance_tree: str | None = None,
) -> None:
    provenance: dict[str, object] = {
        "generated_at": "2026-05-12T00:00:00.000000Z",
        "git_commit": provenance_sha,
        "git_dirty": False,
    }
    if provenance_tree is not None:
        provenance["git_tree"] = provenance_tree
    body: dict[str, object] = {"provenance": provenance}
    if run_manifest_sha == "match":
        body["run_manifest"] = {
            "config_sha256": "deadbeefcafe",
            "generated_at": "2026-05-12T00:00:00.000000Z",
            "git_commit": provenance_sha,
            "git_dirty": False,
        }
    elif run_manifest_sha is not None:
        body["run_manifest"] = {
            "config_sha256": "deadbeefcafe",
            "generated_at": "2026-05-12T00:00:00.000000Z",
            "git_commit": run_manifest_sha,
            "git_dirty": False,
        }
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class CheckBaselineProvenanceUnit(unittest.TestCase):
    def setUp(self) -> None:
        self._td = Path(tempfile.mkdtemp())
        self._shas = _init_repo(self._td)
        self._baseline = self._td / "baseline.aggregate.json"

    def test_ancestor_of_main_passes(self) -> None:
        _write_baseline(self._baseline, self._shas["a"])
        code, msg = check(self._baseline, "main", None, repo_root=self._td)
        self.assertEqual(code, 0, msg)
        self.assertIn("[OK]", msg)
        self.assertIn(self._shas["a"], msg)

    def test_head_of_main_passes(self) -> None:
        _write_baseline(self._baseline, self._shas["b"])
        code, _ = check(self._baseline, "main", None, repo_root=self._td)
        self.assertEqual(code, 0)

    def test_unmerged_branch_commit_fails_against_main(self) -> None:
        _write_baseline(self._baseline, self._shas["c"])
        code, msg = check(self._baseline, "main", None, repo_root=self._td)
        self.assertEqual(code, 1, msg)
        self.assertIn("not reachable", msg)

    def test_unmerged_commit_passes_with_allow_equal_to(self) -> None:
        _write_baseline(self._baseline, self._shas["c"])
        code, msg = check(
            self._baseline, "main", self._shas["c"], repo_root=self._td
        )
        self.assertEqual(code, 0, msg)
        self.assertIn("escape hatch", msg)

    def test_dangling_orphan_sha_fails(self) -> None:
        _write_baseline(self._baseline, self._shas["d_orphan"])
        code, msg = check(self._baseline, "main", None, repo_root=self._td)
        self.assertEqual(code, 1, msg)
        self.assertIn("not reachable", msg)

    def test_completely_missing_sha_fails_with_object_db_error(self) -> None:
        _write_baseline(self._baseline, "deadbeefcafe")
        code, msg = check(self._baseline, "main", None, repo_root=self._td)
        self.assertEqual(code, 1, msg)
        self.assertIn("does not exist in the git object database", msg)

    def test_provenance_run_manifest_mismatch_fails(self) -> None:
        _write_baseline(
            self._baseline,
            self._shas["a"],
            run_manifest_sha=self._shas["b"],
        )
        code, msg = check(self._baseline, "main", None, repo_root=self._td)
        self.assertEqual(code, 2, msg)
        self.assertIn("mismatch", msg)

    def test_missing_baseline_file_returns_config_error(self) -> None:
        missing = self._td / "does-not-exist.json"
        code, msg = check(missing, "main", None, repo_root=self._td)
        self.assertEqual(code, 2, msg)
        self.assertIn("baseline not found", msg)

    def test_malformed_json_returns_config_error(self) -> None:
        self._baseline.write_text("not json {", encoding="utf-8")
        code, msg = check(self._baseline, "main", None, repo_root=self._td)
        self.assertEqual(code, 2, msg)
        self.assertIn("malformed", msg)

    def test_missing_provenance_block_returns_config_error(self) -> None:
        self._baseline.write_text(
            json.dumps({"some_other_key": "value"}), encoding="utf-8"
        )
        code, msg = check(self._baseline, "main", None, repo_root=self._td)
        self.assertEqual(code, 2, msg)
        self.assertIn("provenance", msg)

    def test_baseline_without_run_manifest_still_passes(self) -> None:
        _write_baseline(
            self._baseline, self._shas["a"], run_manifest_sha=None
        )
        code, _ = check(self._baseline, "main", None, repo_root=self._td)
        self.assertEqual(code, 0)


class CheckBaselineProvenanceSquashTwin(unittest.TestCase):
    """Tree-based reachability fallback for squash-merged baselines (#1222).

    Squash-merge lands an identical-tree commit on main under a NEW SHA,
    so the recorded ``provenance.git_commit`` (pre-squash PR tip) dangles
    while the tree stays reachable. The gate must accept on tree match.
    """

    def setUp(self) -> None:
        self._td = Path(tempfile.mkdtemp())
        self._shas = _init_repo(self._td)

        # A real-tree commit on main; its tree is the "squash-invariant" key.
        (self._td / "f.txt").write_text("payload\n", encoding="utf-8")
        _git(["add", "f.txt"], cwd=self._td)
        _git(["commit", "-m", "real-tree commit on main"], cwd=self._td)
        self._tree_main = _git(["rev-parse", "HEAD^{tree}"], cwd=self._td)

        # Dangling twin: same tree as main commit, different SHA, off main.
        self._twin = subprocess.run(
            ["git", "commit-tree", self._tree_main, "-p", self._shas["a"],
             "-m", "pre-squash twin"],
            cwd=self._td, check=True, text=True, stdout=subprocess.PIPE,
        ).stdout.strip()

        # A commit on a side branch with a tree NOT present on main.
        _git(["checkout", "-b", "prhead", self._shas["a"]], cwd=self._td)
        (self._td / "g.txt").write_text("only-on-prhead\n", encoding="utf-8")
        _git(["add", "g.txt"], cwd=self._td)
        _git(["commit", "-m", "side-branch real-tree commit"], cwd=self._td)
        self._prhead = _git(["rev-parse", "HEAD"], cwd=self._td)
        self._tree_prhead = _git(["rev-parse", "HEAD^{tree}"], cwd=self._td)
        _git(["checkout", "main"], cwd=self._td)

        self._baseline = self._td / "baseline.aggregate.json"

    def test_dangling_twin_in_db_passes_via_tree(self) -> None:
        # git_commit present but not ancestor of main; tree is on main.
        _write_baseline(
            self._baseline,
            self._twin[:12],
            run_manifest_sha=None,
            provenance_tree=self._tree_main[:12],
        )
        code, msg = check(self._baseline, "main", None, repo_root=self._td)
        self.assertEqual(code, 0, msg)
        self.assertIn("squash-merge-invariant", msg)

    def test_absent_twin_commit_passes_via_tree(self) -> None:
        # Faithful CI repro: twin commit object is absent (sparse fetch),
        # only the tree survives on main. Must still pass.
        _write_baseline(
            self._baseline,
            "deadbeefcafe",
            run_manifest_sha=None,
            provenance_tree=self._tree_main[:12],
        )
        code, msg = check(self._baseline, "main", None, repo_root=self._td)
        self.assertEqual(code, 0, msg)
        self.assertIn("[OK]", msg)

    def test_tree_not_on_main_still_fails(self) -> None:
        _write_baseline(
            self._baseline,
            "deadbeefcafe",
            run_manifest_sha=None,
            provenance_tree=self._tree_prhead[:12],
        )
        code, msg = check(self._baseline, "main", None, repo_root=self._td)
        self.assertEqual(code, 1, msg)
        self.assertIn("not reachable", msg)

    def test_commit_ancestor_short_circuits_before_tree(self) -> None:
        # git_commit is a genuine ancestor of main — tier-1 wins even
        # though git_tree is also set.
        _write_baseline(
            self._baseline,
            self._shas["a"],
            run_manifest_sha=None,
            provenance_tree=self._tree_main[:12],
        )
        code, msg = check(self._baseline, "main", None, repo_root=self._td)
        self.assertEqual(code, 0, msg)
        self.assertNotIn("squash-merge-invariant", msg)

    def test_tree_escape_hatch_via_allow_equal_to(self) -> None:
        # In-flight: tree lives on the PR head ref but not yet on main.
        _write_baseline(
            self._baseline,
            "deadbeefcafe",
            run_manifest_sha=None,
            provenance_tree=self._tree_prhead[:12],
        )
        code, msg = check(
            self._baseline, "main", self._prhead, repo_root=self._td
        )
        self.assertEqual(code, 0, msg)
        self.assertIn("escape hatch", msg)

    def test_absent_commit_without_tree_keeps_object_db_error(self) -> None:
        # No git_tree to fall back on — legacy object-DB error preserved.
        _write_baseline(
            self._baseline, "deadbeefcafe", run_manifest_sha=None
        )
        code, msg = check(self._baseline, "main", None, repo_root=self._td)
        self.assertEqual(code, 1, msg)
        self.assertIn("does not exist in the git object database", msg)


class CheckBaselineProvenanceCli(unittest.TestCase):
    def setUp(self) -> None:
        self._td = Path(tempfile.mkdtemp())
        self._shas = _init_repo(self._td)
        self._baseline = self._td / "baseline.aggregate.json"

    def _invoke(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "check_baseline_provenance.py"),
                "--baseline", str(self._baseline),
                "--ref", "main",
                "--repo-root", str(self._td),
                *extra,
            ],
            capture_output=True,
            text=True,
        )

    def test_cli_exits_zero_for_ancestor(self) -> None:
        _write_baseline(self._baseline, self._shas["a"])
        result = self._invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[OK]", result.stdout)

    def test_cli_exits_one_for_unreachable(self) -> None:
        _write_baseline(self._baseline, self._shas["c"])
        result = self._invoke()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("not reachable", result.stderr)

    def test_cli_allow_equal_to_lets_pr_commit_pass(self) -> None:
        _write_baseline(self._baseline, self._shas["c"])
        result = self._invoke("--allow-equal-to", self._shas["c"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("escape hatch", result.stdout)

    def test_cli_exits_two_for_mismatch(self) -> None:
        _write_baseline(
            self._baseline,
            self._shas["a"],
            run_manifest_sha=self._shas["b"],
        )
        result = self._invoke()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("mismatch", result.stderr)


if __name__ == "__main__":
    unittest.main()
