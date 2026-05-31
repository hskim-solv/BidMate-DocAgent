"""Resource-hygiene tests for the codex adversarial pre-commit gate (issue #1699).

Covers the three additions that keep the gate contract unchanged while stopping
broker/app-server accumulation:

- (C) `reap_orphaned_brokers` — selectively removes stale/orphaned `cxc-*` broker
  run-dirs and NEVER touches a live, parented session.
- (A) diff-fingerprint cache — an identical staged diff reuses the prior verdict
  with 0 codex passes; a corrupt cache entry falls back to a real run.
- (B) `_default_runner` — on timeout, the whole process group is killed (killpg),
  exercised through a fake Popen/os.killpg seam (no real codex spawned).
"""
from __future__ import annotations

import json
import signal
import subprocess
from pathlib import Path

import pytest

from scripts import run_codex_adversarial_precommit as precommit


# --------------------------------------------------------------------------- #
# (C) reap_orphaned_brokers
# --------------------------------------------------------------------------- #


def _make_broker_dir(base: Path, name: str, pid_text: str | None) -> Path:
    d = base / name
    d.mkdir()
    (d / "broker.log").write_text("", encoding="utf-8")
    (d / "broker.sock").write_text("", encoding="utf-8")
    if pid_text is not None:
        (d / "broker.pid").write_text(pid_text, encoding="utf-8")
    return d


def test_reap_removes_dead_keeps_live_parented_and_removes_malformed(tmp_path, monkeypatch):
    # (a) dead pid → removed; (b) live + parented → kept; (c) empty pid → removed.
    dead = _make_broker_dir(tmp_path, "cxc-dead", "1111")
    live = _make_broker_dir(tmp_path, "cxc-live", "2222")
    empty = _make_broker_dir(tmp_path, "cxc-empty", "")
    # A non-cxc dir must never be scanned/removed.
    unrelated = tmp_path / "not-a-broker"
    unrelated.mkdir()

    alive = {1111: False, 2222: True}
    ppids = {2222: 4242}  # live broker has a live companion parent → keep

    monkeypatch.setattr(precommit, "_pid_alive", lambda pid: alive.get(pid, False))
    monkeypatch.setattr(precommit, "_pid_ppid", lambda pid: ppids.get(pid))
    # Safety: the reaper must not signal a parented (kept) broker.
    monkeypatch.setattr(
        precommit, "_killpg", lambda *a, **k: pytest.fail("must not killpg a kept broker")
    )

    counts = precommit.reap_orphaned_brokers(base_dir=tmp_path)

    assert counts == {"stale": 2, "orphaned": 0, "kept": 1}
    assert not dead.exists()
    assert not empty.exists()
    assert live.exists()  # live, parented session preserved (safety)
    assert unrelated.exists()  # non-cxc dir untouched


def test_reap_terminates_orphaned_broker(tmp_path, monkeypatch):
    # Live broker whose parent is gone (ppid == 1) → SIGTERM + dir removed.
    orphan = _make_broker_dir(tmp_path, "cxc-orphan", "3333")
    killed: list[tuple[int, int]] = []

    monkeypatch.setattr(precommit, "_pid_alive", lambda pid: pid == 3333)
    monkeypatch.setattr(precommit, "_pid_ppid", lambda pid: 1)
    monkeypatch.setattr(precommit, "_killpg", lambda pid, sig: killed.append((pid, sig)))

    counts = precommit.reap_orphaned_brokers(base_dir=tmp_path)

    assert counts == {"stale": 0, "orphaned": 1, "kept": 0}
    assert killed == [(3333, signal.SIGTERM)]
    assert not orphan.exists()


def test_reap_keeps_broker_when_ppid_unknown(tmp_path, monkeypatch):
    # ppid cannot be determined → fail safe: do NOT kill, keep the dir.
    keep = _make_broker_dir(tmp_path, "cxc-unknown", "4444")
    monkeypatch.setattr(precommit, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(precommit, "_pid_ppid", lambda pid: None)
    monkeypatch.setattr(
        precommit, "_killpg", lambda *a, **k: pytest.fail("must not killpg on unknown ppid")
    )

    counts = precommit.reap_orphaned_brokers(base_dir=tmp_path)

    assert counts == {"stale": 0, "orphaned": 0, "kept": 1}
    assert keep.exists()


def test_reap_missing_pid_file_is_stale(tmp_path, monkeypatch):
    half = _make_broker_dir(tmp_path, "cxc-nopid", pid_text=None)
    monkeypatch.setattr(precommit, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(precommit, "_pid_ppid", lambda pid: 1)

    counts = precommit.reap_orphaned_brokers(base_dir=tmp_path)

    assert counts["stale"] == 1
    assert not half.exists()


def test_reap_missing_base_dir_returns_zero_counts(tmp_path):
    counts = precommit.reap_orphaned_brokers(base_dir=tmp_path / "does-not-exist")
    assert counts == {"stale": 0, "orphaned": 0, "kept": 0}


def test_reap_default_base_dirs_cover_tmpdir_and_macos_default(monkeypatch):
    # With no base_dir, the reaper scans a deduped SET of candidate roots —
    # tempfile.gettempdir() + $TMPDIR + the macOS /var/folders default — so a
    # broker under EITHER root is reachable (AR3). Single-root scoping missed
    # orphans accumulating in the other tmp root.
    import tempfile

    globbed: list[Path] = []

    def fake_glob(self, pattern):  # noqa: ANN001
        assert pattern == "cxc-*"
        globbed.append(self)
        return []

    monkeypatch.setenv("TMPDIR", "/tmp/claude-501")
    monkeypatch.setattr(precommit, "_macos_default_temp_dir", lambda: "/var/folders/ab/cd/T")
    monkeypatch.setattr(Path, "glob", fake_glob)

    precommit.reap_orphaned_brokers()  # no base_dir → default candidate set

    assert Path(tempfile.gettempdir()) in globbed
    assert Path("/var/folders/ab/cd/T") in globbed
    # Deduped: /tmp/claude-501 appears once even though gettempdir() == $TMPDIR here.
    assert globbed.count(Path("/tmp/claude-501")) == 1


def test_reap_default_base_dirs_deduped_when_no_macos_default(monkeypatch):
    # gettempdir() == $TMPDIR and no macOS default available → a single scan.
    import tempfile

    globbed: list[Path] = []

    def fake_glob(self, pattern):  # noqa: ANN001
        globbed.append(self)
        return []

    monkeypatch.setenv("TMPDIR", tempfile.gettempdir())
    monkeypatch.setattr(precommit, "_macos_default_temp_dir", lambda: None)
    monkeypatch.setattr(Path, "glob", fake_glob)

    precommit.reap_orphaned_brokers()

    assert globbed == [Path(tempfile.gettempdir())]


def test_reap_multi_base_scans_all_and_preserves_live_parented(tmp_path, monkeypatch):
    # AR3 core: base A has a dead-pid broker (stale → removed); base B has a
    # live, PARENTED broker (e.g. the active shared-session broker under
    # /var/folders) → it must be KEPT, never signalled, while base A is still
    # cleaned. Both roots must be scanned in one reap call.
    base_a = tmp_path / "tmp_root_a"
    base_b = tmp_path / "var_folders_root_b"
    base_a.mkdir()
    base_b.mkdir()

    dead = _make_broker_dir(base_a, "cxc-dead", "1111")  # dead pid → stale
    live = _make_broker_dir(base_b, "cxc-live-session", "2222")  # alive + parented → keep

    alive = {1111: False, 2222: True}
    ppids = {2222: 4242}  # live broker has a live companion parent → keep

    monkeypatch.setattr(precommit, "_pid_alive", lambda pid: alive.get(pid, False))
    monkeypatch.setattr(precommit, "_pid_ppid", lambda pid: ppids.get(pid))
    monkeypatch.setattr(
        precommit,
        "_killpg",
        lambda *a, **k: pytest.fail("must not killpg a live-parented broker across bases"),
    )

    counts = precommit.reap_orphaned_brokers(base_dirs=[base_a, base_b])

    assert counts == {"stale": 1, "orphaned": 0, "kept": 1}
    assert not dead.exists()  # base A cleaned
    assert live.exists()  # base B live-parented session preserved (safety)


def test_reap_multi_base_terminates_orphan_in_second_root(tmp_path, monkeypatch):
    # An orphan (alive, ppid==1) sitting in the SECOND candidate root must still
    # be SIGTERM'd + removed — proving the orphan logic runs per-base, not just
    # on the first root.
    base_a = tmp_path / "root_a"
    base_b = tmp_path / "root_b"
    base_a.mkdir()
    base_b.mkdir()

    orphan = _make_broker_dir(base_b, "cxc-orphan", "3333")
    killed: list[tuple[int, int]] = []

    monkeypatch.setattr(precommit, "_pid_alive", lambda pid: pid == 3333)
    monkeypatch.setattr(precommit, "_pid_ppid", lambda pid: 1)
    monkeypatch.setattr(precommit, "_killpg", lambda pid, sig: killed.append((pid, sig)))

    counts = precommit.reap_orphaned_brokers(base_dirs=[base_a, base_b])

    assert counts == {"stale": 0, "orphaned": 1, "kept": 0}
    assert killed == [(3333, signal.SIGTERM)]
    assert not orphan.exists()


# --------------------------------------------------------------------------- #
# (A) diff-fingerprint cache
# --------------------------------------------------------------------------- #


def _approve_runner(cmd, timeout_sec):  # noqa: ANN001
    payload = {
        "result": {"verdict": "approve", "summary": "ok", "findings": [], "next_steps": []},
        "parseError": None,
    }
    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=json.dumps(payload), stderr="")


def test_diff_cache_hit_runs_zero_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(precommit, "_staged_diff_digest", lambda: "deadbeef" * 8)
    calls = {"n": 0}

    def runner(cmd, timeout_sec):  # noqa: ANN001
        calls["n"] += 1
        return _approve_runner(cmd, timeout_sec)

    # First run = miss → writes the cache.
    rc1 = precommit.run_precommit_review(
        attempts=2,
        base="HEAD",
        scope="branch",
        companion=Path("/tmp/codex-companion.mjs"),
        changed_files=["rag_core.py"],
        hits=["rag_core.py"],
        out_dir=tmp_path,
        timeout_sec=900,
        min_frequency=2,
        runner=runner,
    )
    assert rc1 == 0
    assert calls["n"] == 2  # 2 passes on a miss
    assert precommit._cache_path(tmp_path, "deadbeef" * 8).exists()

    # Second run, identical digest = HIT → 0 additional runner invocations.
    calls["n"] = 0
    rc2 = precommit.run_precommit_review(
        attempts=2,
        base="HEAD",
        scope="branch",
        companion=Path("/tmp/codex-companion.mjs"),
        changed_files=["rag_core.py"],
        hits=["rag_core.py"],
        out_dir=tmp_path,
        timeout_sec=900,
        min_frequency=2,
        runner=runner,
    )
    assert rc2 == 0
    assert calls["n"] == 0  # cache hit: NO codex pass spawned


def test_diff_cache_different_digest_is_fresh_run(tmp_path, monkeypatch):
    digests = iter(["a" * 64, "b" * 64])
    monkeypatch.setattr(precommit, "_staged_diff_digest", lambda: next(digests))
    calls = {"n": 0}

    def runner(cmd, timeout_sec):  # noqa: ANN001
        calls["n"] += 1
        return _approve_runner(cmd, timeout_sec)

    for _ in range(2):
        precommit.run_precommit_review(
            attempts=2,
            base="HEAD",
            scope="branch",
            companion=Path("/tmp/codex-companion.mjs"),
            changed_files=["rag_core.py"],
            hits=["rag_core.py"],
            out_dir=tmp_path,
            timeout_sec=900,
            min_frequency=2,
            runner=runner,
        )
    # Both runs missed (distinct digests) → both spawned their passes.
    assert calls["n"] == 4


def test_diff_cache_corrupt_entry_falls_back_to_real_run(tmp_path, monkeypatch):
    digest = "c" * 64
    monkeypatch.setattr(precommit, "_staged_diff_digest", lambda: digest)
    # Pre-seed a corrupt cache entry.
    cache_path = precommit._cache_path(tmp_path, digest)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("{ this is not json", encoding="utf-8")

    calls = {"n": 0}

    def runner(cmd, timeout_sec):  # noqa: ANN001
        calls["n"] += 1
        return _approve_runner(cmd, timeout_sec)

    rc = precommit.run_precommit_review(
        attempts=2,
        base="HEAD",
        scope="branch",
        companion=Path("/tmp/codex-companion.mjs"),
        changed_files=["rag_core.py"],
        hits=["rag_core.py"],
        out_dir=tmp_path,
        timeout_sec=900,
        min_frequency=2,
        runner=runner,
    )
    assert rc == 0
    assert calls["n"] == 2  # corrupt entry → real run (fail-open), not a crash
    # The corrupt entry is overwritten with a valid one.
    assert isinstance(json.loads(cache_path.read_text(encoding="utf-8")), dict)


def test_diff_cache_no_digest_disables_cache(tmp_path, monkeypatch):
    # When the staged diff digest cannot be computed (None), the cache is a no-op:
    # every run is fresh and nothing is written.
    monkeypatch.setattr(precommit, "_staged_diff_digest", lambda: None)
    calls = {"n": 0}

    def runner(cmd, timeout_sec):  # noqa: ANN001
        calls["n"] += 1
        return _approve_runner(cmd, timeout_sec)

    precommit.run_precommit_review(
        attempts=2,
        base="HEAD",
        scope="branch",
        companion=Path("/tmp/codex-companion.mjs"),
        changed_files=["rag_core.py"],
        hits=["rag_core.py"],
        out_dir=tmp_path,
        timeout_sec=900,
        min_frequency=2,
        runner=runner,
    )
    assert calls["n"] == 2
    assert not (tmp_path / precommit._CACHE_SUBDIR).exists()


def test_run_precommit_review_auto_reaps_on_exit(tmp_path, monkeypatch):
    # The reaper runs in a finally after every review (hit or miss).
    monkeypatch.setattr(precommit, "_staged_diff_digest", lambda: None)
    reaped = {"n": 0}
    monkeypatch.setattr(
        precommit,
        "reap_orphaned_brokers",
        lambda *a, **k: reaped.__setitem__("n", reaped["n"] + 1) or {"stale": 0, "orphaned": 0, "kept": 0},
    )

    precommit.run_precommit_review(
        attempts=2,
        base="HEAD",
        scope="branch",
        companion=Path("/tmp/codex-companion.mjs"),
        changed_files=["rag_core.py"],
        hits=["rag_core.py"],
        out_dir=tmp_path,
        timeout_sec=900,
        min_frequency=2,
        runner=_approve_runner,
    )
    assert reaped["n"] == 1


# --------------------------------------------------------------------------- #
# (B) _default_runner process-group reap
# --------------------------------------------------------------------------- #


class _FakeProc:
    def __init__(self, *, timeout_then_done: bool):
        self.pid = 99999
        self.returncode = 0
        self._calls = 0
        self._timeout_then_done = timeout_then_done

    def communicate(self, timeout=None):  # noqa: ANN001
        self._calls += 1
        if self._timeout_then_done and self._calls == 1:
            raise subprocess.TimeoutExpired(cmd=["node"], timeout=timeout)
        return ("out", "err")


def test_default_runner_killpg_on_timeout(monkeypatch):
    # On the initial communicate() TimeoutExpired, _default_runner must killpg the
    # whole group (SIGTERM), drain, and re-raise TimeoutExpired — no real codex.
    fake = _FakeProc(timeout_then_done=True)
    monkeypatch.setattr(precommit.subprocess, "Popen", lambda *a, **k: fake)
    killed: list[int] = []
    monkeypatch.setattr(precommit, "_killpg", lambda pid, sig: killed.append(sig))

    with pytest.raises(subprocess.TimeoutExpired):
        precommit._default_runner(["node", "companion"], 5)

    # SIGTERM on timeout, plus the finally SIGTERM = at least one SIGTERM issued.
    assert signal.SIGTERM in killed


def test_default_runner_killpg_in_finally_on_success(monkeypatch):
    # Even a clean completion reaps the (now-empty) group in the finally so no
    # detached companion child can survive.
    fake = _FakeProc(timeout_then_done=False)
    monkeypatch.setattr(precommit.subprocess, "Popen", lambda *a, **k: fake)
    killed: list[int] = []
    monkeypatch.setattr(precommit, "_killpg", lambda pid, sig: killed.append(sig))

    result = precommit._default_runner(["node", "companion"], 5)

    assert result.returncode == 0
    assert result.stdout == "out"
    assert result.stderr == "err"
    assert killed == [signal.SIGTERM]  # finally-path reap on success


def test_default_runner_spawns_in_new_session_with_sanitized_env(monkeypatch):
    captured: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):  # noqa: ANN001
        captured["start_new_session"] = kwargs.get("start_new_session")
        captured["env"] = kwargs.get("env")
        return _FakeProc(timeout_then_done=False)

    monkeypatch.setenv("GIT_DIR", "/x/.git")
    monkeypatch.setattr(precommit.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(precommit, "_killpg", lambda *a, **k: None)

    precommit._default_runner(["node", "companion"], 5)

    assert captured["start_new_session"] is True
    env = captured["env"]
    assert isinstance(env, dict)
    assert not any(k.startswith("GIT_") for k in env)  # sanitized_env preserved


def test_killpg_swallows_process_lookup(monkeypatch):
    # _killpg must never raise when the group is already gone.
    def boom(pid):  # noqa: ANN001
        raise ProcessLookupError

    monkeypatch.setattr(precommit.os, "getpgid", boom)
    precommit._killpg(12345, signal.SIGTERM)  # no exception
