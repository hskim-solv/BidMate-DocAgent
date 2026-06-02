"""Tests for issue #1757 — adr-lifecycle-manager advisory on loop completion.

When `write_active_auto_loop` finishes a run that actually ran a cycle, the
terminal loop state + completion event carry an advisory-only pointer at the
adr-lifecycle-manager skill IF there are proposed ADRs over the 30-day SLA
(ADR 0047). Sibling of the learning-capture advisory. Call-only: it reads the
``proposed_adr_age`` collector read-only and never mutates an ADR, touches the
README index, opens a PR, or invokes the skill, and never changes the loop's
decision or control flow. A collector failure degrades to None (never blocks).
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import agent_loop  # noqa: E402
from scripts._governance import ProposedADR  # noqa: E402


def _over_sla_record(number: int = 88) -> ProposedADR:
    return ProposedADR(
        number=number,
        filename=f"{number:04d}-x.md",
        status="proposed",
        first_commit=date(2026, 4, 1),
        age_days=62,
        grandfathered=False,
        over_sla=True,
        resolved_in_place=False,
    )


def _ok_record(number: int = 90) -> ProposedADR:
    return ProposedADR(
        number=number,
        filename=f"{number:04d}-y.md",
        status="proposed",
        first_commit=date(2026, 6, 1),
        age_days=1,
        grandfathered=False,
        over_sla=False,
        resolved_in_place=False,
    )


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


def test_adr_lifecycle_advisory_content_fires_when_over_sla(monkeypatch) -> None:
    monkeypatch.setattr(agent_loop, "proposed_adr_age", lambda *a, **k: [_over_sla_record(88)])
    adv = agent_loop._adr_lifecycle_advisory()
    assert adv is not None
    assert adv["skill"] == "adr-lifecycle-manager"
    assert adv["over_sla_adrs"][0]["number"] == "0088"
    assert "30-day SLA" in adv["guidance"]
    # Call-only contract is stated explicitly.
    assert "Advisory only" in adv["guidance"]


def test_adr_lifecycle_advisory_none_when_no_over_sla(monkeypatch) -> None:
    # resolved_in_place / grandfathered / fresh ADRs do NOT carry over_sla.
    monkeypatch.setattr(agent_loop, "proposed_adr_age", lambda *a, **k: [_ok_record(90)])
    assert agent_loop._adr_lifecycle_advisory() is None


def test_adr_lifecycle_advisory_none_on_collector_failure(monkeypatch) -> None:
    def _boom(*a, **k):
        raise RuntimeError("git unavailable")

    monkeypatch.setattr(agent_loop, "proposed_adr_age", _boom)
    # Must never block the loop: a collector crash degrades to None.
    assert agent_loop._adr_lifecycle_advisory() is None


def test_loop_state_carries_advisory_when_over_sla_and_cycle_ran(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(agent_loop, "proposed_adr_age", lambda *a, **k: [_over_sla_record(88)])
    repo = _write_loop_repo(tmp_path)
    active_dir = repo / "reports" / "agent_loop" / "active"
    result = agent_loop.write_active_auto_loop(
        max_iterations=1,
        execute_runner=False,
        execute_ship=False,
        repo_root=repo,
    )
    assert result.cycles  # a cycle was recorded
    state = json.loads((active_dir / "auto_loop_state.json").read_text(encoding="utf-8"))
    adv = state["adr_lifecycle_advisory"]
    assert adv is not None
    assert adv["skill"] == "adr-lifecycle-manager"
    assert adv["over_sla_adrs"][0]["number"] == "0088"


def test_loop_state_advisory_absent_when_no_cycle_ran(monkeypatch, tmp_path: Path) -> None:
    # Even with OVER_SLA ADRs present, no cycle => no advisory (the `if cycles` gate).
    monkeypatch.setattr(agent_loop, "proposed_adr_age", lambda *a, **k: [_over_sla_record(88)])
    repo = _write_loop_repo(tmp_path, task_id="T-2026-1001")
    active_dir = repo / "reports" / "agent_loop" / "active"
    active_dir.mkdir(parents=True, exist_ok=True)
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
    )
    assert result.cycles == ()  # target already reached, no cycle ran
    state = json.loads((active_dir / "auto_loop_state.json").read_text(encoding="utf-8"))
    assert state["adr_lifecycle_advisory"] is None


def test_loop_decision_invariant_to_advisory(monkeypatch, tmp_path: Path) -> None:
    """The advisory cannot perturb the loop: OVER_SLA vs none yields the same
    decision + completed set; the advisory only appears in the OVER_SLA run."""
    repo_a = _write_loop_repo(tmp_path / "a")
    monkeypatch.setattr(agent_loop, "proposed_adr_age", lambda *a, **k: [_over_sla_record(88)])
    result_over = agent_loop.write_active_auto_loop(
        max_iterations=1,
        execute_runner=False,
        execute_ship=False,
        repo_root=repo_a,
    )
    repo_b = _write_loop_repo(tmp_path / "b")
    monkeypatch.setattr(agent_loop, "proposed_adr_age", lambda *a, **k: [])
    result_none = agent_loop.write_active_auto_loop(
        max_iterations=1,
        execute_runner=False,
        execute_ship=False,
        repo_root=repo_b,
    )
    assert result_over.decision == result_none.decision
    assert result_over.completed_task_ids == result_none.completed_task_ids
    state_a = json.loads((repo_a / "reports" / "agent_loop" / "active" / "auto_loop_state.json").read_text(encoding="utf-8"))
    state_b = json.loads((repo_b / "reports" / "agent_loop" / "active" / "auto_loop_state.json").read_text(encoding="utf-8"))
    assert state_a["adr_lifecycle_advisory"] is not None
    assert state_b["adr_lifecycle_advisory"] is None
