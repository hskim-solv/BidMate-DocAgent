"""Tests for scripts/fleet_coordination.py — cross-process reservation substrate (ADR 0101 M1).

Determinism contract (mirrors the module's design):
  * Every operation function takes ``path=`` and ``now=`` keywords. Tests inject a
    ``tmp_path``-isolated reservations.json (``path=``) and an explicit
    ``now=datetime(...)`` so neither the on-disk fleet store nor the wall clock can
    make a test flaky.
  * AC1a (true cross-process exclusivity) uses ``multiprocessing`` with the *spawn*
    start method (macOS default), so the worker MUST be a module-top-level picklable
    function — see ``_concurrent_reserve_worker``. A spin-barrier (all children busy-wait
    until the same wall-clock instant) forces real contention; the success count is then
    asserted *deterministically* (exactly one winner, the rest blocked).

ADR 0005 boundary: NO real private RFP path/content ever appears in a fixture. Every
claimed-file string is a synthetic *relative* code path (``scripts/foo.py`` etc.) and the
privacy assertions are positive-shape (allowed structure), never a blocklist of forbidden
literals.
"""
from __future__ import annotations

import errno
import json
import multiprocessing as mp
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# fleet_coordination is imported as a scripts/ package module. It internally does a BARE
# ``import agent_loop`` (after prepending scripts/ to sys.path), so the module fleet reads at
# runtime is ``fc.agent_loop`` — a DIFFERENT object from ``scripts.agent_loop`` in sys.modules.
# All monkeypatching / serializer references below go through ``fc.agent_loop`` for that reason.
from scripts import fleet_coordination as fc


# Repo root is needed by the spawned children to put scripts/ on sys.path, because
# pytest's pyproject ``pythonpath`` setting does NOT propagate into a spawn-start child.
_REPO_ROOT = Path(__file__).resolve().parents[1]

# A fixed, deterministic clock. All time-dependent assertions derive from this anchor +
# explicit timedeltas — never from datetime.now().
T0 = datetime(2026, 6, 4, 12, 0, 0, tzinfo=timezone.utc)

# Synthetic relative code paths only (ADR 0005). None of these touch data/ or any real
# private corpus file; they are pure strings the reservation schema is allowed to carry.
F_A = "scripts/contended_a.py"
F_B = "scripts/contended_b.py"
F_C = "rag_core.py"
F_D = "scripts/agent_loop.py"


@pytest.fixture()
def store(tmp_path: Path) -> Path:
    """An isolated reservations.json path under tmp_path (never the real fleet store)."""
    return tmp_path / "reservations.json"


# ---------------------------------------------------------------------------
# AC1a — TRUE cross-process exclusivity (multiprocessing, spawn-safe)
# ---------------------------------------------------------------------------
def _concurrent_reserve_worker(
    idx: int,
    repo_root: str,
    path_str: str,
    files: list[str],
    start_epoch: float,
    result_q: "mp.Queue",
) -> None:
    """Top-level picklable worker for the spawn-start contention probe (AC1a).

    Each child re-establishes the import path (spawn does not inherit pytest's
    pythonpath), spin-waits on a shared wall-clock barrier so all children race the
    same lock simultaneously, then attempts a reserve of the SAME overlapping file set
    with an injected fixed clock. Reports ("ok"|"block"|"err", payload) on the queue.
    """
    import sys as _sys

    for entry in (repo_root, f"{repo_root}/scripts"):
        if entry not in _sys.path:
            _sys.path.insert(0, entry)
    import fleet_coordination as _fc  # type: ignore[import-not-found]  # resolved via scripts/ on sys.path

    # Spin-barrier: bound the busy-wait so a mis-scheduled child can never hang the suite.
    deadline = start_epoch + 30.0
    while time.time() < start_epoch and time.time() < deadline:
        pass

    now = datetime(2026, 6, 4, 12, 0, 0, tzinfo=timezone.utc)
    try:
        _fc.reserve(
            window_id=f"feat/issue-{idx}",
            runtime="cc",
            issue=str(idx),
            files=files,
            path=Path(path_str),
            now=now,
        )
        result_q.put(("ok", idx))
    except _fc.FleetError:
        result_q.put(("block", idx))
    except Exception as exc:  # pragma: no cover - surfaced as a test failure if hit
        result_q.put(("err", f"{type(exc).__name__}: {exc}"))


def test_ac1a_concurrent_reserve_exactly_one_winner_cross_process(store: Path) -> None:
    """AC1a: 10 processes racing an overlapping file set -> exactly 1 reserve succeeds.

    Real cross-process verification that the reused flock serializes contenders. The
    success count is asserted deterministically (winner==1, the other 9 BLOCK) despite
    the inherently concurrent scheduling, so the test is repeatable.
    """
    ctx = mp.get_context("spawn")
    files = [F_A, F_B]
    result_q: "mp.Queue" = ctx.Queue()
    n = 10
    start_epoch = time.time() + 0.5  # give every child time to spawn before the barrier opens
    procs = [
        ctx.Process(
            target=_concurrent_reserve_worker,
            args=(i, str(_REPO_ROOT), str(store), files, start_epoch, result_q),
        )
        for i in range(n)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)

    results = [result_q.get(timeout=10) for _ in range(n)]
    oks = [r for r in results if r[0] == "ok"]
    blocks = [r for r in results if r[0] == "block"]
    errs = [r for r in results if r[0] == "err"]

    assert not errs, f"unexpected worker errors: {errs}"
    assert len(oks) == 1, f"expected exactly one winner, got {len(oks)}: {results}"
    assert len(blocks) == n - 1, f"expected {n - 1} blocked, got {len(blocks)}: {results}"

    # The on-disk store must reflect exactly the single winner's claim.
    rows = fc.status_rows(path=store, now=T0)
    assert len(rows) == 1
    assert set(rows[0]["files"]) == {F_A, F_B}


# ---------------------------------------------------------------------------
# AC1b — file disjoint / self-replace
# ---------------------------------------------------------------------------
def test_ac1b_same_file_different_window_blocks(store: Path) -> None:
    """Same file claimed by a different window_id -> the second reservation BLOCKs."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    with pytest.raises(fc.FleetError, match="overlap"):
        fc.reserve(window_id="feat/issue-2-b", runtime="cc", issue="2", files=[F_A], path=store, now=T0)


def test_ac1b_disjoint_files_coexist(store: Path) -> None:
    """Non-overlapping file sets from two windows both succeed and coexist."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    fc.reserve(window_id="feat/issue-2-b", runtime="codex", issue="2", files=[F_B], path=store, now=T0)
    rows = fc.status_rows(path=store, now=T0)
    assert {r["window_id"] for r in rows} == {"feat/issue-1-a", "feat/issue-2-b"}


def test_ac1b_same_window_rereserve_is_self_replace_not_block(store: Path) -> None:
    """Re-reserving the SAME window_id replaces its own record (file-set/heartbeat refresh).

    It must NOT block on its own prior claim, and the file set must be the new set.
    """
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    refreshed = fc.reserve(
        window_id="feat/issue-1-a",
        runtime="cc",
        issue="1",
        files=[F_A, F_B],
        path=store,
        now=T0 + timedelta(minutes=5),
    )
    assert set(refreshed["claimed_files"]) == {F_A, F_B}
    rows = fc.status_rows(path=store, now=T0 + timedelta(minutes=5))
    assert len(rows) == 1
    assert set(rows[0]["files"]) == {F_A, F_B}


def test_ac1b_self_reserve_preserves_started_at(store: Path) -> None:
    """Self re-reservation keeps the original started_at (only heartbeat/expiry advance)."""
    first = fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    second = fc.reserve(
        window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0 + timedelta(minutes=3)
    )
    assert second["started_at"] == first["started_at"]
    assert second["heartbeat_at"] != first["heartbeat_at"]


# ---------------------------------------------------------------------------
# AC3 — TTL expiry / release idempotency / orphan prune
# ---------------------------------------------------------------------------
def test_ac3_expired_reservation_is_pruned_and_file_reclaimable(store: Path) -> None:
    """Advancing now past the TTL (30m) prunes the expired record; its file is reclaimable."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    past_ttl = T0 + timedelta(minutes=fc._FLEET_TTL_MINUTES + 10)
    # The expired window no longer appears as live.
    assert fc.status_rows(path=store, now=past_ttl) == []
    # A different window can now claim the same file (the writer prunes the expired record).
    reclaimed = fc.reserve(window_id="feat/issue-2-b", runtime="codex", issue="2", files=[F_A], path=store, now=past_ttl)
    assert reclaimed["claimed_files"] == [F_A]
    rows = fc.status_rows(path=store, now=past_ttl)
    assert len(rows) == 1
    assert rows[0]["window_id"] == "feat/issue-2-b"


def test_ac3_expired_record_pruned_from_disk_by_next_writer(store: Path) -> None:
    """An expired record is physically removed from the file by the next writer (prune-on-write)."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    past_ttl = T0 + timedelta(minutes=fc._FLEET_TTL_MINUTES + 10)
    # release of an unrelated window still triggers the expired-record prune (file converges).
    fc.release(window_id="feat/issue-zzz", path=store, now=past_ttl)
    payload = json.loads(store.read_text(encoding="utf-8"))
    assert payload["leases"] == []


def test_ac3_release_idempotent_returns_false_when_absent(store: Path) -> None:
    """release is idempotent: removing a present window -> True, a second/absent call -> False."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    assert fc.release(window_id="feat/issue-1-a", path=store, now=T0) is True
    assert fc.release(window_id="feat/issue-1-a", path=store, now=T0) is False


def test_ac3_release_absent_window_no_error(store: Path) -> None:
    """release of a window that never existed returns False without raising."""
    assert fc.release(window_id="never-existed", path=store, now=T0) is False


# ---------------------------------------------------------------------------
# AC4 — monitor (lockless read, status / --check / --json)
# ---------------------------------------------------------------------------
def test_ac4_empty_store_renders_no_active_reservations(store: Path) -> None:
    """status_rows on an absent file is empty; render_status_table reports no reservations."""
    assert fc.status_rows(path=store, now=T0) == []
    assert fc.render_status_table([]) == "fleet: no active reservations."


def test_ac4_render_status_table_lists_active_window(store: Path) -> None:
    """A live reservation appears in the rendered single-pane table."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    rows = fc.status_rows(path=store, now=T0)
    table = fc.render_status_table(rows)
    assert "feat/issue-1-a" in table
    assert F_A in table


def test_ac4_main_status_exits_zero_pure_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    """``main(["status"])`` is pure observation -> exit 0 even when windows are stale."""
    monkeypatch.setattr(fc, "status_rows", lambda **_: [])
    assert fc.main(["status"]) == 0


def test_ac4_main_status_check_nonzero_when_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    """``main(["status","--check"])`` exits non-zero when a window is stale."""
    stale_row = {
        "window_id": "feat/issue-1-a",
        "runtime": "cc",
        "issue": "1",
        "files": [F_A],
        "heartbeat_age_min": 99.0,
        "stale": True,
        "status": "active",
    }
    monkeypatch.setattr(fc, "status_rows", lambda **_: [stale_row])
    assert fc.main(["status", "--check"]) != 0


def test_ac4_main_status_check_zero_when_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    """``main(["status","--check"])`` exits 0 when nothing is stale or overlapping."""
    clean_row = {
        "window_id": "feat/issue-1-a",
        "runtime": "cc",
        "issue": "1",
        "files": [F_A],
        "heartbeat_age_min": 1.0,
        "stale": False,
        "status": "active",
    }
    monkeypatch.setattr(fc, "status_rows", lambda **_: [clean_row])
    assert fc.main(["status", "--check"]) == 0


def test_ac4_main_status_json_is_valid_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """``main(["status","--json"])`` emits a parseable JSON object with reservation rows.

    M2 (AC14): the --json envelope is now ``{"reservations": [...], "reviews": [...]}``
    so the single pane can carry both substrates; the reservation rows live under
    ``reservations`` (the bare-list shape predates the review channel).
    """
    row = {
        "window_id": "feat/issue-1-a",
        "runtime": "cc",
        "issue": "1",
        "files": [F_A],
        "heartbeat_age_min": 1.0,
        "stale": False,
        "status": "active",
    }
    monkeypatch.setattr(fc, "status_rows", lambda **_: [row])
    monkeypatch.setattr(fc, "review_rows", lambda **_: [])
    code = fc.main(["status", "--json"])
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert code == 0
    assert parsed["reservations"][0]["window_id"] == "feat/issue-1-a"
    assert parsed["reviews"] == []


def test_ac4_has_conflict_or_stale_flags_overlap(store: Path) -> None:
    """has_conflict_or_stale surfaces a pairwise file overlap across live rows."""
    rows = [
        {"window_id": "w1", "runtime": "cc", "issue": "1", "files": [F_A], "heartbeat_age_min": 1.0, "stale": False, "status": "active"},
        {"window_id": "w2", "runtime": "cc", "issue": "2", "files": [F_A], "heartbeat_age_min": 1.0, "stale": False, "status": "active"},
    ]
    problems = fc.has_conflict_or_stale(rows)
    assert any("overlap" in p for p in problems)


def test_ac4_status_read_is_lockless_during_held_lock(store: Path) -> None:
    """A monitor read succeeds even while the reservation lock is held (lockless read).

    Reads go through os.replace-published state, never the flock — so holding the
    exclusive lock must not block status_rows.
    """
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    manager = fc._lease_manager(store)
    with manager._exclusive():
        rows = fc.status_rows(path=store, now=T0)
    assert len(rows) == 1 and rows[0]["window_id"] == "feat/issue-1-a"


# ---------------------------------------------------------------------------
# AC6 — fail-closed substrate honesty
# ---------------------------------------------------------------------------
def test_ac6_reserve_refuses_when_fcntl_unavailable(monkeypatch: pytest.MonkeyPatch, store: Path) -> None:
    """(1) fcntl is None (non-POSIX) -> reserve refuses with a 'fcntl unavailable' FleetError.

    NOTE: the patch target is ``fc.agent_loop`` (the module object fleet actually reads at
    runtime), NOT the test-imported ``scripts.agent_loop``. fleet_coordination does a bare
    ``import agent_loop`` after prepending scripts/ to sys.path, so the bare module and the
    ``scripts.agent_loop`` package module are TWO distinct objects in sys.modules (see the
    "dual-module identity" finding in the report). Patching the wrong one is invisible to fleet.
    """
    monkeypatch.setattr(fc.agent_loop, "fcntl", None)
    with pytest.raises(fc.FleetError, match="fcntl unavailable"):
        fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)


def test_ac6_flock_honest_passes_on_real_filesystem(tmp_path: Path) -> None:
    """The two-open honesty probe PASSES on a normal FS (second LOCK_EX|NB raises BlockingIOError)."""
    # Must not raise: a real local FS honors exclusive flocks.
    fc._assert_flock_honest(tmp_path / "probe.lock")


def test_ac6_flock_honest_refuses_lying_filesystem(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A simulated dishonest FS (flock always 'succeeds') is detected and refused.

    Patch target is ``fc.agent_loop`` for the dual-module reason documented above.
    """
    real = fc.agent_loop.fcntl
    assert real is not None  # precondition: the host actually has fcntl

    class _LyingFcntl:
        LOCK_EX = real.LOCK_EX
        LOCK_NB = real.LOCK_NB
        LOCK_UN = real.LOCK_UN

        @staticmethod
        def flock(fd: int, op: int) -> None:  # never blocks -> dishonest exclusion
            return None

    monkeypatch.setattr(fc.agent_loop, "fcntl", _LyingFcntl)
    with pytest.raises(fc.FleetError, match="does not honor exclusive flocks"):
        fc._assert_flock_honest(tmp_path / "lying.lock")


# ---------------------------------------------------------------------------
# AC7 — ADR 0005 record privacy boundary (positive-shape)
# ---------------------------------------------------------------------------
def test_ac7_record_rejects_key_outside_allowlist() -> None:
    """A record carrying any key outside the positive allowlist is rejected."""
    record = {
        "schema_version": 1,
        "window_id": "feat/issue-1-a",
        "runtime": "cc",
        "claimed_files": [F_A],
        "rfp_payload": "anything",  # disallowed key
    }
    with pytest.raises(fc.FleetError, match="disallowed key"):
        fc.assert_record_privacy_safe(record)


def test_ac7_record_rejects_wrong_schema_version() -> None:
    """schema_version != 1 is rejected."""
    record = {"schema_version": 2, "window_id": "w", "runtime": "cc", "claimed_files": [F_A]}
    with pytest.raises(fc.FleetError, match="schema_version"):
        fc.assert_record_privacy_safe(record)


def test_ac7_record_rejects_bad_runtime() -> None:
    """runtime not in (cc, codex) is rejected."""
    record = {"schema_version": 1, "window_id": "w", "runtime": "gemini", "claimed_files": [F_A]}
    with pytest.raises(fc.FleetError, match="runtime"):
        fc.assert_record_privacy_safe(record)


def test_ac7_record_rejects_non_list_claimed_files() -> None:
    """claimed_files that is not a list is rejected."""
    record = {"schema_version": 1, "window_id": "w", "runtime": "cc", "claimed_files": "scripts/foo.py"}
    with pytest.raises(fc.FleetError, match="claimed_files must be a list"):
        fc.assert_record_privacy_safe(record)


def test_ac7_record_accepts_valid_synthetic_record() -> None:
    """A well-formed record with synthetic relative paths passes the guard."""
    record = {
        "schema_version": 1,
        "window_id": "feat/issue-1-a",
        "runtime": "cc",
        "issue": "1",
        "claimed_files": [F_A, F_C],
        "started_at": "2026-06-04T12:00:00Z",
        "heartbeat_at": "2026-06-04T12:00:00Z",
        "expires_at": "2026-06-04T12:30:00Z",
        "status": "active",
    }
    fc.assert_record_privacy_safe(record)  # must not raise


def test_ac7_reserve_rejects_data_corpus_path(store: Path) -> None:
    """reserve refuses a claim under data/ (private corpus tree) — ADR 0005."""
    with pytest.raises(fc.FleetError, match="data/"):
        fc.reserve(window_id="w", runtime="cc", issue="1", files=["data/private_rfp.pdf"], path=store, now=T0)


def test_ac7_reserve_rejects_absolute_path_outside_repo(store: Path) -> None:
    """reserve refuses an absolute path that resolves outside the repo."""
    with pytest.raises(fc.FleetError, match="outside the repo"):
        fc.reserve(window_id="w", runtime="cc", issue="1", files=["/etc/passwd"], path=store, now=T0)


def test_ac7_reserve_rejects_dotdot_escape(store: Path) -> None:
    """reserve refuses a relative path containing a .. escape."""
    with pytest.raises(fc.FleetError, match="not a safe relative path"):
        fc.reserve(window_id="w", runtime="cc", issue="1", files=["../outside.py"], path=store, now=T0)


def test_ac7_reserve_accepts_normal_relative_path(store: Path) -> None:
    """reserve accepts an ordinary in-repo relative code path."""
    record = fc.reserve(window_id="w", runtime="cc", issue="1", files=[F_D], path=store, now=T0)
    assert record["claimed_files"] == [F_D]


# ---------------------------------------------------------------------------
# AC8 — runtime field (cc | codex)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("runtime", ["cc", "codex"])
def test_ac8_reserve_accepts_valid_runtimes_and_preserves_field(store: Path, runtime: str) -> None:
    """Both cc and codex are accepted, and the runtime is preserved on the record."""
    record = fc.reserve(window_id=f"feat/issue-{runtime}", runtime=runtime, issue="1", files=[F_A], path=store, now=T0)
    assert record["runtime"] == runtime
    rows = fc.status_rows(path=store, now=T0)
    assert rows[0]["runtime"] == runtime


def test_ac8_reserve_rejects_unknown_runtime(store: Path) -> None:
    """An unknown runtime is rejected before any write."""
    with pytest.raises(fc.FleetError, match="runtime"):
        fc.reserve(window_id="w", runtime="bogus", issue="1", files=[F_A], path=store, now=T0)


# ---------------------------------------------------------------------------
# heartbeat
# ---------------------------------------------------------------------------
def test_heartbeat_refreshes_clock_for_live_window(store: Path) -> None:
    """heartbeat advances heartbeat_at and expires_at for a live window."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    later = T0 + timedelta(minutes=10)
    refreshed = fc.heartbeat(window_id="feat/issue-1-a", path=store, now=later)
    assert refreshed is not None
    # Use fc.agent_loop._isoformat — the exact serializer fleet writes with (dual-module note above).
    assert refreshed["heartbeat_at"] == fc.agent_loop._isoformat(later)
    assert refreshed["expires_at"] == fc.agent_loop._isoformat(later + timedelta(minutes=fc._FLEET_TTL_MINUTES))


def test_heartbeat_returns_none_for_absent_window_and_does_not_create(store: Path) -> None:
    """heartbeat on a window with no live reservation returns None and creates nothing."""
    result = fc.heartbeat(window_id="never-existed", path=store, now=T0)
    assert result is None
    assert fc.status_rows(path=store, now=T0) == []


def test_heartbeat_keeps_window_alive_past_original_ttl(store: Path) -> None:
    """A heartbeat before expiry extends liveness past the original TTL window."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    # Beat at +20m (still within the original 30m TTL).
    fc.heartbeat(window_id="feat/issue-1-a", path=store, now=T0 + timedelta(minutes=20))
    # At +40m the window would have expired under the original expiry, but the heartbeat
    # at +20m pushed expiry to +50m, so it is still live.
    rows = fc.status_rows(path=store, now=T0 + timedelta(minutes=40))
    assert len(rows) == 1
    assert rows[0]["window_id"] == "feat/issue-1-a"


def test_heartbeat_does_not_create_window_when_only_expired_present(store: Path) -> None:
    """heartbeat for a window whose record already expired returns None (no resurrection)."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    past_ttl = T0 + timedelta(minutes=fc._FLEET_TTL_MINUTES + 10)
    assert fc.heartbeat(window_id="feat/issue-1-a", path=store, now=past_ttl) is None


# ===========================================================================
# M2 — cross-family review toggle (ADR 0101 D5 + D7; AC11-AC14)
#
# Every review test injects a FAKE runner — no real claude/codex/agent-turn
# process is EVER spawned (no external egress, no private data). The runner
# contract is (candidate_family, reviewer_family, base, repo_root) -> core dict.
# ===========================================================================
@pytest.fixture()
def reviews_store(tmp_path: Path) -> Path:
    """An isolated reviews.json path under tmp_path (never the real fleet store)."""
    return tmp_path / "reviews.json"


def _fake_runner_factory(verdict: str = "approved", findings: list | None = None):
    """Build an injectable review runner that records its call args + returns a core."""
    calls: list[tuple[str, str, str]] = []

    def runner(candidate_family: str, reviewer_family: str, base: str, repo_root: Path) -> dict:
        calls.append((candidate_family, reviewer_family, base))
        return {"verdict": verdict, "summary": "synthetic", "findings": findings or []}

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


# ---------------------------------------------------------------------------
# AC11 — cross-family fail-closed + opposite-family routing
# ---------------------------------------------------------------------------
def test_ac11_reviewer_family_is_opposite_of_candidate() -> None:
    """cc -> codex, codex -> cc (the explicit opposite-family map)."""
    assert fc.reviewer_family_for("cc") == "codex"
    assert fc.reviewer_family_for("codex") == "cc"


def test_ac11_reviewer_family_never_equals_candidate() -> None:
    """The map structurally guarantees reviewer != candidate for every valid family."""
    for family in ("cc", "codex"):
        assert fc.reviewer_family_for(family) != family


def test_ac11_reviewer_family_rejects_unknown_candidate() -> None:
    """An unknown candidate family cannot derive an opposite -> FleetError."""
    with pytest.raises(fc.FleetError, match="candidate_family"):
        fc.reviewer_family_for("gpt")


def test_ac11_review_routes_cc_candidate_to_codex_reviewer(
    store: Path, reviews_store: Path
) -> None:
    """A cc window's review is routed to the codex reviewer (cc produced -> codex reviews)."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    runner = _fake_runner_factory()
    record = fc.review(
        base="origin/main",
        coupling="adversarial",
        window_id="feat/issue-1-a",
        path=reviews_store,
        reservations_path=store,
        runner=runner,
        now=T0,
    )
    assert record["candidate_family"] == "cc"
    assert record["reviewer_family"] == "codex"
    assert runner.calls == [("cc", "codex", "origin/main")]  # type: ignore[attr-defined]


def test_ac11_review_routes_codex_candidate_to_cc_reviewer(
    store: Path, reviews_store: Path
) -> None:
    """A codex window's review is routed to the claude (cc) reviewer."""
    fc.reserve(window_id="feat/issue-2-b", runtime="codex", issue="2", files=[F_B], path=store, now=T0)
    runner = _fake_runner_factory()
    record = fc.review(
        base="origin/main",
        coupling="adversarial",
        window_id="feat/issue-2-b",
        path=reviews_store,
        reservations_path=store,
        runner=runner,
        now=T0,
    )
    assert record["candidate_family"] == "codex"
    assert record["reviewer_family"] == "cc"
    assert runner.calls == [("codex", "cc", "origin/main")]  # type: ignore[attr-defined]


def test_ac11_same_family_record_is_refused_by_privacy_guard() -> None:
    """A hand-built record with reviewer_family == candidate_family is rejected (fail-closed)."""
    record = {
        "schema_version": 1,
        "window_id": "feat/issue-1-a",
        "candidate_family": "cc",
        "reviewer_family": "cc",  # SAME family — must be refused
        "base": "origin/main",
        "verdict": "approved",
        "severity_counts": {"blocker": 0, "warning": 0, "info": 0},
        "reviewed_at": "2026-06-04T12:00:00Z",
    }
    with pytest.raises(fc.FleetError, match="same-family review refused"):
        fc.assert_review_privacy_safe(record)


def test_ac11_review_explicit_runtime_overrides_reservation(
    store: Path, reviews_store: Path
) -> None:
    """An explicit --runtime determines candidate_family even without a reservation."""
    runner = _fake_runner_factory()
    record = fc.review(
        base="origin/main",
        runtime="codex",
        coupling="adversarial",
        window_id="feat/issue-orphan",
        path=reviews_store,
        reservations_path=store,
        runner=runner,
        now=T0,
    )
    assert record["candidate_family"] == "codex"
    assert record["reviewer_family"] == "cc"


def test_ac11_review_without_reservation_or_runtime_errors(
    store: Path, reviews_store: Path
) -> None:
    """No live reservation and no --runtime -> cannot determine candidate_family."""
    runner = _fake_runner_factory()
    with pytest.raises(fc.FleetError, match="no live reservation"):
        fc.review(
            base="origin/main",
            coupling="adversarial",
            window_id="feat/issue-ghost",
            path=reviews_store,
            reservations_path=store,
            runner=runner,
            now=T0,
        )


# ---------------------------------------------------------------------------
# AC12 — FLEET_COUPLING toggle (off / reserve / adversarial; default reserve)
# ---------------------------------------------------------------------------
def test_ac12_resolve_coupling_default_is_reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset FLEET_COUPLING resolves to 'reserve' (M2 opt-in default)."""
    monkeypatch.delenv("FLEET_COUPLING", raising=False)
    assert fc.resolve_coupling() == "reserve"


def test_ac12_resolve_coupling_empty_env_is_reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty FLEET_COUPLING value falls back to the default."""
    monkeypatch.setenv("FLEET_COUPLING", "")
    assert fc.resolve_coupling() == "reserve"


@pytest.mark.parametrize("mode", ["off", "reserve", "adversarial"])
def test_ac12_resolve_coupling_reads_env(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """Each valid mode is read from the env (and is case-insensitive)."""
    monkeypatch.setenv("FLEET_COUPLING", mode.upper())
    assert fc.resolve_coupling() == mode


def test_ac12_resolve_coupling_rejects_unknown_value() -> None:
    """A typo'd coupling value fails closed rather than silently defaulting."""
    with pytest.raises(fc.FleetError, match="FLEET_COUPLING"):
        fc.resolve_coupling("adverserial")  # misspelling


@pytest.mark.parametrize("mode", ["off", "reserve"])
def test_ac12_review_refused_unless_adversarial(
    store: Path, reviews_store: Path, mode: str
) -> None:
    """off / reserve refuse the review with a clear message (NOT inert) — no runner call."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    runner = _fake_runner_factory()
    with pytest.raises(fc.FleetError, match="FLEET_COUPLING=adversarial"):
        fc.review(
            base="origin/main",
            coupling=mode,
            window_id="feat/issue-1-a",
            path=reviews_store,
            reservations_path=store,
            runner=runner,
            now=T0,
        )
    assert runner.calls == []  # type: ignore[attr-defined]  # refused before any review ran
    assert fc._load_reviews(reviews_store) == []  # nothing persisted


def test_ac12_review_runs_when_adversarial(store: Path, reviews_store: Path) -> None:
    """adversarial actually invokes the injected runner and persists the verdict."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    runner = _fake_runner_factory(verdict="clear")
    record = fc.review(
        base="origin/main",
        coupling="adversarial",
        window_id="feat/issue-1-a",
        path=reviews_store,
        reservations_path=store,
        runner=runner,
        now=T0,
    )
    assert len(runner.calls) == 1  # type: ignore[attr-defined]
    assert record["verdict"] == "clear"
    assert len(fc._load_reviews(reviews_store)) == 1


def test_ac12_review_default_coupling_refuses(
    store: Path, reviews_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With FLEET_COUPLING unset (-> reserve), review refuses (coupling=None reads env)."""
    monkeypatch.delenv("FLEET_COUPLING", raising=False)
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    runner = _fake_runner_factory()
    with pytest.raises(fc.FleetError, match="FLEET_COUPLING=adversarial"):
        fc.review(
            base="origin/main",
            coupling=None,
            window_id="feat/issue-1-a",
            path=reviews_store,
            reservations_path=store,
            runner=runner,
            now=T0,
        )


# ---------------------------------------------------------------------------
# AC13 — reviews.json record ADR 0005 boundary (positive-shape allowlist)
# ---------------------------------------------------------------------------
def _valid_review_record() -> dict:
    return {
        "schema_version": 1,
        "window_id": "feat/issue-1-a",
        "candidate_family": "cc",
        "reviewer_family": "codex",
        "base": "origin/main",
        "verdict": "approved",
        "severity_counts": {"blocker": 0, "warning": 1, "info": 2},
        "reviewed_at": "2026-06-04T12:00:00Z",
    }


def test_ac13_valid_review_record_passes() -> None:
    """A well-formed meta-only record passes the guard."""
    fc.assert_review_privacy_safe(_valid_review_record())  # must not raise


def test_ac13_review_record_rejects_key_outside_allowlist() -> None:
    """A record carrying a key outside the allowlist (e.g. a diff) is rejected."""
    record = _valid_review_record()
    record["diff"] = "--- a/x\n+++ b/x\n"  # forbidden — no such key in the allowlist
    with pytest.raises(fc.FleetError, match="disallowed key"):
        fc.assert_review_privacy_safe(record)


def test_ac13_review_record_rejects_findings_text_key() -> None:
    """A 'findings' text key is not in the allowlist -> rejected (text never enters fleet)."""
    record = _valid_review_record()
    record["findings"] = [{"title": "leak", "body": "secret code snippet"}]
    with pytest.raises(fc.FleetError, match="disallowed key"):
        fc.assert_review_privacy_safe(record)


def test_ac13_review_record_rejects_wrong_schema_version() -> None:
    record = _valid_review_record()
    record["schema_version"] = 2
    with pytest.raises(fc.FleetError, match="schema_version"):
        fc.assert_review_privacy_safe(record)


def test_ac13_review_record_rejects_bad_verdict() -> None:
    record = _valid_review_record()
    record["verdict"] = "lgtm"  # not in the contract enum
    with pytest.raises(fc.FleetError, match="verdict"):
        fc.assert_review_privacy_safe(record)


def test_ac13_review_record_rejects_data_base() -> None:
    """A base that points under data/ (private corpus) is refused."""
    record = _valid_review_record()
    record["base"] = "data/private_rfp"
    with pytest.raises(fc.FleetError, match="data/"):
        fc.assert_review_privacy_safe(record)


def test_ac13_review_record_rejects_path_shaped_base() -> None:
    """A path-shaped base (not a git ref) is refused."""
    record = _valid_review_record()
    record["base"] = "./relative/path.py"
    with pytest.raises(fc.FleetError, match="path"):
        fc.assert_review_privacy_safe(record)


def test_ac13_review_record_rejects_absolute_base() -> None:
    record = _valid_review_record()
    record["base"] = "/etc/passwd"
    with pytest.raises(fc.FleetError, match="path"):
        fc.assert_review_privacy_safe(record)


def test_ac13_severity_counts_must_be_numeric() -> None:
    """A non-int severity count (a string carrying a snippet) is refused."""
    record = _valid_review_record()
    record["severity_counts"] = {"blocker": "a code snippet here", "warning": 0, "info": 0}
    with pytest.raises(fc.FleetError, match="non-negative int"):
        fc.assert_review_privacy_safe(record)


def test_ac13_severity_counts_rejects_negative() -> None:
    record = _valid_review_record()
    record["severity_counts"] = {"blocker": -1, "warning": 0, "info": 0}
    with pytest.raises(fc.FleetError, match="non-negative int"):
        fc.assert_review_privacy_safe(record)


def test_ac13_severity_counts_rejects_bool() -> None:
    """A bool (int subclass) must not masquerade as a count."""
    record = _valid_review_record()
    record["severity_counts"] = {"blocker": True, "warning": 0, "info": 0}
    with pytest.raises(fc.FleetError, match="non-negative int"):
        fc.assert_review_privacy_safe(record)


def test_ac13_severity_counts_rejects_extra_key() -> None:
    record = _valid_review_record()
    record["severity_counts"] = {"blocker": 0, "warning": 0, "info": 0, "code": 1}
    with pytest.raises(fc.FleetError, match="disallowed key"):
        fc.assert_review_privacy_safe(record)


def test_ac13_review_record_rejects_oversized_string_value() -> None:
    """A long string value (a smuggled code blob) in an allowlisted field is refused."""
    record = _valid_review_record()
    record["window_id"] = "x" * (fc._REVIEW_STRING_VALUE_MAX + 1)
    with pytest.raises(fc.FleetError, match="exceeds"):
        fc.assert_review_privacy_safe(record)


def test_ac13_persisted_record_only_has_allowlisted_keys(
    store: Path, reviews_store: Path
) -> None:
    """A review run through review() persists ONLY allowlisted keys (no diff/findings text)."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    runner = _fake_runner_factory(
        verdict="needs-attention",
        findings=[{"severity": "blocker", "title": "t", "body": "raw secret body"}],
    )
    fc.review(
        base="origin/main",
        coupling="adversarial",
        window_id="feat/issue-1-a",
        path=reviews_store,
        reservations_path=store,
        runner=runner,
        now=T0,
    )
    persisted = fc._load_reviews(reviews_store)
    assert len(persisted) == 1
    assert set(persisted[0].keys()) <= fc._ALLOWED_REVIEW_KEYS
    # The findings body text must NOT have leaked into the record anywhere.
    blob = json.dumps(persisted[0])
    assert "raw secret body" not in blob
    # Only the COUNT survived.
    assert persisted[0]["severity_counts"] == {"blocker": 1, "warning": 0, "info": 0}


# ---------------------------------------------------------------------------
# AC14 — engine reuse (injectable, no shell-out) + fleet-status integration
# ---------------------------------------------------------------------------
def test_ac14_review_uses_injected_runner_no_shellout(
    store: Path, reviews_store: Path
) -> None:
    """review() calls ONLY the injected runner — no real claude/codex/agent-turn spawn."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    runner = _fake_runner_factory(verdict="approved")
    fc.review(
        base="origin/main",
        coupling="adversarial",
        window_id="feat/issue-1-a",
        path=reviews_store,
        reservations_path=store,
        runner=runner,
        now=T0,
    )
    # The runner was the only review path exercised (1 call, expected args).
    assert runner.calls == [("cc", "codex", "origin/main")]  # type: ignore[attr-defined]


def test_ac14_review_keeps_only_latest_per_window(store: Path, reviews_store: Path) -> None:
    """Re-reviewing a window replaces its prior verdict (one current verdict per window)."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    fc.review(
        base="origin/main", coupling="adversarial", window_id="feat/issue-1-a",
        path=reviews_store, reservations_path=store, runner=_fake_runner_factory("needs-attention"), now=T0,
    )
    fc.review(
        base="origin/main", coupling="adversarial", window_id="feat/issue-1-a",
        path=reviews_store, reservations_path=store, runner=_fake_runner_factory("approved"),
        now=T0 + timedelta(minutes=5),
    )
    persisted = fc._load_reviews(reviews_store)
    assert len(persisted) == 1
    assert persisted[0]["verdict"] == "approved"


_orig_status_rows = fc.status_rows
_orig_review_rows = fc.review_rows


def _bind_isolated_stores(store: Path, reviews_store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rebind main()'s row functions to the isolated tmp stores.

    main() calls the module-level ``status_rows()`` / ``review_rows()`` with no
    ``path=`` arg, so they would otherwise read the real fleet store (the path
    DEFAULT is bound at def-time, so monkeypatching ``fc.RESERVATIONS_PATH`` is
    invisible — the same dual-binding caveat the M1 status tests document). Rebind
    the FUNCTIONS to read the isolated stores instead, so main()'s render + gating
    logic is exercised against the test data.
    """
    monkeypatch.setattr(fc, "status_rows", lambda **_: _orig_status_rows(path=store, now=T0))
    monkeypatch.setattr(fc, "review_rows", lambda **_: _orig_review_rows(path=reviews_store, now=T0))


def test_ac14_status_shows_reservation_and_review_together(
    monkeypatch: pytest.MonkeyPatch, store: Path, reviews_store: Path, capsys: pytest.CaptureFixture
) -> None:
    """main(['status']) renders BOTH the reservation row AND the review verdict row, exit 0."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    fc.review(
        base="origin/main", coupling="adversarial", window_id="feat/issue-1-a",
        path=reviews_store, reservations_path=store, runner=_fake_runner_factory("approved"), now=T0,
    )
    _bind_isolated_stores(store, reviews_store, monkeypatch)
    code = fc.main(["status"])
    out = capsys.readouterr().out
    assert code == 0
    assert "feat/issue-1-a" in out  # reservation row
    assert "cc→codex" in out  # review row
    assert "approved" in out


def test_ac14_status_json_includes_reviews(
    monkeypatch: pytest.MonkeyPatch, store: Path, reviews_store: Path, capsys: pytest.CaptureFixture
) -> None:
    """main(['status','--json']) emits both reservations and reviews arrays."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    fc.review(
        base="origin/main", coupling="adversarial", window_id="feat/issue-1-a",
        path=reviews_store, reservations_path=store, runner=_fake_runner_factory("approved"), now=T0,
    )
    _bind_isolated_stores(store, reviews_store, monkeypatch)
    code = fc.main(["status", "--json"])
    parsed = json.loads(capsys.readouterr().out)
    assert code == 0
    assert "reservations" in parsed and "reviews" in parsed
    assert parsed["reviews"][0]["window_id"] == "feat/issue-1-a"
    assert parsed["reviews"][0]["reviewer_family"] == "codex"


def test_ac16_status_check_zero_when_review_clear(
    monkeypatch: pytest.MonkeyPatch, store: Path, reviews_store: Path
) -> None:
    """A review verdict NEVER gates --check (advisory, option B): a passing 'clear'
    review keeps --check at 0 when nothing else is wrong — and so would a blocked one
    (see test_ac16_blocked_verdict_does_not_gate_check). The gate is reservation
    conflict / staleness / unreadable store only."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    fc.review(
        base="origin/main", coupling="adversarial", window_id="feat/issue-1-a",
        path=reviews_store, reservations_path=store, runner=_fake_runner_factory("clear"), now=T0,
    )
    _bind_isolated_stores(store, reviews_store, monkeypatch)
    assert fc.main(["status", "--check"]) == 0


def test_ac16_blocked_verdict_does_not_gate_check(
    monkeypatch: pytest.MonkeyPatch, store: Path, reviews_store: Path
) -> None:
    """ADVISORY (ADR 0101 D5, option B): a 'blocked' review verdict is rendered in the
    status pane but does NOT gate --check. No automated cross-family verdict auto-blocks
    a ship — the merge gate is ship-arm's D6 review-gate plus the human operator. With no
    reservation conflict / stale window, --check exits 0 despite the blocked review.

    This is the regression that locks in option B: the prior pass-class gate (only
    approved/clear pass; needs-attention/blocked/error fail) is gone.
    """
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    fc.review(
        base="origin/main", coupling="adversarial", window_id="feat/issue-1-a",
        path=reviews_store, reservations_path=store, runner=_fake_runner_factory("blocked"), now=T0,
    )
    _bind_isolated_stores(store, reviews_store, monkeypatch)
    assert fc.main(["status", "--check"]) == 0


def test_ac16_error_verdict_does_not_gate_check(
    monkeypatch: pytest.MonkeyPatch, store: Path, reviews_store: Path
) -> None:
    """Same advisory contract for an 'error' verdict — shown, never gated."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    fc.review(
        base="origin/main", coupling="adversarial", window_id="feat/issue-1-a",
        path=reviews_store, reservations_path=store, runner=_fake_runner_factory("error"), now=T0,
    )
    _bind_isolated_stores(store, reviews_store, monkeypatch)
    assert fc.main(["status", "--check"]) == 0


def test_ac16_blocked_verdict_is_still_rendered(store: Path, reviews_store: Path) -> None:
    """Advisory does not mean hidden — the blocked verdict still surfaces in the review
    rows so the operator can act on it (the whole point of rendering-without-gating)."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    fc.review(
        base="origin/main", coupling="adversarial", window_id="feat/issue-1-a",
        path=reviews_store, reservations_path=store, runner=_fake_runner_factory("blocked"), now=T0,
    )
    rows = fc.review_rows(path=reviews_store, now=T0)
    assert any(r["verdict"] == "blocked" for r in rows)


def test_ac14_review_lockless_read_during_held_lock(store: Path, reviews_store: Path) -> None:
    """review_rows reads through os.replace-published state, never the flock."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    fc.review(
        base="origin/main", coupling="adversarial", window_id="feat/issue-1-a",
        path=reviews_store, reservations_path=store, runner=_fake_runner_factory("approved"), now=T0,
    )
    manager = fc._lease_manager(reviews_store)
    with manager._exclusive():
        rows = fc.review_rows(path=reviews_store, now=T0)
    assert len(rows) == 1 and rows[0]["window_id"] == "feat/issue-1-a"


def test_ac14_main_review_refuses_under_reserve_coupling(
    monkeypatch: pytest.MonkeyPatch, store: Path, reviews_store: Path, capsys: pytest.CaptureFixture
) -> None:
    """CLI: `review` exits non-zero with a clear message when coupling is reserve (default)."""
    monkeypatch.delenv("FLEET_COUPLING", raising=False)
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    monkeypatch.setattr(fc, "RESERVATIONS_PATH", store)
    monkeypatch.setattr(fc, "REVIEWS_PATH", reviews_store)
    code = fc.main(["review", "--window", "feat/issue-1-a", "--base", "origin/main"])
    err = capsys.readouterr().err
    assert code == 1
    assert "FLEET_COUPLING=adversarial" in err


# ===========================================================================
# Group A — _default_review_runner unit tests (code review L4)
#
# _default_review_runner is NEVER exercised by the M2 tests above because every
# review() call there supplies an injected runner.  These tests monkeypatch the
# modules that _default_review_runner imports INSIDE its own body so the codex /
# claude turn binaries are never invoked.
#
# Import strategy: _default_review_runner does
#   from scripts import agent_loop_codex_turn as codex_turn
#   from scripts import agent_loop_claude_turn as claude_turn
# inside the function body on every call.  The canonical objects in sys.modules
# are "scripts.agent_loop_codex_turn" and "scripts.agent_loop_claude_turn".
# Replacing the run_turn attribute on those live module objects is the
# narrowest correct patch target (no sys.modules key swap needed).
# ===========================================================================
import sys as _sys


def _get_codex_turn_module():
    """Return the live scripts.agent_loop_codex_turn module (force-import if absent)."""
    import importlib

    key = "scripts.agent_loop_codex_turn"
    if key not in _sys.modules:
        importlib.import_module(key)
    return _sys.modules[key]


def _get_claude_turn_module():
    """Return the live scripts.agent_loop_claude_turn module (force-import if absent)."""
    import importlib

    key = "scripts.agent_loop_claude_turn"
    if key not in _sys.modules:
        importlib.import_module(key)
    return _sys.modules[key]


# ---------------------------------------------------------------------------
# A1 — reviewer_family="codex" branch: codex run_turn called with correct args
# ---------------------------------------------------------------------------
def test_group_a1_default_runner_codex_branch_calls_codex_run_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """_default_review_runner(reviewer_family='codex') calls codex_turn.run_turn with
    base/scope/focus args and returns the core.  The claude lane is never touched.
    """
    codex_calls: list[dict] = []
    claude_calls: list[dict] = []

    _synthetic_core = {"verdict": "approved", "summary": "synthetic codex review", "findings": []}

    def _fake_codex_run_turn(**kwargs: object) -> dict:
        codex_calls.append(dict(kwargs))
        return _synthetic_core

    def _fake_claude_run_turn(**kwargs: object) -> dict:  # must not be called
        claude_calls.append(dict(kwargs))
        return {"verdict": "error", "findings": []}

    codex_mod = _get_codex_turn_module()
    claude_mod = _get_claude_turn_module()
    monkeypatch.setattr(codex_mod, "run_turn", _fake_codex_run_turn)
    monkeypatch.setattr(claude_mod, "run_turn", _fake_claude_run_turn)
    # Also patch the privacy backstop so we don't need a real git repo.
    monkeypatch.setattr(fc, "_review_core_has_residual_private_span", lambda _core, **_kw: False)

    result = fc._default_review_runner(
        candidate_family="cc",
        reviewer_family="codex",
        base="origin/main",
        repo_root=tmp_path,
    )

    # Codex lane called exactly once with the expected keyword args.
    assert len(codex_calls) == 1, f"expected 1 codex call, got {codex_calls}"
    assert codex_calls[0].get("base") == "origin/main"
    assert codex_calls[0].get("scope") == "branch"
    assert "cc" in str(codex_calls[0].get("focus", ""))
    # Claude lane never called.
    assert claude_calls == [], f"claude lane must not be called: {claude_calls}"
    # Core propagated to return value.
    assert result.get("verdict") == "approved"
    assert result.get("summary") == "synthetic codex review"


# ---------------------------------------------------------------------------
# A2 — reviewer_family="cc" branch: claude run_turn called, diff embedded
# ---------------------------------------------------------------------------
def test_group_a2_default_runner_cc_branch_calls_claude_run_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """_default_review_runner(reviewer_family='cc') calls claude_turn.run_turn with
    prompt (containing the fake diff) and schema_path.  The codex lane is never touched.
    """
    codex_calls: list[dict] = []
    claude_calls: list[dict] = []

    _synthetic_core = {"verdict": "needs-attention", "summary": "synthetic cc review", "findings": []}

    def _fake_codex_run_turn(**kwargs: object) -> dict:  # must not be called
        codex_calls.append(dict(kwargs))
        return {"verdict": "error", "findings": []}

    def _fake_claude_run_turn(**kwargs: object) -> dict:
        claude_calls.append(dict(kwargs))
        return _synthetic_core

    _fake_diff = "--- a/scripts/foo.py\n+++ b/scripts/foo.py\n@@ -1 +1 @@\n-old\n+new\n"

    codex_mod = _get_codex_turn_module()
    claude_mod = _get_claude_turn_module()
    monkeypatch.setattr(codex_mod, "run_turn", _fake_codex_run_turn)
    monkeypatch.setattr(claude_mod, "run_turn", _fake_claude_run_turn)
    # Patch _agent_turn_diff via fc.agent_loop (same dual-module note as AC6 tests).
    monkeypatch.setattr(fc.agent_loop, "_agent_turn_diff", lambda _base, **_kw: _fake_diff)
    monkeypatch.setattr(fc, "_review_core_has_residual_private_span", lambda _core, **_kw: False)

    result = fc._default_review_runner(
        candidate_family="codex",
        reviewer_family="cc",
        base="origin/main",
        repo_root=tmp_path,
    )

    # Codex lane never called.
    assert codex_calls == [], f"codex lane must not be called: {codex_calls}"
    # Claude lane called exactly once.
    assert len(claude_calls) == 1, f"expected 1 claude call, got {claude_calls}"
    # Prompt must contain the fake diff.
    prompt_arg = str(claude_calls[0].get("prompt", ""))
    assert _fake_diff in prompt_arg, "diff must be embedded in the claude prompt"
    # schema_path must be a Path that ends with the review artifact schema name.
    schema_arg = claude_calls[0].get("schema_path")
    assert isinstance(schema_arg, Path), f"schema_path must be a Path, got {type(schema_arg)}"
    assert schema_arg.name.endswith(".json"), f"schema_path should point to a .json file: {schema_arg}"
    # Core propagated.
    assert result.get("verdict") == "needs-attention"
    assert result.get("summary") == "synthetic cc review"


# ---------------------------------------------------------------------------
# A3 — privacy backstop: residual private span collapses verdict to "error"
# ---------------------------------------------------------------------------
def test_group_a3_default_runner_backstop_collapses_on_residual_private_span(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When _review_core_has_residual_private_span returns True (residual span survived
    redaction), _default_review_runner must return {'verdict': 'error', ...} regardless
    of the runner's verdict.  Synthetic absolute path pattern used — no real private data.
    """
    # The synthetic core that the runner returns (verdict would be 'approved' without backstop).
    _dirty_core: dict[str, object] = {
        "verdict": "approved",
        "summary": "review of /Users/x/private/secret_rfp.pdf page 3",
        "findings": [],
    }

    def _fake_codex_run_turn(**kwargs: object) -> dict:
        return _dirty_core

    codex_mod = _get_codex_turn_module()
    monkeypatch.setattr(codex_mod, "run_turn", _fake_codex_run_turn)
    # Force the audit to report a residual span (simulates a pattern that survived redaction).
    monkeypatch.setattr(fc, "_review_core_has_residual_private_span", lambda core, **_kw: True)

    result = fc._default_review_runner(
        candidate_family="cc",
        reviewer_family="codex",
        base="origin/main",
        repo_root=tmp_path,
    )

    assert result.get("verdict") == "error", (
        f"backstop must collapse verdict to 'error', got: {result.get('verdict')!r}"
    )
    summary = str(result.get("summary", ""))
    assert "privacy" in summary.lower() or "backstop" in summary.lower(), (
        f"error summary should mention privacy/backstop, got: {summary!r}"
    )


# ===========================================================================
# Group B — _assert_flock_honest probe concurrency regression guard
#           (code review M1/M2 — guards the return-on-contention new behavior)
#
# The key behavioral change: when fd1 LOCK_EX|NB fails (another fd holds the
# lock), _assert_flock_honest now returns (passes) instead of raising.  This
# avoids a false-block when two windows contend on the same probe path — the
# real exclusion comes from the caller's blocking _exclusive() acquire.
# ===========================================================================
def test_group_b1_flock_honest_passes_when_lock_already_held(tmp_path: Path) -> None:
    """When another fd already holds LOCK_EX on the .lock file, _assert_flock_honest
    must return without raising (the contention itself proves the FS is honest).

    This is the regression guard for the M1/M2 fix: previously this would raise
    FleetError('retry shortly'), causing a spurious false-block the operator had
    to retry by hand.
    """
    import fcntl as _fcntl

    lock_path = tmp_path / "concurrent.lock"
    lock_path.touch()

    fd_holder = os.open(str(lock_path), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        # Acquire an exclusive lock from an external fd — this is the "another holder" scenario.
        _fcntl.flock(fd_holder, _fcntl.LOCK_EX)
        # The probe must PASS (return None) because the failed LOCK_EX|NB on fd1 is itself
        # proof that the FS honors exclusion.
        result = fc._assert_flock_honest(lock_path)
        assert result is None, (
            f"_assert_flock_honest must return None when lock is held, got: {result!r}"
        )
    finally:
        try:
            _fcntl.flock(fd_holder, _fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd_holder)


# ===========================================================================
# Group C — Codex adversarial pre-commit review regressions (re-commit pass)
#
# The first commit was BLOCKED by a critical (per-worktree store, so cross-worktree
# reservations never meet) + 3 high/medium informational findings (probe errno
# discrimination, malformed-state fail-open, needs-attention treated as passing).
# These guard the fixes so they cannot silently regress.
# ===========================================================================
def test_group_c1_resolve_fleet_dir_shared_across_real_worktrees(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two distinct worktree roots MUST resolve to the same fleet dir (Codex critical).

    The per-worktree ``.omc`` store meant cross-worktree reservations never met.
    ``_resolve_fleet_dir`` now anchors at the git COMMON dir (shared by every
    worktree of a repo). Build a real repo + a linked worktree and prove both
    resolve to one shared fleet dir.
    """
    monkeypatch.delenv("FLEET_STATE_DIR", raising=False)
    main = tmp_path / "main"
    main.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    subprocess.run(["git", "init", "-q", str(main)], check=True, env=env)
    (main / "x.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(main), "add", "."], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(main), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True, env=env,
    )
    wt = tmp_path / "wt"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-q", str(wt), "-b", "feat/issue-1-x"],
        check=True, env=env,
    )

    main_fleet = fc._resolve_fleet_dir(main)
    wt_fleet = fc._resolve_fleet_dir(wt)
    assert main_fleet == wt_fleet, (
        f"worktrees must share one fleet dir, got main={main_fleet} wt={wt_fleet}"
    )
    # Anchored at the MAIN worktree's .omc/state/fleet, not the linked worktree's.
    assert main_fleet == (main / ".omc" / "state" / "fleet").resolve()


def test_group_c2_fleet_state_dir_override_shares_store_and_blocks_overlap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A shared store (two windows, two runtimes) BLOCKS an overlapping claim —
    end-to-end proof that one shared anchor makes cross-worktree reservations meet."""
    monkeypatch.setenv("FLEET_STATE_DIR", str(tmp_path / "shared"))
    assert fc._resolve_fleet_dir() == (tmp_path / "shared").resolve()
    shared_store = tmp_path / "shared" / "reservations.json"
    # window A (worktree 1, cc) claims F_A through the shared store.
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=shared_store, now=T0)
    # window B (worktree 2, codex) claiming the SAME file is refused — the headline
    # cross-worktree first-writer-wins block the per-worktree store could not do.
    with pytest.raises(fc.FleetError, match="overlap"):
        fc.reserve(window_id="feat/issue-2-b", runtime="codex", issue="2", files=[F_A], path=shared_store, now=T0)


def test_group_c3_probe_fails_closed_on_non_contention_errno(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A non-contention flock errno (ENOLCK) must FAIL CLOSED, not be mistaken for
    honest contention (Codex high — probe errno discrimination).

    Only BlockingIOError (real contention) passes the probe; every other OSError is
    a substrate that cannot lock and must be refused.
    """
    real = fc.agent_loop.fcntl
    assert real is not None

    class _NoLockFcntl:
        LOCK_EX = real.LOCK_EX
        LOCK_NB = real.LOCK_NB
        LOCK_UN = real.LOCK_UN

        @staticmethod
        def flock(fd: int, op: int) -> None:
            raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(fc.agent_loop, "fcntl", _NoLockFcntl)
    with pytest.raises(fc.FleetError, match="does not support advisory locking"):
        fc._assert_flock_honest(tmp_path / "nolock.lock")


def test_group_c4_rmw_fails_closed_on_corrupt_store(store: Path) -> None:
    """A garbled reservations.json makes reserve/heartbeat/release FAIL CLOSED and
    leaves the file UNTOUCHED — never a blind overwrite that erases live claims
    (Codex high — malformed state must not fail open)."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[F_A], path=store, now=T0)
    store.write_text("{ not valid json", encoding="utf-8")
    corrupt = store.read_text(encoding="utf-8")

    with pytest.raises(fc.FleetError, match="unreadable"):
        fc.reserve(window_id="feat/issue-2-b", runtime="cc", issue="2", files=[F_B], path=store, now=T0)
    with pytest.raises(fc.FleetError, match="unreadable"):
        fc.heartbeat(window_id="feat/issue-1-a", path=store, now=T0)
    with pytest.raises(fc.FleetError, match="unreadable"):
        fc.release(window_id="feat/issue-1-a", path=store, now=T0)

    # The corrupt file is left exactly as-is for the operator to inspect/repair.
    assert store.read_text(encoding="utf-8") == corrupt


def test_group_c4b_monitor_read_tolerates_corrupt_store(store: Path) -> None:
    """The LOCKLESS monitor read (status) stays tolerant of a garbled file — it must
    NOT raise (a status pane never gates), unlike the strict RMW path above."""
    store.write_text("{ not valid json", encoding="utf-8")
    assert fc.status_rows(path=store, now=T0) == []


# ===========================================================================
# Group D — option B (advisory verdict) + Codex round-2 high/medium regressions
# ===========================================================================
# Locks in the four findings resolved for PR #2236 commit-2 (ADR 0101 D5/D7):
#   - directory/descendant claim overlap (Codex high)
#   - status --check fails CLOSED on a corrupt store (Codex high)
#   - reserve CLI has no cc default (Codex info 1311)
#   - malformed reviews store fails closed in the strict RMW reader (Codex medium)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("eval/", "eval/config.yaml"),        # directory claim blocks descendant file
        ("api/main.py", "api/"),              # file claim blocks ancestor directory
        ("docs/adr/", "docs/adr/0101-x.md"),  # nested directory vs specific file
    ],
)
def test_group_d_path_overlap_blocks_directory_descendant(
    store: Path, first: str, second: str
) -> None:
    """A directory claim must conflict with a descendant file claim and vice-versa —
    repo-path overlap, not exact-set intersection (Codex high). The load-bearing set
    holds real directory entries (eval/, api/, docs/adr/), so this is the semantics a
    reviewer relies on to keep two windows out of the same tree."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=[first], path=store, now=T0)
    with pytest.raises(fc.FleetError):
        fc.reserve(window_id="feat/issue-2-b", runtime="codex", issue="2", files=[second], path=store, now=T0)


def test_group_d_path_overlap_allows_sibling_files(store: Path) -> None:
    """Sibling files under the same dir do NOT conflict — only ancestor/descendant or
    identical paths do (guards against an over-broad match)."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=["eval/config.yaml"], path=store, now=T0)
    rec = fc.reserve(window_id="feat/issue-2-b", runtime="codex", issue="2", files=["eval/runner.py"], path=store, now=T0)
    assert rec["window_id"] == "feat/issue-2-b"


def test_group_d_path_overlap_allows_prefix_lookalike(store: Path) -> None:
    """`eval/` must NOT swallow `evaluation/foo.py` — the conflict is a path-segment
    boundary, not a raw string prefix (eval ⊄ evaluation)."""
    fc.reserve(window_id="feat/issue-1-a", runtime="cc", issue="1", files=["eval/"], path=store, now=T0)
    rec = fc.reserve(window_id="feat/issue-2-b", runtime="codex", issue="2", files=["evaluation/foo.py"], path=store, now=T0)
    assert rec["window_id"] == "feat/issue-2-b"


def test_group_d_status_check_fails_closed_on_corrupt_reservations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--check is a GATE: a corrupt reservations store must fail CLOSED (non-zero), not
    read as empty via the lockless monitor path (Codex high: status --check fails open
    on corrupt fleet state). The strict reader is invoked against the module-level
    path, which the CLI block looks up at runtime (so monkeypatch is honoured)."""
    corrupt = tmp_path / "reservations.json"
    corrupt.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr(fc, "RESERVATIONS_PATH", corrupt)
    assert fc.main(["status", "--check"]) != 0


def test_group_d_status_check_fails_closed_on_corrupt_reviews(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Symmetric: a corrupt reviews store also fails the gate closed."""
    corrupt = tmp_path / "reviews.json"
    corrupt.write_text("not json at all", encoding="utf-8")
    monkeypatch.setattr(fc, "REVIEWS_PATH", corrupt)
    assert fc.main(["status", "--check"]) != 0


def test_group_d_reserve_cli_requires_runtime() -> None:
    """The reserve CLI has NO cc default — omitting --runtime is an argparse error
    (SystemExit), so a Codex window can never be silently stamped cc and then reviewed
    by its own family (Codex info 1311). Parsing aborts before any reservation write."""
    with pytest.raises(SystemExit):
        fc.main(["reserve", "--window", "feat/issue-1-a", "--files", F_A])


def test_group_d_load_reviews_strict_rejects_non_dict_non_list(tmp_path: Path) -> None:
    """A reviews store that is neither a {'reviews': [...]} dict nor a bare list fails
    closed — a blind RMW overwrite must never erase prior verdicts (Codex medium)."""
    bad = tmp_path / "reviews.json"
    bad.write_text('"just a string"', encoding="utf-8")
    with pytest.raises(fc.FleetError):
        fc._load_reviews_strict(bad)


def test_group_d_load_reviews_strict_rejects_dict_without_reviews_list(tmp_path: Path) -> None:
    """A dict store missing the 'reviews' list also fails closed."""
    bad = tmp_path / "reviews.json"
    bad.write_text('{"schema_version": 1}', encoding="utf-8")
    with pytest.raises(fc.FleetError):
        fc._load_reviews_strict(bad)


def test_group_d_load_reviews_strict_absent_is_empty(tmp_path: Path) -> None:
    """Absent file = legitimately empty (NOT corrupt) — returns [] without raising."""
    assert fc._load_reviews_strict(tmp_path / "nope.json") == []
