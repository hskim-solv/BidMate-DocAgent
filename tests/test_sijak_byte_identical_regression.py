"""ADR 0088 / ADR 0001: the default `make 시작` recipe must stay byte-identical.

The staging self-ship lane is opt-in via the SEPARATE `시작-ship` target. This test
pins the exact `시작:` recipe so the self-ship work cannot silently alter the default
loop (which CI / the demo / 20-30 worktrees depend on). If `시작:` is changed for a
legitimate reason, update EXPECTED_SIJAK_RECIPE deliberately.
"""
from __future__ import annotations

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT_DIR / "Makefile"

# Exact recipe lines of the `시작:` target (tab-indented), as of ADR 0085.
EXPECTED_SIJAK_RECIPE = [
    '\t$(MAKE) agent-loop-queue-parallel-plan \\',
    '\t  QUEUE_PARALLEL_PLAN_LIMIT="$(ACTIVE_AUTO_LOOP_AUTO_MAX_ITERATIONS)"',
    '\t$(MAKE) agent-loop-queue-recommendations \\',
    '\t  QUEUE_RECOMMENDATIONS_APPLY="$(START_QUEUE_RECOMMENDATIONS_APPLY)"',
    '\t$(MAKE) agent-loop-active-auto-loop \\',
    '\t  ACTIVE_AUTO_LOOP_MAX_ITERATIONS="$(if $(filter 1 true yes,$(START_INFINITE)),0,$(START_TASK_LIMIT))" \\',
    '\t  ACTIVE_AUTO_LOOP_AUTO_MAX_ITERATIONS="$(START_TASK_ATTEMPT_LIMIT)" \\',
    '\t  ACTIVE_AUTO_LOOP_TARGET_COMPLETED_COUNT="$(if $(filter 1 true yes,$(START_INFINITE)),,$(START_TASK_LIMIT))" \\',
    '\t  ACTIVE_RUNNER="$(ACTIVE_RUNNER)" \\',
    '\t  ACTIVE_AUTO_LOOP_EXECUTE_RUNNER=1 \\',
    '\t  ACTIVE_AUTO_LOOP_EXECUTE_SHIP=0 \\',
    '\t  ACTIVE_AUTO_LOOP_AUTO_REPAIR=1',
]


def _extract_recipe(target: str) -> list[str]:
    """Return the tab-indented recipe lines for *target* (exact, no normalisation)."""
    lines = MAKEFILE.read_text().splitlines()
    recipe: list[str] = []
    in_target = False
    for line in lines:
        if not in_target:
            if line == f"{target}:":
                in_target = True
            continue
        if line.startswith("\t"):
            recipe.append(line)
        elif line.strip() == "":
            break  # blank line ends the recipe block
        else:
            break  # next target / non-indented line ends the block
    return recipe


def test_sijak_recipe_is_byte_identical():
    assert _extract_recipe("시작") == EXPECTED_SIJAK_RECIPE


def test_sijak_default_does_not_self_ship():
    recipe = "\n".join(_extract_recipe("시작"))
    assert "ACTIVE_AUTO_LOOP_EXECUTE_SHIP=0" in recipe
    for forbidden in ("_staging_ship", "시작-ship", "EXECUTE_SHIP=1"):
        assert forbidden not in recipe, f"default 시작 recipe must not reference {forbidden!r}"


def test_sijak_ship_is_a_separate_additive_target():
    ship_recipe = "\n".join(_extract_recipe("시작-ship"))
    assert ship_recipe, "시작-ship target must exist"
    assert "_staging_ship.py" in ship_recipe
    assert ".ship-armed" in ship_recipe  # ship-arm mutual exclusion
    assert "$(MAKE) 시작" in ship_recipe  # composes the unchanged default loop


def test_phony_declares_both_targets():
    text = MAKEFILE.read_text()
    assert " 시작 " in text  # 시작 still phony-declared
    assert "시작-ship" in text
