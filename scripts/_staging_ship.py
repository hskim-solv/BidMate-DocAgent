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

D1 + v1 primitive scope
-----------------------
This module keeps main promotion live wiring deferred, but now carries the local
contracts and explicit staging live path needed by self-ship v1:
  1. The ship-manifest contract (write/read/archive + schema) — the loop→lane hand-off.
  2. A *live* read-only ``protection_verified`` that actually queries GitHub branch
     protection (``gh repo view`` + ``gh api .../protection``) and returns True only
     when the specific ``staging-self-ship-guard`` required check is present AND
     force-push is denied.
  3. An explicit ``--execute-live-staging`` path for staging PR create/check/merge
     using ``BIDMATE_SHIP_MERGE_TOKEN`` and ``--match-head-commit``.
  4. A read-only GraphQL resolver for main review-gate facts
     (``reviewDecision`` + unresolved non-outdated review threads).
  5. Fail-closed local primitives for main-gate simulation, guard-change external
     ack, bounded no-cap mode, and promotion locking.
The **main** autonomous merge orchestration (main source binding around live PRs,
live main mutation, and durable cap-store semantics) is still deferred. The default
CLI mode remains verify-and-refuse; staging mutation requires the explicit flag and
never uses admin/delete-branch bypasses.
"""

from __future__ import annotations

import argparse
import fnmatch
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
_TARGET_STAGING = "staging"
_TARGET_MAIN = "main"
_MAIN_EXACT = "main"

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
_SHIP_MERGE_TOKEN_ENV = "BIDMATE_SHIP_MERGE_TOKEN"
_REVIEW_THREADS_PAGE_SIZE = 100
_REVIEW_THREADS_MAX_PAGES = 10
_REVIEW_GATE_QUERY = """
query(
  $owner: String!,
  $name: String!,
  $number: Int!,
  $first: Int!,
  $after: String
) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewDecision
      reviewThreads(first: $first, after: $after) {
        nodes {
          isResolved
          isOutdated
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}
""".strip()

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
SHIP_MANIFEST_SCHEMA_VERSION = 2

_SHIP_MANIFEST_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "source_branch",
        "source_sha",
        "target",
        "base_branch",
        "title",
        "body",
        "day",
        "gate_evidence_path",
        "gate_evidence_digest",
        "protected_paths_changed",
        "ci_evidence_ref",
        "review_gate_ref",
    }
)

SELF_SHIP_PROTECTED_PATH_GLOBS: tuple[str, ...] = (
    "Makefile",
    "scripts/agent_loop.py",
    "scripts/_staging_ship.py",
    "scripts/_ship_env.py",
    "scripts/claude-hooks/**",
    ".githooks/**",
    ".claude/settings.json",
    ".github/CODEOWNERS",
    ".github/workflows/staging-self-ship-guard.yml",
    ".github/workflows/branch-and-issue-check.yml",
    ".github/workflows/pr-eval.yml",
    "docs/operations/staging-self-ship.md",
    "docs/operations/auto-ship.md",
    "docs/operations/active-agent-loop.md",
    "docs/adr/0088-*",
    "docs/adr/0090-*",
    "docs/adr/*self-ship*",
)

_ALLOWED_MANIFEST_TARGETS = frozenset({_TARGET_STAGING, _TARGET_MAIN})
_ACK_ALLOWED_PERMISSIONS = frozenset({"maintain", "admin"})
_ACK_DENIED_ACTOR_KINDS = frozenset(
    {"runner", "bot", "github-actions", "dependency-bot", "codex", "claude", "omx", "merge-token"}
)


def write_ship_manifest(
    manifest_dir: str | os.PathLike[str],
    *,
    source_branch: str,
    source_sha: str,
    title: str,
    body: str,
    day: str,
    target: str = _TARGET_STAGING,
    base_branch: str = _STAGING_EXACT,
    gate_evidence_path: str = "",
    gate_evidence_digest: str = "",
    protected_paths_changed: list[str] | tuple[str, ...] | None = None,
    ci_evidence_ref: str = "",
    review_gate_ref: str = "",
    now: datetime | None = None,
) -> Path:
    """Write ``<manifest_dir>/ship_manifest.json`` with the v2 contract.

    ``agent_loop.py`` imports and calls this with the keyword signature above;
    the signature is part of the contract — do not change it. ``source_sha`` binds
    the merge to the exact gated commit (consumed by live staging / deferred main
    orchestration via ``--match-head-commit``).
    """
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    payload = {
        "schema_version": SHIP_MANIFEST_SCHEMA_VERSION,
        "source_branch": source_branch,
        "source_sha": source_sha,
        "target": target,
        "base_branch": base_branch,
        "title": title,
        "body": body,
        "day": day,
        "gate_evidence_path": gate_evidence_path,
        "gate_evidence_digest": gate_evidence_digest,
        "protected_paths_changed": sorted(set(protected_paths_changed or [])),
        "ci_evidence_ref": ci_evidence_ref,
        "review_gate_ref": review_gate_ref,
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


# A valid source_sha is a full 40-char lowercase hex git SHA (binds live staging /
# deferred main merge to the exact gated commit). A malformed/empty SHA fails closed.
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def read_ship_manifest(manifest_dir: str | os.PathLike[str]) -> dict | None:
    """Read + validate ``<dir>/ship_manifest.json`` WITHOUT consuming it.

    Parses the manifest and validates the schema v2 contract, then returns the dict.
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
    target = data.get("target")
    if target not in _ALLOWED_MANIFEST_TARGETS:
        raise ValueError(
            f"ship manifest {src} target {target!r} must be one of {sorted(_ALLOWED_MANIFEST_TARGETS)}"
        )
    for key in (
        "source_branch",
        "base_branch",
        "title",
        "body",
        "day",
        "gate_evidence_path",
        "gate_evidence_digest",
        "ci_evidence_ref",
        "review_gate_ref",
    ):
        if not isinstance(data.get(key), str):
            raise ValueError(f"ship manifest {src} field {key!r} must be a string")
    if target == _TARGET_STAGING and data["base_branch"] != _STAGING_EXACT:
        raise ValueError(
            f"ship manifest {src} staging target must bind base_branch to {_STAGING_EXACT!r}"
        )
    if target == _TARGET_MAIN:
        if data["base_branch"] != _MAIN_EXACT:
            raise ValueError(
                f"ship manifest {src} main target must bind base_branch to {_MAIN_EXACT!r}"
            )
        for key in (
            "gate_evidence_path",
            "gate_evidence_digest",
            "ci_evidence_ref",
            "review_gate_ref",
        ):
            if not data[key].strip():
                raise ValueError(f"ship manifest {src} main field {key!r} must be non-empty")
    protected_paths = data.get("protected_paths_changed")
    if not isinstance(protected_paths, list) or not all(
        isinstance(path, str) for path in protected_paths
    ):
        raise ValueError(
            f"ship manifest {src} protected_paths_changed must be a list of strings"
        )
    return data


def detect_self_ship_protected_paths(paths: list[str] | tuple[str, ...]) -> list[str]:
    """Return changed paths that require external human ack for main self-ship.

    This is an in-process detector only. The authoritative unblock decision still
    comes from external ack evidence resolved by the promoter.
    """
    protected: set[str] = set()
    for raw in paths:
        path = str(raw).strip().lstrip("./")
        if any(fnmatch.fnmatchcase(path, pattern) for pattern in SELF_SHIP_PROTECTED_PATH_GLOBS):
            protected.add(path)
    return sorted(protected)


@dataclass(frozen=True)
class GuardChangeAck:
    """External ack evidence for guard/ship/protection path changes.

    Runner-authored manifests/reports are never valid ack sources. The promoter
    must bind this evidence to the exact source SHA and protected path set.
    """

    actor: str
    actor_kind: str
    source_sha: str
    protected_paths: tuple[str, ...]
    permission: str = ""
    external: bool = True
    codeowner_approval: bool = False


def guard_change_ack_valid(
    ack: GuardChangeAck | None,
    *,
    source_sha: str,
    protected_paths: list[str] | tuple[str, ...],
) -> bool:
    """True only for external maintainer/admin/CODEOWNER ack bound to this diff."""
    required_paths = tuple(sorted(set(protected_paths)))
    if not required_paths:
        return True
    if ack is None or not ack.external:
        return False
    if ack.actor_kind.strip().lower() in _ACK_DENIED_ACTOR_KINDS:
        return False
    if ack.source_sha != source_sha:
        return False
    if tuple(sorted(set(ack.protected_paths))) != required_paths:
        return False
    if ack.codeowner_approval:
        return True
    return ack.permission.strip().lower() in _ACK_ALLOWED_PERMISSIONS


def review_gate_clean(
    review_decision: str | None,
    unresolved_non_outdated_threads: int | None,
    *,
    api_error: bool = False,
) -> bool:
    """Main review gate: APPROVED and zero unresolved non-outdated threads only."""
    if api_error:
        return False
    if review_decision != "APPROVED":
        return False
    return unresolved_non_outdated_threads == 0


@dataclass(frozen=True)
class ReviewGateResolution:
    """Read-only GitHub review gate facts resolved by the promoter.

    ``api_error=True`` means the result must be treated as not clean. The
    unresolved count is only authoritative when every requested page was fetched
    and parsed.
    """

    review_decision: str | None
    unresolved_non_outdated_threads: int | None
    fetched_thread_pages: int = 0
    api_error: bool = False


def _review_gate_api_error(
    *,
    review_decision: str | None = None,
    fetched_thread_pages: int = 0,
) -> ReviewGateResolution:
    return ReviewGateResolution(
        review_decision=review_decision,
        unresolved_non_outdated_threads=None,
        fetched_thread_pages=fetched_thread_pages,
        api_error=True,
    )


@dataclass(frozen=True)
class MainGateSnapshot:
    """Promoter-resolved external facts for main promotion.

    Manifest refs may point to evidence, but they do not authorize merge. This
    snapshot is the value object used by tests/fake GitHub adapters to prove that
    the promoter, not the runner, resolved CI/review/protection/source state.
    """

    ci_green: bool
    review_decision: str | None
    unresolved_non_outdated_threads: int | None
    protection_verified: bool
    token_verified: bool
    pr_head_sha: str | None
    api_error: bool = False


def bounded_main_without_cap_blocker(
    *,
    target: str,
    target_manifest_count: int,
    distinct_main_source_sha_count: int,
    start_infinite: bool = False,
    active_auto_loop_max_iterations: int | None = None,
    retry_loop_requested: bool = False,
) -> ShipResult | None:
    """Block unbounded main promotion until a self-immutable cap store exists."""
    if target != _TARGET_MAIN:
        return None
    reasons: list[str] = []
    if start_infinite:
        reasons.append("START_INFINITE=1")
    if active_auto_loop_max_iterations == 0:
        reasons.append("ACTIVE_AUTO_LOOP_MAX_ITERATIONS=0")
    if target_manifest_count > 1:
        reasons.append("multiple main manifests in one invocation")
    if retry_loop_requested:
        reasons.append("automatic retry loop requested")
    if distinct_main_source_sha_count > 1:
        reasons.append("more than one distinct main source SHA")
    if reasons:
        return ShipResult("main-blocked-cap-deferred", reasons=reasons)
    return None


def evaluate_main_promotion(
    manifest: dict,
    gates: MainGateSnapshot,
    *,
    ack: GuardChangeAck | None = None,
    target_manifest_count: int = 1,
    distinct_main_source_sha_count: int = 1,
    start_infinite: bool = False,
    active_auto_loop_max_iterations: int | None = None,
    retry_loop_requested: bool = False,
) -> ShipResult:
    """Simulate the fail-closed main promotion gate from promoter-resolved facts."""
    if manifest.get("target") != _TARGET_MAIN:
        return ShipResult("not-main", reasons=["manifest target is not main"])
    cap_block = bounded_main_without_cap_blocker(
        target=_TARGET_MAIN,
        target_manifest_count=target_manifest_count,
        distinct_main_source_sha_count=distinct_main_source_sha_count,
        start_infinite=start_infinite,
        active_auto_loop_max_iterations=active_auto_loop_max_iterations,
        retry_loop_requested=retry_loop_requested,
    )
    if cap_block is not None:
        return cap_block
    if not gates.protection_verified:
        return ShipResult("main-blocked-protection", reasons=["main branch protection not verified"])
    if not gates.token_verified:
        return ShipResult("main-blocked-token", reasons=["merge token not verified as non-admin"])
    if not gates.ci_green:
        return ShipResult("main-blocked-ci", reasons=["promoter-resolved CI is not green"])
    if not review_gate_clean(
        gates.review_decision,
        gates.unresolved_non_outdated_threads,
        api_error=gates.api_error,
    ):
        return ShipResult("main-blocked-review", reasons=["review gate is not clean"])
    source_sha = manifest.get("source_sha")
    if gates.pr_head_sha != source_sha:
        return ShipResult("main-blocked-source-mismatch", reasons=["PR head SHA differs from manifest"])
    protected_paths = manifest.get("protected_paths_changed") or []
    if protected_paths and not guard_change_ack_valid(
        ack,
        source_sha=source_sha,
        protected_paths=protected_paths,
    ):
        return ShipResult("main-blocked-guard-ack", reasons=["protected path change lacks external ack"])
    return ShipResult("main-merge-allowed")


class PromotionLock:
    """Small cross-process lock primitive for promotion critical sections."""

    def __init__(self, lock_path: str | os.PathLike[str]):
        self.lock_path = Path(lock_path)
        self._fd: int | None = None

    def __enter__(self) -> "PromotionLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise EnforcementNotVerified(f"promotion lock already held: {self.lock_path}") from exc
        os.write(self._fd, str(os.getpid()).encode("ascii"))
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass


def archive_ship_manifest(manifest_dir: str | os.PathLike[str]) -> None:
    """Consume the manifest by renaming it to ``ship_manifest.consumed.json``.

    Called ONLY after a successful ship so the manifest can never be re-consumed once
    its work landed. ``os.replace`` is atomic; a no-op when the source manifest is
    already gone (idempotent). NOTE: the D1 ``main()`` harness never ships, so it does
    not archive — archiving belongs only to successful live staging / main promotion.
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


class SingleInvocationCounterStore:
    """Bounded staging-only counter for one explicit CLI invocation.

    This is not the deferred durable cap store for main promotion. It is intentionally
    process-local and only supports the v1 rule "one live staging merge attempt per
    explicit invocation".
    """

    loop_writable = False

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def get(self, day: str) -> int:
        return self._counts.get(day, 0)

    def increment(self, day: str) -> None:
        self._counts[day] = self._counts.get(day, 0) + 1


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

    def merge(self, pr_id: str, *, match_head_commit: str | None = None) -> None: ...


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

    def ship(
        self,
        *,
        source: str,
        title: str,
        body: str,
        day: str,
        source_sha: str = "",
    ) -> ShipResult:
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
        if source_sha:
            self.ops.merge(pr_id, match_head_commit=source_sha)
        else:
            self.ops.merge(pr_id)
        self.merge_cap.record_merge(day)
        self.failures.record_success()
        return ShipResult("shipped", pr_id=pr_id)


# --------------------------------------------------------------------------- #
# Real git/gh ops (used by the CLI). Runner is injectable so the methods are
# unit-testable without touching the network.
#
# Split: ``protection_verified`` is LIVE read-only. The side-effecting staging
# methods are implemented but are only reachable from the CLI through the explicit
# ``--execute-live-staging`` flag; the default CLI path remains verify-and-refuse.
# --------------------------------------------------------------------------- #
class _RealGitOps:
    """Shells out to git/gh via an injectable runner.

    ``protection_verified`` read-verifies the *actual* GitHub branch protection
    (the ``staging-self-ship-guard`` required check is present + force-push denied);
    there is no env-trust bypass. Mutation methods use only the permission-separated
    ``BIDMATE_SHIP_MERGE_TOKEN`` mapped to ``GH_TOKEN`` and never pass ``--admin`` or
    ``--delete-branch``.
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
                if k not in _GH_AMBIENT_DROP_KEYS and k != _SHIP_MERGE_TOKEN_ENV
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

    def _repo_identity(self) -> tuple[str, str] | None:
        """Return (owner, repo) resolved from this repo root, or None on failure."""
        try:
            view = self._gh(["gh", "repo", "view", "--json", "owner,name"])
        except (OSError, subprocess.SubprocessError):
            return None
        if view.returncode != 0:
            return None
        try:
            repo = json.loads(view.stdout)
            owner = repo["owner"]["login"]
            name = repo["name"]
        except (ValueError, KeyError, TypeError):
            return None
        if not isinstance(owner, str) or not isinstance(name, str) or not owner or not name:
            return None
        return owner, name

    def _mutation_env(self) -> dict[str, str]:
        token = os.environ.get(_SHIP_MERGE_TOKEN_ENV, "").strip()
        if not token:
            raise EnforcementNotVerified(
                f"{_SHIP_MERGE_TOKEN_ENV} is required for live self-ship mutation"
            )
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in _GH_AMBIENT_DROP_KEYS and k != _SHIP_MERGE_TOKEN_ENV
        }
        env["GH_TOKEN"] = token
        return env

    def _pr_view(self, source: str) -> dict | None:
        proc = self._gh(
            ["gh", "pr", "view", source, "--json", "number,baseRefName,headRefOid,state"],
            env=self._mutation_env(),
        )
        if proc.returncode != 0:
            return None
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def protection_verified(self, branch: str) -> bool:
        # Fail CLOSED on ANY environmental failure of the gh subprocess (issue #1697
        # BLOCKING): gh missing (FileNotFoundError/OSError), a hung gh
        # (subprocess.TimeoutExpired), an invalid cwd, or any other SubprocessError
        # must be treated as verification failure → return False, never propagate out
        # of this verifier and crash main(). Nonzero rc + unparseable JSON + incomplete
        # protection state are handled below and likewise fail closed.
        # Derive owner/repo for the gh api path.
        repo = self._repo_identity()
        if repo is None:
            return False
        owner, name = repo
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

    def resolve_review_gate(
        self,
        pr_id: str | int,
        *,
        page_size: int = _REVIEW_THREADS_PAGE_SIZE,
        max_pages: int = _REVIEW_THREADS_MAX_PAGES,
    ) -> ReviewGateResolution:
        """Read-only GraphQL resolver for main review-gate facts.

        The clean path is intentionally narrow: ``reviewDecision == APPROVED`` and
        every non-outdated review thread is resolved. Any gh/API/schema/pagination
        failure returns ``api_error=True`` so callers fail closed.
        """
        try:
            pr_number = int(str(pr_id))
        except (TypeError, ValueError):
            return _review_gate_api_error()
        if pr_number <= 0 or not (1 <= page_size <= 100) or max_pages <= 0:
            return _review_gate_api_error()
        repo = self._repo_identity()
        if repo is None:
            return _review_gate_api_error()
        owner, name = repo
        after: str | None = None
        review_decision: str | None = None
        unresolved_non_outdated = 0
        for page_idx in range(max_pages):
            argv = [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={_REVIEW_GATE_QUERY}",
                "-F",
                f"owner={owner}",
                "-F",
                f"name={name}",
                "-F",
                f"number={pr_number}",
                "-F",
                f"first={page_size}",
            ]
            if after is not None:
                argv.extend(["-F", f"after={after}"])
            try:
                proc = self._gh(argv)
            except (OSError, subprocess.SubprocessError):
                return _review_gate_api_error(
                    review_decision=review_decision,
                    fetched_thread_pages=page_idx,
                )
            if proc.returncode != 0:
                return _review_gate_api_error(
                    review_decision=review_decision,
                    fetched_thread_pages=page_idx,
                )
            try:
                payload = json.loads(proc.stdout)
            except ValueError:
                return _review_gate_api_error(
                    review_decision=review_decision,
                    fetched_thread_pages=page_idx,
                )
            if not isinstance(payload, dict) or payload.get("errors"):
                return _review_gate_api_error(
                    review_decision=review_decision,
                    fetched_thread_pages=page_idx,
                )
            data = payload.get("data")
            if not isinstance(data, dict):
                return _review_gate_api_error(fetched_thread_pages=page_idx)
            repository = data.get("repository")
            if not isinstance(repository, dict):
                return _review_gate_api_error(fetched_thread_pages=page_idx)
            pull_request = repository.get("pullRequest")
            if not isinstance(pull_request, dict):
                return _review_gate_api_error(fetched_thread_pages=page_idx)
            raw_decision = pull_request.get("reviewDecision")
            if raw_decision is not None and not isinstance(raw_decision, str):
                return _review_gate_api_error(fetched_thread_pages=page_idx)
            review_decision = raw_decision
            threads = pull_request.get("reviewThreads")
            if not isinstance(threads, dict):
                return _review_gate_api_error(
                    review_decision=review_decision,
                    fetched_thread_pages=page_idx,
                )
            nodes = threads.get("nodes")
            page_info = threads.get("pageInfo")
            if not isinstance(nodes, list) or not isinstance(page_info, dict):
                return _review_gate_api_error(
                    review_decision=review_decision,
                    fetched_thread_pages=page_idx,
                )
            for node in nodes:
                if not isinstance(node, dict):
                    return _review_gate_api_error(
                        review_decision=review_decision,
                        fetched_thread_pages=page_idx,
                    )
                is_resolved = node.get("isResolved")
                is_outdated = node.get("isOutdated")
                if not isinstance(is_resolved, bool) or not isinstance(is_outdated, bool):
                    return _review_gate_api_error(
                        review_decision=review_decision,
                        fetched_thread_pages=page_idx,
                    )
                if not is_resolved and not is_outdated:
                    unresolved_non_outdated += 1
            has_next = page_info.get("hasNextPage")
            end_cursor = page_info.get("endCursor")
            fetched_pages = page_idx + 1
            if not isinstance(has_next, bool):
                return _review_gate_api_error(
                    review_decision=review_decision,
                    fetched_thread_pages=fetched_pages,
                )
            if not has_next:
                return ReviewGateResolution(
                    review_decision=review_decision,
                    unresolved_non_outdated_threads=unresolved_non_outdated,
                    fetched_thread_pages=fetched_pages,
                    api_error=False,
                )
            if not isinstance(end_cursor, str) or not end_cursor:
                return _review_gate_api_error(
                    review_decision=review_decision,
                    fetched_thread_pages=fetched_pages,
                )
            after = end_cursor
        return _review_gate_api_error(
            review_decision=review_decision,
            fetched_thread_pages=max_pages,
        )

    def open_pr(self, *, source: str, base: str, title: str, body: str) -> str:
        existing = self._pr_view(source)
        if existing is not None:
            if existing.get("baseRefName") != base:
                raise EnforcementNotVerified(
                    f"existing PR for {source!r} targets {existing.get('baseRefName')!r}, "
                    f"not expected base {base!r}"
                )
            if existing.get("state") != "OPEN":
                raise EnforcementNotVerified(f"existing PR for {source!r} is not open")
            return str(existing["number"])
        proc = self._gh(
            [
                "gh",
                "pr",
                "create",
                "--head",
                source,
                "--base",
                base,
                "--title",
                title,
                "--body",
                body,
                "--no-maintainer-edit",
            ],
            env=self._mutation_env(),
        )
        if proc.returncode != 0:
            raise EnforcementNotVerified("gh pr create failed")
        created = self._pr_view(source)
        if created is None or created.get("baseRefName") != base or created.get("state") != "OPEN":
            raise EnforcementNotVerified("created PR could not be re-read/bound to expected base")
        return str(created["number"])

    def required_checks_all_success(self, pr_id: str) -> bool:
        try:
            proc = self._gh(
                [
                    "gh",
                    "pr",
                    "checks",
                    str(pr_id),
                    "--required",
                    "--json",
                    "name,state,bucket",
                ],
                env=self._mutation_env(),
            )
        except (OSError, subprocess.SubprocessError, EnforcementNotVerified):
            return False
        if proc.returncode != 0:
            return False
        try:
            checks = json.loads(proc.stdout)
        except ValueError:
            return False
        if not isinstance(checks, list) or not checks:
            return False
        return all(isinstance(item, dict) and item.get("bucket") == "pass" for item in checks)

    def merge(self, pr_id: str, *, match_head_commit: str | None = None) -> None:
        if not match_head_commit or not _SHA_RE.match(match_head_commit):
            raise EnforcementNotVerified("merge requires a 40-char source_sha for --match-head-commit")
        proc = self._gh(
            [
                "gh",
                "pr",
                "merge",
                str(pr_id),
                "--squash",
                "--match-head-commit",
                match_head_commit,
            ],
            env=self._mutation_env(),
        )
        if proc.returncode != 0:
            raise EnforcementNotVerified("gh pr merge failed")


def main(argv: list[str] | None = None) -> int:
    """Verify-first harness; live staging requires an explicit flag.

    Reads the ship manifest (loop → lane hand-off), runs the cheap local guards, and
    LIVE-verifies the external GitHub branch protection (read-only). By default it
    returns 2 (blocked-on-user) after verification. Only ``--execute-live-staging``
    may create/check/merge a staging PR, and even then it requires ``source_sha`` so
    merge uses ``--match-head-commit``.
    """
    parser = argparse.ArgumentParser(
        description="staging self-ship verify-first harness (ADR 0088/0090); live merge requires --execute-live-staging"
    )
    parser.add_argument("--source", default="", help="source branch to ship")
    parser.add_argument("--title", default="")
    parser.add_argument("--body", default="")
    parser.add_argument("--day", default="")
    parser.add_argument("--source-sha", default="", help="40-char source SHA for --match-head-commit")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--state-dir", default=".omc/state")
    parser.add_argument(
        "--manifest-dir",
        default="",
        help="dir holding ship_manifest.json (defaults to --state-dir)",
    )
    parser.add_argument(
        "--execute-live-staging",
        action="store_true",
        help="explicitly create/check/merge a staging PR; default remains verify-and-refuse",
    )
    args = parser.parse_args(argv)

    # 1) Read the manifest (loop -> lane hand-off). The read is idempotent — D1 never
    #    ships, so it never archives the manifest (consumption belongs to successful
    #    live staging / main promotion).
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
        source_sha = manifest["source_sha"]
        title = manifest["title"]
        body = manifest["body"]
        day = manifest["day"]
        target = manifest["target"]
    else:
        source = source_sha = title = body = day = ""
        target = _TARGET_STAGING
    # CLI flags override manifest fields when non-empty.
    source = args.source or source
    source_sha = args.source_sha or source_sha
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
    #     to hand to explicit live staging / deferred main promotion.
    if manifest is None and not args.source:
        sys.stderr.write("[staging-self-ship] blocked-on-user: no ship manifest\n")
        return 2

    if args.execute_live_staging:
        if target != _TARGET_STAGING:
            sys.stderr.write(
                f"[staging-self-ship] blocked-on-user: live CLI only supports target={_TARGET_STAGING!r}\n"
            )
            return 2
        if not source_sha or not _SHA_RE.match(source_sha):
            sys.stderr.write(
                "[staging-self-ship] blocked-on-user: --execute-live-staging requires "
                "manifest source_sha or --source-sha for --match-head-commit\n"
            )
            return 2
        if not enforcement_verified:
            sys.stderr.write(
                "[staging-self-ship] blocked-on-user: external enforcement must verify before live staging\n"
            )
            return 2
        lane = StagingShipLane(
            ops=ops,
            repo_root=args.repo_root,
            state_dir=args.state_dir,
            merge_cap=DailyMergeCapCounter(store=SingleInvocationCounterStore(), cap=1),
        )
        try:
            result = lane.ship(
                source=source,
                title=title,
                body=body,
                day=day,
                source_sha=source_sha,
            )
        except (ShipArmConflict, StagingBoundaryViolation, ForcePushForbidden, EnforcementNotVerified) as exc:
            sys.stderr.write(f"[staging-self-ship] blocked-on-user: live staging failed: {exc}\n")
            return 2
        if result.decision == "shipped":
            archive_ship_manifest(manifest_dir)
            sys.stderr.write(
                f"[staging-self-ship] staging-merged: pr={result.pr_id} source_sha={source_sha}\n"
            )
            return 0
        sys.stderr.write(
            f"[staging-self-ship] {result.decision}: {'; '.join(result.reasons)}\n"
        )
        return 2

    # 4) Default path refuses to merge, but the message must be HONEST about whether
    #    protection was actually verified (codex Fix 4): only claim "verified
    #    read-only" when the live check returned True; otherwise focus on the
    #    unverified/unreachable enforcement. Live mutation requires the explicit
    #    --execute-live-staging flag above.
    if enforcement_verified:
        sys.stderr.write(
            "[staging-self-ship] blocked-on-user: enforcement model verified read-only, but "
            "default mode does not auto-merge. Re-run with --execute-live-staging only "
            "when the manifest source_sha is the exact commit to merge.\n"
        )
    else:
        sys.stderr.write(
            "[staging-self-ship] blocked-on-user: external enforcement NOT verified / not "
            "reachable (required staging-self-ship-guard check, explicit force-push-deny, and "
            "enforce_admins not confirmed). Default mode does not auto-merge.\n"
        )
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
