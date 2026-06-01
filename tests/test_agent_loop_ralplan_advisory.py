"""Tests for issue #1741 — ralplan plan-gate advisory at preflight (T-X3).

The agent-loop preflight surfaces an advisory-only recommendation to crystallize
an *ambiguous* task (one lacking BOTH an Acceptance Criteria section and any
Validation Commands) with the ``/ralplan`` consensus plan gate before it enters
the implementation lane. The advisory is call-only: it must never change
preflight's exit code or block the loop.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import agent_loop  # noqa: E402

AMBIGUOUS_ID = "T-2026-9001"
SPECIFIED_ID = "T-2026-9002"

QUEUE_FIXTURE = f"""# Persistent Task Queue

## {AMBIGUOUS_ID} — Ambiguous seed task

- Title: Ambiguous seed task
- Status: ready
- Owner role: Implementer -> Reviewer

Do something useful. No acceptance contract, no validation commands.

## {SPECIFIED_ID} — Well-specified task

- Title: Well-specified task
- Status: ready
- Owner role: Implementer -> Reviewer

### Acceptance Criteria

- [ ] The thing works.

### Validation Commands

```bash
python3 -m pytest tests/test_agent_loop.py -q
```
"""


def _write_queue(repo_root: Path) -> None:
    queue_path = repo_root / agent_loop.QUEUE_PATH
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(QUEUE_FIXTURE, encoding="utf-8")


def test_task_is_ambiguous_detects_missing_contract(tmp_path: Path) -> None:
    _write_queue(tmp_path)
    assert agent_loop._task_is_ambiguous(AMBIGUOUS_ID, repo_root=tmp_path) is True
    assert agent_loop._task_is_ambiguous(SPECIFIED_ID, repo_root=tmp_path) is False


def test_task_is_ambiguous_unknown_or_missing_queue_is_false(tmp_path: Path) -> None:
    # No queue file at all -> never blocks / never advises.
    assert agent_loop._task_is_ambiguous(AMBIGUOUS_ID, repo_root=tmp_path) is False
    _write_queue(tmp_path)
    # Unknown task id -> False.
    assert agent_loop._task_is_ambiguous("T-2026-0000", repo_root=tmp_path) is False


def test_preflight_emits_ralplan_advisory_for_ambiguous_task(tmp_path: Path) -> None:
    _write_queue(tmp_path)
    _rc, rendered = agent_loop.render_preflight(
        task_id=AMBIGUOUS_ID,
        changed_files=["scripts/agent_loop.py"],
        repo_root=tmp_path,
    )
    assert "Plan gate (ralplan):" in rendered
    assert "/ralplan" in rendered
    assert AMBIGUOUS_ID in rendered
    # Advisory-only: it does not block. rc is driven solely by the handoff check,
    # so a present advisory must not be the reason for a non-zero exit code.
    assert "does NOT block preflight" in rendered


def test_preflight_omits_advisory_for_well_specified_task(tmp_path: Path) -> None:
    _write_queue(tmp_path)
    _rc, rendered = agent_loop.render_preflight(
        task_id=SPECIFIED_ID,
        changed_files=["scripts/agent_loop.py"],
        repo_root=tmp_path,
    )
    assert "Plan gate (ralplan):" not in rendered
    assert "/ralplan" not in rendered


def test_ralplan_advisory_does_not_change_exit_code(tmp_path: Path) -> None:
    """Same handoff state, ambiguous vs specified -> identical rc (advisory only)."""
    _write_queue(tmp_path)
    rc_ambiguous, _ = agent_loop.render_preflight(
        task_id=AMBIGUOUS_ID, changed_files=["scripts/agent_loop.py"], repo_root=tmp_path
    )
    rc_specified, _ = agent_loop.render_preflight(
        task_id=SPECIFIED_ID, changed_files=["scripts/agent_loop.py"], repo_root=tmp_path
    )
    assert rc_ambiguous == rc_specified
