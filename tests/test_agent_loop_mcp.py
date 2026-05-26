from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts import agent_loop_mcp


ROOT = Path(__file__).resolve().parents[1]


def _call(name: str, arguments: dict | None = None) -> str:
    response = agent_loop_mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
    )
    assert response is not None
    assert "error" not in response
    result = response["result"]
    assert not result.get("isError", False)
    return result["content"][0]["text"]


def test_mcp_initialize_and_tool_list_are_read_report_centered() -> None:
    init = agent_loop_mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": "init",
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
    )
    assert init is not None
    assert init["result"]["capabilities"] == {"tools": {}}

    listed = agent_loop_mcp.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )
    assert listed is not None
    names = {tool["name"] for tool in listed["result"]["tools"]}

    assert "agent_loop_classify_surface" in names
    assert "agent_loop_gate_status" in names
    assert "agent_loop_auto_pass_check" in names
    assert "agent_loop_dashboard" in names
    assert "agent_loop_mcp_config" in names
    assert "agent_loop_pr_health" in names
    assert "agent_loop_safe_fix_dry_run" in names
    assert "agent_loop_approval_packet" in names
    assert "agent_loop_pr_body" in names
    assert "agent_loop_review_plan" in names
    assert "agent_loop_context_pack" in names
    assert "agent_loop_architecture_brief" in names
    assert "agent_loop_ship_simulate" in names
    assert "agent_loop_auto_ship_plan" in names
    assert "agent_loop_auto_ship_prepare" in names
    assert "agent_loop_gate_brief" in names
    assert "agent_loop_manifest" in names
    assert "agent_loop_pr_body_check" in names
    assert "agent_loop_patch_proposal" in names
    assert "agent_loop_dashboard_html" in names
    assert "agent_loop_ship_command_pack" in names
    assert "agent_loop_apply_queue_plan_dry_run" in names
    assert "agent_loop_review_threads" in names
    assert "agent_loop_ci_summary" in names
    assert "agent_loop_readiness_score" in names
    assert "agent_loop_branch_issue_hygiene" in names
    assert "agent_loop_validation_history" in names
    assert "agent_loop_privacy_regression" in names
    assert "agent_loop_claim_policy" in names
    assert "agent_loop_architecture_decision" in names
    assert "agent_loop_workset_recommend" in names
    assert "agent_loop_dependency_graph" in names
    assert "agent_loop_integration_pack" in names
    assert "agent_loop_scheduled_status" in names
    assert "agent_loop_automation_coverage" in names
    assert "agent_loop_promote_draft_dry_run" in names
    assert "agent_loop_validate" not in names
    assert "agent_loop_pr_scan" not in names
    assert "agent_loop_draft_next" not in names
    for name in names:
        lowered = name.lower()
        assert "push" not in lowered
        assert "merge" not in lowered
        assert "close" not in lowered
        assert "delete" not in lowered
        assert "force" not in lowered

    write_defaults = {
        prop["default"]
        for tool in listed["result"]["tools"]
        for prop in tool["inputSchema"]["properties"].values()
        if isinstance(prop, dict) and "default" in prop and prop.get("type") == "boolean"
    }
    assert write_defaults == {False}


def test_mcp_classifies_private_eval_and_redacts_private_report_paths() -> None:
    text = _call(
        "agent_loop_classify_surface",
        {
            "changed_files": [
                "reports/real100/eval_summary.json",
                "eval/real_config.local.yaml",
                "reports/eval_summary.json",
            ]
        },
    )

    assert "privacy-sensitive-artifact" in text
    assert "private-real-eval" in text
    assert "public-fixture-smoke" in text
    assert "reports/real100/[redacted-private-artifact]" in text
    assert "reports/real100/eval_summary.json" not in text
    assert "/Users/" not in text


def test_mcp_suggest_validation_does_not_run_commands() -> None:
    text = _call(
        "agent_loop_suggest_validation",
        {
            "changed_files": [
                "eval/naive_rag/benchmark.py",
                "scripts/compare_eval.py",
            ]
        },
    )

    assert "python3 -m py_compile eval/naive_rag/benchmark.py scripts/compare_eval.py" in text
    assert "python3 -m pytest tests/test_naive_rag_benchmark_v1.py -q" in text
    assert "python3 -m pytest tests/test_compare_eval_regression_gate.py -q" in text
    assert "git diff --check" in text
    assert "did not run them" in text


def test_mcp_unknown_tool_returns_tool_error_not_process_error() -> None:
    response = agent_loop_mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "agent_loop_validate", "arguments": {}},
        }
    )

    assert response is not None
    assert "error" not in response
    result = response["result"]
    assert result["isError"] is True
    assert "unknown tool" in result["content"][0]["text"]


def test_mcp_auto_pass_check_fails_closed_without_validation() -> None:
    text = _call(
        "agent_loop_auto_pass_check",
        {
            "changed_files": [
                "scripts/agent_loop.py",
                "tests/test_agent_loop.py",
            ]
        },
    )

    assert "human-review-required" in text
    assert "validation was not run" in text
    assert "auto-pass" not in text.splitlines()[2]


def test_mcp_rejects_input_paths_outside_repo() -> None:
    response = agent_loop_mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "agent_loop_claim_audit",
                "arguments": {"text": "/etc/passwd"},
            },
        }
    )

    assert response is not None
    result = response["result"]
    assert result["isError"] is True
    assert "repository root" in result["content"][0]["text"]


def test_mcp_dashboard_config_and_safe_fix_are_read_centered(tmp_path: Path) -> None:
    text = _call("agent_loop_dashboard", {"changed_files": ["scripts/agent_loop.py"]})
    assert "Agent Loop Dashboard" in text
    assert "ci-validation" in text

    config = _call("agent_loop_mcp_config")
    assert "<REPO_ROOT>/scripts/agent_loop_mcp.py" in config
    assert str(ROOT) not in config

    safe_fix = _call("agent_loop_safe_fix_dry_run", {"changed_files": ["scripts/agent_loop.py"]})
    assert "Safe Local Auto-Fix" in safe_fix
    assert "dry-run" in safe_fix

    context = _call("agent_loop_context_pack", {"changed_files": ["reports/real100/doc_id-1.json"]})
    assert "Cross-Agent Context Pack" in context
    assert "reports/real100/[redacted-private-artifact]" in context
    assert "doc_id-1" not in context

    ship = _call("agent_loop_ship_simulate", {"changed_files": ["scripts/agent_loop.py"], "branch": "chore/issue-123-agent-loop"})
    assert "Simulation only" in ship
    assert "gh pr create" in ship

    auto_ship = _call(
        "agent_loop_auto_ship_plan",
        {
            "changed_files": ["docs/operations/auto-ship.md"],
            "branch": "chore/issue-123-agent-loop",
            "dry_run": True,
        },
    )
    assert "Auto-Ship Plan" in auto_ship
    assert "make ship-arm" in auto_ship
    assert "does not arm auto-ship" in auto_ship

    prepare = _call(
        "agent_loop_auto_ship_prepare",
        {
            "issue": "123",
            "slug": "agent-loop",
        },
    )
    assert "Auto-Ship Prepare" in prepare
    assert "auto-ship-prepare --issue 123" in prepare
    assert "make ship-arm" in prepare
    assert "does not arm auto-ship" in prepare

    manifest = _call("agent_loop_manifest", {"changed_files": ["scripts/agent_loop.py"]})
    assert "changed_files_hash" in manifest

    html = _call("agent_loop_dashboard_html", {"changed_files": ["scripts/agent_loop.py"]})
    assert "<!doctype html>" in html

    dry_apply = _call("agent_loop_apply_queue_plan_dry_run")
    assert "blocked" in dry_apply


def test_mcp_new_reports_are_read_centered_and_redacted() -> None:
    scratch = ROOT / ".agent_loop_tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    threads = scratch / "mcp_threads.json"
    threads.write_text(
        json.dumps(
            [
                {
                    "isResolved": False,
                    "path": "reports/real100/doc_id-1.json",
                    "line": 7,
                    "comments": [{"body": "privacy issue with doc_id: SECRET"}],
                }
            ]
        ),
        encoding="utf-8",
    )
    claim = scratch / "mcp_claim.md"
    claim.write_text("This improves latency. question: PRIVATE RAW QUERY\n", encoding="utf-8")

    threads_report = _call("agent_loop_review_threads", {"threads_json": ".agent_loop_tmp/mcp_threads.json"})
    approval = _call(
        "agent_loop_approval_packet",
        {"changed_files": ["reports/eval_summary.json"], "claim_text": ".agent_loop_tmp/mcp_claim.md"},
    )
    policy = _call(
        "agent_loop_claim_policy",
        {"changed_files": ["reports/eval_summary.json"], "text": ".agent_loop_tmp/mcp_claim.md"},
    )
    privacy = _call("agent_loop_privacy_regression")
    coverage = _call("agent_loop_automation_coverage")

    assert "Privacy Auditor" in threads_report
    assert "SECRET" not in threads_report
    assert "performance claim language detected" in approval
    assert "PRIVATE RAW QUERY" not in approval
    assert "Disallowed Or Human-Gated Claims" in policy
    assert "Result: `pass`" in privacy
    assert "existing auto-ship bridge" in coverage


def test_mcp_stdio_smoke_lists_tools() -> None:
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    result = subprocess.run(
        [sys.executable, "scripts/agent_loop_mcp.py"],
        cwd=ROOT,
        input=request + "\n",
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    response = json.loads(result.stdout.strip())
    assert response["id"] == 1
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert "agent_loop_map" in names
