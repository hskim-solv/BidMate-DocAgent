#!/usr/bin/env python3
"""Sequential paired-trial runner for the BidMate operator-skill eval surface.

Each trial runs one frozen playbook against one task in a DETACHED git worktree
created at a fixed start commit, then ALWAYS tears the worktree down.  The run-log
is a sanitized dict of timings / counts / gate booleans — never raw diff, patch,
issue, PR, or reviewer prose — and the caller persists it to a GITIGNORED path
(``agent-evals/runs/`` is deny-by-default).

Design constraints:

* The candidate is INJECTED (``candidate(...)``).  The default stub is
  deterministic and applies nothing, so the runner itself stays side-effect-free
  and testable; the real candidate (which invokes a coding agent) is wired by the
  CLI, not here.
* The clock is injectable and there is NO module-import-time ``datetime.now()`` —
  tests pass a fixed clock so run-logs are byte-deterministic.
* Worktree teardown runs in a ``finally`` (remove --force, best-effort rmtree,
  then ``git worktree prune``) so a crashing candidate cannot leak worktrees and
  fill the disk; the matrix runs one worktree at a time for the same reason.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


DEFAULT_PLAYBOOKS: tuple[str, ...] = ("v0_naive", "v1_spec_first")
DEFAULT_SEEDS: tuple[int, ...] = (17, 18, 19)
_WORKTREE_OP_TIMEOUT = 300


def _zero_clock() -> float:
    """Deterministic default clock (tests override; never wall-clock at import)."""

    return 0.0


def stub_candidate(*, worktree: Path, task_id: str, playbook: str, seed: int) -> dict[str, Any]:
    """Deterministic no-op candidate used as the default / in tests.

    Applies no repository change and returns a fixed sanitized result.  The
    ``gate_results`` here are intentionally all-pass so the downstream stub
    pipeline can surface some ACCEPTED rows under public attestation + a stub
    cross-family reviewer; this is a directional smoke signal, not a real solve.
    """

    return {
        "intervention_count": 0,
        "cost": {"input_tokens": 0, "output_tokens": 0, "usd": 0.0},
        "human_minutes": 0.0,
        "gate_results": {
            "hidden_test_gate": True,
            "pytest_pass": True,
            "regression_pass": True,
            "hard_gates": [],
        },
    }


def run_one(
    *,
    start_commit: str,
    task_id: str,
    playbook: str,
    seed: int,
    candidate: Callable[..., dict[str, Any]] = stub_candidate,
    repo_root: Path,
    clock: Callable[[], float] = _zero_clock,
    subprocess_run: Callable[..., Any] = subprocess.run,
    workdir_factory: Callable[..., str] = tempfile.mkdtemp,
) -> dict[str, Any]:
    """Run one (task, playbook, seed) trial in a fresh detached worktree.

    Returns a sanitized run-log dict.  The worktree is always removed before
    return (success or failure).  ``candidate`` is injected; the default applies
    nothing.  ``clock`` is injected so ``started``/``finished`` are deterministic
    in tests.
    """

    tmp = workdir_factory(prefix=f"agent-evals-{task_id}-{playbook}-seed{seed}-")
    tmp_path = Path(tmp)
    started = float(clock())
    try:
        subprocess_run(
            ["git", "-C", str(repo_root), "worktree", "add", str(tmp_path), "--detach", start_commit],
            check=True,
            capture_output=True,
            timeout=_WORKTREE_OP_TIMEOUT,
        )
        candidate_result = candidate(
            worktree=tmp_path,
            task_id=task_id,
            playbook=playbook,
            seed=seed,
        )
    finally:
        _cleanup_worktree(repo_root, tmp_path, subprocess_run=subprocess_run)

    finished = float(clock())
    result = candidate_result or {}
    cost = result.get("cost") or {}
    gate_results = result.get("gate_results") or {}
    return {
        "task_id": task_id,
        "playbook": playbook,
        "seed": int(seed),
        "start_commit": start_commit,
        "timestamps": {"started": started, "finished": finished},
        "human_minutes": float(result.get("human_minutes", 0.0)),
        "intervention_count": int(result.get("intervention_count", 0)),
        "cost": {
            "input_tokens": int(cost.get("input_tokens", 0)),
            "output_tokens": int(cost.get("output_tokens", 0)),
            "usd": float(cost.get("usd", 0.0)),
        },
        "gate_results": {
            "hidden_test_gate": bool(gate_results.get("hidden_test_gate", False)),
            "pytest_pass": bool(gate_results.get("pytest_pass", False)),
            "regression_pass": bool(gate_results.get("regression_pass", False)),
            "hard_gates": list(gate_results.get("hard_gates", [])),
            "tier": gate_results.get("tier"),
        },
        "candidate_meta": {
            "candidate": getattr(candidate, "__name__", "candidate"),
            "applied_change": bool(result.get("applied_change", False)),
        },
    }


def _cleanup_worktree(
    repo_root: Path,
    tmp_path: Path,
    *,
    subprocess_run: Callable[..., Any] = subprocess.run,
) -> None:
    """Best-effort teardown: ``worktree remove --force`` -> rmtree -> ``prune``."""

    try:
        subprocess_run(
            ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(tmp_path)],
            check=False,
            capture_output=True,
            timeout=_WORKTREE_OP_TIMEOUT,
        )
    except Exception:  # pragma: no cover - teardown must never raise
        pass
    if tmp_path.exists():
        shutil.rmtree(tmp_path, ignore_errors=True)
    try:
        subprocess_run(
            ["git", "-C", str(repo_root), "worktree", "prune"],
            check=False,
            capture_output=True,
            timeout=_WORKTREE_OP_TIMEOUT,
        )
    except Exception:  # pragma: no cover - teardown must never raise
        pass


def write_run_log(run_log: dict[str, Any], *, runs_dir: Path) -> Path:
    """Persist one run-log to ``runs_dir/<task_id>__<playbook>__seed<seed>.json``.

    ``runs_dir`` defaults under ``agent-evals/runs/`` (GITIGNORED, deny-by-default)
    so a run-log is never committed.  The directory is created if missing.
    """

    runs_dir.mkdir(parents=True, exist_ok=True)
    name = f"{run_log['task_id']}__{run_log['playbook']}__seed{run_log['seed']}.json"
    out_path = runs_dir / name
    out_path.write_text(json.dumps(run_log, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out_path


def run_matrix(
    *,
    tasks: Iterable[str],
    start_commit: str,
    repo_root: Path,
    playbooks: Sequence[str] = DEFAULT_PLAYBOOKS,
    seeds: Sequence[int] = DEFAULT_SEEDS,
    candidate: Callable[..., dict[str, Any]] = stub_candidate,
    clock: Callable[[], float] = _zero_clock,
    subprocess_run: Callable[..., Any] = subprocess.run,
    workdir_factory: Callable[..., str] = tempfile.mkdtemp,
) -> list[dict[str, Any]]:
    """Run the full (task x playbook x seed) matrix sequentially.

    Sequential by design: one worktree exists at a time so concurrent disk usage
    stays bounded.  Returns the list of run-log dicts (caller persists them).
    """

    run_logs: list[dict[str, Any]] = []
    for task_id in tasks:
        for playbook in playbooks:
            for seed in seeds:
                run_logs.append(
                    run_one(
                        start_commit=start_commit,
                        task_id=task_id,
                        playbook=playbook,
                        seed=int(seed),
                        candidate=candidate,
                        repo_root=repo_root,
                        clock=clock,
                        subprocess_run=subprocess_run,
                        workdir_factory=workdir_factory,
                    )
                )
    return run_logs
