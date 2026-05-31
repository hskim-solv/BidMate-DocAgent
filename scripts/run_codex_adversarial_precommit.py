#!/usr/bin/env python3
"""Run local Codex adversarial review for staged load-bearing changes.

This is the local replacement for the old PR-time GitHub Actions review:
pre-commit should catch contract problems before the branch is pushed, without
creating a fresh PR comment/check-run loop on every synchronize event.

The adversarial reviewer is stochastic: a single pass only catches a random
subset of the real findings, so blocking on "any strong finding exists" lets a
fresh one-off nitpick re-block every recommit (commit storm). Instead we run N
passes in parallel, union/dedup their findings into clusters, and only block on
clusters that reproduced across `MIN_FREQUENCY` distinct passes at
critical/high severity. One-off findings are shown for reference but never
block — this structurally prevents the recommit storm.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import render_codex_review
from scripts._governance import is_load_bearing
from scripts.agent_loop_codex_turn import resolve_companion

DEFAULT_ATTEMPTS = 8
DEFAULT_MIN_FREQUENCY = 2
DEFAULT_TIMEOUT_SEC = 900
DEFAULT_OUT_SUBDIR = "codex-adversarial-precommit"

# gap (in lines) within which two findings on the same file are treated as the
# same cluster — overlap test is `not (le < lo - GAP or ls > hi + GAP)`.
CLUSTER_GAP = 8
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
BLOCKING_SEVERITIES = {"critical", "high"}

Runner = Callable[[Sequence[str], int], subprocess.CompletedProcess[str]]


def _run_git(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def staged_files() -> list[str]:
    proc = _run_git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "git diff --cached failed").strip())
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def default_out_dir() -> Path:
    proc = _run_git(["rev-parse", "--git-dir"])
    if proc.returncode != 0:
        return Path(".git") / DEFAULT_OUT_SUBDIR
    git_dir = Path(proc.stdout.strip() or ".git")
    return git_dir / DEFAULT_OUT_SUBDIR


def load_bearing_hits(paths: Sequence[str]) -> list[str]:
    return [path for path in paths if is_load_bearing(path)]


def _env_attempts() -> int:
    raw = os.environ.get("BIDMATE_CODEX_ADVERSARIAL_ATTEMPTS")
    if not raw:
        return DEFAULT_ATTEMPTS
    try:
        return int(raw)
    except ValueError:
        raise ValueError("BIDMATE_CODEX_ADVERSARIAL_ATTEMPTS must be an integer") from None


def _env_min_frequency() -> int:
    raw = os.environ.get("BIDMATE_CODEX_ADVERSARIAL_MIN_FREQUENCY")
    if not raw:
        return DEFAULT_MIN_FREQUENCY
    try:
        return int(raw)
    except ValueError:
        raise ValueError("BIDMATE_CODEX_ADVERSARIAL_MIN_FREQUENCY must be an integer") from None


def _env_timeout_sec() -> int:
    raw = os.environ.get("BIDMATE_CODEX_ADVERSARIAL_TIMEOUT_SEC")
    if not raw:
        return DEFAULT_TIMEOUT_SEC
    try:
        return int(raw)
    except ValueError:
        raise ValueError("BIDMATE_CODEX_ADVERSARIAL_TIMEOUT_SEC must be an integer") from None


def build_focus(*, hits: Sequence[str], changed_files: Sequence[str], attempt: int, attempts: int) -> str:
    hit_list = ", ".join(hits)
    changed = "\n".join(f"- {path}" for path in changed_files)
    return (
        "Pre-commit adversarial review. Review only the staged diff for this commit. "
        "Use `git diff --cached` and `git diff --cached --name-only`; do not review "
        "unstaged worktree changes as required fixes for this commit. "
        f"Pass {attempt}/{attempts}. Load-bearing staged paths: {hit_list}.\n\n"
        "Staged files:\n"
        f"{changed}"
    )


# Git environment variables that a pre-commit hook exports. If these leak into
# the Codex app-server subprocess, Codex's own git operations (plugin-loader,
# broker reuse) write into THIS worktree's index — recording plugin-marketplace
# paths whose blobs never exist in this object store, which corrupts the index
# (`fatal: unable to read <blob>` / `invalid sha1 pointer in cache-tree`). The
# 8-pass union amplifies this 8x. Stripping the git env makes Codex resolve git
# from `--cwd` only, so it cannot mutate the hook's index. (Codex diagnosis,
# issue #1691 / ADR 0066.)
_GIT_ENV_PREFIX = "GIT_"
_DROP_ENV_EXACT = frozenset({"CODEX_COMPANION_APP_SERVER_ENDPOINT"})


def sanitized_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Return os.environ minus inherited git-hook vars and the broker endpoint."""
    source = os.environ if base is None else base
    return {
        k: v
        for k, v in source.items()
        if not k.startswith(_GIT_ENV_PREFIX) and k not in _DROP_ENV_EXACT
    }


def _default_runner(cmd: Sequence[str], timeout_sec: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_sec,
        env=sanitized_env(),
    )


def _parse_payload(stdout: str) -> dict[str, object] | None:
    try:
        payload = json.loads(stdout or "")
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _payload_findings(payload: dict[str, object] | None) -> list[dict[str, object]]:
    """Extract `result.findings` (verdict is ignored — union collects all findings)."""
    if payload is None or payload.get("parseError"):
        return []
    result = payload.get("result")
    if not isinstance(result, dict):
        return []
    findings = result.get("findings")
    if not isinstance(findings, list):
        return []
    return [f for f in findings if isinstance(f, dict)]


def severity_rank(severity: str | None) -> int:
    """Lower rank = more severe (critical=0 … low=3, unknown last)."""
    return SEVERITY_RANK.get(str(severity or "").lower(), 99)


def _stderr_tail(stderr: str, *, lines: int = 30) -> str:
    return "\n".join((stderr or "").splitlines()[-lines:])


@dataclass
class PassResult:
    """Outcome of one adversarial-review pass."""

    index: int
    payload: dict[str, object] | None
    stdout: str
    stderr: str
    rc: int

    @property
    def is_error(self) -> bool:
        return self.rc != 0 or self.payload is None or bool(self.payload.get("parseError"))

    @property
    def findings(self) -> list[dict[str, object]]:
        if self.is_error:
            return []
        return _payload_findings(self.payload)


@dataclass
class Cluster:
    """A union/dedup cluster of findings that overlap on the same file+line range."""

    file: str
    line_lo: int
    line_hi: int
    members: list[dict[str, object]] = field(default_factory=list)
    pass_indices: set[int] = field(default_factory=set)

    @property
    def frequency(self) -> int:
        """Distinct passes that reported this cluster (same pass duplicates count once)."""
        return len(self.pass_indices)

    @property
    def max_severity(self) -> str:
        best = "low"
        best_rank = 99
        for member in self.members:
            rank = severity_rank(member.get("severity"))
            if rank < best_rank:
                best_rank = rank
                best = str(member.get("severity") or "low").lower()
        return best

    @property
    def representative(self) -> dict[str, object]:
        """Highest-confidence member (ties broken by first-seen order)."""
        def conf(member: dict[str, object]) -> float:
            value = member.get("confidence")
            return float(value) if isinstance(value, (int, float)) else -1.0

        best = self.members[0]
        best_conf = conf(best)
        for member in self.members[1:]:
            if conf(member) > best_conf:
                best = member
                best_conf = conf(member)
        return best


def _finding_lines(finding: dict[str, object]) -> tuple[int, int]:
    start = finding.get("line_start")
    end = finding.get("line_end")
    lo = int(start) if isinstance(start, (int, float)) else 0
    hi = int(end) if isinstance(end, (int, float)) else 0
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi


def cluster_findings(
    findings: Sequence[tuple[int, dict[str, object]]],
    *,
    gap: int = CLUSTER_GAP,
) -> list[Cluster]:
    """Union/dedup findings into clusters by file + overlapping line range.

    Input is a sequence of `(pass_index, finding)` pairs. Two findings on the
    same file merge when their line ranges overlap within `gap` lines:
    `not (le < c.line_lo - gap or ls > c.line_hi + gap)`. line_start/line_end of
    None are treated as 0. Frequency counts *distinct* passes per cluster.
    """
    clusters: list[Cluster] = []
    for pass_index, finding in findings:
        file = str(finding.get("file") or "")
        lo, hi = _finding_lines(finding)
        target: Cluster | None = None
        for cluster in clusters:
            if cluster.file != file:
                continue
            if not (hi < cluster.line_lo - gap or lo > cluster.line_hi + gap):
                target = cluster
                break
        if target is None:
            target = Cluster(file=file, line_lo=lo, line_hi=hi)
            clusters.append(target)
        else:
            target.line_lo = min(target.line_lo, lo)
            target.line_hi = max(target.line_hi, hi)
        target.members.append(finding)
        target.pass_indices.add(pass_index)
    return clusters


def is_blocking(cluster: Cluster, *, min_frequency: int) -> bool:
    return cluster.frequency >= min_frequency and cluster.max_severity in BLOCKING_SEVERITIES


def _cluster_to_dict(cluster: Cluster, *, attempts: int) -> dict[str, object]:
    rep = cluster.representative
    return {
        "file": cluster.file,
        "line_lo": cluster.line_lo,
        "line_hi": cluster.line_hi,
        "frequency": cluster.frequency,
        "total_passes": attempts,
        "max_severity": cluster.max_severity,
        "title": str(rep.get("title") or "(untitled)"),
        "recommendation": str(rep.get("recommendation") or ""),
        "members": cluster.members,
        "pass_indices": sorted(cluster.pass_indices),
    }


def _render_cluster_line(cluster: Cluster, *, attempts: int) -> list[str]:
    rep = cluster.representative
    title = str(rep.get("title") or "(untitled)")
    rec = str(rep.get("recommendation") or "").strip()
    lines = [
        f"- [{cluster.max_severity}] `{cluster.file}:{cluster.line_lo}-{cluster.line_hi}` "
        f"(freq {cluster.frequency}/{attempts}) — {title}",
    ]
    if rec:
        lines.append(f"  - Recommendation: {rec}")
    return lines


def render_union_markdown(
    *,
    clusters: Sequence[Cluster],
    attempts: int,
    error_passes: int,
    min_frequency: int,
) -> str:
    blocking = sorted(
        (c for c in clusters if is_blocking(c, min_frequency=min_frequency)),
        key=lambda c: (severity_rank(c.max_severity), -c.frequency, c.file),
    )
    informational = sorted(
        (c for c in clusters if not is_blocking(c, min_frequency=min_frequency)),
        key=lambda c: (severity_rank(c.max_severity), -c.frequency, c.file),
    )
    lines = [
        "## Codex adversarial pre-commit review — union of N parallel passes",
        "",
        f"Passes: {attempts} (errored: {error_passes}). "
        f"Block gate: frequency ≥ {min_frequency} and severity in {{critical, high}}.",
        "",
        f"### Blocking findings ({len(blocking)})",
        "",
    ]
    if blocking:
        for cluster in blocking:
            lines.extend(_render_cluster_line(cluster, attempts=attempts))
    else:
        lines.append("_None — no critical/high finding reproduced across enough passes._")
    lines.append("")
    lines.append(f"### Informational findings ({len(informational)})")
    lines.append("")
    lines.append("_Non-blocking: one-off (freq below threshold) or medium/low severity._")
    lines.append("")
    if informational:
        for cluster in informational:
            lines.extend(_render_cluster_line(cluster, attempts=attempts))
    else:
        lines.append("_None._")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_pass_artifacts(*, out_dir: Path, result: PassResult, changed_files: set[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_json = out_dir / f"pass-{result.index}.json"
    err_log = out_dir / f"pass-{result.index}.err"
    raw_json.write_text(result.stdout or "{}", encoding="utf-8")
    err_log.write_text(result.stderr or "", encoding="utf-8")
    comment = out_dir / f"pass-{result.index}.md"
    rendered = render_codex_review.render_markdown(
        payload=result.payload,
        rc=result.rc,
        repo=None,
        sha=None,
        changed=changed_files,
        stderr_tail=_stderr_tail(result.stderr),
    )
    comment.write_text(rendered, encoding="utf-8")


def _run_pass(
    *,
    index: int,
    attempts: int,
    base: str,
    scope: str,
    companion: Path,
    changed_files: Sequence[str],
    hits: Sequence[str],
    timeout_sec: int,
    runner: Runner,
) -> PassResult:
    focus = build_focus(hits=hits, changed_files=changed_files, attempt=index, attempts=attempts)
    cmd = [
        "node",
        str(companion),
        "adversarial-review",
        "--json",
        "--base",
        base,
        "--scope",
        scope,
        focus,
    ]
    try:
        proc = runner(cmd, timeout_sec)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        stderr = (
            stderr + f"\nCodex adversarial pre-commit review timed out after {timeout_sec}s."
        ).strip()
        proc = subprocess.CompletedProcess(args=cmd, returncode=124, stdout=stdout, stderr=stderr)
    payload = _parse_payload(proc.stdout)
    return PassResult(
        index=index,
        payload=payload,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        rc=proc.returncode,
    )


def run_precommit_review(
    *,
    attempts: int,
    base: str,
    scope: str,
    companion: Path,
    changed_files: Sequence[str],
    hits: Sequence[str],
    out_dir: Path,
    timeout_sec: int,
    min_frequency: int = DEFAULT_MIN_FREQUENCY,
    runner: Runner = _default_runner,
) -> int:
    """Run N adversarial passes in parallel, union their findings, and gate on frequency.

    Returns 0 (commit allowed) unless a critical/high finding reproduced across
    at least `min_frequency` distinct passes. All-error passes return 1.
    """
    if attempts < 1:
        raise ValueError("--attempts must be >= 1")
    if min_frequency < 1:
        raise ValueError("--min-frequency must be >= 1")
    if min_frequency > attempts:
        raise ValueError(
            f"--min-frequency ({min_frequency}) must be <= --attempts ({attempts}); "
            "otherwise no finding can reach the threshold and the gate is silently disabled"
        )
    if timeout_sec < 1:
        raise ValueError("--timeout-sec must be >= 1")
    changed_set = set(changed_files)

    with ThreadPoolExecutor(max_workers=attempts) as executor:
        futures = [
            executor.submit(
                _run_pass,
                index=index,
                attempts=attempts,
                base=base,
                scope=scope,
                companion=companion,
                changed_files=changed_files,
                hits=hits,
                timeout_sec=timeout_sec,
                runner=runner,
            )
            for index in range(1, attempts + 1)
        ]
        results = sorted((f.result() for f in futures), key=lambda r: r.index)

    for result in results:
        _write_pass_artifacts(out_dir=out_dir, result=result, changed_files=changed_set)

    error_passes = sum(1 for r in results if r.is_error)
    successful_passes = attempts - error_passes
    # Fail-closed: confirming a reproduced finding needs >= min_frequency
    # successful passes. If too many passes errored (companion outage / timeout),
    # the gate cannot establish reproduction and must block rather than silently
    # pass — otherwise a partial outage disables the gate.
    if successful_passes < min_frequency:
        print(
            f"Codex adversarial pre-commit review: only {successful_passes} of "
            f"{attempts} pass(es) succeeded (< min_frequency {min_frequency}); cannot "
            f"confirm a reproduced finding. Blocking fail-closed (companion environment "
            f"problem, not a code finding). See {out_dir}.",
            file=sys.stderr,
        )
        return 1

    collected: list[tuple[int, dict[str, object]]] = []
    for result in results:
        for finding in result.findings:
            collected.append((result.index, finding))

    clusters = cluster_findings(collected)
    blocking = [c for c in clusters if is_blocking(c, min_frequency=min_frequency)]

    union_md = render_union_markdown(
        clusters=clusters,
        attempts=attempts,
        error_passes=error_passes,
        min_frequency=min_frequency,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "union.md").write_text(union_md, encoding="utf-8")
    (out_dir / "union.json").write_text(
        json.dumps(
            {
                "attempts": attempts,
                "error_passes": error_passes,
                "min_frequency": min_frequency,
                "clusters": [_cluster_to_dict(c, attempts=attempts) for c in clusters],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(union_md, file=sys.stderr)
    if blocking:
        print(
            f"Codex adversarial pre-commit review BLOCKED: {len(blocking)} cluster(s) "
            f"reproduced across ≥{min_frequency} passes at critical/high severity. "
            f"See {out_dir / 'union.md'}.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Codex adversarial pre-commit review passed "
        f"({error_passes}/{attempts} passes errored, no blocking cluster). "
        f"See {out_dir / 'union.md'}.",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, default=None, help="Number of parallel union passes.")
    parser.add_argument(
        "--min-frequency",
        type=int,
        default=None,
        help="Min distinct passes a critical/high cluster must reproduce in to block.",
    )
    parser.add_argument("--timeout-sec", type=int, default=None)
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--scope", default="branch")
    parser.add_argument("--companion", default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        files = staged_files()
    except RuntimeError as exc:
        print(f"codex-adversarial-precommit: {exc}", file=sys.stderr)
        return 1
    if not files:
        return 0
    hits = load_bearing_hits(files)
    if not hits:
        return 0

    try:
        attempts = args.attempts if args.attempts is not None else _env_attempts()
        min_frequency = (
            args.min_frequency if args.min_frequency is not None else _env_min_frequency()
        )
        timeout_sec = args.timeout_sec if args.timeout_sec is not None else _env_timeout_sec()
    except ValueError as exc:
        print(f"codex-adversarial-precommit: {exc}", file=sys.stderr)
        return 1

    companion = resolve_companion(args.companion)
    if companion is None:
        print(
            "codex-adversarial-precommit: codex companion not found. "
            "Install/refresh the Claude Codex plugin, set CODEX_COMPANION, "
            "or use git commit --no-verify for an intentional emergency bypass.",
            file=sys.stderr,
        )
        return 1

    return run_precommit_review(
        attempts=attempts,
        base=args.base,
        scope=args.scope,
        companion=companion,
        changed_files=files,
        hits=hits,
        out_dir=args.out_dir or default_out_dir(),
        timeout_sec=timeout_sec,
        min_frequency=min_frequency,
    )


if __name__ == "__main__":
    raise SystemExit(main())
