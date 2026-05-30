#!/usr/bin/env python3
"""Run local Codex adversarial review for staged load-bearing changes.

This is the local replacement for the old PR-time GitHub Actions review:
pre-commit should catch contract problems before the branch is pushed, without
creating a fresh PR comment/check-run loop on every synchronize event.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import render_codex_review
from scripts._governance import is_load_bearing
from scripts.agent_loop_codex_turn import resolve_companion

DEFAULT_ATTEMPTS = 2
DEFAULT_TIMEOUT_SEC = 900
DEFAULT_OUT_SUBDIR = "codex-adversarial-precommit"

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
        f"Attempt {attempt}/{attempts}. Load-bearing staged paths: {hit_list}.\n\n"
        "Staged files:\n"
        f"{changed}"
    )


def _default_runner(cmd: Sequence[str], timeout_sec: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout_sec)


def _parse_payload(stdout: str) -> dict[str, object] | None:
    try:
        payload = json.loads(stdout or "")
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _payload_verdict(payload: dict[str, object] | None) -> str:
    if payload is None or payload.get("parseError"):
        return "error"
    result = payload.get("result")
    if not isinstance(result, dict):
        return "error"
    verdict = result.get("verdict")
    return str(verdict) if verdict else "error"


def _stderr_tail(stderr: str, *, lines: int = 30) -> str:
    return "\n".join((stderr or "").splitlines()[-lines:])


def _write_attempt_artifacts(
    *,
    out_dir: Path,
    attempt: int,
    payload: dict[str, object] | None,
    stdout: str,
    stderr: str,
    rc: int,
    changed_files: set[str],
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_json = out_dir / f"attempt-{attempt}.json"
    err_log = out_dir / f"attempt-{attempt}.err.log"
    comment = out_dir / f"attempt-{attempt}.md"
    raw_json.write_text(stdout or "{}", encoding="utf-8")
    err_log.write_text(stderr or "", encoding="utf-8")
    rendered = render_codex_review.render_markdown(
        payload=payload,
        rc=rc,
        repo=None,
        sha=None,
        changed=changed_files,
        stderr_tail=_stderr_tail(stderr),
    )
    comment.write_text(rendered, encoding="utf-8")
    return comment


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
    runner: Runner = _default_runner,
) -> int:
    if attempts < 1:
        raise ValueError("--attempts must be >= 1")
    if timeout_sec < 1:
        raise ValueError("--timeout-sec must be >= 1")
    changed_set = set(changed_files)
    real_review_ran = False
    for attempt in range(1, attempts + 1):
        focus = build_focus(hits=hits, changed_files=changed_files, attempt=attempt, attempts=attempts)
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
                stderr
                + f"\nCodex adversarial pre-commit review timed out after {timeout_sec}s."
            ).strip()
            proc = subprocess.CompletedProcess(args=cmd, returncode=124, stdout=stdout, stderr=stderr)
        payload = _parse_payload(proc.stdout)
        comment = _write_attempt_artifacts(
            out_dir=out_dir,
            attempt=attempt,
            payload=payload,
            stdout=proc.stdout,
            stderr=proc.stderr,
            rc=proc.returncode,
            changed_files=changed_set,
        )
        verdict = _payload_verdict(payload)
        # ADR 0089 (amends ADR 0066): distinguish an INFRA failure (codex could
        # not produce a verdict — auth/refresh-token race, network, timeout,
        # missing companion, unparseable output) from a real adversarial VERDICT.
        # Infra failures must NOT hard-block the commit (that fail-closed coupling
        # forced --no-verify on every load-bearing commit whenever codex auth
        # lapsed under concurrent multi-worktree use). They WARN and defer the
        # real adversarial review to CI / pre-push. Only a genuine non-approve
        # verdict blocks. ``_payload_verdict`` already maps parseError / missing
        # result to "error", so rc!=0 (companion/codex failed) OR verdict=="error"
        # (no usable verdict) covers every infra case.
        infra_failure = proc.returncode != 0 or verdict == "error"
        if infra_failure:
            print(
                f"WARN: Codex adversarial pre-commit review could not run on attempt "
                f"{attempt}/{attempts} (rc={proc.returncode}); non-blocking — commit "
                f"allowed, adversarial review deferred to CI/pre-push. See {comment}.",
                file=sys.stderr,
            )
            continue
        real_review_ran = True
        if verdict != "approve":
            print(
                f"Codex adversarial pre-commit review returned `{verdict}` on attempt "
                f"{attempt}/{attempts}. See {comment}.",
                file=sys.stderr,
            )
            return 1
        print(
            f"Codex adversarial pre-commit review attempt {attempt}/{attempts}: approve",
            file=sys.stderr,
        )
    if not real_review_ran:
        print(
            f"WARN: Codex adversarial pre-commit review did not complete (all {attempts} "
            f"attempt(s) infra-failed); commit allowed, adversarial review deferred to "
            f"CI/pre-push (ADR 0089).",
            file=sys.stderr,
        )
        return 0
    print("Codex adversarial pre-commit review passed.", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, default=None)
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
        timeout_sec = args.timeout_sec if args.timeout_sec is not None else _env_timeout_sec()
    except ValueError as exc:
        print(f"codex-adversarial-precommit: {exc}", file=sys.stderr)
        return 1

    companion = resolve_companion(args.companion)
    if companion is None:
        # ADR 0089: a missing companion is an INFRA condition, not a review
        # finding — warn and allow the commit (adversarial review deferred to
        # CI/pre-push) instead of hard-blocking every load-bearing commit on
        # machines without the Codex plugin installed.
        print(
            "WARN: codex-adversarial-precommit: codex companion not found; "
            "non-blocking — commit allowed, adversarial review deferred to "
            "CI/pre-push. Install/refresh the Claude Codex plugin or set "
            "CODEX_COMPANION to re-enable the local review.",
            file=sys.stderr,
        )
        return 0

    return run_precommit_review(
        attempts=attempts,
        base=args.base,
        scope=args.scope,
        companion=companion,
        changed_files=files,
        hits=hits,
        out_dir=args.out_dir or default_out_dir(),
        timeout_sec=timeout_sec,
    )


if __name__ == "__main__":
    raise SystemExit(main())
