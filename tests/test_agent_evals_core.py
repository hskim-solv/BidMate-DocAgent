from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(rel_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_paired_delta_reports_directional_same_task_difference() -> None:
    metrics = load_module("agent-evals/core/metrics.py", "agent_evals_metrics_test")

    delta = metrics.paired_delta(
        [
            {"v0": 0, "v1": 1},
            {"v0": 1, "v1": 1},
            {"v0": 0, "v1": 1},
        ],
        baseline_key="v0",
        candidate_key="v1",
        metric="hidden_gate_pass_rate",
    )

    assert delta.n == 3
    assert delta.baseline_mean == 0.333333
    assert delta.candidate_mean == 1.0
    assert delta.delta == 0.666667
    assert (delta.wins, delta.losses, delta.ties) == (2, 0, 1)


def test_paired_delta_rejects_empty_input() -> None:
    metrics = load_module("agent-evals/core/metrics.py", "agent_evals_metrics_empty_test")

    try:
        metrics.paired_delta([], baseline_key="v0", candidate_key="v1", metric="accepted")
    except ValueError as exc:
        assert "at least one" in str(exc)
    else:  # pragma: no cover - explicit failure keeps this stdlib-only
        raise AssertionError("paired_delta accepted an empty same-task set")


def test_scanner_accepts_current_pr2_surface_files() -> None:
    report = load_module("agent-evals/core/report.py", "agent_evals_report_accept_test")
    rel_paths = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "agent-evals").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )

    violations = []
    for rel_path in rel_paths:
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        violations.extend(report.validate_agent_eval_file(rel_path, text))

    assert [violation.render() for violation in violations] == []


def test_scanner_rejects_unexpected_agent_evals_path() -> None:
    report = load_module("agent-evals/core/report.py", "agent_evals_report_path_test")

    violations = report.validate_agent_eval_file("agent-evals/runs/T-1/run-log.json", "{}")

    assert any("outside the PR2 committable allowlist" in violation.reason for violation in violations)


def test_scanner_rejects_raw_data_keys_and_local_paths() -> None:
    report = load_module("agent-evals/core/report.py", "agent_evals_report_raw_test")

    violations = report.validate_agent_eval_file(
        "agent-evals/reports/smoke.aggregate.json",
        '{"schema_version": 1, "query": "redacted", "notes": ["/Users/example/private"]}',
    )

    rendered = "\n".join(violation.render() for violation in violations)
    assert "forbidden data key" in rendered
    assert "absolute local path" in rendered


def test_scanner_rejects_bidmate_back_edge_in_core_code() -> None:
    report = load_module("agent-evals/core/report.py", "agent_evals_report_import_test")

    violations = report.validate_agent_eval_file("agent-evals/core/schema.py", "import rag_core\n")

    assert any("forbidden repo back-edge import" in violation.reason for violation in violations)


def test_schema_rejects_unknown_task_keys() -> None:
    schema = load_module("agent-evals/core/schema.py", "agent_evals_schema_test")

    try:
        schema.EvalTask.from_mapping(
            {
                "task_id": "T-1",
                "source": "smoke_synthetic_contract",
                "category": "hook_privacy",
                "acceptance": ["preserve guard"],
                "hidden_test_gate": "unseen guard passes",
                "filename": "not allowed",
            }
        )
    except ValueError as exc:
        assert "unknown task key" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("EvalTask accepted a raw-sink key")
