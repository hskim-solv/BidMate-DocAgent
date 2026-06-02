"""Tests for issue #1755 — eval-to-adr-bridge advisory at gate evidence.

When the active loop bundles its Conservative-Gate evidence for a task that
touched an eval/benchmark surface, the audit record carries an advisory-only
pointer at the ``eval-to-adr-bridge`` agent (sibling of the eval-anomaly
advisory). The advisory is call-only: it is recorded but never runs the eval,
judges the ADR threshold, reserves an ADR number, invokes the agent, or changes
the gate's ready decision.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import agent_loop  # noqa: E402


def _repo(tmp_path: Path) -> Path:
    # The active dir exists in a real run; create it so every path op has a home.
    (tmp_path / "reports" / "agent_loop" / "active").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_eval_to_adr_advisory_content() -> None:
    adv = agent_loop._eval_to_adr_advisory(["eval/config.yaml"])
    assert adv["agent"] == "eval-to-adr-bridge"
    assert adv["trigger"]
    assert adv["eval_files"] == ["eval/config.yaml"]
    guidance = adv["guidance"]
    assert "ADR threshold" in guidance
    assert "Proposed" in guidance
    # Call-only contract is explicit.
    assert "Advisory only" in guidance


def test_gate_evidence_emits_eval_to_adr_advisory_on_eval_surface(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    out_dir = repo / "gate"
    path, summary = agent_loop.write_active_gate_evidence(
        task_id="T-2026-0042",
        changed_files=["eval/config.yaml", "rag_core.py"],
        repo_root=repo,
        out_dir=out_dir,
    )
    ev = json.loads(path.read_text(encoding="utf-8"))
    adv = ev["eval_to_adr_advisory"]
    assert adv is not None
    assert adv["agent"] == "eval-to-adr-bridge"
    # Only the eval-surface file is listed, not the product-runtime one.
    assert "eval/config.yaml" in adv["eval_files"]
    assert "rag_core.py" not in adv["eval_files"]
    assert "ADR threshold" in adv["guidance"]
    assert summary["eval_to_adr_advisory"] is not None

    md = (out_dir / "evidence.md").read_text(encoding="utf-8")
    assert "## Eval-to-ADR advisory" in md
    assert "eval-to-adr-bridge" in md
    # Call-only: the human-gated ship note must still be present and unchanged.
    assert "Ship is NOT triggered here" in md


def test_gate_evidence_omits_eval_to_adr_advisory_without_eval_surface(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    out_dir = repo / "gate"
    path, summary = agent_loop.write_active_gate_evidence(
        task_id="T-2026-0042",
        # Load-bearing (rag_core.py) but NOT an eval surface, plus a docs file.
        changed_files=["rag_core.py", "docs/operations/long-session-workflow.md"],
        repo_root=repo,
        out_dir=out_dir,
    )
    ev = json.loads(path.read_text(encoding="utf-8"))
    assert ev["eval_to_adr_advisory"] is None
    assert summary["eval_to_adr_advisory"] is None
    # load-bearing alone must NOT trigger the eval-to-adr advisory.
    assert ev["load_bearing_touched"] is True

    md = (out_dir / "evidence.md").read_text(encoding="utf-8")
    assert "Eval-to-ADR advisory" not in md


def test_eval_to_adr_advisory_does_not_change_gate_ready_decision(tmp_path: Path) -> None:
    """The advisory is additive: with the same (empty) registry, the ready
    decision is identical whether or not an eval surface was touched."""
    repo = _repo(tmp_path)
    _path_a, summary_eval = agent_loop.write_active_gate_evidence(
        task_id="T-2026-0042",
        changed_files=["eval/config.yaml"],
        repo_root=repo,
        out_dir=repo / "gate_a",
    )
    _path_b, summary_noeval = agent_loop.write_active_gate_evidence(
        task_id="T-2026-0042",
        changed_files=["docs/operations/x.md"],
        repo_root=repo,
        out_dir=repo / "gate_b",
    )
    assert summary_eval["ready"] == summary_noeval["ready"]
    # And the eval-to-adr advisory only appears on the eval-surface run.
    assert summary_eval["eval_to_adr_advisory"] is not None
    assert summary_noeval["eval_to_adr_advisory"] is None
