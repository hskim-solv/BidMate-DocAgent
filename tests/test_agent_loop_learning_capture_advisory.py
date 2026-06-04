"""Tests for issue #1745 — learning-capture advisory on loop completion (T-X1).

When `write_active_auto_loop` finishes a run that actually ran a cycle, the
terminal loop state + completion event carry an advisory-only pointer at the
`/wiki` skill + memory-curator agent so the cycle's learning can be accumulated.
The advisory is call-only: it never writes to the wiki/memory, never invokes an
agent, and never changes the loop's decision or control flow.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import agent_loop  # noqa: E402


def _write_loop_repo(tmp_path: Path, *, task_id: str = "T-2026-9999", status: str = "ready") -> Path:
    (tmp_path / "tasks").mkdir(parents=True)
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    queue = f"""# Persistent Task Queue

## Ready Order

| Order | ID | Status | Owner role | Why ready / not ready |
|---:|---|---|---|---|
| 1 | `{task_id}` | `{status}` | Implementer -> Reviewer | fixture ready task |

## {task_id} — Agent loop automation

- ID: {task_id}
- Title: Agent loop automation
- Status: {status}
- Owner role: Implementer -> Reviewer

### Goal

Automate the existing operating loop without changing product behavior.

### Acceptance Criteria

- [ ] CLI renders prompts and checks handoffs.

### Validation Commands

```bash
python3 -m pytest tests/test_agent_loop.py -q
```

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/{task_id}-agent-loop.md`](../docs/plans/{task_id}-agent-loop.md)
"""
    (tmp_path / "tasks" / "queue.md").write_text(queue, encoding="utf-8")
    (tmp_path / "docs" / "plans" / f"{task_id}-agent-loop.md").write_text(
        f"# Plan: {task_id}\n\n- Status: running\n- Related task: `tasks/queue.md::{task_id}`\n",
        encoding="utf-8",
    )
    return tmp_path


def test_learning_capture_advisory_content() -> None:
    adv = agent_loop._learning_capture_advisory(
        decision="partial", completed=["T-2026-0001"], deferred=["T-2026-0002"]
    )
    assert adv["tools"] == ["/wiki", "memory-curator"]
    assert adv["decision"] == "partial"
    assert adv["completed_task_ids"] == ["T-2026-0001"]
    assert adv["deferred_task_ids"] == ["T-2026-0002"]
    assert "/wiki" in adv["guidance"]
    assert "memory-curator" in adv["guidance"]
    # Call-only contract is stated explicitly.
    assert "Advisory only" in adv["guidance"]


def test_advisory_present_in_state_when_a_cycle_ran(tmp_path: Path) -> None:
    repo = _write_loop_repo(tmp_path)
    active_dir = repo / "reports" / "agent_loop" / "active"
    # execute_runner=False still records a (planned) cycle for the selected task.
    result = agent_loop.write_active_auto_loop(
        max_iterations=1,
        execute_runner=False,
        execute_ship=False,
        repo_root=repo,
        task_pool=1,  # PR-F flipped the default to 2; pin X=1 (advisory emission is pool-agnostic) so this fixture (no real git repo) does not enter the X>1 worktree-per-task path.
    )
    assert result.cycles  # a cycle was recorded
    state = json.loads((active_dir / "auto_loop_state.json").read_text(encoding="utf-8"))
    adv = state["learning_capture_advisory"]
    assert adv is not None
    assert adv["tools"] == ["/wiki", "memory-curator"]
    assert adv["decision"] == result.decision


def test_advisory_absent_when_no_cycle_ran(tmp_path: Path) -> None:
    repo = _write_loop_repo(tmp_path, task_id="T-2026-1001")
    active_dir = repo / "reports" / "agent_loop" / "active"
    active_dir.mkdir(parents=True, exist_ok=True)
    # Pre-seed the target as already reached so the loop stops without a cycle.
    (active_dir / "auto_loop_state.json").write_text(
        json.dumps({"completed_task_ids": ["T-2026-1001", "T-2026-1002"]}),
        encoding="utf-8",
    )
    result = agent_loop.write_active_auto_loop(
        max_iterations=5,
        target_completed_count=2,
        execute_runner=False,
        execute_ship=False,
        repo_root=repo,
        task_pool=1,  # PR-F flipped the default to 2; pin X=1 to isolate this fixture from the X>1 worktree path (target already met -> no cycle, but keep intent explicit).
    )
    assert result.cycles == ()  # target already reached, no cycle ran
    state = json.loads((active_dir / "auto_loop_state.json").read_text(encoding="utf-8"))
    assert state["learning_capture_advisory"] is None
