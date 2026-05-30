"""Regression: `make install-hooks` must set the shared-objectstore corruption guards.

issue #1680 — 20-30 git worktrees share one ``.git/objects`` store. Automatic
``git gc``/repack/prune races with an in-flight ``git add``/commit and deletes blobs
that only an uncommitted worktree index references (``fatal: unable to read <blob>`` /
invalid cache-tree). The fix lives in the ``install-hooks`` make target so every clone
inherits it; this test pins that the target keeps configuring those guards.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _install_hooks_recipe() -> str:
    lines = (ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("install-hooks:"))
    body: list[str] = []
    for line in lines[start + 1 :]:
        # A make recipe is the contiguous tab-indented block under the target.
        if line and not line.startswith("\t"):
            break
        body.append(line)
    return "\n".join(body)


def test_install_hooks_disables_automatic_object_pruning() -> None:
    recipe = _install_hooks_recipe()
    # Disabling every automatic pruner is what removes the gc-vs-add race entirely.
    assert "git config gc.auto 0" in recipe
    assert "git config gc.autoDetach false" in recipe
    assert "git config maintenance.auto false" in recipe


def test_install_hooks_enables_loose_object_fsync() -> None:
    recipe = _install_hooks_recipe()
    # Durability: the index must never reference a not-yet-fsynced loose object.
    assert "git config core.fsync loose-object" in recipe
    assert "git config core.fsyncMethod batch" in recipe


def test_install_hooks_still_activates_hooks_path() -> None:
    # The corruption guards are additive; the original hook activation stays.
    assert "git config core.hooksPath .githooks" in _install_hooks_recipe()
