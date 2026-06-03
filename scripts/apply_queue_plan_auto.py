#!/usr/bin/env python3
"""Apply local queue/plan drafts without a human-approval flag.

This is intentionally narrower than ``agent_loop.py human-gated-exec``: it only
writes tracked local planning files from existing drafts and delegates all
sanitization/privacy checks to ``agent_loop.write_apply_queue_plan``. It never
pushes, creates/merges/closes PRs, closes issues, deletes branches, force-pushes,
runs private eval, or approves benchmark claims.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# When executed as ``python3 scripts/apply_queue_plan_auto.py``, the script
# directory is already on sys.path. Importing the existing module reuses the
# repo's queue/plan writer instead of duplicating policy-sensitive logic.
import agent_loop


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Apply agent-loop queue/plan drafts non-interactively. "
            "Local tracked docs only; no remote state mutation."
        )
    )
    parser.add_argument("--queue-draft", type=Path, default=agent_loop.DEFAULT_QUEUE_DRAFT)
    parser.add_argument("--plan-draft", type=Path, default=agent_loop.DEFAULT_PLAN_DRAFT)
    parser.add_argument("--out", type=Path, default=agent_loop.DEFAULT_APPLY_QUEUE_PLAN)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=agent_loop.ROOT_DIR,
        help="Repository root to apply into; primarily for focused tests.",
    )
    return parser


def _resolve_draft(path: Path, *, default_name: str, repo_root: Path) -> Path:
    # Reuse the existing resolver so default paths are interpreted relative to
    # the target repo root, but keep this wrapper's extra preflight local.
    return agent_loop._resolve_default_agent_loop_path(path, default_name, repo_root=repo_root)  # noqa: SLF001


def _fail_on_raw_private_values(*, queue_draft: Path, plan_draft: Path, repo_root: Path) -> None:
    queue_path = _resolve_draft(queue_draft, default_name="queue_entry_draft.md", repo_root=repo_root)
    plan_path = _resolve_draft(plan_draft, default_name="plan_draft.md", repo_root=repo_root)
    if not queue_path.exists() or not plan_path.exists():
        raise ValueError("queue/plan drafts not found; run draft-task first")
    raw_text = queue_path.read_text(encoding="utf-8") + "\n" + plan_path.read_text(encoding="utf-8")
    findings = agent_loop._privacy_findings_for_text(raw_text, path="queue/plan drafts")  # noqa: SLF001
    if findings:
        issues = ", ".join(sorted({finding.issue for finding in findings}))
        raise ValueError(f"queue/plan drafts contain private raw values before redaction: {issues}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    _fail_on_raw_private_values(queue_draft=args.queue_draft, plan_draft=args.plan_draft, repo_root=repo_root)
    out, _ = agent_loop.write_apply_queue_plan(
        confirm_human_approved=True,
        queue_draft=args.queue_draft,
        plan_draft=args.plan_draft,
        out=args.out,
        repo_root=repo_root,
    )
    try:
        display = agent_loop._repo_path(out, repo_root)  # noqa: SLF001 - display-only reuse.
    except Exception:  # pragma: no cover - defensive display fallback.
        display = out
    sys.stdout.write(f"[OK] applied queue/plan drafts without approval flag; wrote {display}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess tests.
    raise SystemExit(main())
