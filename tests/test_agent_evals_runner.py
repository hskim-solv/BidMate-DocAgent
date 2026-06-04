from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(rel_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# oracle.decide_verdict — exhaustive fail-closed decision table                #
# --------------------------------------------------------------------------- #


def _oracle():
    return load_module("agent-evals/core/oracle.py", "agent_evals_oracle_runner_test")


def test_decide_verdict_hard_gate_rejects_outright() -> None:
    oracle = _oracle()
    gates = oracle.GateResults(
        hidden_test_gate=True,
        pytest_pass=True,
        regression_pass=True,
        hard_gates=(oracle.HardGate.SECRET_LEAK,),
    )
    tier = oracle.decide_verdict(
        gates,
        oracle.ReviewerVerdict(accepted=True, reviewer_family="other", reason_code="ok"),
        candidate_family="cand",
        public_attestation=True,
    )
    assert tier is oracle.VerdictTier.REJECTED_HARD_GATE
    assert not oracle.is_accepted(tier)


def test_decide_verdict_necessary_gate_failure_rejects() -> None:
    oracle = _oracle()
    gates = oracle.GateResults(hidden_test_gate=True, pytest_pass=False, regression_pass=True)
    tier = oracle.decide_verdict(
        gates,
        oracle.ReviewerVerdict(accepted=True, reviewer_family="other", reason_code="ok"),
        candidate_family="cand",
        public_attestation=True,
    )
    assert tier is oracle.VerdictTier.REJECTED_NECESSARY_GATE


def test_decide_verdict_egress_closed_caps_at_necessary_gate_only() -> None:
    oracle = _oracle()
    gates = oracle.GateResults(hidden_test_gate=True, pytest_pass=True, regression_pass=True)
    # Even with an accepting cross-family reviewer object, a closed egress gate must
    # cap the tier — the payload never left, so acceptance is unprovable.
    tier = oracle.decide_verdict(
        gates,
        oracle.ReviewerVerdict(accepted=True, reviewer_family="other", reason_code="ok"),
        candidate_family="cand",
        public_attestation=False,
    )
    assert tier is oracle.VerdictTier.NECESSARY_GATE_ONLY


def test_decide_verdict_public_but_no_reviewer_caps_at_necessary_gate_only() -> None:
    oracle = _oracle()
    gates = oracle.GateResults(hidden_test_gate=True, pytest_pass=True, regression_pass=True)
    tier = oracle.decide_verdict(
        gates,
        None,
        candidate_family="cand",
        public_attestation=True,
    )
    assert tier is oracle.VerdictTier.NECESSARY_GATE_ONLY


def test_decide_verdict_same_family_reviewer_is_neutralized() -> None:
    oracle = _oracle()
    gates = oracle.GateResults(hidden_test_gate=True, pytest_pass=True, regression_pass=True)
    # Same-family self-judge (ADR 0064): even an accepting verdict is neutralized.
    tier = oracle.decide_verdict(
        gates,
        oracle.ReviewerVerdict(accepted=True, reviewer_family="cand", reason_code="ok"),
        candidate_family="cand",
        public_attestation=True,
    )
    assert tier is oracle.VerdictTier.NECESSARY_GATE_ONLY


def test_decide_verdict_cross_family_reject() -> None:
    oracle = _oracle()
    gates = oracle.GateResults(hidden_test_gate=True, pytest_pass=True, regression_pass=True)
    tier = oracle.decide_verdict(
        gates,
        oracle.ReviewerVerdict(accepted=False, reviewer_family="other", reason_code="contract_gap"),
        candidate_family="cand",
        public_attestation=True,
    )
    assert tier is oracle.VerdictTier.REJECTED_BY_REVIEWER


def test_decide_verdict_cross_family_accept_is_only_accepted_path() -> None:
    oracle = _oracle()
    gates = oracle.GateResults(hidden_test_gate=True, pytest_pass=True, regression_pass=True)
    tier = oracle.decide_verdict(
        gates,
        oracle.ReviewerVerdict(accepted=True, reviewer_family="other", reason_code="ok"),
        candidate_family="cand",
        public_attestation=True,
    )
    assert tier is oracle.VerdictTier.ACCEPTED
    assert oracle.is_accepted(tier)


# --------------------------------------------------------------------------- #
# oracle.decide_verdict — fail-OPEN regression guards (cross-family review)     #
#                                                                              #
# A cross-family Codex review of this surface found two fail-open bypasses:     #
# (1) a truthy non-bool gate value (the string "false") slipped past the        #
#     necessary-gate check, and (2) a cosmetic case variant of the family       #
# label ("Codex" vs "codex") bypassed the same-family self-judge gate. Both     #
# returned ACCEPTED. These tests reproduce the exact bypasses and pin the now   #
# strict ``is True`` / normalized-family behavior; the same hardening also      #
# covers the adjacent truthy-non-bool attestation and accepted-flag vectors.    #
# --------------------------------------------------------------------------- #


def _all_pass_gates(oracle):
    return oracle.GateResults(hidden_test_gate=True, pytest_pass=True, regression_pass=True)


def test_decide_verdict_truthy_nonbool_gate_does_not_fail_open() -> None:
    # Codex finding #1: gate fields typed as bool but checked with truthiness.
    # The string "false" is truthy, so ``not (g1 and g2 and g3)`` used to be False
    # and the necessary gate falsely "passed" -> ACCEPTED. Strict ``is True`` must
    # treat any non-bool as a failed gate (fail-closed).
    oracle = _oracle()
    gates = oracle.GateResults(
        hidden_test_gate="false", pytest_pass="false", regression_pass="false"
    )
    tier = oracle.decide_verdict(
        gates,
        oracle.ReviewerVerdict(accepted=True, reviewer_family="other", reason_code="ok"),
        candidate_family="cand",
        public_attestation=True,
    )
    assert tier is oracle.VerdictTier.REJECTED_NECESSARY_GATE
    assert not oracle.is_accepted(tier)


def test_decide_verdict_case_variant_same_family_does_not_fail_open() -> None:
    # Codex finding #2: the same-family self-judge gate used a case-sensitive ==,
    # so reviewer_family='Codex' vs candidate_family='codex' bypassed it -> ACCEPTED.
    # The comparison must be case-insensitive so the self-judge is neutralized.
    oracle = _oracle()
    tier = oracle.decide_verdict(
        _all_pass_gates(oracle),
        oracle.ReviewerVerdict(accepted=True, reviewer_family="Codex", reason_code="ok"),
        candidate_family="codex",
        public_attestation=True,
    )
    assert tier is oracle.VerdictTier.NECESSARY_GATE_ONLY
    assert not oracle.is_accepted(tier)


def test_decide_verdict_whitespace_variant_same_family_does_not_fail_open() -> None:
    # Same self-judge gate, whitespace variant: ' codex ' must still neutralize a
    # 'codex' candidate's reviewer.
    oracle = _oracle()
    tier = oracle.decide_verdict(
        _all_pass_gates(oracle),
        oracle.ReviewerVerdict(accepted=True, reviewer_family=" codex ", reason_code="ok"),
        candidate_family="codex",
        public_attestation=True,
    )
    assert tier is oracle.VerdictTier.NECESSARY_GATE_ONLY


def test_decide_verdict_truthy_nonbool_attestation_does_not_open_egress() -> None:
    # Adjacent vector hardened in the same fix: the egress gate must open only on a
    # strict ``public_attestation is True``. A truthy non-bool (the string "true")
    # must NOT open egress -> caps at NECESSARY_GATE_ONLY (fail-closed).
    oracle = _oracle()
    tier = oracle.decide_verdict(
        _all_pass_gates(oracle),
        oracle.ReviewerVerdict(accepted=True, reviewer_family="other", reason_code="ok"),
        candidate_family="cand",
        public_attestation="true",
    )
    assert tier is oracle.VerdictTier.NECESSARY_GATE_ONLY


def test_decide_verdict_truthy_nonbool_accepted_does_not_fail_open() -> None:
    # Adjacent vector hardened in the same fix: acceptance requires a strict
    # ``reviewer.accepted is True``. A truthy non-bool accepted flag (the string
    # "yes") must fail closed to a reviewer rejection, never ACCEPTED.
    oracle = _oracle()
    tier = oracle.decide_verdict(
        _all_pass_gates(oracle),
        oracle.ReviewerVerdict(accepted="yes", reviewer_family="other", reason_code="ok"),
        candidate_family="cand",
        public_attestation=True,
    )
    assert tier is oracle.VerdictTier.REJECTED_BY_REVIEWER
    assert not oracle.is_accepted(tier)


def test_decide_verdict_bytes_reviewer_family_does_not_fail_open() -> None:
    # Second-round Codex finding: a bytes family label bypasses the self-judge gate
    # because str(b'codex') == "b'codex'" != "codex". A bytes reviewer_family that
    # is really the SAME family as the candidate must still neutralize -> the family
    # must be a usable str or the verdict fails closed.
    oracle = _oracle()
    tier = oracle.decide_verdict(
        _all_pass_gates(oracle),
        oracle.ReviewerVerdict(accepted=True, reviewer_family=b"codex", reason_code="ok"),
        candidate_family="codex",
        public_attestation=True,
    )
    assert tier is oracle.VerdictTier.NECESSARY_GATE_ONLY
    assert not oracle.is_accepted(tier)


def test_decide_verdict_bytes_candidate_family_does_not_fail_open() -> None:
    # Same second-round finding, bytes on the candidate_family side.
    oracle = _oracle()
    tier = oracle.decide_verdict(
        _all_pass_gates(oracle),
        oracle.ReviewerVerdict(accepted=True, reviewer_family="codex", reason_code="ok"),
        candidate_family=b"codex",
        public_attestation=True,
    )
    assert tier is oracle.VerdictTier.NECESSARY_GATE_ONLY
    assert not oracle.is_accepted(tier)


def test_decide_verdict_empty_family_label_fails_closed() -> None:
    # A blank / whitespace family label is malformed and cannot establish a valid
    # cross-family reviewer; fail closed to NECESSARY_GATE_ONLY, never ACCEPTED.
    oracle = _oracle()
    for reviewer_family, candidate_family in (("", "codex"), ("   ", "codex"), ("claude", "")):
        tier = oracle.decide_verdict(
            _all_pass_gates(oracle),
            oracle.ReviewerVerdict(accepted=True, reviewer_family=reviewer_family, reason_code="ok"),
            candidate_family=candidate_family,
            public_attestation=True,
        )
        assert tier is oracle.VerdictTier.NECESSARY_GATE_ONLY, (reviewer_family, candidate_family)


def test_decide_verdict_str_subclass_dunder_spoof_does_not_fail_open() -> None:
    # Third-round Codex finding: a str SUBCLASS whose __str__ (or strip/lower) is
    # overridden could spoof the canonical token. SpoofStr('codex') has real value
    # 'codex' (same family as the candidate) but __str__ -> 'claude', so a str()-based
    # normalization read it as cross-family -> ACCEPTED. The unbound base-str
    # normalization must use the real buffer ('codex') and neutralize the self-judge.
    oracle = _oracle()

    class SpoofStr(str):
        def __str__(self) -> str:  # noqa: D401 - spoof
            return "claude"

        def strip(self, *args, **kwargs):  # type: ignore[override]
            return "claude"

        def lower(self):  # type: ignore[override]
            return "claude"

    tier = oracle.decide_verdict(
        _all_pass_gates(oracle),
        oracle.ReviewerVerdict(accepted=True, reviewer_family=SpoofStr("codex"), reason_code="ok"),
        candidate_family="codex",
        public_attestation=True,
    )
    assert tier is oracle.VerdictTier.NECESSARY_GATE_ONLY
    assert not oracle.is_accepted(tier)


def test_decide_verdict_legit_cross_family_with_falsy_hard_gates_still_accepts() -> None:
    # Guard against over-correction: the second-round Codex probe also listed
    # hard_gates=None/0/False as "reaches ACCEPTED", but those are LEGITIMATE accepts
    # (a genuine cross-family 'claude' reviewer accepting a 'codex' candidate with no
    # hard gate). A falsy hard_gates means "no hard gate", identical to the default
    # (). This must remain ACCEPTED — failing it closed would reject every clean
    # candidate (whose default hard_gates=() is also falsy).
    oracle = _oracle()
    for falsy in (None, 0, False, ()):
        gates = oracle.GateResults(
            hidden_test_gate=True, pytest_pass=True, regression_pass=True, hard_gates=falsy
        )
        tier = oracle.decide_verdict(
            gates,
            oracle.ReviewerVerdict(accepted=True, reviewer_family="claude", reason_code="ok"),
            candidate_family="codex",
            public_attestation=True,
        )
        assert tier is oracle.VerdictTier.ACCEPTED, falsy
        assert oracle.is_accepted(tier)


# --------------------------------------------------------------------------- #
# oracle_bidmate — egress discipline + injected gates                          #
# --------------------------------------------------------------------------- #


def _oracle_bidmate():
    return load_module(
        "agent-evals/adapters/bidmate/oracle_bidmate.py", "agent_evals_oracle_bidmate_test"
    )


def test_cross_family_review_no_egress_when_attestation_closed() -> None:
    ob = _oracle_bidmate()

    calls = {"provider": 0, "reviewer": 0}

    def provider():
        calls["provider"] += 1
        raise AssertionError("payload_provider must NOT be invoked when egress is closed")

    def reviewer_call(_payload):
        calls["reviewer"] += 1
        return True, "ok"

    verdict = ob.cross_family_review(
        provider,
        public_attestation=False,
        candidate_family="cand",
        reviewer_family="other",
        reviewer_call=reviewer_call,
    )
    assert verdict is None
    assert calls == {"provider": 0, "reviewer": 0}


def test_cross_family_review_egress_when_attestation_open() -> None:
    ob = _oracle_bidmate()

    seen = {}

    def provider():
        return "issue+patch payload"

    def reviewer_call(payload):
        seen["payload"] = payload
        return True, "ok"

    verdict = ob.cross_family_review(
        provider,
        public_attestation=True,
        candidate_family="cand",
        reviewer_family="other_family",
        reviewer_call=reviewer_call,
    )
    assert verdict is not None
    assert verdict.accepted is True
    assert verdict.reviewer_family == "other_family"
    assert verdict.reason_code == "ok"
    assert seen["payload"] == "issue+patch payload"


def test_run_necessary_gates_maps_returncodes_with_injected_subprocess() -> None:
    ob = _oracle_bidmate()

    class _Proc:
        def __init__(self, rc):
            self.returncode = rc

    # hidden -> 0 (pass), pytest -> 1 (fail), regression -> 0 (pass)
    rc_by_first_arg = {"hidden": 0, "pytest": 0, "regression": 1}

    def fake_run(cmd, **_kwargs):
        return _Proc(rc_by_first_arg[cmd[0]])

    gates = ob.run_necessary_gates(
        Path("/tmp/does-not-matter"),
        hidden_test_cmd=["hidden"],
        pytest_cmd=["pytest"],
        regression_cmd=["regression"],
        runner_subprocess=fake_run,
    )
    assert gates.hidden_test_gate is True
    assert gates.pytest_pass is True
    assert gates.regression_pass is False
    assert gates.hard_gates == ()


def test_detect_hard_gates_maps_sanitized_summary() -> None:
    ob = _oracle_bidmate()
    # Compare against the SAME oracle module oracle_bidmate loaded internally
    # (``ob.oracle``); a separate path-load would create a distinct HardGate enum
    # class whose members are not identity-equal to the returned ones.
    HardGate = ob.oracle.HardGate
    gates = ob.detect_hard_gates(
        {
            "added_secrets": True,
            "unauthorized_migration": True,
            "deleted_paths": 2,
            "build_failure": False,
        }
    )
    assert HardGate.SECRET_LEAK in gates
    assert HardGate.UNAUTHORIZED_MIGRATION in gates
    assert HardGate.DESTRUCTIVE in gates
    assert HardGate.BUILD_FAILURE not in gates


def test_evaluate_returns_sanitized_verdict_dict_only() -> None:
    ob = _oracle_bidmate()

    class _Proc:
        returncode = 0

    def fake_run(cmd, **_kwargs):
        return _Proc()

    out = ob.evaluate(
        Path("/tmp/x"),
        task={"task_id": "T-1"},
        candidate_family="cand",
        public_attestation=True,
        reviewer_family="other",
        payload_provider=lambda: "payload",
        hidden_test_cmd=["h"],
        pytest_cmd=["p"],
        regression_cmd=["r"],
        runner_subprocess=fake_run,
        reviewer_call=lambda _p: (True, "ok"),
    )
    assert out == {
        "tier": "ACCEPTED",
        "candidate_family": "cand",
        "reviewer_family": "other",
        "egress": "performed",
        "reason_code": "ok",
    }
    # No payload/prose keys leaked into the verdict dict.
    assert set(out) == {"tier", "candidate_family", "reviewer_family", "egress", "reason_code"}


def test_evaluate_skips_egress_when_hard_gate_fires() -> None:
    # PR-bot P1: a hard gate (e.g. added_secrets) makes rejection certain, so the
    # issue+patch payload — which may contain exactly the detected secret — must NOT
    # be handed to the external reviewer. evaluate must short-circuit egress entirely.
    ob = _oracle_bidmate()

    class _Proc:
        returncode = 0

    def fake_run(_cmd, **_kwargs):
        return _Proc()

    def exploding_provider():
        raise AssertionError("payload_provider must NOT be invoked once a gate has failed")

    out = ob.evaluate(
        Path("/tmp/x"),
        task={"task_id": "T-sec"},
        candidate_family="cand",
        public_attestation=True,
        reviewer_family="other",
        payload_provider=exploding_provider,
        hidden_test_cmd=["h"],
        pytest_cmd=["p"],
        regression_cmd=["r"],
        diff_summary={"added_secrets": True},
        runner_subprocess=fake_run,
        reviewer_call=lambda _p: (True, "ok"),
    )
    assert out["tier"] == "REJECTED_HARD_GATE"
    assert out["egress"] == "skipped"
    assert out["reviewer_family"] is None
    assert out["reason_code"] is None


def test_evaluate_skips_egress_when_necessary_gate_fails() -> None:
    # PR-bot P1: same short-circuit when a NECESSARY gate fails (no hard gate). A
    # candidate that already failed must not have its payload leave the boundary.
    ob = _oracle_bidmate()

    class _Proc:
        def __init__(self, rc):
            self.returncode = rc

    rc_by_first = {"h": 0, "p": 1, "r": 0}  # pytest fails

    def fake_run(cmd, **_kwargs):
        return _Proc(rc_by_first[cmd[0]])

    def exploding_provider():
        raise AssertionError("payload_provider must NOT be invoked when a gate failed")

    out = ob.evaluate(
        Path("/tmp/x"),
        task={"task_id": "T-fail"},
        candidate_family="cand",
        public_attestation=True,
        reviewer_family="other",
        payload_provider=exploding_provider,
        hidden_test_cmd=["h"],
        pytest_cmd=["p"],
        regression_cmd=["r"],
        runner_subprocess=fake_run,
        reviewer_call=lambda _p: (True, "ok"),
    )
    assert out["tier"] == "REJECTED_NECESSARY_GATE"
    assert out["egress"] == "skipped"


# --------------------------------------------------------------------------- #
# runner.run_one — real detached worktree at HEAD + cleanup                    #
# --------------------------------------------------------------------------- #


def _runner():
    return load_module("agent-evals/adapters/bidmate/runner.py", "agent_evals_runner_test")


def test_run_one_creates_and_cleans_up_detached_worktree() -> None:
    runner = _runner()
    head = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    captured = {}

    def stub_candidate(*, worktree, task_id, playbook, seed):
        # The detached worktree must really exist on disk while the candidate runs.
        captured["worktree"] = Path(worktree)
        captured["existed_during_run"] = Path(worktree).is_dir()
        captured["is_git_worktree"] = (Path(worktree) / ".git").exists()
        return {
            "intervention_count": 2,
            "cost": {"input_tokens": 10, "output_tokens": 5, "usd": 0.0},
            "human_minutes": 1.5,
            "gate_results": {
                "hidden_test_gate": True,
                "pytest_pass": True,
                "regression_pass": True,
                "hard_gates": [],
            },
        }

    run_log = runner.run_one(
        start_commit=head,
        task_id="T-smoke-001",
        playbook="v1_spec_first",
        seed=17,
        candidate=stub_candidate,
        repo_root=REPO_ROOT,
        clock=lambda: 42.0,
    )

    # Run-log shape.
    assert run_log["task_id"] == "T-smoke-001"
    assert run_log["playbook"] == "v1_spec_first"
    assert run_log["seed"] == 17
    assert run_log["start_commit"] == head
    assert run_log["intervention_count"] == 2
    assert run_log["human_minutes"] == 1.5
    assert run_log["timestamps"] == {"started": 42.0, "finished": 42.0}
    assert run_log["gate_results"]["hidden_test_gate"] is True

    # The worktree really existed during the run...
    assert captured["existed_during_run"] is True
    assert captured["is_git_worktree"] is True

    # ...and is fully cleaned up afterward.
    assert not captured["worktree"].exists()
    listed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "worktree", "list"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert str(captured["worktree"]) not in listed


def test_run_one_cleans_up_worktree_even_if_candidate_raises() -> None:
    runner = _runner()
    head = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    captured = {}

    def boom(*, worktree, task_id, playbook, seed):
        captured["worktree"] = Path(worktree)
        raise RuntimeError("candidate failed mid-run")

    try:
        runner.run_one(
            start_commit=head,
            task_id="T-smoke-002",
            playbook="v0_naive",
            seed=18,
            candidate=boom,
            repo_root=REPO_ROOT,
            clock=lambda: 0.0,
        )
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("run_one should propagate the candidate failure")

    assert not captured["worktree"].exists()
    listed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "worktree", "list"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert str(captured["worktree"]) not in listed


def test_write_run_log_targets_gitignored_runs_dir(tmp_path) -> None:
    runner = _runner()
    run_log = {
        "task_id": "T-smoke-003",
        "playbook": "v1_spec_first",
        "seed": 19,
        "gate_results": {"tier": "ACCEPTED"},
    }
    out = runner.write_run_log(run_log, runs_dir=tmp_path / "runs")
    assert out.name == "T-smoke-003__v1_spec_first__seed19.json"
    assert out.exists()
    # The default runs dir is the gitignored agent-evals/runs tree.
    assert "agent-evals/runs/" in (runner.write_run_log.__doc__ or "")


def test_run_matrix_default_uses_at_least_three_seeds() -> None:
    runner = _runner()
    assert len(runner.DEFAULT_SEEDS) >= 3
    assert runner.DEFAULT_SEEDS == (17, 18, 19)
    assert runner.DEFAULT_PLAYBOOKS == ("v0_naive", "v1_spec_first")


# --------------------------------------------------------------------------- #
# metrics.underpowered                                                         #
# --------------------------------------------------------------------------- #


def test_underpowered_threshold() -> None:
    metrics = load_module("agent-evals/core/metrics.py", "agent_evals_metrics_underpowered_test")
    assert metrics.N_MIN_DEFAULT == 10
    assert metrics.underpowered(3) is True
    assert metrics.underpowered(9) is True
    assert metrics.underpowered(10) is False
    assert metrics.underpowered(11) is False
    assert metrics.underpowered(5, n_min=4) is False


# --------------------------------------------------------------------------- #
# scripts/agent_evals_report.build_report — powered (n>=n_min) bootstrap path  #
# --------------------------------------------------------------------------- #


def _synth_paired_logs(n_tasks: int, n_ties: int) -> list[dict]:
    """Synthesize paired run-logs: candidate wins on (n_tasks - n_ties), ties on n_ties.

    A "win" is candidate accepted + baseline not; a "tie" is both accepted. One seed
    per (task, playbook) so each task contributes exactly one paired row, giving
    n == n_tasks paired rows for the report's bootstrap.
    """

    logs: list[dict] = []
    for i in range(n_tasks):
        baseline_accepted = i < n_ties  # first n_ties tasks tie (both accepted)
        for playbook, accepted in (("v0_naive", baseline_accepted), ("v1_spec_first", True)):
            logs.append(
                {
                    "task_id": f"T-pow-{i:03d}",
                    "playbook": playbook,
                    "seed": 17,
                    "gate_results": {"tier": "ACCEPTED" if accepted else "NECESSARY_GATE_ONLY"},
                    "human_minutes": 1.0,
                    "cost": {"usd": 0.0},
                }
            )
    return logs


def test_report_powered_path_attaches_sign_aligned_ci_band() -> None:
    report_script = load_module("scripts/agent_evals_report.py", "agent_evals_report_powered_test")
    report_mod = load_module("agent-evals/core/report.py", "agent_evals_report_powered_scan")

    logs = _synth_paired_logs(n_tasks=12, n_ties=3)  # n=12 >= n_min=10 -> powered
    report = report_script.build_report(
        logs, report_id="powered-test", num_resamples=200, alpha=0.05, seed=17
    )

    row = report["metrics"]["accepted_solve_rate"]
    assert row["n"] == 12
    # Powered: a real CI band, never the underpowered flag.
    assert "underpowered" not in row
    for key in ("ci_lo", "ci_hi", "num_resamples", "alpha"):
        assert key in row, f"powered metric row missing {key}"
    # Candidate (v1) beats baseline (v0), so delta and the CI band must share the
    # positive (candidate - baseline) sign. A flipped paired_bootstrap_ci arg order
    # would push the band negative (ci_hi <= 0), so this guards the sign fix.
    assert row["delta"] > 0
    assert row["ci_lo"] >= 0.0
    assert row["ci_hi"] > 0.0
    assert row["ci_lo"] <= row["ci_hi"]

    # The powered report must still pass the aggregate-only content scanner.
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    violations = report_mod.validate_agent_eval_file(
        "agent-evals/reports/powered-test.aggregate.json", serialized
    )
    assert [v.render() for v in violations] == []
    assert any(note.startswith("N=12") for note in report["notes"])
    assert not any("UNDERPOWERED" in note for note in report["notes"])


def _cost_log(task: str, playbook: str, accepted: bool, usd: float, commit: str = "c0") -> dict:
    return {
        "task_id": task,
        "playbook": playbook,
        "seed": 17,
        "start_commit": commit,
        "gate_results": {"tier": "ACCEPTED" if accepted else "NECESSARY_GATE_ONLY"},
        "human_minutes": 1.0,
        "cost": {"usd": usd},
    }


def test_report_zero_solve_cost_is_not_scored_as_free() -> None:
    # PR-bot P3: a playbook that accepts NOTHING must not score 0.0 cost (which would
    # look cheapest/best and let a zero-solve baseline win the cost metric). The
    # undefined (task, playbook) is dropped from the cost/human-min paired sample.
    report_script = load_module("scripts/agent_evals_report.py", "agent_evals_report_p3_test")
    logs = [
        # task A: both accept -> cost defined on both sides -> one valid cost pair
        _cost_log("T-a", "v0_naive", True, 5.0),
        _cost_log("T-a", "v1_spec_first", True, 3.0),
        # task B: baseline accepts nothing (cost UNDEFINED), candidate accepts at cost
        _cost_log("T-b", "v0_naive", False, 0.0),
        _cost_log("T-b", "v1_spec_first", True, 4.0),
    ]
    report = report_script.build_report(logs, report_id="p3", num_resamples=50, alpha=0.05, seed=17)

    # Only task A forms a valid cost pair; task B's zero-solve baseline is dropped
    # (NOT folded in as a free 0.0 that would beat the candidate's nonzero cost).
    assert report["metrics"]["cost_per_accepted"]["n"] == 1
    assert report["metrics"]["human_min_per_accepted"]["n"] == 1
    # accepted_solve_rate is always defined, so it still covers BOTH tasks.
    assert report["metrics"]["accepted_solve_rate"]["n"] == 2


def test_report_refuses_mixed_start_commits() -> None:
    # PR-bot P2: run-logs from different start_commit values in one (gitignored) runs
    # dir would silently fold stale measurements into one aggregate and corrupt
    # task_count / means / deltas. build_report must refuse loudly, not corrupt.
    report_script = load_module("scripts/agent_evals_report.py", "agent_evals_report_p2_test")
    logs = [
        _cost_log("T", "v0_naive", True, 1.0, commit="aaaa"),
        _cost_log("T", "v1_spec_first", True, 1.0, commit="bbbb"),
    ]
    with pytest.raises(ValueError, match="multiple start_commit"):
        report_script.build_report(logs, report_id="p2", num_resamples=50, alpha=0.05, seed=17)


def _write_log(runner, runs_dir: Path, task: str, playbook: str, seed: int) -> Path:
    """Persist a minimal run-log via the runner's own writer (real filename scheme)."""

    return runner.write_run_log(
        {
            "task_id": task,
            "playbook": playbook,
            "seed": seed,
            "start_commit": "c0",
            "gate_results": {"tier": "ACCEPTED"},
            "human_minutes": 1.0,
            "cost": {"usd": 0.0},
        },
        runs_dir=runs_dir,
    )


def test_report_manifest_scopes_to_current_run_only(tmp_path) -> None:
    # PR-bot P2 (completion): the report must read EXACTLY the current matrix. A later
    # run with a smaller task list / changed seeds (same start_commit) leaves orphaned
    # logs on disk; the start_commit guard cannot catch them. The run_manifest scopes
    # reads to the files THIS run wrote, so orphans are skipped — not folded in.
    report_script = load_module("scripts/agent_evals_report.py", "agent_evals_report_manifest_scope")
    runner = load_module("agent-evals/adapters/bidmate/runner.py", "agent_evals_runner_manifest_scope")
    runs_dir = tmp_path / "runs"

    # Current run: one task, both playbooks, one seed -> 2 logs + a manifest.
    current = [
        _write_log(runner, runs_dir, "T-keep", "v0_naive", 17),
        _write_log(runner, runs_dir, "T-keep", "v1_spec_first", 17),
    ]
    runner.write_run_manifest(current, runs_dir=runs_dir, start_commit="c0", tasks=["T-keep"])
    # Orphan from an earlier, larger matrix at the SAME start_commit: still on disk,
    # NOT in the manifest. A whole-dir glob would fold it into task_count.
    _write_log(runner, runs_dir, "T-stale", "v0_naive", 17)
    _write_log(runner, runs_dir, "T-stale", "v1_spec_first", 17)

    logs = report_script._read_run_logs(runs_dir)
    task_ids = sorted({log["task_id"] for log in logs})
    assert task_ids == ["T-keep"]  # orphan excluded; manifest is authoritative
    # The manifest file itself is never parsed as a run-log (no task_id KeyError).
    assert all("task_id" in log for log in logs)


def test_report_manifest_missing_log_fails_loud(tmp_path) -> None:
    # If the manifest references a log that is not on disk, the runs dir is
    # inconsistent; the report must fail loudly rather than silently under-report.
    report_script = load_module("scripts/agent_evals_report.py", "agent_evals_report_manifest_missing")
    runner = load_module("agent-evals/adapters/bidmate/runner.py", "agent_evals_runner_manifest_missing")
    runs_dir = tmp_path / "runs"
    kept = _write_log(runner, runs_dir, "T-a", "v0_naive", 17)
    runner.write_run_manifest(
        [kept, runs_dir / "T-a__v1_spec_first__seed17.json"],  # second never written
        runs_dir=runs_dir,
        start_commit="c0",
        tasks=["T-a"],
    )
    with pytest.raises(FileNotFoundError, match="not on disk"):
        report_script._read_run_logs(runs_dir)


def test_report_glob_fallback_when_no_manifest(tmp_path) -> None:
    # Legacy / hand-populated dir with no manifest: fall back to globbing every
    # *.json. (The cross-commit guard in build_report remains the safety net there.)
    report_script = load_module("scripts/agent_evals_report.py", "agent_evals_report_no_manifest")
    runner = load_module("agent-evals/adapters/bidmate/runner.py", "agent_evals_runner_no_manifest")
    runs_dir = tmp_path / "runs"
    _write_log(runner, runs_dir, "T-x", "v0_naive", 17)
    _write_log(runner, runs_dir, "T-x", "v1_spec_first", 17)
    # No manifest written.
    logs = report_script._read_run_logs(runs_dir)
    assert sorted({log["task_id"] for log in logs}) == ["T-x"]
    assert len(logs) == 2
