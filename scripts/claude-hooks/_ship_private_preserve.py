#!/usr/bin/env python3
"""Preserve untracked private-path files skipped by auto-ship staging.

``stop-ship.sh`` deliberately refuses to stage paths such as ``reports/real*/``
and private data directories. This helper prevents generated aggregate files
from being stranded in short-lived worktrees by moving untracked skipped files
to the operator's canonical local checkout.

Tracked modifications are never moved: moving them would delete a tracked file
from the active worktree. Those stay in place for the operator to handle.
"""
from __future__ import annotations

import argparse
import filecmp
import os
from pathlib import Path
import shutil
import sys
from typing import Iterable


def _safe_relative_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe relative path: {raw!r}")
    return path


def _same_file_content(source: Path, dest: Path) -> bool:
    return source.is_file() and dest.is_file() and filecmp.cmp(source, dest, shallow=False)


def _conflict_dest(dest: Path) -> Path:
    suffix = f".ship-preserved-{os.getpid()}"
    candidate = dest.with_name(dest.name + suffix)
    idx = 1
    while candidate.exists():
        candidate = dest.with_name(f"{dest.name}{suffix}-{idx}")
        idx += 1
    return candidate


def _preserve_root_from_env() -> Path | None:
    configured = (
        os.environ.get("SHIP_PRIVATE_PRESERVE_ROOT")
        or os.environ.get("BIDMATE_PRIVATE_PRESERVE_ROOT")
    )
    return Path(configured) if configured else None


def preserve_one(
    *,
    repo_root: Path,
    preserve_root: Path,
    status: str,
    relpath: str,
    dry_run: bool = False,
) -> str:
    rel = _safe_relative_path(relpath)
    if status != "??":
        return f"skip tracked-status {status} {rel}"

    source = repo_root / rel
    if not source.exists():
        return f"skip missing {rel}"

    resolved_repo = repo_root.resolve()
    resolved_preserve = preserve_root.resolve()
    if resolved_repo == resolved_preserve:
        return f"skip same-root {rel}"

    dest = preserve_root / rel
    final_dest = dest
    if dest.exists():
        if _same_file_content(source, dest):
            if not dry_run:
                source.unlink()
            return f"dedupe {rel}"
        final_dest = _conflict_dest(dest)

    if dry_run:
        return f"dry-run move {rel} -> {final_dest}"

    final_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(final_dest))
    return f"moved {rel} -> {final_dest}"


def _records(lines: Iterable[str]) -> Iterable[tuple[str, str]]:
    for line in lines:
        line = line.rstrip("\n")
        if not line:
            continue
        if "\t" not in line:
            yield line[:2], line[3:]
            continue
        status, relpath = line.split("\t", 1)
        yield status, relpath


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--preserve-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    configured_root = args.preserve_root or _preserve_root_from_env()
    if configured_root is None:
        print(
            "ship-private-preserve: skip; SHIP_PRIVATE_PRESERVE_ROOT is not set",
            file=sys.stderr,
        )
        return 0

    preserve_root = configured_root.resolve()
    if not preserve_root.exists():
        print(f"ship-private-preserve: skip missing preserve root {preserve_root}", file=sys.stderr)
        return 0

    for status, relpath in _records(sys.stdin):
        try:
            message = preserve_one(
                repo_root=repo_root,
                preserve_root=preserve_root,
                status=status,
                relpath=relpath,
                dry_run=args.dry_run,
            )
        except (OSError, ValueError) as exc:
            print(f"ship-private-preserve: failed {relpath}: {exc}", file=sys.stderr)
            continue
        print(f"ship-private-preserve: {message}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
