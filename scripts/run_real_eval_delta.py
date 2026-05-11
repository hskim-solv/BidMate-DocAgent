#!/usr/bin/env python3
"""Aggregate-only delta between two real-data eval summaries.

Designed for the **private real-data surface only**. The script:

1. Reads the current run (`reports/real100/eval_summary.json` by
   default) and a committed baseline snapshot
   (`reports/real100/baseline.aggregate.json`).
2. Extracts an explicit allow-list of **aggregate-only fields** — no
   `case_results`, no `query` text, no per-case `evidence`, no
   `doc_id`. The extractor refuses to even look at forbidden keys, so
   schema drift cannot accidentally leak per-case content into the
   committable diff.
3. Renders a markdown delta table to stdout for the contributor to
   paste into the PR body (or for the optional Decision Log stub
   appender to use).

This is the structural mechanism behind ADR 0005's commit boundary
on the contributor side: aggregates are committable, anything
case-level is not.

CLI:

    python3 scripts/run_real_eval_delta.py \
        --head reports/real100/eval_summary.json \
        --base reports/real100/baseline.aggregate.json \
        [--title "Real-data delta — #NN"] \
        [--write-decision-log-stub]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Top-level aggregate keys that are safe to commit. Anything else in
# the input JSONs is ignored. Keep this list intentionally narrow —
# adding a key requires a privacy review.
SAFE_TOPLEVEL_KEYS = frozenset(
    {
        "num_predictions",
        "accuracy",
        "groundedness",
        "citation_precision",
        "citation_grounding",
        "claim_citation_alignment",
        "answer_format_compliance",
        "abstention",
        "retry",
        "latency",  # only sub-keys "p50", "p95", "mean" extracted below
        "stage_latency",  # aggregated p50/p95/mean per stage
        "retry_reason_counts",  # reason strings are non-identifying
        "pipeline",
        "primary_run",
        "prompt_profile",
        "top_k",
        # LLM-judge aggregates (ADR 0006). Only status_distribution /
        # grounded_rate / agreement_with_verifier / n cross the commit
        # boundary; per-case judge text stays in
        # reports/real100/judge.local.json.
        "judge",
    }
)

# Per-slice subkeys extracted from `by_query_type`.
SAFE_SLICE_METRICS = (
    "num_predictions",
    "accuracy",
    "groundedness",
    "abstention",
    "answer_format_compliance",
)

# Keys that must never be read or written by this script. The
# extractor asserts none of these are present in its output as a
# defense against schema drift.
FORBIDDEN_KEYS = frozenset(
    {
        "case_results",
        "query",
        "answer",
        "answer_text",
        "evidence",
        "expected_doc_ids",
        "expected_terms",
        "expected_citation_terms",
        "expected_citation_pages",
        "expected_citation_regions",
        "expected_claim_citations",
        "evidence_doc_ids",
        "metadata_selected_doc_ids",
        "doc_id",
        "chunk_id",
        "resolved_query",
    }
)

# Metric direction for the rendered delta arrow.
# (path, label, higher_is_better)
METRICS: list[tuple[str, str, bool]] = [
    ("accuracy", "accuracy", True),
    ("groundedness", "groundedness", True),
    ("citation_precision", "citation_precision", True),
    ("citation_grounding", "citation_grounding", True),
    ("claim_citation_alignment", "claim_citation_alignment", True),
    ("answer_format_compliance", "answer_format_compliance", True),
    ("abstention", "abstention (intended)", True),
    ("retry", "retry_rate", False),
    ("latency.p50", "latency_p50_ms", False),
    ("latency.p95", "latency_p95_ms", False),
]


# -----------------------------------------------------------------------------
# Extraction
# -----------------------------------------------------------------------------


def extract_aggregate(summary: dict[str, Any]) -> dict[str, Any]:
    """Return a dict containing only ADR-0005-safe aggregate fields.

    Anything outside :data:`SAFE_TOPLEVEL_KEYS` is dropped. The output
    is then re-validated against :data:`FORBIDDEN_KEYS` as a guard
    against silent schema drift; an :class:`AssertionError` is raised
    if a forbidden key somehow makes it through.
    """
    if not isinstance(summary, dict):
        raise ValueError("Eval summary must be a JSON object.")

    out: dict[str, Any] = {}
    for key in SAFE_TOPLEVEL_KEYS:
        if key not in summary:
            continue
        value = summary[key]
        if key == "latency" and isinstance(value, dict):
            out[key] = {
                sub: value.get(sub)
                for sub in ("p50", "p95", "mean")
                if value.get(sub) is not None
            }
        elif key == "stage_latency" and isinstance(value, dict):
            # value is {stage_name: {p50,p95,mean,count}}
            out[key] = {
                stage: {k: v.get(k) for k in ("p50", "p95", "mean") if v.get(k) is not None}
                for stage, v in value.items()
                if isinstance(v, dict)
            }
        elif key == "retry_reason_counts" and isinstance(value, dict):
            # Reason strings are taxonomy codes ("topic_not_grounded"), not
            # identifying. Counts are integers. Safe.
            out[key] = {str(k): int(v) for k, v in value.items()}
        else:
            out[key] = value

    by_query_type = summary.get("by_query_type")
    if isinstance(by_query_type, dict):
        slice_out: dict[str, dict[str, Any]] = {}
        for slice_name, slice_summary in by_query_type.items():
            if not isinstance(slice_summary, dict):
                continue
            slice_out[str(slice_name)] = {
                m: slice_summary.get(m)
                for m in SAFE_SLICE_METRICS
                if slice_summary.get(m) is not None
            }
        out["by_query_type"] = slice_out

    _assert_no_forbidden(out)
    return out


def _assert_no_forbidden(obj: Any, path: str = "") -> None:
    """Recursively assert that no forbidden key appears in the aggregate."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key) in FORBIDDEN_KEYS:
                raise AssertionError(
                    f"Aggregate output contains forbidden key '{key}' at '{path}'. "
                    "This indicates a schema drift in the extractor and would "
                    "violate ADR 0005's commit boundary. Refusing to emit."
                )
            _assert_no_forbidden(value, f"{path}.{key}" if path else str(key))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _assert_no_forbidden(item, f"{path}[{i}]")


# -----------------------------------------------------------------------------
# Rendering
# -----------------------------------------------------------------------------


def _get_path(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _fmt_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _fmt_delta(base: Any, head: Any, higher_is_better: bool) -> str:
    if not isinstance(base, (int, float)) or not isinstance(head, (int, float)):
        return "—"
    delta = float(head) - float(base)
    if abs(delta) < 5e-4:
        return "·"
    sign = "+" if delta > 0 else ""
    improved = (delta > 0) if higher_is_better else (delta < 0)
    flag = " ✅" if improved else " ⚠️"
    return f"{sign}{delta:.3f}{flag}"


def render_markdown(
    base: dict[str, Any],
    head: dict[str, Any],
    title: str,
) -> str:
    lines: list[str] = []
    lines.append(f"### {title}")
    lines.append("")
    lines.append(
        f"- pipeline: `{head.get('pipeline', '?')}` "
        f"(primary run: `{head.get('primary_run', '?')}`)"
    )
    lines.append(
        f"- cases: base={base.get('num_predictions', '?')} · "
        f"head={head.get('num_predictions', '?')}"
    )
    lines.append("")
    lines.append("| metric | base | head | Δ |")
    lines.append("|---|---|---|---|")
    for path, label, higher in METRICS:
        b = _get_path(base, path)
        h = _get_path(head, path)
        lines.append(
            f"| {label} | {_fmt_value(b)} | {_fmt_value(h)} | "
            f"{_fmt_delta(b, h, higher)} |"
        )

    # Slice-level abstention is the most important signal we surfaced
    # from #69 — render it explicitly so future regressions are obvious.
    base_slices = base.get("by_query_type") or {}
    head_slices = head.get("by_query_type") or {}
    slice_names = sorted(set(base_slices) | set(head_slices))
    if slice_names:
        lines.append("")
        lines.append("#### Slice abstention rate (intended-abstention preservation)")
        lines.append("")
        lines.append("| slice | base | head | Δ |")
        lines.append("|---|---|---|---|")
        for name in slice_names:
            b = (base_slices.get(name) or {}).get("abstention")
            h = (head_slices.get(name) or {}).get("abstention")
            lines.append(
                f"| {name} | {_fmt_value(b)} | {_fmt_value(h)} | "
                f"{_fmt_delta(b, h, True)} |"
            )

    base_reasons = base.get("retry_reason_counts") or {}
    head_reasons = head.get("retry_reason_counts") or {}
    if base_reasons or head_reasons:
        lines.append("")
        lines.append("#### Retry reason counts")
        lines.append("")
        lines.append("| reason | base | head |")
        lines.append("|---|---:|---:|")
        for reason in sorted(set(base_reasons) | set(head_reasons)):
            lines.append(
                f"| `{reason}` | {base_reasons.get(reason, 0)} | "
                f"{head_reasons.get(reason, 0)} |"
            )

    base_judge = base.get("judge") or {}
    head_judge = head.get("judge") or {}
    if base_judge or head_judge:
        lines.append("")
        lines.append("#### LLM-judge aggregate (ADR 0006)")
        lines.append("")
        lines.append("| metric | base | head | Δ |")
        lines.append("|---|---|---|---|")
        for key, label, higher in (
            ("grounded_rate", "judge_grounded_rate", True),
            ("agreement_with_verifier", "agreement_with_verifier", True),
        ):
            b = base_judge.get(key)
            h = head_judge.get(key)
            lines.append(
                f"| {label} | {_fmt_value(b)} | {_fmt_value(h)} | "
                f"{_fmt_delta(b, h, higher)} |"
            )
        base_dist = base_judge.get("status_distribution") or {}
        head_dist = head_judge.get("status_distribution") or {}
        statuses = sorted(set(base_dist) | set(head_dist))
        if statuses:
            lines.append("")
            lines.append("| judge_status | base count | head count |")
            lines.append("|---|---:|---:|")
            for status in statuses:
                lines.append(
                    f"| {status} | {base_dist.get(status, 0)} | "
                    f"{head_dist.get(status, 0)} |"
                )

    lines.append("")
    lines.append(
        "_Aggregate-only. Per-case data is never read or rendered by this "
        "script (ADR 0005). ✅ direction-of-improvement; ⚠️ "
        "direction-of-regression._"
    )
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Decision Log stub
# -----------------------------------------------------------------------------


_DECISION_LOG_TEMPLATE = """

### Entry: {date} — TODO short title

**Change.** TODO 1-2 sentences. Link the PR/issue.

**Surface.** Local private real-data set (`eval/real_config.local.yaml`,
N={cases} cases). Same index, same case set, same tooling for both
sides.

{table}

**Interpretation.** TODO — what worked? what regressed? what to do
next?

**Decision.** TODO — ship / revert / tighten / follow-up issue.
"""


def append_decision_log_stub(
    docs_path: Path,
    table_md: str,
    cases: int,
) -> None:
    import datetime

    if not docs_path.exists():
        raise FileNotFoundError(f"Decision log target not found: {docs_path}")
    date = datetime.date.today().isoformat()
    body = _DECISION_LOG_TEMPLATE.format(date=date, cases=cases, table=table_md)
    with docs_path.open("a", encoding="utf-8") as fh:
        fh.write(body)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--head",
        default="reports/real100/eval_summary.json",
        help="Current real-data eval_summary.json path.",
    )
    ap.add_argument(
        "--base",
        default="reports/real100/baseline.aggregate.json",
        help="Committed baseline aggregate snapshot path.",
    )
    ap.add_argument("--title", default="Real-data eval delta")
    ap.add_argument(
        "--write-decision-log-stub",
        action="store_true",
        help=(
            "Append a Decision Log entry stub (with the rendered table) to "
            "docs/private-100-doc-experiments.md so you only fill the "
            "interpretation paragraph."
        ),
    )
    ap.add_argument(
        "--decision-log-path",
        default="docs/private-100-doc-experiments.md",
        help="Target file for the Decision Log stub (default is the public doc).",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    head_path = Path(args.head)
    base_path = Path(args.base)
    if not head_path.exists():
        print(
            f"[ERROR] Head eval summary not found: {head_path}\n"
            "Run `make real-eval` first to generate it.",
            file=sys.stderr,
        )
        return 2
    if not base_path.exists():
        print(
            f"[ERROR] Baseline aggregate not found: {base_path}\n"
            "Run `make real-eval-baseline-update` once to seed it.",
            file=sys.stderr,
        )
        return 2

    head_raw = json.loads(head_path.read_text(encoding="utf-8"))
    base_raw = json.loads(base_path.read_text(encoding="utf-8"))

    head = extract_aggregate(head_raw)

    # ADR 0006: if a judge.local.json sits beside the head eval
    # summary, fold its aggregate into the head view so the delta
    # surfaces judge_grounded_rate / agreement_with_verifier when the
    # user just ran `make real-eval-with-judge`. The per-case judge
    # text is never copied into the head aggregate.
    judge_local = head_path.parent / "judge.local.json"
    if judge_local.exists():
        from collections import Counter

        judge_payload = json.loads(judge_local.read_text(encoding="utf-8"))
        cases = judge_payload.get("cases") or []
        statuses = [c.get("judge_status") for c in cases if c.get("judge_status")]
        grounded = [bool(c.get("judge_grounded")) for c in cases]
        agreements = [bool(c.get("agrees")) for c in cases if c.get("agrees") is not None]
        head["judge"] = {
            "status_distribution": dict(Counter(statuses)),
            "grounded_rate": (sum(grounded) / len(grounded)) if grounded else None,
            "agreement_with_verifier": (
                sum(agreements) / len(agreements) if agreements else None
            ),
            "n": len(cases),
        }
        # Privacy guard: assert nothing leaked.
        _assert_no_forbidden(head["judge"], "judge")

    base = extract_aggregate(base_raw) if "case_results" in base_raw else base_raw
    # If the baseline file was already in aggregate form (it should be),
    # re-running the extractor is a no-op but also re-asserts the
    # privacy invariant. Do it anyway:
    base = extract_aggregate(base)

    table = render_markdown(base, head, args.title)
    print(table)

    if args.write_decision_log_stub:
        cases = head.get("num_predictions") or "?"
        append_decision_log_stub(Path(args.decision_log_path), table, cases)
        print(
            f"\n[OK] Decision Log stub appended to {args.decision_log_path}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
