"""Opt-in queue auto-grow wiring for the `시작` loop (issue #2137).

`make 시작` runs `agent-loop-queue-recommendations` in report-only mode by default
(byte-identical, additionally pinned by test_sijak_byte_identical_regression.py). This
locks the opt-in contract: passing ``START_QUEUE_RECOMMENDATIONS_APPLY=1`` (the
discoverable ``START_``-namespace flag, consistent with ``START_INFINITE`` /
``START_TASK_LIMIT``) OR the pre-existing ``QUEUE_RECOMMENDATIONS_APPLY=1`` front door
makes that step append generated tasks (emits ``--apply``); the default stays
report-only. ``--apply`` is unique to the queue-recommendations command in the loop, so
its presence in ``make -n`` output is a faithful proxy for the apply path being wired.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
APPLY_VARS = ("QUEUE_RECOMMENDATIONS_APPLY", "START_QUEUE_RECOMMENDATIONS_APPLY")


def _dry_run_sijak(*overrides):
    # Strip ambient apply vars so the environment cannot leak an opt-in into the default
    # case; pass the opt-in (if any) as a make command-line override instead.
    env = {k: v for k, v in os.environ.items() if k not in APPLY_VARS}
    result = subprocess.run(
        ["make", "-n", "시작", *overrides],
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_default_sijak_is_report_only():
    assert "--apply" not in _dry_run_sijak()


def test_legacy_front_door_still_applies():
    # The pre-existing (undocumented) front door must keep working after the rewire.
    assert "--apply" in _dry_run_sijak("QUEUE_RECOMMENDATIONS_APPLY=1")


def test_start_namespace_optin_applies():
    # The new discoverable opt-in.
    assert "--apply" in _dry_run_sijak("START_QUEUE_RECOMMENDATIONS_APPLY=1")
