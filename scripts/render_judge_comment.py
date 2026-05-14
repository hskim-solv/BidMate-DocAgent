"""Render `reports/synthetic_judge.aggregate.json` as a PR-comment markdown table.

Used by ``.github/workflows/pr-judge.yml`` (ADR 0043 — label-gated live LLM-judge
cadence).  Stdlib-only so the CI step can run before any project deps are
installed; the workflow installs deps for ``make synthetic-judge`` itself,
but rendering the comment doesn't need them.

The comment uses a stable HTML marker (``<!-- pr-judge-bot -->``) so the
workflow can upsert in place instead of stacking duplicates on every re-run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

COMMENT_MARKER = "<!-- pr-judge-bot -->"

_HEADLINE_KEYS: list[tuple[str, str]] = [
    ("n", "n"),
    ("faithfulness_mean", "faithfulness"),
    ("answer_relevance_mean", "answer_relevance"),
    ("grounded_rate", "grounded_rate"),
    ("agreement_with_verifier", "agreement_w/_verifier"),
]


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render(aggregate: dict[str, Any]) -> str:
    backend = aggregate.get("backend", "unknown")
    model = aggregate.get("model", "unknown")
    generated_at = aggregate.get("generated_at", "—")
    lines: list[str] = [
        COMMENT_MARKER,
        "## Live LLM-judge signal (ADR 0043)",
        "",
        f"- **backend**: `{backend}`",
        f"- **model**: `{model}`",
        f"- **generated_at**: `{generated_at}`",
        "",
        "### Headline aggregate",
        "",
        "| metric | value |",
        "|--------|------:|",
    ]
    for json_key, label in _HEADLINE_KEYS:
        lines.append(f"| {label} | {_fmt(aggregate.get(json_key))} |")

    status_dist = aggregate.get("status_distribution") or {}
    if status_dist:
        lines.append("")
        lines.append("### Status distribution")
        lines.append("")
        lines.append("| status | count |")
        lines.append("|--------|------:|")
        for status, count in sorted(status_dist.items()):
            lines.append(f"| {status} | {count} |")

    by_query_type = aggregate.get("by_query_type") or {}
    if isinstance(by_query_type, dict) and by_query_type:
        lines.append("")
        lines.append("### By query type")
        lines.append("")
        lines.append(
            "| query_type | n | faithfulness | answer_relevance |"
            " grounded_rate | agreement |"
        )
        lines.append("|------------|--:|------------:|----------------:|"
                     "-------------:|---------:|")
        for query_type, slice_summary in sorted(by_query_type.items()):
            if not isinstance(slice_summary, dict):
                continue
            lines.append(
                "| {qt} | {n} | {faith} | {ans} | {gr} | {agr} |".format(
                    qt=query_type,
                    n=_fmt(slice_summary.get("n")),
                    faith=_fmt(slice_summary.get("faithfulness_mean")),
                    ans=_fmt(slice_summary.get("answer_relevance_mean")),
                    gr=_fmt(slice_summary.get("grounded_rate")),
                    agr=_fmt(slice_summary.get("agreement_with_verifier")),
                )
            )

    lines.append("")
    lines.append(
        "<sub>Triggered by label `live-judge-please`. Re-attach the label "
        "after each push to refresh (ADR 0043 Goodhart guard).</sub>"
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--aggregate",
        type=Path,
        default=Path("reports/synthetic_judge.aggregate.json"),
        help="Path to the synthetic-judge aggregate JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional output path. Defaults to stdout.",
    )
    args = parser.parse_args(argv)

    if not args.aggregate.is_file():
        print(f"aggregate file not found: {args.aggregate}", file=sys.stderr)
        return 1

    aggregate = json.loads(args.aggregate.read_text(encoding="utf-8"))
    if not isinstance(aggregate, dict):
        print("aggregate JSON must be an object", file=sys.stderr)
        return 1

    rendered = render(aggregate)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
