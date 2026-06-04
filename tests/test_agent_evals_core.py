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


def test_scanner_rejects_oversized_yaml_value_under_innocuous_key() -> None:
    # GAP 1: raw prose smuggled as a long scalar under a non-forbidden task key
    # (``train_hint``) is only caught once the YAML is parsed structurally.
    report = load_module("agent-evals/core/report.py", "agent_evals_report_yaml_size_test")

    smuggled = "x" * 600
    text = (
        "task_id: T-1\n"
        "source: smoke_synthetic_contract\n"
        "category: hook_privacy\n"
        f"train_hint: {smuggled}\n"
        "acceptance:\n  - preserve guard\n"
        "hidden_test_gate: unseen guard passes\n"
    )
    violations = report.validate_agent_eval_file("agent-evals/tasks/T-1/task.yaml", text)

    assert any("oversized data string" in violation.reason for violation in violations)


def test_scanner_rejects_yaml_value_pattern_only_visible_after_parse() -> None:
    # GAP 1: the diff marker is anchored to start-of-line, so as a raw YAML scalar
    # value it escapes the whole-text scan and is only exposed after a real parse.
    report = load_module("agent-evals/core/report.py", "agent_evals_report_yaml_parse_test")

    text = (
        "task_id: T-1\n"
        "source: smoke_synthetic_contract\n"
        "category: hook_privacy\n"
        "train_hint: 'diff --git a/secret b/secret'\n"
        "acceptance:\n  - preserve guard\n"
        "hidden_test_gate: unseen guard passes\n"
    )
    violations = report.validate_agent_eval_file("agent-evals/tasks/T-1/task.yaml", text)

    assert any("raw diff marker" in violation.reason for violation in violations)


def test_scanner_rejects_unparseable_yaml_artifact() -> None:
    # GAP 1: a committable YAML artifact that does not parse cannot be cleared by
    # the structural layer, so it is rejected rather than silently text-scanned.
    report = load_module("agent-evals/core/report.py", "agent_evals_report_yaml_bad_test")

    violations = report.validate_agent_eval_file(
        "agent-evals/splits.yaml", "assignment: [unterminated\n"
    )

    assert any("unparseable YAML data artifact" in violation.reason for violation in violations)


def test_scanner_rejects_oversized_aggregate_json_value() -> None:
    # GAP 2: an aggregate JSON string value can hide a raw excerpt even when it
    # matches none of the value patterns, so a size cap mirrors the Python check.
    report = load_module("agent-evals/core/report.py", "agent_evals_report_json_size_test")

    blob = "y" * 600
    text = '{"schema_version": 1, "notes": "' + blob + '"}'
    violations = report.validate_agent_eval_file("agent-evals/reports/smoke.aggregate.json", text)

    assert any("oversized data string" in violation.reason for violation in violations)


def test_scanner_key_allowlists_match_schema() -> None:
    # The scanner mirrors schema.py's positive key sets inline so the pre-commit
    # boundary stays import-free; this guards the duplication against drift.
    report = load_module("agent-evals/core/report.py", "agent_evals_report_drift_test")
    schema = load_module("agent-evals/core/schema.py", "agent_evals_schema_drift_test")

    assert report._ALLOWED_TASK_KEYS == schema.ALLOWED_TASK_KEYS
    assert report._ALLOWED_REPORT_KEYS == schema.ALLOWED_REPORT_KEYS


def test_scanner_rejects_unknown_task_yaml_key() -> None:
    # P1 (cross-family review): a non-forbidden raw sink under an unknown key
    # (issue_title) must fail closed, not only the fixed forbidden-key list.
    report = load_module("agent-evals/core/report.py", "agent_evals_report_task_key_test")

    text = (
        "task_id: T-1\n"
        "source: smoke_synthetic_contract\n"
        "category: hook_privacy\n"
        "acceptance:\n  - preserve guard\n"
        "hidden_test_gate: unseen guard passes\n"
        "issue_title: raw upstream issue title\n"
    )
    violations = report.validate_agent_eval_file("agent-evals/tasks/T-1/task.yaml", text)

    assert any("unknown task key" in violation.reason for violation in violations)


def test_scanner_rejects_unknown_aggregate_report_key() -> None:
    report = load_module("agent-evals/core/report.py", "agent_evals_report_report_key_test")

    text = '{"schema_version": 1, "pr_title": "raw upstream pr title"}'
    violations = report.validate_agent_eval_file("agent-evals/reports/smoke.aggregate.json", text)

    assert any("unknown report key" in violation.reason for violation in violations)


def test_scanner_rejects_unknown_splits_key() -> None:
    report = load_module("agent-evals/core/report.py", "agent_evals_report_split_key_test")

    text = "schema_version: 1\nrfp_excerpt: a short raw excerpt\n"
    violations = report.validate_agent_eval_file("agent-evals/splits.yaml", text)

    assert any("unknown split key" in violation.reason for violation in violations)


def test_scanner_rejects_raw_sink_under_allowed_report_object() -> None:
    # P1 (cross-family review): a raw-title sink nested under an allowed top-level
    # object (metrics) bypasses the top-level allowlist, so the recursive denylist
    # must name it. pr_title/issue_title/rfp_excerpt are now forbidden at any depth.
    report = load_module("agent-evals/core/report.py", "agent_evals_report_nested_sink_test")

    text = '{"schema_version": 1, "metrics": {"pr_title": "raw upstream title"}}'
    violations = report.validate_agent_eval_file("agent-evals/reports/smoke.aggregate.json", text)

    assert any(
        "forbidden data key" in violation.reason and "pr_title" in violation.reason
        for violation in violations
    )


def test_scanner_rejects_non_mapping_yaml_artifact() -> None:
    # P1 (cross-family review): wrapping unknown keys in a sequence must not bypass
    # the positive key allowlist; a non-mapping committable YAML is rejected.
    report = load_module("agent-evals/core/report.py", "agent_evals_report_yaml_seq_test")

    violations = report.validate_agent_eval_file(
        "agent-evals/tasks/T-1/task.yaml", "- issue_title: raw upstream issue title\n"
    )

    assert any("must be a mapping" in violation.reason for violation in violations)


def test_scanner_rejects_raw_body_variant_under_nested_object() -> None:
    # P1 (cross-family review): nested raw sinks must fail closed structurally via
    # the recursive allowlist, not depend on the denylist naming every variant
    # (issue_body / review_body / comment_body / ...). scanner is a non-dynamic
    # allowed object, so an unknown nested key is rejected outright.
    report = load_module("agent-evals/core/report.py", "agent_evals_report_nested_body_test")

    text = '{"schema_version": 1, "scanner": {"issue_body": "raw upstream body"}}'
    violations = report.validate_agent_eval_file("agent-evals/reports/smoke.aggregate.json", text)

    assert any("unknown report key not in schema" in violation.reason for violation in violations)


def test_scanner_rejects_scalar_metric_entry() -> None:
    # P1 (cross-family review): under the dynamic-name parent `metrics`, a scalar
    # raw sink masquerading as a metric name is rejected because each metric entry
    # must itself be a mapping (a PairedDelta row). issue_body is not denylisted,
    # so this proves the structural gate is independent of the denylist.
    report = load_module("agent-evals/core/report.py", "agent_evals_report_scalar_metric_test")

    text = '{"schema_version": 1, "metrics": {"issue_body": "raw upstream body"}}'
    violations = report.validate_agent_eval_file("agent-evals/reports/smoke.aggregate.json", text)

    assert any("must be a mapping" in violation.reason for violation in violations)
