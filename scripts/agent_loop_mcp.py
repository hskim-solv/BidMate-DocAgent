#!/usr/bin/env python3
"""MCP stdio server for the BidMate agent-loop helper.

This adapter exposes the read/report-centered parts of ``scripts/agent_loop.py``
to MCP clients. It intentionally does not expose commands that push, merge,
create or close PRs, delete branches, force-push, run private eval, or call
external model APIs.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Callable


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import agent_loop  # noqa: E402


JSON = dict[str, Any]
ToolHandler = Callable[[JSON], str]

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "bidmate-agent-loop"
SERVER_VERSION = "0.1.0"


def tool_definitions() -> list[JSON]:
    """Return MCP tool metadata with conservative input schemas."""

    changed_files_schema: JSON = {
        "type": "array",
        "items": {"type": "string"},
        "description": "Changed file paths. Use repo-relative paths when possible.",
    }
    maybe_changed_files = {"changed_files": changed_files_schema}
    task_property = {
        "task": {
            "type": "string",
            "pattern": r"^T-\d{4}-\d{4}$",
            "description": "BidMate queue task id.",
        }
    }

    return [
        {
            "name": "agent_loop_map",
            "description": "Render the BidMate agent-loop map and human stop points.",
            "inputSchema": _schema({}),
        },
        {
            "name": "agent_loop_classify_surface",
            "description": "Classify changed-file surface conservatively from provided paths.",
            "inputSchema": _schema(maybe_changed_files),
        },
        {
            "name": "agent_loop_suggest_validation",
            "description": "Suggest safe focused validation commands without running them.",
            "inputSchema": _schema(maybe_changed_files),
        },
        {
            "name": "agent_loop_gate_status",
            "description": "Summarize the current gate, severity, signals, and next safe command.",
            "inputSchema": _schema(
                {
                    **task_property,
                    **maybe_changed_files,
                    "batch": {"type": "string", "description": "Optional local batch plan JSON path."},
                    "review_followups": {
                        "type": "string",
                        "description": "Optional local review follow-up report path.",
                    },
                    "pr": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "write": {
                        "type": "boolean",
                        "description": "Write reports/agent_loop/gate_status.md as well as returning text.",
                        "default": False,
                    },
                }
            ),
        },
        {
            "name": "agent_loop_loop_state",
            "description": "Build machine-readable loop state JSON from local artifacts and changed paths.",
            "inputSchema": _schema(
                {
                    **task_property,
                    **maybe_changed_files,
                    "batch": {"type": "string"},
                    "review_followups": {"type": "string"},
                    "pr": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "write": {
                        "type": "boolean",
                        "description": "Write reports/agent_loop/loop_state.json as well as returning JSON.",
                        "default": False,
                    },
                }
            ),
        },
        {
            "name": "agent_loop_decision_brief",
            "description": "Render human-gate options with trade-offs, severity, evidence, and next commands.",
            "inputSchema": _schema(
                {
                    **task_property,
                    **maybe_changed_files,
                    "batch": {"type": "string"},
                    "review_followups": {"type": "string"},
                    "gate": {
                        "type": "string",
                        "enum": ["auto", "task", "plan", "review", "claim", "ship"],
                        "default": "auto",
                    },
                    "pr": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "write": {
                        "type": "boolean",
                        "description": "Write reports/agent_loop/decision_brief.md as well as returning text.",
                        "default": False,
                    },
                }
            ),
        },
        {
            "name": "agent_loop_render_prompt",
            "description": "Render a copy-paste Codex implementation prompt for a task.",
            "inputSchema": _schema(
                {
                    **task_property,
                    "role": {"type": "string", "default": "Implementer"},
                    "plan": {"type": "string", "description": "Optional plan path."},
                },
                required=["task"],
            ),
        },
        {
            "name": "agent_loop_review_prompt",
            "description": "Render a copy-paste adversarial review prompt for a task.",
            "inputSchema": _schema(
                {
                    **task_property,
                    **maybe_changed_files,
                    "pr": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "branch": {"type": "string"},
                },
                required=["task"],
            ),
        },
        {
            "name": "agent_loop_handoff_check",
            "description": "Check the latest handoff block and fail closed on missing or weak evidence.",
            "inputSchema": _schema({**task_property, **maybe_changed_files, "plan": {"type": "string"}}, required=["task"]),
        },
        {
            "name": "agent_loop_claim_audit",
            "description": "Audit claim wording against changed-file surface classification.",
            "inputSchema": _schema(
                {
                    **maybe_changed_files,
                    "text": {"type": "string", "description": "Optional local text/report path to audit."},
                    "write": {
                        "type": "boolean",
                        "description": "Write reports/agent_loop/claim_audit.md as well as returning text.",
                        "default": False,
                    },
                }
            ),
        },
        {
            "name": "agent_loop_privacy_audit_output",
            "description": "Scan local agent-loop report artifacts for unredacted private raw values.",
            "inputSchema": _schema(
                {
                    "path": {
                        "type": "string",
                        "description": "Path under reports/agent_loop to scan.",
                        "default": "reports/agent_loop",
                    },
                    "write": {
                        "type": "boolean",
                        "description": "Write reports/agent_loop/privacy_audit.md as well as returning text.",
                        "default": False,
                    },
                }
            ),
        },
        {
            "name": "agent_loop_auto_pass_check",
            "description": "Fail-closed check for whether a low-risk local gate can continue without human review.",
            "inputSchema": _schema(
                {
                    **task_property,
                    **maybe_changed_files,
                    "claim_text": {"type": "string", "description": "Optional local claim text/report path."},
                    "run_validation": {
                        "type": "boolean",
                        "description": "Run allowlisted local validation before allowing auto-pass.",
                        "default": False,
                    },
                    "strict": {
                        "type": "boolean",
                        "description": "Require task, claim text, and no open review follow-up artifacts.",
                        "default": False,
                    },
                    "profile": {
                        "type": "string",
                        "enum": ["standard", "docs-only-strict", "ci-only-strict", "agent-loop-tooling-strict"],
                        "default": "standard",
                    },
                    "write": {
                        "type": "boolean",
                        "description": "Write reports/agent_loop/auto_pass.md as well as returning text.",
                        "default": False,
                    },
                }
            ),
        },
        {
            "name": "agent_loop_dashboard",
            "description": "Render a human-readable dashboard from current loop state.",
            "inputSchema": _schema(
                {
                    **task_property,
                    **maybe_changed_files,
                    "batch": {"type": "string"},
                    "review_followups": {"type": "string"},
                    "pr": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "write": {
                        "type": "boolean",
                        "description": "Write reports/agent_loop/dashboard.md as well as returning text.",
                        "default": False,
                    },
                }
            ),
        },
        {
            "name": "agent_loop_mcp_config",
            "description": "Render placeholder-based MCP client config samples.",
            "inputSchema": _schema({}),
        },
        {
            "name": "agent_loop_pr_health",
            "description": "Analyze exported PR state JSON into next-action lanes.",
            "inputSchema": _schema(
                {
                    "pr_json": {"type": "string", "default": "reports/agent_loop/pr_state.json"},
                    "write": {
                        "type": "boolean",
                        "description": "Write reports/agent_loop/pr_health.md as well as returning text.",
                        "default": False,
                    },
                }
            ),
        },
        {
            "name": "agent_loop_issue_scan",
            "description": "Read open issue state and conservatively classify cleanup versus queue migration lanes.",
            "inputSchema": _schema(
                {
                    "issue_json": {"type": "string", "description": "Optional local issue state JSON path."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 200},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_maintenance_plan",
            "description": "Render conservative issue, queue, branch, and worktree maintenance plan without executing cleanup.",
            "inputSchema": _schema(
                {
                    "issue_json": {"type": "string", "description": "Optional local issue state JSON path."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 200},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_safe_fix_dry_run",
            "description": "Dry-run safe whitespace-only local fixes for changed files.",
            "inputSchema": _schema(maybe_changed_files),
        },
        {
            "name": "agent_loop_approval_packet",
            "description": "Bundle PR/shipping approval evidence into one local report without approving action.",
            "inputSchema": _schema(
                {
                    **task_property,
                    **maybe_changed_files,
                    "pr": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "claim_text": {"type": "string"},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_propose_queue_plan",
            "description": "Render a dry-run queue/plan patch proposal; tracked files are not modified.",
            "inputSchema": _schema(
                {
                    "task_brief": {"type": "string"},
                    "task_id": {"type": "string", "pattern": r"^T-\d{4}-\d{4}$", "default": "T-2026-0000"},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_pr_body",
            "description": "Render a PR body draft from local evidence without creating a PR.",
            "inputSchema": _schema(
                {
                    **task_property,
                    **maybe_changed_files,
                    "branch": {"type": "string"},
                    "issue": {"type": "string"},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_review_plan",
            "description": "Triage review findings into fix and human-decision lanes.",
            "inputSchema": _schema(
                {
                    "review": {"type": "string"},
                    "pr": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_stale_reports",
            "description": "Report stale local agent-loop artifacts; delete is not exposed over MCP.",
            "inputSchema": _schema(
                {
                    "max_age_days": {"type": "integer", "minimum": 0, "maximum": 365, "default": 7},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_context_pack",
            "description": "Render a redacted cross-agent context pack.",
            "inputSchema": _schema(
                {
                    **task_property,
                    **maybe_changed_files,
                    "pr": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_architecture_brief",
            "description": "Explain architecture/ADR trade-offs without choosing an architecture.",
            "inputSchema": _schema({**maybe_changed_files, "write": {"type": "boolean", "default": False}}),
        },
        {
            "name": "agent_loop_ship_simulate",
            "description": "Simulate auto-ship readiness without mutating remote state.",
            "inputSchema": _schema(
                {
                    **task_property,
                    **maybe_changed_files,
                    "pr": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "branch": {"type": "string"},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_auto_ship_plan",
            "description": "Plan existing make ship-arm usage without arming or mutating remote state.",
            "inputSchema": _schema(
                {
                    **task_property,
                    **maybe_changed_files,
                    "pr": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "branch": {"type": "string"},
                    "ttl": {"type": "string", "default": "2h"},
                    "real_eval": {"type": "string", "enum": ["auto", "skip", "async"]},
                    "draft": {"type": "boolean", "default": False},
                    "dry_run": {"type": "boolean", "default": False},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_auto_ship_prepare",
            "description": "Report local branch preparation needed before make ship-arm; MCP never creates branches.",
            "inputSchema": _schema(
                {
                    "issue": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "target_branch": {"type": "string"},
                    "branch_type": {"type": "string", "default": "chore"},
                    "slug": {"type": "string", "default": "agent-loop-auto-ship"},
                    "ttl": {"type": "string", "default": "2h"},
                    "real_eval": {"type": "string", "enum": ["auto", "skip", "async"]},
                    "draft": {"type": "boolean"},
                    "dry_run": {"type": "boolean"},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_gate_brief",
            "description": "Explain a specific human gate with options and trade-offs.",
            "inputSchema": _schema(
                {
                    **task_property,
                    **maybe_changed_files,
                    "gate": {
                        "type": "string",
                        "enum": sorted(agent_loop.GATE_BRIEF_CHOICES),
                    },
                    "pr": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "write": {"type": "boolean", "default": False},
                },
                required=["gate"],
            ),
        },
        {
            "name": "agent_loop_manifest",
            "description": "Build or write an input-hash manifest for generated reports.",
            "inputSchema": _schema(
                {
                    **maybe_changed_files,
                    "source_command": {"type": "string", "default": "mcp"},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_pr_body_check",
            "description": "Validate a local PR body draft without creating or updating a PR.",
            "inputSchema": _schema(
                {
                    **maybe_changed_files,
                    "body": {"type": "string", "default": "reports/agent_loop/pr_body.md"},
                    "branch": {"type": "string"},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_ci_ingest",
            "description": "Ingest CI log text from local files into follow-up briefs.",
            "inputSchema": _schema(
                {
                    "log": {"type": "string"},
                    "pr": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_stacked_risk",
            "description": "Check read-only dependent PR risk from exported PR state or GitHub.",
            "inputSchema": _schema(
                {
                    "branch": {"type": "string"},
                    "pr_json": {"type": "string"},
                    "write": {"type": "boolean", "default": False},
                },
                required=["branch"],
            ),
        },
        {
            "name": "agent_loop_patch_proposal",
            "description": "Render a dry-run safe patch proposal from changed files.",
            "inputSchema": _schema({**maybe_changed_files, "write": {"type": "boolean", "default": False}}),
        },
        {
            "name": "agent_loop_adr_reserve",
            "description": "Draft ADR reservation artifacts under reports/agent_loop only.",
            "inputSchema": _schema({"title": {"type": "string"}, "write": {"type": "boolean", "default": False}}, required=["title"]),
        },
        {
            "name": "agent_loop_dashboard_html",
            "description": "Render a static HTML dashboard from local loop state.",
            "inputSchema": _schema(
                {
                    **task_property,
                    **maybe_changed_files,
                    "pr": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_ship_command_pack",
            "description": "Render human-gated shipping command suggestions without executing them.",
            "inputSchema": _schema(
                {
                    "pr": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "branch": {"type": "string"},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_apply_queue_plan_dry_run",
            "description": "Explain queue/plan apply gate without applying tracked docs.",
            "inputSchema": _schema({}),
        },
        {
            "name": "agent_loop_review_threads",
            "description": "Ingest review threads from local JSON or a PR without resolving or replying.",
            "inputSchema": _schema(
                {
                    "threads_json": {"type": "string"},
                    "pr": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_ci_summary",
            "description": "Summarize CI logs or read-only PR check state.",
            "inputSchema": _schema(
                {
                    "log": {"type": "string"},
                    "pr": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_readiness_score",
            "description": "Score local PR readiness signals without approving shipping.",
            "inputSchema": _schema(
                {
                    **task_property,
                    **maybe_changed_files,
                    "pr": {"type": "string", "pattern": r"^\d{1,10}$"},
                    "body": {"type": "string"},
                    "branch": {"type": "string"},
                    "claim_text": {"type": "string"},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_branch_issue_hygiene",
            "description": "Check branch, issue, task, and PR body linkage without creating issues or PRs.",
            "inputSchema": _schema(
                {
                    **task_property,
                    "branch": {"type": "string"},
                    "body": {"type": "string"},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_validation_history",
            "description": "Summarize local validation JSONL history.",
            "inputSchema": _schema(
                {
                    "history": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_privacy_regression",
            "description": "Run public sanitizer regression checks without private data.",
            "inputSchema": _schema({"write": {"type": "boolean", "default": False}}),
        },
        {
            "name": "agent_loop_claim_policy",
            "description": "Render claim policy for changed files and optional claim text.",
            "inputSchema": _schema(
                {
                    **maybe_changed_files,
                    "text": {"type": "string"},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_architecture_decision",
            "description": "Detect whether human architecture review is needed.",
            "inputSchema": _schema({**maybe_changed_files, "write": {"type": "boolean", "default": False}}),
        },
        {
            "name": "agent_loop_workset_recommend",
            "description": "Recommend serial, parallel, review-only, and manual-gated worksets.",
            "inputSchema": _schema(
                {
                    "batch": {"type": "string"},
                    "tasks_dir": {"type": "string"},
                    "max_items": {"type": "integer", "minimum": 1, "maximum": 100, "default": 12},
                    "write": {"type": "boolean", "default": False},
                }
            ),
        },
        {
            "name": "agent_loop_dependency_graph",
            "description": "Render a read-only stacked PR dependency graph.",
            "inputSchema": _schema(
                {
                    "branch": {"type": "string"},
                    "pr_json": {"type": "string"},
                    "write": {"type": "boolean", "default": False},
                },
                required=["branch"],
            ),
        },
        {
            "name": "agent_loop_integration_pack",
            "description": "Render Codex/Claude/ChatGPT/MCP integration guidance.",
            "inputSchema": _schema({"write": {"type": "boolean", "default": False}}),
        },
        {
            "name": "agent_loop_scheduled_status",
            "description": "Render a safe scheduled status recipe without installing it.",
            "inputSchema": _schema({"write": {"type": "boolean", "default": False}}),
        },
        {
            "name": "agent_loop_automation_coverage",
            "description": "Render coverage map for implemented automation candidates.",
            "inputSchema": _schema({"write": {"type": "boolean", "default": False}}),
        },
        {
            "name": "agent_loop_batch_plan",
            "description": "Group local generated task briefs into serial, parallel-safe, review-only, and gated lanes.",
            "inputSchema": _schema(
                {
                    "tasks_dir": {"type": "string", "default": "reports/agent_loop/codex_tasks"},
                    "max_items": {"type": "integer", "minimum": 1, "maximum": 100, "default": 12},
                    "write": {
                        "type": "boolean",
                        "description": "Write reports/agent_loop/batch_plan.md/json as well as returning text.",
                        "default": False,
                    },
                }
            ),
        },
        {
            "name": "agent_loop_review_followup",
            "description": "Convert reviewer findings into local follow-up task briefs.",
            "inputSchema": _schema(
                {
                    "review": {
                        "type": "string",
                        "description": "Local review output path under the repo.",
                    },
                    "write": {
                        "type": "boolean",
                        "description": "Write reports/agent_loop/review_followups.md and briefs.",
                        "default": False,
                    },
                },
                required=["review"],
            ),
        },
        {
            "name": "agent_loop_promote_draft_dry_run",
            "description": "Render a dry-run diff for queue/plan draft promotion; tracked files are not modified.",
            "inputSchema": _schema(
                {
                    "queue_draft": {"type": "string", "default": "reports/agent_loop/queue_entry_draft.md"},
                    "plan_draft": {"type": "string", "default": "reports/agent_loop/plan_draft.md"},
                    "write": {
                        "type": "boolean",
                        "description": "Write reports/agent_loop/promote_draft.md as well as returning text.",
                        "default": False,
                    },
                }
            ),
        },
    ]


def _schema(properties: JSON, *, required: list[str] | None = None) -> JSON:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def call_tool(name: str, arguments: JSON | None = None) -> JSON:
    args = arguments or {}
    handlers: dict[str, ToolHandler] = {
        "agent_loop_map": _tool_map,
        "agent_loop_classify_surface": _tool_classify_surface,
        "agent_loop_suggest_validation": _tool_suggest_validation,
        "agent_loop_gate_status": _tool_gate_status,
        "agent_loop_loop_state": _tool_loop_state,
        "agent_loop_decision_brief": _tool_decision_brief,
        "agent_loop_render_prompt": _tool_render_prompt,
        "agent_loop_review_prompt": _tool_review_prompt,
        "agent_loop_handoff_check": _tool_handoff_check,
        "agent_loop_claim_audit": _tool_claim_audit,
        "agent_loop_privacy_audit_output": _tool_privacy_audit_output,
        "agent_loop_auto_pass_check": _tool_auto_pass_check,
        "agent_loop_dashboard": _tool_dashboard,
        "agent_loop_mcp_config": _tool_mcp_config,
        "agent_loop_pr_health": _tool_pr_health,
        "agent_loop_issue_scan": _tool_issue_scan,
        "agent_loop_maintenance_plan": _tool_maintenance_plan,
        "agent_loop_safe_fix_dry_run": _tool_safe_fix_dry_run,
        "agent_loop_approval_packet": _tool_approval_packet,
        "agent_loop_propose_queue_plan": _tool_propose_queue_plan,
        "agent_loop_pr_body": _tool_pr_body,
        "agent_loop_review_plan": _tool_review_plan,
        "agent_loop_stale_reports": _tool_stale_reports,
        "agent_loop_context_pack": _tool_context_pack,
        "agent_loop_architecture_brief": _tool_architecture_brief,
        "agent_loop_ship_simulate": _tool_ship_simulate,
        "agent_loop_auto_ship_plan": _tool_auto_ship_plan,
        "agent_loop_auto_ship_prepare": _tool_auto_ship_prepare,
        "agent_loop_gate_brief": _tool_gate_brief,
        "agent_loop_manifest": _tool_manifest,
        "agent_loop_pr_body_check": _tool_pr_body_check,
        "agent_loop_ci_ingest": _tool_ci_ingest,
        "agent_loop_stacked_risk": _tool_stacked_risk,
        "agent_loop_patch_proposal": _tool_patch_proposal,
        "agent_loop_adr_reserve": _tool_adr_reserve,
        "agent_loop_dashboard_html": _tool_dashboard_html,
        "agent_loop_ship_command_pack": _tool_ship_command_pack,
        "agent_loop_apply_queue_plan_dry_run": _tool_apply_queue_plan_dry_run,
        "agent_loop_review_threads": _tool_review_threads,
        "agent_loop_ci_summary": _tool_ci_summary,
        "agent_loop_readiness_score": _tool_readiness_score,
        "agent_loop_branch_issue_hygiene": _tool_branch_issue_hygiene,
        "agent_loop_validation_history": _tool_validation_history,
        "agent_loop_privacy_regression": _tool_privacy_regression,
        "agent_loop_claim_policy": _tool_claim_policy,
        "agent_loop_architecture_decision": _tool_architecture_decision,
        "agent_loop_workset_recommend": _tool_workset_recommend,
        "agent_loop_dependency_graph": _tool_dependency_graph,
        "agent_loop_integration_pack": _tool_integration_pack,
        "agent_loop_scheduled_status": _tool_scheduled_status,
        "agent_loop_automation_coverage": _tool_automation_coverage,
        "agent_loop_batch_plan": _tool_batch_plan,
        "agent_loop_review_followup": _tool_review_followup,
        "agent_loop_promote_draft_dry_run": _tool_promote_draft_dry_run,
    }
    handler = handlers.get(name)
    if handler is None:
        return _tool_result(f"unknown tool: {name}", is_error=True)
    try:
        return _tool_result(handler(args))
    except (OSError, ValueError) as exc:
        return _tool_result(f"agent-loop: {exc}", is_error=True)


def _tool_result(text: str, *, is_error: bool = False) -> JSON:
    return {
        "content": [{"type": "text", "text": agent_loop._sanitize_dynamic_text(text)}],
        "isError": is_error,
    }


def _tool_map(_: JSON) -> str:
    return agent_loop.render_loop_map()


def _tool_classify_surface(args: JSON) -> str:
    return agent_loop.render_surface_report(agent_loop.classify_changed_files(_changed_files_arg(args)))


def _tool_suggest_validation(args: JSON) -> str:
    return agent_loop.render_validation_suggestions(
        agent_loop.suggest_validation_commands(_changed_files_arg(args))
    )


def _tool_gate_status(args: JSON) -> str:
    out = agent_loop.DEFAULT_GATE_STATUS if _bool_arg(args, "write", False) else None
    _, rendered = agent_loop.write_gate_status(
        task_id=_optional_str(args, "task"),
        batch=_optional_path(args, "batch"),
        review_followups=_optional_path(args, "review_followups"),
        changed_files=_changed_files_arg(args),
        pr=_optional_str(args, "pr"),
        out=out,
    )
    return rendered


def _tool_loop_state(args: JSON) -> str:
    if _bool_arg(args, "write", False):
        _, state = agent_loop.write_loop_state(
            task_id=_optional_str(args, "task"),
            batch=_optional_path(args, "batch"),
            review_followups=_optional_path(args, "review_followups"),
            changed_files=_changed_files_arg(args),
            pr=_optional_str(args, "pr"),
        )
    else:
        state = agent_loop.build_loop_state(
            task_id=_optional_str(args, "task"),
            batch=_optional_path(args, "batch"),
            review_followups=_optional_path(args, "review_followups"),
            changed_files=_changed_files_arg(args),
            pr=_optional_str(args, "pr"),
            repo_root=agent_loop.ROOT_DIR,
        )
    return json.dumps(state, indent=2, sort_keys=True) + "\n"


def _tool_decision_brief(args: JSON) -> str:
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_decision_brief(
            task_id=_optional_str(args, "task"),
            batch=_optional_path(args, "batch"),
            review_followups=_optional_path(args, "review_followups"),
            gate=_str_arg(args, "gate", "auto"),
            changed_files=_changed_files_arg(args),
            pr=_optional_str(args, "pr"),
        )
        return rendered
    points = agent_loop.build_decision_points(
        task_id=_optional_str(args, "task"),
        batch=_optional_path(args, "batch"),
        review_followups=_optional_path(args, "review_followups"),
        gate=_str_arg(args, "gate", "auto"),
        changed_files=_changed_files_arg(args),
        pr=_optional_str(args, "pr"),
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_decision_brief(points)


def _tool_render_prompt(args: JSON) -> str:
    return agent_loop.render_prompt(
        _required_str(args, "task"),
        role=_str_arg(args, "role", "Implementer"),
        plan_path=_optional_path(args, "plan"),
    )


def _tool_review_prompt(args: JSON) -> str:
    return agent_loop.render_review_prompt(
        _required_str(args, "task"),
        pr=_optional_str(args, "pr"),
        branch=_optional_str(args, "branch"),
        changed_files=_changed_files_arg(args) or None,
    )


def _tool_handoff_check(args: JSON) -> str:
    report = agent_loop.check_handoff(
        _required_str(args, "task"),
        plan_path=_optional_path(args, "plan"),
        changed_files=_changed_files_arg(args),
    )
    return agent_loop.render_handoff_report(report)


def _tool_claim_audit(args: JSON) -> str:
    if _bool_arg(args, "write", False):
        _, _, rendered = agent_loop.write_claim_audit(
            text_path=_optional_path(args, "text"),
            changed_files=_changed_files_arg(args),
        )
        return rendered
    text = ""
    source = "changed files only"
    text_path = _optional_path(args, "text")
    if text_path is not None:
        resolved = agent_loop._resolve_input_path(text_path, repo_root=agent_loop.ROOT_DIR)
        text = resolved.read_text(encoding="utf-8")
        source = agent_loop._display_path(agent_loop._repo_path(resolved, agent_loop.ROOT_DIR))
    surface = agent_loop.classify_changed_files(_changed_files_arg(args))
    findings = agent_loop.audit_claim_text(text, surface)
    return agent_loop.render_claim_audit(source=source, surface=surface, findings=findings)


def _tool_privacy_audit_output(args: JSON) -> str:
    path = _optional_path(args, "path") or agent_loop.DEFAULT_REPORT_DIR
    if _bool_arg(args, "write", False):
        _, _, rendered = agent_loop.write_privacy_audit_output(path=path)
        return rendered
    target = agent_loop._resolve_input_path(path, repo_root=agent_loop.ROOT_DIR)
    safe_target = agent_loop._safe_output_path(target, repo_root=agent_loop.ROOT_DIR)
    findings = agent_loop.audit_privacy_output(
        safe_target,
        out_path=agent_loop.DEFAULT_PRIVACY_AUDIT,
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_privacy_audit(findings, target=safe_target, repo_root=agent_loop.ROOT_DIR)


def _tool_auto_pass_check(args: JSON) -> str:
    if _bool_arg(args, "write", False):
        _, _, rendered = agent_loop.write_auto_pass_check(
            task_id=_optional_str(args, "task"),
            changed_files=_changed_files_arg(args),
            claim_text=_optional_path(args, "claim_text"),
            run_validation=_bool_arg(args, "run_validation", False),
            strict=_bool_arg(args, "strict", False),
            profile=_str_arg(args, "profile", "standard"),
        )
        return rendered
    report = agent_loop.build_auto_pass_report(
        task_id=_optional_str(args, "task"),
        changed_files=_changed_files_arg(args),
        claim_text=_optional_path(args, "claim_text"),
        run_validation=_bool_arg(args, "run_validation", False),
        repo_root=agent_loop.ROOT_DIR,
        strict=_bool_arg(args, "strict", False),
        profile=_str_arg(args, "profile", "standard"),
    )
    return agent_loop.render_auto_pass_report(report)


def _tool_dashboard(args: JSON) -> str:
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_dashboard(
            task_id=_optional_str(args, "task"),
            batch=_optional_path(args, "batch"),
            review_followups=_optional_path(args, "review_followups"),
            changed_files=_changed_files_arg(args),
            pr=_optional_str(args, "pr"),
        )
        return rendered
    state = agent_loop.build_loop_state(
        task_id=_optional_str(args, "task"),
        batch=_optional_path(args, "batch"),
        review_followups=_optional_path(args, "review_followups"),
        changed_files=_changed_files_arg(args),
        pr=_optional_str(args, "pr"),
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_dashboard(state)


def _tool_mcp_config(_: JSON) -> str:
    return agent_loop.render_mcp_client_config()


def _tool_pr_health(args: JSON) -> str:
    pr_json = _optional_path(args, "pr_json") or agent_loop.DEFAULT_PR_STATE
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_pr_health(pr_json=pr_json)
        return rendered
    path = agent_loop._resolve_input_path(pr_json, repo_root=agent_loop.ROOT_DIR)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("PR state JSON must be an array")
    return agent_loop.render_pr_health([item for item in payload if isinstance(item, dict)])


def _tool_issue_scan(args: JSON) -> str:
    if _bool_arg(args, "write", False):
        _, _, _, rendered = agent_loop.write_issue_scan(
            issue_json=_optional_path(args, "issue_json"),
            limit=_int_arg(args, "limit", 200),
        )
        return rendered
    issues = agent_loop._load_issue_state(
        issue_json=_optional_path(args, "issue_json"),
        limit=_int_arg(args, "limit", 200),
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_issue_triage(agent_loop.build_issue_triage(issues=issues, repo_root=agent_loop.ROOT_DIR))


def _tool_maintenance_plan(args: JSON) -> str:
    if _bool_arg(args, "write", False):
        _, _, _, rendered = agent_loop.write_maintenance_plan(
            issue_json=_optional_path(args, "issue_json"),
            limit=_int_arg(args, "limit", 200),
        )
        return rendered
    issues = agent_loop._load_issue_state(
        issue_json=_optional_path(args, "issue_json"),
        limit=_int_arg(args, "limit", 200),
        repo_root=agent_loop.ROOT_DIR,
    )
    triage = agent_loop.build_issue_triage(issues=issues, repo_root=agent_loop.ROOT_DIR)
    plan = agent_loop.MaintenancePlan(
        issues=triage,
        worktree_actions=("make worktree-cleanup-dry-run",),
        queue_task_briefs=(),
    )
    return agent_loop.render_maintenance_plan(plan)


def _tool_safe_fix_dry_run(args: JSON) -> str:
    report = agent_loop.build_safe_fix_report(
        changed_files=_changed_files_arg(args),
        apply=False,
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_safe_fix_report(report)


def _tool_approval_packet(args: JSON) -> str:
    changed_files = _changed_files_arg(args)
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_approval_packet(
            task_id=_optional_str(args, "task"),
            changed_files=changed_files,
            pr=_optional_str(args, "pr"),
            claim_text=_optional_path(args, "claim_text"),
        )
        return rendered
    surface = agent_loop.classify_changed_files(changed_files)
    gate = agent_loop.build_gate_status(
        task_id=_optional_str(args, "task"),
        batch=None,
        review_followups=None,
        changed_files=changed_files,
        pr=_optional_str(args, "pr"),
        repo_root=agent_loop.ROOT_DIR,
    )
    auto_pass = agent_loop.build_auto_pass_report(
        task_id=_optional_str(args, "task"),
        changed_files=changed_files,
        claim_text=_optional_path(args, "claim_text"),
        run_validation=False,
        strict=False,
        repo_root=agent_loop.ROOT_DIR,
    )
    claim_findings = ()
    claim_source = "N/A"
    claim_text = _optional_path(args, "claim_text")
    if claim_text is not None:
        resolved = agent_loop._resolve_input_path(claim_text, repo_root=agent_loop.ROOT_DIR)
        if resolved.exists():
            claim_source = agent_loop._display_path(agent_loop._repo_path(resolved, agent_loop.ROOT_DIR))
            claim_findings = tuple(agent_loop.audit_claim_text(resolved.read_text(encoding="utf-8"), surface))
    privacy_findings = tuple(
        agent_loop.audit_privacy_output(
            agent_loop.ROOT_DIR / "reports" / "agent_loop",
            out_path=None,
            repo_root=agent_loop.ROOT_DIR,
        )
    )
    return agent_loop.render_approval_packet(
        task_id=_optional_str(args, "task"),
        changed_files=changed_files,
        pr=_optional_str(args, "pr"),
        surface=surface,
        gate=gate,
        auto_pass=auto_pass,
        claim_findings=claim_findings,
        claim_source=claim_source,
        privacy_findings=privacy_findings,
    )


def _tool_propose_queue_plan(args: JSON) -> str:
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_propose_queue_plan(
            task_brief=_optional_path(args, "task_brief"),
            task_id=_str_arg(args, "task_id", agent_loop.DEFAULT_DRAFT_TASK_ID),
        )
        return rendered
    return _queue_plan_patch_text(
        task_brief=_optional_path(args, "task_brief"),
        task_id=_str_arg(args, "task_id", agent_loop.DEFAULT_DRAFT_TASK_ID),
    )


def _tool_pr_body(args: JSON) -> str:
    changed_files = _changed_files_arg(args)
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_pr_body(
            task_id=_optional_str(args, "task"),
            changed_files=changed_files,
            branch=_optional_str(args, "branch"),
            issue=_optional_str(args, "issue"),
        )
        return rendered
    return agent_loop.render_pr_body(
        task_id=_optional_str(args, "task"),
        changed_files=changed_files,
        branch=_optional_str(args, "branch"),
        issue=_optional_str(args, "issue"),
    )


def _tool_review_plan(args: JSON) -> str:
    review = _optional_path(args, "review")
    reviews = [review] if review is not None else []
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_review_plan(
            reviews=reviews,
            pr=_optional_str(args, "pr"),
        )
        return rendered
    findings, sources = agent_loop._collect_review_findings(
        reviews=reviews,
        pr=_optional_str(args, "pr"),
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_review_plan(findings, sources=sources)


def _tool_stale_reports(args: JSON) -> str:
    max_age_days = _int_arg(args, "max_age_days", 7)
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_stale_reports(max_age_days=max_age_days, apply=False)
        return rendered
    artifacts = agent_loop._report_freshness(repo_root=agent_loop.ROOT_DIR, max_age_days=max_age_days)
    return agent_loop.render_stale_reports(artifacts, max_age_days=max_age_days, apply=False, deleted=())


def _tool_context_pack(args: JSON) -> str:
    changed_files = _changed_files_arg(args)
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_context_pack(
            task_id=_optional_str(args, "task"),
            changed_files=changed_files,
            pr=_optional_str(args, "pr"),
        )
        return rendered
    state = agent_loop.build_loop_state(
        task_id=_optional_str(args, "task"),
        batch=None,
        review_followups=None,
        changed_files=changed_files,
        pr=_optional_str(args, "pr"),
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_context_pack(state, changed_files=changed_files)


def _tool_architecture_brief(args: JSON) -> str:
    changed_files = _changed_files_arg(args)
    surface = agent_loop.classify_changed_files(changed_files)
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_architecture_brief(changed_files=changed_files)
        return rendered
    return agent_loop.render_architecture_brief(surface=surface, changed_files=changed_files)


def _tool_ship_simulate(args: JSON) -> str:
    changed_files = _changed_files_arg(args)
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_ship_simulation(
            task_id=_optional_str(args, "task"),
            changed_files=changed_files,
            pr=_optional_str(args, "pr"),
            branch=_optional_str(args, "branch"),
        )
        return rendered
    return agent_loop.render_ship_simulation(
        task_id=_optional_str(args, "task"),
        changed_files=changed_files,
        pr=_optional_str(args, "pr"),
        branch=_optional_str(args, "branch"),
        repo_root=agent_loop.ROOT_DIR,
    )


def _tool_auto_ship_plan(args: JSON) -> str:
    changed_files = _changed_files_arg(args)
    if _bool_arg(args, "write", False):
        _, _, rendered = agent_loop.write_auto_ship_plan(
            task_id=_optional_str(args, "task"),
            changed_files=changed_files,
            pr=_optional_str(args, "pr"),
            branch=_optional_str(args, "branch"),
            ttl=_str_arg(args, "ttl", "2h"),
            real_eval=_optional_str(args, "real_eval"),
            draft=_bool_arg(args, "draft", False),
            dry_run=_bool_arg(args, "dry_run", False),
        )
        return rendered
    plan = agent_loop.build_auto_ship_plan(
        task_id=_optional_str(args, "task"),
        changed_files=changed_files,
        pr=_optional_str(args, "pr"),
        branch=_optional_str(args, "branch"),
        ttl=_str_arg(args, "ttl", "2h"),
        real_eval=_optional_str(args, "real_eval"),
        draft=_bool_arg(args, "draft", False),
        dry_run=_bool_arg(args, "dry_run", False),
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_auto_ship_plan(
        plan,
        task_id=_optional_str(args, "task"),
        changed_files=changed_files,
        pr=_optional_str(args, "pr"),
        repo_root=agent_loop.ROOT_DIR,
    )


def _tool_auto_ship_prepare(args: JSON) -> str:
    if _bool_arg(args, "write", False):
        _, _, rendered = agent_loop.write_auto_ship_prepare(
            issue=_optional_str(args, "issue"),
            target_branch=_optional_str(args, "target_branch"),
            branch_type=_str_arg(args, "branch_type", "chore"),
            slug=_str_arg(args, "slug", "agent-loop-auto-ship"),
            create_branch=False,
            confirm_human_approved=False,
            ttl=_str_arg(args, "ttl", "2h"),
            real_eval=_optional_str(args, "real_eval"),
            draft=_bool_arg(args, "draft", True),
            dry_run=_bool_arg(args, "dry_run", True),
        )
        return rendered
    report = agent_loop.build_auto_ship_prepare(
        issue=_optional_str(args, "issue"),
        target_branch=_optional_str(args, "target_branch"),
        branch_type=_str_arg(args, "branch_type", "chore"),
        slug=_str_arg(args, "slug", "agent-loop-auto-ship"),
        create_branch=False,
        confirm_human_approved=False,
        ttl=_str_arg(args, "ttl", "2h"),
        real_eval=_optional_str(args, "real_eval"),
        draft=_bool_arg(args, "draft", True),
        dry_run=_bool_arg(args, "dry_run", True),
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_auto_ship_prepare(report)


def _tool_gate_brief(args: JSON) -> str:
    changed_files = _changed_files_arg(args)
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_gate_brief(
            gate=_required_str(args, "gate"),
            task_id=_optional_str(args, "task"),
            changed_files=changed_files,
            pr=_optional_str(args, "pr"),
        )
        return rendered
    return agent_loop.render_gate_brief(
        gate=_required_str(args, "gate"),
        task_id=_optional_str(args, "task"),
        changed_files=changed_files,
        pr=_optional_str(args, "pr"),
        repo_root=agent_loop.ROOT_DIR,
    )


def _tool_manifest(args: JSON) -> str:
    changed_files = _changed_files_arg(args)
    if _bool_arg(args, "write", False):
        _, manifest = agent_loop.write_manifest(
            changed_files=changed_files,
            command=_str_arg(args, "source_command", "mcp"),
        )
    else:
        manifest = agent_loop.build_manifest(
            changed_files=changed_files,
            command=_str_arg(args, "source_command", "mcp"),
            outputs=(),
            repo_root=agent_loop.ROOT_DIR,
        )
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def _tool_pr_body_check(args: JSON) -> str:
    body = _optional_path(args, "body") or agent_loop.DEFAULT_PR_BODY
    changed_files = _changed_files_arg(args)
    if _bool_arg(args, "write", False):
        _, _, rendered = agent_loop.write_pr_body_check(
            body=body,
            changed_files=changed_files,
            branch=_optional_str(args, "branch"),
        )
        return rendered
    body_path = agent_loop._resolve_input_path(body, repo_root=agent_loop.ROOT_DIR)
    findings = agent_loop.check_pr_body_text(
        body_path.read_text(encoding="utf-8"),
        changed_files=changed_files,
        branch=_optional_str(args, "branch"),
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_pr_body_check(
        findings,
        body_path=body_path,
        changed_files=changed_files,
        branch=_optional_str(args, "branch"),
        repo_root=agent_loop.ROOT_DIR,
    )


def _tool_ci_ingest(args: JSON) -> str:
    log = _optional_path(args, "log")
    logs = [log] if log is not None else []
    if _bool_arg(args, "write", False):
        _, _, _, rendered = agent_loop.write_ci_ingest(logs=logs, pr=_optional_str(args, "pr"))
        return rendered
    findings, sources = agent_loop.collect_ci_findings(
        logs=logs,
        pr=_optional_str(args, "pr"),
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_ci_ingest(
        findings,
        sources=sources,
        tasks_dir=agent_loop.DEFAULT_CI_FOLLOWUPS_DIR,
        repo_root=agent_loop.ROOT_DIR,
    )


def _tool_stacked_risk(args: JSON) -> str:
    branch = _required_str(args, "branch")
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_stacked_risk(
            branch=branch,
            pr_json=_optional_path(args, "pr_json"),
        )
        return rendered
    items = agent_loop._stacked_pr_items(
        branch=branch,
        pr_json=_optional_path(args, "pr_json"),
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_stacked_risk(branch=branch, items=items)


def _tool_patch_proposal(args: JSON) -> str:
    changed_files = _changed_files_arg(args)
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_patch_proposal(changed_files=changed_files)
        return rendered
    return agent_loop.render_patch_proposal(
        changed_files=changed_files,
        review_plan=None,
        repo_root=agent_loop.ROOT_DIR,
    )


def _tool_adr_reserve(args: JSON) -> str:
    title = _required_str(args, "title")
    if _bool_arg(args, "write", False):
        _, _, rendered = agent_loop.write_adr_reservation(title=title)
        return rendered
    number = agent_loop._next_adr_number(agent_loop.ROOT_DIR)
    return agent_loop.render_adr_reservation(
        number=number,
        title=title,
        draft_path=agent_loop.DEFAULT_ADR_DRAFT,
    )


def _tool_dashboard_html(args: JSON) -> str:
    changed_files = _changed_files_arg(args)
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_dashboard_html(
            task_id=_optional_str(args, "task"),
            changed_files=changed_files,
            pr=_optional_str(args, "pr"),
        )
        return rendered
    state = agent_loop.build_loop_state(
        task_id=_optional_str(args, "task"),
        batch=None,
        review_followups=None,
        changed_files=changed_files,
        pr=_optional_str(args, "pr"),
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_dashboard_html(agent_loop.render_dashboard(state))


def _tool_ship_command_pack(args: JSON) -> str:
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_ship_command_pack(
            pr=_optional_str(args, "pr"),
            branch=_optional_str(args, "branch"),
        )
        return rendered
    return agent_loop.render_ship_command_pack(
        pr=_optional_str(args, "pr"),
        branch=_optional_str(args, "branch"),
        repo_root=agent_loop.ROOT_DIR,
    )


def _tool_apply_queue_plan_dry_run(_: JSON) -> str:
    return agent_loop.render_apply_queue_plan(
        confirm_human_approved=False,
        target_queue=agent_loop.QUEUE_PATH.as_posix(),
        target_plan="docs/plans/<from-plan-draft>.md",
    )


def _tool_review_threads(args: JSON) -> str:
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_review_threads(
            threads_json=_optional_path(args, "threads_json"),
            pr=_optional_str(args, "pr"),
        )
        return rendered
    findings, sources = agent_loop.collect_review_thread_findings(
        threads_json=_optional_path(args, "threads_json"),
        pr=_optional_str(args, "pr"),
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_review_threads(findings, sources=sources)


def _tool_ci_summary(args: JSON) -> str:
    log = _optional_path(args, "log")
    logs = [log] if log is not None else []
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_ci_summary(logs=logs, pr=_optional_str(args, "pr"))
        return rendered
    findings, sources = agent_loop.collect_ci_findings(
        logs=logs,
        pr=_optional_str(args, "pr"),
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_ci_summary(findings, sources=sources)


def _tool_readiness_score(args: JSON) -> str:
    changed_files = _changed_files_arg(args)
    if _bool_arg(args, "write", False):
        _, _, rendered = agent_loop.write_readiness_score(
            task_id=_optional_str(args, "task"),
            changed_files=changed_files,
            pr=_optional_str(args, "pr"),
            body=_optional_path(args, "body"),
            branch=_optional_str(args, "branch"),
            claim_text=_optional_path(args, "claim_text"),
        )
        return rendered
    report = agent_loop.build_readiness_score(
        task_id=_optional_str(args, "task"),
        changed_files=changed_files,
        pr=_optional_str(args, "pr"),
        body=_optional_path(args, "body"),
        branch=_optional_str(args, "branch"),
        claim_text=_optional_path(args, "claim_text"),
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_readiness_score(report, changed_files=changed_files, pr=_optional_str(args, "pr"))


def _tool_branch_issue_hygiene(args: JSON) -> str:
    if _bool_arg(args, "write", False):
        _, _, rendered = agent_loop.write_branch_issue_hygiene(
            branch=_optional_str(args, "branch"),
            body=_optional_path(args, "body"),
            task_id=_optional_str(args, "task"),
        )
        return rendered
    rendered, _ = agent_loop.render_branch_issue_hygiene(
        branch=_optional_str(args, "branch") or agent_loop._current_branch(agent_loop.ROOT_DIR) or "unknown",
        body=_optional_path(args, "body"),
        task_id=_optional_str(args, "task"),
        repo_root=agent_loop.ROOT_DIR,
    )
    return rendered


def _tool_validation_history(args: JSON) -> str:
    history = _optional_path(args, "history") or agent_loop.DEFAULT_VALIDATION_HISTORY
    limit = _int_arg(args, "limit", 10)
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_validation_history_report(history=history, limit=limit)
        return rendered
    entries = agent_loop.read_validation_history(history=history, limit=limit, repo_root=agent_loop.ROOT_DIR)
    return agent_loop.render_validation_history(entries, history=history, repo_root=agent_loop.ROOT_DIR)


def _tool_privacy_regression(args: JSON) -> str:
    if _bool_arg(args, "write", False):
        _, _, rendered = agent_loop.write_privacy_regression()
        return rendered
    rendered, _ = agent_loop.render_privacy_regression()
    return rendered


def _tool_claim_policy(args: JSON) -> str:
    changed_files = _changed_files_arg(args)
    if _bool_arg(args, "write", False):
        _, _, rendered = agent_loop.write_claim_policy(
            changed_files=changed_files,
            text=_optional_path(args, "text"),
        )
        return rendered
    surface = agent_loop.classify_changed_files(changed_files)
    findings = ()
    source = "N/A"
    text_path = _optional_path(args, "text")
    if text_path is not None:
        path = agent_loop._resolve_input_path(text_path, repo_root=agent_loop.ROOT_DIR)
        findings = tuple(agent_loop.audit_claim_text(path.read_text(encoding="utf-8"), surface))
        source = agent_loop._display_path(agent_loop._repo_path(path, agent_loop.ROOT_DIR), repo_root=agent_loop.ROOT_DIR)
    return agent_loop.render_claim_policy(surface=surface, findings=findings, source=source)


def _tool_architecture_decision(args: JSON) -> str:
    changed_files = _changed_files_arg(args)
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_architecture_decision(changed_files=changed_files)
        return rendered
    return agent_loop.render_architecture_decision(
        surface=agent_loop.classify_changed_files(changed_files),
        changed_files=changed_files,
    )


def _tool_workset_recommend(args: JSON) -> str:
    batch = _optional_path(args, "batch")
    tasks_dir = _optional_path(args, "tasks_dir") or agent_loop.DEFAULT_CODEX_TASKS_DIR
    max_items = _int_arg(args, "max_items", 12)
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_workset_recommendation(batch=batch, tasks_dir=tasks_dir, max_items=max_items)
        return rendered
    return agent_loop.render_workset_recommendation(
        batch=batch,
        tasks_dir=tasks_dir,
        max_items=max_items,
        repo_root=agent_loop.ROOT_DIR,
    )


def _tool_dependency_graph(args: JSON) -> str:
    branch = _required_str(args, "branch")
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_dependency_graph(
            branch=branch,
            pr_json=_optional_path(args, "pr_json"),
        )
        return rendered
    items = agent_loop._stacked_pr_items(
        branch=branch,
        pr_json=_optional_path(args, "pr_json"),
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_dependency_graph(branch=branch, items=items)


def _tool_integration_pack(args: JSON) -> str:
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_integration_pack()
        return rendered
    return agent_loop.render_integration_pack()


def _tool_scheduled_status(args: JSON) -> str:
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_schedule_config()
        return rendered
    return agent_loop.render_schedule_config()


def _tool_automation_coverage(args: JSON) -> str:
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_automation_coverage()
        return rendered
    return agent_loop.render_automation_coverage()


def _tool_batch_plan(args: JSON) -> str:
    tasks_dir = _optional_path(args, "tasks_dir") or agent_loop.DEFAULT_CODEX_TASKS_DIR
    max_items = _int_arg(args, "max_items", 12)
    if _bool_arg(args, "write", False):
        _, _, rendered = agent_loop.write_batch_plan(tasks_dir=tasks_dir, max_items=max_items)
        return rendered
    resolved = agent_loop._resolve_input_path(tasks_dir, repo_root=agent_loop.ROOT_DIR)
    briefs = agent_loop._load_brief_summaries(
        resolved,
        max_items=max_items,
        repo_root=agent_loop.ROOT_DIR,
    )
    return agent_loop.render_batch_plan(briefs, tasks_dir=resolved, repo_root=agent_loop.ROOT_DIR)


def _tool_review_followup(args: JSON) -> str:
    review = Path(_required_str(args, "review"))
    if _bool_arg(args, "write", False):
        _, _, _, rendered = agent_loop.write_review_followups(review=review)
        return rendered
    review_path = agent_loop._resolve_input_path(review, repo_root=agent_loop.ROOT_DIR)
    findings = agent_loop.parse_review_findings(review_path.read_text(encoding="utf-8"))
    return agent_loop.render_review_followups(
        findings,
        review_path=review_path,
        tasks_dir=agent_loop.DEFAULT_REVIEW_FOLLOWUPS_DIR,
    )


def _tool_promote_draft_dry_run(args: JSON) -> str:
    if _bool_arg(args, "write", False):
        _, rendered = agent_loop.write_promote_draft(
            queue_draft=_optional_path(args, "queue_draft") or agent_loop.DEFAULT_QUEUE_DRAFT,
            plan_draft=_optional_path(args, "plan_draft") or agent_loop.DEFAULT_PLAN_DRAFT,
        )
        return rendered
    queue_path = agent_loop._resolve_default_agent_loop_path(
        _optional_path(args, "queue_draft") or agent_loop.DEFAULT_QUEUE_DRAFT,
        "queue_entry_draft.md",
        repo_root=agent_loop.ROOT_DIR,
    )
    plan_path = agent_loop._resolve_default_agent_loop_path(
        _optional_path(args, "plan_draft") or agent_loop.DEFAULT_PLAN_DRAFT,
        "plan_draft.md",
        repo_root=agent_loop.ROOT_DIR,
    )
    queue_text = queue_path.read_text(encoding="utf-8")
    plan_text = plan_path.read_text(encoding="utf-8")
    target_plan = agent_loop._extract_suggested_plan_path(plan_text)
    queue_before = (agent_loop.ROOT_DIR / agent_loop.QUEUE_PATH).read_text(encoding="utf-8")
    target_plan_path = agent_loop.ROOT_DIR / target_plan
    plan_before = target_plan_path.read_text(encoding="utf-8") if target_plan_path.exists() else ""
    return agent_loop.render_promote_draft(
        queue_before=queue_before,
        queue_after=queue_before.rstrip() + "\n\n" + queue_text.rstrip() + "\n",
        plan_before=plan_before,
        plan_after=plan_text.rstrip() + "\n",
        target_queue=agent_loop.QUEUE_PATH.as_posix(),
        target_plan=target_plan.as_posix(),
    )


def _queue_plan_patch_text(*, task_brief: Path | None, task_id: str) -> str:
    if task_brief is not None:
        brief_path = agent_loop._resolve_input_path(task_brief, repo_root=agent_loop.ROOT_DIR)
        brief = agent_loop._parse_task_brief(agent_loop._sanitize_dynamic_text(brief_path.read_text(encoding="utf-8")))
        queue_text, plan_text = agent_loop._render_task_drafts(
            brief,
            task_id=task_id,
            brief_path=brief_path,
            repo_root=agent_loop.ROOT_DIR,
        )
    else:
        queue_path = agent_loop._resolve_default_agent_loop_path(
            agent_loop.DEFAULT_QUEUE_DRAFT,
            "queue_entry_draft.md",
            repo_root=agent_loop.ROOT_DIR,
        )
        plan_path = agent_loop._resolve_default_agent_loop_path(
            agent_loop.DEFAULT_PLAN_DRAFT,
            "plan_draft.md",
            repo_root=agent_loop.ROOT_DIR,
        )
        queue_text = queue_path.read_text(encoding="utf-8")
        plan_text = plan_path.read_text(encoding="utf-8")
    target_plan = agent_loop._extract_suggested_plan_path(plan_text)
    queue_before = (agent_loop.ROOT_DIR / agent_loop.QUEUE_PATH).read_text(encoding="utf-8")
    target_plan_path = agent_loop.ROOT_DIR / target_plan
    plan_before = target_plan_path.read_text(encoding="utf-8") if target_plan_path.exists() else ""
    return agent_loop.render_queue_plan_patch(
        queue_before=queue_before,
        queue_after=queue_before.rstrip() + "\n\n" + queue_text.rstrip() + "\n",
        plan_before=plan_before,
        plan_after=plan_text.rstrip() + "\n",
        target_queue=agent_loop.QUEUE_PATH.as_posix(),
        target_plan=target_plan.as_posix(),
    )


def _changed_files_arg(args: JSON) -> list[str]:
    raw = args.get("changed_files") or []
    if isinstance(raw, str):
        values = [item.strip() for item in raw.splitlines()]
    elif isinstance(raw, list):
        values = [str(item) for item in raw]
    else:
        raise ValueError("changed_files must be an array of strings")
    return sorted(
        {
            normalized
            for item in values
            if (normalized := agent_loop._normalize_changed_file(item, repo_root=agent_loop.ROOT_DIR))
        }
    )


def _optional_path(args: JSON, key: str) -> Path | None:
    value = args.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string path")
    path = Path(value)
    candidate = path if path.is_absolute() else agent_loop.ROOT_DIR / path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(agent_loop.ROOT_DIR.resolve())
    except ValueError as exc:
        raise ValueError(f"{key} must stay under the repository root") from exc
    return resolved


def _optional_str(args: JSON, key: str) -> str | None:
    value = args.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _required_str(args: JSON, key: str) -> str:
    value = _optional_str(args, key)
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _str_arg(args: JSON, key: str, default: str) -> str:
    return _optional_str(args, key) or default


def _bool_arg(args: JSON, key: str, default: bool) -> bool:
    value = args.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _int_arg(args: JSON, key: str, default: int) -> int:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def handle_request(request: JSON) -> JSON | None:
    method = request.get("method")
    request_id = request.get("id")
    is_notification = "id" not in request

    try:
        if method == "initialize":
            result = {
                "protocolVersion": _requested_protocol(request),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }
            return _response(request_id, result)
        if method == "notifications/initialized":
            return None
        if method == "ping":
            return _response(request_id, {})
        if method == "tools/list":
            return _response(request_id, {"tools": tool_definitions()})
        if method == "tools/call":
            params = request.get("params") or {}
            if not isinstance(params, dict):
                raise ValueError("params must be an object")
            name = params.get("name")
            if not isinstance(name, str):
                raise ValueError("tool name is required")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be an object")
            return _response(request_id, call_tool(name, arguments))
        if is_notification:
            return None
        return _error(request_id, -32601, f"method not found: {method}")
    except ValueError as exc:
        if is_notification:
            return None
        return _error(request_id, -32602, str(exc))


def _requested_protocol(request: JSON) -> str:
    params = request.get("params") or {}
    if isinstance(params, dict) and isinstance(params.get("protocolVersion"), str):
        return params["protocolVersion"]
    return PROTOCOL_VERSION


def _response(request_id: Any, result: JSON) -> JSON:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> JSON:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            response = _error(None, -32700, f"parse error: {exc.msg}")
        else:
            response = handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(serve())
