"""Guards for parallel agent worktree isolation + exit hygiene (issue #1719).

P2.2's parallel run failed two ways: a write lane edited the *parent repo* instead
of its isolated scratch worktree (changes leaked onto main), and an aborted lane's
uncommitted scratch work was destroyed by the ``--force`` teardown. These tests pin
the four guards that close those holes:

- ``assert_worktree_confinement`` — the lane's git top-level is its assigned scratch
  worktree and is not the parent repo (guards 1+2).
- ``assert_claimed_files_disjoint`` — concurrent write leases claim disjoint files (guard 3).
- ``commit_scratch_worktree_before_exit`` + ``teardown_scratch_worktree`` wiring —
  uncommitted scratch state is pinned to a commit before destructive removal (guard 4).
"""

from __future__ import annotations

from pathlib import Path
import subprocess

from scripts import agent_loop


def _proc(stdout: str = "", *, returncode: int = 0, stderr: str = "") -> "subprocess.CompletedProcess[str]":
    return subprocess.CompletedProcess(["git"], returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# Guards 1+2: assert_worktree_confinement
# ---------------------------------------------------------------------------


def test_confinement_passes_when_toplevel_matches_assigned_scratch(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch-wt"
    repo = tmp_path / "parent-repo"

    def runner(cmd):
        return _proc(str(scratch) + "\n")

    assert agent_loop.assert_worktree_confinement(scratch, repo_root=repo, runner=runner) == []


def test_confinement_blocks_when_lane_resolves_to_parent_repo(tmp_path: Path) -> None:
    # The exact #1719 failure: a lane assigned a scratch path actually runs in the
    # parent checkout, so rev-parse resolves the top-level to the parent repo root.
    scratch = tmp_path / "scratch-wt"
    repo = tmp_path / "parent-repo"

    def runner(cmd):
        return _proc(str(repo) + "\n")

    blockers = agent_loop.assert_worktree_confinement(scratch, repo_root=repo, runner=runner)
    assert any("not inside its assigned scratch worktree" in b for b in blockers)
    assert any("parent-repo write ban" in b for b in blockers)


def test_confinement_blocks_unrelated_toplevel_without_parent_ban(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch-wt"
    repo = tmp_path / "parent-repo"
    other = tmp_path / "somewhere-else"

    def runner(cmd):
        return _proc(str(other) + "\n")

    blockers = agent_loop.assert_worktree_confinement(scratch, repo_root=repo, runner=runner)
    assert any("not inside its assigned scratch worktree" in b for b in blockers)
    # top-level is not the parent repo, so the parent-repo ban must NOT fire.
    assert not any("parent-repo write ban" in b for b in blockers)


def test_confinement_fail_closed_when_git_errors(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch-wt"
    repo = tmp_path / "parent-repo"

    def runner(cmd):
        return _proc("", returncode=128, stderr="fatal: not a git repository\n")

    blockers = agent_loop.assert_worktree_confinement(scratch, repo_root=repo, runner=runner)
    assert len(blockers) == 1
    assert "could not resolve scratch worktree top-level" in blockers[0]


# ---------------------------------------------------------------------------
# Guard 3: assert_claimed_files_disjoint
# ---------------------------------------------------------------------------


def _write_lease(
    lease_id: str,
    claimed: list[str],
    *,
    status: str = "active",
    lease_type: str = "write",
) -> dict[str, object]:
    return {
        "lease_id": lease_id,
        "lease_type": lease_type,
        "status": status,
        "claimed_files": claimed,
    }


def test_disjoint_passes_for_non_overlapping_write_leases() -> None:
    leases = [_write_lease("L1", ["rag_core.py"]), _write_lease("L2", ["rag_answer.py"])]
    assert agent_loop.assert_claimed_files_disjoint(leases) == []


def test_disjoint_blocks_overlapping_write_leases() -> None:
    leases = [
        _write_lease("L1", ["rag_core.py", "shared.py"]),
        _write_lease("L2", ["shared.py"]),
    ]
    blockers = agent_loop.assert_claimed_files_disjoint(leases)
    assert len(blockers) == 1
    assert "L1" in blockers[0] and "L2" in blockers[0]
    assert "shared.py" in blockers[0]


def test_disjoint_single_write_lease_is_trivially_ok() -> None:
    assert agent_loop.assert_claimed_files_disjoint([_write_lease("L1", ["rag_core.py"])]) == []


def test_disjoint_ignores_non_write_and_inactive_leases() -> None:
    leases = [
        _write_lease("R1", ["shared.py"], lease_type="read"),
        _write_lease("W-done", ["shared.py"], status="released"),
        _write_lease("W1", ["shared.py"]),
    ]
    # Only one *active write* lease claims shared.py -> no overlap.
    assert agent_loop.assert_claimed_files_disjoint(leases) == []


def test_disjoint_excludes_shared_context_only_files() -> None:
    queue = agent_loop.QUEUE_PATH.as_posix()
    leases = [
        _write_lease("L1", [queue, "docs/plans/p.md"]),
        _write_lease("L2", [queue, "reports/agent_loop/x.md"]),
    ]
    # Coordination files are shared across lanes by design -> never an overlap conflict.
    assert agent_loop.assert_claimed_files_disjoint(leases) == []


# ---------------------------------------------------------------------------
# Guard 4 (exit hygiene): commit_scratch_worktree_before_exit + teardown wiring
# ---------------------------------------------------------------------------


def test_exit_hygiene_noop_when_scratch_missing(tmp_path: Path) -> None:
    committed, warnings = agent_loop.commit_scratch_worktree_before_exit(tmp_path / "gone")
    assert committed is False
    assert warnings == []


def test_exit_hygiene_noop_when_tree_clean(tmp_path: Path) -> None:
    def runner(cmd):
        return _proc("")  # `status --porcelain` empty == clean

    committed, warnings = agent_loop.commit_scratch_worktree_before_exit(tmp_path, runner=runner)
    assert committed is False
    assert warnings == []


def test_exit_hygiene_commits_dirty_tree(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(cmd):
        calls.append(cmd)
        if "status" in cmd:
            return _proc(" M scripts/agent_loop.py\n")
        return _proc("")  # add + commit succeed

    committed, warnings = agent_loop.commit_scratch_worktree_before_exit(tmp_path, runner=runner)
    assert committed is True
    assert warnings == []
    assert any("add" in c for c in calls)
    assert any("commit" in c and "--no-verify" in c for c in calls)


def test_exit_hygiene_warns_when_commit_fails(tmp_path: Path) -> None:
    def runner(cmd):
        if "status" in cmd:
            return _proc(" M scripts/agent_loop.py\n")
        if "commit" in cmd:
            return _proc("", returncode=1, stderr="nothing to commit\n")
        return _proc("")  # add ok

    committed, warnings = agent_loop.commit_scratch_worktree_before_exit(tmp_path, runner=runner)
    assert committed is False
    assert any("commit failed" in w for w in warnings)


def test_exit_hygiene_warns_when_status_unreadable(tmp_path: Path) -> None:
    def runner(cmd):
        return _proc("", returncode=128, stderr="fatal\n")

    committed, warnings = agent_loop.commit_scratch_worktree_before_exit(tmp_path, runner=runner)
    assert committed is False
    assert any("could not read scratch worktree status" in w for w in warnings)


def test_teardown_commits_dirty_scratch_before_removal(tmp_path: Path) -> None:
    # Wiring: teardown must pin uncommitted scratch state to a commit before the
    # destructive `worktree remove --force` (issue #1719). Make the computed scratch
    # path exist + report dirty, and assert the hygiene-commit warning surfaces.
    path, branch = agent_loop._scratch_worktree_paths("T-2026-1719", "codex", repo_root=tmp_path)
    path.mkdir(parents=True, exist_ok=True)

    def runner(cmd):
        if "status" in cmd:
            return _proc(" M scripts/agent_loop.py\n")
        return _proc("")  # add / commit / worktree remove / branch delete all succeed

    warnings = agent_loop.teardown_scratch_worktree(
        "T-2026-1719", "codex", repo_root=tmp_path, runner=runner
    )
    assert any("committed uncommitted scratch changes" in w and branch in w for w in warnings)
