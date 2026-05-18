#!/usr/bin/env python3
"""Phase 5 audit item 2 supply — failure-mode distribution dashboard.

Reads ``reports/real100/eval_summary.json`` (gitignored, local-only) and
emits a committable markdown + aggregate JSON pair under
``reports/real100/failure_distribution.{md,aggregate.json}``.

The data this renderer surfaces was introduced by ADR 0059 (PR #1001) —
top-level ``failure_category_counts: dict[str, int]`` with a fail-closed
7-key taxonomy (retrieval_miss / planner_under_decomposition /
verifier_false_negative / verifier_false_positive /
generator_hallucination / context_dilution / unknown). The classifier
is in ``eval/scorers/failure_classifier.py``; this renderer is a
read-only consumer.

Sibling renderers (same pattern):

* ``scripts/distinguishing_power.py`` (ADR 0053 §Consequences gauge)
* ``scripts/eda_real100.py`` (corpus EDA)

Both outputs are aggregate-only — no per-case data ever crosses the
ADR 0005 commit boundary; the script reads only the top-level
``failure_category_counts``, ``abstention_outcomes``, and
``num_predictions`` fields.

CLI::

    python3 scripts/render_failure_distribution.py
    python3 scripts/render_failure_distribution.py --summary path/to/eval_summary.json
    python3 scripts/render_failure_distribution.py --out-md X.md --out-json Y.json

Exit codes::

    0 — wrote both artifacts successfully
    1 — summary file missing / failure_category_counts missing / unexpected schema
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Repo root sentinel so the script works whether invoked as
# ``python3 scripts/render_failure_distribution.py`` or imported as
# ``scripts.render_failure_distribution`` from the test suite.
ROOT = Path(__file__).resolve().parents[1]

DEFAULT_SUMMARY = ROOT / "reports" / "real100" / "eval_summary.json"
DEFAULT_OUT_MD = ROOT / "reports" / "real100" / "failure_distribution.md"
DEFAULT_OUT_JSON = (
    ROOT / "reports" / "real100" / "failure_distribution.aggregate.json"
)

# Fail-closed 7-key taxonomy — mirror
# ``eval.scorers.failure_classifier.FAILURE_CATEGORIES``. Any other key
# in ``failure_category_counts`` is ignored (defense against schema drift).
SAFE_CATEGORIES: tuple[str, ...] = (
    "retrieval_miss",
    "planner_under_decomposition",
    "verifier_false_negative",
    "verifier_false_positive",
    "generator_hallucination",
    "context_dilution",
    "unknown",
)

# Abstention outcomes (PR #464, 3-bin refusal axis) — overlaid on the
# 7-category surface so reviewers can see how the new taxonomy
# decomposes the old refusal bins.
SAFE_OUTCOME_KEYS: tuple[str, ...] = (
    "correct_refusal",
    "incorrect_answer",
    "boundary_partial",
)


def _load_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"eval_summary.json not found: {path}")
    with path.open() as fh:
        return json.load(fh)


def _extract_failure_counts(summary: dict[str, Any]) -> dict[str, int]:
    """Pull ``failure_category_counts`` from the primary_run top-level.

    Fail-closed: any non-whitelisted key is silently dropped. Missing
    keys are emitted as zero so downstream consumers can always count on
    the full 7-key shape.
    """
    raw = summary.get("failure_category_counts")
    if not isinstance(raw, dict):
        raise ValueError(
            "eval_summary.json::failure_category_counts missing or not a dict "
            "— make sure the file was generated post-PR #1001 (ADR 0059)."
        )
    return {
        category: int(raw[category])
        for category in SAFE_CATEGORIES
        if isinstance(raw.get(category), (int, float))
    } | {category: 0 for category in SAFE_CATEGORIES if category not in raw}


def _extract_abstention_outcomes(summary: dict[str, Any]) -> dict[str, int]:
    """Same shape as failure_category_counts but for the refusal-axis 3-bin."""
    raw = summary.get("abstention_outcomes")
    if not isinstance(raw, dict):
        return {key: 0 for key in SAFE_OUTCOME_KEYS}
    return {
        key: int(raw[key])
        for key in SAFE_OUTCOME_KEYS
        if isinstance(raw.get(key), (int, float))
    } | {key: 0 for key in SAFE_OUTCOME_KEYS if key not in raw}


def build_aggregate(summary: dict[str, Any]) -> dict[str, Any]:
    """Construct the committable aggregate JSON payload."""
    counts = _extract_failure_counts(summary)
    outcomes = _extract_abstention_outcomes(summary)
    num_predictions = int(summary.get("num_predictions") or 0)
    total_failures = sum(counts.values())
    return {
        "schema_version": 1,
        "num_predictions": num_predictions,
        "total_failures": total_failures,
        "failure_category_counts": counts,
        # Percentage of *failed cases* attributable to each category (the
        # supply 2 dashboard cares about composition, not absolute rates).
        "failure_category_percent_of_failed": {
            category: (
                round(100.0 * counts[category] / total_failures, 2)
                if total_failures > 0
                else 0.0
            )
            for category in SAFE_CATEGORIES
        },
        # ADR 0059 first-match-wins contract — verifier_false_negative
        # must equal abstention_outcomes.incorrect_answer (Phase 5 audit
        # #992 finding #1). Emit both alongside so a future ordering bug
        # surfaces in the rendered markdown immediately.
        "abstention_outcomes": outcomes,
        "finding_1_contract": {
            "verifier_false_negative": counts["verifier_false_negative"],
            "incorrect_answer": outcomes["incorrect_answer"],
            "match": counts["verifier_false_negative"] == outcomes["incorrect_answer"],
        },
    }


def render_markdown(aggregate: dict[str, Any]) -> str:
    """Render the aggregate dict as a human-readable markdown report."""
    counts = aggregate["failure_category_counts"]
    pcts = aggregate["failure_category_percent_of_failed"]
    outcomes = aggregate["abstention_outcomes"]
    total_failures = aggregate["total_failures"]
    num_predictions = aggregate["num_predictions"]
    finding = aggregate["finding_1_contract"]

    # Sort categories by descending count for the headline table (preserves
    # rank in the rendered output — dominant categories first).
    ranked = sorted(SAFE_CATEGORIES, key=lambda c: counts[c], reverse=True)

    lines: list[str] = []
    lines.append("# Failure-mode distribution (real100, n=" f"{num_predictions})")
    lines.append("")
    lines.append(
        f"Generated by `scripts/render_failure_distribution.py` from "
        f"`reports/real100/eval_summary.json`. Aggregate-only artifact "
        f"under the ADR 0005 commit boundary (no per-case data). "
        f"Source classifier: `eval/scorers/failure_classifier.py` "
        f"(ADR 0059, PR #1001 — Phase 5 audit #992 supply 1)."
    )
    lines.append("")
    lines.append(
        f"**Total failures**: {total_failures} / {num_predictions} "
        f"({100.0 * total_failures / max(1, num_predictions):.1f}% of cases)."
    )
    lines.append("")

    # Headline table — rank order, count + % of failures.
    lines.append("## Composition (% of failed cases)")
    lines.append("")
    lines.append("| Rank | Category | Count | % of failures |")
    lines.append("|---:|---|---:|---:|")
    for rank, category in enumerate(ranked, start=1):
        lines.append(
            f"| {rank} | `{category}` | {counts[category]} | "
            f"{pcts[category]:.2f}% |"
        )
    lines.append("")

    # ADR 0059 first-match-wins contract check — verifier_false_negative
    # MUST equal abstention_outcomes.incorrect_answer.
    contract_emoji = "✓" if finding["match"] else "✗"
    lines.append(f"## ADR 0059 first-match contract: {contract_emoji}")
    lines.append("")
    lines.append(
        f"- `failure_category_counts.verifier_false_negative` = "
        f"**{finding['verifier_false_negative']}**"
    )
    lines.append(
        f"- `abstention_outcomes.incorrect_answer` = "
        f"**{finding['incorrect_answer']}**"
    )
    if finding["match"]:
        lines.append(
            "- ✓ First-match-wins ordering is intact — Phase 5 audit "
            "(#992) finding #1 pattern (`answerable=False AND not "
            "abstained`) accumulates into `verifier_false_negative` "
            "as required by ADR 0059."
        )
    else:
        lines.append(
            "- ✗ **CONTRACT VIOLATED** — `verifier_false_negative` "
            "diverges from `abstention_outcomes.incorrect_answer`. "
            "The first-match-wins ordering in "
            "`eval/scorers/failure_classifier.py::classify_failure` "
            "has likely been broken; see Phase 5 audit "
            "`docs/audits/eval-framework-phase5-audit.md` finding #1 "
            "for the contract."
        )
    lines.append("")

    # Refusal-axis decomposition — show how the 3-bin overlays the
    # 7-category surface so reviewers can correlate (esp. for the
    # unanswerable subset).
    lines.append("## Refusal-axis cross-reference (PR #464, 3-bin)")
    lines.append("")
    lines.append("| Bin | Count |")
    lines.append("|---|---:|")
    for key in SAFE_OUTCOME_KEYS:
        lines.append(f"| `{key}` | {outcomes[key]} |")
    lines.append("")

    return "\n".join(lines) + "\n"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render failure-mode distribution dashboard.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_SUMMARY,
        help=f"eval_summary.json path (default: {DEFAULT_SUMMARY})",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=DEFAULT_OUT_MD,
        help=f"Markdown output path (default: {DEFAULT_OUT_MD})",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=DEFAULT_OUT_JSON,
        help=f"Aggregate JSON output path (default: {DEFAULT_OUT_JSON})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary = _load_summary(args.summary)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        aggregate = build_aggregate(summary)
    except (ValueError, KeyError) as exc:
        print(f"Failed to build aggregate: {exc}", file=sys.stderr)
        return 1
    markdown = render_markdown(aggregate)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(markdown)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(aggregate, indent=2, sort_keys=True) + "\n")
    print(f"[OK] Wrote {args.out_md}")
    print(f"[OK] Wrote {args.out_json}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
