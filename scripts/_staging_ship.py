"""Staging self-ship lane primitives + isolated lane (P1, ADR 0088).

Design note — isolation over surgery
-------------------------------------
ADR 0088 chose Option A (in-process opt-in lane). For P1 this module deliberately
keeps the ship execution **isolated** from ``scripts/agent_loop.py`` (a ~19k-line
load-bearing file): ``agent_loop.py`` is left byte-identical, and ``make 시작-ship``
composes the normal loop (EXECUTE_SHIP=0) with this standalone module as a post
step. This is the Architect-preferred "isolated ship authority" seam and guarantees
zero regression to the default ``make 시작`` path.

Enforcement model (ADR 0088 §4)
-------------------------------
The in-process guards below are a **1차 fast-fail (best-effort) first line, NOT the
authority**. A workspace-write runner can bypass them. The *authoritative* enforcement
lives outside the loop's permission domain: GitHub branch protection required checks
+ a permission-separated merge token. This module therefore (a) runs the cheap local
guards, and (b) **fails closed** (``EnforcementNotVerified``) unless the external
protection is read-verified, so it can never silently "pass" gate 3 without the real
GitHub setup.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ship_payload_guard import assert_no_raw_payload  # noqa: E402


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #
class StagingBoundaryViolation(RuntimeError):
    """Ship target is main/default rather than the staging integration branch."""


class ForcePushForbidden(RuntimeError):
    """A force-push / history-rewrite git invocation was attempted."""


class ShipArmConflict(RuntimeError):
    """make ship-arm is armed; the self-ship lane must not run concurrently."""


class EnforcementNotVerified(RuntimeError):
    """External branch-protection enforcement could not be read-verified (fail-closed)."""


# --------------------------------------------------------------------------- #
# Constitutional-invariant guards (1차 fast-fail; authority is external)
# --------------------------------------------------------------------------- #
# Branches the loop may NEVER ship to directly.
_PROTECTED_TARGETS: frozenset[str] = frozenset(
    {"main", "master", "head", "develop", "trunk", "release", ""}
)
# Only branches under this namespace are acceptable staging targets.
_STAGING_PREFIX = "autopilot/"
_STAGING_EXACT = "autopilot/integration"

_FORCE_PUSH_TOKENS: frozenset[str] = frozenset(
    {"--force", "-f", "--force-with-lease", "--mirror"}
)
_HISTORY_REWRITE_TOKENS: frozenset[str] = frozenset(
    {"filter-branch", "filter-repo"}
)


def assert_staging_target(branch: str | None) -> None:
    """Raise :class:`StagingBoundaryViolation` unless *branch* is a staging branch."""
    name = (branch or "").strip()
    if name.lower() in _PROTECTED_TARGETS:
        raise StagingBoundaryViolation(
            f"refusing to ship to protected/default branch {name!r}; "
            f"self-ship targets {_STAGING_EXACT!r} only"
        )
    if name == _STAGING_EXACT or name.startswith(_STAGING_PREFIX):
        return
    raise StagingBoundaryViolation(
        f"ship target {name!r} is not under {_STAGING_PREFIX!r}; staging-only (ADR 0088)"
    )


def assert_no_force_push(argv: list[str] | str) -> None:
    """Raise :class:`ForcePushForbidden` if a git argv force-pushes or rewrites history."""
    tokens = argv.split() if isinstance(argv, str) else list(argv)
    lowered = [t.lower() for t in tokens]
    is_push = "push" in lowered
    for tok in lowered:
        if tok in _HISTORY_REWRITE_TOKENS:
            raise ForcePushForbidden(f"history rewrite forbidden: {tok!r}")
        if is_push and tok in _FORCE_PUSH_TOKENS:
            raise ForcePushForbidden(f"force-push forbidden: {tok!r}")
        # `git push origin +ref` (leading '+') is a force update.
        if is_push and tok.startswith("+") and ":" not in tok and len(tok) > 1:
            raise ForcePushForbidden(f"force-push (refspec '+') forbidden: {tok!r}")


def kill_switch_active(state_dir: str | os.PathLike[str], *, env: dict[str, str] | None = None) -> bool:
    """True iff the root kill-switch is engaged (file ``<state_dir>/KILL`` or env)."""
    environ = env if env is not None else os.environ
    if environ.get("BIDMATE_SHIP_KILL_SWITCH", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return (Path(state_dir) / "KILL").exists()


def assert_ship_arm_not_active(repo_root: str | os.PathLike[str]) -> None:
    """Raise :class:`ShipArmConflict` if ``.claude/.ship-armed`` exists (ADR 0088 §7)."""
    if (Path(repo_root) / ".claude" / ".ship-armed").exists():
        raise ShipArmConflict(
            "make ship-arm is armed; self-ship lane and ship-arm are mutually exclusive"
        )


# --------------------------------------------------------------------------- #
# Circuit breaker counters
# --------------------------------------------------------------------------- #
@dataclass
class BoundedFailureCounter:
    """T1 for the *bounded* lane.

    ``agent_loop.py`` only counts consecutive blockers in infinite mode
    (``register_task_blocker`` short-circuits ``if not infinite_mode``), so the
    bounded staging lane needs its own independent consecutive-failure counter.
    """

    limit: int = 3
    consecutive: int = 0

    def record_success(self) -> None:
        self.consecutive = 0

    def record_failure(self) -> None:
        self.consecutive += 1

    def should_halt(self) -> bool:
        return self.consecutive >= self.limit


@runtime_checkable
class ImmutableCounterStore(Protocol):
    """A daily-merge counter store that the loop CANNOT reset (self-immutable).

    The real store must live outside the runner's write domain (e.g. derived from a
    server-side artifact or a path the merge token cannot write). ``loop_writable``
    MUST be ``False`` or the breaker is not self-immutable and the lane fails closed.
    """

    loop_writable: bool

    def get(self, day: str) -> int: ...
    def increment(self, day: str) -> None: ...


@dataclass
class DailyMergeCapCounter:
    """T4 daily-merge cap. Refuses a non-self-immutable store (ADR 0088 §6)."""

    store: ImmutableCounterStore
    cap: int = 5

    def __post_init__(self) -> None:
        if getattr(self.store, "loop_writable", True):
            raise EnforcementNotVerified(
                "T4 counter store is loop-writable; a self-immutable store is required "
                "(the loop must not be able to reset its own merge cap)"
            )

    def would_exceed(self, day: str) -> bool:
        return self.store.get(day) >= self.cap

    def record_merge(self, day: str) -> None:
        self.store.increment(day)


# --------------------------------------------------------------------------- #
# Git/gh operations interface (injectable for tests)
# --------------------------------------------------------------------------- #
@runtime_checkable
class GitOps(Protocol):
    """Side-effecting git/gh operations, injected so the lane is unit-testable."""

    def protection_verified(self, branch: str) -> bool:
        """Read-verify (e.g. ``gh api``) that *branch* has required-check + force-push-deny.
        Returns False when the external enforcement is absent/unverifiable."""
        ...

    def open_pr(self, *, source: str, base: str, title: str, body: str) -> str: ...

    def required_checks_all_success(self, pr_id: str) -> bool:
        """True only when ALL required status checks reported SUCCESS (pending/absent -> False)."""
        ...

    def merge(self, pr_id: str) -> None: ...


@dataclass
class ShipResult:
    decision: str  # "shipped" | "blocked-ci" | "halted-kill-switch" | "blocked-cap" | "blocked-on-user"
    pr_id: str | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class StagingShipLane:
    """Isolated staging self-ship lane. Authority is external; this runs the seam."""

    ops: GitOps
    repo_root: str | os.PathLike[str]
    state_dir: str | os.PathLike[str]
    merge_cap: DailyMergeCapCounter
    failures: BoundedFailureCounter = field(default_factory=BoundedFailureCounter)
    target_branch: str = _STAGING_EXACT
    require_external_enforcement: bool = True

    def ship(self, *, source: str, title: str, body: str, day: str) -> ShipResult:
        # 1) mutual exclusion with ship-arm (ADR 0088 §7)
        assert_ship_arm_not_active(self.repo_root)
        # 2) kill-switch (checked before any side effect)
        if kill_switch_active(self.state_dir):
            return ShipResult("halted-kill-switch", reasons=["root kill-switch engaged"])
        # 3) staging boundary + force-push posture (1차 fast-fail)
        assert_staging_target(self.target_branch)
        assert_no_force_push(["git", "push", "origin", source])
        # 4) data boundary on the PR payload (ADR 0005 / 0088 §5)
        assert_no_raw_payload(title)
        assert_no_raw_payload(body)
        # 5) external enforcement read-verify — fail closed (authority lives here)
        if self.require_external_enforcement and not self.ops.protection_verified(self.target_branch):
            return ShipResult(
                "blocked-on-user",
                reasons=[
                    f"branch protection for {self.target_branch!r} not verified; "
                    "configure protected branch + permission-separated token (see runbook). "
                    "NOT faking gate 3."
                ],
            )
        # 6) daily merge cap (T4)
        if self.merge_cap.would_exceed(day):
            self.failures.record_failure()
            return ShipResult("blocked-cap", reasons=[f"daily merge cap {self.merge_cap.cap} reached"])
        # 7) open PR + require ALL required checks green before merge
        pr_id = self.ops.open_pr(source=source, base=self.target_branch, title=title, body=body)
        if not self.ops.required_checks_all_success(pr_id):
            self.failures.record_failure()
            return ShipResult("blocked-ci", pr_id=pr_id, reasons=["required checks not all SUCCESS"])
        self.ops.merge(pr_id)
        self.merge_cap.record_merge(day)
        self.failures.record_success()
        return ShipResult("shipped", pr_id=pr_id)


# --------------------------------------------------------------------------- #
# Real git/gh ops (used by the CLI). Kept thin; unit tests use a fake.
# --------------------------------------------------------------------------- #
class _RealGitOps:  # pragma: no cover - exercised only with a live GitHub remote
    """Shells out to git/gh. ``protection_verified`` returns False unless the
    operator has set up the protected branch + token (so the CLI fails closed)."""

    def protection_verified(self, branch: str) -> bool:
        token_scoped = os.environ.get("BIDMATE_SHIP_TOKEN_SEPARATED", "").lower() in {"1", "true", "yes"}
        protection_ok = os.environ.get("BIDMATE_SHIP_PROTECTION_VERIFIED", "").lower() in {"1", "true", "yes"}
        return token_scoped and protection_ok

    def open_pr(self, *, source: str, base: str, title: str, body: str) -> str:
        raise EnforcementNotVerified(
            "real PR open requires verified external enforcement; not reached in P1 local"
        )

    def required_checks_all_success(self, pr_id: str) -> bool:
        return False

    def merge(self, pr_id: str) -> None:
        raise EnforcementNotVerified("real merge requires verified external enforcement")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P1 staging self-ship lane (ADR 0088)")
    parser.add_argument("--source", default="", help="source branch to ship")
    parser.add_argument("--title", default="")
    parser.add_argument("--body", default="")
    parser.add_argument("--day", default="")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--state-dir", default=".omc/state")
    parser.parse_args(argv)  # validate the interface; P2 wires these through

    # P1 CLI: with no verified external enforcement this honestly refuses to ship,
    # rather than faking gate 3. The operator runbook (docs/operations/staging-self-ship.md)
    # describes the GitHub-admin setup required to make this lane real.
    ops = _RealGitOps()
    if not ops.protection_verified(_STAGING_EXACT):
        sys.stderr.write(
            "[staging-self-ship] blocked-on-user: external enforcement not verified.\n"
            "  Required (operator GitHub-admin action, see docs/operations/staging-self-ship.md):\n"
            "    1. create protected branch 'autopilot/integration' with required status checks\n"
            "    2. provision a permission-separated merge token (no protection bypass)\n"
            "    3. set BIDMATE_SHIP_PROTECTION_VERIFIED=1 BIDMATE_SHIP_TOKEN_SEPARATED=1 after gate-3 live e2e\n"
            "  Refusing to ship (not faking gate 3).\n"
        )
        return 2
    sys.stderr.write("[staging-self-ship] enforcement verified; lane wiring is P2 scope.\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
