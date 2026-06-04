from __future__ import annotations

import importlib.util
import json
import subprocess
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


def _is_gitignored(rel_path: str) -> bool:
    """True iff git ignores ``rel_path`` by pattern (ephemeral, non-committable)."""

    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", "--", rel_path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode in (0, 1), (
        f"git check-ignore failed for {rel_path} (rc={result.returncode}); treat as failure."
    )
    return result.returncode == 0


def test_scanner_accepts_current_pr2_surface_files() -> None:
    report = load_module("agent-evals/core/report.py", "agent_evals_report_accept_test")
    # Only the *committable* surface is asserted clean. Gitignored, deny-by-default
    # artifacts (e.g. ephemeral run-logs under agent-evals/runs/ that a local
    # pipeline run leaves behind) are not surface files and are intentionally
    # excluded — a clean CI checkout never has them, and they are *meant* to fail
    # the path allowlist if force-added (covered by the gitignore guard tests).
    rel_paths = sorted(
        rel
        for rel in (
            path.relative_to(REPO_ROOT).as_posix()
            for path in (REPO_ROOT / "agent-evals").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )
        if not _is_gitignored(rel)
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


def test_scanner_rejects_non_mapping_dynamic_section() -> None:
    # P1 (cross-family review): a dynamic section (metrics) that is a list/scalar
    # would let raw items fall through unchecked, so the section itself must be a
    # mapping of name -> row before any entry is accepted.
    report = load_module("agent-evals/core/report.py", "agent_evals_report_dyn_section_test")

    text = '{"schema_version": 1, "metrics": ["short raw reviewer body"]}'
    violations = report.validate_agent_eval_file("agent-evals/reports/smoke.aggregate.json", text)

    assert any("dynamic section must be a mapping" in violation.reason for violation in violations)


def test_scanner_rejects_top_level_key_reused_below_root() -> None:
    # P1 (cross-family review): top-level-only keys (notes/surface/...) must not be
    # accepted nested. A metric row reusing `notes` would otherwise smuggle short
    # raw prose; only the root uses the top-level schema, nested uses the row set.
    report = load_module("agent-evals/core/report.py", "agent_evals_report_nested_toplevel_test")

    text = '{"schema_version": 1, "metrics": {"review_body": {"notes": "raw upstream body"}}}'
    violations = report.validate_agent_eval_file("agent-evals/reports/smoke.aggregate.json", text)

    assert any("unknown report key not in schema" in violation.reason for violation in violations)


def test_scanner_accepts_pr3_paired_ci_nested_keys() -> None:
    # PR3: a powered metric row carries the bootstrap-CI extension nested keys
    # (underpowered / ci_lo / ci_hi / num_resamples / alpha). These must be in the
    # nested allowlist so a legitimate CI-aware row passes the scanner.
    report = load_module("agent-evals/core/report.py", "agent_evals_report_pr3_ci_keys_test")

    text = json.dumps(
        {
            "schema_version": 1,
            "surface": "agent-evals-pr3",
            "metrics": {
                "accepted_solve_rate": {
                    "metric": "accepted_solve_rate",
                    "baseline": "v0_naive",
                    "candidate": "v1_spec_first",
                    "n": 12,
                    "baseline_mean": 0.4,
                    "candidate_mean": 0.7,
                    "delta": 0.3,
                    "wins": 6,
                    "losses": 1,
                    "ties": 5,
                    "underpowered": False,
                    "ci_lo": 0.1,
                    "ci_hi": 0.5,
                    "num_resamples": 1000,
                    "alpha": 0.05,
                }
            },
        }
    )
    violations = report.validate_agent_eval_file("agent-evals/reports/holdout.aggregate.json", text)

    assert [violation.render() for violation in violations] == []


def test_scanner_rejects_raw_sink_nested_under_metric_row() -> None:
    # PR3: extending the nested allowlist with CI keys must NOT open a hole — a raw
    # sink nested inside a metric row (metrics.<name>.pr_title) is still rejected by
    # the recursive denylist.
    report = load_module("agent-evals/core/report.py", "agent_evals_report_pr3_nested_sink_test")

    text = json.dumps(
        {
            "schema_version": 1,
            "metrics": {"accepted_solve_rate": {"pr_title": "raw upstream pr title"}},
        }
    )
    violations = report.validate_agent_eval_file("agent-evals/reports/holdout.aggregate.json", text)

    assert any(
        "forbidden data key" in violation.reason and "pr_title" in violation.reason
        for violation in violations
    )


def test_generated_holdout_report_passes_scanner_and_is_aggregate_only() -> None:
    # PR3: the committed holdout report must clear the content scanner and contain
    # none of the raw/private sink tokens (aggregate-only boundary, ADR 0005).
    report = load_module("agent-evals/core/report.py", "agent_evals_report_holdout_scan_test")
    rel_path = "agent-evals/reports/holdout-v0-vs-v1.aggregate.json"
    text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")

    violations = report.validate_agent_eval_file(rel_path, text)
    assert [violation.render() for violation in violations] == []

    forbidden_tokens = (
        "pr_title",
        "issue_title",
        "rfp_excerpt",
        "patch",
        "diff --git",
        "/Users/",
        "run-log",
        "captured.diff",
    )
    lowered = text.lower()
    for token in forbidden_tokens:
        assert token.lower() not in lowered, f"forbidden token leaked into holdout report: {token}"


def test_generated_holdout_report_is_underpowered_with_no_ci_band() -> None:
    # PR3: the N=3 smoke holdout is below n_min, so every metric row must be flagged
    # underpowered and must OMIT the CI band (no ci_lo/ci_hi).
    rel_path = "agent-evals/reports/holdout-v0-vs-v1.aggregate.json"
    data = json.loads((REPO_ROOT / rel_path).read_text(encoding="utf-8"))

    assert data["surface"] == "agent-evals-pr3"
    assert data["task_count"] == 3
    assert set(data["metrics"]) == {
        "accepted_solve_rate",
        "difficulty_weighted_rate",
        "human_min_per_accepted",
        "cost_per_accepted",
    }
    for name, row in data["metrics"].items():
        assert row.get("underpowered") is True, f"{name} should be underpowered at N=3"
        assert "ci_lo" not in row and "ci_hi" not in row, f"{name} must omit CI band when underpowered"
    assert any(note.startswith("UNDERPOWERED N=") for note in data["notes"])


def _init_repo(tmp_path) -> Path:
    """Create an isolated git repo for scan_staged tests (no real-repo coupling)."""

    repo = tmp_path / "repo"
    repo.mkdir()

    def _git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    _git("init", "-q")
    _git("config", "user.email", "t@example.test")
    _git("config", "user.name", "agent-evals-test")
    return repo


def test_scan_staged_flags_denied_staged_agent_eval_path(tmp_path) -> None:
    # scan_staged is the ADR 0005 commit-time enforcer the pre-commit hook invokes
    # via `report.py --check-staged`. Existing coverage only asserts the hook TEXT
    # references it; this asserts the enforcement actually fires — a staged file
    # outside the committable allowlist (a raw run-log) must be flagged.
    report = load_module("agent-evals/core/report.py", "agent_evals_report_scan_staged_denied")
    repo = _init_repo(tmp_path)

    raw = repo / "agent-evals" / "runs"
    raw.mkdir(parents=True)
    (raw / "leak.json").write_text('{"captured_patch": "x"}', encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", "agent-evals/runs/leak.json"],
        check=True,
        capture_output=True,
    )

    violations = report.scan_staged(repo)

    assert [v.path for v in violations] == ["agent-evals/runs/leak.json"]
    assert "outside the PR2 committable allowlist" in violations[0].reason


def test_scan_staged_judges_staged_blob_not_worktree(tmp_path) -> None:
    # scan_staged must validate what will be COMMITTED — the staged blob read via
    # `git show :path` — not the current working-tree text. Stage a clean aggregate,
    # then dirty the worktree with content that WOULD be flagged: the scan must still
    # pass, because _read_staged_text reads the index, not the worktree. This locks
    # the staged-vs-worktree correctness of the commit boundary.
    report = load_module("agent-evals/core/report.py", "agent_evals_report_scan_staged_blob")
    repo = _init_repo(tmp_path)

    reports_dir = repo / "agent-evals" / "reports"
    reports_dir.mkdir(parents=True)
    clean = (REPO_ROOT / "agent-evals" / "reports" / "holdout-v0-vs-v1.aggregate.json").read_text(
        encoding="utf-8"
    )
    target = reports_dir / "x.aggregate.json"
    target.write_text(clean, encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", "agent-evals/reports/x.aggregate.json"],
        check=True,
        capture_output=True,
    )

    # Dirty the worktree AFTER staging; the index still holds the clean blob.
    target.write_text('{"captured_patch": "secret leak"}', encoding="utf-8")

    assert report.scan_staged(repo) == []
