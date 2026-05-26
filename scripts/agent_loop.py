#!/usr/bin/env python3
"""Lightweight orchestration CLI for the BidMate AI-agent operating loop.

The CLI is intentionally read-centered except when explicitly writing generated
local artifacts under ``reports/agent_loop/``. It never pushes, merges, closes
PRs, deletes branches, force-pushes, or calls external model APIs.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import difflib
import hashlib
import html
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Iterable, Sequence


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts._governance import is_load_bearing  # noqa: E402


TASK_ID_RE = re.compile(r"\bT-\d{4}-\d{4}\b")
TASK_HEADING_RE = re.compile(
    r"^##\s+(?P<id>T-\d{4}-\d{4})\s+(?:[-\u2013\u2014])\s+(?P<title>.+?)\s*$",
    re.MULTILINE,
)
FIELD_RE = re.compile(r"^\s*[-*]\s*(?P<label>[^:\n]+):\s*(?P<value>.*)$", re.MULTILINE)
FENCED_BASH_RE = re.compile(r"```(?:bash|sh|shell)?\n(?P<body>.*?)```", re.DOTALL)
HANDOFF_HEADING_RE = re.compile(
    r"^#{1,6}\s+(?P<title>(?:Session\s+Handoff|Workstream\s+State|Handoff)(?!\s+Notes)\b.*)$",
    re.IGNORECASE | re.MULTILINE,
)
ABSOLUTE_LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:/Users|/private|/var/folders|/Volumes)/[^\s)`'\"]+"
)
PRIVATE_INLINE_VALUE_RE = re.compile(
    r"\b(?P<label>(?:raw\s+)?(?:question|answer|evidence)|doc[_ -]?id|"
    r"chunk[_ -]?id|file\s*name|filename)\b"
    r"\s*[:=]\s*(?P<value>[^\n;,]+)",
    re.IGNORECASE,
)
PRIVATE_FLAG_VALUE_RE = re.compile(
    r"(?P<flag>--(?:raw-)?(?:question|answer|evidence|doc[_-]?id|chunk[_-]?id|file(?:[_-]?name)?)\s+)"
    r"(?P<value>\"[^\"]*\"|'[^']*'|\S+)",
    re.IGNORECASE,
)

DEFAULT_REPORT_DIR = ROOT_DIR / "reports" / "agent_loop"
DEFAULT_RENDER_PROMPT = DEFAULT_REPORT_DIR / "rendered_prompt.txt"
DEFAULT_REVIEW_PROMPT = DEFAULT_REPORT_DIR / "review_prompt.txt"
DEFAULT_PR_STATE = DEFAULT_REPORT_DIR / "pr_state.json"
DEFAULT_QUEUE_DRAFT = DEFAULT_REPORT_DIR / "queue_entry_draft.md"
DEFAULT_PLAN_DRAFT = DEFAULT_REPORT_DIR / "plan_draft.md"
DEFAULT_AI_NEXT_ACTIONS = DEFAULT_REPORT_DIR / "ai_next_actions.md"
DEFAULT_CODEX_TASKS_DIR = DEFAULT_REPORT_DIR / "codex_tasks"
DEFAULT_BATCH_PLAN = DEFAULT_REPORT_DIR / "batch_plan.md"
DEFAULT_BATCH_PLAN_JSON = DEFAULT_REPORT_DIR / "batch_plan.json"
DEFAULT_REVIEW_FOLLOWUPS = DEFAULT_REPORT_DIR / "review_followups.md"
DEFAULT_REVIEW_FOLLOWUPS_DIR = DEFAULT_REPORT_DIR / "review_followups"
DEFAULT_DECISION_BRIEF = DEFAULT_REPORT_DIR / "decision_brief.md"
DEFAULT_PROMOTE_DRAFT = DEFAULT_REPORT_DIR / "promote_draft.md"
DEFAULT_GATE_STATUS = DEFAULT_REPORT_DIR / "gate_status.md"
DEFAULT_CLAIM_AUDIT = DEFAULT_REPORT_DIR / "claim_audit.md"
DEFAULT_PRIVACY_AUDIT = DEFAULT_REPORT_DIR / "privacy_audit.md"
DEFAULT_LOOP_STATE = DEFAULT_REPORT_DIR / "loop_state.json"
DEFAULT_AUTO_PASS = DEFAULT_REPORT_DIR / "auto_pass.md"
DEFAULT_DASHBOARD = DEFAULT_REPORT_DIR / "dashboard.md"
DEFAULT_MCP_CLIENT_CONFIG = DEFAULT_REPORT_DIR / "mcp_client_config.md"
DEFAULT_REVIEW_INGEST = DEFAULT_REPORT_DIR / "review_ingest.md"
DEFAULT_PR_HEALTH = DEFAULT_REPORT_DIR / "pr_health.md"
DEFAULT_SAFE_FIX = DEFAULT_REPORT_DIR / "safe_fix.md"
DEFAULT_APPROVAL_PACKET = DEFAULT_REPORT_DIR / "approval_packet.md"
DEFAULT_QUEUE_PLAN_PATCH = DEFAULT_REPORT_DIR / "queue_plan_patch.diff"
DEFAULT_PR_BODY = DEFAULT_REPORT_DIR / "pr_body.md"
DEFAULT_REVIEW_PLAN = DEFAULT_REPORT_DIR / "review_plan.md"
DEFAULT_STALE_REPORTS = DEFAULT_REPORT_DIR / "stale_reports.md"
DEFAULT_CONTEXT_PACK = DEFAULT_REPORT_DIR / "context_pack.md"
DEFAULT_ARCHITECTURE_BRIEF = DEFAULT_REPORT_DIR / "architecture_brief.md"
DEFAULT_SHIP_SIMULATION = DEFAULT_REPORT_DIR / "ship_simulation.md"
DEFAULT_GATE_BRIEF = DEFAULT_REPORT_DIR / "gate_brief.md"
DEFAULT_MANIFEST = DEFAULT_REPORT_DIR / "manifest.json"
DEFAULT_PR_BODY_CHECK = DEFAULT_REPORT_DIR / "pr_body_check.md"
DEFAULT_CI_INGEST = DEFAULT_REPORT_DIR / "ci_ingest.md"
DEFAULT_CI_FOLLOWUPS_DIR = DEFAULT_REPORT_DIR / "ci_followups"
DEFAULT_STACKED_RISK = DEFAULT_REPORT_DIR / "stacked_risk.md"
DEFAULT_PATCH_PROPOSAL = DEFAULT_REPORT_DIR / "patch_proposal.diff"
DEFAULT_ADR_RESERVATION = DEFAULT_REPORT_DIR / "adr_reservation.md"
DEFAULT_ADR_DRAFT = DEFAULT_REPORT_DIR / "adr_draft.md"
DEFAULT_DASHBOARD_HTML = DEFAULT_REPORT_DIR / "dashboard.html"
DEFAULT_SHIP_COMMANDS = DEFAULT_REPORT_DIR / "ship_commands.md"
DEFAULT_APPLY_QUEUE_PLAN = DEFAULT_REPORT_DIR / "apply_queue_plan.md"
DEFAULT_REVIEW_THREADS = DEFAULT_REPORT_DIR / "review_threads.md"
DEFAULT_CI_SUMMARY = DEFAULT_REPORT_DIR / "ci_summary.md"
DEFAULT_READINESS_SCORE = DEFAULT_REPORT_DIR / "readiness_score.md"
DEFAULT_BRANCH_ISSUE_HYGIENE = DEFAULT_REPORT_DIR / "branch_issue_hygiene.md"
DEFAULT_INTEGRATION_PACK = DEFAULT_REPORT_DIR / "integration_pack.md"
DEFAULT_SCHEDULE_CONFIG = DEFAULT_REPORT_DIR / "schedule_config.md"
DEFAULT_VALIDATION_HISTORY = DEFAULT_REPORT_DIR / "validation_history.jsonl"
DEFAULT_VALIDATION_HISTORY_REPORT = DEFAULT_REPORT_DIR / "validation_history.md"
DEFAULT_PRIVACY_REGRESSION = DEFAULT_REPORT_DIR / "privacy_regression.md"
DEFAULT_CLAIM_POLICY = DEFAULT_REPORT_DIR / "claim_policy.md"
DEFAULT_ARCHITECTURE_DECISION = DEFAULT_REPORT_DIR / "architecture_decision.md"
DEFAULT_WORKSET_RECOMMENDATION = DEFAULT_REPORT_DIR / "workset_recommendation.md"
DEFAULT_DEPENDENCY_GRAPH = DEFAULT_REPORT_DIR / "dependency_graph.md"
DEFAULT_AUTOMATION_COVERAGE = DEFAULT_REPORT_DIR / "automation_coverage.md"
DEFAULT_HUMAN_GATED_EXEC = DEFAULT_REPORT_DIR / "human_gated_exec.md"
DEFAULT_AUTO_SHIP_PLAN = DEFAULT_REPORT_DIR / "auto_ship_plan.md"
DEFAULT_AUTO_SHIP_PREPARE = DEFAULT_REPORT_DIR / "auto_ship_prepare.md"
DEFAULT_DRAFT_TASK_ID = "T-2026-0000"
QUEUE_PATH = Path("tasks/queue.md")
PLAN_DIR = Path("docs/plans")

GH_PR_JSON_FIELDS = (
    "number",
    "title",
    "url",
    "headRefName",
    "baseRefName",
    "isDraft",
    "reviewDecision",
    "mergeStateStatus",
    "statusCheckRollup",
    "labels",
    "updatedAt",
)
GH_PR_BODY_FIELD = "body"

REQUIRED_READS = (
    "CLAUDE.md",
    "docs/operations/ai-engineering-operating-system.md",
    "docs/operations/long-session-workflow.md",
    "tasks/queue.md",
    "docs/evaluation/surface-map.md",
    "docs/reviews/ai-review-checklists.md",
)

REQUIRED_HANDOFF_FIELDS = (
    "Role",
    "Lifecycle stage",
    "Branch / worktree",
    "Task",
    "Current status",
    "Files touched",
    "Commands run",
    "Results",
    "Validation evidence",
    "Blockers",
    "Open risks",
    "Next action",
    "Next safe command",
    "Reviewer focus",
)

EVAL_SURFACE_SIGNALS = (
    "eval/",
    "configs/eval/",
    "data/eval/",
    "reports/",
    "eval_summary.json",
    "benchmark_naive_rag",
    "real-eval",
    "real eval",
    "real100",
    "private aggregate",
    "public fixture",
    "synthetic benchmark",
    "performance claim",
)

FORBIDDEN_DYNAMIC_LABELS = {
    "raw question",
    "question",
    "raw answer",
    "answer",
    "raw evidence",
    "evidence",
    "doc_id",
    "doc id",
    "chunk_id",
    "chunk id",
    "filename",
    "file name",
}


@dataclass(frozen=True)
class TaskEntry:
    task_id: str
    title: str
    body: str
    status: str | None
    owner_role: str | None


@dataclass(frozen=True)
class HandoffReport:
    ok: bool
    source: str
    heading: str
    present_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    invalid_fields: tuple[str, ...]
    eval_surface_required: bool


@dataclass(frozen=True)
class SurfaceReport:
    surface: str
    confidence: str
    reviewer_type: str
    disallowed_claims: tuple[str, ...]
    matched_files: tuple[str, ...]
    additional_surfaces: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationRun:
    command: str
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class DraftTaskResult:
    queue_path: Path
    plan_path: Path
    queue_text: str
    plan_text: str


@dataclass(frozen=True)
class BriefSummary:
    path: Path
    index: int
    title: str
    classification: str
    source: str
    reason: str
    goal: str
    verification: str
    lane: str
    gate_reason: str


@dataclass(frozen=True)
class ReviewFinding:
    severity: str
    target: str
    summary: str
    reviewer_mode: str


@dataclass(frozen=True)
class DecisionOption:
    label: str
    recommended: bool
    severity: str
    reversibility: str
    tradeoffs: tuple[str, ...]
    evidence_needed: tuple[str, ...]
    next_safe_command: str
    manual_approval: str


@dataclass(frozen=True)
class DecisionPoint:
    gate: str
    title: str
    context: tuple[str, ...]
    options: tuple[DecisionOption, ...]


@dataclass(frozen=True)
class PrivacyFinding:
    path: str
    issue: str


@dataclass(frozen=True)
class ClaimFinding:
    issue: str
    severity: str
    reviewer: str


@dataclass(frozen=True)
class AutoPassReport:
    ok: bool
    decision: str
    confidence: str
    surface: SurfaceReport
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence: tuple[str, ...]
    next_safe_command: str


@dataclass(frozen=True)
class SafeFixChange:
    path: str
    action: str


@dataclass(frozen=True)
class SafeFixReport:
    applied: bool
    changes: tuple[SafeFixChange, ...]
    skipped: tuple[str, ...]


@dataclass(frozen=True)
class PRBodyFinding:
    severity: str
    issue: str
    remediation: str


@dataclass(frozen=True)
class CIFinding:
    lane: str
    summary: str
    source: str
    validation: str


@dataclass(frozen=True)
class ReviewThreadFinding:
    status: str
    path: str
    line: str
    reviewer_mode: str
    lane: str
    summary: str


@dataclass(frozen=True)
class ReadinessScore:
    score: int
    decision: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class AutoShipPlan:
    decision: str
    branch: str
    issue: str | None
    surface: SurfaceReport
    recommended_command: str
    dry_run_command: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence: tuple[str, ...]
    human_gates: tuple[str, ...]


@dataclass(frozen=True)
class AutoShipPrepareReport:
    result: str
    current_branch: str
    target_branch: str | None
    branch_command: str
    ship_arm_command: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence: tuple[str, ...]
    created: bool = False
    returncode: int | None = None


@dataclass(frozen=True)
class HumanGatedExecPlan:
    action: str
    command: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    dry_run: bool
    executed: bool
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""


def _repo_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalize_field(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", label.lower())


def _field_map(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in FIELD_RE.finditer(text):
        label = match.group("label").strip()
        value = match.group("value").strip()
        fields[_normalize_field(label)] = value
    return fields


def _task_public_fields(body: str) -> dict[str, str]:
    fields = {}
    for match in FIELD_RE.finditer(body):
        label = match.group("label").strip()
        if label.lower() in FORBIDDEN_DYNAMIC_LABELS:
            continue
        if label in {"Title", "Status", "Owner role"}:
            fields[label] = _sanitize_dynamic_text(match.group("value").strip())
    return fields


def _sanitize_dynamic_text(text: str) -> str:
    redacted = ABSOLUTE_LOCAL_PATH_RE.sub("[redacted-local-path]", text)
    return PRIVATE_INLINE_VALUE_RE.sub(
        lambda match: f"{match.group('label')}: [redacted-private-value]",
        redacted,
    )


def _sanitize_inline_text(text: str) -> str:
    redacted = _sanitize_dynamic_text(text)
    redacted = redacted.replace("```", "'''")
    redacted = re.sub(
        r"\b(?:review instructions|output format|system|developer|user|instructions)\s*:",
        "[redacted-instruction-label]:",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(r"[\r\n\t]+", " ", redacted)
    return re.sub(r"\s{2,}", " ", redacted).strip()


def _sanitize_command_text(text: str) -> str:
    redacted = _sanitize_dynamic_text(text)
    return PRIVATE_FLAG_VALUE_RE.sub(
        lambda match: f"{match.group('flag')}[redacted-private-value]",
        redacted,
    )


def _normalize_changed_file(path: str, *, repo_root: Path = ROOT_DIR) -> str:
    raw = path.strip().strip("`")
    if not raw:
        return ""
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            return "[redacted-local-path]"
    normalized = raw[2:] if raw.startswith("./") else raw
    try:
        return (repo_root / normalized).resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return "[redacted-local-path]"


def _privacy_sensitive_path(path: str) -> bool:
    lowered = path.lower()
    if lowered.startswith(
        (
            "reports/real100/",
            "reports/private",
            "data/private/",
            "data/files/",
            "data/files_kordoc/",
            "data/index/real",
        )
    ):
        return True
    return bool(re.search(r"(^|[/_.-])(doc[_-]?id|chunk[_-]?id)([/_.-]|$)", lowered))


def _display_path(path: str, *, repo_root: Path = ROOT_DIR) -> str:
    normalized = _normalize_changed_file(path, repo_root=repo_root)
    if normalized == "[redacted-local-path]":
        return normalized
    if normalized.startswith("reports/real100/"):
        return "reports/real100/[redacted-private-artifact]"
    if normalized.startswith("reports/private"):
        return "reports/[redacted-private-artifact]"
    if normalized.startswith("data/index/real"):
        return "data/index/[redacted-private-index]"
    if normalized.startswith(("data/private/", "data/files/", "data/files_kordoc/")):
        return "data/[redacted-private-input]"
    if _privacy_sensitive_path(normalized):
        return "[redacted-private-path]"
    return _sanitize_dynamic_text(normalized)


def _extract_validation_commands(task: TaskEntry) -> list[str]:
    commands: list[str] = []
    section = _section_text(task.body, "Validation Commands")
    for fenced in FENCED_BASH_RE.finditer(section):
        for line in fenced.group("body").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                commands.append(_sanitize_command_text(stripped))
    return commands


def _section_text(markdown: str, heading: str) -> str:
    pattern = re.compile(
        rf"^###\s+{re.escape(heading)}\s*$|^##\s+{re.escape(heading)}\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(markdown)
    if not match:
        return ""
    rest = markdown[match.end() :]
    next_heading = re.search(r"^#{2,3}\s+", rest, re.MULTILINE)
    return rest[: next_heading.start()] if next_heading else rest


def parse_task_entries(queue_text: str) -> list[TaskEntry]:
    matches = list(TASK_HEADING_RE.finditer(queue_text))
    entries: list[TaskEntry] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(queue_text)
        body = queue_text[start:end].strip()
        fields = _task_public_fields(body)
        entries.append(
            TaskEntry(
                task_id=match.group("id"),
                title=fields.get("Title") or match.group("title").strip(),
                body=body,
                status=fields.get("Status"),
                owner_role=fields.get("Owner role"),
            )
        )
    return entries


def load_task(task_id: str, repo_root: Path = ROOT_DIR) -> TaskEntry:
    if not TASK_ID_RE.fullmatch(task_id):
        raise ValueError(f"invalid task id: {task_id}")
    queue_path = repo_root / QUEUE_PATH
    queue_text = _read_text(queue_path)
    for entry in parse_task_entries(queue_text):
        if entry.task_id == task_id:
            return entry
    raise ValueError(f"task {task_id} not found in {_repo_path(queue_path, repo_root)}")


def find_plan_path(task: TaskEntry, repo_root: Path = ROOT_DIR) -> Path | None:
    body_match = re.search(r"\((?P<path>\.\./docs/plans/[^)]+|docs/plans/[^)]+)\)", task.body)
    if body_match:
        raw = body_match.group("path")
        rel = raw[3:] if raw.startswith("../") else raw
        candidate = repo_root / rel
        if candidate.exists():
            return candidate
    plan_dir = repo_root / PLAN_DIR
    candidates = sorted(plan_dir.glob(f"*{task.task_id}*.md")) if plan_dir.is_dir() else []
    return candidates[0] if candidates else None


def render_prompt(
    task_id: str,
    *,
    role: str = "Implementer",
    plan_path: Path | None = None,
    repo_root: Path = ROOT_DIR,
) -> str:
    task = load_task(task_id, repo_root)
    resolved_plan = plan_path or find_plan_path(task, repo_root)
    validation_commands = _extract_validation_commands(task)
    plan_display = _display_path(_repo_path(resolved_plan, repo_root), repo_root=repo_root) if resolved_plan else "N/A"
    validation_block = (
        "\n".join(f"- {cmd}" for cmd in validation_commands)
        if validation_commands
        else "- Derive focused validation from changed files; do not claim it was run."
    )
    required_reads = "\n".join(f"- {path}" for path in REQUIRED_READS)
    text = f"""# BidMate-DocAgent Codex Session Prompt

Role: {_sanitize_inline_text(role)}
Operating mode: Actual development mode for BidMate-DocAgent.
Task: {task.task_id} - {_sanitize_inline_text(task.title)}
Plan: {plan_display}

BidMate operating mode:
- Stay within the existing task queue, plan doc, review checklist, and eval surface map.
- Do not create a new governance system or replace the operating model.
- Do not auto-merge, auto-push, auto-close PRs, delete branches, or force-push.
- Human approval is required for merge/close/push/delete/force-push, benchmark claims,
  private real-eval decisions, and architecture tradeoff decisions.

Session-time-maxing loop:
1. Inspect the existing repo workflow and relevant scripts.
2. Identify the smallest useful automation surface inside the task scope.
3. Implement the scoped change.
4. Add focused tests.
5. Run focused validation and fix in-scope failures.
6. Stop only when the scoped MVP is implemented and validated, or when blocked by
   missing repo evidence or human approval.

Required reads:
{required_reads}
- This task entry in tasks/queue.md
{"- " + plan_display if resolved_plan else "- Plan doc: N/A; create one only if project rules require it."}

Eval surface reminder:
- Classify public fixture smoke, public synthetic benchmark, private real-eval, and
  benchmark-reporting separately before making any evaluation claim.
- Public smoke is wiring/regression evidence, not real-world model quality.
- Synthetic benchmark evidence must not be described as real RFP performance.
- Private real-eval evidence must stay aggregate-only and public-safe.

Validation expectations:
{validation_block}
- Always include git diff --check before final handoff.
- Report only commands actually run; suggestions are not evidence.

Handoff requirement:
- Before stopping, leave or verify a Session Handoff / Workstream State block with
  Role, Lifecycle stage, Branch / worktree, Task, Current status, Files touched,
  Commands run, Results, Validation evidence, Blockers, Open risks, Next action,
  Next safe command, and Reviewer focus.
- Include Eval surface when eval, benchmark, metrics, reports, or performance/private
  claims are touched.
- Do not expose private raw question, answer, evidence, doc_id, chunk_id, filenames,
  exact local paths, or raw case text.

Final response format:
1. Implementation summary
2. Commands added or changed
3. Files changed
4. Tests added
5. Validation commands run
6. Validation result
7. Example usage
8. Remaining risks
9. Follow-up automation steps
10. Commands intentionally left unimplemented, if any
"""
    return _sanitize_dynamic_text(text).rstrip() + "\n"


def _load_plan_text(plan_path: Path | None, repo_root: Path) -> tuple[str, str] | None:
    if plan_path is None:
        return None
    path = plan_path if plan_path.is_absolute() else repo_root / plan_path
    if not path.exists():
        raise ValueError(f"plan not found: {path}")
    return _display_path(_repo_path(path, repo_root), repo_root=repo_root), _read_text(path)


def _latest_handoff_block(sources: Sequence[tuple[str, str]]) -> tuple[str, str, str] | None:
    latest: tuple[str, str, str] | None = None
    for source, text in sources:
        matches = list(HANDOFF_HEADING_RE.finditer(text))
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            latest = (source, match.group("title").strip(), text[start:end])
    return latest


def _needs_eval_surface(*texts: str) -> bool:
    haystack = "\n".join(texts).lower()
    for match in re.finditer(r"surface:\s*([^\n]+)", haystack):
        value = match.group(1).strip().strip(".")
        if value and value not in {"none", "n/a", "no data touched"}:
            return True
    return any(signal in haystack for signal in EVAL_SURFACE_SIGNALS)


def check_handoff(
    task_id: str,
    *,
    plan_path: Path | None = None,
    changed_files: Sequence[str] = (),
    repo_root: Path = ROOT_DIR,
) -> HandoffReport:
    task = load_task(task_id, repo_root)
    resolved_plan = plan_path or find_plan_path(task, repo_root)
    sources: list[tuple[str, str]] = [(f"{QUEUE_PATH}::{task.task_id}", task.body)]
    loaded_plan = _load_plan_text(resolved_plan, repo_root)
    if loaded_plan is not None:
        sources.append(loaded_plan)
    latest = _latest_handoff_block(sources)
    if latest is None:
        required = list(REQUIRED_HANDOFF_FIELDS)
        if _needs_eval_surface(task.body, loaded_plan[1] if loaded_plan else "", "\n".join(changed_files)):
            required.append("Eval surface")
        return HandoffReport(False, "(none)", "(none)", (), tuple(required), (), "Eval surface" in required)

    source, heading, block = latest
    fields = _field_map(block)
    required = list(REQUIRED_HANDOFF_FIELDS)
    eval_required = _needs_eval_surface(task.body, loaded_plan[1] if loaded_plan else "", "\n".join(changed_files))
    if eval_required:
        required.append("Eval surface")

    missing: list[str] = []
    present: list[str] = []
    invalid: list[str] = []
    current_status = fields.get(_normalize_field("Current status"), "")
    terminal = _is_terminal_status(current_status)
    for label in required:
        value = fields.get(_normalize_field(label), "")
        if value:
            present.append(label)
            if not _handoff_field_value_is_valid(label, value, terminal=terminal):
                invalid.append(label)
        else:
            missing.append(label)
    return HandoffReport(
        ok=not missing and not invalid,
        source=source,
        heading=heading,
        present_fields=tuple(present),
        missing_fields=tuple(missing),
        invalid_fields=tuple(invalid),
        eval_surface_required=eval_required,
    )


def _is_terminal_status(value: str) -> bool:
    lowered = value.strip().lower()
    return any(token in lowered for token in ("done", "merged", "complete", "completed"))


def _handoff_field_value_is_valid(label: str, value: str, *, terminal: bool) -> bool:
    lowered = value.strip().lower().strip(".")
    weak_evidence = {
        "n/a",
        "na",
        "none",
        "not run",
        "not yet",
        "not executed",
        "not validated",
        "suggested only",
        "todo",
        "tbd",
        "unknown",
    }
    if label == "Eval surface":
        return lowered not in {"n/a", "na", "none", "no data touched", "unknown", "tbd"}
    if label in {"Commands run", "Results", "Validation evidence"}:
        return lowered not in weak_evidence
    if label == "Next safe command" and not terminal:
        return lowered not in {"n/a", "na", "none", "not applicable", "unknown", "tbd", "todo"}
    return True


def render_handoff_report(report: HandoffReport) -> str:
    lines = [
        "Handoff check",
        f"- source: {_sanitize_dynamic_text(report.source)}",
        f"- heading: {_sanitize_dynamic_text(report.heading)}",
        f"- eval surface required: {'yes' if report.eval_surface_required else 'no'}",
        f"- present fields: {len(report.present_fields)}",
    ]
    if report.ok:
        lines.append("- result: pass")
    else:
        lines.append("- result: fail")
        if report.missing_fields:
            lines.append("- missing fields:")
            lines.extend(f"  - {field}" for field in report.missing_fields)
        if report.invalid_fields:
            lines.append("- invalid fields:")
            lines.extend(f"  - {field}" for field in report.invalid_fields)
    return "\n".join(lines) + "\n"


def _changed_files_from_git(repo_root: Path = ROOT_DIR) -> list[str]:
    try:
        status = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain=v1"],
            capture_output=True,
            check=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("could not read changed files from git status") from exc
    files: list[str] = []
    for line in status.splitlines():
        if not line:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            files.append(path)
    return sorted(set(files))


def _changed_files_from_pr(pr: str, repo_root: Path = ROOT_DIR) -> list[str]:
    safe_pr = _validate_pr_selector(pr)
    try:
        result = subprocess.run(
            ["gh", "pr", "diff", safe_pr, "--name-only"],
            cwd=repo_root,
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"could not read changed files from PR {pr}") from exc
    return sorted(
        {
            normalized
            for line in result.stdout.splitlines()
            if (normalized := _normalize_changed_file(line, repo_root=repo_root))
        }
    )


def _validate_pr_selector(pr: str) -> str:
    if not re.fullmatch(r"\d{1,10}", str(pr)):
        raise ValueError("PR selector must be a numeric PR number")
    return str(pr)


def _read_changed_files(
    path: Path | None,
    *,
    from_git: bool,
    pr: str | None = None,
    repo_root: Path,
) -> list[str]:
    files: list[str] = []
    if path is not None:
        text = _read_text(path)
        for raw in re.split(r"[\n,]", text):
            item = _normalize_changed_file(raw, repo_root=repo_root)
            if item:
                files.append(item)
    if pr and path is None:
        files.extend(_changed_files_from_pr(pr, repo_root))
    if from_git:
        files.extend(_changed_files_from_git(repo_root))
    return sorted(set(files))


def _path_matches(path: str, *prefixes_or_names: str) -> bool:
    return any(path == item or path.startswith(item) for item in prefixes_or_names)


def _surface_for_path(path: str) -> tuple[str, ...]:
    p = _normalize_changed_file(path).strip()
    p = p[2:] if p.startswith("./") else p
    if not p:
        return ("unknown",)
    if p == "reports/eval_summary.json":
        return ("public-fixture-smoke", "benchmark-reporting")
    if p.startswith("docs/adr/"):
        return ("governance-adr",)
    if p.startswith(".github/workflows/") or p in {
        ".claude/settings.json",
        ".gitignore",
        "pyproject.toml",
        "Makefile",
        "scripts/_governance.py",
        "scripts/agent_loop.py",
        "scripts/agent_loop_mcp.py",
        "tests/test_agent_loop.py",
        "tests/test_agent_loop_mcp.py",
        "tests/test_agent_loop_claude_integration.py",
        "scripts/ai_next_actions.py",
        "tests/test_ai_next_actions.py",
        "tests/test_hook_telemetry.py",
    }:
        return ("ci-validation",)
    if p.startswith(".claude/commands/") or p.startswith("scripts/claude-hooks/"):
        return ("ci-validation",)
    if p.startswith("reports/real100/") or p.startswith("reports/private"):
        return ("private-real-eval", "privacy-sensitive-artifact", "benchmark-reporting")
    if p in {"eval/real_config.local.yaml", "configs/eval/private_real_eval.local.yaml"}:
        return ("private-real-eval", "privacy-sensitive-artifact")
    if p.startswith(("data/index/real100", "data/private/", "data/files/", "data/files_kordoc/")):
        return ("private-real-eval", "privacy-sensitive-artifact")
    if p in {"scripts/run_real_eval_delta.py"}:
        return ("private-real-eval", "benchmark-reporting")
    if p.startswith("configs/eval/benchmark") or p.startswith("data/eval/benchmark/"):
        return ("public-synthetic-benchmark",)
    if p in {"eval/naive_rag/benchmark.py", "tests/test_naive_rag_benchmark_v1.py"}:
        return ("public-synthetic-benchmark",)
    if p.startswith("eval/fixtures/smoke_rfp/") or p == "eval/config.yaml":
        return ("public-fixture-smoke",)
    if p.startswith("eval/") or p.startswith("configs/eval/") or p in {
        "scripts/compare_eval.py",
        "scripts/render_difficulty_profile.py",
        "scripts/render_failure_distribution.py",
        "scripts/render_failure_slices.py",
        "scripts/measure_variance.py",
    }:
        return ("eval-harness", "benchmark-reporting")
    if p.startswith("reports/"):
        return ("benchmark-reporting",)
    if is_load_bearing(p) or _path_matches(p, "api/"):
        return ("product-runtime",)
    if p.startswith("docs/evaluation/") or p.startswith("docs/eval/"):
        return ("benchmark-reporting", "docs-only")
    if p.startswith("docs/") and p.endswith(".md"):
        return ("docs-only",)
    if p.endswith(".md"):
        return ("docs-only",)
    return ("unknown",)


SURFACE_PRIORITY = {
    "privacy-sensitive-artifact": 0,
    "private-real-eval": 1,
    "public-synthetic-benchmark": 2,
    "eval-harness": 3,
    "public-fixture-smoke": 4,
    "benchmark-reporting": 5,
    "product-runtime": 6,
    "governance-adr": 7,
    "ci-validation": 8,
    "docs-only": 9,
    "unknown": 99,
}

DISALLOWED_CLAIMS = {
    "docs-only": (
        "Do not claim behavior, benchmark, or private real-eval impact from docs alone.",
    ),
    "governance-adr": (
        "Do not claim implementation behavior changed unless code and tests changed too.",
    ),
    "product-runtime": (
        "Do not claim quality, retrieval, latency, or performance improvement without eval surface evidence.",
        "Do not expose private raw data or exact local paths.",
    ),
    "eval-harness": (
        "Do not treat harness wiring or smoke output as real-world RFP quality.",
        "Do not compare incompatible dataset/config/index provenance.",
    ),
    "public-fixture-smoke": (
        "Do not claim real-world model quality or production performance.",
    ),
    "public-synthetic-benchmark": (
        "Do not claim real RFP performance, customer quality, or private real-eval success.",
    ),
    "private-real-eval": (
        "Do not expose raw question, answer, evidence, filename, exact local path, doc_id, or chunk_id.",
        "Do not make headline metrics without dataset/config/index/provenance.",
    ),
    "benchmark-reporting": (
        "Do not compare metrics across surfaces without matching dataset/config/index/provenance.",
    ),
    "privacy-sensitive-artifact": (
        "Do not include raw private content, raw IDs, exact local paths, or per-case evidence text.",
    ),
    "ci-validation": (
        "Do not interpret CI green as private real-eval or benchmark performance evidence.",
    ),
    "unknown": (
        "Do not make benchmark, performance, or private-data claims until a human classifies the surface.",
    ),
}


def classify_changed_files(changed_files: Sequence[str]) -> SurfaceReport:
    normalized_files = sorted(
        {
            normalized
            for path in changed_files
            if (normalized := _normalize_changed_file(path))
        }
    )
    if not normalized_files:
        surface = "unknown"
        return SurfaceReport(
            surface=surface,
            confidence="low",
            reviewer_type="Human reviewer",
            disallowed_claims=DISALLOWED_CLAIMS[surface],
            matched_files=(),
        )
    surfaces: list[str] = []
    for path in normalized_files:
        surfaces.extend(_surface_for_path(path))
    unique = sorted(set(surfaces), key=lambda item: SURFACE_PRIORITY.get(item, 99))
    surface = unique[0] if unique else "unknown"
    unknown_count = surfaces.count("unknown")
    confidence = "high"
    if unknown_count:
        confidence = "low" if unknown_count == len(changed_files) else "medium"
    elif len(set(unique) - {"docs-only"}) > 1:
        confidence = "medium"

    if surface in {"private-real-eval", "privacy-sensitive-artifact"}:
        reviewer = "Benchmark Auditor + Privacy Auditor"
    elif surface in {
        "eval-harness",
        "public-fixture-smoke",
        "public-synthetic-benchmark",
        "benchmark-reporting",
    }:
        reviewer = "Benchmark Auditor"
    elif surface in {"product-runtime", "governance-adr"}:
        reviewer = "Deep Reviewer"
    elif surface == "ci-validation":
        reviewer = "Maintainer / CI Reviewer"
    elif surface == "docs-only":
        reviewer = "Documentation / Governance Reviewer"
    else:
        reviewer = "Human reviewer"

    return SurfaceReport(
        surface=surface,
        confidence=confidence,
        reviewer_type=reviewer,
        disallowed_claims=tuple(
            _dedupe_preserve_order(
                claim for item in unique for claim in DISALLOWED_CLAIMS[item]
            )
        ),
        matched_files=tuple(normalized_files),
        additional_surfaces=tuple(item for item in unique if item != surface),
    )


def render_surface_report(report: SurfaceReport) -> str:
    lines = [
        f"surface: {report.surface}",
        f"confidence: {report.confidence}",
        f"required reviewer type: {report.reviewer_type}",
    ]
    if report.additional_surfaces:
        lines.append("additional surfaces: " + ", ".join(report.additional_surfaces))
    lines.append("disallowed claims:")
    lines.extend(f"- {claim}" for claim in report.disallowed_claims)
    if report.matched_files:
        lines.append("matched files:")
        lines.extend(f"- {_display_path(path)}" for path in report.matched_files)
    return "\n".join(lines) + "\n"


def _has_any(files: Sequence[str], predicate) -> bool:  # type: ignore[no-untyped-def]
    return any(predicate(path) for path in files)


def suggest_validation_commands(changed_files: Sequence[str]) -> list[str]:
    files = sorted(
        {
            normalized
            for path in changed_files
            if (normalized := _normalize_changed_file(path))
        }
    )
    commands: list[str] = []
    py_files = [path for path in files if path.endswith(".py") and not _privacy_sensitive_path(path)]
    if py_files:
        commands.append("python3 -m py_compile " + " ".join(py_files))
    test_files = [
        path
        for path in files
        if path.startswith("tests/test_") and path.endswith(".py") and not _privacy_sensitive_path(path)
    ]
    if test_files:
        commands.append("python3 -m pytest " + " ".join(test_files) + " -q")

    def touched(*targets: str) -> bool:
        return any(path in targets for path in files)

    if touched(
        "tests/test_naive_rag_benchmark_v1.py",
        "eval/naive_rag/benchmark.py",
        "configs/eval/benchmark_naive_rag_v1.yaml",
    ) or _has_any(files, lambda p: p.startswith("data/eval/benchmark/")):
        commands.append("python3 -m pytest tests/test_naive_rag_benchmark_v1.py -q")
    if touched("scripts/compare_eval.py"):
        commands.append("python3 -m pytest tests/test_compare_eval_regression_gate.py -q")
    if touched("scripts/run_real_eval_delta.py"):
        commands.append("python3 -m pytest tests/test_run_real_eval_delta.py -q")
    if touched("scripts/render_difficulty_profile.py"):
        commands.append("python3 -m pytest tests/test_render_difficulty_profile.py -q")
    if _has_any(files, lambda p: p.startswith("docs/") and p.endswith(".md")):
        commands.append("python3 scripts/check_doc_links.py --check-all")
    if _has_any(files, lambda p: p.startswith("docs/adr/") and p.endswith(".md")):
        commands.append(
            "python3 -m pytest tests/test_governance_adr_numbers.py "
            "tests/test_governance_adr_readme_parity.py -q"
        )
    surface = classify_changed_files(files)
    privacy_related = surface.surface in {"private-real-eval", "privacy-sensitive-artifact"} or (
        "privacy-sensitive-artifact" in surface.additional_surfaces
        or surface.surface == "private-real-eval"
        or "private-real-eval" in surface.additional_surfaces
    )
    if privacy_related:
        commands.append("python3 scripts/_governance.py --check-eval-privacy")
    commands.append("git diff --check")
    return _dedupe_preserve_order(commands)


def _dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def render_validation_suggestions(commands: Sequence[str]) -> str:
    lines = ["Suggested validation commands:", ""]
    lines.extend(
        f"{index}. {_sanitize_command_text(command)}"
        for index, command in enumerate(commands, start=1)
    )
    lines.append("")
    lines.append("These are suggestions only; this command did not run them.")
    return "\n".join(lines) + "\n"


def _validation_command_allowed(command: str) -> bool:
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if parts == ["git", "diff", "--check"]:
        return True
    if parts == ["python3", "scripts/check_doc_links.py", "--check-all"]:
        return True
    if parts == ["python3", "scripts/_governance.py", "--check-eval-privacy"]:
        return True
    if parts[:3] == ["python3", "-m", "py_compile"] and len(parts) > 3:
        return all(
            arg.endswith(".py") and not _privacy_sensitive_path(arg)
            for arg in parts[3:]
        )
    if parts[:3] == ["python3", "-m", "pytest"] and len(parts) > 4:
        test_args = [arg for arg in parts[3:] if arg != "-q"]
        return bool(test_args) and all(
            arg.startswith("tests/test_") and arg.endswith(".py") and not _privacy_sensitive_path(arg)
            for arg in test_args
        )
    return False


def run_validation_commands(
    changed_files: Sequence[str],
    *,
    keep_going: bool = False,
) -> tuple[int, list[ValidationRun]]:
    runs: list[ValidationRun] = []
    final_rc = 0
    for command in suggest_validation_commands(changed_files):
        if not _validation_command_allowed(command):
            runs.append(
                ValidationRun(
                    command=command,
                    returncode=2,
                    stdout="",
                    stderr="agent-loop: refused non-allowlisted validation command",
                )
            )
            final_rc = 2
            if not keep_going:
                break
            continue
        result = subprocess.run(
            shlex.split(command),
            capture_output=True,
            text=True,
            check=False,
        )
        run = ValidationRun(
            command=command,
            returncode=result.returncode,
            stdout=_sanitize_dynamic_text(result.stdout or ""),
            stderr=_sanitize_dynamic_text(result.stderr or ""),
        )
        runs.append(run)
        if result.returncode != 0:
            final_rc = result.returncode
            if not keep_going:
                break
    return final_rc, runs


def render_validation_run_report(runs: Sequence[ValidationRun]) -> str:
    lines = ["Validation run:", ""]
    for index, run in enumerate(runs, start=1):
        lines.append(f"{index}. {_sanitize_command_text(run.command)}")
        lines.append(f"   rc: {run.returncode}")
        if run.stdout.strip():
            lines.append("   stdout:")
            lines.extend(f"     {line}" for line in run.stdout.rstrip().splitlines())
        if run.stderr.strip():
            lines.append("   stderr:")
            lines.extend(f"     {line}" for line in run.stderr.rstrip().splitlines())
    if not runs:
        lines.append("No validation commands selected.")
    return "\n".join(lines) + "\n"


def _review_modes(changed_files: Sequence[str]) -> list[str]:
    report = classify_changed_files(changed_files)
    modes = ["Normal Code Review", "Adversarial Review"]
    surfaces = {report.surface, *report.additional_surfaces}
    if surfaces & {
        "eval-harness",
        "public-fixture-smoke",
        "public-synthetic-benchmark",
        "private-real-eval",
        "benchmark-reporting",
        "privacy-sensitive-artifact",
    }:
        modes.extend(
            [
                "Benchmark Validity Audit",
                "eval surface classification",
                "allowed/disallowed claim audit",
                "privacy boundary check",
            ]
        )
    if any(is_load_bearing(path) or path.startswith("docs/adr/") for path in changed_files):
        modes.append("Deep Review")
    return _dedupe_preserve_order(modes)


def render_review_prompt(
    task_id: str,
    *,
    pr: str | None = None,
    branch: str | None = None,
    changed_files: Sequence[str] | None = None,
    repo_root: Path = ROOT_DIR,
) -> str:
    task = load_task(task_id, repo_root)
    plan = find_plan_path(task, repo_root)
    files = sorted(changed_files or _changed_files_from_git(repo_root))
    surface = classify_changed_files(files)
    modes = _review_modes(files)
    file_block = "\n".join(f"- {_display_path(path)}" for path in files) if files else "- Not discovered"
    mode_block = "\n".join(f"- {mode}" for mode in modes)
    safe_pr = _validate_pr_selector(pr) if pr else None
    ref_lines = []
    if safe_pr:
        ref_lines.append(f"- PR: {safe_pr}")
    if branch:
        ref_lines.append(f"- Branch: {_sanitize_inline_text(branch)}")
    refs = "\n".join(ref_lines) if ref_lines else "- PR/Branch: N/A"
    plan_display = _display_path(_repo_path(plan, repo_root), repo_root=repo_root) if plan else "N/A"
    text = f"""# BidMate-DocAgent Adversarial Review Prompt

Role: Reviewer / Adversarial Reviewer
Task: {task.task_id} - {_sanitize_inline_text(task.title)}
Plan: {plan_display}
{refs}

Changed files:
{file_block}

Required review modes:
{mode_block}

Surface classification:
- surface: {surface.surface}
- confidence: {surface.confidence}
- reviewer type: {surface.reviewer_type}

Review instructions:
- Start with findings, ordered by severity, with file/line references when possible.
- Check task/plan scope, existing contracts, tests, validation evidence, and claim wording.
- Treat generated artifacts as local evidence, not source-of-truth, unless commit policy allows them.
- If eval, benchmark, metrics, reports, or configs are touched, perform Benchmark Validity Audit:
  classify the eval surface, verify dataset/config/index/provenance, audit allowed/disallowed
  claims, and check the privacy boundary.
- If load-bearing paths or ADRs are touched, perform Deep Review for architecture drift,
  hidden coupling, baseline/schema/eval split changes, and missing ADR/test evidence.
- Do not approve benchmark/performance/private real-eval claims without human-reviewable
  provenance and aggregate-only evidence.

Disallowed claims to attack:
{chr(10).join(f"- {claim}" for claim in surface.disallowed_claims)}

Output format:
## Findings
- [blocking] <file/path>:<line> - issue, impact, required fix.
- [non-blocking] <file/path>:<line> - follow-up recommendation.

## Evidence Checked
- Task:
- Plan:
- Commands:
- Eval surface:

## Verdict
Approve / Needs changes / Needs benchmark audit / Needs deep review
"""
    return _sanitize_dynamic_text(text).rstrip() + "\n"


def recommend_next_task(repo_root: Path = ROOT_DIR) -> str:
    queue_text = _read_text(repo_root / QUEUE_PATH)
    entries = parse_task_entries(queue_text)
    if not entries:
        raise ValueError("no task entries found in tasks/queue.md")
    ready = [entry for entry in entries if (entry.status or "").lower() == "ready"]
    backlog = [entry for entry in entries if (entry.status or "").lower() == "backlog"]
    candidates = ready or backlog
    if not candidates:
        raise ValueError("no ready or backlog task found; choose manually from tasks/queue.md")
    candidates = sorted(
        candidates,
        key=lambda item: (
            0 if _extract_validation_commands(item) else 1,
            0 if "Acceptance Criteria" in item.body else 1,
            item.task_id,
        ),
    )
    task = candidates[0]
    plan = find_plan_path(task, repo_root)
    validation = _extract_validation_commands(task)
    files = [line.strip("- ` ") for line in re.findall(r"`([^`]+)`", task.body)]
    surface = classify_changed_files(files)
    lines = [
        f"Recommended next task: {task.task_id} - {task.title}",
        f"- status: {task.status or 'unknown'}",
        f"- role: {task.owner_role or 'Implementer'}",
        f"- branch suggestion: <type>/issue-<N>-{task.task_id.lower()}",
        f"- plan required: {'yes' if plan else 'evaluate before implementation'}",
        f"- plan: {_display_path(_repo_path(plan, repo_root), repo_root=repo_root) if plan else 'N/A'}",
        f"- validation command: {validation[0] if validation else 'derive from changed files'}",
        f"- reviewer requirement: {surface.reviewer_type}",
    ]
    return "\n".join(lines) + "\n"


def render_status(
    *,
    task_id: str | None = None,
    changed_files: Sequence[str] = (),
    repo_root: Path = ROOT_DIR,
) -> str:
    lines = ["Agent-loop status", ""]
    if task_id:
        task = load_task(task_id, repo_root)
        plan = find_plan_path(task, repo_root)
        lines.extend(
            [
                f"- task: {task.task_id} - {_sanitize_dynamic_text(task.title)}",
                f"- status: {task.status or 'unknown'}",
                f"- owner role: {task.owner_role or 'unknown'}",
                f"- plan: {_display_path(_repo_path(plan, repo_root), repo_root=repo_root) if plan else 'N/A'}",
            ]
        )
        handoff = check_handoff(task_id, changed_files=changed_files, repo_root=repo_root)
        lines.append(f"- handoff: {'pass' if handoff.ok else 'fail'}")
        if handoff.missing_fields:
            lines.append("- handoff missing: " + ", ".join(handoff.missing_fields))
        if handoff.invalid_fields:
            lines.append("- handoff invalid: " + ", ".join(handoff.invalid_fields))
    else:
        lines.append(recommend_next_task(repo_root).rstrip())

    surface = classify_changed_files(changed_files)
    lines.extend(
        [
            "",
            "Surface:",
            render_surface_report(surface).rstrip(),
            "",
            render_validation_suggestions(suggest_validation_commands(changed_files)).rstrip(),
        ]
    )
    return "\n".join(lines) + "\n"


def render_preflight(
    *,
    task_id: str,
    changed_files: Sequence[str],
    write_prompts: bool = False,
    repo_root: Path = ROOT_DIR,
) -> tuple[int, str]:
    handoff = check_handoff(task_id, changed_files=changed_files, repo_root=repo_root)
    surface = classify_changed_files(changed_files)
    validation = suggest_validation_commands(changed_files)
    lines = [
        "Agent-loop preflight",
        "",
        "Handoff:",
        render_handoff_report(handoff).rstrip(),
        "",
        "Surface:",
        render_surface_report(surface).rstrip(),
        "",
        render_validation_suggestions(validation).rstrip(),
    ]
    if write_prompts:
        prompt = render_prompt(task_id, repo_root=repo_root)
        review = render_review_prompt(task_id, changed_files=changed_files, repo_root=repo_root)
        _write_or_stdout(prompt, DEFAULT_RENDER_PROMPT)
        _write_or_stdout(review, DEFAULT_REVIEW_PROMPT)
        lines.extend(
            [
                "",
                "Generated prompts:",
                f"- {_repo_path(DEFAULT_RENDER_PROMPT, repo_root)}",
                f"- {_repo_path(DEFAULT_REVIEW_PROMPT, repo_root)}",
            ]
        )
    return (0 if handoff.ok else 1), "\n".join(lines) + "\n"


def scan_pr_state(
    *,
    out: Path = DEFAULT_PR_STATE,
    state: str = "open",
    limit: int = 30,
    include_body: bool = False,
    repo_root: Path = ROOT_DIR,
) -> Path:
    if state not in {"open", "closed", "all"}:
        raise ValueError("--state must be one of: open, closed, all")
    if limit < 1 or limit > 100:
        raise ValueError("--limit must be between 1 and 100")
    if out == DEFAULT_PR_STATE:
        out = repo_root / "reports" / "agent_loop" / "pr_state.json"
    safe_out = _safe_output_path(out, repo_root=repo_root)
    fields = ",".join((*GH_PR_JSON_FIELDS, GH_PR_BODY_FIELD) if include_body else GH_PR_JSON_FIELDS)
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                state,
                "--limit",
                str(limit),
                "--json",
                fields,
            ],
            cwd=repo_root,
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("could not scan PR state with read-only gh pr list") from exc
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("gh pr list did not return valid JSON") from exc
    if not isinstance(payload, list):
        raise ValueError("gh pr list JSON must be an array")
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return safe_out


def run_next_from_prs(
    *,
    pr_json: Path = DEFAULT_PR_STATE,
    out_md: Path = DEFAULT_AI_NEXT_ACTIONS,
    tasks_dir: Path = DEFAULT_CODEX_TASKS_DIR,
    readiness_summaries: Sequence[Path] = (),
    readiness_reports: Sequence[Path] = (),
    real100_dir: Path | None = None,
    page_metadata_index_dir: Path | None = None,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, Path]:
    from scripts import ai_next_actions  # local import keeps the base CLI lightweight

    pr_path = _resolve_input_path(pr_json, repo_root=repo_root)
    if not pr_path.exists():
        raise ValueError("PR state JSON not found; run pr-scan first or pass --pr-json")
    if out_md == DEFAULT_AI_NEXT_ACTIONS:
        out_md = repo_root / "reports" / "agent_loop" / "ai_next_actions.md"
    if tasks_dir == DEFAULT_CODEX_TASKS_DIR:
        tasks_dir = repo_root / "reports" / "agent_loop" / "codex_tasks"
    safe_out_md = _safe_output_path(out_md, repo_root=repo_root)
    safe_tasks_dir = _safe_output_path(tasks_dir, repo_root=repo_root)

    items, sources, page_gate, private_delta_needed = ai_next_actions.build_plan(
        [_resolve_input_path(path, repo_root=repo_root) for path in readiness_summaries],
        [_resolve_input_path(path, repo_root=repo_root) for path in readiness_reports],
        pr_path,
        _resolve_input_path(real100_dir, repo_root=repo_root) if real100_dir is not None else None,
        _resolve_input_path(page_metadata_index_dir, repo_root=repo_root)
        if page_metadata_index_dir is not None
        else None,
    )
    safe_items = [_sanitize_work_item(ai_next_actions, item) for item in items]
    safe_sources = [_sanitize_source_state(ai_next_actions, source) for source in sources]
    markdown = ai_next_actions.render_summary_markdown(
        safe_items,
        safe_sources,
        page_gate=page_gate,
        private_delta_needed=private_delta_needed,
    )
    ai_next_actions._write_outputs(  # noqa: SLF001 - reuse the existing local writer
        safe_out_md,
        None,
        safe_tasks_dir,
        safe_items,
        _sanitize_dynamic_text(markdown),
        None,
    )
    return safe_out_md, safe_tasks_dir


def _sanitize_work_item(ai_next_actions, item):  # type: ignore[no-untyped-def]
    return ai_next_actions.WorkItem(
        classification=_sanitize_inline_text(item.classification),
        title=_sanitize_inline_text(item.title),
        reason=_sanitize_inline_text(item.reason),
        source=_sanitize_inline_text(item.source),
        slug=_slugify(item.slug),
        goal=_sanitize_dynamic_text(item.goal),
        expected_evidence=_sanitize_dynamic_text(item.expected_evidence),
        verification=_sanitize_command_text(item.verification),
    )


def _sanitize_source_state(ai_next_actions, source):  # type: ignore[no-untyped-def]
    return ai_next_actions.SourceState(
        kind=_sanitize_inline_text(source.kind),
        label=_sanitize_inline_text(source.label),
        unsafe=source.unsafe,
    )


def draft_task_from_brief(
    *,
    task_brief: Path | None = None,
    task_id: str = DEFAULT_DRAFT_TASK_ID,
    out_queue: Path = DEFAULT_QUEUE_DRAFT,
    out_plan: Path = DEFAULT_PLAN_DRAFT,
    repo_root: Path = ROOT_DIR,
) -> DraftTaskResult:
    if not TASK_ID_RE.fullmatch(task_id):
        raise ValueError("--task-id must match T-YYYY-NNNN")
    brief_path = _resolve_task_brief(task_brief, repo_root=repo_root)
    brief_text = _sanitize_dynamic_text(_read_text(brief_path))
    brief = _parse_task_brief(brief_text)
    queue_text, plan_text = _render_task_drafts(
        brief,
        task_id=task_id,
        brief_path=brief_path,
        repo_root=repo_root,
    )
    if out_queue == DEFAULT_QUEUE_DRAFT:
        out_queue = repo_root / "reports" / "agent_loop" / "queue_entry_draft.md"
    if out_plan == DEFAULT_PLAN_DRAFT:
        out_plan = repo_root / "reports" / "agent_loop" / "plan_draft.md"
    safe_queue = _safe_output_path(out_queue, repo_root=repo_root)
    safe_plan = _safe_output_path(out_plan, repo_root=repo_root)
    safe_queue.parent.mkdir(parents=True, exist_ok=True)
    safe_plan.parent.mkdir(parents=True, exist_ok=True)
    safe_queue.write_text(queue_text, encoding="utf-8")
    safe_plan.write_text(plan_text, encoding="utf-8")
    return DraftTaskResult(safe_queue, safe_plan, queue_text, plan_text)


def draft_next_from_prs(
    *,
    task_id: str = DEFAULT_DRAFT_TASK_ID,
    state: str = "open",
    limit: int = 30,
    include_body: bool = False,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, Path, DraftTaskResult]:
    pr_state = scan_pr_state(
        out=repo_root / "reports" / "agent_loop" / "pr_state.json",
        state=state,
        limit=limit,
        include_body=include_body,
        repo_root=repo_root,
    )
    _, tasks_dir = run_next_from_prs(pr_json=pr_state, repo_root=repo_root)
    briefs = sorted(tasks_dir.glob("*.md"))
    if not briefs:
        raise ValueError("planner did not produce a task brief")
    draft = draft_task_from_brief(task_brief=briefs[0], task_id=task_id, repo_root=repo_root)
    return pr_state, tasks_dir, draft


def write_batch_plan(
    *,
    tasks_dir: Path = DEFAULT_CODEX_TASKS_DIR,
    out: Path = DEFAULT_BATCH_PLAN,
    json_out: Path | None = DEFAULT_BATCH_PLAN_JSON,
    max_items: int = 12,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, Path | None, str]:
    if max_items < 1:
        raise ValueError("--max-items must be at least 1")
    if tasks_dir == DEFAULT_CODEX_TASKS_DIR:
        tasks_dir = repo_root / "reports" / "agent_loop" / "codex_tasks"
    resolved_tasks_dir = _resolve_input_path(tasks_dir, repo_root=repo_root)
    briefs = _load_brief_summaries(resolved_tasks_dir, max_items=max_items, repo_root=repo_root)
    if out == DEFAULT_BATCH_PLAN:
        out = repo_root / "reports" / "agent_loop" / "batch_plan.md"
    safe_out = _safe_output_path(out, repo_root=repo_root)
    rendered = render_batch_plan(briefs, tasks_dir=resolved_tasks_dir, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")

    safe_json: Path | None = None
    if json_out is not None:
        if json_out == DEFAULT_BATCH_PLAN_JSON:
            json_out = repo_root / "reports" / "agent_loop" / "batch_plan.json"
        safe_json = _safe_output_path(json_out, repo_root=repo_root)
        safe_json.parent.mkdir(parents=True, exist_ok=True)
        payload = [_brief_summary_payload(item, repo_root=repo_root) for item in briefs]
        safe_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return safe_out, safe_json, rendered


def _load_brief_summaries(tasks_dir: Path, *, max_items: int, repo_root: Path) -> list[BriefSummary]:
    if not tasks_dir.is_dir():
        raise ValueError("task briefs directory not found; run next-from-prs first or pass --tasks-dir")
    paths = sorted(tasks_dir.glob("*.md"))[:max_items]
    if not paths:
        raise ValueError("no task briefs found for batch planning")
    summaries: list[BriefSummary] = []
    for index, path in enumerate(paths, start=1):
        brief = _parse_task_brief(_sanitize_dynamic_text(_read_text(path)))
        lane, reason = _lane_for_brief(brief)
        summaries.append(
            BriefSummary(
                path=path,
                index=index,
                title=_sanitize_inline_text(brief["title"]),
                classification=_sanitize_inline_text(brief["classification"]),
                source=_sanitize_inline_text(brief["source"]),
                reason=_sanitize_inline_text(brief["reason"]),
                goal=_sanitize_inline_text(brief["goal"]),
                verification=_sanitize_command_text(brief["verification"]),
                lane=lane,
                gate_reason=reason,
            )
        )
    return summaries


def _lane_for_brief(brief: dict[str, str]) -> tuple[str, str]:
    classification = brief["classification"].lower()
    haystack = "\n".join(
        [brief["title"], brief["classification"], brief["source"], brief["reason"], brief["goal"], brief["verification"]]
    ).lower()
    manual_terms = (
        "gh pr merge",
        "gh pr close",
        "gh pr create",
        "git push",
        "git branch -d",
        "git branch -D".lower(),
        "force-push",
        "delete branch",
        "make real-eval",
        "private delta",
        "private real-eval",
        "benchmark claim",
        "architecture tradeoff",
    )
    if classification in {"needs_private_delta", "close_superseded"} or any(term in haystack for term in manual_terms):
        return "manual-gated", "requires human approval or private/PR decision"
    if classification in {"blocked", "failed_experiment"}:
        return "serial", "resolve before dependent implementation or claims"
    if classification == "ready_for_review" or "review " in haystack:
        return "review-only", "review pass can run without implementation mutation"
    return "parallel-safe", "no hard dependency detected; verify independently"


def render_batch_plan(briefs: Sequence[BriefSummary], *, tasks_dir: Path, repo_root: Path = ROOT_DIR) -> str:
    lanes = ("serial", "parallel-safe", "review-only", "manual-gated")
    label = {
        "serial": "Set A - Serial Blockers",
        "parallel-safe": "Set B - Parallel Safe Candidates",
        "review-only": "Set C - Review-Only Passes",
        "manual-gated": "Set D - Manual Gates",
    }
    lines = [
        "# Agent Loop Batch Plan",
        "",
        f"- Source briefs: `{_display_path(_repo_path(tasks_dir, repo_root), repo_root=repo_root)}`",
        "- This is a local planning artifact. It does not edit `tasks/queue.md`, plans, branches, PRs, or GitHub state.",
        "- Execute at most one serial lane item at a time; parallel-safe items can be assigned independently after human scope review.",
        "",
        "## Lane Summary",
        "",
        "| Lane | Count | Meaning |",
        "|---|---:|---|",
    ]
    for lane in lanes:
        count = sum(1 for item in briefs if item.lane == lane)
        lines.append(f"| `{lane}` | {count} | {label[lane]} |")
    lines.append("")

    for lane in lanes:
        lines.extend([f"## {label[lane]}", ""])
        items = [item for item in briefs if item.lane == lane]
        if not items:
            lines.extend(["- None", ""])
            continue
        for item in items:
            lines.extend(
                [
                    f"### {item.index:03d}. {item.title}",
                    "",
                    f"- Brief: `{_display_path(_repo_path(item.path, repo_root), repo_root=repo_root)}`",
                    f"- Classification: `{item.classification}`",
                    f"- Source: `{item.source}`",
                    f"- Gate reason: {item.gate_reason}",
                    f"- Reason: {item.reason}",
                    "- Suggested next safe command:",
                    "",
                    "```bash",
                    _ensure_git_diff_check(item.verification),
                    "```",
                    "",
                ]
            )
    lines.extend(
        [
            "## Human Stop Points",
            "",
            "- Applying any draft to `tasks/queue.md` or `docs/plans/*.md`.",
            "- Any push, PR create/merge/close, branch delete, or force-push.",
            "- Benchmark/performance/private real-eval claims.",
            "- Architecture tradeoff decisions.",
            "",
        ]
    )
    return _sanitize_dynamic_text("\n".join(lines))


def _brief_summary_payload(item: BriefSummary, *, repo_root: Path) -> dict[str, object]:
    return {
        "index": item.index,
        "title": item.title,
        "classification": item.classification,
        "source": item.source,
        "lane": item.lane,
        "gate_reason": item.gate_reason,
        "brief": _display_path(_repo_path(item.path, repo_root), repo_root=repo_root),
        "verification": _ensure_git_diff_check(item.verification).splitlines(),
    }


def write_review_followups(
    *,
    review: Path,
    out: Path = DEFAULT_REVIEW_FOLLOWUPS,
    tasks_dir: Path = DEFAULT_REVIEW_FOLLOWUPS_DIR,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, Path, int, str]:
    review_path = _resolve_input_path(review, repo_root=repo_root)
    if not review_path.exists():
        raise ValueError(f"review file not found: {_display_path(str(review), repo_root=repo_root)}")
    findings = parse_review_findings(_read_text(review_path))
    if out == DEFAULT_REVIEW_FOLLOWUPS:
        out = repo_root / "reports" / "agent_loop" / "review_followups.md"
    if tasks_dir == DEFAULT_REVIEW_FOLLOWUPS_DIR:
        tasks_dir = repo_root / "reports" / "agent_loop" / "review_followups"
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_tasks_dir = _safe_output_path(tasks_dir, repo_root=repo_root)
    rendered = render_review_followups(findings, review_path=review_path, tasks_dir=safe_tasks_dir, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_tasks_dir.mkdir(parents=True, exist_ok=True)
    for stale in safe_tasks_dir.glob("*.md"):
        stale.unlink()
    safe_out.write_text(rendered, encoding="utf-8")
    for index, finding in enumerate(findings, start=1):
        task_path = safe_tasks_dir / f"{index:03d}-{_slugify(finding.summary)}.md"
        task_path.write_text(
            render_review_followup_task(finding, index=index, review_path=review_path, repo_root=repo_root),
            encoding="utf-8",
        )
    return safe_out, safe_tasks_dir, len(findings), rendered


def parse_review_findings(text: str) -> list[ReviewFinding]:
    sanitized = _sanitize_dynamic_text(text)
    findings: list[ReviewFinding] = []
    in_findings = False
    for raw_line in sanitized.splitlines():
        line = raw_line.strip()
        if re.match(r"^#{1,3}\s+Findings\b", line, re.IGNORECASE):
            in_findings = True
            continue
        if in_findings and re.match(r"^#{1,3}\s+", line):
            break
        if not in_findings or not line.startswith("-"):
            continue
        match = re.match(r"^-\s*\[(?P<severity>[^\]]+)\]\s*(?P<body>.+)$", line)
        if not match:
            continue
        severity = _sanitize_inline_text(match.group("severity").lower())
        body = _sanitize_inline_text(match.group("body"))
        target = "N/A"
        summary = body
        if " - " in body:
            left, summary = body.split(" - ", 1)
            target = _display_path(left.strip())
        findings.append(
            ReviewFinding(
                severity=severity,
                target=target,
                summary=_sanitize_inline_text(summary),
                reviewer_mode=_reviewer_mode_for_finding(severity, body),
            )
        )
    return findings


def _reviewer_mode_for_finding(severity: str, body: str) -> str:
    lowered = f"{severity}\n{body}".lower()
    if any(token in lowered for token in ("privacy", "private", "doc_id", "chunk_id", "raw evidence", "filename")):
        return "Privacy Auditor"
    if any(token in lowered for token in ("benchmark", "eval", "metric", "claim", "real-eval", "performance")):
        return "Benchmark Auditor"
    if any(token in lowered for token in ("architecture", "adr", "load-bearing", "schema", "contract")):
        return "Deep Reviewer"
    return "Reviewer"


def render_review_followups(
    findings: Sequence[ReviewFinding],
    *,
    review_path: Path,
    tasks_dir: Path,
    repo_root: Path = ROOT_DIR,
) -> str:
    lines = [
        "# Review Follow-up Plan",
        "",
        f"- Source review: `{_display_path(_repo_path(review_path, repo_root), repo_root=repo_root)}`",
        f"- Task briefs: `{_display_path(_repo_path(tasks_dir, repo_root), repo_root=repo_root)}`",
        "- This command does not auto-fix code, edit queue/plan docs, push, create/close/merge PRs, or delete branches.",
        "",
    ]
    if not findings:
        lines.extend(
            [
                "## Findings",
                "",
                "- No actionable findings parsed. Review manually if the source used a different format.",
                "",
            ]
        )
        return _sanitize_dynamic_text("\n".join(lines))
    lines.extend(["## Findings", ""])
    for index, finding in enumerate(findings, start=1):
        lane = "serial" if finding.severity in {"blocking", "p0", "p1"} else "parallel-safe"
        if finding.reviewer_mode in {"Privacy Auditor", "Benchmark Auditor", "Deep Reviewer"}:
            lane = "manual-gated"
        lines.extend(
            [
                f"### {index:03d}. {finding.summary}",
                "",
                f"- Severity: `{finding.severity}`",
                f"- Target: `{finding.target}`",
                f"- Reviewer mode: `{finding.reviewer_mode}`",
                f"- Lane: `{lane}`",
                f"- Brief: `{_display_path(_repo_path(tasks_dir / f'{index:03d}-{_slugify(finding.summary)}.md', repo_root), repo_root=repo_root)}`",
                "",
            ]
        )
    return _sanitize_dynamic_text("\n".join(lines))


def render_review_followup_task(
    finding: ReviewFinding,
    *,
    index: int,
    review_path: Path,
    repo_root: Path = ROOT_DIR,
) -> str:
    summary = finding.summary
    verification = _ensure_git_diff_check(_validation_for_finding(finding))
    return _sanitize_dynamic_text(
        f"""# Review Follow-up {index:03d}: {summary}

- Classification: `review_followup`
- Severity: `{finding.severity}`
- Reviewer mode: `{finding.reviewer_mode}`
- Source review: `{_display_path(_repo_path(review_path, repo_root), repo_root=repo_root)}`
- Target: `{finding.target}`

## Goal

Address the reviewer finding with the smallest scoped change, or document why human approval is required.

## Finding

{summary}

## Constraints

- Do not auto-merge, auto-push, create/close/merge PRs, delete branches, or force-push.
- Do not make benchmark, performance, private real-eval, or architecture tradeoff claims without human approval.
- Do not expose raw private question, answer, evidence, doc_id, chunk_id, filenames, or exact local paths.

## Expected Evidence

Focused diff, focused validation, and updated handoff evidence for this finding only.

## Verification

```bash
{verification}
```
"""
    )


def _validation_for_finding(finding: ReviewFinding) -> str:
    target = finding.target.split(":", 1)[0].strip()
    if target.endswith(".py") and not _privacy_sensitive_path(target):
        commands = [f"python3 -m py_compile {target}"]
        if target.startswith("tests/test_"):
            commands.append(f"python3 -m pytest {target} -q")
        return "\n".join(commands)
    if target.startswith("docs/") and target.endswith(".md"):
        return "python3 scripts/check_doc_links.py --check-all"
    if finding.reviewer_mode == "Privacy Auditor":
        return "python3 scripts/_governance.py --check-eval-privacy"
    return "git diff --check"


def write_decision_brief(
    *,
    task_id: str | None = None,
    batch: Path | None = None,
    review_followups: Path | None = None,
    gate: str = "auto",
    changed_files: Sequence[str] = (),
    pr: str | None = None,
    out: Path = DEFAULT_DECISION_BRIEF,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    points = build_decision_points(
        task_id=task_id,
        batch=batch,
        review_followups=review_followups,
        gate=gate,
        changed_files=changed_files,
        pr=pr,
        repo_root=repo_root,
    )
    if out == DEFAULT_DECISION_BRIEF:
        out = repo_root / "reports" / "agent_loop" / "decision_brief.md"
    safe_out = _safe_output_path(out, repo_root=repo_root)
    rendered = render_decision_brief(points, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def write_promote_draft(
    *,
    queue_draft: Path = DEFAULT_QUEUE_DRAFT,
    plan_draft: Path = DEFAULT_PLAN_DRAFT,
    out: Path = DEFAULT_PROMOTE_DRAFT,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    queue_path = _resolve_default_agent_loop_path(queue_draft, "queue_entry_draft.md", repo_root=repo_root)
    plan_path = _resolve_default_agent_loop_path(plan_draft, "plan_draft.md", repo_root=repo_root)
    if not queue_path.exists():
        raise ValueError("queue draft not found; run draft-task first or pass --queue-draft")
    if not plan_path.exists():
        raise ValueError("plan draft not found; run draft-task first or pass --plan-draft")
    queue_draft_text = _sanitize_dynamic_text(_read_text(queue_path)).rstrip() + "\n"
    plan_draft_text = _sanitize_dynamic_text(_read_text(plan_path)).rstrip() + "\n"
    target_plan = _extract_suggested_plan_path(plan_draft_text)
    target_queue = repo_root / QUEUE_PATH
    target_plan_path = repo_root / target_plan
    queue_before = _read_text(target_queue) if target_queue.exists() else ""
    queue_after = queue_before.rstrip() + "\n\n" + queue_draft_text
    plan_before = _read_text(target_plan_path) if target_plan_path.exists() else ""
    rendered = render_promote_draft(
        queue_before=queue_before,
        queue_after=queue_after,
        plan_before=plan_before,
        plan_after=plan_draft_text,
        target_queue=QUEUE_PATH.as_posix(),
        target_plan=target_plan.as_posix(),
    )
    if out == DEFAULT_PROMOTE_DRAFT:
        out = repo_root / "reports" / "agent_loop" / "promote_draft.md"
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_promote_draft(
    *,
    queue_before: str,
    queue_after: str,
    plan_before: str,
    plan_after: str,
    target_queue: str,
    target_plan: str,
) -> str:
    queue_diff = _unified_diff(queue_before, queue_after, fromfile=f"a/{target_queue}", tofile=f"b/{target_queue}")
    plan_diff = _unified_diff(plan_before, plan_after, fromfile=f"a/{target_plan}", tofile=f"b/{target_plan}")
    return _sanitize_dynamic_text(
        f"""# Promote Draft Dry Run

- Result: dry-run only; no tracked files were modified.
- Queue target: `{target_queue}`
- Plan target: `{target_plan}`
- Manual approval required before applying these changes.

## Queue Diff

```diff
{queue_diff}
```

## Plan Diff

```diff
{plan_diff}
```
"""
    )


def _unified_diff(before: str, after: str, *, fromfile: str, tofile: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=fromfile,
        tofile=tofile,
        lineterm="",
    )
    return "\n".join(diff) or "(no diff)"


def _extract_suggested_plan_path(plan_text: str) -> Path:
    match = re.search(r"Suggested (?:final )?path:\s*`(?P<path>docs/plans/[^`]+\.md)`", plan_text)
    if not match:
        match = re.search(r"Suggested plan path:\s*`(?P<path>docs/plans/[^`]+\.md)`", plan_text)
    if not match:
        raise ValueError("plan draft does not name a suggested docs/plans/*.md path")
    rel = Path(match.group("path"))
    if rel.is_absolute() or ".." in rel.parts or not rel.as_posix().startswith("docs/plans/"):
        raise ValueError("suggested plan path must stay under docs/plans/")
    return rel


def _resolve_default_agent_loop_path(path: Path, default_name: str, *, repo_root: Path) -> Path:
    if path == DEFAULT_QUEUE_DRAFT and default_name == "queue_entry_draft.md":
        return repo_root / "reports" / "agent_loop" / default_name
    if path == DEFAULT_PLAN_DRAFT and default_name == "plan_draft.md":
        return repo_root / "reports" / "agent_loop" / default_name
    return _resolve_input_path(path, repo_root=repo_root)


def write_gate_status(
    *,
    task_id: str | None = None,
    batch: Path | None = None,
    review_followups: Path | None = None,
    changed_files: Sequence[str] = (),
    pr: str | None = None,
    out: Path | None = None,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path | None, str]:
    status = build_gate_status(
        task_id=task_id,
        batch=batch,
        review_followups=review_followups,
        changed_files=changed_files,
        pr=pr,
        repo_root=repo_root,
    )
    rendered = render_gate_status(status)
    written: Path | None = None
    if out is not None:
        if out == DEFAULT_GATE_STATUS:
            out = repo_root / "reports" / "agent_loop" / "gate_status.md"
        written = _safe_output_path(out, repo_root=repo_root)
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_text(rendered, encoding="utf-8")
    return written, rendered


def build_gate_status(
    *,
    task_id: str | None,
    batch: Path | None,
    review_followups: Path | None,
    changed_files: Sequence[str],
    pr: str | None,
    repo_root: Path,
) -> dict[str, object]:
    signals: list[str] = []
    gate = "orientation"
    severity = "low"
    next_safe = "python3 scripts/agent_loop.py map"
    if task_id:
        report = check_handoff(task_id, changed_files=changed_files, repo_root=repo_root)
        if not report.ok:
            gate = "handoff"
            severity = "high"
            next_safe = f"python3 scripts/agent_loop.py handoff-check --task {task_id}"
            signals.append("handoff missing or invalid")
        else:
            gate = "implementation-or-review"
            severity = "medium"
            next_safe = f"python3 scripts/agent_loop.py review-prompt --task {task_id} --from-git"
            signals.append("handoff passes")
    batch_path = _default_existing_path(batch, repo_root / "reports" / "agent_loop" / "batch_plan.json")
    if batch_path is not None:
        batch_path = _resolve_input_path(batch_path, repo_root=repo_root)
        if batch_path.exists():
            payload = _load_batch_payload(batch_path)
            manual = sum(1 for item in payload if item.get("lane") == "manual-gated")
            serial = sum(1 for item in payload if item.get("lane") == "serial")
            if manual:
                gate = "manual-gated-task"
                severity = "high"
                next_safe = "python3 scripts/agent_loop.py decision-brief --gate task"
                signals.append(f"manual-gated task count: {manual}")
            elif serial:
                gate = "serial-task-selection"
                severity = "medium"
                next_safe = "python3 scripts/agent_loop.py batch-plan"
                signals.append(f"serial task count: {serial}")
    followups_path = _default_existing_path(review_followups, repo_root / "reports" / "agent_loop" / "review_followups.md")
    if followups_path is not None:
        followups_path = _resolve_input_path(followups_path, repo_root=repo_root)
        if followups_path.exists():
            text = _sanitize_dynamic_text(_read_text(followups_path))
            parsed = len(re.findall(r"^###\s+\d{3}\.", text, re.MULTILINE))
            if parsed:
                gate = "review-followup"
                severity = "high" if "manual-gated" in text else "medium"
                next_safe = "python3 scripts/agent_loop.py decision-brief --gate review"
                signals.append(f"review follow-up count: {parsed}")
    if changed_files:
        surface = classify_changed_files(changed_files)
        signals.append(f"surface: {surface.surface}")
        if {surface.surface, *surface.additional_surfaces} & {"private-real-eval", "privacy-sensitive-artifact", "benchmark-reporting"}:
            gate = "claim-boundary"
            severity = "critical" if surface.surface in {"private-real-eval", "privacy-sensitive-artifact"} else "high"
            next_safe = "python3 scripts/agent_loop.py decision-brief --gate claim --from-git"
    if pr:
        _validate_pr_selector(pr)
        if gate not in {"claim-boundary", "manual-gated-task", "review-followup"}:
            gate = "ship"
            severity = "high"
            next_safe = f"make ship-review-gate PR={pr}"
        signals.append(f"pr: {pr}")
    return {
        "gate": gate,
        "severity": severity,
        "signals": tuple(_dedupe_preserve_order(signals)),
        "next_safe_command": next_safe,
    }


def render_gate_status(status: dict[str, object]) -> str:
    signals = status.get("signals") or ()
    lines = [
        "# Agent Loop Gate Status",
        "",
        f"- Current gate: `{status['gate']}`",
        f"- Severity: `{status['severity']}`",
        "- Signals:",
    ]
    if signals:
        lines.extend(f"  - {_sanitize_dynamic_text(str(item))}" for item in signals)
    else:
        lines.append("  - no concrete loop artifact detected")
    lines.extend(
        [
            "- Next safe command:",
            "",
            "```bash",
            _sanitize_command_text(str(status["next_safe_command"])),
            "```",
            "",
        ]
    )
    return _sanitize_dynamic_text("\n".join(lines))


def write_claim_audit(
    *,
    text_path: Path | None = None,
    changed_files: Sequence[str] = (),
    out: Path = DEFAULT_CLAIM_AUDIT,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, int, str]:
    text = ""
    source = "changed files only"
    if text_path is not None:
        resolved = _resolve_input_path(text_path, repo_root=repo_root)
        if not resolved.exists():
            raise ValueError(f"claim text file not found: {_display_path(_repo_path(resolved, repo_root), repo_root=repo_root)}")
        text = _read_text(resolved)
        source = _display_path(_repo_path(resolved, repo_root), repo_root=repo_root)
    surface = classify_changed_files(changed_files)
    findings = audit_claim_text(text, surface)
    rendered = render_claim_audit(source=source, surface=surface, findings=findings)
    if out == DEFAULT_CLAIM_AUDIT:
        out = repo_root / "reports" / "agent_loop" / "claim_audit.md"
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, 1 if findings else 0, rendered


def audit_claim_text(text: str, surface: SurfaceReport) -> list[ClaimFinding]:
    lowered = text.lower()
    findings: list[ClaimFinding] = []
    claim_patterns = {
        "performance": r"\b(performance|latency|faster|speed|p95|throughput)\b",
        "quality": r"\b(quality|accuracy|recall|precision|improved|improvement|better)\b",
        "benchmark": r"\b(benchmark|score|metric|eval result|regression)\b",
        "private-real-eval": r"\b(private real[- ]?eval|real100|real rfp|customer|production)\b",
    }
    for issue, pattern in claim_patterns.items():
        if re.search(pattern, lowered):
            findings.append(
                ClaimFinding(
                    issue=f"{issue} claim language detected",
                    severity=_claim_severity(issue, surface),
                    reviewer=_claim_reviewer(issue, surface),
                )
            )
    surfaces = {surface.surface, *surface.additional_surfaces}
    if findings and surface.surface in {"unknown", "docs-only", "ci-validation"}:
        findings.append(
            ClaimFinding(
                issue=f"claim language appears on `{surface.surface}` surface without sufficient eval provenance",
                severity="high",
                reviewer="Human reviewer + Benchmark Auditor",
            )
        )
    if "private-real-eval" in surfaces or "privacy-sensitive-artifact" in surfaces:
        findings.append(
            ClaimFinding(
                issue="private/privacy-sensitive surface requires aggregate-only evidence and human claim approval",
                severity="critical",
                reviewer="Benchmark Auditor + Privacy Auditor",
            )
        )
    return _dedupe_claim_findings(findings)


def _dedupe_claim_findings(findings: Iterable[ClaimFinding]) -> list[ClaimFinding]:
    seen: set[tuple[str, str, str]] = set()
    out: list[ClaimFinding] = []
    for finding in findings:
        key = (finding.issue, finding.severity, finding.reviewer)
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    return out


def _claim_severity(issue: str, surface: SurfaceReport) -> str:
    surfaces = {surface.surface, *surface.additional_surfaces}
    if issue == "private-real-eval" or surfaces & {"private-real-eval", "privacy-sensitive-artifact"}:
        return "critical"
    if issue in {"performance", "benchmark"}:
        return "high"
    return "medium"


def _claim_reviewer(issue: str, surface: SurfaceReport) -> str:
    surfaces = {surface.surface, *surface.additional_surfaces}
    if issue == "private-real-eval" or surfaces & {"private-real-eval", "privacy-sensitive-artifact"}:
        return "Benchmark Auditor + Privacy Auditor"
    if issue in {"performance", "benchmark", "quality"}:
        return "Benchmark Auditor"
    return "Human reviewer"


def render_claim_audit(*, source: str, surface: SurfaceReport, findings: Sequence[ClaimFinding]) -> str:
    lines = [
        "# Claim Audit",
        "",
        f"- Source: `{_sanitize_dynamic_text(source)}`",
        f"- Surface: `{surface.surface}`",
        f"- Confidence: `{surface.confidence}`",
        f"- Required reviewer: `{surface.reviewer_type}`",
        "- Matched files:",
    ]
    if surface.matched_files:
        lines.extend(f"  - `{_display_path(path)}`" for path in surface.matched_files)
    else:
        lines.append("  - `N/A`")
    lines.extend(["", "## Findings", ""])
    if not findings:
        lines.append("- None. No risky claim language detected in the provided text.")
    else:
        for finding in findings:
            lines.extend(
                [
                    f"- Severity: `{finding.severity}`",
                    f"  - Issue: {_sanitize_dynamic_text(finding.issue)}",
                    f"  - Reviewer: `{finding.reviewer}`",
                ]
            )
    lines.extend(["", "## Disallowed Claims", ""])
    lines.extend(f"- {claim}" for claim in surface.disallowed_claims)
    return _sanitize_dynamic_text("\n".join(lines)) + "\n"


def write_privacy_audit_output(
    *,
    path: Path = DEFAULT_REPORT_DIR,
    out: Path = DEFAULT_PRIVACY_AUDIT,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, int, str]:
    target = repo_root / "reports" / "agent_loop" if path == DEFAULT_REPORT_DIR else _resolve_input_path(path, repo_root=repo_root)
    safe_target = _safe_output_path(target, repo_root=repo_root)
    if out == DEFAULT_PRIVACY_AUDIT:
        out = repo_root / "reports" / "agent_loop" / "privacy_audit.md"
    safe_out = _safe_output_path(out, repo_root=repo_root)
    findings = audit_privacy_output(safe_target, out_path=safe_out, repo_root=repo_root)
    rendered = render_privacy_audit(findings, target=safe_target, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, 1 if findings else 0, rendered


def audit_privacy_output(target: Path, *, out_path: Path | None, repo_root: Path) -> list[PrivacyFinding]:
    paths = sorted(target.rglob("*")) if target.is_dir() else [target]
    findings: list[PrivacyFinding] = []
    for file_path in paths:
        if not file_path.is_file() or (out_path is not None and file_path.resolve() == out_path.resolve()):
            continue
        if file_path.suffix.lower() not in {".md", ".txt", ".json", ".jsonl", ".yaml", ".yml"}:
            continue
        try:
            text = _read_text(file_path)
        except UnicodeDecodeError:
            continue
        rel = _display_path(_repo_path(file_path, repo_root), repo_root=repo_root)
        for issue, pattern in _privacy_audit_patterns().items():
            if pattern.search(text):
                findings.append(PrivacyFinding(path=rel, issue=issue))
    return _dedupe_privacy_findings(findings)


def _privacy_audit_patterns() -> dict[str, re.Pattern[str]]:
    return {
        "absolute local path": ABSOLUTE_LOCAL_PATH_RE,
        "private raw field value": re.compile(
            r"\b(?:(?:raw\s+)?(?:question|answer|evidence)|doc[_ -]?id|chunk[_ -]?id|file\s*name|filename)\b"
            r"\s*[:=](?!\s*\[redacted-private-value\])\s*([^\n;,]+)",
            re.IGNORECASE,
        ),
        "json private raw field value": re.compile(
            r'"(?:question|answer|evidence|doc_id|chunk_id|filename)"\s*:\s*"(?!\[redacted-private-value\])[^"]+"',
            re.IGNORECASE,
        ),
        "private raw flag value": re.compile(
            r"--(?:raw-)?(?:question|answer|evidence|doc[_-]?id|chunk[_-]?id|file(?:[_-]?name)?)\s+"
            r"(?!\[redacted-private-value\])(\"[^\"]*\"|'[^']*'|\S+)",
            re.IGNORECASE,
        ),
        "private real100 artifact path": re.compile(r"reports/real100/(?!\[redacted-private-artifact\])\S+", re.IGNORECASE),
        "raw doc/chunk id token": re.compile(r"\b(?:doc|chunk)[_-]?id[-_:][A-Za-z0-9]", re.IGNORECASE),
    }


def _dedupe_privacy_findings(findings: Iterable[PrivacyFinding]) -> list[PrivacyFinding]:
    seen: set[tuple[str, str]] = set()
    out: list[PrivacyFinding] = []
    for finding in findings:
        key = (finding.path, finding.issue)
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    return out


def render_privacy_audit(findings: Sequence[PrivacyFinding], *, target: Path, repo_root: Path) -> str:
    lines = [
        "# Agent Loop Privacy Audit",
        "",
        f"- Target: `{_display_path(_repo_path(target, repo_root), repo_root=repo_root)}`",
        f"- Result: `{'fail' if findings else 'pass'}`",
        f"- Finding count: `{len(findings)}`",
        "",
        "## Findings",
        "",
    ]
    if not findings:
        lines.append("- None")
    else:
        for finding in findings:
            lines.extend(
                [
                    f"- File: `{finding.path}`",
                    f"  - Issue: {finding.issue}",
                ]
            )
    return _sanitize_dynamic_text("\n".join(lines)) + "\n"


AUTO_PASS_LOW_RISK_SURFACES = {"docs-only", "ci-validation"}


def write_auto_pass_check(
    *,
    task_id: str | None = None,
    changed_files: Sequence[str] = (),
    claim_text: Path | None = None,
    run_validation: bool = False,
    strict: bool = False,
    profile: str = "standard",
    out: Path | None = DEFAULT_AUTO_PASS,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path | None, AutoPassReport, str]:
    report = build_auto_pass_report(
        task_id=task_id,
        changed_files=changed_files,
        claim_text=claim_text,
        run_validation=run_validation,
        strict=strict,
        profile=profile,
        repo_root=repo_root,
    )
    rendered = render_auto_pass_report(report)
    written: Path | None = None
    if out is not None:
        if out == DEFAULT_AUTO_PASS:
            out = repo_root / "reports" / "agent_loop" / "auto_pass.md"
        written = _safe_output_path(out, repo_root=repo_root)
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_text(rendered, encoding="utf-8")
    return written, report, rendered


def build_auto_pass_report(
    *,
    task_id: str | None,
    changed_files: Sequence[str],
    claim_text: Path | None,
    run_validation: bool,
    repo_root: Path,
    strict: bool = False,
    profile: str = "standard",
) -> AutoPassReport:
    if profile not in {"standard", "docs-only-strict", "ci-only-strict", "agent-loop-tooling-strict"}:
        raise ValueError("--profile must be one of: standard, docs-only-strict, ci-only-strict, agent-loop-tooling-strict")
    files = sorted(
        {
            normalized
            for path in changed_files
            if (normalized := _normalize_changed_file(path, repo_root=repo_root))
        }
    )
    surface = classify_changed_files(files)
    surfaces = {surface.surface, *surface.additional_surfaces}
    blockers: list[str] = []
    warnings: list[str] = []
    evidence: list[str] = []

    if not files:
        blockers.append("changed files were not provided; auto-pass requires concrete file evidence")
    gated_surfaces = sorted(surfaces - AUTO_PASS_LOW_RISK_SURFACES)
    if gated_surfaces:
        blockers.append("surface requires human review: " + ", ".join(gated_surfaces))
    if surface.confidence != "high":
        blockers.append(f"surface confidence is {surface.confidence}; auto-pass requires high confidence")
    blockers.extend(_auto_pass_profile_blockers(profile=profile, files=files, surfaces=surfaces))

    if task_id:
        handoff = check_handoff(task_id, changed_files=files, repo_root=repo_root)
        if handoff.ok:
            evidence.append(f"handoff-check passed for {task_id}")
        else:
            missing = ", ".join((*handoff.missing_fields, *handoff.invalid_fields))
            blockers.append(f"handoff-check failed for {task_id}: {missing or 'unknown issue'}")
    elif strict:
        blockers.append("strict mode requires --task so handoff-check can run")
    else:
        warnings.append("no task id was provided; handoff was not checked")

    privacy_target = repo_root / "reports" / "agent_loop"
    privacy_findings = audit_privacy_output(
        privacy_target,
        out_path=repo_root / "reports" / "agent_loop" / "auto_pass.md",
        repo_root=repo_root,
    )
    if privacy_findings:
        blockers.append(f"privacy audit found {len(privacy_findings)} generated artifact issue(s)")
    else:
        evidence.append("privacy audit found no generated artifact issues")

    if claim_text is not None:
        resolved_claim_text = _resolve_input_path(claim_text, repo_root=repo_root)
        if not resolved_claim_text.exists():
            blockers.append("claim text file not found")
        else:
            claim_source = _display_path(_repo_path(resolved_claim_text, repo_root), repo_root=repo_root)
            claim_findings = audit_claim_text(_read_text(resolved_claim_text), surface)
            if claim_findings:
                blockers.append(f"claim audit found {len(claim_findings)} issue(s) in {claim_source}")
            else:
                evidence.append(f"claim audit found no risky claim language in {claim_source}")
    elif strict:
        blockers.append("strict mode requires --claim-text so claim wording can be audited")
    else:
        warnings.append("no claim text was provided; claim wording was not audited")

    followups = repo_root / "reports" / "agent_loop" / "review_followups.md"
    if strict and followups.exists():
        text = _sanitize_dynamic_text(_read_text(followups))
        parsed = len(re.findall(r"^###\s+\d{3}\.", text, re.MULTILINE))
        if parsed:
            blockers.append(f"strict mode blocks because {parsed} review follow-up item(s) exist")

    if run_validation:
        rc, runs = run_validation_commands(files)
        if not runs:
            blockers.append("validation selected no commands")
        for run in runs:
            evidence.append(f"validation rc={run.returncode}: {_sanitize_command_text(run.command)}")
        if rc != 0:
            blockers.append("validation failed; auto-pass requires all selected validation commands to pass")
    else:
        blockers.append("validation was not run; pass --run-validation to allow auto-pass")

    ok = not blockers
    confidence = "high" if ok else ("medium" if evidence else "low")
    next_safe = (
        "python3 scripts/agent_loop.py loop-state --from-git"
        if ok
        else "python3 scripts/agent_loop.py decision-brief --from-git"
    )
    if task_id:
        next_safe = (
            f"python3 scripts/agent_loop.py loop-state --task {task_id} --from-git"
            if ok
            else f"python3 scripts/agent_loop.py decision-brief --task {task_id} --from-git"
        )
    return AutoPassReport(
        ok=ok,
        decision="auto-pass" if ok else "human-review-required",
        confidence=confidence,
        surface=surface,
        blockers=tuple(_dedupe_preserve_order(blockers)),
        warnings=tuple(_dedupe_preserve_order(warnings)),
        evidence=tuple(_dedupe_preserve_order(evidence)),
        next_safe_command=next_safe,
    )


def _auto_pass_profile_blockers(*, profile: str, files: Sequence[str], surfaces: set[str]) -> list[str]:
    if profile == "standard":
        return []
    blockers: list[str] = []
    if profile == "docs-only-strict":
        if surfaces != {"docs-only"}:
            blockers.append("docs-only-strict requires only docs-only surface")
        if any(not (path.startswith("docs/") and path.endswith(".md")) for path in files):
            blockers.append("docs-only-strict requires every changed file to be a docs/*.md file")
    elif profile == "ci-only-strict":
        if surfaces != {"ci-validation"}:
            blockers.append("ci-only-strict requires only ci-validation surface")
        if any(
            not (
                path.startswith(".github/workflows/")
                or path.startswith(".claude/")
                or path.startswith("scripts/claude-hooks/")
                or path in {"Makefile", ".gitignore", "scripts/_governance.py"}
            )
            for path in files
        ):
            blockers.append("ci-only-strict allows only workflow, Claude hook/command, Makefile, .gitignore, or governance helper files")
    elif profile == "agent-loop-tooling-strict":
        allowed_prefixes = (
            "scripts/agent_loop",
            "tests/test_agent_loop",
            ".github/workflows/agent-loop-artifacts.yml",
            ".claude/commands/agent-loop",
            "scripts/claude-hooks/stop-agent-loop.sh",
        )
        allowed_names = {"Makefile", ".gitignore", "scripts/_governance.py", "tests/test_hook_telemetry.py"}
        if any(not (path in allowed_names or path.startswith(allowed_prefixes)) for path in files):
            blockers.append("agent-loop-tooling-strict allows only agent-loop CLI, tests, workflow, Claude command/hook, Makefile, .gitignore, or governance helper files")
        if surfaces - {"ci-validation"}:
            blockers.append("agent-loop-tooling-strict requires ci-validation surface only")
    return blockers


def render_auto_pass_report(report: AutoPassReport) -> str:
    lines = [
        "# Agent Loop Auto-Pass Check",
        "",
        f"- Decision: `{report.decision}`",
        f"- Confidence: `{report.confidence}`",
        f"- Surface: `{report.surface.surface}`",
        f"- Surface confidence: `{report.surface.confidence}`",
        "- This check does not push, create/merge/close PRs, delete branches, force-push, run private eval, or approve shipping.",
        "",
        "## Blockers",
        "",
    ]
    if report.blockers:
        lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in report.blockers)
    else:
        lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    if report.warnings:
        lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in report.warnings)
    else:
        lines.append("- None")
    lines.extend(["", "## Evidence", ""])
    if report.evidence:
        lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in report.evidence)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Matched Files",
            "",
        ]
    )
    if report.surface.matched_files:
        lines.extend(f"- `{_display_path(path)}`" for path in report.surface.matched_files)
    else:
        lines.append("- `N/A`")
    lines.extend(
        [
            "",
            "## Next Safe Command",
            "",
            "```bash",
            _sanitize_command_text(report.next_safe_command),
            "```",
            "",
        ]
    )
    return _sanitize_dynamic_text("\n".join(lines))


def write_dashboard(
    *,
    task_id: str | None = None,
    batch: Path | None = None,
    review_followups: Path | None = None,
    changed_files: Sequence[str] = (),
    pr: str | None = None,
    out: Path = DEFAULT_DASHBOARD,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    state = build_loop_state(
        task_id=task_id,
        batch=batch,
        review_followups=review_followups,
        changed_files=changed_files,
        pr=pr,
        repo_root=repo_root,
    )
    rendered = render_dashboard(state, repo_root=repo_root)
    if out == DEFAULT_DASHBOARD:
        out = repo_root / "reports" / "agent_loop" / "dashboard.md"
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_dashboard(state: dict[str, object], *, repo_root: Path = ROOT_DIR) -> str:
    gate = state.get("gate") if isinstance(state.get("gate"), dict) else {}
    surface = state.get("surface") if isinstance(state.get("surface"), dict) else {}
    task = state.get("task") if isinstance(state.get("task"), dict) else None
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    freshness = state.get("freshness") if isinstance(state.get("freshness"), list) else []
    manifest = state.get("manifest") if isinstance(state.get("manifest"), dict) else {}
    validation = state.get("validation_suggestions") if isinstance(state.get("validation_suggestions"), list) else []
    lines = [
        "# Agent Loop Dashboard",
        "",
        "- This dashboard is generated from local agent-loop state.",
        "- It does not push, create/merge/close PRs, delete branches, force-push, run private eval, or approve claims.",
        "",
        "## Current Gate",
        "",
        f"- Gate: `{gate.get('gate', 'unknown')}`",
        f"- Severity: `{gate.get('severity', 'unknown')}`",
        f"- Surface: `{surface.get('surface', 'unknown')}`",
        f"- Surface confidence: `{surface.get('confidence', 'unknown')}`",
        f"- Reviewer: `{surface.get('reviewer_type', 'unknown')}`",
        f"- PR: `{state.get('pr') or 'N/A'}`",
    ]
    if task:
        lines.extend(
            [
                f"- Task: `{task.get('id')}` - {_sanitize_dynamic_text(str(task.get('title', '')))}",
                f"- Handoff: `{'pass' if task.get('handoff_ok') else 'fail'}`",
            ]
        )
    else:
        lines.append("- Task: `N/A`")
    lines.extend(["", "## Signals", ""])
    signals = gate.get("signals") if isinstance(gate.get("signals"), (list, tuple)) else []
    if signals:
        lines.extend(f"- {_sanitize_dynamic_text(str(item))}" for item in signals)
    else:
        lines.append("- no concrete loop artifact detected")

    lines.extend(["", "## Artifacts", "", "| Artifact | Exists |", "|---|---:|"])
    for name, exists in sorted(artifacts.items()):
        lines.append(f"| `{_display_path(str(name), repo_root=repo_root)}` | `{bool(exists)}` |")

    stale = [item for item in freshness if isinstance(item, dict) and item.get("stale")]
    lines.extend(["", "## Freshness", ""])
    if stale:
        lines.append(f"- Stale local artifact count: `{len(stale)}`")
        lines.append("- Next safe command:")
        lines.extend(["", "```bash", "python3 scripts/agent_loop.py stale-reports", "```"])
    else:
        lines.append("- No stale local artifact detected by the 7-day report threshold.")
    lines.append(f"- Manifest current: `{bool(manifest.get('current', False))}` ({_sanitize_inline_text(str(manifest.get('reason', 'not checked')))})")

    lines.extend(["", "## Suggested Validation", ""])
    if validation:
        lines.extend(f"{index}. {_sanitize_command_text(str(command))}" for index, command in enumerate(validation, start=1))
    else:
        lines.append("- N/A")

    next_safe = str(gate.get("next_safe_command", "python3 scripts/agent_loop.py map"))
    lines.extend(
        [
            "",
            "## Next Safe Command",
            "",
            "```bash",
            _sanitize_command_text(next_safe),
            "```",
            "",
            "## Loop",
            "",
            "```mermaid",
            "flowchart LR",
            "  status[\"status\"] --> gate[\"gate-status\"] --> audit[\"claim/privacy/auto-pass\"] --> handoff[\"handoff-check\"] --> review[\"review\"]",
            "  review --> state[\"loop-state\"] --> status",
            "```",
            "",
        ]
    )
    return _sanitize_dynamic_text("\n".join(lines))


def render_mcp_client_config(*, repo_root: Path = ROOT_DIR) -> str:
    return """# Agent Loop MCP Client Config Samples

Use placeholders instead of personal absolute paths when committing or sharing.

## Claude Desktop / Claude Code style

```json
{
  "mcpServers": {
    "bidmate-agent-loop": {
      "command": "python3",
      "args": ["<REPO_ROOT>/scripts/agent_loop_mcp.py"],
      "cwd": "<REPO_ROOT>"
    }
  }
}
```

## Cursor / generic MCP client

```json
{
  "bidmate-agent-loop": {
    "command": "python3",
    "args": ["<REPO_ROOT>/scripts/agent_loop_mcp.py"],
    "env": {}
  }
}
```

## Smoke Test

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}\\n' \\
  | python3 scripts/agent_loop_mcp.py
```

Safety boundary:
- Tools are read/report centered by default.
- `write` defaults to `false` for MCP tools.
- Exposed tools do not push, create/merge/close PRs, delete branches,
  force-push, run private real-eval, or call external model APIs.
""".rstrip() + "\n"


def write_mcp_client_config(
    *,
    out: Path = DEFAULT_MCP_CLIENT_CONFIG,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    rendered = render_mcp_client_config(repo_root=repo_root)
    if out == DEFAULT_MCP_CLIENT_CONFIG:
        out = repo_root / "reports" / "agent_loop" / "mcp_client_config.md"
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def write_review_ingest(
    *,
    reviews: Sequence[Path] = (),
    pr: str | None = None,
    out: Path = DEFAULT_REVIEW_INGEST,
    followup_out: Path = DEFAULT_REVIEW_FOLLOWUPS,
    tasks_dir: Path = DEFAULT_REVIEW_FOLLOWUPS_DIR,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, Path, Path, int, str]:
    findings: list[ReviewFinding] = []
    source_lines: list[str] = []
    for review in reviews:
        path = _resolve_input_path(review, repo_root=repo_root)
        if not path.exists():
            raise ValueError(f"review file not found: {_display_path(str(review), repo_root=repo_root)}")
        text = _read_text(path)
        parsed = parse_review_findings(text) or _extract_loose_review_findings(text)
        findings.extend(parsed)
        source_lines.append(f"- file: `{_display_path(_repo_path(path, repo_root), repo_root=repo_root)}` ({len(parsed)} finding(s))")
    if pr:
        pr_text = _review_text_from_pr(pr, repo_root=repo_root)
        parsed = parse_review_findings(pr_text) or _extract_loose_review_findings(pr_text)
        findings.extend(parsed)
        source_lines.append(f"- PR: `{_validate_pr_selector(pr)}` ({len(parsed)} finding(s))")
    if not reviews and not pr:
        raise ValueError("review-ingest requires --review or --pr")

    if out == DEFAULT_REVIEW_INGEST:
        out = repo_root / "reports" / "agent_loop" / "review_ingest.md"
    safe_out = _safe_output_path(out, repo_root=repo_root)
    rendered = _render_review_ingest(findings, source_lines=source_lines)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    followup_path, followup_dir, count, _ = write_review_followups(
        review=safe_out,
        out=followup_out,
        tasks_dir=tasks_dir,
        repo_root=repo_root,
    )
    return safe_out, followup_path, followup_dir, count, rendered


def _render_review_ingest(findings: Sequence[ReviewFinding], *, source_lines: Sequence[str]) -> str:
    lines = [
        "# Review Ingest",
        "",
        "- This local artifact normalizes reviewer output into the `review-followup` finding format.",
        "- It does not auto-fix, push, create/merge/close PRs, delete branches, or force-push.",
        "",
        "## Sources",
        "",
    ]
    lines.extend(source_lines or ["- N/A"])
    lines.extend(["", "## Findings", ""])
    if not findings:
        lines.append("- No actionable findings parsed. Review manually if the source format is unusual.")
    for finding in findings:
        lines.append(f"- [{finding.severity}] {finding.target} - {finding.summary}")
    return _sanitize_dynamic_text("\n".join(lines)) + "\n"


def _review_text_from_pr(pr: str, *, repo_root: Path) -> str:
    safe_pr = _validate_pr_selector(pr)
    try:
        result = subprocess.run(
            ["gh", "pr", "view", safe_pr, "--json", "reviews,comments,reviewDecision"],
            cwd=repo_root,
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"could not read review state from PR {safe_pr}") from exc
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("gh pr view did not return valid JSON") from exc
    blocks: list[str] = ["## Findings"]
    for key in ("reviews", "comments"):
        items = payload.get(key) if isinstance(payload, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            body = item.get("body") or ""
            if body:
                blocks.append(_sanitize_dynamic_text(str(body)))
    return "\n\n".join(blocks)


def _extract_loose_review_findings(text: str) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    for raw in _sanitize_dynamic_text(text).splitlines():
        line = raw.strip().lstrip("-* ").strip()
        if not line:
            continue
        lowered = line.lower()
        if not any(token in lowered for token in ("blocking", "p0", "p1", "p2", "bug", "privacy", "benchmark", "unsafe", "missing")):
            continue
        severity = "blocking" if any(token in lowered for token in ("blocking", "p0", "p1", "privacy", "unsafe")) else "non-blocking"
        target = "N/A"
        match = re.search(r"(?P<target>(?:[\w.-]+/)*[\w.-]+\.\w+:\d+)", line)
        if match:
            target = _display_path(match.group("target"))
        findings.append(
            ReviewFinding(
                severity=severity,
                target=target,
                summary=_sanitize_inline_text(line),
                reviewer_mode=_reviewer_mode_for_finding(severity, line),
            )
        )
    return findings


def write_pr_health(
    *,
    pr_json: Path = DEFAULT_PR_STATE,
    out: Path = DEFAULT_PR_HEALTH,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    path = _resolve_input_path(pr_json, repo_root=repo_root)
    if not path.exists():
        raise ValueError("PR state JSON not found; run pr-scan first or pass --pr-json")
    try:
        payload = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise ValueError("PR state JSON must be valid JSON") from exc
    if not isinstance(payload, list):
        raise ValueError("PR state JSON must be an array")
    rendered = render_pr_health([item for item in payload if isinstance(item, dict)])
    if out == DEFAULT_PR_HEALTH:
        out = repo_root / "reports" / "agent_loop" / "pr_health.md"
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_pr_health(items: Sequence[dict[str, object]]) -> str:
    lanes: dict[str, list[str]] = {
        "ci-failing": [],
        "review-required": [],
        "draft": [],
        "blocked-or-dirty": [],
        "stale": [],
        "ready-ish": [],
    }
    for item in items:
        number = str(item.get("number") or "N/A")
        title = _sanitize_inline_text(str(item.get("title") or "Untitled PR"))
        label = f"#{number} {title}"
        if item.get("isDraft") is True:
            lanes["draft"].append(label)
        review = str(item.get("reviewDecision") or "").upper()
        if review in {"REVIEW_REQUIRED", "CHANGES_REQUESTED"}:
            lanes["review-required"].append(label)
        merge_state = str(item.get("mergeStateStatus") or "").upper()
        if merge_state and merge_state not in {"CLEAN", "HAS_HOOKS"}:
            lanes["blocked-or-dirty"].append(f"{label} (`{merge_state}`)")
        if _has_failing_check(item.get("statusCheckRollup")):
            lanes["ci-failing"].append(label)
        if _is_stale_pr(item.get("updatedAt")):
            lanes["stale"].append(label)
        if not any(label in entry for lane in ("ci-failing", "review-required", "draft", "blocked-or-dirty") for entry in lanes[lane]):
            lanes["ready-ish"].append(label)

    lines = [
        "# PR Health",
        "",
        "- Read-only analysis of exported PR state.",
        "- It does not push, create/merge/close PRs, delete branches, or force-push.",
        "",
    ]
    for lane, entries in lanes.items():
        lines.extend([f"## {lane}", ""])
        if entries:
            lines.extend(f"- {_sanitize_dynamic_text(entry)}" for entry in entries)
        else:
            lines.append("- None")
        lines.append("")
    lines.extend(
        [
            "## Next Recommendation",
            "",
            _pr_health_next_command(lanes),
            "",
        ]
    )
    return _sanitize_dynamic_text("\n".join(lines))


def _has_failing_check(value: object) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, dict):
            continue
        conclusion = str(item.get("conclusion") or item.get("state") or "").upper()
        status = str(item.get("status") or "").upper()
        if conclusion in {"FAILURE", "ERROR", "CANCELLED", "ACTION_REQUIRED"} or status in {"FAILURE", "ERROR"}:
            return True
    return False


def _is_stale_pr(value: object, *, days: int = 14) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - parsed).days >= days


def _pr_health_next_command(lanes: dict[str, list[str]]) -> str:
    if lanes["ci-failing"]:
        return "```bash\npython3 scripts/agent_loop.py pr-health\n```"
    if lanes["review-required"]:
        return "```bash\npython3 scripts/agent_loop.py review-ingest --pr <PR_NUMBER>\n```"
    if lanes["blocked-or-dirty"]:
        return "```bash\npython3 scripts/agent_loop.py decision-brief --gate ship --pr <PR_NUMBER>\n```"
    return "```bash\npython3 scripts/agent_loop.py batch-plan\n```"


SAFE_FIX_SUFFIXES = {".py", ".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".sh"}
SAFE_FIX_NAMES = {"Makefile", ".gitignore"}


def write_safe_fix(
    *,
    changed_files: Sequence[str],
    apply: bool = False,
    out: Path = DEFAULT_SAFE_FIX,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, SafeFixReport, str]:
    report = build_safe_fix_report(changed_files=changed_files, apply=apply, repo_root=repo_root)
    rendered = render_safe_fix_report(report)
    if out == DEFAULT_SAFE_FIX:
        out = repo_root / "reports" / "agent_loop" / "safe_fix.md"
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, report, rendered


def build_safe_fix_report(
    *,
    changed_files: Sequence[str],
    apply: bool,
    repo_root: Path,
) -> SafeFixReport:
    changes: list[SafeFixChange] = []
    skipped: list[str] = []
    for raw in changed_files:
        rel = _normalize_changed_file(raw, repo_root=repo_root)
        if not rel or rel == "[redacted-local-path]":
            skipped.append("unusable path")
            continue
        if _privacy_sensitive_path(rel):
            skipped.append(f"{_display_path(rel)}: privacy-sensitive path")
            continue
        path = repo_root / rel
        if not path.is_file():
            skipped.append(f"{_display_path(rel)}: not a file")
            continue
        if path.name not in SAFE_FIX_NAMES and path.suffix.lower() not in SAFE_FIX_SUFFIXES:
            skipped.append(f"{_display_path(rel)}: unsupported suffix")
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped.append(f"{_display_path(rel)}: not utf-8 text")
            continue
        fixed = _fix_text_whitespace(original)
        if fixed == original:
            continue
        if apply:
            path.write_text(fixed, encoding="utf-8")
        action = "applied whitespace normalization" if apply else "would normalize whitespace"
        changes.append(SafeFixChange(path=_display_path(rel), action=action))
    return SafeFixReport(
        applied=apply,
        changes=tuple(changes),
        skipped=tuple(_dedupe_preserve_order(skipped)),
    )


def _fix_text_whitespace(text: str) -> str:
    lines = [line.rstrip(" \t") for line in text.splitlines()]
    return "\n".join(lines).rstrip("\n") + "\n"


def render_safe_fix_report(report: SafeFixReport) -> str:
    lines = [
        "# Safe Local Auto-Fix",
        "",
        f"- Mode: `{'apply' if report.applied else 'dry-run'}`",
        "- Scope: trailing whitespace and final newline only for allowlisted public-safe text files.",
        "- This command does not run formatters, change product behavior, push, create/merge/close PRs, delete branches, or force-push.",
        "",
        "## Changes",
        "",
    ]
    if report.changes:
        lines.extend(f"- `{item.path}`: {item.action}" for item in report.changes)
    else:
        lines.append("- None")
    lines.extend(["", "## Skipped", ""])
    if report.skipped:
        lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in report.skipped)
    else:
        lines.append("- None")
    return _sanitize_dynamic_text("\n".join(lines)) + "\n"


def _default_output(out: Path, default: Path, filename: str, *, repo_root: Path) -> Path:
    return repo_root / "reports" / "agent_loop" / filename if out == default else out


def write_approval_packet(
    *,
    task_id: str | None = None,
    changed_files: Sequence[str] = (),
    pr: str | None = None,
    claim_text: Path | None = None,
    run_validation: bool = False,
    out: Path = DEFAULT_APPROVAL_PACKET,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    files = sorted(_normalize_changed_file(path, repo_root=repo_root) for path in changed_files if path)
    surface = classify_changed_files(files)
    gate = build_gate_status(
        task_id=task_id,
        batch=None,
        review_followups=None,
        changed_files=files,
        pr=pr,
        repo_root=repo_root,
    )
    auto_pass = build_auto_pass_report(
        task_id=task_id,
        changed_files=files,
        claim_text=claim_text,
        run_validation=run_validation,
        strict=False,
        repo_root=repo_root,
    )
    claim_findings: list[ClaimFinding] = []
    claim_source = "N/A"
    if claim_text is not None:
        resolved = _resolve_input_path(claim_text, repo_root=repo_root)
        if resolved.exists():
            claim_source = _display_path(_repo_path(resolved, repo_root), repo_root=repo_root)
            claim_findings = audit_claim_text(_read_text(resolved), surface)
    privacy_findings = audit_privacy_output(
        repo_root / "reports" / "agent_loop",
        out_path=_default_output(out, DEFAULT_APPROVAL_PACKET, "approval_packet.md", repo_root=repo_root),
        repo_root=repo_root,
    )
    rendered = render_approval_packet(
        task_id=task_id,
        changed_files=files,
        pr=pr,
        surface=surface,
        gate=gate,
        auto_pass=auto_pass,
        claim_findings=claim_findings,
        claim_source=claim_source,
        privacy_findings=privacy_findings,
    )
    out = _default_output(out, DEFAULT_APPROVAL_PACKET, "approval_packet.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_approval_packet(
    *,
    task_id: str | None,
    changed_files: Sequence[str],
    pr: str | None,
    surface: SurfaceReport,
    gate: dict[str, object],
    auto_pass: AutoPassReport,
    claim_findings: Sequence[ClaimFinding],
    claim_source: str,
    privacy_findings: Sequence[PrivacyFinding],
) -> str:
    lines = [
        "# Agent Loop PR Approval Packet",
        "",
        "- Purpose: collect the evidence a human should inspect before PR creation or shipping.",
        "- This packet does not push, create/merge/close PRs, delete branches, force-push, run private eval, or approve claims.",
        "",
        "## Summary",
        "",
        f"- Task: `{task_id or 'N/A'}`",
        f"- PR: `{_validate_pr_selector(pr) if pr else 'N/A'}`",
        f"- Gate: `{gate.get('gate', 'unknown')}`",
        f"- Severity: `{gate.get('severity', 'unknown')}`",
        f"- Auto-pass decision: `{auto_pass.decision}`",
        f"- Surface: `{surface.surface}`",
        f"- Surface confidence: `{surface.confidence}`",
        f"- Required reviewer: `{surface.reviewer_type}`",
        "",
        "## Changed Files",
        "",
    ]
    if changed_files:
        lines.extend(f"- `{_display_path(path)}`" for path in changed_files)
    else:
        lines.append("- `N/A`")
    lines.extend(
        [
            "",
            "## Validation Suggestions",
            "",
        ]
    )
    lines.extend(f"{index}. {_sanitize_command_text(command)}" for index, command in enumerate(suggest_validation_commands(changed_files), start=1))
    lines.extend(["", "## Auto-Pass Blockers", ""])
    lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in auto_pass.blockers) if auto_pass.blockers else lines.append("- None")
    lines.extend(["", "## Claim Audit", ""])
    lines.append(f"- Source: `{_sanitize_dynamic_text(claim_source)}`")
    if claim_findings:
        for finding in claim_findings:
            lines.append(f"- `{finding.severity}` / `{finding.reviewer}`: {_sanitize_dynamic_text(finding.issue)}")
    else:
        lines.append("- No risky claim wording was detected in the provided claim text.")
    lines.extend(["", "## Privacy Audit", ""])
    if privacy_findings:
        for finding in privacy_findings:
            lines.append(f"- `{finding.path}`: {finding.issue}")
    else:
        lines.append("- No private raw values were found in generated agent-loop artifacts.")
    lines.extend(
        [
            "",
            "## Human Approval Required Before",
            "",
            "- Applying queue/plan drafts to tracked docs.",
            "- Running push, PR create/merge/close, branch delete, or force-push.",
            "- Making benchmark/performance/private real-eval claims.",
            "- Choosing architecture tradeoffs.",
            "",
            "## Next Safe Command",
            "",
            "```bash",
            _sanitize_command_text(str(gate.get("next_safe_command", "python3 scripts/agent_loop.py gate-brief --gate pr-create"))),
            "```",
            "",
        ]
    )
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def write_propose_queue_plan(
    *,
    task_brief: Path | None = None,
    task_id: str = DEFAULT_DRAFT_TASK_ID,
    queue_draft: Path = DEFAULT_QUEUE_DRAFT,
    plan_draft: Path = DEFAULT_PLAN_DRAFT,
    out: Path = DEFAULT_QUEUE_PLAN_PATCH,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    if task_brief is not None:
        draft_task_from_brief(
            task_brief=task_brief,
            task_id=task_id,
            out_queue=queue_draft,
            out_plan=plan_draft,
            repo_root=repo_root,
        )
    queue_path = _resolve_default_agent_loop_path(queue_draft, "queue_entry_draft.md", repo_root=repo_root)
    plan_path = _resolve_default_agent_loop_path(plan_draft, "plan_draft.md", repo_root=repo_root)
    if not queue_path.exists() or not plan_path.exists():
        raise ValueError("queue/plan drafts not found; run draft-task or pass --task-brief")
    queue_text = _sanitize_dynamic_text(_read_text(queue_path)).rstrip() + "\n"
    plan_text = _sanitize_dynamic_text(_read_text(plan_path)).rstrip() + "\n"
    target_plan = _extract_suggested_plan_path(plan_text)
    target_queue = repo_root / QUEUE_PATH
    target_plan_path = repo_root / target_plan
    rendered = render_queue_plan_patch(
        queue_before=_read_text(target_queue) if target_queue.exists() else "",
        queue_after=(_read_text(target_queue).rstrip() + "\n\n" + queue_text) if target_queue.exists() else queue_text,
        plan_before=_read_text(target_plan_path) if target_plan_path.exists() else "",
        plan_after=plan_text,
        target_queue=QUEUE_PATH.as_posix(),
        target_plan=target_plan.as_posix(),
    )
    out = _default_output(out, DEFAULT_QUEUE_PLAN_PATCH, "queue_plan_patch.diff", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_queue_plan_patch(
    *,
    queue_before: str,
    queue_after: str,
    plan_before: str,
    plan_after: str,
    target_queue: str,
    target_plan: str,
) -> str:
    queue_diff = _unified_diff(queue_before, queue_after, fromfile=f"a/{target_queue}", tofile=f"b/{target_queue}")
    plan_diff = _unified_diff(plan_before, plan_after, fromfile=f"a/{target_plan}", tofile=f"b/{target_plan}")
    return _sanitize_dynamic_text(
        "\n".join(
            [
                "# Agent-loop queue/plan patch proposal. Dry-run only; do not apply without human approval.",
                queue_diff,
                plan_diff,
                "",
            ]
        )
    )


def write_pr_body(
    *,
    task_id: str | None = None,
    changed_files: Sequence[str] = (),
    branch: str | None = None,
    issue: str | None = None,
    out: Path = DEFAULT_PR_BODY,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    rendered = render_pr_body(
        task_id=task_id,
        changed_files=changed_files,
        branch=branch,
        issue=issue,
        repo_root=repo_root,
    )
    out = _default_output(out, DEFAULT_PR_BODY, "pr_body.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_pr_body(
    *,
    task_id: str | None,
    changed_files: Sequence[str],
    branch: str | None,
    issue: str | None,
    repo_root: Path = ROOT_DIR,
) -> str:
    task = load_task(task_id, repo_root) if task_id else None
    files = sorted(_normalize_changed_file(path, repo_root=repo_root) for path in changed_files if path)
    surface = classify_changed_files(files)
    branch_name = branch or _current_branch(repo_root) or ""
    issue_number = issue or _issue_from_branch(branch_name) or ""
    validation = suggest_validation_commands(files)
    load_bearing = [path for path in files if path != "[redacted-local-path]" and (is_load_bearing(path) or path.startswith("eval/"))]
    title = _sanitize_inline_text(task.title) if task else "Agent-loop scoped change"
    file_block = "\n".join(f"- `{_display_path(path)}`" for path in files) if files else "- N/A"
    validation_block = "\n".join(f"- Suggested, not yet run: `{_sanitize_command_text(command)}`" for command in validation)
    five_b = (
        "Load-bearing or eval surface touched. Human reviewer must verify aggregate-only §5b evidence or a truthful no-behavior-change attestation before PR is marked ready."
        if load_bearing
        else "N/A - no load-bearing path detected by changed-file surface; reviewer should still confirm."
    )
    text = f"""## 1. 무엇을 왜 바꿨는가

{title}

Closes #{issue_number or '<ISSUE_NUMBER>'}

## 2. 영향 파일

{file_block}

- Surface: `{surface.surface}`
- Additional surfaces: `{', '.join(surface.additional_surfaces) if surface.additional_surfaces else 'N/A'}`
- Required reviewer: `{surface.reviewer_type}`

## 3. 리스크

- Human-gated decisions remain outside this CLI: push, PR create/merge/close, branch delete, force-push, private real-eval decisions, benchmark/performance claims, and architecture tradeoffs.
- Disallowed claims to avoid:
{chr(10).join(f'  - {claim}' for claim in surface.disallowed_claims)}

## 4. 테스트

{validation_block}

## 5. Eval 영향

- Surface classification: `{surface.surface}`
- Claim boundary: suggestions only; no benchmark/performance/private real-eval claim is made by this draft.

### 5b. Real-data delta

{five_b}

## 6. 하위 호환

N/A - this draft must be reviewed against the actual implementation diff before PR creation.

## 7. 범위 외

- Auto-push, PR creation/merge/close, branch deletion, force-push.
- Private raw question/answer/evidence/doc_id/chunk_id/filename/local path exposure.
"""
    return _sanitize_dynamic_text(text).rstrip() + "\n"


def _issue_from_branch(branch: str) -> str | None:
    match = re.search(r"(?:^|/)issue-(\d+)(?:-|$)", branch)
    return match.group(1) if match else None


def _current_branch(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _current_git_head(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def write_review_plan(
    *,
    reviews: Sequence[Path] = (),
    pr: str | None = None,
    out: Path = DEFAULT_REVIEW_PLAN,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    findings, sources = _collect_review_findings(reviews=reviews, pr=pr, repo_root=repo_root)
    rendered = render_review_plan(findings, sources=sources)
    out = _default_output(out, DEFAULT_REVIEW_PLAN, "review_plan.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def _collect_review_findings(
    *,
    reviews: Sequence[Path],
    pr: str | None,
    repo_root: Path,
) -> tuple[list[ReviewFinding], list[str]]:
    findings: list[ReviewFinding] = []
    sources: list[str] = []
    for review in reviews:
        path = _resolve_input_path(review, repo_root=repo_root)
        if not path.exists():
            raise ValueError(f"review file not found: {_display_path(str(review), repo_root=repo_root)}")
        text = _read_text(path)
        parsed = parse_review_findings(text) or _extract_loose_review_findings(text)
        findings.extend(parsed)
        sources.append(f"file `{_display_path(_repo_path(path, repo_root), repo_root=repo_root)}`")
    if pr:
        text = _review_text_from_pr(pr, repo_root=repo_root)
        parsed = parse_review_findings(text) or _extract_loose_review_findings(text)
        findings.extend(parsed)
        sources.append(f"PR `{_validate_pr_selector(pr)}`")
    if not reviews and not pr:
        raise ValueError("review-plan requires --review or --pr")
    return findings, sources


def render_review_plan(findings: Sequence[ReviewFinding], *, sources: Sequence[str]) -> str:
    lanes = {"must-fix": 0, "should-fix": 0, "needs-human-decision": 0, "safe-local-fix-candidate": 0}
    lines = [
        "# Review Plan",
        "",
        "- This is a triage artifact. It does not auto-fix, push, create/merge/close PRs, delete branches, or force-push.",
        "- Privacy, benchmark, and architecture findings stay human-gated.",
        "",
        "## Sources",
        "",
    ]
    lines.extend(f"- {_sanitize_dynamic_text(source)}" for source in sources)
    lines.extend(["", "## Findings", ""])
    if not findings:
        lines.append("- No actionable findings parsed. Review manually if the source format is unusual.")
    for finding in findings:
        lane = _review_plan_lane(finding)
        lanes[lane] += 1
        lines.extend(
            [
                f"### {finding.summary}",
                "",
                f"- Lane: `{lane}`",
                f"- Severity: `{finding.severity}`",
                f"- Target: `{finding.target}`",
                f"- Reviewer mode: `{finding.reviewer_mode}`",
                f"- Suggested validation: `{_sanitize_command_text(_validation_for_finding(finding))}`",
                "",
            ]
        )
    lines.extend(["## Lane Summary", "", "| Lane | Count |", "|---|---:|"])
    for lane, count in lanes.items():
        lines.append(f"| `{lane}` | {count} |")
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def _review_plan_lane(finding: ReviewFinding) -> str:
    if finding.reviewer_mode in {"Privacy Auditor", "Benchmark Auditor", "Deep Reviewer"}:
        return "needs-human-decision"
    target = finding.target.split(":", 1)[0]
    if target.endswith((".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".sh")) and not _privacy_sensitive_path(target):
        if finding.severity in {"non-blocking", "p2", "p3", "nit"}:
            return "safe-local-fix-candidate"
    if finding.severity in {"blocking", "p0", "p1"}:
        return "must-fix"
    return "should-fix"


def write_stale_reports(
    *,
    changed_files: Sequence[str] = (),
    max_age_days: int = 7,
    apply: bool = False,
    out: Path = DEFAULT_STALE_REPORTS,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    out = _default_output(out, DEFAULT_STALE_REPORTS, "stale_reports.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    artifacts = _report_freshness(repo_root=repo_root, max_age_days=max_age_days, out_path=safe_out)
    deleted: list[str] = []
    if apply:
        for item in artifacts:
            if item["stale"] and item["path"] != _display_path(_repo_path(safe_out, repo_root), repo_root=repo_root):
                target = repo_root / str(item["path"])
                if target.is_file():
                    target.unlink()
                    deleted.append(str(item["path"]))
    rendered = render_stale_reports(
        artifacts,
        max_age_days=max_age_days,
        apply=apply,
        deleted=deleted,
        manifest=_manifest_freshness(changed_files=changed_files, repo_root=repo_root),
    )
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def _report_freshness(*, repo_root: Path, max_age_days: int = 7, out_path: Path | None = None) -> list[dict[str, object]]:
    report_dir = repo_root / "reports" / "agent_loop"
    if not report_dir.exists():
        return []
    now = datetime.now(timezone.utc)
    artifacts: list[dict[str, object]] = []
    for path in sorted(report_dir.rglob("*")):
        if not path.is_file():
            continue
        age_days = max(0.0, (now - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)).total_seconds() / 86400)
        rel = _display_path(_repo_path(path, repo_root), repo_root=repo_root)
        artifacts.append(
            {
                "path": rel,
                "age_days": round(age_days, 2),
                "stale": age_days > max_age_days,
                "current_output": bool(out_path and path.resolve() == out_path.resolve()),
            }
        )
    return artifacts


def render_stale_reports(
    artifacts: Sequence[dict[str, object]],
    *,
    max_age_days: int,
    apply: bool,
    deleted: Sequence[str],
    manifest: dict[str, object] | None = None,
) -> str:
    stale_count = sum(1 for item in artifacts if item.get("stale"))
    lines = [
        "# Agent Loop Stale Report Artifacts",
        "",
        f"- Mode: `{'apply' if apply else 'dry-run'}`",
        f"- Stale threshold days: `{max_age_days}`",
        f"- Stale artifact count: `{stale_count}`",
        "- This command is limited to ignored `reports/agent_loop/` artifacts.",
        "",
        "## Manifest Freshness",
        "",
        f"- Exists: `{bool((manifest or {}).get('exists', False))}`",
        f"- Current: `{bool((manifest or {}).get('current', False))}`",
        f"- Reason: `{_sanitize_inline_text(str((manifest or {}).get('reason', 'not checked')))}`",
        "",
        "## Artifacts",
        "",
        "| Artifact | Age days | Stale |",
        "|---|---:|---:|",
    ]
    if artifacts:
        for item in artifacts:
            lines.append(f"| `{item['path']}` | `{item['age_days']}` | `{bool(item['stale'])}` |")
    else:
        lines.append("| `N/A` | `0` | `False` |")
    lines.extend(["", "## Deleted", ""])
    if deleted:
        lines.extend(f"- `{_display_path(path)}`" for path in deleted)
    else:
        lines.append("- None")
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def write_context_pack(
    *,
    task_id: str | None = None,
    changed_files: Sequence[str] = (),
    pr: str | None = None,
    profile: str = "generic",
    out: Path = DEFAULT_CONTEXT_PACK,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    state = build_loop_state(
        task_id=task_id,
        batch=None,
        review_followups=None,
        changed_files=changed_files,
        pr=pr,
        repo_root=repo_root,
    )
    rendered = render_context_pack(state, changed_files=changed_files, profile=profile)
    out = _default_output(out, DEFAULT_CONTEXT_PACK, "context_pack.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_context_pack(state: dict[str, object], *, changed_files: Sequence[str], profile: str = "generic") -> str:
    if profile not in {"generic", "codex", "claude", "chatgpt"}:
        raise ValueError("--profile must be one of: generic, codex, claude, chatgpt")
    surface = state.get("surface") if isinstance(state.get("surface"), dict) else {}
    gate = state.get("gate") if isinstance(state.get("gate"), dict) else {}
    task = state.get("task") if isinstance(state.get("task"), dict) else None
    lines = [
        "# Cross-Agent Context Pack",
        "",
        f"- Profile: `{profile}`",
        "- Safe to paste into another coding agent only after human review of this redacted summary.",
        "- Contains no raw diff, private case text, raw question/answer/evidence, doc_id, chunk_id, filename, or exact local path by design.",
        "",
        "## Task",
        "",
    ]
    if task:
        lines.extend(
            [
                f"- ID: `{task.get('id')}`",
                f"- Title: {_sanitize_dynamic_text(str(task.get('title', '')))}",
                f"- Status: `{task.get('status')}`",
                f"- Handoff: `{'pass' if task.get('handoff_ok') else 'fail'}`",
            ]
        )
    else:
        lines.append("- N/A")
    lines.extend(
        [
            "",
            "## Surface",
            "",
            f"- Surface: `{surface.get('surface', 'unknown')}`",
            f"- Confidence: `{surface.get('confidence', 'unknown')}`",
            f"- Reviewer: `{surface.get('reviewer_type', 'unknown')}`",
            "",
            "## Changed Files",
            "",
        ]
    )
    lines.extend(f"- `{_display_path(path)}`" for path in changed_files) if changed_files else lines.append("- `N/A`")
    lines.extend(["", "## Suggested Validation", ""])
    validation = state.get("validation_suggestions") if isinstance(state.get("validation_suggestions"), list) else []
    lines.extend(f"- `{_sanitize_command_text(str(command))}`" for command in validation) if validation else lines.append("- N/A")
    lines.extend(["", "## Profile Notes", ""])
    if profile == "codex":
        lines.append("- Focus on file edits, tests, validation, and concise handoff.")
    elif profile == "claude":
        lines.append("- Focus on long-session handoff, slash commands, hooks, and allowed-tools boundaries.")
    elif profile == "chatgpt":
        lines.append("- Focus on design review, trade-offs, claim wording, and reviewer questions.")
    else:
        lines.append("- Generic profile for any coding agent.")
    lines.extend(
        [
            "",
            "## Next Safe Command",
            "",
            "```bash",
            _sanitize_command_text(str(gate.get("next_safe_command", "python3 scripts/agent_loop.py map"))),
            "```",
            "",
        ]
    )
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def write_architecture_brief(
    *,
    changed_files: Sequence[str] = (),
    out: Path = DEFAULT_ARCHITECTURE_BRIEF,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    surface = classify_changed_files(changed_files)
    rendered = render_architecture_brief(surface=surface, changed_files=changed_files)
    out = _default_output(out, DEFAULT_ARCHITECTURE_BRIEF, "architecture_brief.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_architecture_brief(*, surface: SurfaceReport, changed_files: Sequence[str]) -> str:
    load_bearing = [path for path in changed_files if path != "[redacted-local-path]" and is_load_bearing(path)]
    adr_files = [path for path in changed_files if _normalize_changed_file(path).startswith("docs/adr/")]
    surfaces = {surface.surface, *surface.additional_surfaces}
    adr_likely = bool(load_bearing or adr_files or surfaces & {"product-runtime", "eval-harness", "public-synthetic-benchmark", "private-real-eval"})
    lines = [
        "# Architecture Decision Brief",
        "",
        "- This brief explains trade-offs. It does not choose architecture, write ADRs, push, or create PRs.",
        "",
        "## Signals",
        "",
        f"- Surface: `{surface.surface}`",
        f"- ADR likely: `{'yes' if adr_likely else 'no'}`",
        f"- Load-bearing files: `{len(load_bearing)}`",
        f"- ADR files: `{len(adr_files)}`",
        "",
        "## Files",
        "",
    ]
    lines.extend(f"- `{_display_path(path)}`" for path in changed_files) if changed_files else lines.append("- `N/A`")
    lines.extend(
        [
            "",
            "## Options",
            "",
            "### 1. Keep the change local and reversible (recommended default)",
            "",
            "- Severity: `low`",
            "- Reversibility: `high`",
            "- Trade-off: fastest way to preserve momentum while avoiding premature architecture commitment.",
            "- Evidence needed: focused tests and no contract or eval-surface expansion.",
            "",
            "### 2. Proceed with scoped architecture change after human review",
            "",
            "- Severity: `high`",
            "- Reversibility: `medium`",
            "- Trade-off: can solve the real design issue but may create coupling, migration, or ADR obligations.",
            "- Evidence needed: alternatives, compatibility, tests, and reviewer agreement.",
            "",
            "### 3. Reserve or update an ADR",
            "",
            "- Severity: `high`",
            "- Reversibility: `low` once accepted",
            "- Trade-off: records the decision but adds governance weight and should not be used for minor implementation detail.",
            "- Evidence needed: load-bearing decision, rejected alternatives, consequences, and validation plan.",
            "",
            "## Next Safe Command",
            "",
            "```bash",
            "python3 scripts/agent_loop.py gate-brief --gate architecture --from-git",
            "```",
            "",
        ]
    )
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def write_ship_simulation(
    *,
    task_id: str | None = None,
    changed_files: Sequence[str] = (),
    pr: str | None = None,
    branch: str | None = None,
    out: Path = DEFAULT_SHIP_SIMULATION,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    rendered = render_ship_simulation(
        task_id=task_id,
        changed_files=changed_files,
        pr=pr,
        branch=branch,
        repo_root=repo_root,
    )
    out = _default_output(out, DEFAULT_SHIP_SIMULATION, "ship_simulation.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_ship_simulation(
    *,
    task_id: str | None,
    changed_files: Sequence[str],
    pr: str | None,
    branch: str | None,
    repo_root: Path,
) -> str:
    surface = classify_changed_files(changed_files)
    branch_name = branch or _current_branch(repo_root) or "unknown"
    issue_number = _issue_from_branch(branch_name)
    blockers: list[str] = []
    if not issue_number:
        blockers.append("branch does not expose an ADR 0007 issue number")
    if surface.confidence != "high":
        blockers.append(f"surface confidence is {surface.confidence}")
    if {surface.surface, *surface.additional_surfaces} & {"private-real-eval", "privacy-sensitive-artifact", "benchmark-reporting"}:
        blockers.append("claim/privacy/eval surface requires human review")
    if task_id:
        handoff = check_handoff(task_id, changed_files=changed_files, repo_root=repo_root)
        if not handoff.ok:
            blockers.append("handoff-check is missing or has weak evidence")
    else:
        blockers.append("no task id provided for handoff-check")
    stop_before = "gh pr create" if not pr else "gh pr merge / gh pr close / branch delete"
    lines = [
        "# Auto-Ship Readiness Simulation",
        "",
        "- Simulation only. This command does not push, create/merge/close PRs, delete branches, or force-push.",
        "",
        "## Inputs",
        "",
        f"- Task: `{task_id or 'N/A'}`",
        f"- PR: `{_validate_pr_selector(pr) if pr else 'N/A'}`",
        f"- Branch: `{_sanitize_inline_text(branch_name)}`",
        f"- Issue from branch: `{issue_number or 'N/A'}`",
        f"- Git HEAD: `{_current_git_head(repo_root) or 'unknown'}`",
        f"- Surface: `{surface.surface}`",
        "",
        "## Simulated Stop",
        "",
        f"- Would stop before: `{stop_before}`",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in blockers) if blockers else lines.append("- None detected by local simulation.")
    lines.extend(["", "## Suggested Validation", ""])
    lines.extend(f"- `{_sanitize_command_text(command)}`" for command in suggest_validation_commands(changed_files))
    lines.extend(
        [
            "",
            "## Next Safe Command",
            "",
            "```bash",
            "python3 scripts/agent_loop.py approval-packet --from-git",
            "```",
            "",
        ]
    )
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def write_auto_ship_plan(
    *,
    task_id: str | None = None,
    changed_files: Sequence[str] = (),
    pr: str | None = None,
    branch: str | None = None,
    ttl: str = "2h",
    real_eval: str | None = None,
    draft: bool = False,
    dry_run: bool = False,
    out: Path = DEFAULT_AUTO_SHIP_PLAN,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, AutoShipPlan, str]:
    plan = build_auto_ship_plan(
        task_id=task_id,
        changed_files=changed_files,
        pr=pr,
        branch=branch,
        ttl=ttl,
        real_eval=real_eval,
        draft=draft,
        dry_run=dry_run,
        repo_root=repo_root,
    )
    rendered = render_auto_ship_plan(plan, task_id=task_id, changed_files=changed_files, pr=pr, repo_root=repo_root)
    out = _default_output(out, DEFAULT_AUTO_SHIP_PLAN, "auto_ship_plan.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, plan, rendered


def build_auto_ship_plan(
    *,
    task_id: str | None,
    changed_files: Sequence[str],
    pr: str | None,
    branch: str | None,
    ttl: str,
    real_eval: str | None,
    draft: bool,
    dry_run: bool,
    repo_root: Path,
) -> AutoShipPlan:
    if not re.fullmatch(r"\s*\d+\s*[smhd]\s*", ttl, flags=re.IGNORECASE):
        raise ValueError("auto-ship ttl must look like 30m, 2h, or 1d")
    if real_eval is not None and real_eval not in {"auto", "skip", "async"}:
        raise ValueError("auto-ship real_eval must be auto, skip, or async")
    files = sorted(
        {
            normalized
            for path in changed_files
            if (normalized := _normalize_changed_file(path, repo_root=repo_root))
        }
    )
    surface = classify_changed_files(files)
    branch_name = branch or _current_branch(repo_root) or "unknown"
    if branch_name != "unknown":
        branch_name = _validate_branch_name(branch_name, allow_protected=True)
    issue_number = _issue_from_branch(branch_name)
    risky_surfaces = {
        "private-real-eval",
        "privacy-sensitive-artifact",
        "benchmark-reporting",
        "public-synthetic-benchmark",
        "eval-harness",
        "product-runtime",
        "governance-adr",
    }
    blockers: list[str] = []
    warnings: list[str] = []
    evidence: list[str] = [
        f"surface={surface.surface}",
        f"surface confidence={surface.confidence}",
        f"required reviewer={surface.reviewer_type}",
        f"changed files={len(files)}",
    ]
    if pr:
        evidence.append(f"PR={_validate_pr_selector(pr)}")
    if branch_name == "unknown":
        blockers.append("current branch could not be determined")
    if branch_name in {"HEAD", "main", "master"} or branch_name.startswith("release/"):
        blockers.append(f"existing ship-arm refuses protected branch `{branch_name}`")
    if not issue_number:
        blockers.append("branch does not expose an ADR 0007 issue number")
    else:
        evidence.append(f"issue from branch=#{issue_number}")
    armed_file = repo_root / ".claude" / ".ship-armed"
    ship_pr_marker = repo_root / ".claude" / ".ship-pr-active"
    if armed_file.exists():
        blockers.append("ship-arm is already armed; run `make ship-status` or `make ship-disarm` before re-arming")
    if ship_pr_marker.exists():
        blockers.append("ship-pr mutex marker exists; finish or cancel the ship-pr workflow before arming auto-ship")
    if not files:
        warnings.append("no changed files were supplied; use `--from-git` or `--changed-files` for a meaningful plan")
    if task_id:
        handoff = check_handoff(task_id, changed_files=files, repo_root=repo_root)
        if handoff.ok:
            evidence.append("handoff-check=pass")
        else:
            blockers.append("handoff-check is missing or has weak evidence for the provided task")
    else:
        warnings.append("no task id supplied; auto-ship can still use issue/branch state, but agent-loop handoff is not checked")
    surface_set = {surface.surface, *surface.additional_surfaces}
    if surface.confidence != "high":
        warnings.append(f"surface confidence is {surface.confidence}; prefer draft or dry-run arming")
    if surface_set & risky_surfaces:
        warnings.append("changed-file surface requires reviewer or human claim/eval/architecture decision before ready merge")
    chosen_real_eval = real_eval or "skip"
    if real_eval is None:
        warnings.append("REAL_EVAL defaults to skip in this plan; choose auto/async only after human private-eval decision")
    chosen_draft = draft or bool(blockers) or surface.confidence != "high" or bool(surface_set & risky_surfaces)
    dry_run_command = _make_ship_arm_command(ttl=ttl, real_eval="skip", draft=True, dry_run=True)
    recommended_command = _make_ship_arm_command(
        ttl=ttl,
        real_eval=chosen_real_eval,
        draft=chosen_draft,
        dry_run=dry_run,
    )
    if blockers:
        decision = "blocked"
    elif dry_run:
        decision = "dry-run-first"
    elif chosen_draft:
        decision = "arm-draft-auto-ship"
    else:
        decision = "arm-ready-auto-ship"
    human_gates = (
        "Running `make ship-arm` is a shipping approval: the existing Stop hook may commit, push, create a PR, wait for CI/review, merge, and delete the remote branch when its gates pass.",
        "Ready auto-merge remains a human shipping decision; use `DRAFT=true` when review or claim risk remains.",
        "Private real-eval mode and benchmark/performance claim wording require human approval before using `REAL_EVAL=auto` or `REAL_EVAL=async` as evidence.",
        "Architecture tradeoffs and ADR decisions are not decided by this plan.",
    )
    return AutoShipPlan(
        decision=decision,
        branch=branch_name,
        issue=issue_number,
        surface=surface,
        recommended_command=recommended_command,
        dry_run_command=dry_run_command,
        blockers=tuple(_dedupe_preserve_order(blockers)),
        warnings=tuple(_dedupe_preserve_order(warnings)),
        evidence=tuple(_dedupe_preserve_order(evidence)),
        human_gates=human_gates,
    )


def _make_ship_arm_command(*, ttl: str, real_eval: str, draft: bool, dry_run: bool) -> str:
    return " ".join(
        (
            "make",
            "ship-arm",
            f"TTL={shlex.quote(ttl)}",
            f"REAL_EVAL={shlex.quote(real_eval)}",
            f"DRAFT={'true' if draft else 'false'}",
            f"DRY_RUN={1 if dry_run else 0}",
        )
    )


def render_auto_ship_plan(
    plan: AutoShipPlan,
    *,
    task_id: str | None,
    changed_files: Sequence[str],
    pr: str | None,
    repo_root: Path,
) -> str:
    lines = [
        "# Auto-Ship Plan",
        "",
        "- Plan only. This command does not arm auto-ship, commit, push, create/merge/close PRs, delete branches, force-push, or run private eval.",
        "- It bridges the agent-loop reports to the existing `make ship-arm` Stop-hook pipeline.",
        "",
        "## Decision",
        "",
        f"- Decision: `{plan.decision}`",
        f"- Task: `{task_id or 'N/A'}`",
        f"- PR: `{_validate_pr_selector(pr) if pr else 'N/A'}`",
        f"- Branch: `{_sanitize_inline_text(plan.branch)}`",
        f"- Issue from branch: `{plan.issue or 'N/A'}`",
        f"- Surface: `{plan.surface.surface}`",
        f"- Surface confidence: `{plan.surface.confidence}`",
        f"- Required reviewer: `{plan.surface.reviewer_type}`",
        "",
        "## Existing Auto-Ship Path",
        "",
        "- `make ship-arm` writes `.claude/.ship-armed`.",
        "- The existing Stop hook then runs the repository auto-ship pipeline once and disarms.",
        "- `DRY_RUN=1` echoes mutating commands to `.claude/.ship-dryrun.log` instead of executing them.",
        "- `DRAFT=true` creates a draft PR so the review gate stops before ready merge.",
        "",
        "## Recommended Command",
        "",
        "```bash",
        _sanitize_command_text(plan.recommended_command),
        "```",
        "",
        "## Dry-Run Rehearsal",
        "",
        "```bash",
        _sanitize_command_text(plan.dry_run_command),
        "```",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in plan.blockers) if plan.blockers else lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in plan.warnings) if plan.warnings else lines.append("- None")
    lines.extend(["", "## Evidence", ""])
    lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in plan.evidence)
    if plan.surface.disallowed_claims:
        lines.extend(["", "## Disallowed Claims", ""])
        lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in plan.surface.disallowed_claims)
    lines.extend(["", "## Human Gates", ""])
    lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in plan.human_gates)
    lines.extend(["", "## Changed Files", ""])
    normalized_paths: set[str] = set()
    for raw in changed_files:
        item = _normalize_changed_file(raw, repo_root=repo_root)
        if item:
            normalized_paths.add(item)
    normalized = [_display_path(path, repo_root=repo_root) for path in sorted(normalized_paths)]
    lines.extend(f"- `{path}`" for path in normalized) if normalized else lines.append("- None supplied")
    lines.extend(
        [
            "",
            "## Next Safe Commands",
            "",
            "```bash",
            "python3 scripts/agent_loop.py approval-packet --from-git",
            "python3 scripts/agent_loop.py readiness-score --from-git",
            "python3 scripts/agent_loop.py auto-ship-plan --from-git --dry-run",
            "make ship-status",
            "```",
            "",
        ]
    )
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def write_auto_ship_prepare(
    *,
    issue: str | None = None,
    target_branch: str | None = None,
    branch_type: str = "chore",
    slug: str = "agent-loop-auto-ship",
    create_branch: bool = False,
    confirm_human_approved: bool = False,
    ttl: str = "2h",
    real_eval: str | None = None,
    draft: bool = True,
    dry_run: bool = True,
    out: Path = DEFAULT_AUTO_SHIP_PREPARE,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, AutoShipPrepareReport, str]:
    report = build_auto_ship_prepare(
        issue=issue,
        target_branch=target_branch,
        branch_type=branch_type,
        slug=slug,
        create_branch=create_branch,
        confirm_human_approved=confirm_human_approved,
        ttl=ttl,
        real_eval=real_eval,
        draft=draft,
        dry_run=dry_run,
        repo_root=repo_root,
    )
    if create_branch and confirm_human_approved and not report.blockers and report.target_branch:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "switch", "-c", report.target_branch],
            capture_output=True,
            text=True,
            check=False,
        )
        report = AutoShipPrepareReport(
            result="branch-created" if result.returncode == 0 else "branch-create-failed",
            current_branch=report.current_branch,
            target_branch=report.target_branch,
            branch_command=report.branch_command,
            ship_arm_command=report.ship_arm_command,
            blockers=report.blockers if result.returncode == 0 else (*report.blockers, "git switch -c failed"),
            warnings=report.warnings,
            evidence=(*report.evidence, f"git switch returncode={result.returncode}"),
            created=result.returncode == 0,
            returncode=result.returncode,
        )
    rendered = render_auto_ship_prepare(report)
    out = _default_output(out, DEFAULT_AUTO_SHIP_PREPARE, "auto_ship_prepare.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, report, rendered


def build_auto_ship_prepare(
    *,
    issue: str | None,
    target_branch: str | None,
    branch_type: str,
    slug: str,
    create_branch: bool,
    confirm_human_approved: bool,
    ttl: str,
    real_eval: str | None,
    draft: bool,
    dry_run: bool,
    repo_root: Path,
) -> AutoShipPrepareReport:
    current = _current_branch(repo_root) or "unknown"
    blockers: list[str] = []
    warnings: list[str] = []
    evidence: list[str] = [f"current branch={current}"]
    if not re.fullmatch(r"\s*\d+\s*[smhd]\s*", ttl, flags=re.IGNORECASE):
        raise ValueError("auto-ship ttl must look like 30m, 2h, or 1d")
    if real_eval is not None and real_eval not in {"auto", "skip", "async"}:
        raise ValueError("auto-ship real_eval must be auto, skip, or async")
    if issue is not None and not re.fullmatch(r"\d{1,10}", issue):
        raise ValueError("issue must be a numeric GitHub issue number")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", branch_type):
        raise ValueError("branch type must be a safe branch prefix such as chore, docs, or feat")
    if target_branch:
        target = _validate_branch_name(target_branch)
    elif issue:
        target = _validate_branch_name(f"{branch_type}/issue-{issue}-{_slugify(slug)}")
    else:
        target = None
    current_issue = _issue_from_branch(current)
    current_ready = bool(
        current_issue
        and current not in {"HEAD", "main", "master"}
        and not current.startswith("release/")
    )
    if current_ready:
        target = current
        evidence.append(f"current branch issue=#{current_issue}")
    else:
        warnings.append("current branch is not ready for `make ship-arm`; create or switch to an ADR 0007 branch first")
    if not target:
        blockers.append("provide --issue <N> or --target-branch <type>/issue-<N>-<slug>")
    elif not _issue_from_branch(target):
        blockers.append("target branch must include an ADR 0007 issue number")
    elif create_branch and _branch_exists(target, repo_root=repo_root):
        blockers.append(f"target branch already exists: `{target}`")
    if create_branch and not confirm_human_approved:
        blockers.append("--confirm-human-approved is required to create a local branch")
    if (repo_root / ".claude" / ".ship-armed").exists():
        warnings.append("ship-arm is already armed; disarm before preparing another shipping branch")
    chosen_real_eval = real_eval or "skip"
    if real_eval is None:
        warnings.append("REAL_EVAL defaults to skip; choose auto/async only after human private-eval decision")
    branch_command = (
        f"python3 scripts/agent_loop.py auto-ship-prepare --issue {issue or '<ISSUE>'} "
        f"--type {shlex.quote(branch_type)} --slug {shlex.quote(slug)} "
        "--create-branch --confirm-human-approved"
    )
    if target_branch:
        branch_command = (
            f"python3 scripts/agent_loop.py auto-ship-prepare --target-branch {shlex.quote(target_branch)} "
            "--create-branch --confirm-human-approved"
        )
    ship_arm_command = _make_ship_arm_command(ttl=ttl, real_eval=chosen_real_eval, draft=draft, dry_run=dry_run)
    if blockers:
        result = "blocked"
    elif current_ready and not create_branch:
        result = "ready-for-ship-arm"
    elif create_branch:
        result = "ready-to-create-branch"
    else:
        result = "needs-branch"
    if target:
        evidence.append(f"target branch={target}")
    return AutoShipPrepareReport(
        result=result,
        current_branch=current,
        target_branch=target,
        branch_command=branch_command,
        ship_arm_command=ship_arm_command,
        blockers=tuple(_dedupe_preserve_order(blockers)),
        warnings=tuple(_dedupe_preserve_order(warnings)),
        evidence=tuple(_dedupe_preserve_order(evidence)),
    )


def _branch_exists(branch: str, *, repo_root: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def render_auto_ship_prepare(report: AutoShipPrepareReport) -> str:
    lines = [
        "# Auto-Ship Prepare",
        "",
        "- This command prepares the local branch state for the existing `make ship-arm` pipeline.",
        "- By default it writes this report only. It creates a local branch only with `--create-branch --confirm-human-approved`.",
        "- It does not arm auto-ship, commit, push, create/merge/close PRs, delete branches, force-push, run private eval, or approve claims.",
        "",
        "## Result",
        "",
        f"- Result: `{report.result}`",
        f"- Current branch: `{_sanitize_inline_text(report.current_branch)}`",
        f"- Target branch: `{_sanitize_inline_text(report.target_branch or 'N/A')}`",
        f"- Branch created: `{report.created}`",
        f"- Return code: `{report.returncode if report.returncode is not None else 'N/A'}`",
        "",
        "## Branch Preparation Command",
        "",
        "```bash",
        _sanitize_command_text(report.branch_command),
        "```",
        "",
        "## Next Ship-Arm Command",
        "",
        "```bash",
        _sanitize_command_text(report.ship_arm_command),
        "```",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in report.blockers) if report.blockers else lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in report.warnings) if report.warnings else lines.append("- None")
    lines.extend(["", "## Evidence", ""])
    lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in report.evidence)
    lines.extend(
        [
            "",
            "## Next Safe Commands",
            "",
            "```bash",
            "python3 scripts/agent_loop.py auto-ship-plan --from-git --dry-run",
            "make ship-status",
            "```",
            "",
        ]
    )
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


GATE_BRIEF_CHOICES = {
    "task",
    "plan",
    "review",
    "claim",
    "ship",
    "pr-create",
    "merge",
    "close",
    "branch-delete",
    "force-push",
    "private-real-eval",
    "benchmark-claim",
    "architecture",
}


def write_gate_brief(
    *,
    gate: str,
    task_id: str | None = None,
    changed_files: Sequence[str] = (),
    pr: str | None = None,
    out: Path = DEFAULT_GATE_BRIEF,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    rendered = render_gate_brief(
        gate=gate,
        task_id=task_id,
        changed_files=changed_files,
        pr=pr,
        repo_root=repo_root,
    )
    out = _default_output(out, DEFAULT_GATE_BRIEF, "gate_brief.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_gate_brief(
    *,
    gate: str,
    task_id: str | None,
    changed_files: Sequence[str],
    pr: str | None,
    repo_root: Path,
) -> str:
    if gate not in GATE_BRIEF_CHOICES:
        raise ValueError("--gate must be one of: " + ", ".join(sorted(GATE_BRIEF_CHOICES)))
    mapped = {
        "pr-create": "ship",
        "merge": "ship",
        "close": "ship",
        "branch-delete": "ship",
        "force-push": "ship",
        "private-real-eval": "claim",
        "benchmark-claim": "claim",
        "architecture": "claim",
    }.get(gate, gate)
    if mapped in {"task", "plan", "review", "claim", "ship"}:
        points = build_decision_points(
            task_id=task_id,
            batch=None,
            review_followups=None,
            gate=mapped,
            changed_files=changed_files,
            pr=pr,
            repo_root=repo_root,
        )
    else:
        points = [_no_input_decision_point()]
    rendered = render_decision_brief(points, repo_root=repo_root)
    return (
        f"# Gate Brief: {gate}\n\n"
        "- Human gates are decision points, not automation failures.\n"
        "- This command explains options and does not execute the gated action.\n\n"
        + rendered.split("\n", 1)[1]
    )


def write_manifest(
    *,
    changed_files: Sequence[str] = (),
    command: str = "manual",
    outputs: Sequence[Path] = (),
    out: Path = DEFAULT_MANIFEST,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, dict[str, object]]:
    manifest = build_manifest(
        changed_files=changed_files,
        command=command,
        outputs=outputs,
        repo_root=repo_root,
    )
    out = _default_output(out, DEFAULT_MANIFEST, "manifest.json", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return safe_out, manifest


def build_manifest(
    *,
    changed_files: Sequence[str],
    command: str,
    outputs: Sequence[Path],
    repo_root: Path,
) -> dict[str, object]:
    normalized = sorted(
        {
            item
            for path in changed_files
            if (item := _normalize_changed_file(path, repo_root=repo_root))
        }
    )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_head": _current_git_head(repo_root) or "unknown",
        "branch": _current_branch(repo_root) or "unknown",
        "command": _sanitize_inline_text(command),
        "changed_files_hash": _changed_files_hash(normalized, repo_root=repo_root),
        "changed_files": [_display_path(path, repo_root=repo_root) for path in normalized],
        "outputs": [_display_path(_repo_path(path if path.is_absolute() else repo_root / path, repo_root), repo_root=repo_root) for path in outputs],
    }


def _changed_files_hash(changed_files: Sequence[str], *, repo_root: Path) -> str:
    payload: list[dict[str, str]] = []
    for path in sorted(changed_files):
        display = _display_path(path, repo_root=repo_root)
        content_hash = "not-read"
        normalized = _normalize_changed_file(path, repo_root=repo_root)
        candidate = repo_root / normalized
        if normalized != "[redacted-local-path]" and not _privacy_sensitive_path(normalized) and candidate.is_file():
            try:
                content_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
            except OSError:
                content_hash = "unreadable"
        payload.append({"path": display, "content_hash": content_hash})
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _manifest_freshness(
    *,
    changed_files: Sequence[str],
    repo_root: Path,
) -> dict[str, object]:
    path = repo_root / "reports" / "agent_loop" / "manifest.json"
    current_hash = _changed_files_hash(changed_files, repo_root=repo_root)
    if not path.exists():
        return {"exists": False, "current": False, "reason": "manifest not found"}
    try:
        payload = json.loads(_read_text(path))
    except json.JSONDecodeError:
        return {"exists": True, "current": False, "reason": "manifest is invalid JSON"}
    recorded = payload.get("changed_files_hash") if isinstance(payload, dict) else None
    return {
        "exists": True,
        "current": recorded == current_hash,
        "reason": "hash match" if recorded == current_hash else "changed files hash mismatch",
        "recorded_hash": recorded or "unknown",
        "current_hash": current_hash,
    }


def write_pr_body_check(
    *,
    body: Path,
    changed_files: Sequence[str] = (),
    branch: str | None = None,
    out: Path = DEFAULT_PR_BODY_CHECK,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, int, str]:
    body_path = _resolve_input_path(body, repo_root=repo_root)
    if not body_path.exists():
        raise ValueError(f"PR body file not found: {_display_path(str(body), repo_root=repo_root)}")
    text = _read_text(body_path)
    findings = check_pr_body_text(text, changed_files=changed_files, branch=branch, repo_root=repo_root)
    rendered = render_pr_body_check(findings, body_path=body_path, changed_files=changed_files, branch=branch, repo_root=repo_root)
    out = _default_output(out, DEFAULT_PR_BODY_CHECK, "pr_body_check.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, 1 if findings else 0, rendered


def check_pr_body_text(
    text: str,
    *,
    changed_files: Sequence[str],
    branch: str | None,
    repo_root: Path,
) -> list[PRBodyFinding]:
    findings: list[PRBodyFinding] = []
    sanitized = _sanitize_dynamic_text(text)
    closers = re.findall(r"\b(?:Closes|Fixes|Resolves)\s+#(\d+)\b", sanitized, flags=re.IGNORECASE)
    branch_issue = _issue_from_branch(branch or _current_branch(repo_root) or "")
    if not closers:
        findings.append(PRBodyFinding("high", "missing Closes/Fixes/Resolves issue reference", "Add `Closes #<issue>` matching the branch issue."))
    elif branch_issue and branch_issue not in closers:
        findings.append(PRBodyFinding("high", "PR body issue reference does not match branch issue", f"Use `Closes #{branch_issue}` or rename the branch."))
    if "### 5b. Real-data delta" not in sanitized:
        findings.append(PRBodyFinding("high", "missing §5b Real-data delta section", "Keep the PR template §5b section."))
    else:
        section = _section_after_heading(sanitized, "### 5b. Real-data delta")
        load_bearing = [path for path in changed_files if _normalize_changed_file(path) != "[redacted-local-path]" and (is_load_bearing(_normalize_changed_file(path)) or _normalize_changed_file(path).startswith("eval/"))]
        weak = not section.strip() or section.strip().lower() in {"n/a", "n/a.", "none", "todo", "tbd"}
        if load_bearing and weak:
            findings.append(PRBodyFinding("critical", "load-bearing change has weak §5b content", "Attach aggregate-only real-data delta or truthful no-behavior-change attestation."))
    surface = classify_changed_files(changed_files)
    for claim in audit_claim_text(_claim_scan_text_from_pr_body(sanitized), surface):
        findings.append(PRBodyFinding(claim.severity, claim.issue, f"Get review from {claim.reviewer} or remove the claim."))
    for issue, pattern in _privacy_audit_patterns().items():
        if pattern.search(text):
            findings.append(PRBodyFinding("critical", f"private raw value detected in PR body: {issue}", "Redact private raw values before PR creation."))
    return _dedupe_pr_body_findings(findings)


def _claim_scan_text_from_pr_body(text: str) -> str:
    kept: list[str] = []
    skip_section = False
    for line in text.splitlines():
        lowered = line.lower()
        if "disallowed claims" in lowered or "human-gated decisions" in lowered:
            skip_section = True
            continue
        if skip_section and re.match(r"^#{1,3}\s+", line):
            skip_section = False
        if skip_section:
            continue
        if any(token in lowered for token in ("do not claim", "claim boundary", "no benchmark", "not a benchmark", "without sufficient eval provenance")):
            continue
        kept.append(line)
    return "\n".join(kept)


def _section_after_heading(text: str, heading: str) -> str:
    index = text.find(heading)
    if index < 0:
        return ""
    rest = text[index + len(heading):]
    match = re.search(r"^#{1,3}\s+", rest, re.MULTILINE)
    return rest[: match.start()] if match else rest


def _dedupe_pr_body_findings(findings: Iterable[PRBodyFinding]) -> list[PRBodyFinding]:
    seen: set[tuple[str, str]] = set()
    out: list[PRBodyFinding] = []
    for finding in findings:
        key = (finding.severity, finding.issue)
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    return out


def render_pr_body_check(
    findings: Sequence[PRBodyFinding],
    *,
    body_path: Path,
    changed_files: Sequence[str],
    branch: str | None,
    repo_root: Path,
) -> str:
    lines = [
        "# PR Body Check",
        "",
        f"- Body: `{_display_path(_repo_path(body_path, repo_root), repo_root=repo_root)}`",
        f"- Branch: `{_sanitize_inline_text(branch or _current_branch(repo_root) or 'unknown')}`",
        f"- Result: `{'fail' if findings else 'pass'}`",
        "- This check does not create, update, merge, or close a PR.",
        "",
        "## Changed Files",
        "",
    ]
    lines.extend(f"- `{_display_path(path)}`" for path in changed_files) if changed_files else lines.append("- `N/A`")
    lines.extend(["", "## Findings", ""])
    if findings:
        for finding in findings:
            lines.extend(
                [
                    f"- Severity: `{finding.severity}`",
                    f"  - Issue: {_sanitize_dynamic_text(finding.issue)}",
                    f"  - Remediation: {_sanitize_dynamic_text(finding.remediation)}",
                ]
            )
    else:
        lines.append("- None")
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def write_ci_ingest(
    *,
    logs: Sequence[Path] = (),
    pr: str | None = None,
    out: Path = DEFAULT_CI_INGEST,
    tasks_dir: Path = DEFAULT_CI_FOLLOWUPS_DIR,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, Path, int, str]:
    findings, sources = collect_ci_findings(logs=logs, pr=pr, repo_root=repo_root)
    out = _default_output(out, DEFAULT_CI_INGEST, "ci_ingest.md", repo_root=repo_root)
    tasks_dir = repo_root / "reports" / "agent_loop" / "ci_followups" if tasks_dir == DEFAULT_CI_FOLLOWUPS_DIR else tasks_dir
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_tasks = _safe_output_path(tasks_dir, repo_root=repo_root)
    rendered = render_ci_ingest(findings, sources=sources, tasks_dir=safe_tasks, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_tasks.mkdir(parents=True, exist_ok=True)
    for stale in safe_tasks.glob("*.md"):
        stale.unlink()
    safe_out.write_text(rendered, encoding="utf-8")
    for index, finding in enumerate(findings, start=1):
        (safe_tasks / f"{index:03d}-{_slugify(finding.summary)}.md").write_text(
            render_ci_followup_task(finding, index=index),
            encoding="utf-8",
        )
    return safe_out, safe_tasks, len(findings), rendered


def collect_ci_findings(
    *,
    logs: Sequence[Path],
    pr: str | None,
    repo_root: Path,
) -> tuple[list[CIFinding], list[str]]:
    blocks: list[str] = []
    sources: list[str] = []
    for log in logs:
        path = _resolve_input_path(log, repo_root=repo_root)
        if not path.exists():
            raise ValueError(f"CI log not found: {_display_path(str(log), repo_root=repo_root)}")
        blocks.append(_read_text(path))
        sources.append(f"file `{_display_path(_repo_path(path, repo_root), repo_root=repo_root)}`")
    if pr:
        blocks.append(_ci_text_from_pr(pr, repo_root=repo_root))
        sources.append(f"PR `{_validate_pr_selector(pr)}`")
    if not blocks:
        raise ValueError("ci-ingest requires --log or --pr")
    findings: list[CIFinding] = []
    for block in blocks:
        findings.extend(_extract_ci_findings(block, pr=pr))
    return _dedupe_ci_findings(findings), sources


def _ci_text_from_pr(pr: str, *, repo_root: Path) -> str:
    safe_pr = _validate_pr_selector(pr)
    try:
        result = subprocess.run(
            ["gh", "pr", "checks", safe_pr, "--json", "name,conclusion,state,detailsUrl,link"],
            cwd=repo_root,
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"could not read CI checks from PR {safe_pr}") from exc
    return _sanitize_dynamic_text(result.stdout)


def _extract_ci_findings(text: str, *, pr: str | None) -> list[CIFinding]:
    sanitized = _sanitize_dynamic_text(text)
    lowered = sanitized.lower()
    findings: list[CIFinding] = []
    test_match = re.search(r"(tests/test_[\w./-]+\.py)", sanitized)
    if any(token in lowered for token in ("assertionerror", "failed", "pytest", '"conclusion":"failure"', '"state":"failure"')):
        test_file = test_match.group(1) if test_match else "tests/test_<target>.py"
        findings.append(CIFinding("test-failure", f"CI test failure near {test_file}", "ci log", f"python3 -m pytest {test_file} -q"))
    if any(token in lowered for token in ("git diff --check", "trailing whitespace", "whitespace error")):
        findings.append(CIFinding("safe-local-fix-candidate", "Whitespace or diff-check failure", "ci log", "git diff --check"))
    if any(token in lowered for token in ("branch", "closes #", "adr 0007", "issue reference")):
        findings.append(CIFinding("branch-issue", "Branch/issue convention failure", "ci log", "make check-branch"))
    if "5b" in lowered or "real-data delta" in lowered:
        validation = f"python3 scripts/check_branch_and_issue.py --check-5b {pr}" if pr else "python3 scripts/check_branch_and_issue.py --check-5b <PR_NUMBER>"
        findings.append(CIFinding("manual-gated", "§5b real-data delta gate needs human-readable evidence", "ci log", validation))
    if any(token in lowered for token in ("privacy", "doc_id", "chunk_id", "raw evidence", "private")):
        findings.append(CIFinding("manual-gated", "Privacy/governance failure requires redaction review", "ci log", "python3 scripts/_governance.py --check-eval-privacy"))
    if not findings:
        findings.append(CIFinding("unknown", "CI failure could not be classified safely", "ci log", "python3 scripts/agent_loop.py gate-brief --gate review"))
    return findings


def _dedupe_ci_findings(findings: Iterable[CIFinding]) -> list[CIFinding]:
    seen: set[tuple[str, str, str]] = set()
    out: list[CIFinding] = []
    for finding in findings:
        key = (finding.lane, finding.summary, finding.validation)
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    return out


def render_ci_ingest(
    findings: Sequence[CIFinding],
    *,
    sources: Sequence[str],
    tasks_dir: Path,
    repo_root: Path,
) -> str:
    lines = [
        "# CI Ingest",
        "",
        "- Read-only CI failure triage. It does not push, re-run CI, create/merge/close PRs, delete branches, or force-push.",
        f"- Follow-up briefs: `{_display_path(_repo_path(tasks_dir, repo_root), repo_root=repo_root)}`",
        "",
        "## Sources",
        "",
    ]
    lines.extend(f"- {_sanitize_dynamic_text(source)}" for source in sources)
    lines.extend(["", "## Findings", ""])
    for index, finding in enumerate(findings, start=1):
        lines.extend(
            [
                f"### {index:03d}. {finding.summary}",
                "",
                f"- Lane: `{finding.lane}`",
                f"- Source: `{_sanitize_dynamic_text(finding.source)}`",
                f"- Suggested validation: `{_sanitize_command_text(finding.validation)}`",
                "",
            ]
        )
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def render_ci_followup_task(finding: CIFinding, *, index: int) -> str:
    return _sanitize_dynamic_text(
        f"""# CI Follow-up {index:03d}: {finding.summary}

- Classification: `ci_followup`
- Lane: `{finding.lane}`
- Source: `{finding.source}`

## Goal

Resolve the CI signal with the smallest local change, or document why human approval is required.

## Expected Evidence

Focused validation output and updated handoff evidence.

## Verification

```bash
{_ensure_git_diff_check(finding.validation)}
```
"""
    )


def write_stacked_risk(
    *,
    branch: str,
    pr_json: Path | None = None,
    out: Path = DEFAULT_STACKED_RISK,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    items = _stacked_pr_items(branch=branch, pr_json=pr_json, repo_root=repo_root)
    rendered = render_stacked_risk(branch=branch, items=items)
    out = _default_output(out, DEFAULT_STACKED_RISK, "stacked_risk.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def _stacked_pr_items(*, branch: str, pr_json: Path | None, repo_root: Path) -> list[dict[str, object]]:
    safe_branch = _sanitize_inline_text(branch)
    if pr_json is not None:
        path = _resolve_input_path(pr_json, repo_root=repo_root)
        payload = json.loads(_read_text(path))
        if not isinstance(payload, list):
            raise ValueError("PR state JSON must be an array")
        return [item for item in payload if isinstance(item, dict) and str(item.get("baseRefName") or "") == safe_branch]
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--base",
                safe_branch,
                "--json",
                "number,title,headRefName,baseRefName,isDraft,reviewDecision,mergeStateStatus",
            ],
            cwd=repo_root,
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"could not read dependent PRs for branch {safe_branch}") from exc
    payload = json.loads(result.stdout)
    if not isinstance(payload, list):
        raise ValueError("gh pr list JSON must be an array")
    return [item for item in payload if isinstance(item, dict)]


def render_stacked_risk(*, branch: str, items: Sequence[dict[str, object]]) -> str:
    lines = [
        "# Stacked PR Dependency Risk",
        "",
        "- Read-only dependent PR check. It does not merge, close, delete branches, push, or force-push.",
        f"- Branch: `{_sanitize_inline_text(branch)}`",
        f"- Dependent open PR count: `{len(items)}`",
        "",
        "## Dependents",
        "",
    ]
    if items:
        for item in items:
            lines.append(f"- #{item.get('number', 'N/A')} {_sanitize_inline_text(str(item.get('title') or 'Untitled'))} from `{_sanitize_inline_text(str(item.get('headRefName') or 'unknown'))}`")
    else:
        lines.append("- None detected.")
    lines.extend(
        [
            "",
            "## Human Gate",
            "",
            "- Branch deletion, PR merge, PR close, and force-push still require explicit human approval.",
            "- If dependents exist, do not delete the branch until child PRs are rebased or intentionally retained.",
            "",
        ]
    )
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def write_patch_proposal(
    *,
    changed_files: Sequence[str] = (),
    review_plan: Path | None = None,
    out: Path = DEFAULT_PATCH_PROPOSAL,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    rendered = render_patch_proposal(changed_files=changed_files, review_plan=review_plan, repo_root=repo_root)
    out = _default_output(out, DEFAULT_PATCH_PROPOSAL, "patch_proposal.diff", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_patch_proposal(
    *,
    changed_files: Sequence[str],
    review_plan: Path | None,
    repo_root: Path,
) -> str:
    header = [
        "# Agent-loop safe patch proposal. Dry-run only; review before applying.",
        "# Scope: whitespace/final-newline diff for public-safe allowlisted text files.",
    ]
    if review_plan is not None:
        path = _resolve_input_path(review_plan, repo_root=repo_root)
        if path.exists():
            header.append(f"# Review plan: {_display_path(_repo_path(path, repo_root), repo_root=repo_root)}")
    diffs: list[str] = []
    for raw in changed_files:
        rel = _normalize_changed_file(raw, repo_root=repo_root)
        if not rel or rel == "[redacted-local-path]" or _privacy_sensitive_path(rel):
            continue
        path = repo_root / rel
        if not path.is_file():
            continue
        if path.name not in SAFE_FIX_NAMES and path.suffix.lower() not in SAFE_FIX_SUFFIXES:
            continue
        try:
            before = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        after = _fix_text_whitespace(before)
        if after != before:
            diffs.append(_unified_diff(before, after, fromfile=f"a/{rel}", tofile=f"b/{rel}"))
    if not diffs:
        diffs.append("# No safe patch proposal generated.")
    return _sanitize_dynamic_text("\n".join([*header, *diffs, ""])).rstrip() + "\n"


def write_adr_reservation(
    *,
    title: str,
    out: Path = DEFAULT_ADR_RESERVATION,
    draft_out: Path = DEFAULT_ADR_DRAFT,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, Path, str]:
    number = _next_adr_number(repo_root)
    draft = render_adr_draft(number=number, title=title)
    rendered = render_adr_reservation(number=number, title=title, draft_path=draft_out)
    out = _default_output(out, DEFAULT_ADR_RESERVATION, "adr_reservation.md", repo_root=repo_root)
    draft_out = _default_output(draft_out, DEFAULT_ADR_DRAFT, "adr_draft.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_draft = _safe_output_path(draft_out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_draft.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    safe_draft.write_text(draft, encoding="utf-8")
    return safe_out, safe_draft, rendered


def _next_adr_number(repo_root: Path) -> int:
    adr_dir = repo_root / "docs" / "adr"
    numbers: list[int] = []
    if adr_dir.is_dir():
        for path in adr_dir.glob("*.md"):
            match = re.match(r"(\d{4})-", path.name)
            if match:
                numbers.append(int(match.group(1)))
    return (max(numbers) + 1) if numbers else 1


def render_adr_reservation(*, number: int, title: str, draft_path: Path) -> str:
    slug = _slugify(title)
    final_path = f"docs/adr/{number:04d}-{slug}.md"
    return _sanitize_dynamic_text(
        f"""# ADR Reservation Assistant

- Suggested ADR number: `{number:04d}`
- Suggested final path: `{final_path}`
- Draft artifact: `{_display_path(draft_path.as_posix())}`
- This command does not create or modify `docs/adr/`; human approval is required before reserving or committing an ADR.

## Human Checks

- Confirm no open PR already reserves ADR `{number:04d}`.
- Confirm this is a load-bearing decision, new measurement surface, or durable architecture tradeoff.
- Confirm alternatives and consequences are clear.
"""
    )


def render_adr_draft(*, number: int, title: str) -> str:
    slug = _slugify(title)
    return _sanitize_dynamic_text(
        f"""# ADR {number:04d}: {title}

- Status: draft
- Suggested final path: `docs/adr/{number:04d}-{slug}.md`

## Context

Describe the load-bearing decision, measurement surface, or architecture tradeoff.

## Decision

TBD by human review.

## Alternatives

- Option A:
- Option B:

## Consequences

- Positive:
- Negative:
- Validation:
"""
    )


def write_dashboard_html(
    *,
    task_id: str | None = None,
    changed_files: Sequence[str] = (),
    pr: str | None = None,
    out: Path = DEFAULT_DASHBOARD_HTML,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    state = build_loop_state(
        task_id=task_id,
        batch=None,
        review_followups=None,
        changed_files=changed_files,
        pr=pr,
        repo_root=repo_root,
    )
    markdown = render_dashboard(state, repo_root=repo_root)
    rendered = render_dashboard_html(markdown)
    out = _default_output(out, DEFAULT_DASHBOARD_HTML, "dashboard.html", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_dashboard_html(markdown: str) -> str:
    escaped = html.escape(_sanitize_dynamic_text(markdown))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>BidMate Agent Loop Dashboard</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #17202a; background: #f7f8fa; }}
    main {{ max-width: 1080px; margin: 0 auto; background: white; border: 1px solid #d8dee4; border-radius: 8px; padding: 24px; }}
    pre {{ white-space: pre-wrap; background: #f0f3f6; padding: 16px; border-radius: 6px; overflow-x: auto; }}
  </style>
</head>
<body>
  <main>
    <pre>{escaped}</pre>
  </main>
</body>
</html>
"""


def write_ship_command_pack(
    *,
    pr: str | None = None,
    branch: str | None = None,
    out: Path = DEFAULT_SHIP_COMMANDS,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    rendered = render_ship_command_pack(pr=pr, branch=branch, repo_root=repo_root)
    out = _default_output(out, DEFAULT_SHIP_COMMANDS, "ship_commands.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_ship_command_pack(*, pr: str | None, branch: str | None, repo_root: Path) -> str:
    safe_pr = _validate_pr_selector(pr) if pr else "<PR_NUMBER>"
    branch_name = _sanitize_inline_text(branch or _current_branch(repo_root) or "<branch>")
    shell_branch = shlex.quote(branch_name)
    lines = [
        "# Ship Command Pack",
        "",
        "- Command suggestions only. Choose one shipping path after explicit approval.",
        "- This command did not push, create/merge/close PRs, delete branches, or force-push.",
        "",
        "## Safe Local Checks",
        "",
        "```bash",
        "python3 scripts/agent_loop.py auto-ship-prepare --issue <ISSUE> --create-branch --confirm-human-approved",
        "python3 scripts/agent_loop.py approval-packet --from-git",
        "python3 scripts/agent_loop.py ship-simulate --from-git",
        "python3 scripts/agent_loop.py auto-ship-plan --from-git --dry-run",
        "make check-branch",
        "git diff --check",
        "```",
        "",
        "## Primary End-to-End Ship Path",
        "",
        "```bash",
        "# plan only: python3 scripts/agent_loop.py auto-ship-plan --from-git --draft --dry-run",
        "# after approval, arm the single end-to-end Stop-hook pipeline:",
        "# make ship-arm REAL_EVAL=skip DRAFT=true DRY_RUN=1",
        "```",
        "",
        "## Manual Fallback Commands",
        "",
        "Use these action-by-action commands only when the end-to-end `make ship-arm` path is not appropriate.",
        "",
        "```bash",
        f"# create PR after approval: python3 scripts/agent_loop.py human-gated-exec --action pr-create --branch {shell_branch} --body reports/agent_loop/pr_body.md --confirm-human-approved",
        f"# review gate before merge/close/delete: make ship-review-gate PR={safe_pr}",
        f"# push after approval: python3 scripts/agent_loop.py human-gated-exec --action push --branch {shell_branch} --confirm-human-approved",
        f"# merge after approval: python3 scripts/agent_loop.py human-gated-exec --action pr-merge --pr {safe_pr} --confirm-review-gate-passed --confirm-human-approved",
        f"# close after approval: python3 scripts/agent_loop.py human-gated-exec --action pr-close --pr {safe_pr} --confirm-review-gate-passed --confirm-human-approved",
        f"# delete remote branch after dependent check and approval: python3 scripts/agent_loop.py human-gated-exec --action branch-delete --branch {shell_branch} --confirm-dependents-reviewed --confirm-human-approved",
        f"# force-with-lease after explicit approval: python3 scripts/agent_loop.py human-gated-exec --action force-push --branch {shell_branch} --confirm-force-with-lease --confirm-human-approved",
        "```",
        "",
        "## Required Before Destructive Actions",
        "",
        "- Run `stacked-risk` for branch deletion or merge cleanup.",
        "- Verify unresolved review threads and CI status.",
        "- Verify no private raw data or overbroad benchmark/performance claim.",
        "",
    ]
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


HUMAN_GATED_ACTIONS = {"push", "pr-create", "pr-merge", "pr-close", "branch-delete", "force-push"}


def write_human_gated_exec(
    *,
    action: str,
    confirm_human_approved: bool,
    dry_run: bool = False,
    branch: str | None = None,
    pr: str | None = None,
    body: Path | None = None,
    base: str | None = None,
    title: str | None = None,
    draft: bool = True,
    confirm_review_gate_passed: bool = False,
    confirm_dependents_reviewed: bool = False,
    confirm_force_with_lease: bool = False,
    out: Path = DEFAULT_HUMAN_GATED_EXEC,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, HumanGatedExecPlan, str]:
    plan = build_human_gated_exec_plan(
        action=action,
        confirm_human_approved=confirm_human_approved,
        dry_run=dry_run,
        branch=branch,
        pr=pr,
        body=body,
        base=base,
        title=title,
        draft=draft,
        confirm_review_gate_passed=confirm_review_gate_passed,
        confirm_dependents_reviewed=confirm_dependents_reviewed,
        confirm_force_with_lease=confirm_force_with_lease,
        repo_root=repo_root,
    )
    if confirm_human_approved and not dry_run and not plan.blockers:
        result = subprocess.run(
            list(plan.command),
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        plan = HumanGatedExecPlan(
            action=plan.action,
            command=plan.command,
            blockers=plan.blockers,
            warnings=plan.warnings,
            dry_run=plan.dry_run,
            executed=True,
            returncode=result.returncode,
            stdout=_sanitize_dynamic_text(result.stdout or ""),
            stderr=_sanitize_dynamic_text(result.stderr or ""),
        )
    rendered = render_human_gated_exec(plan)
    out = _default_output(out, DEFAULT_HUMAN_GATED_EXEC, "human_gated_exec.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, plan, rendered


def build_human_gated_exec_plan(
    *,
    action: str,
    confirm_human_approved: bool,
    dry_run: bool,
    branch: str | None,
    pr: str | None,
    body: Path | None,
    base: str | None,
    title: str | None,
    draft: bool,
    confirm_review_gate_passed: bool,
    confirm_dependents_reviewed: bool,
    confirm_force_with_lease: bool,
    repo_root: Path,
) -> HumanGatedExecPlan:
    if action not in HUMAN_GATED_ACTIONS:
        raise ValueError("--action must be one of: " + ", ".join(sorted(HUMAN_GATED_ACTIONS)))
    blockers: list[str] = []
    warnings: list[str] = []
    if not confirm_human_approved:
        blockers.append("--confirm-human-approved is required before any remote state mutation")
    branch_needed = action in {"push", "force-push", "pr-create", "branch-delete"}
    current_branch = branch or (_current_branch(repo_root) if branch_needed else None)
    safe_branch = _validate_branch_name(current_branch) if current_branch else ""

    command: tuple[str, ...]
    if action == "push":
        if not safe_branch:
            blockers.append("--branch is required when the current branch is unknown")
        command = ("git", "push", "-u", "origin", safe_branch or "<branch>")
    elif action == "force-push":
        if not safe_branch:
            blockers.append("--branch is required for force-push")
        if not confirm_force_with_lease:
            blockers.append("--confirm-force-with-lease is required; plain force-push is not supported")
        command = ("git", "push", "--force-with-lease", "origin", safe_branch or "<branch>")
    elif action == "pr-create":
        if not safe_branch:
            blockers.append("--branch is required when the current branch is unknown")
        body_path = _resolve_input_path(body or DEFAULT_PR_BODY, repo_root=repo_root)
        if not body_path.exists():
            blockers.append("PR body file not found")
        else:
            findings = check_pr_body_text(_read_text(body_path), changed_files=_changed_files_from_git(repo_root), branch=safe_branch, repo_root=repo_root)
            if findings:
                blockers.append(f"PR body check has {len(findings)} finding(s)")
        command_parts = ["gh", "pr", "create", "--body-file", _display_path(_repo_path(body_path, repo_root), repo_root=repo_root)]
        if draft:
            command_parts.append("--draft")
        if base:
            command_parts.extend(["--base", _validate_branch_name(base, allow_protected=True)])
        if title:
            command_parts.extend(["--title", _sanitize_inline_text(title)])
        command = tuple(command_parts)
    elif action == "pr-merge":
        safe_pr = _validate_pr_selector(pr or "")
        if not confirm_review_gate_passed:
            blockers.append("--confirm-review-gate-passed is required before merge")
        command = ("gh", "pr", "merge", safe_pr, "--squash")
        warnings.append("merge command intentionally omits --delete-branch")
    elif action == "pr-close":
        safe_pr = _validate_pr_selector(pr or "")
        if not confirm_review_gate_passed:
            blockers.append("--confirm-review-gate-passed is required before close")
        command = ("gh", "pr", "close", safe_pr)
    else:
        if not safe_branch:
            blockers.append("--branch is required for branch-delete")
        dependents: list[dict[str, object]] = []
        if safe_branch:
            try:
                dependents = _stacked_pr_items(branch=safe_branch, pr_json=None, repo_root=repo_root)
            except ValueError as exc:
                blockers.append(f"could not verify dependent PRs: {exc}")
        if dependents and not confirm_dependents_reviewed:
            blockers.append(f"branch has {len(dependents)} dependent open PR(s); pass --confirm-dependents-reviewed only after human review")
        command = ("git", "push", "origin", "--delete", safe_branch or "<branch>")
    return HumanGatedExecPlan(
        action=action,
        command=command,
        blockers=tuple(_dedupe_preserve_order(blockers)),
        warnings=tuple(_dedupe_preserve_order(warnings)),
        dry_run=dry_run,
        executed=False,
    )


def _validate_branch_name(branch: str | None, *, allow_protected: bool = False) -> str:
    if not branch:
        return ""
    safe = _sanitize_inline_text(branch)
    if not allow_protected and safe in {"HEAD", "main", "master"}:
        raise ValueError("refusing gated action on HEAD/main/master branch")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", safe) or safe.startswith("-") or ".." in safe or safe.endswith(".lock"):
        raise ValueError("branch name contains unsafe characters")
    return safe


def render_human_gated_exec(plan: HumanGatedExecPlan) -> str:
    lines = [
        "# Human-Gated Execution",
        "",
        "- This command exists only for explicit human-approved execution of already gated operations.",
        "- It never bypasses review, claim, private real-eval, architecture, or dependency decisions.",
        f"- Action: `{plan.action}`",
        f"- Mode: `{'dry-run' if plan.dry_run else 'execute'}`",
        f"- Executed: `{plan.executed}`",
        f"- Return code: `{plan.returncode if plan.returncode is not None else 'N/A'}`",
        "",
        "## Command",
        "",
        "```bash",
        _sanitize_command_text(shlex.join(plan.command)),
        "```",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in plan.blockers) if plan.blockers else lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in plan.warnings) if plan.warnings else lines.append("- None")
    if plan.executed:
        lines.extend(
            [
                "",
                "## Execution Output",
                "",
                f"- stdout bytes: `{len(plan.stdout.encode('utf-8'))}`",
                f"- stderr bytes: `{len(plan.stderr.encode('utf-8'))}`",
            ]
        )
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def write_apply_queue_plan(
    *,
    confirm_human_approved: bool,
    queue_draft: Path = DEFAULT_QUEUE_DRAFT,
    plan_draft: Path = DEFAULT_PLAN_DRAFT,
    out: Path = DEFAULT_APPLY_QUEUE_PLAN,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    queue_path = _resolve_default_agent_loop_path(queue_draft, "queue_entry_draft.md", repo_root=repo_root)
    plan_path = _resolve_default_agent_loop_path(plan_draft, "plan_draft.md", repo_root=repo_root)
    if not queue_path.exists() or not plan_path.exists():
        raise ValueError("queue/plan drafts not found; run draft-task first")
    queue_text = _sanitize_dynamic_text(_read_text(queue_path)).rstrip() + "\n"
    plan_text = _sanitize_dynamic_text(_read_text(plan_path)).rstrip() + "\n"
    if _privacy_audit_text(queue_text + "\n" + plan_text):
        raise ValueError("queue/plan drafts contain private raw values; redact before applying")
    target_queue = repo_root / QUEUE_PATH
    target_plan = repo_root / _extract_suggested_plan_path(plan_text)
    rendered = render_apply_queue_plan(
        confirm_human_approved=confirm_human_approved,
        target_queue=QUEUE_PATH.as_posix(),
        target_plan=_repo_path(target_plan, repo_root),
    )
    out = _default_output(out, DEFAULT_APPLY_QUEUE_PLAN, "apply_queue_plan.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    if confirm_human_approved:
        target_queue.parent.mkdir(parents=True, exist_ok=True)
        target_plan.parent.mkdir(parents=True, exist_ok=True)
        before = _read_text(target_queue) if target_queue.exists() else ""
        target_queue.write_text(before.rstrip() + "\n\n" + queue_text, encoding="utf-8")
        target_plan.write_text(plan_text, encoding="utf-8")
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def _privacy_audit_text(text: str) -> bool:
    return any(pattern.search(text) for pattern in _privacy_audit_patterns().values())


def render_apply_queue_plan(*, confirm_human_approved: bool, target_queue: str, target_plan: str) -> str:
    return _sanitize_dynamic_text(
        f"""# Apply Queue/Plan

- Result: `{'applied' if confirm_human_approved else 'blocked'}`
- Queue target: `{target_queue}`
- Plan target: `{target_plan}`
- This command writes tracked queue/plan docs only when `--confirm-human-approved` is present.
- It does not push, create/merge/close PRs, delete branches, force-push, run private eval, or approve claims.
"""
    )


def write_review_threads(
    *,
    threads_json: Path | None = None,
    pr: str | None = None,
    out: Path = DEFAULT_REVIEW_THREADS,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    findings, sources = collect_review_thread_findings(threads_json=threads_json, pr=pr, repo_root=repo_root)
    rendered = render_review_threads(findings, sources=sources)
    out = _default_output(out, DEFAULT_REVIEW_THREADS, "review_threads.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def collect_review_thread_findings(
    *,
    threads_json: Path | None,
    pr: str | None,
    repo_root: Path,
) -> tuple[list[ReviewThreadFinding], list[str]]:
    payloads: list[object] = []
    sources: list[str] = []
    if threads_json is not None:
        path = _resolve_input_path(threads_json, repo_root=repo_root)
        if not path.exists():
            raise ValueError(f"review threads JSON not found: {_display_path(str(threads_json), repo_root=repo_root)}")
        payloads.append(json.loads(_read_text(path)))
        sources.append(f"file `{_display_path(_repo_path(path, repo_root), repo_root=repo_root)}`")
    if pr:
        payloads.append(_review_threads_payload_from_pr(pr, repo_root=repo_root))
        sources.append(f"PR `{_validate_pr_selector(pr)}`")
    if not payloads:
        raise ValueError("review-threads requires --threads-json or --pr")
    findings: list[ReviewThreadFinding] = []
    for payload in payloads:
        findings.extend(_parse_review_threads_payload(payload))
    return _dedupe_review_thread_findings(findings), sources


def _review_threads_payload_from_pr(pr: str, *, repo_root: Path) -> object:
    safe_pr = _validate_pr_selector(pr)
    try:
        repo = subprocess.run(
            ["gh", "repo", "view", "--json", "owner,name"],
            cwd=repo_root,
            capture_output=True,
            check=True,
            text=True,
        )
        repo_payload = json.loads(repo.stdout)
        owner = repo_payload.get("owner", {}).get("login")
        name = repo_payload.get("name")
        if not owner or not name:
            raise ValueError("could not determine GitHub owner/name")
        query = """
        query($owner:String!, $name:String!, $number:Int!) {
          repository(owner:$owner, name:$name) {
            pullRequest(number:$number) {
              reviewThreads(first:100) {
                nodes {
                  isResolved
                  path
                  line
                  comments(first:20) {
                    nodes {
                      body
                      path
                      line
                      author { login }
                    }
                  }
                }
              }
            }
          }
        }
        """
        result = subprocess.run(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"owner={owner}",
                "-F",
                f"name={name}",
                "-F",
                f"number={safe_pr}",
            ],
            cwd=repo_root,
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"could not read review threads from PR {safe_pr}") from exc
    return json.loads(result.stdout)


def _parse_review_threads_payload(payload: object) -> list[ReviewThreadFinding]:
    threads = _find_review_thread_nodes(payload)
    findings: list[ReviewThreadFinding] = []
    for thread in threads:
        if not isinstance(thread, dict):
            continue
        comments = _thread_comments(thread)
        last_comment = comments[-1] if comments else {}
        body = str(last_comment.get("body") or thread.get("body") or "")
        path = _display_path(str(thread.get("path") or last_comment.get("path") or "unknown"))
        line = str(thread.get("line") or last_comment.get("line") or "unknown")
        resolved = bool(thread.get("isResolved") or thread.get("resolved"))
        reviewer_mode = _reviewer_mode_for_text(body + "\n" + path)
        lane = _review_thread_lane(resolved=resolved, reviewer_mode=reviewer_mode, text=body)
        findings.append(
            ReviewThreadFinding(
                status="resolved" if resolved else "unresolved",
                path=path,
                line=_sanitize_inline_text(line),
                reviewer_mode=reviewer_mode,
                lane=lane,
                summary=_review_thread_summary(body, path=path),
            )
        )
    return findings


def _find_review_thread_nodes(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    nodes = payload.get("nodes")
    if isinstance(nodes, list) and any(isinstance(item, dict) and ("isResolved" in item or "resolved" in item) for item in nodes):
        return nodes
    out: list[object] = []
    for value in payload.values():
        out.extend(_find_review_thread_nodes(value))
    return out


def _thread_comments(thread: dict[str, object]) -> list[dict[str, object]]:
    comments = thread.get("comments")
    if isinstance(comments, dict):
        nodes = comments.get("nodes")
        if isinstance(nodes, list):
            return [item for item in nodes if isinstance(item, dict)]
    if isinstance(comments, list):
        return [item for item in comments if isinstance(item, dict)]
    return []


def _reviewer_mode_for_text(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("private", "privacy", "doc_id", "chunk_id", "raw evidence", "raw question")):
        return "Privacy Auditor"
    if any(token in lowered for token in ("benchmark", "eval", "metric", "latency", "performance", "claim")):
        return "Benchmark Auditor"
    if any(token in lowered for token in ("architecture", "adr", "contract", "load-bearing", "schema")):
        return "Deep Reviewer"
    return "Adversarial Reviewer"


def _review_thread_lane(*, resolved: bool, reviewer_mode: str, text: str) -> str:
    if resolved:
        return "resolved"
    if reviewer_mode in {"Privacy Auditor", "Benchmark Auditor", "Deep Reviewer"}:
        return "needs-human-decision"
    lowered = text.lower()
    if any(token in lowered for token in ("must", "blocking", "requested changes", "regression", "bug")):
        return "must-fix"
    return "should-fix"


def _review_thread_summary(text: str, *, path: str) -> str:
    mode = _reviewer_mode_for_text(text + "\n" + path)
    if mode == "Privacy Auditor":
        return "Privacy-sensitive review thread needs redaction-aware handling"
    if mode == "Benchmark Auditor":
        return "Benchmark/eval review thread needs claim-boundary handling"
    if mode == "Deep Reviewer":
        return "Architecture/load-bearing review thread needs human design review"
    return "Implementation review thread needs local follow-up"


def _dedupe_review_thread_findings(findings: Iterable[ReviewThreadFinding]) -> list[ReviewThreadFinding]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[ReviewThreadFinding] = []
    for finding in findings:
        key = (finding.status, finding.path, finding.line, finding.summary)
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    return out


def render_review_threads(findings: Sequence[ReviewThreadFinding], *, sources: Sequence[str]) -> str:
    unresolved = [finding for finding in findings if finding.status == "unresolved"]
    lines = [
        "# Review Thread Ingest",
        "",
        "- Read-only review-thread triage. It does not reply, resolve comments, push, create/merge/close PRs, delete branches, or force-push.",
        "- Comment bodies are summarized instead of echoed to avoid leaking private raw values.",
        f"- Unresolved count: `{len(unresolved)}`",
        "",
        "## Sources",
        "",
    ]
    lines.extend(f"- {_sanitize_dynamic_text(source)}" for source in sources)
    lines.extend(["", "## Threads", "", "| Status | Lane | Reviewer | Location | Summary |", "|---|---|---|---|---|"])
    if findings:
        for finding in findings:
            location = f"{finding.path}:{finding.line}"
            lines.append(
                "| "
                f"`{finding.status}` | `{finding.lane}` | `{finding.reviewer_mode}` | "
                f"`{_display_path(location)}` | {_sanitize_inline_text(finding.summary)} |"
            )
    else:
        lines.append("| `none` | `N/A` | `N/A` | `N/A` | No review threads found. |")
    lines.extend(
        [
            "",
            "## Next Safe Command",
            "",
            "```bash",
            "python3 scripts/agent_loop.py review-plan --pr <PR_NUMBER>",
            "```",
            "",
        ]
    )
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def write_ci_summary(
    *,
    logs: Sequence[Path] = (),
    pr: str | None = None,
    out: Path = DEFAULT_CI_SUMMARY,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    findings, sources = collect_ci_findings(logs=logs, pr=pr, repo_root=repo_root)
    rendered = render_ci_summary(findings, sources=sources)
    out = _default_output(out, DEFAULT_CI_SUMMARY, "ci_summary.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_ci_summary(findings: Sequence[CIFinding], *, sources: Sequence[str]) -> str:
    lanes: dict[str, int] = {}
    for finding in findings:
        lanes[finding.lane] = lanes.get(finding.lane, 0) + 1
    lines = [
        "# CI Summary",
        "",
        "- Read-only CI summary. It does not re-run CI, push, create/merge/close PRs, delete branches, or force-push.",
        "",
        "## Sources",
        "",
    ]
    lines.extend(f"- {_sanitize_dynamic_text(source)}" for source in sources)
    lines.extend(["", "## Lane Counts", "", "| Lane | Count |", "|---|---:|"])
    for lane, count in sorted(lanes.items()):
        lines.append(f"| `{lane}` | {count} |")
    lines.extend(["", "## Recommended Local Reproduction", ""])
    for finding in findings:
        lines.append(f"- `{_sanitize_command_text(finding.validation)}`")
    lines.extend(["", "## Next Safe Command", "", "```bash", "python3 scripts/agent_loop.py ci-ingest --log <CI_LOG>", "```", ""])
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def write_readiness_score(
    *,
    task_id: str | None = None,
    changed_files: Sequence[str] = (),
    pr: str | None = None,
    body: Path | None = None,
    branch: str | None = None,
    claim_text: Path | None = None,
    out: Path = DEFAULT_READINESS_SCORE,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, ReadinessScore, str]:
    report = build_readiness_score(
        task_id=task_id,
        changed_files=changed_files,
        pr=pr,
        body=body,
        branch=branch,
        claim_text=claim_text,
        repo_root=repo_root,
    )
    rendered = render_readiness_score(report, changed_files=changed_files, pr=pr)
    out = _default_output(out, DEFAULT_READINESS_SCORE, "readiness_score.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, report, rendered


def build_readiness_score(
    *,
    task_id: str | None,
    changed_files: Sequence[str],
    pr: str | None,
    body: Path | None,
    branch: str | None,
    claim_text: Path | None,
    repo_root: Path,
) -> ReadinessScore:
    files = sorted(_normalize_changed_file(path, repo_root=repo_root) for path in changed_files if path)
    surface = classify_changed_files(files)
    surfaces = {surface.surface, *surface.additional_surfaces}
    blockers: list[str] = []
    warnings: list[str] = []
    evidence: list[str] = []

    if not files:
        blockers.append("changed files are missing")
    else:
        evidence.append(f"changed-file surface classified as {surface.surface}")
    if surface.confidence != "high":
        warnings.append(f"surface confidence is {surface.confidence}")
    if surfaces & {"private-real-eval", "privacy-sensitive-artifact"}:
        blockers.append("private/privacy-sensitive surface requires human review")
    if surfaces & {"benchmark-reporting", "public-synthetic-benchmark"}:
        warnings.append("benchmark/eval surface requires claim-boundary review")
    if surfaces & {"product-runtime", "governance-adr"}:
        warnings.append("runtime/governance surface requires reviewer attention")

    if task_id:
        handoff = check_handoff(task_id, changed_files=files, repo_root=repo_root)
        if handoff.ok:
            evidence.append(f"handoff-check passed for {task_id}")
        else:
            blockers.append("handoff-check failed or has weak evidence")
    else:
        warnings.append("no task id provided; handoff-check was not evaluated")

    privacy_findings = audit_privacy_output(repo_root / "reports" / "agent_loop", out_path=None, repo_root=repo_root)
    if privacy_findings:
        blockers.append(f"privacy audit found {len(privacy_findings)} generated artifact issue(s)")
    else:
        evidence.append("generated agent-loop privacy audit has no findings")

    if body is not None:
        body_path = _resolve_input_path(body, repo_root=repo_root)
        if body_path.exists():
            pr_findings = check_pr_body_text(_read_text(body_path), changed_files=files, branch=branch, repo_root=repo_root)
            if pr_findings:
                blockers.append(f"PR body check has {len(pr_findings)} finding(s)")
            else:
                evidence.append("PR body check has no findings")
        else:
            blockers.append("PR body path does not exist")
    else:
        warnings.append("no PR body was provided")

    if claim_text is not None:
        resolved_claim = _resolve_input_path(claim_text, repo_root=repo_root)
        if resolved_claim.exists():
            claim_findings = audit_claim_text(_read_text(resolved_claim), surface)
            if claim_findings:
                blockers.append(f"claim audit found {len(claim_findings)} issue(s)")
            else:
                evidence.append("claim audit found no risky wording")
        else:
            blockers.append("claim text path does not exist")
    else:
        warnings.append("no claim text was provided")

    manifest = _manifest_freshness(changed_files=files, repo_root=repo_root)
    if manifest.get("current"):
        evidence.append("manifest freshness hash matches changed files")
    else:
        warnings.append("manifest is missing or stale")

    score = 100 - (30 * len(blockers)) - (8 * len(warnings))
    score = max(0, min(100, score))
    decision = "ready-for-human-approval" if not blockers and score >= 80 else ("blocked" if blockers else "review-before-ship")
    if pr:
        evidence.append(f"PR context: {_validate_pr_selector(pr)}")
    return ReadinessScore(
        score=score,
        decision=decision,
        blockers=tuple(_dedupe_preserve_order(blockers)),
        warnings=tuple(_dedupe_preserve_order(warnings)),
        evidence=tuple(_dedupe_preserve_order(evidence)),
    )


def render_readiness_score(report: ReadinessScore, *, changed_files: Sequence[str], pr: str | None) -> str:
    lines = [
        "# PR Readiness Score",
        "",
        "- Decision support only. This score does not push, create/merge/close PRs, delete branches, force-push, run private eval, or approve claims.",
        f"- Score: `{report.score}`",
        f"- Decision: `{report.decision}`",
        f"- PR: `{_validate_pr_selector(pr) if pr else 'N/A'}`",
        "",
        "## Changed Files",
        "",
    ]
    lines.extend(f"- `{_display_path(path)}`" for path in changed_files) if changed_files else lines.append("- `N/A`")
    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in report.blockers) if report.blockers else lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in report.warnings) if report.warnings else lines.append("- None")
    lines.extend(["", "## Evidence", ""])
    lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in report.evidence) if report.evidence else lines.append("- None")
    lines.extend(["", "## Next Safe Command", "", "```bash", "python3 scripts/agent_loop.py approval-packet --from-git", "```", ""])
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def write_branch_issue_hygiene(
    *,
    branch: str | None = None,
    body: Path | None = None,
    task_id: str | None = None,
    out: Path = DEFAULT_BRANCH_ISSUE_HYGIENE,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, int, str]:
    rendered, findings = render_branch_issue_hygiene(
        branch=branch or _current_branch(repo_root) or "unknown",
        body=body,
        task_id=task_id,
        repo_root=repo_root,
    )
    out = _default_output(out, DEFAULT_BRANCH_ISSUE_HYGIENE, "branch_issue_hygiene.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, 1 if findings else 0, rendered


def render_branch_issue_hygiene(
    *,
    branch: str,
    body: Path | None,
    task_id: str | None,
    repo_root: Path,
) -> tuple[str, list[str]]:
    findings: list[str] = []
    safe_branch = _sanitize_inline_text(branch)
    issue = _issue_from_branch(safe_branch)
    if not re.match(r"^[a-z][a-z0-9_-]*/issue-\d+", safe_branch):
        findings.append("branch does not match ADR 0007 `<type>/issue-<N>` convention")
    if not issue:
        findings.append("branch does not expose an issue number")
    closers: list[str] = []
    body_label = "N/A"
    if body is not None:
        body_path = _resolve_input_path(body, repo_root=repo_root)
        body_label = _display_path(_repo_path(body_path, repo_root), repo_root=repo_root)
        if body_path.exists():
            closers = re.findall(r"\b(?:Closes|Fixes|Resolves)\s+#(\d+)\b", _sanitize_dynamic_text(_read_text(body_path)), re.IGNORECASE)
            if not closers:
                findings.append("PR body has no Closes/Fixes/Resolves issue reference")
            elif issue and issue not in closers:
                findings.append("PR body issue reference does not match branch issue")
        else:
            findings.append("PR body path does not exist")
    else:
        findings.append("PR body was not provided")
    if task_id and not TASK_ID_RE.fullmatch(task_id):
        findings.append("task id does not match T-YYYY-NNNN")
    lines = [
        "# Branch / Issue Hygiene",
        "",
        "- Read-only hygiene check. It does not create issues, rename branches, push, create PRs, merge, close, or delete branches.",
        f"- Branch: `{safe_branch}`",
        f"- Issue from branch: `{issue or 'N/A'}`",
        f"- PR body: `{body_label}`",
        f"- PR body closers: `{', '.join('#' + item for item in closers) if closers else 'N/A'}`",
        f"- Task: `{task_id or 'N/A'}`",
        "",
        "## Findings",
        "",
    ]
    lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in findings) if findings else lines.append("- None")
    lines.extend(["", "## Next Safe Command", "", "```bash", "make check-branch", "```", ""])
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n", findings


def write_integration_pack(
    *,
    out: Path = DEFAULT_INTEGRATION_PACK,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    rendered = render_integration_pack(repo_root=repo_root)
    out = _default_output(out, DEFAULT_INTEGRATION_PACK, "integration_pack.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_integration_pack(*, repo_root: Path = ROOT_DIR) -> str:
    return _sanitize_dynamic_text(
        f"""# Agent Loop Integration Pack

- Purpose: package read-only CLI/MCP usage for Codex, Claude, ChatGPT, and generic MCP clients.
- This pack does not call external LLM APIs, install clients, push, create/merge/close PRs, delete branches, force-push, run private eval, or approve claims.

## Local CLI

```bash
python3 scripts/agent_loop.py map
python3 scripts/agent_loop.py dashboard --from-git
python3 scripts/agent_loop.py readiness-score --from-git
```

## MCP

```bash
python3 scripts/agent_loop.py mcp-config --out reports/agent_loop/mcp_client_config.md
python3 scripts/agent_loop_mcp.py
```

## Agent Profiles

- Codex: use `context-pack --profile codex` for implementation context.
- Claude: use `context-pack --profile claude` for hooks, slash commands, and long-session handoff.
- ChatGPT: use `context-pack --profile chatgpt` for decision support and reviewer prompts.

## Privacy Boundary

- Share generated summaries only after checking `privacy-audit-output`.
- Do not paste private raw question, answer, evidence, doc_id, chunk_id, filename, exact local path, or private case text into external services.

## Repo

- Root placeholder: `<REPO_ROOT>`
- Current branch: `{_current_branch(repo_root) or 'unknown'}`
"""
    ).rstrip() + "\n"


def write_schedule_config(
    *,
    out: Path = DEFAULT_SCHEDULE_CONFIG,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    rendered = render_schedule_config()
    out = _default_output(out, DEFAULT_SCHEDULE_CONFIG, "schedule_config.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_schedule_config() -> str:
    return """# Agent Loop Scheduled Status Recipe

- Recipe only. This command does not install cron jobs, create Codex app automations, push, create/merge/close PRs, delete branches, force-push, run private eval, or approve claims.
- Keep scheduled jobs read-only/report-only unless a human explicitly changes the policy.

## Safe Refresh Commands

```bash
python3 scripts/agent_loop.py loop-state --from-git --out reports/agent_loop/loop_state.json
python3 scripts/agent_loop.py dashboard --from-git --out reports/agent_loop/dashboard.md
python3 scripts/agent_loop.py stale-reports --from-git --out reports/agent_loop/stale_reports.md
python3 scripts/agent_loop.py privacy-audit-output --path reports/agent_loop --out reports/agent_loop/privacy_audit.md
```

## Human Gate

- Ask before installing a recurring runner.
- Do not schedule `validate` with private real-eval inputs.
- Do not schedule push, PR creation, merge, close, branch deletion, or force-push.
""".rstrip() + "\n"


def append_validation_history(
    runs: Sequence[ValidationRun],
    *,
    changed_files: Sequence[str],
    history: Path = DEFAULT_VALIDATION_HISTORY,
    repo_root: Path = ROOT_DIR,
) -> Path:
    if history == DEFAULT_VALIDATION_HISTORY:
        history = repo_root / "reports" / "agent_loop" / "validation_history.jsonl"
    safe_history = _safe_output_path(history, repo_root=repo_root)
    safe_history.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_head": _current_git_head(repo_root) or "unknown",
        "branch": _current_branch(repo_root) or "unknown",
        "changed_files_hash": _changed_files_hash(changed_files, repo_root=repo_root),
        "changed_files": [_display_path(path, repo_root=repo_root) for path in changed_files],
        "commands": [
            {
                "command": _sanitize_command_text(run.command),
                "returncode": run.returncode,
            }
            for run in runs
        ],
    }
    with safe_history.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return safe_history


def write_validation_history_report(
    *,
    history: Path = DEFAULT_VALIDATION_HISTORY,
    out: Path = DEFAULT_VALIDATION_HISTORY_REPORT,
    limit: int = 10,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    entries = read_validation_history(history=history, limit=limit, repo_root=repo_root)
    rendered = render_validation_history(entries, history=history, repo_root=repo_root)
    out = _default_output(out, DEFAULT_VALIDATION_HISTORY_REPORT, "validation_history.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def read_validation_history(*, history: Path, limit: int, repo_root: Path) -> list[dict[str, object]]:
    path = repo_root / "reports" / "agent_loop" / "validation_history.jsonl" if history == DEFAULT_VALIDATION_HISTORY else _resolve_input_path(history, repo_root=repo_root)
    if not path.exists():
        return []
    entries: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries[-limit:]


def render_validation_history(entries: Sequence[dict[str, object]], *, history: Path, repo_root: Path) -> str:
    history_label = _display_path(_repo_path(history if history.is_absolute() else repo_root / history, repo_root), repo_root=repo_root)
    lines = [
        "# Validation History",
        "",
        "- Local JSONL ledger summary. It stores command names and return codes, not raw stdout/stderr.",
        f"- History: `{history_label}`",
        f"- Entry count shown: `{len(entries)}`",
        "",
        "| Time | Git HEAD | Commands | Result |",
        "|---|---|---|---|",
    ]
    if entries:
        for entry in entries:
            commands = entry.get("commands") if isinstance(entry.get("commands"), list) else []
            command_count = len(commands)
            failed = any(isinstance(command, dict) and command.get("returncode") not in {0, "0"} for command in commands)
            lines.append(
                f"| `{_sanitize_inline_text(str(entry.get('generated_at', 'unknown')))}` | "
                f"`{_sanitize_inline_text(str(entry.get('git_head', 'unknown')))}` | `{command_count}` | "
                f"`{'fail' if failed else 'pass'}` |"
            )
    else:
        lines.append("| `N/A` | `N/A` | `0` | `N/A` |")
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def write_privacy_regression(
    *,
    out: Path = DEFAULT_PRIVACY_REGRESSION,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, int, str]:
    rendered, failures = render_privacy_regression()
    out = _default_output(out, DEFAULT_PRIVACY_REGRESSION, "privacy_regression.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, 1 if failures else 0, rendered


def render_privacy_regression() -> tuple[str, list[str]]:
    samples = [
        "question: PRIVATE_QUERY\nanswer: PRIVATE_ANSWER\nevidence: PRIVATE_EVIDENCE\ndoc_id: DOC-1\nchunk_id: CHUNK-1\n/Users/example/private.pdf",
        "--raw-question PRIVATE_QUERY --answer PRIVATE_ANSWER --doc-id DOC-1 --chunk-id CHUNK-1",
    ]
    failures: list[str] = []
    for index, sample in enumerate(samples, start=1):
        sanitized = _sanitize_command_text(_sanitize_dynamic_text(sample))
        if any(token in sanitized for token in ("PRIVATE_QUERY", "PRIVATE_ANSWER", "PRIVATE_EVIDENCE", "DOC-1", "CHUNK-1", "/Users/example")):
            failures.append(f"sample-{index} leaked a private token")
        if _privacy_audit_text(sanitized):
            failures.append(f"sample-{index} still matches privacy audit patterns after sanitization")
    lines = [
        "# Privacy Regression",
        "",
        "- Fixture-based sanitizer check. It does not read private data, push, create/merge/close PRs, delete branches, force-push, run private eval, or call external services.",
        f"- Result: `{'fail' if failures else 'pass'}`",
        f"- Sample count: `{len(samples)}`",
        "",
        "## Findings",
        "",
    ]
    lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in failures) if failures else lines.append("- None")
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n", failures


def write_claim_policy(
    *,
    changed_files: Sequence[str] = (),
    text: Path | None = None,
    out: Path = DEFAULT_CLAIM_POLICY,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, int, str]:
    surface = classify_changed_files(changed_files)
    findings: list[ClaimFinding] = []
    source = "N/A"
    if text is not None:
        path = _resolve_input_path(text, repo_root=repo_root)
        if not path.exists():
            raise ValueError(f"claim text file not found: {_display_path(str(text), repo_root=repo_root)}")
        source = _display_path(_repo_path(path, repo_root), repo_root=repo_root)
        findings = audit_claim_text(_read_text(path), surface)
    rendered = render_claim_policy(surface=surface, findings=findings, source=source)
    out = _default_output(out, DEFAULT_CLAIM_POLICY, "claim_policy.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, 1 if findings else 0, rendered


def render_claim_policy(*, surface: SurfaceReport, findings: Sequence[ClaimFinding], source: str) -> str:
    lines = [
        "# Claim Policy",
        "",
        "- Claim policy helper. It does not approve benchmark/performance/private real-eval claims.",
        f"- Surface: `{surface.surface}`",
        f"- Additional surfaces: `{', '.join(surface.additional_surfaces) if surface.additional_surfaces else 'N/A'}`",
        f"- Required reviewer: `{surface.reviewer_type}`",
        f"- Source: `{_sanitize_dynamic_text(source)}`",
        "",
        "## Allowed Without Extra Human Claim Approval",
        "",
        "- Local orchestration, docs, or CI-helper wording that does not claim product quality, benchmark lift, private real-eval success, latency improvement, or production behavior.",
        "",
        "## Disallowed Or Human-Gated Claims",
        "",
    ]
    lines.extend(f"- {claim}" for claim in surface.disallowed_claims)
    lines.extend(["", "## Text Findings", ""])
    if findings:
        for finding in findings:
            lines.append(f"- `{finding.severity}` / `{finding.reviewer}`: {_sanitize_dynamic_text(finding.issue)}")
    else:
        lines.append("- None")
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def write_architecture_decision(
    *,
    changed_files: Sequence[str] = (),
    out: Path = DEFAULT_ARCHITECTURE_DECISION,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    surface = classify_changed_files(changed_files)
    rendered = render_architecture_decision(surface=surface, changed_files=changed_files)
    out = _default_output(out, DEFAULT_ARCHITECTURE_DECISION, "architecture_decision.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_architecture_decision(*, surface: SurfaceReport, changed_files: Sequence[str]) -> str:
    load_bearing = [path for path in changed_files if path != "[redacted-local-path]" and is_load_bearing(_normalize_changed_file(path))]
    adr_files = [path for path in changed_files if _normalize_changed_file(path).startswith("docs/adr/")]
    surfaces = {surface.surface, *surface.additional_surfaces}
    likely = bool(load_bearing or adr_files or surfaces & {"product-runtime", "eval-harness", "public-synthetic-benchmark", "private-real-eval", "governance-adr"})
    decision = "human-architecture-review-required" if likely else "no-architecture-decision-detected"
    lines = [
        "# Architecture Decision Detector",
        "",
        "- Detector only. It does not choose architecture, write ADRs, push, create/merge/close PRs, delete branches, force-push, run private eval, or approve claims.",
        f"- Decision: `{decision}`",
        f"- Surface: `{surface.surface}`",
        f"- Load-bearing files: `{len(load_bearing)}`",
        f"- ADR files: `{len(adr_files)}`",
        "",
        "## Signals",
        "",
    ]
    lines.extend(f"- `{_display_path(path)}`" for path in changed_files) if changed_files else lines.append("- `N/A`")
    lines.extend(
        [
            "",
            "## Next Safe Command",
            "",
            "```bash",
            "python3 scripts/agent_loop.py architecture-brief --from-git",
            "```",
            "",
        ]
    )
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def write_workset_recommendation(
    *,
    batch: Path | None = None,
    tasks_dir: Path = DEFAULT_CODEX_TASKS_DIR,
    max_items: int = 12,
    out: Path = DEFAULT_WORKSET_RECOMMENDATION,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    rendered = render_workset_recommendation(batch=batch, tasks_dir=tasks_dir, max_items=max_items, repo_root=repo_root)
    out = _default_output(out, DEFAULT_WORKSET_RECOMMENDATION, "workset_recommendation.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_workset_recommendation(*, batch: Path | None, tasks_dir: Path, max_items: int, repo_root: Path) -> str:
    items: list[dict[str, object]] = []
    source = "batch JSON"
    if batch is not None:
        path = _resolve_input_path(batch, repo_root=repo_root)
        items = _load_batch_payload(path)
        source = _display_path(_repo_path(path, repo_root), repo_root=repo_root)
    else:
        resolved_tasks_dir = repo_root / "reports" / "agent_loop" / "codex_tasks" if tasks_dir == DEFAULT_CODEX_TASKS_DIR else _resolve_input_path(tasks_dir, repo_root=repo_root)
        briefs = _load_brief_summaries(resolved_tasks_dir, max_items=max_items, repo_root=repo_root)
        items = [_brief_summary_payload(brief, repo_root=repo_root) for brief in briefs]
        source = _display_path(_repo_path(resolved_tasks_dir, repo_root), repo_root=repo_root)
    lanes: dict[str, list[dict[str, object]]] = {}
    for item in items:
        lanes.setdefault(str(item.get("lane", "unknown")), []).append(item)
    lines = [
        "# Workset Recommendation",
        "",
        "- Local planning recommendation. It does not edit queue/plan docs, push, create/merge/close PRs, delete branches, force-push, run private eval, or approve claims.",
        f"- Source: `{source}`",
        "",
        "## Candidate Sets",
        "",
    ]
    serial = lanes.get("serial", [])[:1]
    parallel = lanes.get("parallel-safe", [])[:3]
    review = lanes.get("review-only", [])[:3]
    manual = lanes.get("manual-gated", [])[:3]
    lines.extend(_render_workset_section("Set A - serial unblocker", serial, "Run one item first; it likely gates downstream work."))
    lines.extend(_render_workset_section("Set B - parallel candidates", parallel, "Can be delegated after checking file overlap and claim surface."))
    lines.extend(_render_workset_section("Set C - review-only passes", review, "Use adversarial review without implementation mutation."))
    lines.extend(_render_workset_section("Set D - manual-gated", manual, "Prepare decision briefs; do not automate the gated action."))
    lines.extend(["", "## Next Safe Command", "", "```bash", "python3 scripts/agent_loop.py decision-brief --gate task", "```", ""])
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def _render_workset_section(title: str, items: Sequence[dict[str, object]], guidance: str) -> list[str]:
    lines = [f"### {title}", "", f"- Guidance: {_sanitize_dynamic_text(guidance)}"]
    if not items:
        lines.append("- Items: `N/A`")
    for item in items:
        lines.append(f"- `{_sanitize_inline_text(str(item.get('title', 'Untitled')))}` - {_sanitize_inline_text(str(item.get('reason', '')))}")
    lines.append("")
    return lines


def write_dependency_graph(
    *,
    branch: str,
    pr_json: Path | None = None,
    out: Path = DEFAULT_DEPENDENCY_GRAPH,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    items = _stacked_pr_items(branch=branch, pr_json=pr_json, repo_root=repo_root)
    rendered = render_dependency_graph(branch=branch, items=items)
    out = _default_output(out, DEFAULT_DEPENDENCY_GRAPH, "dependency_graph.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_dependency_graph(*, branch: str, items: Sequence[dict[str, object]]) -> str:
    safe_branch = _sanitize_inline_text(branch)
    lines = [
        "# Stacked Dependency Graph",
        "",
        "- Read-only graph. It does not merge, close, delete branches, push, or force-push.",
        f"- Base branch: `{safe_branch}`",
        "",
        "```mermaid",
        "flowchart TD",
        f"  base[\"{safe_branch}\"]",
    ]
    if items:
        for item in items:
            node_id = "pr" + re.sub(r"\W+", "_", str(item.get("number", "x")))
            label = f"PR #{item.get('number', 'N/A')} {str(item.get('headRefName') or 'unknown')}"
            lines.append(f"  {node_id}[\"{_sanitize_inline_text(label)}\"] --> base")
    else:
        lines.append('  none["No dependent PRs detected"] --> base')
    lines.extend(
        [
            "```",
            "",
            "## Human Gate",
            "",
            "- If dependents exist, branch deletion and merge cleanup require explicit human approval.",
            "",
        ]
    )
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def write_automation_coverage(
    *,
    out: Path = DEFAULT_AUTOMATION_COVERAGE,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, str]:
    rendered = render_automation_coverage()
    out = _default_output(out, DEFAULT_AUTOMATION_COVERAGE, "automation_coverage.md", repo_root=repo_root)
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(rendered, encoding="utf-8")
    return safe_out, rendered


def render_automation_coverage() -> str:
    rows = (
        ("1", "PR review thread ingest", "review-threads, review-plan, review-ingest"),
        ("2", "CI logs summary", "ci-summary, ci-ingest"),
        ("3", "PR readiness score", "readiness-score, approval-packet, ship-simulate"),
        ("4", "dashboard UX", "dashboard, dashboard-html, loop-state"),
        ("5", "artifact freshness", "artifact-freshness, stale-reports, manifest"),
        ("6", "safe local auto-fix", "safe-fix, patch-proposal"),
        ("7", "review to patch proposal", "review-patch-plan, patch-proposal"),
        ("8", "queue/plan sync UX", "queue-plan-sync, propose-queue-plan, apply-queue-plan"),
        ("9", "stacked PR dependency graph", "dependency-graph, stacked-risk"),
        ("10", "branch/issue hygiene", "branch-issue-hygiene, pr-body-check"),
        ("11", "agent integrations", "integration-pack, mcp-config, context-pack"),
        ("12", "scheduled status recipe", "scheduled-status"),
        ("13", "validation history ledger", "validate --record-history, validation-history"),
        ("14", "privacy regression corpus", "privacy-regression, privacy-audit-output"),
        ("15", "claim policy engine", "claim-policy, claim-audit"),
        ("16", "architecture decision detector", "architecture-decision, architecture-brief, adr-reserve"),
        ("17", "next work-set recommender", "workset-recommend, batch-plan"),
        ("18", "auto-pass strict profiles", "auto-pass-check --profile ..."),
        ("19", "human-approved remote execution", "human-gated-exec --confirm-human-approved"),
        ("20", "existing auto-ship bridge", "auto-ship-prepare, auto-ship-plan, ship-simulate, ship-command-pack"),
    )
    lines = [
        "# Agent Loop Automation Coverage",
        "",
        "- Coverage map only. It does not execute gated actions.",
        "",
        "| # | Candidate | Implemented command surface |",
        "|---:|---|---|",
    ]
    lines.extend(f"| {index} | {name} | `{commands}` |" for index, name, commands in rows)
    lines.extend(
        [
            "",
            "## Still Human-Gated",
            "",
            "- Queue/plan actual tracked-doc application unless `--confirm-human-approved` is explicit.",
            "- Running existing `make ship-arm` remains a shipping approval; `auto-ship-plan` only prepares a plan.",
            "- Push, PR create/merge/close, branch delete, force-push require `human-gated-exec --confirm-human-approved` plus action-specific gates.",
            "- Private real-eval decisions, benchmark/performance claims, architecture tradeoffs.",
            "",
        ]
    )
    return "\n".join(lines)


def write_loop_state(
    *,
    task_id: str | None = None,
    batch: Path | None = None,
    review_followups: Path | None = None,
    changed_files: Sequence[str] = (),
    pr: str | None = None,
    out: Path = DEFAULT_LOOP_STATE,
    repo_root: Path = ROOT_DIR,
) -> tuple[Path, dict[str, object]]:
    state = build_loop_state(
        task_id=task_id,
        batch=batch,
        review_followups=review_followups,
        changed_files=changed_files,
        pr=pr,
        repo_root=repo_root,
    )
    if out == DEFAULT_LOOP_STATE:
        out = repo_root / "reports" / "agent_loop" / "loop_state.json"
    safe_out = _safe_output_path(out, repo_root=repo_root)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return safe_out, state


def build_loop_state(
    *,
    task_id: str | None,
    batch: Path | None,
    review_followups: Path | None,
    changed_files: Sequence[str],
    pr: str | None,
    repo_root: Path,
) -> dict[str, object]:
    surface = classify_changed_files(changed_files)
    gate = build_gate_status(
        task_id=task_id,
        batch=batch,
        review_followups=review_followups,
        changed_files=changed_files,
        pr=pr,
        repo_root=repo_root,
    )
    payload: dict[str, object] = {
        "schema_version": 1,
        "task": None,
        "pr": _validate_pr_selector(pr) if pr else None,
        "gate": gate,
        "surface": {
            "surface": surface.surface,
            "confidence": surface.confidence,
            "reviewer_type": surface.reviewer_type,
            "additional_surfaces": list(surface.additional_surfaces),
            "matched_files": [_display_path(path) for path in surface.matched_files],
            "disallowed_claims": list(surface.disallowed_claims),
        },
        "validation_suggestions": suggest_validation_commands(changed_files),
        "artifacts": _loop_artifact_state(repo_root),
        "freshness": _report_freshness(repo_root=repo_root, max_age_days=7),
        "manifest": _manifest_freshness(changed_files=changed_files, repo_root=repo_root),
    }
    if task_id:
        task = load_task(task_id, repo_root)
        handoff = check_handoff(task_id, changed_files=changed_files, repo_root=repo_root)
        payload["task"] = {
            "id": task.task_id,
            "title": _sanitize_inline_text(task.title),
            "status": task.status or "unknown",
            "owner_role": task.owner_role or "unknown",
            "handoff_ok": handoff.ok,
            "handoff_missing": list(handoff.missing_fields),
            "handoff_invalid": list(handoff.invalid_fields),
        }
    return payload


def _loop_artifact_state(repo_root: Path) -> dict[str, bool]:
    rels = (
        "reports/agent_loop/pr_state.json",
        "reports/agent_loop/ai_next_actions.md",
        "reports/agent_loop/codex_tasks",
        "reports/agent_loop/batch_plan.json",
        "reports/agent_loop/queue_entry_draft.md",
        "reports/agent_loop/plan_draft.md",
        "reports/agent_loop/review_followups.md",
        "reports/agent_loop/decision_brief.md",
        "reports/agent_loop/auto_pass.md",
        "reports/agent_loop/dashboard.md",
        "reports/agent_loop/mcp_client_config.md",
        "reports/agent_loop/review_ingest.md",
        "reports/agent_loop/pr_health.md",
        "reports/agent_loop/safe_fix.md",
        "reports/agent_loop/approval_packet.md",
        "reports/agent_loop/queue_plan_patch.diff",
        "reports/agent_loop/pr_body.md",
        "reports/agent_loop/review_plan.md",
        "reports/agent_loop/stale_reports.md",
        "reports/agent_loop/context_pack.md",
        "reports/agent_loop/architecture_brief.md",
        "reports/agent_loop/ship_simulation.md",
        "reports/agent_loop/gate_brief.md",
        "reports/agent_loop/manifest.json",
        "reports/agent_loop/pr_body_check.md",
        "reports/agent_loop/ci_ingest.md",
        "reports/agent_loop/ci_followups",
        "reports/agent_loop/stacked_risk.md",
        "reports/agent_loop/patch_proposal.diff",
        "reports/agent_loop/adr_reservation.md",
        "reports/agent_loop/adr_draft.md",
        "reports/agent_loop/dashboard.html",
        "reports/agent_loop/ship_commands.md",
        "reports/agent_loop/apply_queue_plan.md",
        "reports/agent_loop/review_threads.md",
        "reports/agent_loop/ci_summary.md",
        "reports/agent_loop/readiness_score.md",
        "reports/agent_loop/branch_issue_hygiene.md",
        "reports/agent_loop/integration_pack.md",
        "reports/agent_loop/schedule_config.md",
        "reports/agent_loop/validation_history.jsonl",
        "reports/agent_loop/validation_history.md",
        "reports/agent_loop/privacy_regression.md",
        "reports/agent_loop/claim_policy.md",
        "reports/agent_loop/architecture_decision.md",
        "reports/agent_loop/workset_recommendation.md",
        "reports/agent_loop/dependency_graph.md",
        "reports/agent_loop/automation_coverage.md",
        "reports/agent_loop/human_gated_exec.md",
    )
    return {rel: (repo_root / rel).exists() for rel in rels}


def build_decision_points(
    *,
    task_id: str | None,
    batch: Path | None,
    review_followups: Path | None,
    gate: str,
    changed_files: Sequence[str],
    pr: str | None,
    repo_root: Path,
) -> list[DecisionPoint]:
    if gate not in {"auto", "task", "plan", "review", "claim", "ship"}:
        raise ValueError("--gate must be one of: auto, task, plan, review, claim, ship")
    points: list[DecisionPoint] = []
    if task_id and gate in {"auto", "task", "plan"}:
        task = load_task(task_id, repo_root)
        points.append(_task_decision_point(task, repo_root=repo_root))

    batch_path = _default_existing_path(batch, repo_root / "reports" / "agent_loop" / "batch_plan.json")
    if batch_path is not None and gate in {"auto", "task", "plan"}:
        batch_path = _resolve_input_path(batch_path, repo_root=repo_root)
        if not batch_path.exists():
            raise ValueError(f"batch plan not found: {_display_path(_repo_path(batch_path, repo_root), repo_root=repo_root)}")
        points.append(_batch_decision_point(batch_path, repo_root=repo_root))

    followups_path = _default_existing_path(
        review_followups,
        repo_root / "reports" / "agent_loop" / "review_followups.md",
    )
    if followups_path is not None and gate in {"auto", "review"}:
        followups_path = _resolve_input_path(followups_path, repo_root=repo_root)
        if not followups_path.exists():
            raise ValueError(
                f"review followups not found: {_display_path(_repo_path(followups_path, repo_root), repo_root=repo_root)}"
            )
        points.append(_review_followup_decision_point(followups_path, repo_root=repo_root))

    if changed_files and gate in {"auto", "claim"}:
        points.append(_claim_decision_point(changed_files, repo_root=repo_root))

    if (pr or gate == "ship") and gate in {"auto", "ship"}:
        points.append(_ship_decision_point(pr=pr, changed_files=changed_files))

    if not points:
        points.append(_no_input_decision_point())
    return points


def _default_existing_path(path: Path | None, default: Path) -> Path | None:
    if path is None:
        return default if default.exists() else None
    return path


def _task_decision_point(task: TaskEntry, *, repo_root: Path) -> DecisionPoint:
    plan = find_plan_path(task, repo_root)
    validation = _extract_validation_commands(task)
    next_validation = validation[0] if validation else "python3 scripts/agent_loop.py suggest-validation --from-git"
    context = (
        f"Task: `{task.task_id}` - {_sanitize_inline_text(task.title)}",
        f"Status: `{task.status or 'unknown'}`",
        f"Owner role: `{task.owner_role or 'unknown'}`",
        f"Plan: `{_display_path(_repo_path(plan, repo_root), repo_root=repo_root) if plan else 'N/A'}`",
    )
    return DecisionPoint(
        gate="task-scope",
        title="Decide whether to promote the task/plan draft",
        context=context,
        options=(
            DecisionOption(
                label="Keep as draft and inspect scope",
                recommended=True,
                severity="medium",
                reversibility="high",
                tradeoffs=(
                    "Safest default; avoids committing an ambiguous task or plan.",
                    "Costs another review pass before implementation starts.",
                ),
                evidence_needed=(
                    "Task has acceptance criteria and validation commands.",
                    "Plan path exists or the work is small enough to proceed without one.",
                ),
                next_safe_command=f"python3 scripts/agent_loop.py render-prompt --task {task.task_id}",
                manual_approval="Required before editing queue/plan docs.",
            ),
            DecisionOption(
                label="Promote draft to queue/plan",
                recommended=False,
                severity="medium",
                reversibility="medium",
                tradeoffs=(
                    "Makes the work visible to future sessions.",
                    "Can create queue churn if the task is too broad or duplicates active work.",
                ),
                evidence_needed=(
                    "No duplicate active task in `tasks/queue.md`.",
                    "Scope is one concern and has reviewer focus.",
                ),
                next_safe_command="python3 scripts/agent_loop.py batch-plan",
                manual_approval="Required because this changes tracked governance docs.",
            ),
            DecisionOption(
                label="Split or defer the task",
                recommended=False,
                severity="low",
                reversibility="high",
                tradeoffs=(
                    "Reduces implementation risk if the task mixes surfaces.",
                    "May delay visible progress if overused.",
                ),
                evidence_needed=("Multiple surfaces, missing validation, or unclear owner role.",),
                next_safe_command="python3 scripts/agent_loop.py map",
                manual_approval="Human scope judgment required.",
            ),
        ),
    )


def _batch_decision_point(batch_path: Path, *, repo_root: Path) -> DecisionPoint:
    payload = _load_batch_payload(batch_path)
    counts = {lane: 0 for lane in ("serial", "parallel-safe", "review-only", "manual-gated")}
    for item in payload:
        lane = str(item.get("lane") or "unknown")
        if lane in counts:
            counts[lane] += 1
    context = (
        f"Batch file: `{_display_path(_repo_path(batch_path, repo_root), repo_root=repo_root)}`",
        "Lane counts: "
        + ", ".join(f"`{lane}`={count}" for lane, count in counts.items()),
    )
    serial_count = counts["serial"]
    parallel_count = counts["parallel-safe"]
    manual_count = counts["manual-gated"]
    return DecisionPoint(
        gate="batch-selection",
        title="Choose the next task lane",
        context=context,
        options=(
            DecisionOption(
                label="Run the first serial blocker",
                recommended=serial_count > 0,
                severity="high" if serial_count else "low",
                reversibility="medium",
                tradeoffs=(
                    "Clears dependencies before parallel work expands the state space.",
                    "Can block throughput if the serial item needs human evidence or external review.",
                ),
                evidence_needed=("Serial lane item has a focused validation command.",),
                next_safe_command="python3 scripts/agent_loop.py draft-task --task-brief reports/agent_loop/codex_tasks/001-*.md",
                manual_approval="Required before applying generated queue/plan drafts.",
            ),
            DecisionOption(
                label="Assign parallel-safe candidates",
                recommended=serial_count == 0 and parallel_count > 0,
                severity="medium",
                reversibility="medium",
                tradeoffs=(
                    "Improves throughput when candidates touch independent surfaces.",
                    "Raises coordination cost and can create merge conflicts if independence is misclassified.",
                ),
                evidence_needed=("No shared files, shared PR source, or manual-gated claim surface.",),
                next_safe_command="python3 scripts/agent_loop.py batch-plan",
                manual_approval="Human should confirm independence before parallel execution.",
            ),
            DecisionOption(
                label="Hold manual-gated items",
                recommended=manual_count > 0,
                severity="high" if manual_count else "low",
                reversibility="high",
                tradeoffs=(
                    "Prevents accidental benchmark/private/PR state claims or destructive actions.",
                    "May leave shipping or cleanup work waiting on a human decision.",
                ),
                evidence_needed=("Reviewer-readable evidence and explicit human approval.",),
                next_safe_command="python3 scripts/agent_loop.py decision-brief --gate claim --from-git",
                manual_approval="Required for private eval, benchmark claims, push/PR/merge/close/delete.",
            ),
        ),
    )


def _load_batch_payload(batch_path: Path) -> list[dict[str, object]]:
    try:
        payload = json.loads(_read_text(batch_path))
    except json.JSONDecodeError as exc:
        raise ValueError("batch JSON must be a JSON array; run batch-plan first") from exc
    if not isinstance(payload, list):
        raise ValueError("batch JSON must be a JSON array")
    return [item for item in payload if isinstance(item, dict)]


def _review_followup_decision_point(path: Path, *, repo_root: Path) -> DecisionPoint:
    text = _sanitize_dynamic_text(_read_text(path))
    blocking = len(re.findall(r"Severity:\s*`?(?:blocking|p0|p1)`?", text, re.IGNORECASE))
    manual = len(re.findall(r"Lane:\s*`?manual-gated`?", text, re.IGNORECASE))
    parsed = len(re.findall(r"^###\s+\d{3}\.", text, re.MULTILINE))
    context = (
        f"Review followups: `{_display_path(_repo_path(path, repo_root), repo_root=repo_root)}`",
        f"Parsed follow-up count: `{parsed}`",
        f"Blocking/P0/P1 findings: `{blocking}`",
        f"Manual-gated findings: `{manual}`",
    )
    return DecisionPoint(
        gate="review-findings",
        title="Choose which reviewer findings to address",
        context=context,
        options=(
            DecisionOption(
                label="Fix blocking findings first",
                recommended=blocking > 0,
                severity="high" if blocking else "low",
                reversibility="medium",
                tradeoffs=(
                    "Targets issues most likely to block review or ship.",
                    "Can delay smaller cleanup items.",
                ),
                evidence_needed=("Focused diff and validation for each blocking finding.",),
                next_safe_command="python3 scripts/agent_loop.py review-followup --review <review-output.md>",
                manual_approval="Required if the finding is privacy, benchmark, or architecture gated.",
            ),
            DecisionOption(
                label="Convert non-blocking findings to follow-up tasks",
                recommended=blocking == 0 and parsed > 0,
                severity="medium",
                reversibility="high",
                tradeoffs=(
                    "Keeps current PR focused while preserving reviewer feedback.",
                    "Can accumulate debt if follow-ups are not queued.",
                ),
                evidence_needed=("Clear rationale for deferring each non-blocking item.",),
                next_safe_command="python3 scripts/agent_loop.py batch-plan",
                manual_approval="Required before changing queue/plan docs.",
            ),
            DecisionOption(
                label="Reject or defer a finding with rationale",
                recommended=False,
                severity="medium",
                reversibility="medium",
                tradeoffs=(
                    "Useful when a finding is out of scope or factually wrong.",
                    "Risky if done without evidence; may hide a real regression.",
                ),
                evidence_needed=("File/line evidence, contract citation, or test output supporting the decision.",),
                next_safe_command="python3 scripts/agent_loop.py render-prompt --task <TASK_ID>",
                manual_approval="Human reviewer should approve rejected findings.",
            ),
        ),
    )


def _claim_decision_point(changed_files: Sequence[str], *, repo_root: Path) -> DecisionPoint:
    surface = classify_changed_files(changed_files)
    context = (
        f"Surface: `{surface.surface}`",
        f"Confidence: `{surface.confidence}`",
        f"Required reviewer: `{surface.reviewer_type}`",
        "Matched files: "
        + (", ".join(f"`{_display_path(path)}`" for path in surface.matched_files) if surface.matched_files else "`N/A`"),
        "Disallowed claims: " + "; ".join(surface.disallowed_claims),
    )
    surfaces = {surface.surface, *surface.additional_surfaces}
    sensitive = bool(surfaces & {"private-real-eval", "privacy-sensitive-artifact", "benchmark-reporting"})
    return DecisionPoint(
        gate="claim-boundary",
        title="Decide what claims are allowed",
        context=context,
        options=(
            DecisionOption(
                label="Make no benchmark/performance/private-data claim",
                recommended=True,
                severity="low",
                reversibility="high",
                tradeoffs=(
                    "Safest wording; avoids overclaiming from insufficient evidence.",
                    "May undersell a valid improvement until evidence is gathered.",
                ),
                evidence_needed=("Changed-file surface classification and validation command list.",),
                next_safe_command="python3 scripts/agent_loop.py suggest-validation --from-git",
                manual_approval="Not required for conservative no-claim wording.",
            ),
            DecisionOption(
                label="Make a scoped public fixture or synthetic benchmark claim",
                recommended=False,
                severity="medium",
                reversibility="medium",
                tradeoffs=(
                    "Can be useful when provenance is complete and wording is narrow.",
                    "Unsafe if phrased as real-world RFP quality or private eval success.",
                ),
                evidence_needed=(
                    "Dataset/config/index/provenance and exact command output.",
                    "Benchmark Validity Audit reviewer pass.",
                ),
                next_safe_command="python3 scripts/agent_loop.py review-prompt --task <TASK_ID> --from-git",
                manual_approval="Required before benchmark/performance claims.",
            ),
            DecisionOption(
                label="Use private real-eval evidence",
                recommended=False,
                severity="critical" if sensitive else "high",
                reversibility="low",
                tradeoffs=(
                    "Most relevant evidence for private real-data behavior.",
                    "Highest privacy and claim risk; aggregate-only evidence is mandatory.",
                ),
                evidence_needed=(
                    "Aggregate-only private delta, no raw question/answer/evidence/doc_id/chunk_id/filename/local path.",
                    "Human approval of claim wording.",
                ),
                next_safe_command="python3 scripts/_governance.py --check-eval-privacy",
                manual_approval="Required for private real-eval decisions and claims.",
            ),
        ),
    )


def _ship_decision_point(*, pr: str | None, changed_files: Sequence[str]) -> DecisionPoint:
    safe_pr = _validate_pr_selector(pr) if pr else "N/A"
    validation = suggest_validation_commands(changed_files) if changed_files else ["git diff --check"]
    context = (
        f"PR: `{safe_pr}`",
        f"Changed files known: `{len(changed_files)}`",
        f"Suggested validation count: `{len(validation)}`",
    )
    return DecisionPoint(
        gate="ship",
        title="Decide whether to push, open PR, merge, close, or delete",
        context=context,
        options=(
            DecisionOption(
                label="Hold shipping and run local preflight",
                recommended=True,
                severity="medium",
                reversibility="high",
                tradeoffs=(
                    "Keeps the state local until validation and handoff evidence are clear.",
                    "Delays collaboration on GitHub.",
                ),
                evidence_needed=("Focused validation, handoff-check, review prompt.",),
                next_safe_command="python3 scripts/agent_loop.py preflight --task <TASK_ID> --from-git --write-prompts",
                manual_approval="Not required for local preflight.",
            ),
            DecisionOption(
                label="Push or create/update PR outside this CLI",
                recommended=False,
                severity="high",
                reversibility="medium",
                tradeoffs=(
                    "Makes work reviewable in GitHub.",
                    "Can expose incomplete state or trigger CI/review churn.",
                ),
                evidence_needed=("Clean diff, validation evidence, branch/issue convention, PR body evidence.",),
                next_safe_command="make check-branch",
                manual_approval="Required by project shipping policy even though this helper does not execute it.",
            ),
            DecisionOption(
                label="Merge, close, or delete branch outside this CLI",
                recommended=False,
                severity="critical",
                reversibility="low",
                tradeoffs=(
                    "Can finish or clean up work quickly.",
                    "Most irreversible path; stacked PRs, unresolved review, or branch deletion can lose coordination state.",
                ),
                evidence_needed=("CI state, unresolved review status, stacked dependent check, explicit human approval.",),
                next_safe_command="make ship-review-gate PR=<N>",
                manual_approval="Required for merge, close, delete, and force-push decisions.",
            ),
        ),
    )


def _no_input_decision_point() -> DecisionPoint:
    return DecisionPoint(
        gate="orientation",
        title="Choose the next decision input",
        context=("No task, batch, review-followup, changed files, or ship gate input was provided.",),
        options=(
            DecisionOption(
                label="Generate current loop state first",
                recommended=True,
                severity="low",
                reversibility="high",
                tradeoffs=(
                    "Gives the decision helper concrete evidence.",
                    "Adds one local report generation step.",
                ),
                evidence_needed=("PR state, task briefs, batch plan, or changed-file surface.",),
                next_safe_command="python3 scripts/agent_loop.py map",
                manual_approval="Not required.",
            ),
        ),
    )


def render_decision_brief(points: Sequence[DecisionPoint], *, repo_root: Path = ROOT_DIR) -> str:
    lines = [
        "# Agent Loop Decision Brief",
        "",
        "- This is a decision-support artifact, not an approval or execution command.",
        "- It does not edit queue/plan docs, push, create/close/merge PRs, delete branches, force-push, or run private eval.",
        "- Recommended defaults prefer reversible local actions and conservative claim wording.",
        "",
    ]
    for point in points:
        lines.extend(
            [
                f"## {point.title}",
                "",
                f"- Gate: `{point.gate}`",
                "",
                "### Context",
                "",
            ]
        )
        lines.extend(f"- {_sanitize_dynamic_text(item)}" for item in point.context)
        lines.extend(["", "### Options", ""])
        for index, option in enumerate(point.options, start=1):
            marker = " (recommended default)" if option.recommended else ""
            lines.extend(
                [
                    f"#### {index}. {option.label}{marker}",
                    "",
                    f"- Severity: `{option.severity}`",
                    f"- Reversibility: `{option.reversibility}`",
                    f"- Manual approval: {option.manual_approval}",
                    "- Trade-offs:",
                ]
            )
            lines.extend(f"  - {_sanitize_dynamic_text(item)}" for item in option.tradeoffs)
            lines.append("- Evidence needed:")
            lines.extend(f"  - {_sanitize_dynamic_text(item)}" for item in option.evidence_needed)
            lines.extend(
                [
                    "- Next safe command:",
                    "",
                    "```bash",
                    _sanitize_command_text(option.next_safe_command),
                    "```",
                    "",
                ]
            )
    return _sanitize_dynamic_text("\n".join(lines)).rstrip() + "\n"


def render_loop_map() -> str:
    return """# BidMate Agent Loop Map

```mermaid
flowchart TD
  A["Repo state: queue, plans, PRs, reports"] --> B["pr-scan: read GitHub PR metadata"]
  A --> MCP["agent-loop-mcp: expose safe local loop tools to MCP clients"]
  MCP --> D
  B --> C["next-from-prs: generate next-action report and task briefs"]
  C --> D["batch-plan: group serial, parallel, review, and manual-gated lanes"]
  D --> E["decision-brief: explain options, trade-offs, severity, and safe commands"]
  E --> F["draft-task: generate queue and plan drafts"]
  F --> G["promote-draft: dry-run queue/plan diff only"]
  G --> H{"Human gate: accept task scope and plan?"}
  H -->|approved| I["render-prompt: copy-paste Codex session prompt"]
  I --> J["Codex implementation session"]
  J --> K["suggest-validation or validate: focused safe local checks"]
  K --> VH["validation-history: local JSONL evidence ledger"]
  K --> AP["auto-pass-check: low-risk local gate decision"]
  AP --> L["claim-audit and privacy-audit-output"]
  L --> POLICY["claim-policy and privacy-regression"]
  L --> M["handoff-check: fail closed on missing or weak evidence"]
  M --> N["review-prompt: adversarial reviewer prompt"]
  M --> PKT["approval-packet, pr-body, context-pack"]
  PKT --> READY["readiness-score and branch-issue-hygiene"]
  PKT --> SIM["ship-simulate: predict stop points without remote mutation"]
  SIM --> ASP["auto-ship-plan: bridge to existing make ship-arm without arming"]
  N --> RT["review-threads: unresolved thread ingest"]
  RT --> RP["review-plan: triage review findings"]
  RP --> O["review-followup: convert findings to local follow-up briefs"]
  O --> P["decision-brief, gate-brief, and gate-status"]
  P --> Q["loop-state: machine-readable state JSON"]
  Q --> DB["dashboard and stale-reports"]
  DB --> FRESH["artifact-freshness and manifest freshness"]
  DB --> ARCH["architecture-decision and architecture-brief"]
  DB --> HTML["dashboard-html and manifest freshness"]
  N --> CI["ci-summary and ci-ingest: convert CI failures to follow-up briefs"]
  PKT --> BODY["pr-body-check and ship-command-pack"]
  BODY --> ASP
  ASP --> STACK["dependency-graph and stacked-risk before merge/delete cleanup"]
  RP --> PATCH["review-patch-plan and patch-proposal: dry-run safe patch"]
  ARCH --> ADR["adr-reserve: draft-only ADR reservation"]
  C --> WORKSET["workset-recommend: serial/parallel/review/manual sets"]
  A --> INT["integration-pack and scheduled-status recipes"]
  INT --> MCP
  Q --> R{"Human gate: review, claims, merge, close, push, delete?"}
  R -->|end-to-end approved| SHIP["make ship-arm: approved single end-to-end ship pipeline"]
  R -->|manual fallback approved| EXEC["human-gated-exec: action-by-action remote mutation fallback"]
  SHIP --> S["Existing ship workflow"]
  EXEC --> S["Manual fallback workflow"]
  R -->|more work| A
```

Automation points:
- pr-scan: read-only `gh pr list` JSON export.
- next-from-prs: deterministic wrapper around `scripts/ai_next_actions.py`.
- pr-health: group exported PR state into CI, review, stale, draft, blocked, and ready lanes.
- batch-plan: group local task briefs into serial, parallel-safe, review-only, and manual-gated lanes.
- decision-brief: explain human-gate options, trade-offs, severity, reversibility, evidence, and next safe commands.
- draft-task: local queue/plan drafts under `reports/agent_loop/`.
- promote-draft: local dry-run diff for queue/plan promotion; no tracked files are changed.
- propose-queue-plan: dry-run queue/plan patch proposal; no tracked files are changed.
- gate-status: summarize the current stop point and next safe command.
- gate-brief: explain one human gate with options, trade-offs, severity, reversibility, and evidence.
- claim-audit: audit risky claim wording against eval/privacy surface classification.
- claim-policy: render allowed/disallowed claim boundaries for the current surface.
- privacy-audit-output: scan generated local artifacts for private raw values.
- privacy-regression: run public sanitizer fixtures to guard prompt/report redaction.
- review-threads: read unresolved review-thread state without resolving or replying.
- approval-packet: bundle pre-PR/pre-ship evidence into one local report.
- readiness-score: combine local ship signals into a decision-support score.
- branch-issue-hygiene: check branch, issue, task, and PR-body linkage.
- pr-body: draft `.github/pull_request_template.md` content without creating a PR.
- context-pack: render a redacted cross-agent handoff bundle.
- integration-pack: package Codex/Claude/ChatGPT/MCP read-only usage guidance.
- scheduled-status: render a safe recurring status recipe without installing it.
- architecture-decision: detect whether human architecture review is needed.
- architecture-brief: summarize ADR/load-bearing trade-offs without choosing an architecture.
- adr-reserve: propose ADR number and local draft without touching `docs/adr/`.
- ship-simulate: predict auto-ship stop points without push/PR/merge/close/delete.
- auto-ship-prepare: prepare or create a local ADR 0007 branch for the primary `make ship-arm` pipeline; branch creation requires `--confirm-human-approved`.
- auto-ship-plan: render a readiness-backed bridge to the primary `make ship-arm` Stop-hook pipeline without arming it.
- ship-command-pack: render human-gated ship commands without executing them.
- human-gated-exec: execute push/PR create/merge/close/remote branch delete/force-with-lease only as an action-by-action fallback with `--confirm-human-approved` and action-specific gates.
- dependency-graph: render stacked PR graph without merge/delete mutation.
- stacked-risk: detect dependent PR risk before merge/delete cleanup.
- pr-body-check: verify `Closes`, §5b, claim, and privacy boundaries before PR creation.
- ci-summary: summarize CI signals without re-running or mutating CI.
- ci-ingest: normalize CI failures into local follow-up briefs.
- review-patch-plan: generate review triage plus safe patch proposal together.
- patch-proposal: render dry-run whitespace-only patch proposal for public-safe files.
- manifest: write input-hash freshness metadata for generated artifacts.
- artifact-freshness: alias around stale/manifest freshness checks.
- validation-history: summarize local JSONL validation history.
- workset-recommend: recommend serial, parallel-safe, review-only, and manual-gated task sets.
- automation-coverage: map implemented automation candidates to command surfaces.
- auto-pass-check: fail-closed low-risk gate check; named strict profiles require high-confidence docs/CI/tooling surfaces and passed validation.
- loop-state: write machine-readable current loop state JSON.
- dashboard: render a human-readable loop report from loop-state signals.
- dashboard-html: render static local HTML view of the dashboard.
- stale-reports: separate current vs stale local report artifacts; dry-run by default.
- apply-queue-plan: apply queue/plan drafts only with explicit `--confirm-human-approved`.
- mcp-config: render placeholder-based MCP client config samples.
- review-followup: parse reviewer findings into local follow-up task briefs.
- review-ingest: normalize local or PR review text into review-followup briefs.
- safe-fix: dry-run/apply whitespace-only local fixes for supported public-safe text files.
- render-prompt, status, preflight, classify-surface, suggest-validation, validate, handoff-check, review-prompt.
- agent-loop-mcp: stdio MCP adapter for external coding agents and desktop clients; exposes local read/report tools, not shipping mutations.
- agent-loop-artifacts.yml: PR-time informational GitHub Actions artifact generation.

Human intervention points:
- Apply a draft to `tasks/queue.md` or `docs/plans/*.md`.
- Create or switch the local shipping branch when detached HEAD or protected branch state is detected.
- Decide architecture tradeoffs, benchmark/performance claims, or private real-eval meaning.
- Push, create/merge/close PRs, delete branches, or force-push.
- Prefer `make ship-arm` for approved end-to-end shipping; use `human-gated-exec` only as a manual fallback after explicit approval and action-specific preflight.
- Approve reviewer findings and shipping path.
"""


def _resolve_input_path(path: Path, *, repo_root: Path) -> Path:
    candidate = path if path.is_absolute() else repo_root / path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ValueError("input path must stay under the repository root") from exc
    return resolved


def _resolve_task_brief(path: Path | None, *, repo_root: Path) -> Path:
    if path is not None:
        resolved = _resolve_input_path(path, repo_root=repo_root)
        if not resolved.exists():
            raise ValueError(f"task brief not found: {_display_path(str(path), repo_root=repo_root)}")
        return resolved
    tasks_dir = repo_root / "reports" / "agent_loop" / "codex_tasks"
    candidates = sorted(tasks_dir.glob("*.md")) if tasks_dir.is_dir() else []
    if not candidates:
        raise ValueError("no task brief found under reports/codex_tasks; run next-from-prs first or pass --task-brief")
    return candidates[0]


def _parse_task_brief(text: str) -> dict[str, str]:
    title_match = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "Untitled agent-loop follow-up"
    fields = _field_map(text)
    verification = ""
    verification_section = _section_text(text, "Verification")
    fenced = FENCED_BASH_RE.search(verification_section)
    if fenced:
        verification = "\n".join(
            line.strip()
            for line in fenced.group("body").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    if not verification:
        verification = "git diff --check"
    return {
        "title": _sanitize_dynamic_text(title),
        "classification": _clean_scalar(fields.get(_normalize_field("Classification"), "unknown")),
        "source": _clean_scalar(fields.get(_normalize_field("Source"), "planner")),
        "reason": _clean_scalar(fields.get(_normalize_field("Reason"), "no reason captured")),
        "goal": _clean_section(_section_text(text, "Goal")) or "Define the smallest safe follow-up from the planner brief.",
        "expected_evidence": _clean_section(_section_text(text, "Expected Evidence"))
        or "Public-safe evidence or a documented no-go decision.",
        "verification": _sanitize_command_text(verification),
    }


def _clean_scalar(text: str) -> str:
    return _sanitize_inline_text(text.strip().strip("`"))


def _clean_section(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"```.*?```", "", cleaned, flags=re.DOTALL).strip()
    return _sanitize_dynamic_text(cleaned)


def _render_task_drafts(
    brief: dict[str, str],
    *,
    task_id: str,
    brief_path: Path,
    repo_root: Path,
) -> tuple[str, str]:
    title = brief["title"]
    slug = _slugify(title)
    suggested_plan = f"docs/plans/{task_id}-{slug}.md"
    source_brief = _display_path(_repo_path(brief_path, repo_root), repo_root=repo_root)
    verification = _ensure_git_diff_check(brief["verification"])
    queue_text = f"""<!-- Draft generated by scripts/agent_loop.py draft-task. Review before applying. -->
## {task_id} — {title}

- ID: {task_id}
- Title: {title}
- Status: backlog
- Owner role: Planner -> Implementer -> Reviewer

### Goal

{brief["goal"]}

### Context

- Classification: `{brief["classification"]}`
- Source: `{brief["source"]}`
- Reason: {brief["reason"]}
- Source brief: `{source_brief}`
- Suggested plan path: `{suggested_plan}`

### Acceptance Criteria

- [ ] Scope stays limited to the cited workflow surface.
- [ ] Public-safe evidence or no-go rationale is captured without raw private data.
- [ ] Reviewer prompt covers any eval, benchmark, privacy, or architecture surface touched.

### Validation Commands

```bash
{verification}
```

### Evidence Required

{brief["expected_evidence"]}

### Related Plan / Issue / PR Links

- Plan: [`{suggested_plan}`](../{suggested_plan})
"""
    plan_text = f"""# Plan: {task_id} {title}

- Status: draft
- Owner role: Planner -> Implementer -> Reviewer
- Related task: `tasks/queue.md::{task_id}`
- Source brief: `{source_brief}`
- Suggested final path: `{suggested_plan}`

## Problem

{brief["reason"]}

## Desired Outcome

{brief["goal"]}

## Scope

- Convert the planner brief into one narrow, reviewable Codex task.
- Reuse existing BidMate operating docs, queue, plans, validation commands, and reviewer prompts.
- Keep generated artifacts local unless a human promotes a redacted artifact.

## Out of Scope

- Auto-merge, auto-push, PR creation/close/merge, branch deletion, or force-push.
- Benchmark, performance, private real-eval, or architecture tradeoff decisions without human approval.
- Raw private question, answer, evidence, doc_id, chunk_id, filenames, or exact local paths.

## Surface / Claim Boundary

- Initial classification: `{brief["classification"]}`
- Eval surface: classify again after implementation if changed files touch eval, benchmark, metrics, reports, configs, or claims.
- Disallowed claim: do not claim product quality, benchmark lift, or private real-eval success from this draft alone.

## Implementation Steps

1. Read the required operating docs and this plan.
2. Inspect the cited workflow surface and existing tests.
3. Make the smallest scoped change.
4. Add or update focused tests.
5. Run focused validation and `git diff --check`.
6. Leave a handoff with required fields and reviewer focus.

## Validation

```bash
{verification}
```

## Reviewer Focus

- Scope control against the source brief.
- Privacy boundary and claim wording.
- Conservative eval surface classification.
- Validation evidence matches commands actually run.

## Session Handoff

- Role:
- Lifecycle stage:
- Branch / worktree:
- Task: {task_id}
- Current status:
- Files touched:
- Commands run:
- Results:
- Validation evidence:
- Blockers:
- Open risks:
- Next action:
- Next safe command:
- Reviewer focus:
- Eval surface:
"""
    return _sanitize_dynamic_text(queue_text).rstrip() + "\n", _sanitize_dynamic_text(plan_text).rstrip() + "\n"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60].strip("-") or "agent-loop-task"


def _ensure_git_diff_check(commands: str) -> str:
    lines = [line.strip() for line in commands.splitlines() if line.strip()]
    if "git diff --check" not in lines:
        lines.append("git diff --check")
    return "\n".join(_sanitize_command_text(line) for line in lines)


def _write_or_stdout(text: str, out: Path | None) -> None:
    if out is None:
        sys.stdout.write(text)
        return
    safe_out = _safe_output_path(out)
    safe_out.parent.mkdir(parents=True, exist_ok=True)
    safe_out.write_text(text, encoding="utf-8")
    sys.stdout.write(f"[OK] wrote {_repo_path(safe_out, ROOT_DIR)}\n")


def _safe_output_path(out: Path, *, repo_root: Path = ROOT_DIR) -> Path:
    candidate = out if out.is_absolute() else repo_root / out
    root = (repo_root / "reports" / "agent_loop").resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("--out must stay under reports/agent_loop/") from exc
    return candidate


def _safe_reports_path(out: Path, *, repo_root: Path = ROOT_DIR) -> Path:
    candidate = out if out.is_absolute() else repo_root / out
    root = (repo_root / "reports").resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("generated report output must stay under reports/") from exc
    return candidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    render = sub.add_parser("render-prompt", help="Render a copy-paste Codex prompt.")
    render.add_argument("--task", required=True, help="Task id, e.g. T-2026-0003")
    render.add_argument("--role", default="Implementer")
    render.add_argument("--plan", type=Path)
    render.add_argument("--out", type=Path, help=f"Optional output path. Default stdout.")

    handoff = sub.add_parser("handoff-check", help="Check latest handoff block.")
    handoff.add_argument("--task", required=True)
    handoff.add_argument("--plan", type=Path)
    handoff.add_argument("--changed-files", type=Path)
    handoff.add_argument("--from-git", action="store_true")
    handoff.add_argument("--pr")

    review = sub.add_parser("review-prompt", help="Render adversarial review prompt.")
    review.add_argument("--task", required=True)
    review.add_argument("--pr")
    review.add_argument("--branch")
    review.add_argument("--changed-files", type=Path)
    review.add_argument("--from-git", action="store_true")
    review.add_argument("--out", type=Path, help=f"Optional output path. Default stdout.")

    classify = sub.add_parser("classify-surface", help="Classify changed-file surface.")
    classify.add_argument("--changed-files", type=Path)
    classify.add_argument("--from-git", action="store_true")
    classify.add_argument("--pr")

    suggest = sub.add_parser("suggest-validation", help="Suggest focused validation.")
    suggest.add_argument("--changed-files", type=Path)
    suggest.add_argument("--from-git", action="store_true")
    suggest.add_argument("--pr")

    validate = sub.add_parser("validate", help="Run allowlisted safe local validation.")
    validate.add_argument("--changed-files", type=Path)
    validate.add_argument("--from-git", action="store_true")
    validate.add_argument("--pr")
    validate.add_argument("--keep-going", action="store_true")
    validate.add_argument("--record-history", action="store_true")
    validate.add_argument("--history", type=Path, default=DEFAULT_VALIDATION_HISTORY)

    status = sub.add_parser("status", help="Summarize task, handoff, surface, and validation suggestions.")
    status.add_argument("--task")
    status.add_argument("--changed-files", type=Path)
    status.add_argument("--from-git", action="store_true")
    status.add_argument("--pr")

    preflight = sub.add_parser("preflight", help="Run handoff/surface/validation preflight.")
    preflight.add_argument("--task", required=True)
    preflight.add_argument("--changed-files", type=Path)
    preflight.add_argument("--from-git", action="store_true")
    preflight.add_argument("--pr")
    preflight.add_argument("--write-prompts", action="store_true")

    pr_scan = sub.add_parser("pr-scan", help="Export read-only PR state for planning.")
    pr_scan.add_argument("--out", type=Path, default=DEFAULT_PR_STATE)
    pr_scan.add_argument("--state", choices=("open", "closed", "all"), default="open")
    pr_scan.add_argument("--limit", type=int, default=30)
    pr_scan.add_argument(
        "--include-body",
        action="store_true",
        help="Include PR body in local ignored state; use only when PR bodies are public-safe.",
    )

    next_prs = sub.add_parser("next-from-prs", help="Generate next-action briefs from PR state JSON.")
    next_prs.add_argument("--pr-json", type=Path, default=DEFAULT_PR_STATE)
    next_prs.add_argument("--out-md", type=Path, default=DEFAULT_AI_NEXT_ACTIONS)
    next_prs.add_argument("--tasks-dir", type=Path, default=DEFAULT_CODEX_TASKS_DIR)
    next_prs.add_argument("--readiness-summary", action="append", type=Path, default=[])
    next_prs.add_argument("--readiness-report", action="append", type=Path, default=[])
    next_prs.add_argument("--real100-dir", type=Path)
    next_prs.add_argument("--page-metadata-index-dir", type=Path)

    draft = sub.add_parser("draft-task", help="Draft queue and plan entries from a task brief.")
    draft.add_argument("--task-brief", type=Path)
    draft.add_argument("--task-id", default=DEFAULT_DRAFT_TASK_ID)
    draft.add_argument("--out-queue", type=Path, default=DEFAULT_QUEUE_DRAFT)
    draft.add_argument("--out-plan", type=Path, default=DEFAULT_PLAN_DRAFT)

    draft_next = sub.add_parser("draft-next", help="Scan PRs, generate briefs, and draft queue/plan artifacts.")
    draft_next.add_argument("--task-id", default=DEFAULT_DRAFT_TASK_ID)
    draft_next.add_argument("--state", choices=("open", "closed", "all"), default="open")
    draft_next.add_argument("--limit", type=int, default=30)
    draft_next.add_argument(
        "--include-body",
        action="store_true",
        help="Include PR body in local ignored state; use only when PR bodies are public-safe.",
    )

    batch = sub.add_parser("batch-plan", help="Group generated task briefs into execution lanes.")
    batch.add_argument("--tasks-dir", type=Path, default=DEFAULT_CODEX_TASKS_DIR)
    batch.add_argument("--out", type=Path, default=DEFAULT_BATCH_PLAN)
    batch.add_argument("--json-out", type=Path, default=DEFAULT_BATCH_PLAN_JSON)
    batch.add_argument("--no-json", action="store_true")
    batch.add_argument("--max-items", type=int, default=12)

    followup = sub.add_parser("review-followup", help="Convert reviewer findings into local follow-up briefs.")
    followup.add_argument("--review", required=True, type=Path)
    followup.add_argument("--out", type=Path, default=DEFAULT_REVIEW_FOLLOWUPS)
    followup.add_argument("--tasks-dir", type=Path, default=DEFAULT_REVIEW_FOLLOWUPS_DIR)

    decision = sub.add_parser("decision-brief", help="Explain human-gate options, trade-offs, and risks.")
    decision.add_argument("--task")
    decision.add_argument("--batch", type=Path)
    decision.add_argument("--review-followups", type=Path)
    decision.add_argument("--gate", choices=("auto", "task", "plan", "review", "claim", "ship"), default="auto")
    decision.add_argument("--changed-files", type=Path)
    decision.add_argument("--from-git", action="store_true")
    decision.add_argument("--pr")
    decision.add_argument("--out", type=Path, default=DEFAULT_DECISION_BRIEF)

    promote = sub.add_parser("promote-draft", help="Render a dry-run diff for queue/plan draft promotion.")
    promote.add_argument("--queue-draft", type=Path, default=DEFAULT_QUEUE_DRAFT)
    promote.add_argument("--plan-draft", type=Path, default=DEFAULT_PLAN_DRAFT)
    promote.add_argument("--out", type=Path, default=DEFAULT_PROMOTE_DRAFT)

    gate_status = sub.add_parser("gate-status", help="Summarize the current human gate and next safe command.")
    gate_status.add_argument("--task")
    gate_status.add_argument("--batch", type=Path)
    gate_status.add_argument("--review-followups", type=Path)
    gate_status.add_argument("--changed-files", type=Path)
    gate_status.add_argument("--from-git", action="store_true")
    gate_status.add_argument("--pr")
    gate_status.add_argument("--out", type=Path)

    claim = sub.add_parser("claim-audit", help="Audit claim wording against the changed-file surface.")
    claim.add_argument("--text", type=Path)
    claim.add_argument("--changed-files", type=Path)
    claim.add_argument("--from-git", action="store_true")
    claim.add_argument("--pr")
    claim.add_argument("--out", type=Path, default=DEFAULT_CLAIM_AUDIT)

    privacy = sub.add_parser("privacy-audit-output", help="Scan local agent-loop artifacts for private raw values.")
    privacy.add_argument("--path", type=Path, default=DEFAULT_REPORT_DIR)
    privacy.add_argument("--out", type=Path, default=DEFAULT_PRIVACY_AUDIT)

    auto_pass = sub.add_parser("auto-pass-check", help="Check whether a low-risk local gate can continue without human review.")
    auto_pass.add_argument("--task")
    auto_pass.add_argument("--changed-files", type=Path)
    auto_pass.add_argument("--from-git", action="store_true")
    auto_pass.add_argument("--claim-text", type=Path)
    auto_pass.add_argument("--run-validation", action="store_true")
    auto_pass.add_argument("--strict", action="store_true")
    auto_pass.add_argument(
        "--profile",
        choices=("standard", "docs-only-strict", "ci-only-strict", "agent-loop-tooling-strict"),
        default="standard",
    )
    auto_pass.add_argument("--out", type=Path, default=DEFAULT_AUTO_PASS)

    dashboard = sub.add_parser("dashboard", help="Render a human-readable dashboard from loop state.")
    dashboard.add_argument("--task")
    dashboard.add_argument("--batch", type=Path)
    dashboard.add_argument("--review-followups", type=Path)
    dashboard.add_argument("--changed-files", type=Path)
    dashboard.add_argument("--from-git", action="store_true")
    dashboard.add_argument("--pr")
    dashboard.add_argument("--out", type=Path, default=DEFAULT_DASHBOARD)

    mcp_config = sub.add_parser("mcp-config", help="Render MCP client config samples.")
    mcp_config.add_argument("--out", type=Path, default=DEFAULT_MCP_CLIENT_CONFIG)

    review_ingest = sub.add_parser("review-ingest", help="Ingest review output or PR review text into follow-up briefs.")
    review_ingest.add_argument("--review", action="append", type=Path, default=[])
    review_ingest.add_argument("--pr")
    review_ingest.add_argument("--out", type=Path, default=DEFAULT_REVIEW_INGEST)
    review_ingest.add_argument("--followup-out", type=Path, default=DEFAULT_REVIEW_FOLLOWUPS)
    review_ingest.add_argument("--tasks-dir", type=Path, default=DEFAULT_REVIEW_FOLLOWUPS_DIR)

    pr_health = sub.add_parser("pr-health", help="Analyze exported PR state into next-action lanes.")
    pr_health.add_argument("--pr-json", type=Path, default=DEFAULT_PR_STATE)
    pr_health.add_argument("--out", type=Path, default=DEFAULT_PR_HEALTH)

    safe_fix = sub.add_parser("safe-fix", help="Dry-run or apply very small local whitespace fixes.")
    safe_fix.add_argument("--changed-files", type=Path)
    safe_fix.add_argument("--from-git", action="store_true")
    safe_fix.add_argument("--apply", action="store_true")
    safe_fix.add_argument("--out", type=Path, default=DEFAULT_SAFE_FIX)

    approval = sub.add_parser("approval-packet", help="Bundle PR/shipping approval evidence into one local report.")
    approval.add_argument("--task")
    approval.add_argument("--changed-files", type=Path)
    approval.add_argument("--from-git", action="store_true")
    approval.add_argument("--pr")
    approval.add_argument("--claim-text", type=Path)
    approval.add_argument("--run-validation", action="store_true")
    approval.add_argument("--out", type=Path, default=DEFAULT_APPROVAL_PACKET)

    propose = sub.add_parser("propose-queue-plan", help="Render a dry-run queue/plan patch proposal.")
    propose.add_argument("--task-brief", type=Path)
    propose.add_argument("--task-id", default=DEFAULT_DRAFT_TASK_ID)
    propose.add_argument("--queue-draft", type=Path, default=DEFAULT_QUEUE_DRAFT)
    propose.add_argument("--plan-draft", type=Path, default=DEFAULT_PLAN_DRAFT)
    propose.add_argument("--out", type=Path, default=DEFAULT_QUEUE_PLAN_PATCH)

    pr_body = sub.add_parser("pr-body", help="Render a PR template body draft from local evidence.")
    pr_body.add_argument("--task")
    pr_body.add_argument("--changed-files", type=Path)
    pr_body.add_argument("--from-git", action="store_true")
    pr_body.add_argument("--pr")
    pr_body.add_argument("--branch")
    pr_body.add_argument("--issue")
    pr_body.add_argument("--out", type=Path, default=DEFAULT_PR_BODY)

    review_plan = sub.add_parser("review-plan", help="Triage review findings into fix and human-decision lanes.")
    review_plan.add_argument("--review", action="append", type=Path, default=[])
    review_plan.add_argument("--pr")
    review_plan.add_argument("--out", type=Path, default=DEFAULT_REVIEW_PLAN)

    stale = sub.add_parser("stale-reports", help="Report or remove stale local agent-loop artifacts.")
    stale.add_argument("--changed-files", type=Path)
    stale.add_argument("--from-git", action="store_true")
    stale.add_argument("--pr")
    stale.add_argument("--max-age-days", type=int, default=7)
    stale.add_argument("--apply", action="store_true")
    stale.add_argument("--out", type=Path, default=DEFAULT_STALE_REPORTS)

    context = sub.add_parser("context-pack", help="Render a redacted cross-agent context pack.")
    context.add_argument("--task")
    context.add_argument("--changed-files", type=Path)
    context.add_argument("--from-git", action="store_true")
    context.add_argument("--pr")
    context.add_argument("--profile", choices=("generic", "codex", "claude", "chatgpt"), default="generic")
    context.add_argument("--out", type=Path, default=DEFAULT_CONTEXT_PACK)

    arch = sub.add_parser("architecture-brief", help="Explain architecture/ADR trade-offs for changed files.")
    arch.add_argument("--changed-files", type=Path)
    arch.add_argument("--from-git", action="store_true")
    arch.add_argument("--pr")
    arch.add_argument("--out", type=Path, default=DEFAULT_ARCHITECTURE_BRIEF)

    ship_sim = sub.add_parser("ship-simulate", help="Simulate auto-ship readiness without mutating remote state.")
    ship_sim.add_argument("--task")
    ship_sim.add_argument("--changed-files", type=Path)
    ship_sim.add_argument("--from-git", action="store_true")
    ship_sim.add_argument("--pr")
    ship_sim.add_argument("--branch")
    ship_sim.add_argument("--out", type=Path, default=DEFAULT_SHIP_SIMULATION)

    auto_ship = sub.add_parser("auto-ship-plan", help="Plan existing make ship-arm usage without arming auto-ship.")
    auto_ship.add_argument("--task")
    auto_ship.add_argument("--changed-files", type=Path)
    auto_ship.add_argument("--from-git", action="store_true")
    auto_ship.add_argument("--pr")
    auto_ship.add_argument("--branch")
    auto_ship.add_argument("--ttl", default="2h")
    auto_ship.add_argument("--real-eval", choices=("auto", "skip", "async"))
    auto_ship.add_argument("--draft", action="store_true")
    auto_ship.add_argument("--dry-run", action="store_true")
    auto_ship.add_argument("--out", type=Path, default=DEFAULT_AUTO_SHIP_PLAN)

    auto_ship_prepare = sub.add_parser("auto-ship-prepare", help="Prepare local branch state for existing make ship-arm.")
    auto_ship_prepare.add_argument("--issue")
    auto_ship_prepare.add_argument("--target-branch")
    auto_ship_prepare.add_argument("--type", dest="branch_type", default="chore")
    auto_ship_prepare.add_argument("--slug", default="agent-loop-auto-ship")
    auto_ship_prepare.add_argument("--create-branch", action="store_true")
    auto_ship_prepare.add_argument("--confirm-human-approved", action="store_true")
    auto_ship_prepare.add_argument("--ttl", default="2h")
    auto_ship_prepare.add_argument("--real-eval", choices=("auto", "skip", "async"))
    auto_ship_prepare.add_argument("--draft", action="store_true", default=True)
    auto_ship_prepare.add_argument("--ready", action="store_true", help="Recommend DRAFT=false for the next ship-arm command.")
    auto_ship_prepare.add_argument("--dry-run", action="store_true", default=True)
    auto_ship_prepare.add_argument("--no-dry-run", dest="dry_run", action="store_false", help="Recommend DRY_RUN=0 for the next ship-arm command.")
    auto_ship_prepare.add_argument("--out", type=Path, default=DEFAULT_AUTO_SHIP_PREPARE)

    gate_brief = sub.add_parser("gate-brief", help="Explain a specific human gate with options and trade-offs.")
    gate_brief.add_argument("--gate", required=True, choices=sorted(GATE_BRIEF_CHOICES))
    gate_brief.add_argument("--task")
    gate_brief.add_argument("--changed-files", type=Path)
    gate_brief.add_argument("--from-git", action="store_true")
    gate_brief.add_argument("--pr")
    gate_brief.add_argument("--out", type=Path, default=DEFAULT_GATE_BRIEF)

    manifest = sub.add_parser("manifest", help="Write input-hash manifest for generated agent-loop artifacts.")
    manifest.add_argument("--changed-files", type=Path)
    manifest.add_argument("--from-git", action="store_true")
    manifest.add_argument("--pr")
    manifest.add_argument("--source-command", dest="manifest_command", default="manual")
    manifest.add_argument("--output", action="append", type=Path, default=[])
    manifest.add_argument("--out", type=Path, default=DEFAULT_MANIFEST)

    pr_check = sub.add_parser("pr-body-check", help="Validate a PR body draft before PR creation.")
    pr_check.add_argument("--body", type=Path, default=DEFAULT_PR_BODY)
    pr_check.add_argument("--changed-files", type=Path)
    pr_check.add_argument("--from-git", action="store_true")
    pr_check.add_argument("--pr")
    pr_check.add_argument("--branch")
    pr_check.add_argument("--out", type=Path, default=DEFAULT_PR_BODY_CHECK)

    ci_ingest = sub.add_parser("ci-ingest", help="Ingest CI output into local follow-up briefs.")
    ci_ingest.add_argument("--log", action="append", type=Path, default=[])
    ci_ingest.add_argument("--pr")
    ci_ingest.add_argument("--out", type=Path, default=DEFAULT_CI_INGEST)
    ci_ingest.add_argument("--tasks-dir", type=Path, default=DEFAULT_CI_FOLLOWUPS_DIR)

    stacked = sub.add_parser("stacked-risk", help="Check read-only dependent PR risk for a branch.")
    stacked.add_argument("--branch", required=True)
    stacked.add_argument("--pr-json", type=Path)
    stacked.add_argument("--out", type=Path, default=DEFAULT_STACKED_RISK)

    patch = sub.add_parser("patch-proposal", help="Render safe dry-run patch proposal for changed files.")
    patch.add_argument("--changed-files", type=Path)
    patch.add_argument("--from-git", action="store_true")
    patch.add_argument("--pr")
    patch.add_argument("--review-plan", type=Path)
    patch.add_argument("--out", type=Path, default=DEFAULT_PATCH_PROPOSAL)

    adr = sub.add_parser("adr-reserve", help="Draft an ADR reservation artifact without touching docs/adr.")
    adr.add_argument("--title", required=True)
    adr.add_argument("--out", type=Path, default=DEFAULT_ADR_RESERVATION)
    adr.add_argument("--draft-out", type=Path, default=DEFAULT_ADR_DRAFT)

    html_dash = sub.add_parser("dashboard-html", help="Render a static HTML dashboard.")
    html_dash.add_argument("--task")
    html_dash.add_argument("--changed-files", type=Path)
    html_dash.add_argument("--from-git", action="store_true")
    html_dash.add_argument("--pr")
    html_dash.add_argument("--out", type=Path, default=DEFAULT_DASHBOARD_HTML)

    ship_cmds = sub.add_parser("ship-command-pack", help="Render human-gated shipping command suggestions.")
    ship_cmds.add_argument("--pr")
    ship_cmds.add_argument("--branch")
    ship_cmds.add_argument("--out", type=Path, default=DEFAULT_SHIP_COMMANDS)

    apply_qp = sub.add_parser("apply-queue-plan", help="Apply queue/plan drafts only with explicit human approval.")
    apply_qp.add_argument("--queue-draft", type=Path, default=DEFAULT_QUEUE_DRAFT)
    apply_qp.add_argument("--plan-draft", type=Path, default=DEFAULT_PLAN_DRAFT)
    apply_qp.add_argument("--confirm-human-approved", action="store_true")
    apply_qp.add_argument("--out", type=Path, default=DEFAULT_APPLY_QUEUE_PLAN)

    review_threads = sub.add_parser("review-threads", help="Ingest unresolved review threads into local triage.")
    review_threads.add_argument("--threads-json", type=Path)
    review_threads.add_argument("--pr")
    review_threads.add_argument("--out", type=Path, default=DEFAULT_REVIEW_THREADS)

    ci_summary = sub.add_parser("ci-summary", help="Summarize CI logs or read-only PR check state.")
    ci_summary.add_argument("--log", action="append", type=Path, default=[])
    ci_summary.add_argument("--pr")
    ci_summary.add_argument("--out", type=Path, default=DEFAULT_CI_SUMMARY)

    readiness = sub.add_parser("readiness-score", help="Score local PR readiness signals without approving ship.")
    readiness.add_argument("--task")
    readiness.add_argument("--changed-files", type=Path)
    readiness.add_argument("--from-git", action="store_true")
    readiness.add_argument("--pr")
    readiness.add_argument("--body", type=Path)
    readiness.add_argument("--branch")
    readiness.add_argument("--claim-text", type=Path)
    readiness.add_argument("--out", type=Path, default=DEFAULT_READINESS_SCORE)

    artifact_freshness = sub.add_parser("artifact-freshness", help="Alias for stale report freshness checks.")
    artifact_freshness.add_argument("--changed-files", type=Path)
    artifact_freshness.add_argument("--from-git", action="store_true")
    artifact_freshness.add_argument("--pr")
    artifact_freshness.add_argument("--max-age-days", type=int, default=7)
    artifact_freshness.add_argument("--out", type=Path, default=DEFAULT_STALE_REPORTS)

    review_patch = sub.add_parser("review-patch-plan", help="Generate review plan and safe patch proposal together.")
    review_patch.add_argument("--review", action="append", type=Path, default=[])
    review_patch.add_argument("--pr")
    review_patch.add_argument("--changed-files", type=Path)
    review_patch.add_argument("--from-git", action="store_true")
    review_patch.add_argument("--review-out", type=Path, default=DEFAULT_REVIEW_PLAN)
    review_patch.add_argument("--patch-out", type=Path, default=DEFAULT_PATCH_PROPOSAL)

    qp_sync = sub.add_parser("queue-plan-sync", help="Render queue/plan sync proposal without tracked-doc mutation.")
    qp_sync.add_argument("--task-brief", type=Path)
    qp_sync.add_argument("--task-id", default=DEFAULT_DRAFT_TASK_ID)
    qp_sync.add_argument("--out", type=Path, default=DEFAULT_QUEUE_PLAN_PATCH)

    dependency = sub.add_parser("dependency-graph", help="Render a read-only stacked PR dependency graph.")
    dependency.add_argument("--branch", required=True)
    dependency.add_argument("--pr-json", type=Path)
    dependency.add_argument("--out", type=Path, default=DEFAULT_DEPENDENCY_GRAPH)

    hygiene = sub.add_parser("branch-issue-hygiene", help="Check branch, issue, task, and PR-body linkage.")
    hygiene.add_argument("--branch")
    hygiene.add_argument("--body", type=Path)
    hygiene.add_argument("--task")
    hygiene.add_argument("--out", type=Path, default=DEFAULT_BRANCH_ISSUE_HYGIENE)

    integration = sub.add_parser("integration-pack", help="Render Codex/Claude/ChatGPT/MCP integration guidance.")
    integration.add_argument("--out", type=Path, default=DEFAULT_INTEGRATION_PACK)

    scheduled = sub.add_parser("scheduled-status", help="Render a safe scheduled status recipe without installing it.")
    scheduled.add_argument("--out", type=Path, default=DEFAULT_SCHEDULE_CONFIG)

    history = sub.add_parser("validation-history", help="Summarize local validation JSONL history.")
    history.add_argument("--history", type=Path, default=DEFAULT_VALIDATION_HISTORY)
    history.add_argument("--limit", type=int, default=10)
    history.add_argument("--out", type=Path, default=DEFAULT_VALIDATION_HISTORY_REPORT)

    privacy_regression = sub.add_parser("privacy-regression", help="Run public fixture sanitizer regression checks.")
    privacy_regression.add_argument("--out", type=Path, default=DEFAULT_PRIVACY_REGRESSION)

    claim_policy = sub.add_parser("claim-policy", help="Render claim policy for a changed-file surface and optional text.")
    claim_policy.add_argument("--text", type=Path)
    claim_policy.add_argument("--changed-files", type=Path)
    claim_policy.add_argument("--from-git", action="store_true")
    claim_policy.add_argument("--pr")
    claim_policy.add_argument("--out", type=Path, default=DEFAULT_CLAIM_POLICY)

    arch_decision = sub.add_parser("architecture-decision", help="Detect whether human architecture review is needed.")
    arch_decision.add_argument("--changed-files", type=Path)
    arch_decision.add_argument("--from-git", action="store_true")
    arch_decision.add_argument("--pr")
    arch_decision.add_argument("--out", type=Path, default=DEFAULT_ARCHITECTURE_DECISION)

    workset = sub.add_parser("workset-recommend", help="Recommend serial/parallel/review/manual worksets.")
    workset.add_argument("--batch", type=Path)
    workset.add_argument("--tasks-dir", type=Path, default=DEFAULT_CODEX_TASKS_DIR)
    workset.add_argument("--max-items", type=int, default=12)
    workset.add_argument("--out", type=Path, default=DEFAULT_WORKSET_RECOMMENDATION)

    coverage = sub.add_parser("automation-coverage", help="Render coverage map for implemented automation candidates.")
    coverage.add_argument("--out", type=Path, default=DEFAULT_AUTOMATION_COVERAGE)

    gated = sub.add_parser("human-gated-exec", help="Execute approved remote mutations only after explicit human approval.")
    gated.add_argument("--action", required=True, choices=sorted(HUMAN_GATED_ACTIONS))
    gated.add_argument("--confirm-human-approved", action="store_true")
    gated.add_argument("--dry-run", action="store_true")
    gated.add_argument("--branch")
    gated.add_argument("--pr")
    gated.add_argument("--body", type=Path)
    gated.add_argument("--base")
    gated.add_argument("--title")
    gated.add_argument("--ready", action="store_true", help="Create PR as ready instead of draft.")
    gated.add_argument("--confirm-review-gate-passed", action="store_true")
    gated.add_argument("--confirm-dependents-reviewed", action="store_true")
    gated.add_argument("--confirm-force-with-lease", action="store_true")
    gated.add_argument("--out", type=Path, default=DEFAULT_HUMAN_GATED_EXEC)

    loop_state = sub.add_parser("loop-state", help="Write machine-readable agent-loop state JSON.")
    loop_state.add_argument("--task")
    loop_state.add_argument("--batch", type=Path)
    loop_state.add_argument("--review-followups", type=Path)
    loop_state.add_argument("--changed-files", type=Path)
    loop_state.add_argument("--from-git", action="store_true")
    loop_state.add_argument("--pr")
    loop_state.add_argument("--out", type=Path, default=DEFAULT_LOOP_STATE)

    sub.add_parser("map", help="Print the agent-loop automation map and human gates.")

    sub.add_parser("next", help="Recommend the next ready/backlog queue task.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "render-prompt":
            text = render_prompt(args.task, role=args.role, plan_path=args.plan)
            _write_or_stdout(text, args.out)
            return 0
        if args.command == "handoff-check":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            report = check_handoff(args.task, plan_path=args.plan, changed_files=files)
            rendered = render_handoff_report(report)
            stream = sys.stdout if report.ok else sys.stderr
            stream.write(rendered)
            return 0 if report.ok else 1
        if args.command == "review-prompt":
            changed_files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            text = render_review_prompt(
                args.task,
                pr=args.pr,
                branch=args.branch,
                changed_files=changed_files or None,
            )
            _write_or_stdout(text, args.out)
            return 0
        if args.command == "classify-surface":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            sys.stdout.write(render_surface_report(classify_changed_files(files)))
            return 0
        if args.command == "suggest-validation":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            sys.stdout.write(render_validation_suggestions(suggest_validation_commands(files)))
            return 0
        if args.command == "validate":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            rc, runs = run_validation_commands(files, keep_going=args.keep_going)
            if args.record_history:
                append_validation_history(runs, changed_files=files, history=args.history, repo_root=ROOT_DIR)
            sys.stdout.write(render_validation_run_report(runs))
            return rc
        if args.command == "status":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            sys.stdout.write(render_status(task_id=args.task, changed_files=files))
            return 0
        if args.command == "preflight":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            rc, rendered = render_preflight(
                task_id=args.task,
                changed_files=files,
                write_prompts=args.write_prompts,
            )
            stream = sys.stdout if rc == 0 else sys.stderr
            stream.write(rendered)
            return rc
        if args.command == "pr-scan":
            out = scan_pr_state(
                out=args.out,
                state=args.state,
                limit=args.limit,
                include_body=args.include_body,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "next-from-prs":
            out_md, tasks_dir = run_next_from_prs(
                pr_json=args.pr_json,
                out_md=args.out_md,
                tasks_dir=args.tasks_dir,
                readiness_summaries=args.readiness_summary,
                readiness_reports=args.readiness_report,
                real100_dir=args.real100_dir,
                page_metadata_index_dir=args.page_metadata_index_dir,
            )
            task_count = len(list(tasks_dir.glob("*.md"))) if tasks_dir.is_dir() else 0
            sys.stdout.write(
                f"[OK] wrote {_repo_path(out_md, ROOT_DIR)} and {task_count} task brief(s) under "
                f"{_repo_path(tasks_dir, ROOT_DIR)}\n"
            )
            return 0
        if args.command == "draft-task":
            draft = draft_task_from_brief(
                task_brief=args.task_brief,
                task_id=args.task_id,
                out_queue=args.out_queue,
                out_plan=args.out_plan,
            )
            sys.stdout.write(
                f"[OK] wrote {_repo_path(draft.queue_path, ROOT_DIR)} and "
                f"{_repo_path(draft.plan_path, ROOT_DIR)}\n"
            )
            return 0
        if args.command == "draft-next":
            pr_state, tasks_dir, draft = draft_next_from_prs(
                task_id=args.task_id,
                state=args.state,
                limit=args.limit,
                include_body=args.include_body,
            )
            sys.stdout.write(
                f"[OK] wrote {_repo_path(pr_state, ROOT_DIR)}, "
                f"{_repo_path(tasks_dir, ROOT_DIR)}, "
                f"{_repo_path(draft.queue_path, ROOT_DIR)}, and "
                f"{_repo_path(draft.plan_path, ROOT_DIR)}\n"
            )
            return 0
        if args.command == "batch-plan":
            out, json_out, _ = write_batch_plan(
                tasks_dir=args.tasks_dir,
                out=args.out,
                json_out=None if args.no_json else args.json_out,
                max_items=args.max_items,
            )
            if json_out is None:
                sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            else:
                sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)} and {_repo_path(json_out, ROOT_DIR)}\n")
            return 0
        if args.command == "review-followup":
            out, tasks_dir, count, _ = write_review_followups(
                review=args.review,
                out=args.out,
                tasks_dir=args.tasks_dir,
            )
            sys.stdout.write(
                f"[OK] wrote {_repo_path(out, ROOT_DIR)} and {count} follow-up brief(s) under "
                f"{_repo_path(tasks_dir, ROOT_DIR)}\n"
            )
            return 0
        if args.command == "decision-brief":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=None,
                repo_root=ROOT_DIR,
            )
            out, _ = write_decision_brief(
                task_id=args.task,
                batch=args.batch,
                review_followups=args.review_followups,
                gate=args.gate,
                changed_files=files,
                pr=args.pr,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "promote-draft":
            out, _ = write_promote_draft(
                queue_draft=args.queue_draft,
                plan_draft=args.plan_draft,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "gate-status":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=None,
                repo_root=ROOT_DIR,
            )
            out, rendered = write_gate_status(
                task_id=args.task,
                batch=args.batch,
                review_followups=args.review_followups,
                changed_files=files,
                pr=args.pr,
                out=args.out,
            )
            if out is None:
                sys.stdout.write(rendered)
            else:
                sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "claim-audit":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            out, rc, _ = write_claim_audit(
                text_path=args.text,
                changed_files=files,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return rc
        if args.command == "privacy-audit-output":
            out, rc, _ = write_privacy_audit_output(path=args.path, out=args.out)
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return rc
        if args.command == "auto-pass-check":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=None,
                repo_root=ROOT_DIR,
            )
            out, report, rendered = write_auto_pass_check(
                task_id=args.task,
                changed_files=files,
                claim_text=args.claim_text,
                run_validation=args.run_validation,
                strict=args.strict,
                profile=args.profile,
                out=args.out,
            )
            if out is None:
                sys.stdout.write(rendered)
            else:
                sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0 if report.ok else 1
        if args.command == "dashboard":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=None,
                repo_root=ROOT_DIR,
            )
            out, _ = write_dashboard(
                task_id=args.task,
                batch=args.batch,
                review_followups=args.review_followups,
                changed_files=files,
                pr=args.pr,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "mcp-config":
            out, _ = write_mcp_client_config(out=args.out)
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "review-ingest":
            out, followup_out, tasks_dir, count, _ = write_review_ingest(
                reviews=args.review,
                pr=args.pr,
                out=args.out,
                followup_out=args.followup_out,
                tasks_dir=args.tasks_dir,
            )
            sys.stdout.write(
                f"[OK] wrote {_repo_path(out, ROOT_DIR)}, {_repo_path(followup_out, ROOT_DIR)}, "
                f"and {count} follow-up brief(s) under {_repo_path(tasks_dir, ROOT_DIR)}\n"
            )
            return 0
        if args.command == "pr-health":
            out, _ = write_pr_health(pr_json=args.pr_json, out=args.out)
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "safe-fix":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=None,
                repo_root=ROOT_DIR,
            )
            out, _, _ = write_safe_fix(
                changed_files=files,
                apply=args.apply,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "approval-packet":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            out, _ = write_approval_packet(
                task_id=args.task,
                changed_files=files,
                pr=args.pr,
                claim_text=args.claim_text,
                run_validation=args.run_validation,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "propose-queue-plan":
            out, _ = write_propose_queue_plan(
                task_brief=args.task_brief,
                task_id=args.task_id,
                queue_draft=args.queue_draft,
                plan_draft=args.plan_draft,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "pr-body":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            out, _ = write_pr_body(
                task_id=args.task,
                changed_files=files,
                branch=args.branch,
                issue=args.issue,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "review-plan":
            out, _ = write_review_plan(reviews=args.review, pr=args.pr, out=args.out)
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "stale-reports":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            out, _ = write_stale_reports(
                changed_files=files,
                max_age_days=args.max_age_days,
                apply=args.apply,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "context-pack":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            out, _ = write_context_pack(task_id=args.task, changed_files=files, pr=args.pr, profile=args.profile, out=args.out)
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "architecture-brief":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            out, _ = write_architecture_brief(changed_files=files, out=args.out)
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "ship-simulate":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            out, _ = write_ship_simulation(
                task_id=args.task,
                changed_files=files,
                pr=args.pr,
                branch=args.branch,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "auto-ship-plan":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            out, plan, _ = write_auto_ship_plan(
                task_id=args.task,
                changed_files=files,
                pr=args.pr,
                branch=args.branch,
                ttl=args.ttl,
                real_eval=args.real_eval,
                draft=args.draft,
                dry_run=args.dry_run,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0 if plan.decision != "blocked" else 1
        if args.command == "auto-ship-prepare":
            out, report, _ = write_auto_ship_prepare(
                issue=args.issue,
                target_branch=args.target_branch,
                branch_type=args.branch_type,
                slug=args.slug,
                create_branch=args.create_branch,
                confirm_human_approved=args.confirm_human_approved,
                ttl=args.ttl,
                real_eval=args.real_eval,
                draft=not args.ready,
                dry_run=args.dry_run,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0 if report.result in {"ready-for-ship-arm", "branch-created"} else 1
        if args.command == "gate-brief":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            out, _ = write_gate_brief(
                gate=args.gate,
                task_id=args.task,
                changed_files=files,
                pr=args.pr,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "manifest":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            out, _ = write_manifest(
                changed_files=files,
                command=args.manifest_command,
                outputs=args.output,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "pr-body-check":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            out, rc, _ = write_pr_body_check(
                body=args.body,
                changed_files=files,
                branch=args.branch,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return rc
        if args.command == "ci-ingest":
            out, tasks_dir, count, _ = write_ci_ingest(
                logs=args.log,
                pr=args.pr,
                out=args.out,
                tasks_dir=args.tasks_dir,
            )
            sys.stdout.write(
                f"[OK] wrote {_repo_path(out, ROOT_DIR)} and {count} CI follow-up brief(s) under "
                f"{_repo_path(tasks_dir, ROOT_DIR)}\n"
            )
            return 0
        if args.command == "stacked-risk":
            out, _ = write_stacked_risk(branch=args.branch, pr_json=args.pr_json, out=args.out)
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "patch-proposal":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            out, _ = write_patch_proposal(
                changed_files=files,
                review_plan=args.review_plan,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "adr-reserve":
            out, draft_out, _ = write_adr_reservation(
                title=args.title,
                out=args.out,
                draft_out=args.draft_out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)} and {_repo_path(draft_out, ROOT_DIR)}\n")
            return 0
        if args.command == "dashboard-html":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            out, _ = write_dashboard_html(task_id=args.task, changed_files=files, pr=args.pr, out=args.out)
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "ship-command-pack":
            out, _ = write_ship_command_pack(pr=args.pr, branch=args.branch, out=args.out)
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "apply-queue-plan":
            if not args.confirm_human_approved:
                raise ValueError("apply-queue-plan requires --confirm-human-approved")
            out, _ = write_apply_queue_plan(
                confirm_human_approved=args.confirm_human_approved,
                queue_draft=args.queue_draft,
                plan_draft=args.plan_draft,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "review-threads":
            out, _ = write_review_threads(
                threads_json=args.threads_json,
                pr=args.pr,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "ci-summary":
            out, _ = write_ci_summary(logs=args.log, pr=args.pr, out=args.out)
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "readiness-score":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            out, report, _ = write_readiness_score(
                task_id=args.task,
                changed_files=files,
                pr=args.pr,
                body=args.body,
                branch=args.branch,
                claim_text=args.claim_text,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0 if report.decision != "blocked" else 1
        if args.command == "artifact-freshness":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            out, _ = write_stale_reports(
                changed_files=files,
                max_age_days=args.max_age_days,
                apply=False,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "review-patch-plan":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            review_out, _ = write_review_plan(reviews=args.review, pr=args.pr, out=args.review_out)
            patch_out, _ = write_patch_proposal(
                changed_files=files,
                review_plan=review_out,
                out=args.patch_out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(review_out, ROOT_DIR)} and {_repo_path(patch_out, ROOT_DIR)}\n")
            return 0
        if args.command == "queue-plan-sync":
            out, _ = write_propose_queue_plan(
                task_brief=args.task_brief,
                task_id=args.task_id,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "dependency-graph":
            out, _ = write_dependency_graph(branch=args.branch, pr_json=args.pr_json, out=args.out)
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "branch-issue-hygiene":
            out, rc, _ = write_branch_issue_hygiene(
                branch=args.branch,
                body=args.body,
                task_id=args.task,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return rc
        if args.command == "integration-pack":
            out, _ = write_integration_pack(out=args.out)
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "scheduled-status":
            out, _ = write_schedule_config(out=args.out)
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "validation-history":
            out, _ = write_validation_history_report(
                history=args.history,
                limit=args.limit,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "privacy-regression":
            out, rc, _ = write_privacy_regression(out=args.out)
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return rc
        if args.command == "claim-policy":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            out, rc, _ = write_claim_policy(
                changed_files=files,
                text=args.text,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return rc
        if args.command == "architecture-decision":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=args.pr,
                repo_root=ROOT_DIR,
            )
            out, _ = write_architecture_decision(changed_files=files, out=args.out)
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "workset-recommend":
            out, _ = write_workset_recommendation(
                batch=args.batch,
                tasks_dir=args.tasks_dir,
                max_items=args.max_items,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "automation-coverage":
            out, _ = write_automation_coverage(out=args.out)
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "human-gated-exec":
            out, plan, _ = write_human_gated_exec(
                action=args.action,
                confirm_human_approved=args.confirm_human_approved,
                dry_run=args.dry_run,
                branch=args.branch,
                pr=args.pr,
                body=args.body,
                base=args.base,
                title=args.title,
                draft=not args.ready,
                confirm_review_gate_passed=args.confirm_review_gate_passed,
                confirm_dependents_reviewed=args.confirm_dependents_reviewed,
                confirm_force_with_lease=args.confirm_force_with_lease,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            if plan.blockers:
                return 1
            return plan.returncode if plan.executed and plan.returncode is not None else 0
        if args.command == "loop-state":
            files = _read_changed_files(
                args.changed_files,
                from_git=args.from_git,
                pr=None,
                repo_root=ROOT_DIR,
            )
            out, _ = write_loop_state(
                task_id=args.task,
                batch=args.batch,
                review_followups=args.review_followups,
                changed_files=files,
                pr=args.pr,
                out=args.out,
            )
            sys.stdout.write(f"[OK] wrote {_repo_path(out, ROOT_DIR)}\n")
            return 0
        if args.command == "map":
            sys.stdout.write(render_loop_map())
            return 0
        if args.command == "next":
            sys.stdout.write(recommend_next_task())
            return 0
    except ValueError as exc:
        sys.stderr.write(f"agent-loop: {exc}\n")
        return 2
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
