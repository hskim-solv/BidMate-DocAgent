#!/usr/bin/env python3
"""BidMate adapter that drives real gates + cross-family review into the oracle.

This is the only layer that touches subprocesses / an external reviewer; it feeds
*already-sanitized* booleans and short tokens into ``core/oracle.py`` (which stays
repo-agnostic and stdlib-only).  The core module is loaded by file path with
``importlib`` because the top-level directory name ``agent-evals`` contains a
hyphen and is therefore not a valid Python package name, so ``from agent-evals...``
is impossible; a path load also keeps this adapter off the forbidden RAG/eval/api
import prefixes the content scanner blocks.

Egress discipline (ADR 0005 + ADR 0064):

* ``cross_family_review`` performs the ONLY payload egress, and ONLY when
  ``public_attestation`` is True.  When it is False the ``payload_provider`` is
  not even invoked — there is no payload built and nothing leaves the boundary.
* The same-family validity check is enforced *downstream* in
  ``oracle.decide_verdict``: even if a same-family reviewer returns a verdict, the
  tier is neutralized to ``NECESSARY_GATE_ONLY``.  This adapter therefore does not
  need to special-case family equality before returning a verdict.

No raw stdout/diff/patch/review prose is ever stored in a returned structure here;
only pass/fail booleans, hard-gate members, a short ``reason_code`` token, and the
sanitized verdict dict cross the boundary.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping


_GATE_TIMEOUT_SECONDS = 1800
_REVIEW_TIMEOUT_SECONDS = 600


def _load_core(name: str):
    """Load ``core/<name>.py`` by path (hyphenated dir is not importable)."""

    core_path = Path(__file__).resolve().parents[2] / "core" / f"{name}.py"
    module_name = f"agent_evals_core_{name}"
    spec = importlib.util.spec_from_file_location(module_name, core_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"could not load agent-evals core module: {core_path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass forward-ref resolution (e.g.
    # ``tuple[HardGate, ...]``) can find the module in ``sys.modules`` during class
    # creation; without this, ``@dataclass`` post-processing raises AttributeError.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


oracle = _load_core("oracle")


# Map of sanitized diff-summary boolean keys -> HardGate members. The caller
# passes booleans/counts only (never raw diff text), so this detector is a pure
# lookup over an already-sanitized summary.
_HARD_GATE_FLAGS: tuple[tuple[str, Any], ...] = (
    ("build_failure", oracle.HardGate.BUILD_FAILURE),
    ("added_secrets", oracle.HardGate.SECRET_LEAK),
    ("destructive", oracle.HardGate.DESTRUCTIVE),
    ("unrelated_churn", oracle.HardGate.UNRELATED_REWRITE),
    ("instruction_violation", oracle.HardGate.INSTRUCTION_VIOLATION),
    ("unauthorized_migration", oracle.HardGate.UNAUTHORIZED_MIGRATION),
)


def run_necessary_gates(
    worktree: Path,
    *,
    hidden_test_cmd: list[str],
    pytest_cmd: list[str],
    regression_cmd: list[str],
    runner_subprocess: Callable[..., Any] = subprocess.run,
    timeout: int = _GATE_TIMEOUT_SECONDS,
) -> Any:  # oracle.GateResults — oracle is importlib-loaded so it is not a static type
    """Run the three necessary-gate commands in ``worktree`` and map rc==0 -> pass.

    ``runner_subprocess`` is injectable so tests pass a fake mapping returncodes to
    commands without spawning real processes.  Only the boolean pass/fail of each
    command is retained — stdout/stderr is never captured into the returned
    ``GateResults`` (or any committed structure).
    """

    def _passed(cmd: list[str]) -> bool:
        proc = runner_subprocess(
            cmd,
            cwd=str(worktree),
            timeout=timeout,
            check=False,
            capture_output=True,
        )
        return int(getattr(proc, "returncode", 1)) == 0

    return oracle.GateResults(
        hidden_test_gate=_passed(hidden_test_cmd),
        pytest_pass=_passed(pytest_cmd),
        regression_pass=_passed(regression_cmd),
    )


def detect_hard_gates(diff_summary: Mapping[str, Any]) -> tuple[Any, ...]:
    """Map an already-sanitized diff-summary dict to HardGate members.

    The summary carries booleans/counts only (e.g. ``{"build_failure": bool,
    "added_secrets": bool, "destructive": bool, "unrelated_churn": bool,
    "unauthorized_migration": bool, "instruction_violation": bool,
    "deleted_paths": int}``) — never raw diff text.  ``deleted_paths`` is treated
    as a destructive signal when positive.
    """

    gates: list[Any] = []
    for key, gate in _HARD_GATE_FLAGS:
        if bool(diff_summary.get(key)):
            gates.append(gate)
    deleted = diff_summary.get("deleted_paths")
    if isinstance(deleted, (int, float)) and deleted > 0 and oracle.HardGate.DESTRUCTIVE not in gates:
        gates.append(oracle.HardGate.DESTRUCTIVE)
    return tuple(gates)


def cross_family_review(
    payload_provider: Callable[[], Any],
    *,
    public_attestation: bool,
    candidate_family: str,
    reviewer_family: str,
    reviewer_call: "Callable[[Any], tuple[bool, str]] | None" = None,
) -> Any:  # oracle.ReviewerVerdict | None — oracle is importlib-loaded, not a static type
    """Run a cross-family reviewer over the candidate payload, egress-gated.

    Egress happens ONLY when ``public_attestation`` is exactly ``True``.  For any
    other value — ``False`` *or a truthy non-bool such as the string ``"false"``* —
    this returns ``None`` and ``payload_provider`` is NOT invoked, so no payload
    (issue + patch) is ever built or sent.  The strict ``is True`` test mirrors the
    fail-closed discipline in ``oracle.decide_verdict``: a truthiness check here
    would let a malformed truthy value open egress *before* the downstream verdict
    caps the tier, leaking the payload the caller never attested as public (ADR
    0005).  The family validity check is intentionally NOT done here; it is enforced
    downstream in ``oracle.decide_verdict`` so even a same-family reviewer's verdict
    is neutralized to ``NECESSARY_GATE_ONLY``.

    ``reviewer_call`` is injectable; tests pass a fake so the real codex egress path
    is never exercised by the suite.  ``candidate_family`` is accepted for interface
    symmetry / future provenance and is not used to short-circuit egress.
    """

    if public_attestation is not True:
        return None
    call = reviewer_call if reviewer_call is not None else _default_codex_reviewer
    payload = payload_provider()
    accepted, reason_code = call(payload)
    return oracle.ReviewerVerdict(
        # Strict identity, not bool(): a reviewer_call returning a truthy non-bool
        # (e.g. the string "false") must NOT be widened to acceptance past
        # decide_verdict's ``accepted is True`` guard.
        accepted=accepted is True,
        reviewer_family=reviewer_family,
        reason_code=str(reason_code),
    )


def _default_codex_reviewer(payload: Any) -> tuple[bool, str]:
    """Real cross-family egress path: hand the payload to a read-only codex review.

    This is the ONLY function that actually sends the candidate payload to an
    external model, so it runs only when ``cross_family_review`` was called with
    ``public_attestation=True``.  It is deliberately minimal and is NOT exercised
    by the test suite (tests inject ``reviewer_call``).  The payload is written to a
    temp file and passed on stdin; only a short ``(accepted, reason_code)`` token
    pair is parsed back, never the model's prose.
    """

    text = payload if isinstance(payload, str) else str(payload)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=True) as handle:
        handle.write(text)
        handle.flush()
        with open(handle.name, "r", encoding="utf-8") as stdin_handle:
            proc = subprocess.run(
                [
                    "codex",
                    "exec",
                    "--sandbox",
                    "read-only",
                    "-c",
                    "model_reasoning_effort=high",
                ],
                stdin=stdin_handle,
                capture_output=True,
                text=True,
                timeout=_REVIEW_TIMEOUT_SECONDS,
                check=False,
            )
    verdict_line = proc.stdout.strip().splitlines()[-1].strip().lower() if proc.stdout.strip() else ""
    accepted = verdict_line.startswith("accept")
    reason_code = "ok" if accepted else "rejected"
    return accepted, reason_code


def evaluate(
    worktree: Path,
    *,
    task: Mapping[str, Any],
    candidate_family: str,
    public_attestation: bool,
    reviewer_family: str,
    payload_provider: Callable[[], Any],
    hidden_test_cmd: list[str],
    pytest_cmd: list[str],
    regression_cmd: list[str],
    diff_summary: "Mapping[str, Any] | None" = None,
    runner_subprocess: Callable[..., Any] = subprocess.run,
    reviewer_call: "Callable[[Any], tuple[bool, str]] | None" = None,
) -> dict[str, Any]:
    """Tie gates + hard-gate detection + cross-family review through the oracle.

    Returns a sanitized verdict dict only — no payload, prose, or command output:
    ``{"tier", "candidate_family", "reviewer_family"|None, "egress", "reason_code"|None}``.
    ``task`` is accepted for provenance symmetry; the verdict does not embed task prose.
    """

    gates = run_necessary_gates(
        worktree,
        hidden_test_cmd=hidden_test_cmd,
        pytest_cmd=pytest_cmd,
        regression_cmd=regression_cmd,
        runner_subprocess=runner_subprocess,
    )
    hard = detect_hard_gates(diff_summary or {})
    if hard:
        gates = oracle.GateResults(
            hidden_test_gate=gates.hidden_test_gate,
            pytest_pass=gates.pytest_pass,
            regression_pass=gates.regression_pass,
            hard_gates=hard,
        )
    # Privacy-preserving egress order: only hand the issue+patch payload to the
    # external cross-family reviewer when the objective gates ALREADY pass. If a
    # hard gate fired (e.g. added_secrets / destructive) or a necessary gate
    # failed, rejection is fully determined by the gates, so the payload — which
    # may contain exactly the secret/destructive content the hard gate detected —
    # must NOT leave the boundary (ADR 0005). Skipping the call here means no
    # payload is built or sent; decide_verdict then rejects on the gates alone.
    gates_pass = (
        not gates.hard_gates
        and gates.hidden_test_gate is True
        and gates.pytest_pass is True
        and gates.regression_pass is True
    )
    reviewer = (
        cross_family_review(
            payload_provider,
            public_attestation=public_attestation,
            candidate_family=candidate_family,
            reviewer_family=reviewer_family,
            reviewer_call=reviewer_call,
        )
        if gates_pass
        else None
    )
    tier = oracle.decide_verdict(
        gates,
        reviewer,
        candidate_family=candidate_family,
        public_attestation=public_attestation,
    )
    return {
        "tier": tier.name,
        "candidate_family": candidate_family,
        "reviewer_family": reviewer.reviewer_family if reviewer is not None else None,
        # Egress reflects whether the payload ACTUALLY left the boundary: a reviewer
        # object exists only when cross_family_review ran (gates passed AND public
        # attestation open). Gate failure or closed attestation => no egress.
        "egress": "performed" if reviewer is not None else "skipped",
        "reason_code": reviewer.reason_code if reviewer is not None else None,
    }
