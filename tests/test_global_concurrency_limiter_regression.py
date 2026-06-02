"""GlobalConcurrencyLimiter global CLI-spawn ceiling regression (issue #1794, ADR 0094 PR-C).

``agent_loop.GlobalConcurrencyLimiter`` is the substrate brick that puts ONE
process-wide ``threading.BoundedSemaphore(M)`` in front of every agent-loop CLI
subprocess spawn (claude write / codex patch / read-review) so a future X*Y*Z
fan-out cannot multiply into hundreds of concurrent children. The senior
contract this guards:

* **M resolution + fail-closed** — ``M = BIDMATE_AGENT_LOOP_GLOBAL_CONCURRENCY``
  (operator front-door ``ACTIVE_GLOBAL_CONCURRENCY``), default 8. Unset / blank /
  non-int falls back to 8; a parsed value ``<= 0`` clamps to 1 so a misconfig can
  never produce a 0/unbounded ceiling.
* **Max-occupancy <= M** — no more than M threads ever hold a slot at once, AND
  the ceiling is actually reachable (max_seen == M under contention), so the
  semaphore both bounds and saturates.
* **Byte-identity (ADR 0001 gate)** — with the env unset the limiter resolves to
  the default 8; at X=1/M=8 the loop spawns one child at a time so the semaphore
  is uncontended and every on-disk artifact + task selection is byte-identical.
  Ships DARK until PR-D/E enable X>1.
* **Exactly-once / no-leak release** — ``slot()`` releases on the exception path
  (no deadlock), and ``BoundedSemaphore`` raises ``ValueError`` on an over-release
  instead of silently raising the ceiling.

The integration byte-identity net for the wired spawn sites lives in
``tests/test_agent_loop.py`` (the runner-execute tests
``...spawns_agentic_processes...`` and ``...patch_mode_execute...``); those must
stay green UNCHANGED — this file pins only the limiter primitive in isolation.

Pinned values are deterministic and need no external model / network.
"""
from __future__ import annotations

import concurrent.futures
import subprocess
import threading
import time
from pathlib import Path

import pytest

from scripts import agent_loop

# The Phase-1/Phase-2 spawn-loop escape-path regressions below drive the real
# two-phase codex-read runner (write_active_codex_runner -> spawn_and_wait), so
# they reuse the expanded-eight read-path fixtures already defined in the agent
# loop integration suite rather than re-deriving the registry/lease scaffolding.
from test_agent_loop import (  # type: ignore[import-not-found]
    _chatgpt_auth_runner,
    _write_expanded_active_runner_fixture,
    _write_repo,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT_DIR / "Makefile"


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the memoized process-wide limiter so each test resolves M fresh.

    ``global_concurrency_limiter()`` builds + caches ONE limiter; tests set env
    then trigger a build, so the cache must be cleared between tests.
    """
    monkeypatch.setattr(agent_loop, "_GLOBAL_CONCURRENCY_LIMITER", None)


# ---------------------------------------------------------------------------
# (a) M resolution + fail-closed + env + Makefile parity
# ---------------------------------------------------------------------------


def test_resolve_global_concurrency_defaults_and_fail_closed() -> None:
    """Explicit ``raw`` arg covers default / parse / fail-closed branches.

    Default (8) on None/blank/non-int; pass-through on valid ints; fail-closed
    clamp to 1 for ``<= 0`` so the ceiling is never 0/unbounded by misconfig.
    """
    assert agent_loop._resolve_global_concurrency(None) == 8
    assert agent_loop._resolve_global_concurrency("4") == 4
    assert agent_loop._resolve_global_concurrency("16") == 16
    assert agent_loop._resolve_global_concurrency("0") == 1  # fail-closed
    assert agent_loop._resolve_global_concurrency("-3") == 1  # fail-closed
    assert agent_loop._resolve_global_concurrency("") == 8  # blank -> default
    assert agent_loop._resolve_global_concurrency("abc") == 8  # non-int -> default


def test_resolve_global_concurrency_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_resolve_global_concurrency()`` (raw=None) reads the env var.

    ``BIDMATE_AGENT_LOOP_GLOBAL_CONCURRENCY`` overrides the default, and the
    ``<= 0`` fail-closed clamp applies to the env path too.
    """
    monkeypatch.setenv(agent_loop.GLOBAL_CONCURRENCY_ENV, "2")
    assert agent_loop._resolve_global_concurrency() == 2
    monkeypatch.setenv(agent_loop.GLOBAL_CONCURRENCY_ENV, "0")
    assert agent_loop._resolve_global_concurrency() == 1  # fail-closed via env


def test_makefile_declares_active_global_concurrency() -> None:
    """The operator front-door var + export + runtime bridge are in the Makefile.

    Parity with the code's default 8 (ADR 0094 PR-C). The bridge wires the
    operator knob ACTIVE_GLOBAL_CONCURRENCY to the env name the code reads
    (BIDMATE_AGENT_LOOP_GLOBAL_CONCURRENCY), so `make ... ACTIVE_GLOBAL_CONCURRENCY=N`
    is not inert.
    """
    makefile = MAKEFILE.read_text(encoding="utf-8")
    assert "ACTIVE_GLOBAL_CONCURRENCY ?= 8" in makefile
    assert "export ACTIVE_GLOBAL_CONCURRENCY" in makefile
    # Bridge: the operator front-door knob must reach the runtime env var the
    # code actually reads (os.getenv BIDMATE_AGENT_LOOP_GLOBAL_CONCURRENCY), else
    # `make ... ACTIVE_GLOBAL_CONCURRENCY=N` is inert (ADR 0094 item 4 override).
    assert "BIDMATE_AGENT_LOOP_GLOBAL_CONCURRENCY ?= $(ACTIVE_GLOBAL_CONCURRENCY)" in makefile
    assert "export BIDMATE_AGENT_LOOP_GLOBAL_CONCURRENCY" in makefile


# ---------------------------------------------------------------------------
# (b) max-occupancy <= M (and reaches the ceiling)
# ---------------------------------------------------------------------------


def test_max_occupancy_never_exceeds_limit_and_reaches_it() -> None:
    """16 threads behind one limiter never exceed M=3 concurrent slots.

    Each thread takes a slot, bumps a shared occupancy counter under a lock,
    records the running max, sleeps briefly to force overlap, then releases.
    ``max_seen <= 3`` proves the bound; ``max_seen == 3`` proves the ceiling is
    actually reached (not merely never approached).
    """
    limiter = agent_loop.GlobalConcurrencyLimiter(3)
    lock = threading.Lock()
    occupancy = 0
    max_seen = 0
    barrier = threading.Barrier(16)

    def worker() -> None:
        nonlocal occupancy, max_seen
        barrier.wait()  # release all 16 at once to maximize contention
        with limiter.slot():
            with lock:
                occupancy += 1
                max_seen = max(max_seen, occupancy)
            time.sleep(0.005)
            with lock:
                occupancy -= 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(worker) for _ in range(16)]
        for future in futures:
            future.result(timeout=30)

    assert max_seen <= 3
    assert max_seen == 3


# ---------------------------------------------------------------------------
# (c) byte-identity default
# ---------------------------------------------------------------------------


def test_global_limiter_default_is_eight(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the env unset the memoized limiter resolves to M=8 (ADR 0001 gate).

    At X=1/M=8 the loop spawns one child at a time, so the semaphore is
    uncontended and on-disk artifacts stay byte-identical. The integration
    byte-identity net (``tests/test_agent_loop.py`` runner-execute tests
    ``...spawns_agentic...`` and ``...patch_mode_execute...``) must stay green
    UNCHANGED alongside this primitive check.
    """
    monkeypatch.delenv(agent_loop.GLOBAL_CONCURRENCY_ENV, raising=False)
    assert agent_loop.global_concurrency_limiter().limit == 8


def test_global_limiter_is_memoized_singleton() -> None:
    """``global_concurrency_limiter()`` hands back the SAME instance each call."""
    first = agent_loop.global_concurrency_limiter()
    second = agent_loop.global_concurrency_limiter()
    assert first is second


# ---------------------------------------------------------------------------
# (d) release-on-exception + over-release guard (BoundedSemaphore)
# ---------------------------------------------------------------------------


def test_slot_releases_on_exception_no_deadlock() -> None:
    """An exception inside ``slot()`` still releases — no permanent slot leak."""
    limiter = agent_loop.GlobalConcurrencyLimiter(1)
    with pytest.raises(RuntimeError):
        with limiter.slot():
            raise RuntimeError("x")
    # The single slot must be reacquirable (no deadlock from a leaked permit).
    assert limiter._sem.acquire(timeout=1.0) is True
    limiter._sem.release()


def test_over_release_raises_value_error_bounded_semaphore() -> None:
    """A spurious extra release raises ValueError (proves BoundedSemaphore).

    BoundedSemaphore (not plain Semaphore) so an over-release fails loudly
    instead of silently raising the ceiling above M.
    """
    limiter = agent_loop.GlobalConcurrencyLimiter(1)
    with limiter.slot():
        pass  # acquire + release one full cycle, leaving the count at its ceiling
    with pytest.raises(ValueError):
        limiter._sem.release()  # over-release past the initial bound


# ---------------------------------------------------------------------------
# (e) Phase-1 / Phase-2 spawn-loop escape paths never leak a permit
#
# ``spawn_and_wait`` (nested in ``write_active_codex_runner``) acquires the ONE
# process-wide slot MANUALLY per codex-read child and relies on a try/finally to
# return EVERY permit on EVERY exit. These tests pin the three escape paths an
# adversarial review found could leak before the finally existed:
#   1. ``_spawn_codex_reader_thread`` (Thread.start) raises AFTER the slot is
#      acquired but BEFORE the child reaches ``batch_spawned`` (pending_release).
#   2. Phase-2 ``wait()`` raises a NON-``TimeoutExpired`` exception (only
#      ``TimeoutExpired`` was caught) — without a finally the remaining permits
#      leaked and the exception escaped.
#   3. A mid-batch spawn ``OSError`` with >= 1 earlier live child — the earlier
#      children must be stopped/reaped AND all permits returned (DEFECT 2).
# After M such leaks the BoundedSemaphore would deadlock. "Permits restored" is
# measured by reading ``limiter._sem._value`` (== M means every permit returned)
# AND proving the limiter can still be acquired M times.
# ---------------------------------------------------------------------------


class _ReadProc:
    """Minimal codex-read subprocess double: usable stdin, no readable stdout.

    No ``stdout`` attribute -> ``_spawn_codex_reader_thread`` returns ``None``
    (no real tail thread), keeping the Phase-2 path deterministic. ``wait``
    returns 0 by default; subclasses / instances override to raise.
    """

    def __init__(self, pid: int = 9000) -> None:
        self.pid = pid
        self.returncode = 0
        self.stdin = self

    def write(self, _text: str) -> None:  # stdin.write
        pass

    def close(self) -> None:  # stdin.close
        pass

    def wait(self, timeout=None):  # type: ignore[no-untyped-def]
        return 0


def _assert_all_permits_restored(limiter: agent_loop.GlobalConcurrencyLimiter, m: int = 8) -> None:
    """Every permit is back: count == M AND the ceiling is re-acquirable M times."""
    assert limiter._sem._value == m  # type: ignore[attr-defined]
    acquired = [limiter._sem.acquire(timeout=1.0) for _ in range(m)]
    try:
        assert all(acquired), "limiter could not be re-acquired M times -> a permit leaked"
        # The ceiling is exhausted now; a further non-blocking acquire must fail.
        assert limiter._sem.acquire(blocking=False) is False
    finally:
        for ok in acquired:
            if ok:
                limiter._sem.release()


def test_reader_thread_start_failure_mid_batch_restores_all_permits(tmp_path: Path) -> None:
    """``_spawn_codex_reader_thread`` raising mid-batch leaks NO permit.

    The slot for the failing child is acquired but the child never reaches
    ``batch_spawned`` (the Thread.start() / pre-append escape), and two earlier
    children are already registered holding slots. The ``finally`` must reclaim
    all three (the registered pair via the batch drain, the failing one via
    ``pending_release``), stop/reap the earlier live children, and let the
    exception propagate (not swallow it).
    """
    repo = _write_repo(tmp_path)
    _write_expanded_active_runner_fixture(repo)

    spawned_pids: list[int] = []

    def fake_popen(cmd, **kwargs):  # type: ignore[no-untyped-def]
        proc = _ReadProc(pid=9000 + len(spawned_pids))
        spawned_pids.append(proc.pid)
        return proc

    # Raise on the 3rd reader-thread spawn so two earlier children are already
    # registered in batch_spawned (exercises BOTH the drain and pending_release).
    calls = {"n": 0}
    real_helper = agent_loop._spawn_codex_reader_thread

    def flaky_reader_thread(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("can't start new thread")
        return real_helper(*args, **kwargs)

    stopped: list[object] = []

    def record_stop(proc, *a, **k):  # type: ignore[no-untyped-def]
        stopped.append(proc)

    import test_agent_loop as _tal  # noqa: F401 - ensure helper module imported

    import unittest.mock as _mock

    with _mock.patch.object(agent_loop, "_spawn_codex_reader_thread", flaky_reader_thread), \
            _mock.patch.object(agent_loop, "_stop_codex_process", record_stop):
        with pytest.raises(RuntimeError, match="can't start new thread"):
            agent_loop.write_active_codex_runner(
                execute=True,
                repo_root=repo,
                popen_factory=fake_popen,
                which_func=lambda exe: "/opt/codex/bin/codex",
                auth_runner=_chatgpt_auth_runner,
            )

    limiter = agent_loop.global_concurrency_limiter()
    _assert_all_permits_restored(limiter)
    # The two earlier live children were reaped by the finally (DEFECT-1 reaping
    # on propagation), not left running.
    assert len(stopped) >= 2


def test_reader_thread_start_failure_first_child_restores_permit(tmp_path: Path) -> None:
    """Reader-thread failure on the FIRST child reclaims the lone unregistered slot.

    With zero earlier children, only ``pending_release`` can return the permit
    acquired just before the failing ``_spawn_codex_reader_thread`` — the
    batch_spawned drain is empty. Proves the pre-append escape is covered in
    isolation.
    """
    repo = _write_repo(tmp_path)
    _write_expanded_active_runner_fixture(repo)

    def fake_popen(cmd, **kwargs):  # type: ignore[no-untyped-def]
        return _ReadProc()

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("thread start failed on first child")

    import unittest.mock as _mock

    with _mock.patch.object(agent_loop, "_spawn_codex_reader_thread", boom):
        with pytest.raises(RuntimeError, match="first child"):
            agent_loop.write_active_codex_runner(
                execute=True,
                repo_root=repo,
                popen_factory=fake_popen,
                which_func=lambda exe: "/opt/codex/bin/codex",
                auth_runner=_chatgpt_auth_runner,
            )

    _assert_all_permits_restored(agent_loop.global_concurrency_limiter())


def test_phase2_wait_non_timeout_exception_restores_all_permits(tmp_path: Path) -> None:
    """A non-``TimeoutExpired`` ``wait()`` failure in Phase 2 leaks NO permit.

    Phase 2 only catches ``subprocess.TimeoutExpired``; any other ``wait()``
    exception propagates. Before the finally, every still-held permit (the
    failing child plus every not-yet-waited child) leaked. The finally must
    return them all and re-raise.
    """
    repo = _write_repo(tmp_path)
    _write_expanded_active_runner_fixture(repo)

    class _BadWaitProc(_ReadProc):
        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            raise RuntimeError("wait() blew up (not a timeout)")

    def fake_popen(cmd, **kwargs):  # type: ignore[no-untyped-def]
        return _BadWaitProc()

    import unittest.mock as _mock

    stopped: list[object] = []
    with _mock.patch.object(agent_loop, "_stop_codex_process", lambda p, *a, **k: stopped.append(p)):
        with pytest.raises(RuntimeError, match="wait\\(\\) blew up"):
            agent_loop.write_active_codex_runner(
                execute=True,
                repo_root=repo,
                popen_factory=fake_popen,
                which_func=lambda exe: "/opt/codex/bin/codex",
                auth_runner=_chatgpt_auth_runner,
            )

    _assert_all_permits_restored(agent_loop.global_concurrency_limiter())


def test_spawn_oserror_mid_batch_reaps_earlier_child_and_restores_permits(tmp_path: Path) -> None:
    """DEFECT 2: a mid-batch spawn ``OSError`` stops earlier children + frees all permits.

    The first child spawns and starts running; the second child's ``Popen``
    raises ``OSError``. The handler records a blocker and returns (OSError is
    caught, not propagated, so the run ends BLOCKED). The finally must (a) stop /
    reap the earlier live child — not leave it running with a freed permit — and
    (b) return every acquired permit so the ceiling is fully restored.
    """
    repo = _write_repo(tmp_path)
    _write_expanded_active_runner_fixture(repo)

    spawn_calls = {"n": 0}

    def fake_popen(cmd, **kwargs):  # type: ignore[no-untyped-def]
        spawn_calls["n"] += 1
        if spawn_calls["n"] == 2:
            raise OSError("simulated spawn failure")
        return _ReadProc(pid=9000 + spawn_calls["n"])

    stopped: list[object] = []

    def record_stop(proc, *a, **k):  # type: ignore[no-untyped-def]
        stopped.append(proc)

    import unittest.mock as _mock

    with _mock.patch.object(agent_loop, "_stop_codex_process", record_stop):
        result = agent_loop.write_active_codex_runner(
            execute=True,
            repo_root=repo,
            popen_factory=fake_popen,
            which_func=lambda exe: "/opt/codex/bin/codex",
            auth_runner=_chatgpt_auth_runner,
        )

    assert result.decision == "blocked"
    assert any("failed to spawn" in b for b in result.blockers)
    # The earlier live child was stopped/reaped by the finally (DEFECT 2: before
    # the fix the OSError handler freed its permit but returned without reaping).
    assert len(stopped) >= 1
    _assert_all_permits_restored(agent_loop.global_concurrency_limiter())


def test_stdin_oserror_after_popen_stops_orphan_proc_and_restores_permits(tmp_path: Path) -> None:
    """Codex re-review HIGH: a child whose Popen SUCCEEDS but whose stdin I/O then
    raises OSError (before ``batch_spawned.append``) must not leave an orphan.

    The permit is reclaimed via ``pending_release``, but the just-spawned proc is
    also live and not yet in ``batch_spawned`` — the finally must stop it (via
    ``pending_proc``), else it keeps running untracked. This pins the PROC cleanup,
    not merely the permit: before the proc/stderr tracking was added the orphan was
    never stopped.
    """
    repo = _write_repo(tmp_path)
    _write_expanded_active_runner_fixture(repo)

    spawned: list[object] = []

    class _BadStdinProc(_ReadProc):
        def write(self, _text: str) -> None:  # stdin.write raises AFTER a good Popen
            raise OSError("broken pipe before append")

    def fake_popen(cmd, **kwargs):  # type: ignore[no-untyped-def]
        proc = _BadStdinProc()
        spawned.append(proc)
        return proc

    stopped: list[object] = []

    import unittest.mock as _mock

    with _mock.patch.object(agent_loop, "_stop_codex_process", lambda p, *a, **k: stopped.append(p)):
        result = agent_loop.write_active_codex_runner(
            execute=True,
            repo_root=repo,
            popen_factory=fake_popen,
            which_func=lambda exe: "/opt/codex/bin/codex",
            auth_runner=_chatgpt_auth_runner,
        )

    assert result.decision == "blocked"
    assert any("failed to spawn" in b for b in result.blockers)
    # The orphan proc (Popen succeeded, stdin failed, never appended) was stopped by
    # the finally via pending_proc -- before the fix only its permit was reclaimed.
    assert spawned, "fixture did not drive a codex spawn"
    assert spawned[0] in stopped
    _assert_all_permits_restored(agent_loop.global_concurrency_limiter())


def test_blocker_break_straggler_inline_and_finally_release_no_over_release(tmp_path: Path) -> None:
    """The blocker-break straggler is released inline AND revisited by the finally;
    the one-shot closure must make the second release a no-op (no ``BoundedSemaphore``
    over-release ``ValueError``).

    Drive >=2 codex children where the first exits non-zero (populating
    ``blockers``) so Phase 2 takes the ``if blockers: ... release(); break``
    straggler path on the next child, then the finally revisits that same child. A
    regression that swapped ``_one_shot_release`` for a plain ``_sem.release()``
    would raise ``ValueError`` here while every other test stayed green.
    """
    repo = _write_repo(tmp_path)
    _write_expanded_active_runner_fixture(repo)

    calls = {"n": 0}

    class _RcProc(_ReadProc):
        def __init__(self, pid: int, rc: int) -> None:
            super().__init__(pid=pid)
            self.returncode = rc

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            return self.returncode

    def fake_popen(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        # First codex child exits non-zero -> blockers populated -> the NEXT child
        # hits the blocker-break straggler path in Phase 2.
        return _RcProc(pid=9000 + calls["n"], rc=1 if calls["n"] == 1 else 0)

    import unittest.mock as _mock

    # Stub stop so the test isolates release accounting: the straggler is stopped
    # twice (inline break + finally), which must also be harmless.
    with _mock.patch.object(agent_loop, "_stop_codex_process", lambda p, *a, **k: None):
        result = agent_loop.write_active_codex_runner(
            execute=True,
            repo_root=repo,
            popen_factory=fake_popen,
            which_func=lambda exe: "/opt/codex/bin/codex",
            auth_runner=_chatgpt_auth_runner,
        )

    assert result.decision == "blocked"
    # Guard against a vacuous run: >=2 codex children must have spawned, else the
    # blocker-break straggler path (Phase 2 child #2 after child #1 populated
    # blockers) is never exercised and the test would pass trivially.
    assert calls["n"] >= 2, "fixture spawned <2 codex children -> blocker-break path not exercised"
    # No ValueError was raised (pytest would have failed); every permit is back
    # despite the straggler being release()'d inline and revisited by the finally.
    _assert_all_permits_restored(agent_loop.global_concurrency_limiter())
