"""Guards the `make test-fast` xdist worker cap (issue #1318).

`-n auto` spawns one worker per logical core. On a dev box hosting many git
worktrees the machine runs under memory pressure; the simultaneous
worker-startup re-collection spikes free RAM to near-zero, macOS jetsam
OOM-kills a worker mid-schedule, and xdist dies with
`INTERNALERROR KeyError <WorkerController gwN>`. Capping the default worker
count (overridable via TEST_WORKERS) keeps the local loop alive. These tests
fail if someone reverts the recipe back to a hardcoded `-n auto`.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT_DIR / "Makefile"


def _test_fast_recipe() -> str:
    """Return the shell command line(s) of the `test-fast` target."""
    text = MAKEFILE.read_text(encoding="utf-8")
    lines = text.splitlines()
    out: list[str] = []
    in_target = False
    for line in lines:
        if line.startswith("test-fast:"):
            in_target = True
            continue
        if in_target:
            # Recipe lines are tab-indented; the target ends at the first
            # line that is neither tab-indented nor blank.
            if line.startswith("\t"):
                out.append(line.lstrip("\t"))
            elif line.strip() == "":
                continue
            else:
                break
    assert out, "could not locate the test-fast recipe in the Makefile"
    return "\n".join(out)


def test_test_fast_does_not_hardcode_n_auto() -> None:
    recipe = _test_fast_recipe()
    assert "-n auto" not in recipe, (
        "test-fast must not hardcode `-n auto` — it OOM-kills xdist workers on "
        "a memory-pressured multi-worktree box (issue #1318). Use "
        "`-n $(TEST_WORKERS)` with a bounded default instead."
    )


def test_test_fast_uses_overridable_worker_var() -> None:
    recipe = _test_fast_recipe()
    assert "-n $(TEST_WORKERS)" in recipe, (
        "test-fast should pass `-n $(TEST_WORKERS)` so the worker count is "
        "overridable (e.g. `make test-fast TEST_WORKERS=auto` on a roomy box)."
    )


def test_test_workers_default_is_a_bounded_integer() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    m = re.search(r"^TEST_WORKERS\s*\?=\s*(\S+)\s*$", text, re.MULTILINE)
    assert m, "missing `TEST_WORKERS ?= <n>` default assignment in the Makefile"
    default = m.group(1)
    assert default.isdigit(), (
        f"TEST_WORKERS default must be a fixed integer cap, not {default!r} — "
        "`auto` reintroduces the over-subscription that issue #1318 fixed."
    )
    assert 1 <= int(default) <= 8, (
        f"TEST_WORKERS default {default} is outside the sane local-loop range "
        "(1–8); pick a value that survives a memory-pressured box."
    )
