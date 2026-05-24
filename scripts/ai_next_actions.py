#!/usr/bin/env python3
"""Deterministic next-action planner for the ChatGPT + Codex workflow.

This planner is intentionally rule-based. It reads public-safe aggregate
readiness artifacts plus an optional ``gh pr list --json ...`` export and
writes local-only Markdown suggestions for the next scoped Codex tasks.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts._governance import find_redacted_summary_forbidden_fields


DEFAULT_OUT_MD = ROOT_DIR / "reports" / "ai_next_actions.md"
DEFAULT_TASKS_DIR = ROOT_DIR / "reports" / "codex_tasks"

CLASSIFICATION_ORDER = {
    "blocked": 0,
    "needs_private_delta": 1,
    "ready_for_review": 2,
    "failed_experiment": 3,
    "next_experiment_candidate": 4,
}
FAILED_CHECK_CONCLUSIONS = {
    "ACTION_REQUIRED",
    "CANCELLED",
    "FAILURE",
    "STARTUP_FAILURE",
    "TIMED_OUT",
}
BLOCKING_MERGE_STATES = {"BLOCKED", "DIRTY", "UNKNOWN"}
PRIVATE_DELTA_RE = re.compile(r"(#1448|\b1448\b|private[-_\s]+delta)", re.IGNORECASE)
LOAD_BEARING_RE = re.compile(r"(load[-_\s]+bearing|\b5b\b|real[-_\s]+data\s+delta)", re.IGNORECASE)
NEGATIVE_EXPERIMENT_RE = re.compile(
    r"(NO-GO|negative\s+delta|regression|failed\s+experiment)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourceState:
    kind: str
    label: str
    unsafe: bool = False


@dataclass(frozen=True)
class WorkItem:
    classification: str
    title: str
    reason: str
    source: str
    slug: str
    goal: str
    expected_evidence: str
    verification: str

    @property
    def priority(self) -> tuple[int, str, str]:
        return (CLASSIFICATION_ORDER[self.classification], self.source, self.title)


def _repo_display(path: Path, *, repo_root: Path = ROOT_DIR) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _labels(pr: Mapping[str, Any]) -> list[str]:
    labels = pr.get("labels")
    if not isinstance(labels, list):
        return []
    out: list[str] = []
    for label in labels:
        if isinstance(label, Mapping):
            name = label.get("name")
            if name:
                out.append(str(name))
        elif label:
            out.append(str(label))
    return sorted(out)


def _pr_text(pr: Mapping[str, Any]) -> str:
    parts = [
        str(pr.get("number") or ""),
        str(pr.get("title") or ""),
        str(pr.get("headRefName") or ""),
        str(pr.get("baseRefName") or ""),
        str(pr.get("body") or ""),
        " ".join(_labels(pr)),
    ]
    return "\n".join(parts)


def _status_rollup_items(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        nodes = value.get("nodes")
        if isinstance(nodes, list):
            return [item for item in nodes if isinstance(item, Mapping)]
        return [value]
    return []


def _failing_checks(pr: Mapping[str, Any]) -> list[str]:
    failed: list[str] = []
    for item in _status_rollup_items(pr.get("statusCheckRollup")):
        conclusion = str(item.get("conclusion") or "").upper()
        status = str(item.get("status") or "").upper()
        name = str(item.get("name") or item.get("workflowName") or item.get("context") or "check")
        if conclusion in FAILED_CHECK_CONCLUSIONS:
            failed.append(name)
        elif status == "COMPLETED" and conclusion and conclusion not in {"SUCCESS", "SKIPPED", "NEUTRAL"}:
            failed.append(name)
    return sorted(set(failed))


def _readiness_page_state(summary: Mapping[str, Any]) -> tuple[str, float | None]:
    index = summary.get("index_integrity")
    if not isinstance(index, Mapping):
        return "UNKNOWN", None
    page = index.get("page_metadata")
    page_gate = "UNKNOWN"
    missing_rate: float | None = None
    if isinstance(page, Mapping):
        gate = page.get("citation_page_claim_go_no_go")
        if gate in {"GO", "NO-GO"}:
            page_gate = str(gate)
        chunk = page.get("chunk")
        if isinstance(chunk, Mapping):
            missing_rate = _as_float(chunk.get("missing_page_metadata_rate"))
    if missing_rate is None:
        missing_rate = _as_float(index.get("missing_page_metadata_rate"))
    if missing_rate == 1.0:
        page_gate = "NO-GO"
    return page_gate, missing_rate


def _summary_work_items(summary: Mapping[str, Any], source: SourceState) -> list[WorkItem]:
    items: list[WorkItem] = []
    flags = summary.get("flags_summary")
    blocker_count = _as_int(flags.get("blocker") if isinstance(flags, Mapping) else 0)
    ready = summary.get("ready_for_improvement")
    page_gate, missing_rate = _readiness_page_state(summary)

    if blocker_count > 0:
        items.append(
            WorkItem(
                classification="blocked",
                title="Fix readiness blockers",
                reason=f"readiness blocker count is {blocker_count}",
                source=source.label,
                slug="fix-blocker",
                goal="Remove readiness blockers before planning private evaluation or review work.",
                expected_evidence="A fresh readiness audit reports zero blockers.",
                verification="python3 scripts/audit_private_data_readiness.py --config eval/real_config.local.yaml",
            )
        )

    if page_gate == "NO-GO":
        rate_text = "unknown" if missing_rate is None else f"{missing_rate:.1f}"
        items.append(
            WorkItem(
                classification="failed_experiment",
                title="Rebuild page-aware index before page citation claims",
                reason=f"page citation claim is NO-GO; missing page metadata rate is {rate_text}",
                source=source.label,
                slug="page-citation-no-go",
                goal="Restore page metadata coverage before making page citation accuracy claims.",
                expected_evidence="Readiness summary reports page citation/page claim as GO.",
                verification="python3 scripts/audit_private_data_readiness.py --config eval/real_config.local.yaml",
            )
        )

    if blocker_count == 0 and ready is True:
        items.append(
            WorkItem(
                classification="ready_for_review",
                title="Prepare readiness evidence for review",
                reason="readiness summary is blocker-free and ready for improvement",
                source=source.label,
                slug="prepare-review-evidence",
                goal="Collect the public-safe aggregate evidence needed for reviewer handoff.",
                expected_evidence="Reviewer-facing summary cites only aggregate or redacted artifacts.",
                verification="python3 -m pytest -q tests/test_private_real_eval_readiness.py",
            )
        )

    if source.unsafe:
        items.append(
            WorkItem(
                classification="blocked",
                title="Sanitize planner input artifact",
                reason="sanitized input contained forbidden fields",
                source=source.label,
                slug="sanitize-input",
                goal="Regenerate the input artifact with aggregate-only fields before sharing planner output.",
                expected_evidence="The planner privacy guard reports no forbidden fields.",
                verification="python3 -m pytest -q tests/test_ai_next_actions.py",
            )
        )
    return items


def _pr_work_items(prs: Sequence[Mapping[str, Any]], readiness_blocked: bool) -> list[WorkItem]:
    items: list[WorkItem] = []
    for pr in sorted(prs, key=lambda p: _as_int(p.get("number"), 999999)):
        number = _as_int(pr.get("number"), 0)
        source = f"PR #{number}" if number else "PR"
        title = str(pr.get("title") or "(untitled)")
        review = str(pr.get("reviewDecision") or "").upper()
        merge_state = str(pr.get("mergeStateStatus") or "").upper()
        failing = _failing_checks(pr)
        draft = bool(pr.get("isDraft"))
        text = _pr_text(pr)
        blocked_reasons: list[str] = []
        if review == "CHANGES_REQUESTED":
            blocked_reasons.append("review changes requested")
        if merge_state in BLOCKING_MERGE_STATES:
            blocked_reasons.append(f"merge state is {merge_state}")
        if failing:
            blocked_reasons.append("failing checks: " + ", ".join(failing[:3]))

        if blocked_reasons:
            items.append(
                WorkItem(
                    classification="blocked",
                    title=f"Unblock {source}: {title}",
                    reason="; ".join(blocked_reasons),
                    source=source,
                    slug="unblock-pr",
                    goal="Resolve review, merge, or CI blockers before asking for review or merge.",
                    expected_evidence="The PR has no requested changes, merge blocker, or failing required check.",
                    verification=f"gh pr view {number} --json reviewDecision,mergeStateStatus,statusCheckRollup",
                )
            )
            continue

        if not readiness_blocked and (PRIVATE_DELTA_RE.search(text) or LOAD_BEARING_RE.search(text)):
            items.append(
                WorkItem(
                    classification="needs_private_delta",
                    title=f"Run private delta for {source}",
                    reason="PR context indicates pending private delta evidence",
                    source=source,
                    slug="run-private-delta",
                    goal="Produce public-safe private delta evidence before final review.",
                    expected_evidence="PR body or reviewer note includes the redacted aggregate delta result.",
                    verification="make real-eval-delta",
                )
            )
            continue

        if not draft:
            items.append(
                WorkItem(
                    classification="ready_for_review",
                    title=f"Review {source}: {title}",
                    reason="PR has no detected blocker in exported GitHub state",
                    source=source,
                    slug="review-pr",
                    goal="Perform a focused reviewer pass and identify any scoped Codex follow-up.",
                    expected_evidence="Reviewer notes are either resolved or converted into a scoped follow-up task.",
                    verification=f"gh pr view {number} --json reviewDecision,mergeStateStatus,statusCheckRollup",
                )
            )
        else:
            items.append(
                WorkItem(
                    classification="next_experiment_candidate",
                    title=f"Continue draft {source}: {title}",
                    reason="draft PR has no exported hard blocker",
                    source=source,
                    slug="continue-draft-pr",
                    goal="Narrow the draft PR to its next verifiable milestone.",
                    expected_evidence="Focused tests and updated PR notes describe the remaining gap.",
                    verification=f"gh pr view {number} --json isDraft,reviewDecision,mergeStateStatus",
                )
            )
    return items


def _read_report_items(reports: Sequence[Path]) -> list[WorkItem]:
    items: list[WorkItem] = []
    for path in sorted(reports, key=lambda p: _repo_display(p)):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if NEGATIVE_EXPERIMENT_RE.search(text):
            items.append(
                WorkItem(
                    classification="failed_experiment",
                    title="Inspect negative readiness report signal",
                    reason="readiness report text contains NO-GO or negative experiment language",
                    source=_repo_display(path),
                    slug="inspect-negative-report",
                    goal="Turn the negative report signal into a concrete fix or a documented no-go.",
                    expected_evidence="A follow-up note identifies the affected surface and next measurement.",
                    verification="python3 -m pytest -q tests/test_ai_next_actions.py",
                )
            )
    return items


def _default_item() -> WorkItem:
    return WorkItem(
        classification="next_experiment_candidate",
        title="Choose the next measurement candidate",
        reason="no readiness summary or PR blocker produced a higher-priority action",
        source="planner",
        slug="next-experiment",
        goal="Select one narrow experiment with a clear aggregate success metric.",
        expected_evidence="A short task brief names the metric, fixture, and acceptance command.",
        verification="python3 -m pytest -q tests/test_ai_next_actions.py",
    )


def _dedupe_items(items: Iterable[WorkItem]) -> list[WorkItem]:
    seen: set[tuple[str, str, str]] = set()
    out: list[WorkItem] = []
    for item in sorted(items, key=lambda i: i.priority):
        key = (item.classification, item.slug, item.source)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out or [_default_item()]


def _classification_counts(items: Sequence[WorkItem]) -> dict[str, int]:
    counts = {name: 0 for name in CLASSIFICATION_ORDER}
    for item in items:
        counts[item.classification] += 1
    return counts


def _privacy_note(sources: Sequence[SourceState]) -> str:
    if any(source.unsafe for source in sources):
        return "sanitized input contained forbidden fields"
    return "no forbidden fields detected in planner inputs"


def render_summary_markdown(
    items: Sequence[WorkItem],
    sources: Sequence[SourceState],
    *,
    page_gate: str,
    private_delta_needed: bool,
) -> str:
    top = items[0]
    counts = _classification_counts(items)
    lines = [
        "# AI Next Actions",
        "",
        "## Current State",
        "",
        f"- Top task: `{top.classification}` - {top.title}",
        f"- Page citation claim: `{page_gate}`",
        f"- Private delta needed: `{private_delta_needed}`",
        f"- Blocked: `{counts['blocked'] > 0}`",
        f"- Privacy guard: {_privacy_note(sources)}",
        "",
        "## Active Work",
        "",
        "| Classification | Count |",
        "|---|---:|",
    ]
    for name in CLASSIFICATION_ORDER:
        lines.append(f"| `{name}` | {counts[name]} |")

    lines.extend(
        [
            "",
            "## Recommended Codex Task",
            "",
            f"- Classification: `{top.classification}`",
            f"- Task: {top.title}",
            f"- Reason: {top.reason}",
            f"- Source: `{top.source}`",
            "",
            "## Follow-up Candidates",
            "",
        ]
    )
    for item in items[1:]:
        lines.append(f"- `{item.classification}` - {item.title} ({item.source})")
    if len(items) == 1:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def render_task_markdown(item: WorkItem) -> str:
    return "\n".join(
        [
            f"# {item.title}",
            "",
            f"- Classification: `{item.classification}`",
            f"- Source: `{item.source}`",
            "",
            "## Goal",
            "",
            item.goal,
            "",
            "## Constraints",
            "",
            "- Keep retrieval, verifier, prompt, chunking, and answer behavior unchanged unless a separate task explicitly scopes that work.",
            "- Use only aggregate or redacted artifacts in reviewer-facing notes.",
            "- Keep the change scoped to the cited workflow surface.",
            "",
            "## Expected Evidence",
            "",
            item.expected_evidence,
            "",
            "## Verification",
            "",
            "```bash",
            item.verification,
            "```",
            "",
        ]
    )


def _write_outputs(out_md: Path, tasks_dir: Path, items: Sequence[WorkItem], markdown: str) -> None:
    out_md.parent.mkdir(parents=True, exist_ok=True)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    for stale in tasks_dir.glob("*.md"):
        stale.unlink()
    out_md.write_text(markdown, encoding="utf-8")
    for idx, item in enumerate(items, start=1):
        task_path = tasks_dir / f"{idx:03d}-{item.slug}.md"
        task_path.write_text(render_task_markdown(item), encoding="utf-8")


def build_plan(
    readiness_summaries: Sequence[Path],
    readiness_reports: Sequence[Path],
    pr_json: Path | None,
) -> tuple[list[WorkItem], list[SourceState], str, bool]:
    sources: list[SourceState] = []
    items: list[WorkItem] = []
    page_gate = "UNKNOWN"
    readiness_blocked = False

    for path in sorted(readiness_summaries, key=lambda p: _repo_display(p)):
        payload = _load_json(path)
        if not isinstance(payload, Mapping):
            continue
        unsafe = bool(find_redacted_summary_forbidden_fields(payload))
        source = SourceState("readiness_summary", _repo_display(path), unsafe)
        sources.append(source)
        flags = payload.get("flags_summary")
        readiness_blocked = readiness_blocked or (
            _as_int(flags.get("blocker") if isinstance(flags, Mapping) else 0) > 0
        )
        current_gate, _ = _readiness_page_state(payload)
        if current_gate == "NO-GO" or page_gate == "UNKNOWN":
            page_gate = current_gate
        items.extend(_summary_work_items(payload, source))

    for path in sorted(readiness_reports, key=lambda p: _repo_display(p)):
        sources.append(SourceState("readiness_report", _repo_display(path), False))
    items.extend(_read_report_items(readiness_reports))

    if pr_json is not None:
        payload = _load_json(pr_json)
        prs = payload if isinstance(payload, list) else []
        sources.append(SourceState("pr_json", _repo_display(pr_json), False))
        items.extend(_pr_work_items([pr for pr in prs if isinstance(pr, Mapping)], readiness_blocked))

    items = _dedupe_items(items)
    private_delta_needed = any(item.classification == "needs_private_delta" for item in items)
    return items, sources, page_gate, private_delta_needed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--readiness-summary",
        action="append",
        type=Path,
        default=[],
        help="Optional aggregate readiness summary JSON. Repeatable.",
    )
    parser.add_argument(
        "--readiness-report",
        action="append",
        type=Path,
        default=[],
        help="Optional readiness report Markdown. Repeatable.",
    )
    parser.add_argument(
        "--pr-json",
        type=Path,
        default=None,
        help="Optional JSON array exported by gh pr list --json ...",
    )
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    parser.add_argument("--tasks-dir", type=Path, default=DEFAULT_TASKS_DIR)
    args = parser.parse_args(argv)

    items, sources, page_gate, private_delta_needed = build_plan(
        args.readiness_summary,
        args.readiness_report,
        args.pr_json,
    )
    markdown = render_summary_markdown(
        items,
        sources,
        page_gate=page_gate,
        private_delta_needed=private_delta_needed,
    )
    _write_outputs(args.out_md, args.tasks_dir, items, markdown)
    print(f"[OK] wrote {args.out_md} and {len(items)} task file(s) under {args.tasks_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
