"""LeaseManager.claim_disjoint transactional-claim regression (issue #1780, ADR 0094 PR-B).

``agent_loop.LeaseManager`` is the substrate brick that runs the lease
read -> disjoint-check -> write as ONE ``fcntl.flock(LOCK_EX)`` critical
section, closing the ``assert_claimed_files_disjoint`` snapshot TOCTOU (ADR
0094 Context). The senior contract this guards:

* **Byte-identity (ADR 0001 gate)** — at a single claimer (X=1) the lock is
  uncontended, so ``claim_disjoint`` writes ``leases.json`` bytes identical to
  the legacy ``_load_active_leases`` -> ``_build_active_leases`` ->
  ``write_text`` path and returns the same ``(payload, blockers, warnings)``.
  One resolved ``now`` flows into both the build and the write so
  ``generated_at`` is consistent.
* **Sidecar lock (Option B)** — the flock is taken on a STABLE ``<leases>.lock``
  file that is never renamed, NOT on ``leases.json`` (which ``_atomic_write_text``
  rewrites via ``os.replace``, swapping its inode). A Codex review proved flocking
  the data file lets a post-replace opener lock a different inode and double-claim
  under >=3 concurrent claimers — so the lock-target choice is load-bearing.
* **Mutual exclusion / no double-claim** — concurrent claimers and concurrent
  acquire/release never observe more than one holder inside the critical section
  and never leave a torn / non-disjoint file.
* **Reuse, not reimplementation** — expiry / stale-clearing / TTL all flow
  through ``_build_active_leases`` verbatim; ``claim_disjoint`` only adds the
  flock + the ``assert_claimed_files_disjoint`` pass.

Payloads are pinned explicitly so the tests are deterministic across machines
and need no external model / network.
"""
from __future__ import annotations

import concurrent.futures
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest

from scripts import agent_loop


FIXED_NOW = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)


def _leases_path(repo_root: Path) -> Path:
    """Resolve the canonical leases.json under a tmp repo root."""
    return agent_loop._active_path(agent_loop.DEFAULT_ACTIVE_LEASES, repo_root=repo_root)


def test_single_claimer_byte_identical_and_return_equivalent(tmp_path: Path) -> None:
    """X=1: claim_disjoint output == legacy _build/_write path, bytes pinned.

    Builds the EXPECTED payload from a direct _build_active_leases call with a
    fixed `now`, derives the on-disk bytes the same way _write_active_leases
    does, then proves claim_disjoint emits exactly those bytes + an equal
    return tuple. disjoint_blockers must be [] (single lease is trivially
    disjoint), so returned blockers == _build's blockers. No temp artifact.
    """
    repo_root = tmp_path
    path = _leases_path(repo_root)

    expected_payload, expected_blockers, expected_warnings = agent_loop._build_active_leases(
        existing_leases=[],
        task_id="T-2026-0001",
        issue="1780",
        branch="feat/issue-1780-lease-claim-disjoint",
        changed_files=["scripts/agent_loop.py"],
        lease_ttl_minutes=30,
        now=FIXED_NOW,
        repo_root=repo_root,
    )
    expected_bytes = (
        json.dumps(agent_loop._sanitize_json_value(expected_payload), indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    payload, blockers, warnings = agent_loop.LeaseManager(
        path, repo_root=repo_root
    ).claim_disjoint(
        task_id="T-2026-0001",
        issue="1780",
        branch="feat/issue-1780-lease-claim-disjoint",
        changed_files=["scripts/agent_loop.py"],
        lease_ttl_minutes=30,
        now=FIXED_NOW,
    )

    # Byte-identity vs the legacy write path it replaces.
    assert path.read_bytes() == expected_bytes
    # Return-equivalence: payload + blockers + warnings match the direct build.
    assert payload == expected_payload
    # disjoint_blockers == [] for a single lease, so blockers == build's blockers.
    assert blockers == expected_blockers
    assert warnings == expected_warnings
    # The atomic temp+replace write drops no .<name>.* artifact.
    assert list(path.parent.glob(".leases.json.*")) == []


def test_lock_is_sidecar_not_the_data_file(tmp_path: Path) -> None:
    """The flock target is <leases>.lock (stable), never leases.json itself.

    Option B (sidecar) is load-bearing: _atomic_write_text rewrites leases.json
    via os.replace (new inode), and flock follows the inode not the path, so
    flocking the data file would let a post-replace opener double-claim. We pin
    that the lock fd is opened on the sidecar path.
    """
    repo_root = tmp_path
    path = _leases_path(repo_root)
    mgr = agent_loop.LeaseManager(path, repo_root=repo_root)

    assert mgr._lock_path == path.with_name("leases.json.lock")
    assert mgr._lock_path != path

    opened: list[str] = []
    real_open = agent_loop.os.open

    def _spy_open(file, flags, mode=0o777):  # noqa: ANN001 - mirrors os.open
        opened.append(str(file))
        return real_open(file, flags, mode)

    # Record what path the exclusive lock opens.
    import unittest.mock as _mock

    with _mock.patch.object(agent_loop.os, "open", _spy_open):
        with mgr._exclusive():
            pass

    assert opened == [str(mgr._lock_path)]
    # The lock file is a real, stable path co-located with leases.json.
    assert mgr._lock_path.exists()


@pytest.mark.skipif(agent_loop.fcntl is None, reason="flock requires POSIX fcntl")
def test_two_concurrent_claimers_never_double_claim(tmp_path: Path) -> None:
    """2 threads claiming disjoint file sets both land + final file is disjoint.

    Under the sidecar flock, two concurrent claimers serialize: both task leases
    end up present and assert_claimed_files_disjoint returns [] (no overlap).
    """
    repo_root = tmp_path
    path = _leases_path(repo_root)
    barrier = threading.Barrier(2)

    specs = [
        {
            "task_id": "T-2026-0001",
            "issue": "1780",
            "branch": "feat/issue-1780-a",
            "changed_files": ["a/one.py"],
        },
        {
            "task_id": "T-2026-0002",
            "issue": "1781",
            "branch": "feat/issue-1781-b",
            "changed_files": ["b/two.py"],
        },
    ]

    def _claim(spec: dict[str, object]) -> None:
        barrier.wait()  # maximize overlap on the critical section
        agent_loop.LeaseManager(path, repo_root=repo_root).claim_disjoint(
            task_id=cast(str, spec["task_id"]),
            issue=cast(str, spec["issue"]),
            branch=cast(str, spec["branch"]),
            changed_files=cast("list[str]", spec["changed_files"]),
            lease_ttl_minutes=30,
            now=FIXED_NOW,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_claim, spec) for spec in specs]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    items = agent_loop._load_active_leases(path)
    task_ids = {str(item.get("task_id")) for item in items}
    # Both claims survived the race (neither lost-update).
    assert "T-2026-0001" in task_ids
    assert "T-2026-0002" in task_ids
    # The final file is disjoint (no overlapping claimed_files).
    assert agent_loop.assert_claimed_files_disjoint(items) == []


@pytest.mark.skipif(agent_loop.fcntl is None, reason="flock requires POSIX fcntl")
def test_unlocked_baseline_can_lose_update(tmp_path: Path) -> None:
    """Control: the SAME race via raw _load->_build->write_text CAN lose a claim.

    Without the sidecar flock, two threads read the same snapshot, each build a
    payload that omits the other's lease, and the later write_text clobbers the
    earlier one — so at least one run drops a claim or tears the file. This
    proves the lock in claim_disjoint is load-bearing, not decorative. We retry
    a few times because a lost update is a race (not guaranteed every run); the
    locked path (sibling test) must NEVER exhibit it.
    """
    repo_root = tmp_path
    path = _leases_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    specs = [
        {"task_id": "T-2026-0001", "issue": "1780", "branch": "feat/issue-1780-a", "files": ["a/one.py"]},
        {"task_id": "T-2026-0002", "issue": "1781", "branch": "feat/issue-1781-b", "files": ["b/two.py"]},
    ]

    def _race_once() -> set[str]:
        if path.exists():
            path.unlink()
        barrier = threading.Barrier(2)

        def _unlocked_claim(spec: dict[str, object]) -> None:
            barrier.wait()
            existing = agent_loop._load_active_leases(path)
            time.sleep(0.005)  # widen the TOCTOU window between read and write
            payload, _, _ = agent_loop._build_active_leases(
                existing_leases=existing,
                task_id=cast(str, spec["task_id"]),
                issue=cast(str, spec["issue"]),
                branch=cast(str, spec["branch"]),
                changed_files=cast("list[str]", spec["files"]),
                lease_ttl_minutes=30,
                now=FIXED_NOW,
                repo_root=repo_root,
            )
            time.sleep(0.005)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(agent_loop._sanitize_json_value(payload), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            futures = [ex.submit(_unlocked_claim, spec) for spec in specs]
            for f in concurrent.futures.as_completed(futures):
                f.result()

        items = agent_loop._load_active_leases(path)
        return {str(item.get("task_id")) for item in items}

    lost_update_observed = False
    for _ in range(25):
        task_ids = _race_once()
        if not {"T-2026-0001", "T-2026-0002"}.issubset(task_ids):
            lost_update_observed = True
            break

    assert lost_update_observed, (
        "expected the unlocked _load->_build->write_text path to drop a concurrent "
        "claim at least once across 25 races — if it never does, the race window "
        "may be too narrow to demonstrate why claim_disjoint's flock is required."
    )


@pytest.mark.skipif(agent_loop.fcntl is None, reason="flock requires POSIX fcntl")
def test_mutual_exclusion_max_occupancy_is_one(tmp_path: Path, monkeypatch) -> None:
    """N=16 claimers behind a Barrier observe critical-section occupancy <= 1.

    Monkeypatch _build_active_leases with a wrapper that increments a shared
    counter on enter (asserting it is never > 1), sleeps briefly, decrements on
    exit. If the flock failed to serialize (the Option-A footgun under inode
    swap), two builders would overlap and the observed max would exceed 1. The
    sidecar lock MUST keep observed max == 1, and the final file parses + is
    disjoint.
    """
    repo_root = tmp_path
    path = _leases_path(repo_root)

    counter = 0
    observed_max = 0
    counter_lock = threading.Lock()
    real_build = agent_loop._build_active_leases

    def _instrumented_build(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal counter, observed_max
        with counter_lock:
            counter += 1
            observed_max = max(observed_max, counter)
            assert counter <= 1, f"critical section overlap: {counter} concurrent builders"
        try:
            time.sleep(0.002)
            return real_build(**kwargs)
        finally:
            with counter_lock:
                counter -= 1

    monkeypatch.setattr(agent_loop, "_build_active_leases", _instrumented_build)

    n = 16
    barrier = threading.Barrier(n)

    def _claim(i: int) -> None:
        barrier.wait()
        agent_loop.LeaseManager(path, repo_root=repo_root).claim_disjoint(
            task_id=f"T-2026-{i:04d}",
            issue=str(2000 + i),
            branch=f"feat/issue-{2000 + i}-lane-{i}",
            changed_files=[f"lane_{i}/file.py"],
            lease_ttl_minutes=30,
            now=FIXED_NOW,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(_claim, i) for i in range(n)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    # The lock serialized every builder: never more than one at a time.
    assert observed_max == 1
    # Final file parses and is disjoint (no overlapping claimed_files).
    items = agent_loop._load_active_leases(path)
    assert agent_loop.assert_claimed_files_disjoint(items) == []


def test_expiry_and_stale_clearing_unchanged(tmp_path: Path) -> None:
    """Expired free same-scope lease is cleared; foreign active lease survives.

    Seeds an expired free write lease in the SAME scope (cleared with a stale
    warning) plus an active foreign-scope lease (must survive). The returned
    leases must equal a direct _build_active_leases over the same inputs —
    proving claim_disjoint reuses the expiry/stale logic verbatim.
    """
    repo_root = tmp_path
    path = _leases_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    expired = agent_loop._isoformat(FIXED_NOW - timedelta(minutes=5))
    future = agent_loop._isoformat(FIXED_NOW + timedelta(minutes=60))
    seeded = [
        {
            "lease_id": "stale-self",
            "status": "active",
            "lease_type": "write",
            "active_agent": None,
            "task_id": "T-2026-0001",
            "issue": "1780",
            "branch": "feat/issue-1780-lease-claim-disjoint",
            "worktree": ".",
            "claimed_files": ["scripts/agent_loop.py"],
            "expires_at": expired,
        },
        {
            "lease_id": "foreign-active",
            "status": "active",
            "lease_type": "write",
            "active_agent": None,
            "task_id": "T-2026-9999",
            "issue": "9999",
            "branch": "feat/issue-9999-other",
            "worktree": "../other-wt",
            "claimed_files": ["other/file.py"],
            "expires_at": future,
        },
    ]
    path.write_text(
        json.dumps({"schema_version": 1, "leases": seeded}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # EXPECTED leases from a direct build over the SAME seeded existing leases.
    expected_payload, _, _ = agent_loop._build_active_leases(
        existing_leases=[dict(item) for item in seeded],
        task_id="T-2026-0001",
        issue="1780",
        branch="feat/issue-1780-lease-claim-disjoint",
        changed_files=["scripts/agent_loop.py"],
        lease_ttl_minutes=30,
        now=FIXED_NOW,
        repo_root=repo_root,
    )

    payload, blockers, warnings = agent_loop.LeaseManager(
        path, repo_root=repo_root
    ).claim_disjoint(
        task_id="T-2026-0001",
        issue="1780",
        branch="feat/issue-1780-lease-claim-disjoint",
        changed_files=["scripts/agent_loop.py"],
        lease_ttl_minutes=30,
        now=FIXED_NOW,
    )

    # Stale free same-scope lease cleared with a warning.
    assert any("stale free write lease cleared" in w for w in warnings)
    # Reuse proof: leases identical to a direct build over the same inputs.
    assert payload["leases"] == expected_payload["leases"]
    # The foreign active lease survived.
    lease_ids = {str(item.get("lease_id")) for item in cast("list[dict]", payload["leases"])}
    assert "foreign-active" in lease_ids
    # Disjoint (different claimed_files), so no disjoint blocker added.
    assert blockers == []


@pytest.mark.skipif(agent_loop.fcntl is None, reason="flock requires POSIX fcntl")
def test_acquire_release_mutually_exclusive_under_flock(tmp_path: Path) -> None:
    """Concurrent acquire/release never tear the file; <=1 holder per snapshot.

    Two threads (claude + codex) drive acquire/release concurrently behind a
    Barrier. Each read-check-write runs under the sidecar flock, so every
    consistent on-disk snapshot has at most one active_agent and the file always
    parses (never torn / partial).
    """
    repo_root = tmp_path
    path = _leases_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Seed a single active write lease both lanes contend for.
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "leases": [
                    {
                        "lease_id": "impl",
                        "status": "active",
                        "lease_type": "write",
                        "active_agent": None,
                        "owner_session": "implementer",
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    err_lock = threading.Lock()

    def _drive(agent: str) -> None:
        try:
            barrier.wait()
            for _ in range(40):
                agent_loop.acquire_active_agent(agent=agent, repo_root=repo_root)
                # File must always parse mid-flight (never torn).
                items = agent_loop._load_active_leases(path)
                holders = [i.get("active_agent") for i in items if i.get("active_agent")]
                assert len(holders) <= 1, f"more than one holder observed: {holders}"
                agent_loop.release_active_agent(agent=agent, repo_root=repo_root)
        except BaseException as exc:  # noqa: BLE001 - surface any thread failure
            with err_lock:
                errors.append(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_drive, "claude"), ex.submit(_drive, "codex")]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    assert errors == []
    # Final file is well-formed and has at most one holder.
    items = agent_loop._load_active_leases(path)
    holders = [i.get("active_agent") for i in items if i.get("active_agent")]
    assert len(holders) <= 1
    # No temp artifact survives the concurrent acquire/release churn.
    assert list(path.parent.glob(".leases.json.*")) == []


@pytest.mark.skipif(agent_loop.fcntl is None, reason="flock requires POSIX fcntl")
def test_same_file_overlap_reports_but_does_not_gate_write(tmp_path: Path) -> None:
    """Overlapping cross-scope claim REPORTS an overlap blocker yet STILL writes.

    This pins the SUBSTRATE-STAGE report-not-gate contract: claim_disjoint runs
    assert_claimed_files_disjoint under the lock so the overlap blocker is
    accurate (not a stale snapshot), folds it into the return, but writes the
    lease unconditionally — byte-identical to a direct _build_active_leases +
    _write_active_leases of the same inputs. First-writer-wins WRITE rejection
    (keeping the durable file disjoint) is DEFERRED to PR-D/E X>1 enablement; the
    deferral is intentional, not accidental — gating here would risk X=1
    byte-identity in the cross-scope active-overlap edge and needs e2e X>1
    coverage. The seeded lease's claimed_files use the repo-relative posix form
    _build_active_leases stores via _display_path, so the overlap actually fires.
    """
    repo_root = tmp_path
    path = _leases_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    future = agent_loop._isoformat(FIXED_NOW + timedelta(minutes=60))
    shared_file = "src/shared.py"
    # Sanity: the seeded path matches what _build_active_leases would store for
    # the new lease (so the claimed_files sets actually intersect).
    assert agent_loop._display_path(shared_file, repo_root=repo_root) == shared_file
    existing = {
        "lease_id": "foreign-overlap",
        "status": "active",
        "lease_type": "write",
        "active_agent": None,
        "task_id": "T-2026-9999",
        "issue": "9999",
        "branch": "feat/issue-9999-other",
        "worktree": "../other-wt",  # DIFFERENT scope: not cleared as stale
        "claimed_files": [shared_file],
        "expires_at": future,  # FUTURE: _build_active_leases keeps it active
    }
    agent_loop._write_active_leases(path, leases=[existing], now=FIXED_NOW)

    # Snapshot the seeded existing leases exactly as claim_disjoint will read them.
    seeded_existing = agent_loop._load_active_leases(path)
    # Independent reference build over the SAME inputs claim_disjoint uses.
    expected_payload, _, _ = agent_loop._build_active_leases(
        existing_leases=[dict(item) for item in seeded_existing],
        task_id="T-2026-0001",
        issue="1780",
        branch="feat/issue-1780-lease-claim-disjoint",
        changed_files=[shared_file],
        lease_ttl_minutes=30,
        now=FIXED_NOW,
        repo_root=repo_root,
    )
    reference_path = tmp_path / "reference" / "leases.json"
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    agent_loop._write_active_leases(
        reference_path, leases=cast("list[dict]", expected_payload["leases"]), now=FIXED_NOW
    )
    expected_bytes = reference_path.read_bytes()

    payload, blockers, warnings = agent_loop.LeaseManager(
        path, repo_root=repo_root
    ).claim_disjoint(
        task_id="T-2026-0001",
        issue="1780",
        branch="feat/issue-1780-lease-claim-disjoint",
        changed_files=[shared_file],
        lease_ttl_minutes=30,
        now=FIXED_NOW,
    )

    # REPORT: the new lease overlaps the seeded one on src/shared.py — a
    # claimed-files overlap blocker MUST be present (non-vacuous: substring check).
    overlap_blockers = [b for b in blockers if "overlap" in b]
    assert overlap_blockers, f"expected an overlap blocker, got blockers={blockers!r}"
    assert any(shared_file in b for b in overlap_blockers)

    # NOT-GATE: the lease file was written and is durable with BOTH task_ids —
    # the overlap was reported, not gated away.
    items = agent_loop._load_active_leases(path)
    task_ids = {str(item.get("task_id")) for item in items}
    assert {"T-2026-9999", "T-2026-0001"}.issubset(task_ids), (
        f"both claimers must survive (report-not-gate), got task_ids={task_ids!r}"
    )
    # The returned payload mirrors the durable on-disk leases.
    assert payload["leases"] == cast("list[dict]", expected_payload["leases"])

    # BYTE-IDENTITY: on-disk bytes equal a direct _build + _write of the same
    # inputs — claim_disjoint neither mutated nor gated the payload.
    assert path.read_bytes() == expected_bytes
    # No abstention/error: warnings are advisory, not a write rejection signal.
    assert isinstance(warnings, list)
