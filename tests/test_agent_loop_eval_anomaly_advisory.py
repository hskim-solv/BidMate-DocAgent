"""Tests for issue #1742 — eval-anomaly-investigator advisory at gate evidence (T-X2).

When the active loop bundles its Conservative-Gate evidence for a task that
touched an eval/benchmark surface, the audit record carries an advisory-only
pointer at the ``eval-anomaly-investigator`` agent. The advisory is call-only:
it is recorded but never runs the eval, computes a regression delta, invokes the
agent, or changes the gate's ready decision.
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


def test_eval_surface_touched_filters_to_eval_surfaces() -> None:
    files = [
        "eval/run_eval.py",  # eval-harness
        "reports/eval_summary.json",  # public-fixture-smoke + benchmark-reporting
        "rag_core.py",  # product-runtime
        "docs/operations/long-session-workflow.md",  # docs-only
    ]
    hits = agent_loop._eval_surface_touched(files)
    assert "eval/run_eval.py" in hits
    assert "reports/eval_summary.json" in hits
    assert "rag_core.py" not in hits
    assert "docs/operations/long-session-workflow.md" not in hits


def test_gate_evidence_emits_eval_anomaly_advisory_on_eval_surface(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    out_dir = repo / "gate"
    path, summary = agent_loop.write_active_gate_evidence(
        task_id="T-2026-0042",
        changed_files=["eval/config.yaml", "rag_core.py"],
        repo_root=repo,
        out_dir=out_dir,
    )
    ev = json.loads(path.read_text(encoding="utf-8"))
    adv = ev["eval_anomaly_advisory"]
    assert adv is not None
    assert adv["agent"] == "eval-anomaly-investigator"
    # Only the eval-surface file is listed, not the product-runtime one.
    assert "eval/config.yaml" in adv["eval_files"]
    assert "rag_core.py" not in adv["eval_files"]
    assert "ADR 0005" in adv["guidance"]
    assert summary["eval_anomaly_advisory"] is not None

    md = (out_dir / "evidence.md").read_text(encoding="utf-8")
    assert "## Eval-anomaly advisory" in md
    assert "eval-anomaly-investigator" in md
    assert "ADR 0005" in md
    # Call-only: the human-gated ship note must still be present and unchanged.
    assert "Ship is NOT triggered here" in md


def test_gate_evidence_omits_eval_anomaly_advisory_without_eval_surface(tmp_path: Path) -> None:
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
    assert ev["eval_anomaly_advisory"] is None
    assert summary["eval_anomaly_advisory"] is None
    # load-bearing alone must NOT trigger the eval advisory.
    assert ev["load_bearing_touched"] is True

    md = (out_dir / "evidence.md").read_text(encoding="utf-8")
    assert "Eval-anomaly advisory" not in md


def test_eval_advisory_does_not_change_gate_ready_decision(tmp_path: Path) -> None:
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
        changed_files=["eval/config.yaml", "docs/operations/x.md"],
        repo_root=repo,
        out_dir=repo / "gate_b",
    )
    assert summary_eval["ready"] == summary_noeval["ready"]
