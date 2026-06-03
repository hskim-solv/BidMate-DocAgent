"""X task-pool E3b — active-surface coordination correctness (ADR 0095 PR-E3b).

E3a built the two-root threading + the ``lease_id`` parameter conduit but shipped them DARK
(every new param ``None``-defaults; X>1-only logic gated on ``effective_repo_root != repo_root``).
E3b wires the FOUR active-surface correctness behaviours, STILL DARK — the observable invariant
stays **X=1 byte-identical (ADR 0001)** and the X>1 fan-out RuntimeError / E2 dark clamp are
untouched, so these are FUNCTION-level tests (you cannot drive X>1 end-to-end — it RuntimeErrors):

1. cycle-worktree branch/issue inheritance — write_active_start/loop derive the PARENT issue when
   handed the parent branch/issue (the override path) even though the checkout branch is a
   ``agent/<task>/cycle`` worktree branch that carries no issue. Default (no params) is unchanged.
2. overlap-preflight cycle-worktree exclusion — a child cycle worktree of the run's own task is
   NOT flagged as a competing owner of the inherited issue; a genuine other-issue worktree still is.
3. claim_disjoint REJECT — ``reject_on_overlap=True`` makes the disjoint check first-writer-wins
   (decision inside the flock, no write for the loser, durable file holds the FIRST writer).
   ``reject_on_overlap=False`` (default) keeps the unconditional-write report-only path.
4. lease_id VALUE injection — write_active_loop RETURNS its task-scoped lease_id on
   ActiveLoopResult WITHOUT serializing it into auto_loop_state.json / the cycle dict.

Payloads are pinned + offline (no external model / network).
"""
from __future__ import annotations

import concurrent.futures
import json
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest

from scripts import agent_loop

from tests.test_agent_loop import (
    _append_ready_task,
    _clear_overlap_report,
    _patch_auto_loop_inner,
    _write_repo,
)


FIXED_NOW = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)


def _leases_path(repo_root: Path) -> Path:
    return agent_loop._active_path(agent_loop.DEFAULT_ACTIVE_LEASES, repo_root=repo_root)


def _stub_write_active_loop_offline(monkeypatch, *, current_branch: str) -> None:
    """Stub git / PR / overlap / privacy readers so write_active_loop runs fully offline.

    ``_current_branch`` returns ``current_branch`` (used to simulate running inside a cycle
    worktree whose branch is ``agent/<task>/cycle``). build_overlap_preflight is stubbed to a
    clear report so issue derivation is the ONLY thing under test. Mirrors
    ``_e3a_stub_write_active_loop_env`` in test_agent_loop.py.
    """
    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: current_branch)
    monkeypatch.setattr(agent_loop, "_open_pr_for_branch", lambda *a, **k: None)
    monkeypatch.setattr(
        agent_loop, "build_overlap_preflight",
        lambda issue, branch, repo_root, **kw: _clear_overlap_report(issue, branch),
    )
    monkeypatch.setattr(agent_loop, "audit_privacy_output", lambda *args, **kwargs: [])


# ---------------------------------------------------------------------------
# Work-item 1: cycle-worktree branch/issue inheritance
# ---------------------------------------------------------------------------


def test_e3b_inheritance_loop_derives_parent_issue_in_cycle_worktree(monkeypatch, tmp_path: Path) -> None:
    """X>1 inheritance: checkout branch is ``agent/T-.../cycle`` (no issue), but passing the parent
    branch/issue (the existing --issue/--branch override path) makes write_active_loop derive the
    parent issue — no "could not derive issue" blocker, leases.json carries the parent issue."""
    repo = _write_repo(tmp_path)
    cycle_branch = "agent/T-2026-0032/cycle"
    _stub_write_active_loop_offline(monkeypatch, current_branch=cycle_branch)

    result = agent_loop.write_active_loop(
        changed_files=["docs/operations/active-agent-loop.md"],
        repo_root=repo,
        # The driver passes the captured parent branch/issue ONLY at X>1.
        issue="1827",
        branch="feat/issue-1827-e3b",
    )

    # The inherited parent issue was derived; the "could not derive issue" block did NOT fire.
    assert not any("could not derive issue" in b for b in result.blockers), result.blockers
    leases = json.loads(result.leases_path.read_text(encoding="utf-8"))
    assert any(lease.get("issue") == "1827" for lease in leases["leases"]), leases
    # At X=1 (no coordination_root) lease_id is None (conduit inactive, first-match path).
    # lease_id is populated only at X>1 (coord != repo_root) or when reject_on_overlap=True.
    assert result.lease_id is None


def test_e3b_inheritance_default_no_params_blocks_on_cycle_branch_byte_identical(monkeypatch, tmp_path: Path) -> None:
    """Byte-identity: WITHOUT the inheritance params (X=1 path) the SAME cycle-branch checkout
    derives NO issue (``agent/.../cycle`` carries none) and the unchanged
    _current_branch/_issue_from_branch derivation blocks with "could not derive issue" — proving
    the inheritance is opt-in and the default derivation is untouched."""
    repo = _write_repo(tmp_path)
    cycle_branch = "agent/T-2026-0032/cycle"
    _stub_write_active_loop_offline(monkeypatch, current_branch=cycle_branch)

    result = agent_loop.write_active_loop(
        changed_files=["docs/operations/active-agent-loop.md"],
        repo_root=repo,
    )

    # No --issue/--branch override -> the cycle branch yields no issue -> the legacy block fires.
    assert any("could not derive issue" in b for b in result.blockers), result.blockers
    # At X=1 (no coordination_root, no reject_on_overlap) lease_id is None — conduit inactive.
    assert result.lease_id is None


def test_e3b_inheritance_start_derives_parent_issue_in_cycle_worktree(monkeypatch, tmp_path: Path) -> None:
    """write_active_start mirrors write_active_loop: handed the parent branch/issue while the
    checkout is a cycle-worktree branch, it derives the parent issue and threads it into the nested
    active-loop (the issue shows up in the start report inputs + leases.json)."""
    repo = _write_repo(tmp_path)
    cycle_branch = "agent/T-2026-0032/cycle"
    _stub_write_active_loop_offline(monkeypatch, current_branch=cycle_branch)

    result = agent_loop.write_active_start(
        changed_files=["docs/operations/active-agent-loop.md"],
        repo_root=repo,
        issue="1827",
        branch="feat/issue-1827-e3b",
    )

    assert not any("could not derive issue" in b for b in result.active_loop.blockers), result.active_loop.blockers
    leases = json.loads(result.active_loop.leases_path.read_text(encoding="utf-8"))
    assert any(lease.get("issue") == "1827" for lease in leases["leases"]), leases


# ---------------------------------------------------------------------------
# Work-item 2: overlap-preflight cycle-worktree exclusion
# ---------------------------------------------------------------------------


def _stub_overlap_readers(monkeypatch, repo: Path, *, branch: str, worktrees) -> None:
    """Stub all build_overlap_preflight readers offline with an explicit worktree list."""
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: branch)
    monkeypatch.setattr(agent_loop, "_git_ref", lambda ref, *, repo_root: "abc1234")
    monkeypatch.setattr(agent_loop, "_git_is_ancestor", lambda *a, **k: True)
    monkeypatch.setattr(agent_loop, "_git_worktree_entries", lambda repo_root: worktrees)
    monkeypatch.setattr(agent_loop, "_local_issue_branches", lambda repo_root: {"1827": {branch}})
    monkeypatch.setattr(agent_loop, "_remote_issue_branches", lambda selected_issue, *, repo_root: set())
    monkeypatch.setattr(agent_loop, "_open_pr_items", lambda *, repo_root: [])
    monkeypatch.setattr(agent_loop, "_branch_pr_items", lambda selected_branch, *, repo_root: [])
    monkeypatch.setattr(
        agent_loop, "_issue_info",
        lambda selected_issue, *, repo_root: {"number": int(selected_issue), "title": "x", "state": "OPEN", "url": "u"},
    )


def test_e3b_overlap_preflight_excludes_own_cycle_worktree_by_branch(monkeypatch, tmp_path: Path) -> None:
    """A child cycle worktree (branch ``agent/T-.../cycle``) of the run's own task is NOT flagged as
    a competing owner of the inherited issue — even if its entry carried the inherited issue."""
    repo = _write_repo(tmp_path)
    branch = "feat/issue-1827-e3b"
    coord = repo
    cycle_path = coord / ".claude" / "worktrees" / "T-2026-0032-cycle"
    worktrees = (
        agent_loop.WorktreeSnapshot(path=str(coord), branch=branch, head="abc1234"),
        # Cycle worktree: branch shape ``agent/<task>/cycle``. Even if some path also makes its
        # issue resolve to 1827 (the inheritance scenario), the cycle-branch shape excludes it.
        agent_loop.WorktreeSnapshot(path=str(cycle_path), branch="agent/T-2026-0032/cycle", head="def5678"),
    )
    _stub_overlap_readers(monkeypatch, repo, branch=branch, worktrees=worktrees)

    report = agent_loop.build_overlap_preflight(issue="1827", branch=branch, repo_root=repo)

    assert report.result == "clear", report.blockers
    assert not any("another worktree" in b for b in report.blockers)
    assert any("no other worktree owns the target issue" in e for e in report.evidence)


def test_e3b_overlap_preflight_non_cycle_branch_under_worktrees_dir_is_still_flagged(monkeypatch, tmp_path: Path) -> None:
    """HIGH-1 regression guard: a worktree living under ``.claude/worktrees/`` but with a
    NON-cycle branch (e.g. an integration worktree ``feature/T-…-integration``) that shares the
    same issue MUST still be flagged as a competing owner.  The original path-based exclusion
    incorrectly suppressed these; after the fix ONLY ``agent/<task>/cycle`` branches are excluded."""
    repo = _write_repo(tmp_path)
    branch = "feat/issue-1827-e3b"
    coord = repo
    # Integration worktree: same issue, non-cycle branch, lives under coord's worktrees dir.
    integration_path = coord / ".claude" / "worktrees" / "T-2026-0030-integration"
    worktrees = (
        agent_loop.WorktreeSnapshot(path=str(coord), branch=branch, head="abc1234"),
        agent_loop.WorktreeSnapshot(
            path=str(integration_path),
            branch="feature/T-2026-0030-integration",  # NOT a cycle branch
            head="def5678",
        ),
    )
    # Stub issue derivation so the integration worktree's branch resolves to issue 1827.
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: branch)
    monkeypatch.setattr(agent_loop, "_git_ref", lambda ref, *, repo_root: "abc1234")
    monkeypatch.setattr(agent_loop, "_git_is_ancestor", lambda *a, **k: True)
    monkeypatch.setattr(agent_loop, "_git_worktree_entries", lambda repo_root: worktrees)
    # integration branch has no ``issue-N`` slug; mimic the scenario by overriding
    # _issue_from_branch so it returns "1827" for the integration branch too.
    _real_issue_from_branch = agent_loop._issue_from_branch

    def _patched_issue_from_branch(branch_name: str) -> str | None:
        if "T-2026-0030-integration" in branch_name:
            return "1827"
        return _real_issue_from_branch(branch_name)

    monkeypatch.setattr(agent_loop, "_issue_from_branch", _patched_issue_from_branch)
    monkeypatch.setattr(agent_loop, "_local_issue_branches", lambda repo_root: {"1827": {branch}})
    monkeypatch.setattr(agent_loop, "_remote_issue_branches", lambda selected_issue, *, repo_root: set())
    monkeypatch.setattr(agent_loop, "_open_pr_items", lambda *, repo_root: [])
    monkeypatch.setattr(agent_loop, "_branch_pr_items", lambda selected_branch, *, repo_root: [])
    monkeypatch.setattr(
        agent_loop, "_issue_info",
        lambda selected_issue, *, repo_root: {"number": int(selected_issue), "title": "x", "state": "OPEN", "url": "u"},
    )

    report = agent_loop.build_overlap_preflight(issue="1827", branch=branch, repo_root=repo)

    # The integration worktree is a genuine competing owner; it MUST still be flagged.
    assert report.result == "blocked", f"expected blocked, got {report.result!r}: {report.blockers}"
    assert any("another worktree already owns an issue branch" in b for b in report.blockers)


def test_e3b_overlap_preflight_still_flags_genuine_other_issue_worktree(monkeypatch, tmp_path: Path) -> None:
    """A genuine OTHER worktree owning the same issue (NOT a cycle worktree, NOT under coord's
    worktrees dir) is STILL flagged competing — the exclusion is surgical, not a blanket pass."""
    repo = _write_repo(tmp_path)
    branch = "feat/issue-1827-e3b"
    other = tmp_path / "sibling-checkout"
    worktrees = (
        agent_loop.WorktreeSnapshot(path=str(repo), branch=branch, head="abc1234"),
        agent_loop.WorktreeSnapshot(path=str(other), branch="docs/issue-1827-existing", head="def5678"),
    )
    _stub_overlap_readers(monkeypatch, repo, branch=branch, worktrees=worktrees)

    report = agent_loop.build_overlap_preflight(issue="1827", branch=branch, repo_root=repo)

    assert report.result == "blocked"
    assert any("another worktree already owns an issue branch" in b for b in report.blockers)


def test_e3b_is_task_cycle_branch_recognises_only_cycle_branches() -> None:
    """The cycle-branch predicate matches ``agent/<task>/cycle`` (case-insensitive) and nothing
    else — neither issue branches nor the per-agent scratch branch."""
    assert agent_loop._is_task_cycle_branch("agent/T-2026-0032/cycle")
    assert agent_loop._is_task_cycle_branch("agent/t-2026-0032/CYCLE")
    assert not agent_loop._is_task_cycle_branch("feat/issue-1827-e3b")
    assert not agent_loop._is_task_cycle_branch("agent/T-2026-0032/codex-scratch")
    assert not agent_loop._is_task_cycle_branch(None)
    assert not agent_loop._is_task_cycle_branch("")


# ---------------------------------------------------------------------------
# HIGH-2: write_active_start REJECT at claim time (X>1 path)
# ---------------------------------------------------------------------------


def test_e3b_write_active_start_rejects_overlapping_second_cycle_claim(monkeypatch, tmp_path: Path) -> None:
    """HIGH-2: write_active_start accepts reject_on_overlap and forwards it to its nested
    write_active_loop claim.  When two cycles would claim the same files, the second call is
    rejected (overlap blocker, durable lease unchanged) rather than being silently written.

    Simulated by: seeding an existing durable overlapping lease directly, then calling
    write_active_start with reject_on_overlap=True and the SAME shared file — the nested
    write_active_loop must reject the claim and propagate the overlap blocker up to the
    ActiveStartResult."""
    repo = _write_repo(tmp_path, task_id="T-2026-9999")
    cycle_branch = "agent/T-2026-0032/cycle"
    _stub_write_active_loop_offline(monkeypatch, current_branch=cycle_branch)

    # Seed an existing ACTIVE write lease with the shared file so the second claimer sees overlap.
    leases_path = _leases_path(repo)
    leases_path.parent.mkdir(parents=True, exist_ok=True)
    future = agent_loop._isoformat(FIXED_NOW + agent_loop.timedelta(minutes=60))
    shared = "docs/operations/active-agent-loop.md"
    agent_loop._write_active_leases(
        leases_path,
        leases=[{
            "lease_id": "first-writer-lease",
            "status": "active",
            "lease_type": "write",
            "active_agent": None,
            "task_id": "T-2026-0001",
            "issue": "1827",
            "branch": "feat/issue-1827-e3b",
            "worktree": "../first-wt",
            "claimed_files": [shared],
            "expires_at": future,
        }],
        now=FIXED_NOW,
    )
    before_bytes = leases_path.read_bytes()

    # X>1-simulated call: pass reject_on_overlap=True (what run_one_task does via start_reject_kwargs).
    result = agent_loop.write_active_start(
        changed_files=[shared],
        repo_root=repo,
        issue="1827",
        branch="feat/issue-1827-e3b",
        reject_on_overlap=True,
    )

    # The nested write_active_loop must have REJECTed: overlap blocker propagated upward.
    loop_blockers = result.active_loop.blockers
    assert any("overlap" in b for b in loop_blockers), (
        f"expected overlap blocker from nested write_active_loop, got: {loop_blockers}"
    )
    # The durable lease file is byte-identical to the first writer's state (no second write).
    assert leases_path.read_bytes() == before_bytes, "second cycle must not have overwritten the first writer's lease"


# ---------------------------------------------------------------------------
# Work-item 3: claim_disjoint REJECT (first-writer-wins)
# ---------------------------------------------------------------------------


def test_e3b_claim_disjoint_reject_default_false_is_unconditional_write(tmp_path: Path) -> None:
    """Byte-identity pin: reject_on_overlap defaults False -> the overlapping claim is REPORTED but
    STILL written (the legacy report-only path). Mirrors
    tests/test_lease_claim_disjoint_regression.py::test_same_file_overlap_reports_but_does_not_gate_write
    so an accidental flip of the default would be caught here too."""
    repo_root = tmp_path
    path = _leases_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    future = agent_loop._isoformat(FIXED_NOW + timedelta(minutes=60))
    shared = "src/shared.py"
    existing = {
        "lease_id": "foreign-overlap",
        "status": "active",
        "lease_type": "write",
        "active_agent": None,
        "task_id": "T-2026-9999",
        "issue": "9999",
        "branch": "feat/issue-9999-other",
        "worktree": "../other-wt",
        "claimed_files": [shared],
        "expires_at": future,
    }
    agent_loop._write_active_leases(path, leases=[existing], now=FIXED_NOW)

    payload, blockers, _ = agent_loop.LeaseManager(path, repo_root=repo_root).claim_disjoint(
        task_id="T-2026-0001",
        issue="1827",
        branch="feat/issue-1827-e3b",
        changed_files=[shared],
        lease_ttl_minutes=30,
        now=FIXED_NOW,
    )

    # Reported AND written (report-not-gate).
    assert any("overlap" in b for b in blockers)
    items = agent_loop._load_active_leases(path)
    task_ids = {str(i.get("task_id")) for i in items}
    assert {"T-2026-9999", "T-2026-0001"}.issubset(task_ids)
    # The returned payload mirrors the durable on-disk leases (write happened).
    assert payload["leases"] == [agent_loop._sanitize_json_value(i) for i in items]


def test_e3b_claim_disjoint_reject_true_does_not_write_and_returns_existing(tmp_path: Path) -> None:
    """reject_on_overlap=True + overlap: the new lease is NOT written, the EXISTING durable payload
    is returned, and the on-disk file is byte-identical to the pre-claim state (first-writer-wins)."""
    repo_root = tmp_path
    path = _leases_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    future = agent_loop._isoformat(FIXED_NOW + timedelta(minutes=60))
    shared = "src/shared.py"
    existing = {
        "lease_id": "winner-overlap",
        "status": "active",
        "lease_type": "write",
        "active_agent": None,
        "task_id": "T-2026-9999",
        "issue": "9999",
        "branch": "feat/issue-9999-other",
        "worktree": "../other-wt",
        "claimed_files": [shared],
        "expires_at": future,
    }
    agent_loop._write_active_leases(path, leases=[existing], now=FIXED_NOW)
    before_bytes = path.read_bytes()
    seeded_existing = agent_loop._load_active_leases(path)

    payload, blockers, _ = agent_loop.LeaseManager(path, repo_root=repo_root).claim_disjoint(
        task_id="T-2026-0001",
        issue="1827",
        branch="feat/issue-1827-e3b",
        changed_files=[shared],
        lease_ttl_minutes=30,
        now=FIXED_NOW,
        reject_on_overlap=True,
    )

    # REJECT: overlap blocker present, the loser's lease was NOT written.
    assert any("overlap" in b for b in blockers)
    items = agent_loop._load_active_leases(path)
    task_ids = {str(i.get("task_id")) for i in items}
    assert "T-2026-9999" in task_ids, "the first writer (winner) must remain"
    assert "T-2026-0001" not in task_ids, "the rejected loser must NOT have been written"
    # The durable file is byte-identical to the first writer's state.
    assert path.read_bytes() == before_bytes
    # The returned payload mirrors the EXISTING durable leases (the winner), not the loser's build.
    assert payload["leases"] == [agent_loop._sanitize_json_value(i) for i in seeded_existing]


def test_e3b_claim_disjoint_reject_true_no_overlap_still_writes(tmp_path: Path) -> None:
    """reject_on_overlap=True with NO overlap: the disjoint claim is written normally (REJECT only
    fires on an actual overlap; a clean disjoint claim always lands)."""
    repo_root = tmp_path
    path = _leases_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    future = agent_loop._isoformat(FIXED_NOW + timedelta(minutes=60))
    existing = {
        "lease_id": "foreign-disjoint",
        "status": "active",
        "lease_type": "write",
        "active_agent": None,
        "task_id": "T-2026-9999",
        "issue": "9999",
        "branch": "feat/issue-9999-other",
        "worktree": "../other-wt",
        "claimed_files": ["other/file.py"],
        "expires_at": future,
    }
    agent_loop._write_active_leases(path, leases=[existing], now=FIXED_NOW)

    _payload, blockers, _ = agent_loop.LeaseManager(path, repo_root=repo_root).claim_disjoint(
        task_id="T-2026-0001",
        issue="1827",
        branch="feat/issue-1827-e3b",
        changed_files=["scripts/agent_loop.py"],
        lease_ttl_minutes=30,
        now=FIXED_NOW,
        reject_on_overlap=True,
    )

    assert not any("overlap" in b for b in blockers)
    items = agent_loop._load_active_leases(path)
    task_ids = {str(i.get("task_id")) for i in items}
    assert {"T-2026-9999", "T-2026-0001"}.issubset(task_ids)


@pytest.mark.skipif(agent_loop.fcntl is None, reason="flock requires POSIX fcntl")
def test_e3b_claim_disjoint_reject_first_writer_wins_under_contention(tmp_path: Path) -> None:
    """Barrier contention harness (template: tests/test_lease_claim_disjoint_regression.py::
    test_mutual_exclusion_max_occupancy_is_one): TWO claimers race for the SAME file with
    reject_on_overlap=True. The flock serializes them, so EXACTLY ONE write lands (the first writer),
    the loser gets an overlap blocker, and the durable file holds only the FIRST writer's claim.
    The reject DECISION is inside the flock, so two losers can never both read "no overlap" and both
    write."""
    repo_root = tmp_path
    path = _leases_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    shared = "src/contended.py"

    barrier = threading.Barrier(2)
    specs = [
        {"task_id": "T-2026-0001", "issue": "1827", "branch": "feat/issue-1827-a"},
        {"task_id": "T-2026-0002", "issue": "1828", "branch": "feat/issue-1828-b"},
    ]
    results: dict[str, list[str]] = {}
    results_lock = threading.Lock()

    def _claim(spec: dict[str, object]) -> None:
        barrier.wait()  # maximize overlap on the critical section
        _payload, blockers, _ = agent_loop.LeaseManager(path, repo_root=repo_root).claim_disjoint(
            task_id=cast(str, spec["task_id"]),
            issue=cast(str, spec["issue"]),
            branch=cast(str, spec["branch"]),
            changed_files=[shared],
            lease_ttl_minutes=30,
            now=FIXED_NOW,
            reject_on_overlap=True,
        )
        with results_lock:
            results[cast(str, spec["task_id"])] = list(blockers)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_claim, spec) for spec in specs]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    items = agent_loop._load_active_leases(path)
    write_task_ids = {
        str(i.get("task_id"))
        for i in items
        if i.get("lease_type") == "write" and i.get("status") == "active"
    }
    # EXACTLY one of the two contenders landed a write lease — first-writer-wins.
    landed = write_task_ids & {"T-2026-0001", "T-2026-0002"}
    assert len(landed) == 1, f"exactly one writer must win, got {landed!r}"
    # The loser observed an overlap blocker.
    loser = ({"T-2026-0001", "T-2026-0002"} - landed).pop()
    assert any("overlap" in b for b in results[loser]), f"loser {loser} must see an overlap blocker"
    # The durable file is disjoint (only the winner's claim on the shared file).
    assert agent_loop.assert_claimed_files_disjoint(items) == []


# ---------------------------------------------------------------------------
# Work-item 4: lease_id VALUE injection (returned, NOT serialized)
# ---------------------------------------------------------------------------


def test_e3b_write_active_loop_returns_task_scoped_lease_id(monkeypatch, tmp_path: Path) -> None:
    """write_active_loop returns its task-scoped lease_id ONLY at X>1 (coord != repo_root).

    Two sub-cases:
    a) X>1 (coordination_root != repo_root): lease_id == the expected slug, matching the durable
       lease id that _build_active_leases minted inside claim_disjoint.
    b) X=1 (no coordination_root / coord == repo_root): lease_id is None (conduit inactive,
       first-match path).  Separately pinned by test_e3b_write_active_loop_x1_lease_id_is_none.
    """
    task_id = "T-2026-9999"  # the id _write_repo seeds into the fixture queue
    repo = _write_repo(tmp_path, task_id=task_id)
    # Use a separate coordination dir to trigger coord != repo_root (X>1 simulation).
    coord_dir = tmp_path / "coord"
    coord_dir.mkdir()
    branch = "feat/issue-1827-e3b"
    _stub_write_active_loop_offline(monkeypatch, current_branch=branch)

    result = agent_loop.write_active_loop(
        task_id=task_id,
        changed_files=["docs/operations/active-agent-loop.md"],
        repo_root=repo,
        coordination_root=coord_dir,
    )

    expected = agent_loop._task_scoped_lease_id(task_id, "1827", branch)
    assert result.lease_id == expected, f"expected {expected!r}, got {result.lease_id!r}"
    # The returned id IS the durable lease's id (single source of truth).
    leases = json.loads(result.leases_path.read_text(encoding="utf-8"))
    assert any(lease.get("lease_id") == expected for lease in leases["leases"]), leases


def test_e3b_lease_id_not_serialized_into_auto_loop_state(monkeypatch, tmp_path: Path) -> None:
    """The new lease_id (and parent_branch/issue) MUST NOT leak into auto_loop_state.json or the
    cycle dict — internal transfer only. A full X=1 driver run's state file is scanned for the
    task-scoped lease slug; it must be ABSENT (the cycle records only decision + report_path)."""
    repo = _write_repo(tmp_path, task_id="T-2026-1001", title="First")
    _append_ready_task(repo, "T-2026-1002", "Second")
    active_dir = repo / "reports" / "agent_loop" / "active"
    _patch_auto_loop_inner(monkeypatch, active_dir)

    agent_loop.write_active_auto_loop(
        max_iterations=2, execute_runner=True, execute_ship=False, repo_root=repo, task_pool=1
    )

    state_text = (active_dir / "auto_loop_state.json").read_text(encoding="utf-8")
    state = json.loads(state_text)
    # No "lease_id" key anywhere in the serialized cycle ledger.
    assert '"lease_id"' not in state_text, "lease_id must not be serialized into auto_loop_state.json"
    # No "parent_branch" / "parent_issue" key either.
    assert '"parent_branch"' not in state_text
    assert '"parent_issue"' not in state_text
    for cyc in state.get("cycles", []):
        assert "lease_id" not in cyc
        assert "parent_branch" not in cyc
        assert "parent_issue" not in cyc


def test_e3b_lease_id_field_defaults_none_and_is_additive(tmp_path: Path) -> None:
    """ActiveLoopResult.lease_id is ADDITIVE: positional construction (legacy call shape) still
    works and defaults to None — so the new field cannot break existing constructors."""
    legacy = agent_loop.ActiveLoopResult(
        tmp_path / "registry.json",
        tmp_path / "leases.json",
        tmp_path / "events.jsonl",
        tmp_path / "assignments",
        tmp_path / "report.md",
        "executed",
        (),
        (),
    )
    assert legacy.lease_id is None


def test_e3b_write_active_loop_x1_lease_id_is_none(monkeypatch, tmp_path: Path) -> None:
    """X=1 contract: write_active_loop WITHOUT coordination_root (coord == repo_root) and WITHOUT
    reject_on_overlap returns lease_id=None — the conduit is inactive at X=1 (first-match path).
    This pins the in-memory invariant; serialization (auto_loop_state.json) is orthogonal and
    already tested by test_e3b_lease_id_not_serialized_into_auto_loop_state."""
    task_id = "T-2026-9999"
    repo = _write_repo(tmp_path, task_id=task_id)
    branch = "feat/issue-1827-e3b"
    _stub_write_active_loop_offline(monkeypatch, current_branch=branch)

    result = agent_loop.write_active_loop(
        task_id=task_id,
        changed_files=["docs/operations/active-agent-loop.md"],
        repo_root=repo,
        # NO coordination_root -> coord == repo_root, NO reject_on_overlap (default False)
        # -> lease_id stays None (conduit inactive).
    )

    assert result.lease_id is None, (
        f"X=1 normal path must return lease_id=None, got {result.lease_id!r}"
    )


# ---------------------------------------------------------------------------
# Mutation verification: revert a gate -> a test flips (proves the gate is load-bearing)
# ---------------------------------------------------------------------------


def test_e3b_reject_mutation_guard_default_false_would_write(tmp_path: Path) -> None:
    """MUTATION-VERIFY (work-item 3 gate): this test asserts the EXACT behavioural difference the
    ``reject_on_overlap`` gate controls. If reject_on_overlap defaulted True (the gate reverted),
    the no-flag call in test_e3b_claim_disjoint_reject_default_false_is_unconditional_write would
    stop writing the loser and that test would FLIP. Here we pin both sides in ONE test so the
    flip is unambiguous: same inputs, the ONLY difference is the flag, and the on-disk result
    differs (write vs no-write)."""
    repo_root = tmp_path
    future = agent_loop._isoformat(FIXED_NOW + timedelta(minutes=60))
    shared = "src/shared.py"

    def _seed(into: Path) -> None:
        into.parent.mkdir(parents=True, exist_ok=True)
        agent_loop._write_active_leases(
            into,
            leases=[{
                "lease_id": "foreign-overlap",
                "status": "active",
                "lease_type": "write",
                "active_agent": None,
                "task_id": "T-2026-9999",
                "issue": "9999",
                "branch": "feat/issue-9999-other",
                "worktree": "../other-wt",
                "claimed_files": [shared],
                "expires_at": future,
            }],
            now=FIXED_NOW,
        )

    report_path = repo_root / "report" / "leases.json"
    reject_path = repo_root / "reject" / "leases.json"
    _seed(report_path)
    _seed(reject_path)

    agent_loop.LeaseManager(report_path, repo_root=repo_root / "report").claim_disjoint(
        task_id="T-2026-0001", issue="1827", branch="feat/issue-1827-e3b",
        changed_files=[shared], lease_ttl_minutes=30, now=FIXED_NOW, reject_on_overlap=False,
    )
    agent_loop.LeaseManager(reject_path, repo_root=repo_root / "reject").claim_disjoint(
        task_id="T-2026-0001", issue="1827", branch="feat/issue-1827-e3b",
        changed_files=[shared], lease_ttl_minutes=30, now=FIXED_NOW, reject_on_overlap=True,
    )

    report_ids = {str(i.get("task_id")) for i in agent_loop._load_active_leases(report_path)}
    reject_ids = {str(i.get("task_id")) for i in agent_loop._load_active_leases(reject_path)}
    # reject_on_overlap=False WROTE the loser; reject_on_overlap=True did NOT — the gate flips behaviour.
    assert "T-2026-0001" in report_ids, "False (default) must write the overlapping claim"
    assert "T-2026-0001" not in reject_ids, "True must reject the overlapping claim"
