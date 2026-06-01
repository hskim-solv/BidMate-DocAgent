from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest

from scripts import run_codex_adversarial_precommit as precommit


def _finding(
    *,
    severity: str = "high",
    file: str = "rag_core.py",
    line_start: int = 10,
    line_end: int = 12,
    title: str = "staged issue",
    confidence: float | None = None,
    recommendation: str = "Fix before committing.",
) -> dict[str, object]:
    out: dict[str, object] = {
        "severity": severity,
        "title": title,
        "body": "The staged change breaks the contract.",
        "file": file,
        "line_start": line_start,
        "line_end": line_end,
        "recommendation": recommendation,
    }
    if confidence is not None:
        out["confidence"] = confidence
    return out


def _payload(findings: list[dict[str, object]], verdict: str = "needs-attention") -> dict[str, object]:
    return {
        "result": {
            "verdict": verdict,
            "summary": "review",
            "findings": findings,
            "next_steps": [],
        },
        "parseError": None,
    }


def _proc(payload: dict[str, object], rc: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["node", "codex-companion.mjs"],
        returncode=rc,
        stdout=json.dumps(payload),
        stderr="",
    )


# ----- preserved unit coverage ---------------------------------------------


def test_load_bearing_hits_reuses_governance_paths():
    assert precommit.load_bearing_hits(["README.md", "rag_core.py", "docs/adr/0066-x.md"]) == [
        "rag_core.py",
        "docs/adr/0066-x.md",
    ]


def test_staged_files_includes_deletions(monkeypatch):
    # A commit that DELETES a load-bearing contract (e.g. an ADR or rag_core.py)
    # must still reach the load-bearing gate, so the discovery filter is ACMRD
    # (includes D), not ACMR. Mocked git runner keeps it deterministic — no real
    # load-bearing file required (AR2).
    captured: dict[str, object] = {}

    def fake_run_git(args):
        captured["args"] = list(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="docs/adr/0001-preserve-naive-baseline.md\nrag_core.py\n",
            stderr="",
        )

    monkeypatch.setattr(precommit, "_run_git", fake_run_git)

    files = precommit.staged_files()

    # The filter must request deletions.
    assert "--diff-filter=ACMRD" in captured["args"]
    # The (mock) deleted load-bearing path is surfaced and the load-bearing
    # filter recognises it → the gate would be invoked.
    assert "docs/adr/0001-preserve-naive-baseline.md" in files
    assert "docs/adr/0001-preserve-naive-baseline.md" in precommit.load_bearing_hits(files)


def test_default_out_dir_uses_actual_git_dir(monkeypatch):
    def fake_run_git(args):
        assert args == ["rev-parse", "--git-dir"]
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="/tmp/worktree-gitdir\n", stderr="")

    monkeypatch.setattr(precommit, "_run_git", fake_run_git)

    assert precommit.default_out_dir() == Path("/tmp/worktree-gitdir/codex-adversarial-precommit")


def test_build_focus_forces_staged_diff_scope():
    focus = precommit.build_focus(
        hits=["rag_core.py"],
        changed_files=["rag_core.py", "README.md"],
        attempt=2,
        attempts=3,
    )
    assert "git diff --cached" in focus
    assert "Pass 2/3" in focus
    assert "rag_core.py" in focus
    assert "README.md" in focus


# ----- cluster_findings -----------------------------------------------------


def test_cluster_findings_merges_overlapping_ranges():
    findings = [
        (1, _finding(file="rag_core.py", line_start=10, line_end=12)),
        (2, _finding(file="rag_core.py", line_start=11, line_end=15)),
    ]
    clusters = precommit.cluster_findings(findings)
    assert len(clusters) == 1
    assert clusters[0].line_lo == 10
    assert clusters[0].line_hi == 15
    assert clusters[0].frequency == 2


def test_cluster_findings_separates_different_files():
    findings = [
        (1, _finding(file="rag_core.py", line_start=10, line_end=12)),
        (2, _finding(file="rag_answer.py", line_start=10, line_end=12)),
    ]
    clusters = precommit.cluster_findings(findings)
    assert len(clusters) == 2
    assert {c.file for c in clusters} == {"rag_core.py", "rag_answer.py"}


def test_cluster_findings_gap_boundary_exactly_8_merges():
    # gap of exactly 8 lines: end=12 (pass1) and start=20 (pass2) → 20 <= 12 + 8 → merge.
    findings = [
        (1, _finding(line_start=10, line_end=12)),
        (2, _finding(line_start=20, line_end=22)),
    ]
    clusters = precommit.cluster_findings(findings)
    assert len(clusters) == 1
    assert clusters[0].frequency == 2


def test_cluster_findings_gap_boundary_9_splits():
    # gap of 9 lines: end=12 (pass1) and start=21 (pass2) → 21 > 12 + 8 → split.
    findings = [
        (1, _finding(line_start=10, line_end=12)),
        (2, _finding(line_start=21, line_end=23)),
    ]
    clusters = precommit.cluster_findings(findings)
    assert len(clusters) == 2


def test_cluster_findings_same_pass_duplicate_counts_once():
    findings = [
        (1, _finding(line_start=10, line_end=12)),
        (1, _finding(line_start=11, line_end=13)),
        (2, _finding(line_start=10, line_end=12)),
    ]
    clusters = precommit.cluster_findings(findings)
    assert len(clusters) == 1
    assert clusters[0].frequency == 2  # pass 1 reported twice but counts once
    assert len(clusters[0].members) == 3


def test_cluster_findings_none_lines_treated_as_zero():
    f = _finding(line_start=0, line_end=0)
    f["line_start"] = None
    f["line_end"] = None
    clusters = precommit.cluster_findings([(1, f)])
    assert len(clusters) == 1
    assert clusters[0].line_lo == 0
    assert clusters[0].line_hi == 0


def test_cluster_max_severity_takes_most_severe():
    findings = [
        (1, _finding(severity="medium", line_start=10, line_end=12)),
        (2, _finding(severity="critical", line_start=11, line_end=13)),
    ]
    clusters = precommit.cluster_findings(findings)
    assert len(clusters) == 1
    assert clusters[0].max_severity == "critical"


def test_cluster_representative_picks_highest_confidence():
    findings = [
        (1, _finding(line_start=10, line_end=12, confidence=0.4, title="low-conf")),
        (2, _finding(line_start=11, line_end=13, confidence=0.9, title="high-conf")),
    ]
    clusters = precommit.cluster_findings(findings)
    assert clusters[0].representative["title"] == "high-conf"


def test_severity_rank_orders_critical_first():
    assert precommit.severity_rank("critical") < precommit.severity_rank("high")
    assert precommit.severity_rank("high") < precommit.severity_rank("medium")
    assert precommit.severity_rank("medium") < precommit.severity_rank("low")
    assert precommit.severity_rank("bogus") > precommit.severity_rank("low")


# ----- frequency gate -------------------------------------------------------


def test_gate_blocks_when_strong_finding_reproduced(tmp_path: Path):
    def runner(cmd, timeout_sec):
        return _proc(_payload([_finding(severity="high", line_start=10, line_end=12)]))

    rc = precommit.run_precommit_review(
        attempts=4,
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
    assert rc == 1
    union = (tmp_path / "union.md").read_text(encoding="utf-8")
    assert "Blocking findings (1)" in union


def test_gate_passes_when_strong_finding_is_one_off(tmp_path: Path):
    # Each pass reports a DIFFERENT strong finding (freq 1 each) → none block.
    calls = {"n": 0}

    def runner(cmd, timeout_sec):
        calls["n"] += 1
        return _proc(_payload([_finding(severity="high", line_start=calls["n"] * 100, line_end=calls["n"] * 100 + 2)]))

    rc = precommit.run_precommit_review(
        attempts=4,
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
    union = (tmp_path / "union.md").read_text(encoding="utf-8")
    assert "Blocking findings (0)" in union
    assert "Informational findings (4)" in union


def test_gate_passes_when_reproduced_finding_is_medium(tmp_path: Path):
    def runner(cmd, timeout_sec):
        return _proc(_payload([_finding(severity="medium", line_start=10, line_end=12)]))

    rc = precommit.run_precommit_review(
        attempts=4,
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
    union = (tmp_path / "union.md").read_text(encoding="utf-8")
    assert "Blocking findings (0)" in union


def test_gate_passes_when_all_passes_empty(tmp_path: Path):
    def runner(cmd, timeout_sec):
        return _proc(_payload([], verdict="approve"))

    rc = precommit.run_precommit_review(
        attempts=4,
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
    assert "Blocking findings (0)" in (tmp_path / "union.md").read_text(encoding="utf-8")


# ----- parallel union collection -------------------------------------------


def test_parallel_passes_union_distinct_findings(tmp_path: Path):
    # Pass 1+2 share a finding (freq 2 → blocks); pass 3 reports a unique one (freq 1).
    sequence = iter(
        [
            _payload([_finding(severity="high", line_start=10, line_end=12, title="shared")]),
            _payload([_finding(severity="high", line_start=11, line_end=13, title="shared")]),
            _payload([_finding(severity="high", line_start=500, line_end=502, title="solo")]),
        ]
    )
    lock_free = list(sequence)
    idx = {"n": 0}

    def runner(cmd, timeout_sec):
        i = idx["n"]
        idx["n"] += 1
        return _proc(lock_free[i])

    rc = precommit.run_precommit_review(
        attempts=3,
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
    assert rc == 1
    union = json.loads((tmp_path / "union.json").read_text(encoding="utf-8"))
    # Two clusters: shared (freq 2, blocks) + solo (freq 1, informational).
    freqs = sorted(c["frequency"] for c in union["clusters"])
    assert freqs == [1, 2]
    assert union["attempts"] == 3


# ----- error passes ---------------------------------------------------------


def test_error_passes_do_not_stop_gate(tmp_path: Path):
    # Pass 1 fails (rc!=0), passes 2+3 report the same strong finding → still blocks.
    idx = {"n": 0}

    def runner(cmd, timeout_sec):
        i = idx["n"]
        idx["n"] += 1
        if i == 0:
            return subprocess.CompletedProcess(args=cmd, returncode=127, stdout="{}", stderr="companion missing")
        return _proc(_payload([_finding(severity="high", line_start=10, line_end=12)]))

    rc = precommit.run_precommit_review(
        attempts=3,
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
    assert rc == 1
    union = json.loads((tmp_path / "union.json").read_text(encoding="utf-8"))
    assert union["error_passes"] == 1
    assert any(c["frequency"] == 2 for c in union["clusters"])


def test_all_error_passes_return_one(tmp_path: Path):
    def runner(cmd, timeout_sec):
        return subprocess.CompletedProcess(args=cmd, returncode=127, stdout="{}", stderr="companion missing")

    rc = precommit.run_precommit_review(
        attempts=3,
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
    assert rc == 1


def test_timeout_pass_is_an_error_pass(tmp_path: Path):
    # One pass times out, the others succeed empty → all-error? no, gate proceeds, passes.
    idx = {"n": 0}

    def runner(cmd, timeout_sec):
        i = idx["n"]
        idx["n"] += 1
        if i == 0:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout_sec)
        return _proc(_payload([], verdict="approve"))

    rc = precommit.run_precommit_review(
        attempts=3,
        base="HEAD",
        scope="branch",
        companion=Path("/tmp/codex-companion.mjs"),
        changed_files=["rag_core.py"],
        hits=["rag_core.py"],
        out_dir=tmp_path,
        timeout_sec=7,
        min_frequency=2,
        runner=runner,
    )
    assert rc == 0
    union = json.loads((tmp_path / "union.json").read_text(encoding="utf-8"))
    assert union["error_passes"] == 1
    assert (tmp_path / "pass-1.err").read_text(encoding="utf-8")  # timeout stderr persisted


# ----- artifacts + runner injection -----------------------------------------


def test_per_pass_artifacts_written(tmp_path: Path):
    def runner(cmd, timeout_sec):
        return _proc(_payload([], verdict="approve"))

    precommit.run_precommit_review(
        attempts=3,
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
    for i in (1, 2, 3):
        assert (tmp_path / f"pass-{i}.json").exists()
        assert (tmp_path / f"pass-{i}.err").exists()
        assert (tmp_path / f"pass-{i}.md").exists()
    assert (tmp_path / "union.md").exists()
    assert (tmp_path / "union.json").exists()


def test_runner_receives_timeout_and_pass_numbering(tmp_path: Path):
    calls: list[list[str]] = []

    def runner(cmd, timeout_sec):
        calls.append(list(cmd))
        assert timeout_sec == 900
        return _proc(_payload([], verdict="approve"))

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
    assert len(calls) == 2
    foci = sorted(call[-1] for call in calls)
    assert any("Pass 1/2" in f for f in foci)
    assert any("Pass 2/2" in f for f in foci)


def test_run_precommit_review_rejects_zero_attempts(tmp_path: Path):
    with pytest.raises(ValueError, match="attempts"):
        precommit.run_precommit_review(
            attempts=0,
            base="HEAD",
            scope="branch",
            companion=Path("/tmp/codex-companion.mjs"),
            changed_files=["rag_core.py"],
            hits=["rag_core.py"],
            out_dir=tmp_path,
            timeout_sec=900,
            runner=lambda cmd, timeout_sec: _proc(_payload([], verdict="approve")),
        )


def test_run_precommit_review_rejects_zero_min_frequency(tmp_path: Path):
    with pytest.raises(ValueError, match="min-frequency"):
        precommit.run_precommit_review(
            attempts=2,
            base="HEAD",
            scope="branch",
            companion=Path("/tmp/codex-companion.mjs"),
            changed_files=["rag_core.py"],
            hits=["rag_core.py"],
            out_dir=tmp_path,
            timeout_sec=900,
            min_frequency=0,
            runner=lambda cmd, timeout_sec: _proc(_payload([], verdict="approve")),
        )


# ----- env parsing ----------------------------------------------------------


def test_env_min_frequency_default(monkeypatch):
    monkeypatch.delenv("BIDMATE_CODEX_ADVERSARIAL_MIN_FREQUENCY", raising=False)
    assert precommit._env_min_frequency() == precommit.DEFAULT_MIN_FREQUENCY


def test_env_min_frequency_override(monkeypatch):
    monkeypatch.setenv("BIDMATE_CODEX_ADVERSARIAL_MIN_FREQUENCY", "3")
    assert precommit._env_min_frequency() == 3


def test_env_min_frequency_rejects_non_integer(monkeypatch):
    monkeypatch.setenv("BIDMATE_CODEX_ADVERSARIAL_MIN_FREQUENCY", "two")
    with pytest.raises(ValueError, match="BIDMATE_CODEX_ADVERSARIAL_MIN_FREQUENCY"):
        precommit._env_min_frequency()


def test_env_attempts_default_is_eight(monkeypatch):
    monkeypatch.delenv("BIDMATE_CODEX_ADVERSARIAL_ATTEMPTS", raising=False)
    assert precommit._env_attempts() == 8
    assert precommit.DEFAULT_ATTEMPTS == 8


def test_sanitized_env_strips_git_and_broker():
    base = {
        "PATH": "/usr/bin",
        "HOME": "/home/u",
        "GIT_INDEX_FILE": "/x/.git/index",
        "GIT_DIR": "/x/.git",
        "GIT_WORK_TREE": "/x",
        "GIT_OBJECT_DIRECTORY": "/x/.git/objects",
        "GIT_COMMON_DIR": "/x/.git",
        "CODEX_COMPANION_APP_SERVER_ENDPOINT": "unix:/tmp/sock",
    }
    out = precommit.sanitized_env(base)
    # Non-git env is preserved.
    assert out["PATH"] == "/usr/bin"
    assert out["HOME"] == "/home/u"
    # Every inherited git var + the broker endpoint is dropped so Codex's own
    # git ops cannot mutate this worktree's index (index-corruption root cause).
    assert not any(k.startswith("GIT_") for k in out)
    assert "CODEX_COMPANION_APP_SERVER_ENDPOINT" not in out


def test_sanitized_env_strips_ship_secrets_from_os_environ(monkeypatch):
    # The auto-ship Stop-hook can export BIDMATE_SHIP_* (merge tokens etc.) while
    # a commit is created. sanitized_env() — which feeds the third-party Codex
    # review subprocess — must drop every BIDMATE_SHIP_* key while preserving the
    # benign env (PATH/HOME) and keeping the existing GIT_*/endpoint drops (AR1).
    monkeypatch.setenv("BIDMATE_SHIP_MERGE_TOKEN", "tok-secret")
    monkeypatch.setenv("BIDMATE_SHIP_AUTO_PR", "1")
    monkeypatch.setenv("GIT_DIR", "/x/.git")
    monkeypatch.setenv("CODEX_COMPANION_APP_SERVER_ENDPOINT", "unix:/tmp/sock")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/home/u")

    out = precommit.sanitized_env()  # reads os.environ

    assert not any(k.startswith("BIDMATE_SHIP_") for k in out)
    assert "BIDMATE_SHIP_MERGE_TOKEN" not in out
    # Benign env survives and the existing GIT_*/endpoint drops still hold.
    assert out["PATH"] == "/usr/bin"
    assert out["HOME"] == "/home/u"
    assert not any(k.startswith("GIT_") for k in out)
    assert "CODEX_COMPANION_APP_SERVER_ENDPOINT" not in out


def test_sanitized_env_delegates_ship_strip_to_shared_helper(monkeypatch):
    # AR1 dedup (#1703 follow-up): the BIDMATE_SHIP_* deny-list has one source of
    # truth in scripts/_ship_env.strip_ship_secret_env. Assert sanitized_env routes
    # ship-secret removal through that shared helper so the prefix can never drift
    # between this call site and the staging-ship runner.
    seen: dict[str, dict[str, str]] = {}
    real_strip = precommit.strip_ship_secret_env

    def spy(env: dict[str, str]) -> dict[str, str]:
        seen["received"] = dict(env)
        return real_strip(env)

    monkeypatch.setattr(precommit, "strip_ship_secret_env", spy)
    base = {
        "PATH": "/usr/bin",
        "GIT_DIR": "/x/.git",
        "BIDMATE_SHIP_MERGE_TOKEN": "tok-secret",
    }
    out = precommit.sanitized_env(base)

    # The shared helper was invoked, and GIT_* was already dropped before delegation.
    assert "received" in seen
    assert "GIT_DIR" not in seen["received"]
    # Ship secret removed by the helper; benign env preserved.
    assert "BIDMATE_SHIP_MERGE_TOKEN" not in out
    assert out["PATH"] == "/usr/bin"


# ----- policy-aware cache (issue #1710) ------------------------------------


def _make_policy_runner(calls: dict[str, int]) -> precommit.Runner:
    """Runner that records how many times it was invoked and returns an empty payload."""

    def runner(cmd, timeout_sec):
        calls["n"] = calls.get("n", 0) + 1
        return _proc(_payload([]))

    return runner


def test_policy_digest_differs_on_attempts_change():
    """Different attempts values must produce different policy digests."""
    d1 = precommit._policy_digest(attempts=2, min_frequency=1, timeout_sec=900)
    d2 = precommit._policy_digest(attempts=4, min_frequency=1, timeout_sec=900)
    assert d1 != d2


def test_policy_digest_differs_on_min_frequency_change():
    """Different min_frequency values must produce different policy digests."""
    d1 = precommit._policy_digest(attempts=4, min_frequency=1, timeout_sec=900)
    d2 = precommit._policy_digest(attempts=4, min_frequency=2, timeout_sec=900)
    assert d1 != d2


def test_policy_digest_differs_on_timeout_change():
    """Different timeout_sec values must produce different policy digests."""
    d1 = precommit._policy_digest(attempts=4, min_frequency=2, timeout_sec=300)
    d2 = precommit._policy_digest(attempts=4, min_frequency=2, timeout_sec=900)
    assert d1 != d2


def test_policy_digest_stable_for_same_policy():
    """Same policy must always produce the same digest."""
    d1 = precommit._policy_digest(attempts=4, min_frequency=2, timeout_sec=900)
    d2 = precommit._policy_digest(attempts=4, min_frequency=2, timeout_sec=900)
    assert d1 == d2


def test_cache_miss_on_policy_change_triggers_rerun(tmp_path: Path, monkeypatch):
    """Seeding a cache under policy A then running under policy B (attempts changed)
    must cause a cache miss and a real review run — not a stale verdict replay
    (regression for issue #1710).
    """
    # Patch _staged_diff_digest to return a fixed digest so the diff is "unchanged".
    fixed_digest = "a" * 64
    monkeypatch.setattr(precommit, "_staged_diff_digest", lambda: fixed_digest)

    call_count: dict[str, int] = {}

    # --- First run: policy A (attempts=2, min_frequency=1) ---
    runner_a = _make_policy_runner(call_count)
    precommit.run_precommit_review(
        attempts=2,
        base="HEAD",
        scope="branch",
        companion=Path("/tmp/codex-companion.mjs"),
        changed_files=["rag_core.py"],
        hits=["rag_core.py"],
        out_dir=tmp_path,
        timeout_sec=900,
        min_frequency=1,
        runner=runner_a,
    )
    assert call_count.get("n", 0) == 2, "policy A: should have run 2 passes"

    # --- Second run: same diff, same policy A → cache hit, 0 new passes ---
    call_count.clear()
    runner_a2 = _make_policy_runner(call_count)
    precommit.run_precommit_review(
        attempts=2,
        base="HEAD",
        scope="branch",
        companion=Path("/tmp/codex-companion.mjs"),
        changed_files=["rag_core.py"],
        hits=["rag_core.py"],
        out_dir=tmp_path,
        timeout_sec=900,
        min_frequency=1,
        runner=runner_a2,
    )
    assert call_count.get("n", 0) == 0, "policy A repeat: must be a cache hit (0 passes)"

    # --- Third run: same diff, CHANGED policy (attempts=4, min_frequency=2) ---
    # Despite identical diff, the policy changed → must be a cache miss → rerun.
    call_count.clear()
    runner_b = _make_policy_runner(call_count)
    precommit.run_precommit_review(
        attempts=4,
        base="HEAD",
        scope="branch",
        companion=Path("/tmp/codex-companion.mjs"),
        changed_files=["rag_core.py"],
        hits=["rag_core.py"],
        out_dir=tmp_path,
        timeout_sec=900,
        min_frequency=2,
        runner=runner_b,
    )
    assert call_count.get("n", 0) == 4, (
        "policy B (attempts changed): must be a cache MISS and run 4 fresh passes"
    )


def test_cache_miss_on_min_frequency_change(tmp_path: Path, monkeypatch):
    """Changing only min_frequency must bust the cache (issue #1710)."""
    fixed_digest = "b" * 64
    monkeypatch.setattr(precommit, "_staged_diff_digest", lambda: fixed_digest)

    call_count: dict[str, int] = {}

    # Seed cache with min_frequency=1.
    precommit.run_precommit_review(
        attempts=2,
        base="HEAD",
        scope="branch",
        companion=Path("/tmp/codex-companion.mjs"),
        changed_files=["rag_core.py"],
        hits=["rag_core.py"],
        out_dir=tmp_path,
        timeout_sec=900,
        min_frequency=1,
        runner=_make_policy_runner(call_count),
    )
    assert call_count.get("n", 0) == 2

    # Re-run with min_frequency=2 (same diff, same attempts, different threshold).
    call_count.clear()
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
        runner=_make_policy_runner(call_count),
    )
    assert call_count.get("n", 0) == 2, "min_frequency change must bust the cache"


def test_cache_miss_on_timeout_change(tmp_path: Path, monkeypatch):
    """Changing only timeout_sec must bust the cache (issue #1710)."""
    fixed_digest = "c" * 64
    monkeypatch.setattr(precommit, "_staged_diff_digest", lambda: fixed_digest)

    call_count: dict[str, int] = {}

    # Seed cache with timeout_sec=300.
    precommit.run_precommit_review(
        attempts=2,
        base="HEAD",
        scope="branch",
        companion=Path("/tmp/codex-companion.mjs"),
        changed_files=["rag_core.py"],
        hits=["rag_core.py"],
        out_dir=tmp_path,
        timeout_sec=300,
        min_frequency=1,
        runner=_make_policy_runner(call_count),
    )
    assert call_count.get("n", 0) == 2

    # Re-run with timeout_sec=900.
    call_count.clear()
    precommit.run_precommit_review(
        attempts=2,
        base="HEAD",
        scope="branch",
        companion=Path("/tmp/codex-companion.mjs"),
        changed_files=["rag_core.py"],
        hits=["rag_core.py"],
        out_dir=tmp_path,
        timeout_sec=900,
        min_frequency=1,
        runner=_make_policy_runner(call_count),
    )
    assert call_count.get("n", 0) == 2, "timeout_sec change must bust the cache"


def test_load_cached_result_rejects_schema_v1_entry(tmp_path: Path):
    """A cache entry written with schema_version=1 (pre-policy) must be a miss
    after the schema bump to version 2 (issue #1710).
    """
    diff_digest = "d" * 64
    pol_dgst = precommit._policy_digest(attempts=2, min_frequency=1, timeout_sec=900)
    # Write a v1-style entry directly (no policy fields).
    cache_dir = tmp_path / precommit._CACHE_SUBDIR
    cache_dir.mkdir()
    # Compute expected composite path to place the stale file there.
    stale_path = precommit._cache_path(tmp_path, diff_digest, pol_dgst)
    import json as _json
    stale_path.write_text(
        _json.dumps({
            "schema_version": 1,
            "digest": diff_digest,
            "rc": 0,
        }),
        encoding="utf-8",
    )
    result = precommit._load_cached_result(tmp_path, diff_digest, pol_dgst)
    assert result is None, "schema_version=1 entry must be treated as a cache miss"


def test_load_cached_result_rejects_wrong_policy_digest(tmp_path: Path):
    """An entry whose stored policy_digest doesn't match the current policy is a miss."""
    import json as _json

    diff_digest = "e" * 64
    pol_dgst_a = precommit._policy_digest(attempts=2, min_frequency=1, timeout_sec=900)
    pol_dgst_b = precommit._policy_digest(attempts=4, min_frequency=2, timeout_sec=900)

    # Write a valid v2 entry under pol_dgst_b's path but with pol_dgst_a as stored value.
    path = precommit._cache_path(tmp_path, diff_digest, pol_dgst_b)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _json.dumps({
            "schema_version": precommit._CACHE_SCHEMA_VERSION,
            "digest": diff_digest,
            "policy_digest": pol_dgst_a,  # deliberately mismatched
            "rc": 0,
        }),
        encoding="utf-8",
    )
    result = precommit._load_cached_result(tmp_path, diff_digest, pol_dgst_b)
    assert result is None, "policy_digest mismatch must be treated as a cache miss"


def test_default_runner_passes_sanitized_env(monkeypatch):
    # _default_runner now uses Popen(start_new_session=True) so it can reap the
    # companion's detached broker/app-server process group (issue #1699). The
    # sanitized-env contract is unchanged: no inherited GIT_* vars reach Codex.
    captured: dict[str, object] = {}

    class _FakeProc:
        pid = 4321
        returncode = 0

        def communicate(self, timeout=None):
            return ("{}", "")

    def fake_popen(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        captured["start_new_session"] = kwargs.get("start_new_session")
        return _FakeProc()

    monkeypatch.setenv("GIT_DIR", "/x/.git")
    monkeypatch.setenv("GIT_INDEX_FILE", "/x/.git/index")
    monkeypatch.setattr(precommit.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(precommit, "_killpg", lambda *a, **k: None)
    precommit._default_runner(["node", "companion"], 10)
    env = captured["env"]
    assert isinstance(env, dict)
    assert not any(k.startswith("GIT_") for k in env)
    assert captured["start_new_session"] is True


def test_run_precommit_review_rejects_min_frequency_above_attempts(tmp_path: Path):
    # MIN_FREQUENCY > ATTEMPTS would mean no finding can ever reach the
    # threshold, silently disabling the gate. Reject the config up front.
    def runner(cmd, timeout_sec):
        return _proc(_payload([]))

    with pytest.raises(ValueError, match="must be <="):
        precommit.run_precommit_review(
            attempts=8,
            base="HEAD",
            scope="branch",
            companion=Path("/tmp/codex-companion.mjs"),
            changed_files=["rag_core.py"],
            hits=["rag_core.py"],
            out_dir=tmp_path,
            timeout_sec=900,
            min_frequency=10,
            runner=runner,
        )


def test_gate_fails_closed_when_too_few_passes_succeed(tmp_path: Path):
    # attempts=4, min_frequency=2: only 1 pass succeeds (with a strong finding),
    # 3 error. successful_passes (1) < min_frequency (2) → reproduction can't be
    # confirmed → fail-closed block, instead of silently passing on a partial
    # companion outage.
    lock = threading.Lock()
    state = {"successes": 0}

    def runner(cmd, timeout_sec):
        with lock:
            if state["successes"] < 1:
                state["successes"] += 1
                return _proc(_payload([_finding(severity="high", line_start=10, line_end=12)]))
        return subprocess.CompletedProcess(
            args=cmd, returncode=127, stdout="{}", stderr="companion missing"
        )

    rc = precommit.run_precommit_review(
        attempts=4,
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
    assert rc == 1
