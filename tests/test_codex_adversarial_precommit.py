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


def test_default_runner_passes_sanitized_env(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setenv("GIT_DIR", "/x/.git")
    monkeypatch.setenv("GIT_INDEX_FILE", "/x/.git/index")
    monkeypatch.setattr(precommit.subprocess, "run", fake_run)
    precommit._default_runner(["node", "companion"], 10)
    env = captured["env"]
    assert isinstance(env, dict)
    assert not any(k.startswith("GIT_") for k in env)


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
