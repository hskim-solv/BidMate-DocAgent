#!/usr/bin/env python3
"""Arm auto-ship and immediately run the dispatcher.

`make ship-arm` intentionally only writes `.claude/.ship-armed`; Claude Code's
Stop hook later invokes `stop-ship.sh`. Codex and other non-Claude sessions do
not naturally fire that Stop hook, so this wrapper keeps the same arm file and
dispatcher contract but runs the dispatcher immediately.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence


ARMED_FILE = Path(".claude/.ship-armed")
HOOK_DIR = Path(__file__).resolve().parent
SHIP_ARM = HOOK_DIR / "_ship_arm.py"
DISPATCHER = HOOK_DIR / "stop-ship.sh"

TRUTHY = {"1", "true", "yes", "y", "on", "ack"}


def is_truthy(value: str) -> bool:
    return value.strip().lower() in TRUTHY


def build_arm_command(args: argparse.Namespace) -> list[str]:
    return [
        sys.executable,
        str(SHIP_ARM),
        "--ttl",
        args.ttl,
        "--real-eval",
        args.real_eval,
        "--draft",
        args.draft,
        "--dry-run",
        args.dry_run,
        "--cross-owner",
        args.cross_owner,
        "--stacked",
        args.stacked,
    ]


def repo_root(runner=subprocess.run) -> Path:
    result = runner(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return Path(os.getcwd())


def run_dispatcher(runner=subprocess.run, root: Path | None = None) -> int:
    root = root or repo_root(runner=runner)
    result = runner(
        ["bash", str(DISPATCHER)],
        input="",
        text=True,
        check=False,
        cwd=root,
    )
    return result.returncode


def run_ship(args: argparse.Namespace, runner=subprocess.run) -> int:
    root = repo_root(runner=runner)
    use_existing_arm = is_truthy(args.use_existing_arm)
    if (root / ARMED_FILE).exists() and not use_existing_arm:
        sys.stderr.write(
            "ship-run: refuse - .claude/.ship-armed already exists.\n"
            "   Use USE_EXISTING_ARM=1 make ship-run to dispatch it, or "
            "make ship-disarm before re-arming.\n"
        )
        return 1

    if not use_existing_arm:
        arm_result = runner(build_arm_command(args), check=False, cwd=root)
        if arm_result.returncode != 0:
            return arm_result.returncode

    return run_dispatcher(runner=runner, root=root)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ttl", default="2h")
    parser.add_argument("--real-eval", default="auto",
                        choices=["auto", "skip", "async"])
    parser.add_argument("--draft", default="false")
    parser.add_argument("--dry-run", default="0")
    parser.add_argument("--cross-owner", default="")
    parser.add_argument("--stacked", default="")
    parser.add_argument(
        "--use-existing-arm",
        default="0",
        help="1/true/yes/ack to dispatch an existing .claude/.ship-armed.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    return run_ship(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
