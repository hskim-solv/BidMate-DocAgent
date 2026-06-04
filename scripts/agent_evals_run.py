#!/usr/bin/env python3
"""Orchestrate the agent-evals paired playbook matrix over holdout tasks.

This CLI lives in ``scripts/`` (NOT under ``agent-evals/``) so it is not subject
to the agent-evals deny-by-default gitignore / commit allowlist; it is ordinary
repository tooling.  It loads the path-restricted agent-evals modules by file path
(mirroring ``tests/test_agent_evals_core.py``'s ``load_module``) because the
``agent-evals`` directory name is not an importable Python package.

The default candidate is a built-in DETERMINISTIC STUB: it applies no repository
change and returns fixed all-pass gate booleans.  ``--real`` is reserved for the
real coding-agent invocation and is intentionally left as a clearly-marked stub
(``NotImplementedError``) for now — wiring a live agent is a later PR.

Verdicts are computed at run time through ``oracle.decide_verdict`` using the two
fail-closed privacy gates:

* ``--public-attestation`` opens the egress gate so a cross-family reviewer may be
  consulted (without it, every run caps at NECESSARY_GATE_ONLY by construction).
* the reviewer here is a deterministic STUB cross-family reviewer (no external
  egress actually happens); it is the harness stand-in described in the report
  notes, NOT a real model call.

Run-logs are written to the GITIGNORED runs dir (``agent-evals/runs/`` by
default), so no per-run artifact is ever committed.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]

# Candidate family for the stub pipeline. The stub reviewer below is a different
# (synthetic) family so the cross-family validity gate (ADR 0064) is satisfied and
# acceptance is reachable in the smoke surface.
STUB_CANDIDATE_FAMILY = "stub_candidate_family"
STUB_REVIEWER_FAMILY = "stub_reviewer_family"
SMOKE_HOLDOUT_TASKS = ("T-smoke-001", "T-smoke-002", "T-smoke-003")


def load_module(rel_path: str, name: str):
    """Load an agent-evals module by repo-relative path (hyphenated dir)."""

    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _stub_cross_family_reviewer(*, playbook: str, task_id: str, seed: int) -> tuple[bool, str]:
    """Deterministic stand-in for a real cross-family reviewer (NO external egress).

    Encodes a modest, honest directional signal so the smoke report is not inert:
    the spec-first playbook (``v1_spec_first``) is accepted on every holdout task,
    while the naive playbook (``v0_naive``) is rejected on a deterministic subset.
    This is a STUB verdict, clearly labelled in the report notes — not a measured
    operator-skill result.
    """

    if playbook == "v1_spec_first":
        return True, "ok"
    # v0_naive: reject on tasks whose trailing id digit is odd (deterministic),
    # accept otherwise — yields a non-trivial paired delta without claiming truth.
    trailing = "".join(ch for ch in task_id if ch.isdigit())[-1:] or "0"
    if int(trailing) % 2 == 1:
        return False, "naive_contract_gap"
    return True, "ok"


def _verdict_for_run(run_log: dict[str, Any], oracle, *, public_attestation: bool) -> str:
    """Compute and return the verdict tier name for one stub run-log."""

    gr = run_log["gate_results"]
    hard = tuple(gr.get("hard_gates", ()))
    # Strict identity to match the fail-closed run-log writer (runner.run_one): a
    # gate counts as passing only when it is exactly True, never a coerced truthy.
    gates = oracle.GateResults(
        hidden_test_gate=gr.get("hidden_test_gate") is True,
        pytest_pass=gr.get("pytest_pass") is True,
        regression_pass=gr.get("regression_pass") is True,
        hard_gates=hard,
    )
    reviewer = None
    if public_attestation is True:
        accepted, reason_code = _stub_cross_family_reviewer(
            playbook=run_log["playbook"],
            task_id=run_log["task_id"],
            seed=run_log["seed"],
        )
        reviewer = oracle.ReviewerVerdict(
            accepted=accepted,
            reviewer_family=STUB_REVIEWER_FAMILY,
            reason_code=reason_code,
        )
    tier = oracle.decide_verdict(
        gates,
        reviewer,
        candidate_family=STUB_CANDIDATE_FAMILY,
        public_attestation=public_attestation,
    )
    return tier.name


def _real_candidate(*, worktree: Path, task_id: str, playbook: str, seed: int) -> dict[str, Any]:
    """Reserved real coding-agent invocation — intentionally not implemented yet."""

    raise NotImplementedError(
        "the --real candidate (live coding-agent invocation) is a later PR; "
        "use the default stub candidate for the smoke surface"
    )


def run(
    *,
    tasks: tuple[str, ...],
    start_commit: str,
    runs_dir: Path,
    public_attestation: bool,
    use_real: bool,
    subprocess_run: Callable[..., Any] = subprocess.run,
) -> list[Path]:
    """Run the matrix and persist one run-log per (task, playbook, seed)."""

    runner = load_module("agent-evals/adapters/bidmate/runner.py", "agent_evals_runner_cli")
    oracle = load_module("agent-evals/core/oracle.py", "agent_evals_oracle_cli")

    candidate = _real_candidate if use_real else runner.stub_candidate
    run_logs = runner.run_matrix(
        tasks=tasks,
        start_commit=start_commit,
        repo_root=REPO_ROOT,
        candidate=candidate,
        subprocess_run=subprocess_run,
    )
    written: list[Path] = []
    for run_log in run_logs:
        run_log["gate_results"]["tier"] = _verdict_for_run(
            run_log, oracle, public_attestation=public_attestation
        )
        written.append(runner.write_run_log(run_log, runs_dir=runs_dir))
    # Record exactly which logs this matrix produced so the report scopes to THIS
    # run and never folds in orphaned logs from an earlier, differently-shaped
    # matrix (smaller task list / changed seeds at the same start_commit).
    runner.write_run_manifest(
        written,
        runs_dir=runs_dir,
        start_commit=start_commit,
        tasks=tasks,
    )
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tasks",
        nargs="*",
        default=list(SMOKE_HOLDOUT_TASKS),
        help="holdout task ids (default: the 3 smoke tasks)",
    )
    parser.add_argument(
        "--start-commit",
        default=None,
        help="detached worktree start commit (default: current HEAD)",
    )
    parser.add_argument(
        "--runs-dir",
        default=str(REPO_ROOT / "agent-evals" / "runs"),
        help="GITIGNORED output dir for run-logs (default: agent-evals/runs)",
    )
    parser.add_argument(
        "--public-attestation",
        action="store_true",
        help="open the egress gate so the stub cross-family reviewer can accept",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="select the real coding-agent candidate (NotImplemented stub for now)",
    )
    args = parser.parse_args(argv)

    start_commit = args.start_commit
    if start_commit is None:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        start_commit = proc.stdout.strip()

    written = run(
        tasks=tuple(args.tasks),
        start_commit=start_commit,
        runs_dir=Path(args.runs_dir),
        public_attestation=args.public_attestation,
        use_real=args.real,
    )
    print(f"wrote {len(written)} run-log(s) to {args.runs_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
