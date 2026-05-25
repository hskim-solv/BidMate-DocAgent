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
    "failed_experiment": 0,
    "close_superseded": 1,
    "blocked": 2,
    "needs_private_delta": 3,
    "ready_for_review": 4,
    "next_experiment_candidate": 5,
}
FAILED_CHECK_CONCLUSIONS = {
    "ACTION_REQUIRED",
    "CANCELLED",
    "FAILURE",
    "STARTUP_FAILURE",
    "TIMED_OUT",
}
BLOCKING_MERGE_STATES = {"BLOCKED", "DIRTY", "UNKNOWN", "UNSTABLE"}
REQUIRED_PR_FIELDS = (
    "number",
    "title",
    "headRefName",
    "baseRefName",
    "isDraft",
    "reviewDecision",
    "mergeStateStatus",
    "statusCheckRollup",
)
PRIVATE_DELTA_RE = re.compile(r"(#1448|\b1448\b|private[-_\s]+delta)", re.IGNORECASE)
LOAD_BEARING_RE = re.compile(r"(load[-_\s]+bearing|\b5b\b|real[-_\s]+data\s+delta)", re.IGNORECASE)
NEGATIVE_EXPERIMENT_RE = re.compile(
    r"(NO-GO|not\s+claim[-\s]+ready|negative\s+delta|failed\s+experiment|"
    r"\bregressed\b|materially\s+regress)",
    re.IGNORECASE,
)
STALE_SUPERSEDED_RE = re.compile(
    r"(stale|superseded|obsolete|replaced\s+by|closed\s+by|do\s+not\s+merge|"
    r"separate\s+smoke\s+eval\s+from\s+naive\s+rag\s+benchmark)",
    re.IGNORECASE,
)
MAPPING_DOC_CANDIDATES = (
    "docs/audits/retrieval-miss-inspection.md",
    "docs/audits/variance-source-inspection.md",
    "docs/adr/0075-normalized-failure-taxonomy.md",
)
REAL100_AGGREGATE_FILES = (
    "failure_distribution.aggregate.json",
    "failure_slices.aggregate.json",
    "variance_measurement/aggregate.json",
    "multi_chunk_evidence_failures.aggregate.json",
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


def _nested_int(payload: Mapping[str, Any], path: Sequence[str]) -> int | None:
    value: Any = payload
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nested_float(payload: Mapping[str, Any], path: Sequence[str]) -> float | None:
    value: Any = payload
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return _as_float(value)


def _retrieval_miss_mapping_fix_available(repo_root: Path = ROOT_DIR) -> bool:
    """Return whether the retrieval_miss mapping audit is already covered.

    The planner should not keep recommending a mapping audit when the delta
    renderer distinguishes missing values from numeric zero and the docs pin
    the retrieval_miss source/comparability contract.
    """
    try:
        delta_text = (repo_root / "scripts" / "run_real_eval_delta.py").read_text(
            encoding="utf-8"
        )
    except OSError:
        return False
    has_delta_handling = all(
        token in delta_text
        for token in (
            "SAFE_FAILURE_CATEGORY_KEYS",
            '"retrieval_miss"',
            "failure_category_counts",
        )
    )
    try:
        helper_text = (repo_root / "scripts" / "_eval_delta.py").read_text(
            encoding="utf-8"
        )
    except OSError:
        helper_text = ""
    has_missing_vs_zero = "if value is None" in helper_text and 'return "—"' in helper_text
    doc_text_parts: list[str] = []
    for rel in MAPPING_DOC_CANDIDATES:
        try:
            doc_text_parts.append((repo_root / rel).read_text(encoding="utf-8"))
        except OSError:
            continue
    doc_text = "\n".join(doc_text_parts)
    has_source_docs = all(
        token in doc_text
        for token in (
            "retrieval_miss",
            "failure_distribution.aggregate.json",
            "failure_slices.aggregate.json",
        )
    )
    has_comparability_docs = "cross-HEAD" in doc_text or "정본 baseline" in doc_text
    return has_delta_handling and has_missing_vs_zero and has_source_docs and has_comparability_docs


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
        missing_fields = [field for field in REQUIRED_PR_FIELDS if field not in pr]
        review = str(pr.get("reviewDecision") or "").upper()
        merge_state = str(pr.get("mergeStateStatus") or "").upper()
        failing = _failing_checks(pr)
        draft = bool(pr.get("isDraft"))
        text = _pr_text(pr)
        blocked_reasons: list[str] = []
        if missing_fields:
            blocked_reasons.append("missing required PR JSON fields")
        if review == "CHANGES_REQUESTED":
            blocked_reasons.append("review changes requested")
        if merge_state in BLOCKING_MERGE_STATES:
            blocked_reasons.append(f"merge state is {merge_state}")
        if failing:
            blocked_reasons.append("failing checks: " + ", ".join(failing[:3]))

        if NEGATIVE_EXPERIMENT_RE.search(text):
            not_ready_reason = "PR reports NO-GO/not claim-ready failed measurement"
            if merge_state:
                not_ready_reason += f"; not merge-ready (merge state is {merge_state})"
            items.append(
                WorkItem(
                    classification="failed_experiment",
                    title=f"Do not merge {source}: {title}",
                    reason=not_ready_reason,
                    source=source,
                    slug="failed-measurement-pr",
                    goal="Convert the failed measurement into a documented no-go or a narrower follow-up task.",
                    expected_evidence="The PR remains draft or explicitly documents NO-GO aggregate evidence without claiming improvement.",
                    verification=f"gh pr view {number} --json isDraft,reviewDecision,mergeStateStatus,statusCheckRollup,body",
                )
            )
            continue

        if draft and STALE_SUPERSEDED_RE.search(text):
            items.append(
                WorkItem(
                    classification="close_superseded",
                    title=f"Close superseded {source}: {title}",
                    reason="draft PR appears stale or superseded; do not treat as an unblock candidate",
                    source=source,
                    slug="close-superseded-pr",
                    goal="Close or clearly mark the stale draft so active next-action planning is not polluted.",
                    expected_evidence="The PR is closed, or its body explicitly points to the replacement work.",
                    verification=f"gh pr view {number} --json state,isDraft,title,body,updatedAt",
                )
            )
            continue

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


def _real100_aggregate_items(
    real100_dir: Path,
    *,
    retrieval_miss_mapping_fix_done: bool = False,
) -> list[WorkItem]:
    items: list[WorkItem] = []
    payloads: dict[str, Mapping[str, Any]] = {}
    for rel in REAL100_AGGREGATE_FILES:
        path = real100_dir / rel
        try:
            payload = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, Mapping):
            payloads[rel] = payload

    distribution = payloads.get("failure_distribution.aggregate.json", {})
    slices = payloads.get("failure_slices.aggregate.json", {})
    variance = payloads.get("variance_measurement/aggregate.json", {})
    distribution_miss = _nested_int(distribution, ("failure_category_counts", "retrieval_miss"))
    slices_miss = _nested_int(slices, ("categories", "retrieval_miss", "total"))
    variance_miss = _nested_int(variance, ("category_stats", "retrieval_miss", "mean"))
    observed = {
        "failure_distribution": distribution_miss,
        "failure_slices": slices_miss,
        "variance": variance_miss,
    }
    present_values = {key: value for key, value in observed.items() if value is not None}
    if len(set(present_values.values())) > 1 and not retrieval_miss_mapping_fix_done:
        reason = ", ".join(f"{key}={value}" for key, value in present_values.items())
        items.append(
            WorkItem(
                classification="next_experiment_candidate",
                title="Audit retrieval_miss aggregate mapping",
                reason=f"retrieval_miss aggregate signals differ: {reason}",
                source=_repo_display(real100_dir),
                slug="retrieval-miss-mapping-audit",
                goal="Reconcile failure taxonomy and aggregate renderers before planning retrieval behavior changes.",
                expected_evidence="A counts-only audit identifies whether the difference is taxonomy drift, run mismatch, or renderer mapping.",
                verification="python3 -m pytest -q tests/test_render_failure_distribution.py tests/test_render_failure_slices.py tests/test_measure_variance_regression.py",
            )
        )

    multi = payloads.get("multi_chunk_evidence_failures.aggregate.json", {})
    multi_cases = _nested_int(multi, ("population", "multi_chunk_gold_cases"))
    top10_failures = _nested_int(multi, ("population", "multi_chunk_top10_evidence_failures"))
    unknown_limited = _nested_int(multi, ("expected_impact", "unknown_due_to_limited_depth"))
    if multi_cases:
        items.append(
            WorkItem(
                classification="next_experiment_candidate",
                title="Use multi-chunk evidence analysis for the next retrieval follow-up",
                reason=(
                    f"multi-chunk aggregate is available: {top10_failures or 0}/"
                    f"{multi_cases} top-10 failures; "
                    f"{unknown_limited or 0} limited-depth cases"
                ),
                source=_repo_display(real100_dir / "multi_chunk_evidence_failures.aggregate.json"),
                slug="multi-chunk-follow-up",
                goal="Turn the aggregate multi-chunk evidence split into one scoped measurement follow-up.",
                expected_evidence="The follow-up chooses pool/rerank, decomposition, or section-expansion measurement using aggregate counts only.",
                verification="python3 -m pytest -q tests/test_render_multi_chunk_evidence_failures.py",
            )
        )

    return items


def _page_metadata_audit_item(index_dir: Path) -> tuple[WorkItem | None, str]:
    try:
        from scripts.page_metadata_recovery_audit import build_audit_report
    except ImportError:
        return None, "UNKNOWN"
    report = build_audit_report(index_dir)
    if not isinstance(report, Mapping):
        return None, "UNKNOWN"
    decision = report.get("decision")
    gate = "UNKNOWN"
    if isinstance(decision, Mapping):
        raw_gate = decision.get("citation_page_claim_go_no_go")
        if raw_gate in {"GO", "NO-GO"}:
            gate = str(raw_gate)
    coverage = _nested_float(report, ("index", "chunk", "any_page_metadata_coverage"))
    if gate != "NO-GO":
        return None, gate
    coverage_text = "unknown" if coverage is None else f"{coverage:.1f}"
    return (
        WorkItem(
            classification="failed_experiment",
            title="Keep page-level citation claims disabled",
            reason=f"page metadata recovery audit is NO-GO; chunk page coverage is {coverage_text}",
            source=_repo_display(index_dir),
            slug="page-level-citation-no-go",
            goal="Keep page-level citation claims disabled until page metadata is recoverable from the index.",
            expected_evidence="A fresh page metadata recovery audit reports non-zero page metadata coverage before any page-level claim.",
            verification=f"python3 scripts/page_metadata_recovery_audit.py --index-dir {_repo_display(index_dir)} --format markdown",
        ),
        gate,
    )


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
            f"- Reason: {item.reason}",
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
    real100_dir: Path | None = None,
    page_metadata_index_dir: Path | None = None,
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

    if real100_dir is not None:
        sources.append(SourceState("real100_aggregates", _repo_display(real100_dir), False))
        items.extend(
            _real100_aggregate_items(
                real100_dir,
                retrieval_miss_mapping_fix_done=_retrieval_miss_mapping_fix_available(),
            )
        )

    if page_metadata_index_dir is not None:
        sources.append(SourceState("page_metadata_index", _repo_display(page_metadata_index_dir), False))
        item, current_gate = _page_metadata_audit_item(page_metadata_index_dir)
        if current_gate == "NO-GO" or page_gate == "UNKNOWN":
            page_gate = current_gate
        if item is not None:
            items.append(item)

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
    parser.add_argument(
        "--real100-dir",
        type=Path,
        default=None,
        help="Optional directory containing public-safe reports/real100 aggregate JSON files.",
    )
    parser.add_argument(
        "--page-metadata-index-dir",
        type=Path,
        default=None,
        help="Optional index directory to audit for page metadata recovery.",
    )
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    parser.add_argument("--tasks-dir", type=Path, default=DEFAULT_TASKS_DIR)
    args = parser.parse_args(argv)

    items, sources, page_gate, private_delta_needed = build_plan(
        args.readiness_summary,
        args.readiness_report,
        args.pr_json,
        args.real100_dir,
        args.page_metadata_index_dir,
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
