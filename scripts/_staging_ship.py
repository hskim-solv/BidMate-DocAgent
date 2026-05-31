"""Staging self-ship lane primitives + isolated lane (P2.0 D1, ADR 0088/0090).

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

D1 scope (this PR)
------------------
This PR ships exactly **D1 = enforcement-model activation + manifest contract**:
  1. The ship-manifest contract (write/read/archive + schema) — the loop→lane hand-off.
  2. A *live* read-only ``protection_verified`` that actually queries GitHub branch
     protection (``gh repo view`` + ``gh api .../protection``) and returns True only
     when the specific ``staging-self-ship-guard`` required check is present AND
     force-push is denied.
The **autonomous merge orchestration** (PR open/merge, daily-cap transactionality,
serialized promotion via a single-instance lock, source-SHA binding) is deliberately
DEFERRED to **P2.2** because it needs cross-worktree transactional hardening. The
``_RealGitOps`` open_pr/merge methods are therefore honest stubs that raise
``EnforcementNotVerified``, and ``main()`` is a verify-and-refuse pre-flight harness
that NEVER merges.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import quote

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

# ADR 0088 external-enforcement authority: this exact required status check must be
# present in the branch protection, not merely *some* required check.
_REQUIRED_STAGING_CHECK = "staging-self-ship-guard"

# Bounded timeout for every gh subprocess call so a hung/unreachable gh cannot wedge
# the read-only verifier. A timeout is treated as verification failure (fail closed).
_GH_TIMEOUT_SEC = 30

# Ambient gh env keys the read-only D1 verify must NOT inherit (issue #1697 Fix 3):
# `GH_REPO` could misdirect the protection read at the wrong repo; the mutation tokens
# would over-privilege a read-only verify (it must use the operator's default gh auth).
_GH_AMBIENT_DROP_KEYS: frozenset[str] = frozenset(
    {"GH_REPO", "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN"}
)

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
        # `--force*` flag in any form, incl. the `=value` syntax (issue #1697 Fix 4b):
        # `--force-with-lease=main`, `--force-if-includes`, etc. A prefix match (not just
        # exact membership) catches the `=`-attached variants the frozenset misses.
        if is_push and tok.startswith("--force"):
            raise ForcePushForbidden(f"force-push forbidden: {tok!r}")
        # ANY push refspec token with a leading '+' is a force update, including the
        # `+src:dst` form (issue #1697 Fix 4a): `+main:autopilot/integration` overwrites
        # the destination. A normal `src:dst` (no leading '+') is a fast-forward and is
        # NOT a force update, so only the leading '+' triggers.
        if is_push and tok.startswith("+") and len(tok) > 1:
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
# Ship manifest contract (P2.0 D1, ADR 0090) — loop -> lane hand-off
# --------------------------------------------------------------------------- #
SHIP_MANIFEST_FILENAME = "ship_manifest.json"
SHIP_MANIFEST_CONSUMED = "ship_manifest.consumed.json"
SHIP_MANIFEST_SCHEMA_VERSION = 1

_SHIP_MANIFEST_REQUIRED_KEYS = frozenset(
    {"schema_version", "source_branch", "source_sha", "title", "body", "day"}
)


def write_ship_manifest(
    manifest_dir: str | os.PathLike[str],
    *,
    source_branch: str,
    source_sha: str,
    title: str,
    body: str,
    day: str,
    now: datetime | None = None,
) -> Path:
    """Write ``<manifest_dir>/ship_manifest.json`` with the P2.0 contract.

    ``agent_loop.py`` imports and calls this with the keyword signature above;
    the signature is part of the contract — do not change it. ``source_sha`` binds
    the merge to the exact gated commit (consumed by the deferred P2.2 merge
    orchestration via ``--match-head-commit``).
    """
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    payload = {
        "schema_version": SHIP_MANIFEST_SCHEMA_VERSION,
        "source_branch": source_branch,
        "source_sha": source_sha,
        "title": title,
        "body": body,
        "day": day,
        "generated_at": generated_at,
    }
    directory = Path(manifest_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / SHIP_MANIFEST_FILENAME
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


# A valid source_sha is a full 40-char lowercase hex git SHA (binds the deferred P2.2
# merge to the exact gated commit). A malformed/empty SHA fails the manifest closed.
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def read_ship_manifest(manifest_dir: str | os.PathLike[str]) -> dict | None:
    """Read + validate ``<dir>/ship_manifest.json`` WITHOUT consuming it.

    Parses the manifest and validates the P2.0 contract, then returns the dict.
    This is intentionally **idempotent / re-readable**: it does NOT rename the file
    (codex #3 / G1). Consumption happens only on a successful ship via
    :func:`archive_ship_manifest`, so a blocked / interrupted run leaves the manifest
    in place and the next ``시작-ship`` run resumes from it. Returns ``None`` when
    the manifest is absent. Raises :class:`ValueError` on missing keys / wrong schema.
    """
    directory = Path(manifest_dir)
    src = directory / SHIP_MANIFEST_FILENAME
    if not src.exists():
        return None
    data = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"ship manifest {src} is not a JSON object")
    missing = _SHIP_MANIFEST_REQUIRED_KEYS - set(data)
    if missing:
        raise ValueError(
            f"ship manifest {src} missing required keys: {sorted(missing)}"
        )
    if data["schema_version"] != SHIP_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"ship manifest {src} schema_version {data['schema_version']!r} "
            f"!= expected {SHIP_MANIFEST_SCHEMA_VERSION}"
        )
    source_sha = data.get("source_sha")
    if not isinstance(source_sha, str) or not _SHA_RE.match(source_sha):
        raise ValueError(
            f"ship manifest {src} source_sha {source_sha!r} is not a 40-char hex SHA"
        )
    return data


def archive_ship_manifest(manifest_dir: str | os.PathLike[str]) -> None:
    """Consume the manifest by renaming it to ``ship_manifest.consumed.json``.

    Called ONLY after a successful ship so the manifest can never be re-consumed once
    its work landed. ``os.replace`` is atomic; a no-op when the source manifest is
    already gone (idempotent). NOTE: the D1 ``main()`` harness never ships, so it does
    not archive — archiving belongs to the deferred P2.2 merge orchestration.
    """
    directory = Path(manifest_dir)
    src = directory / SHIP_MANIFEST_FILENAME
    if not src.exists():
        return
    os.replace(src, directory / SHIP_MANIFEST_CONSUMED)


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
# Real git/gh ops (used by the CLI). Runner is injectable so the methods are
# unit-testable without touching the network.
#
# D1 split: ``protection_verified`` is LIVE (read-only) — it actually queries the
# GitHub branch protection. The side-effecting merge orchestration (open_pr / merge /
# required_checks_all_success) is DEFERRED to P2.2 and kept as honest stubs that
# refuse rather than fake.
# --------------------------------------------------------------------------- #
class _RealGitOps:
    """Shells out to git/gh via an injectable runner.

    ``protection_verified`` read-verifies the *actual* GitHub branch protection
    (the ``staging-self-ship-guard`` required check is present + force-push denied);
    there is no env-trust bypass. The merge-orchestration methods are deferred to
    P2.2 and raise/return so this lane can verify external enforcement read-only
    without yet auto-merging.
    """

    def __init__(self, run=None, repo_root="."):
        self._run = run or subprocess.run
        self._repo_root = str(repo_root)

    def _gh(self, argv: list[str], *, env: dict[str, str] | None = None):
        # Resolve gh against THIS repo regardless of process cwd (codex Fix 1):
        # cwd binds gh's repo auto-detection to repo_root so a runner started from
        # a sibling worktree cannot read the wrong repo's branch protection.
        #
        # Sanitize the inherited environment (issue #1697 Fix 3): the D1 verify is
        # read-only, so it must NOT inherit an ambient `GH_REPO` (which could
        # misdirect the protection read at the wrong repo) nor the ambient mutation
        # credentials `GH_TOKEN` / `GITHUB_TOKEN` / `GH_ENTERPRISE_TOKEN` (a
        # read-only verify must use the operator's default gh auth, not an inherited
        # over-privileged mutation token). owner/repo is derived from `gh repo view`
        # bound to cwd=repo_root, so dropping GH_REPO does not lose the target.
        if env is None:
            env = {
                k: v
                for k, v in os.environ.items()
                if k not in _GH_AMBIENT_DROP_KEYS
            }
        return self._run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            env=env,
            cwd=self._repo_root,
            timeout=_GH_TIMEOUT_SEC,
        )

    def protection_verified(self, branch: str) -> bool:
        # Fail CLOSED on ANY environmental failure of the gh subprocess (issue #1697
        # BLOCKING): gh missing (FileNotFoundError/OSError), a hung gh
        # (subprocess.TimeoutExpired), an invalid cwd, or any other SubprocessError
        # must be treated as verification failure → return False, never propagate out
        # of this verifier and crash main(). Nonzero rc + unparseable JSON + incomplete
        # protection state are handled below and likewise fail closed.
        # Derive owner/repo for the gh api path.
        try:
            view = self._gh(["gh", "repo", "view", "--json", "owner,name"])
        except (OSError, subprocess.SubprocessError):
            return False
        if view.returncode != 0:
            return False
        try:
            repo = json.loads(view.stdout)
            owner = repo["owner"]["login"]
            name = repo["name"]
        except (ValueError, KeyError, TypeError):
            return False
        # URL-encode the branch (staging branches contain a slash, e.g.
        # ``autopilot/integration`` -> ``autopilot%2Fintegration``) so the gh api
        # path is not malformed (informational #1 / G4).
        encoded_branch = quote(branch, safe="")
        try:
            proc = self._gh(
                ["gh", "api", f"repos/{owner}/{name}/branches/{encoded_branch}/protection"]
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if proc.returncode != 0:
            return False
        try:
            protection = json.loads(proc.stdout)
        except ValueError:
            return False
        if not isinstance(protection, dict):
            return False
        # Required status checks must exist AND include the ADR 0088 authority check
        # (``staging-self-ship-guard``). Some unrelated required check is not enough.
        required = protection.get("required_status_checks")
        if not isinstance(required, dict):
            return False
        # `strict` must be EXPLICITLY True (require branches up-to-date before merge):
        # absent / false / non-bool => fail closed, otherwise a stale source could be
        # merged past the required check (issue #1697 Fix 1).
        if required.get("strict") is not True:
            return False
        names: set[str] = set()
        contexts = required.get("contexts")
        if isinstance(contexts, list):
            names.update(c for c in contexts if isinstance(c, str))
        checks = required.get("checks")
        if isinstance(checks, list):
            names.update(
                item["context"]
                for item in checks
                if isinstance(item, dict) and isinstance(item.get("context"), str)
            )
        if _REQUIRED_STAGING_CHECK not in names:
            return False
        # Force-pushes must be EXPLICITLY denied (codex Fix 2: fail CLOSED on
        # incomplete state). An ABSENT `allow_force_pushes` key, a non-dict value, or
        # a missing/truthy `enabled` is NOT proof of denial — only an explicit
        # `allow_force_pushes.enabled is False` counts.
        force = protection.get("allow_force_pushes")
        if not isinstance(force, dict) or force.get("enabled") is not False:
            return False
        # Admins must NOT be able to bypass the required check (no admin merge of an
        # un-gated promotion). Require `enforce_admins.enabled is True` explicitly;
        # absent / false / non-dict => fail closed.
        admins = protection.get("enforce_admins")
        if not isinstance(admins, dict) or admins.get("enabled") is not True:
            return False
        return True

    def open_pr(self, *, source: str, base: str, title: str, body: str) -> str:
        raise EnforcementNotVerified(
            "live merge orchestration is deferred to P2.2; this lane verifies external "
            "enforcement but does not yet auto-merge"
        )

    def required_checks_all_success(self, pr_id: str) -> bool:
        return False

    def merge(self, pr_id: str) -> None:
        raise EnforcementNotVerified(
            "live merge orchestration is deferred to P2.2; this lane verifies external "
            "enforcement but does not yet auto-merge"
        )


def main(argv: list[str] | None = None) -> int:
    """D1 verify-and-refuse harness — NEVER merges.

    Reads the ship manifest (loop → lane hand-off), runs the cheap local guards, and
    LIVE-verifies the external GitHub branch protection (read-only). It ALWAYS returns
    2 (blocked-on-user) because the autonomous merge orchestration (PR open/merge,
    daily-cap transactionality, serialized promotion, source-SHA binding) is deferred
    to P2.2. This is an honest pre-flight; nothing is faked.
    """
    parser = argparse.ArgumentParser(
        description="P2.0 D1 staging self-ship pre-flight harness (ADR 0088/0090); does NOT merge"
    )
    parser.add_argument("--source", default="", help="source branch to ship")
    parser.add_argument("--title", default="")
    parser.add_argument("--body", default="")
    parser.add_argument("--day", default="")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--state-dir", default=".omc/state")
    parser.add_argument(
        "--manifest-dir",
        default="",
        help="dir holding ship_manifest.json (defaults to --state-dir)",
    )
    args = parser.parse_args(argv)

    # 1) Read the manifest (loop -> lane hand-off). The read is idempotent — D1 never
    #    ships, so it never archives the manifest (consumption belongs to P2.2).
    manifest_dir = args.manifest_dir or args.state_dir
    try:
        manifest = read_ship_manifest(manifest_dir)
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        # codex Fix 3: a malformed manifest is a user-config problem, not a crash.
        sys.stderr.write(
            f"[staging-self-ship] blocked-on-user: invalid ship manifest: {exc}\n"
        )
        return 2
    if manifest is not None:
        source = manifest["source_branch"]
        title = manifest["title"]
        body = manifest["body"]
        day = manifest["day"]
    else:
        source = title = body = day = ""
    # CLI flags override manifest fields when non-empty.
    source = args.source or source
    title = args.title or title
    body = args.body or body
    day = args.day or day

    # 2) Cheap local guards (1차 fast-fail). Any trip fails closed rc 2.
    #    NOTE: the "no manifest + no source" refusal is deliberately DEFERRED to step 4
    #    (after the live protection pre-flight) so that `make 시작-ship` with no manifest
    #    and no --source STILL exercises + reports the headline D-minus value — the live
    #    branch-protection verifier (issue #1697 Fix 2). Refusing here would skip it.
    try:
        assert_ship_arm_not_active(args.repo_root)
        if kill_switch_active(args.state_dir):
            sys.stderr.write(
                "[staging-self-ship] blocked-on-user: root kill-switch engaged\n"
            )
            return 2
        assert_staging_target(_STAGING_EXACT)
        assert_no_force_push(["git", "push", "origin", source or _STAGING_EXACT])
        assert_no_raw_payload(title)
        assert_no_raw_payload(body)
    except (ShipArmConflict, StagingBoundaryViolation, ForcePushForbidden) as exc:
        sys.stderr.write(f"[staging-self-ship] blocked-on-user: local guard tripped: {exc}\n")
        return 2
    except Exception as exc:  # noqa: BLE001 — assert_no_raw_payload raises its own type
        sys.stderr.write(f"[staging-self-ship] blocked-on-user: payload guard tripped: {exc}\n")
        return 2

    # 3) LIVE read-only verification of the external enforcement model. This is the
    #    real D1 deliverable and ALWAYS runs — even with no manifest / no --source — so
    #    the default `make 시작-ship` path still exercises + reports the live check
    #    (issue #1697 Fix 2). Query GitHub branch protection and report whether the
    #    `staging-self-ship-guard` required check + force-push-deny are in place.
    ops = _RealGitOps(repo_root=args.repo_root)
    enforcement_verified = ops.protection_verified(_STAGING_EXACT)
    if enforcement_verified:
        sys.stderr.write(
            f"[staging-self-ship] external enforcement for {_STAGING_EXACT!r} is VERIFIED "
            "(required staging-self-ship-guard check present, force-push denied).\n"
        )
    else:
        sys.stderr.write(
            f"[staging-self-ship] external enforcement for {_STAGING_EXACT!r} is NOT verified "
            "(missing required staging-self-ship-guard check, force-push allowed, or unreachable).\n"
        )

    # 3b) No work to ship (no manifest AND no --source). The live protection pre-flight
    #     above has already run + reported (issue #1697 Fix 2), so the headline D-minus
    #     value is exercised even on the default path. Refuse rc 2 — there is nothing
    #     to hand to the (deferred) P2.2 merge orchestration.
    if manifest is None and not args.source:
        sys.stderr.write("[staging-self-ship] blocked-on-user: no ship manifest\n")
        return 2

    # 4) ALWAYS refuse to merge in D1, but the message must be HONEST about whether
    #    protection was actually verified (codex Fix 4): only claim "verified
    #    read-only" when the live check returned True; otherwise focus on the
    #    unverified/unreachable enforcement. Either way autonomous merge orchestration
    #    is deferred to P2.2.
    if enforcement_verified:
        sys.stderr.write(
            "[staging-self-ship] blocked-on-user: enforcement model verified read-only, but "
            "autonomous merge orchestration (PR open/merge, daily-cap transactionality, "
            "serialized promotion, source-SHA binding) is deferred to P2.2 — this lane does "
            "not yet auto-merge.\n"
        )
    else:
        sys.stderr.write(
            "[staging-self-ship] blocked-on-user: external enforcement NOT verified / not "
            "reachable (required staging-self-ship-guard check, explicit force-push-deny, and "
            "enforce_admins not confirmed). Autonomous merge orchestration is also deferred to "
            "P2.2 — this lane does not yet auto-merge.\n"
        )
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
