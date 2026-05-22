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
ADR 0005 commit boundary. The script reads the top-level
``failure_category_counts``, ``abstention_outcomes``, and
``num_predictions`` fields, and (when present) ``case_results`` — but
only to derive *counts*. Every value emitted is an integer count or an
enum bucket name from a fail-closed whitelist; no raw ``query`` text,
``answer``, doc identifier, or other per-case string is ever copied into
the aggregate (issue #1239; #1286 raw-passthrough leak precedent).

The ``slice_counts`` block (schema_version 2, issue #1239) re-derives
the ADR 0059 per-category label via
``eval.scorers.failure_classifier.classify_failure`` (single source of
truth — no reimplementation) and counts, *per failure category*, the
distribution of: ``query_type``, ``hardcase_categories`` (multi-tag),
evidence cardinality, ``expected_doc_ids`` coverage, ``retry_count``,
query-specificity keyword hit, and the abstained/term_match/doc_match
aux booleans. These are the slices the failure-mode inspection docs
(``docs/audits/{retrieval-miss,verifier-false-negative}-inspection.md``)
hand-extracted from the gitignored ``eval_summary.json`` — surfacing
them here makes those slice tables reproducible from a committed
artifact.

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
import re
import sys
from pathlib import Path
from typing import Any

# Repo root sentinel so the script works whether invoked as
# ``python3 scripts/render_failure_distribution.py`` or imported as
# ``scripts.render_failure_distribution`` from the test suite.
ROOT = Path(__file__).resolve().parents[1]

# Ensure ``eval`` is importable when invoked as a bare script (sys.path[0]
# would otherwise be ``scripts/``, not the repo root).
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.scorers.failure_classifier import classify_failure  # noqa: E402

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

# --- ADR 0005-safe slice whitelists (issue #1239) -------------------------
#
# Every per-case dimension we slice on is mapped onto a closed enum here.
# Any case-level value NOT in the whitelist is bucketed into ``other`` /
# ``untagged`` rather than emitted as a fresh dict key — this is the
# fail-closed guard against the #1286 raw-passthrough leak (where a nested
# slice copied an unbounded private string into the committable aggregate).

# ``eval/run_eval.py::QUERY_TYPES`` (multi_doc already aliased to comparison
# by ``canonical_query_type`` before it reaches case_result.query_type).
SAFE_QUERY_TYPES: tuple[str, ...] = (
    "single_doc",
    "comparison",
    "follow_up",
    "abstention",
)

# ADR 0052 hardcase-only 5-enum (distractor_heavy / ambiguous_query /
# multi_hop / no_answer / long_context). Multi-tag: a case may carry
# several, so per-tag counts can sum past the category total.
SAFE_HARDCASE: tuple[str, ...] = (
    "multi_hop",
    "distractor_heavy",
    "long_context",
    "no_answer",
    "ambiguous_query",
)

# Generic Korean specificity markers (quantitative / explicit-criterion
# intent). These are *language patterns*, not private RFP identifiers —
# only the count of cases whose query matches crosses the ADR 0005
# boundary, never the query text itself. Mirrors the manual pattern set in
# ``docs/audits/verifier-false-negative-inspection.md`` (얼마 / 구체적으로 /
# 기준은 / 몇 % …); this regex is the reproducible single source of truth.
SPECIFICITY_REGEX = re.compile(r"얼마|구체적|기준은|몇\s*%?|\d+\s*%")

# Retry-count buckets (3+ collapsed so an unbounded integer never becomes a
# dict key).
RETRY_BUCKETS: tuple[str, ...] = ("0", "1", "2", "3plus")


def _retry_bucket(retry_count: Any) -> str:
    try:
        value = int(retry_count)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    if value == 2:
        return "2"
    return "3plus"


def _empty_slice() -> dict[str, Any]:
    """A zeroed per-category slice payload — every key is a count."""
    return {
        "n": 0,
        "query_type": {qt: 0 for qt in SAFE_QUERY_TYPES} | {"other": 0},
        "hardcase_categories": {hc: 0 for hc in SAFE_HARDCASE}
        | {"untagged": 0, "other": 0},
        "evidence_cardinality": {"empty": 0, "single_doc": 0, "multi_doc": 0},
        "expected_doc_coverage": {
            "no_expected": 0,
            "expected_in_evidence": 0,
            "expected_not_in_evidence": 0,
        },
        "retry_count": {bucket: 0 for bucket in RETRY_BUCKETS},
        "query_specificity": {"keyword_hit": 0, "no_hit": 0},
        "aux_true": {"abstained": 0, "term_match": 0, "doc_match": 0},
    }


def _accumulate_case(slice_payload: dict[str, Any], case: dict[str, Any]) -> None:
    """Fold one failed case into its category slice — counts only."""
    slice_payload["n"] += 1

    # query_type (already canonicalised in case.py); whitelist → else other.
    query_type = str(case.get("query_type") or "")
    bucket = query_type if query_type in SAFE_QUERY_TYPES else "other"
    slice_payload["query_type"][bucket] += 1

    # hardcase_categories — multi-tag. Whitelist each; untagged if empty;
    # any non-whitelisted tag collapses into ``other`` (no raw key emitted).
    tags = case.get("hardcase_categories") or []
    if not isinstance(tags, list):
        tags = [tags]
    if not tags:
        slice_payload["hardcase_categories"]["untagged"] += 1
    else:
        for tag in tags:
            key = str(tag) if str(tag) in SAFE_HARDCASE else "other"
            slice_payload["hardcase_categories"][key] += 1

    # evidence cardinality — distinct doc count of the retrieved evidence.
    evidence_doc_ids = set(case.get("evidence_doc_ids") or [])
    if not evidence_doc_ids:
        slice_payload["evidence_cardinality"]["empty"] += 1
    elif len(evidence_doc_ids) == 1:
        slice_payload["evidence_cardinality"]["single_doc"] += 1
    else:
        slice_payload["evidence_cardinality"]["multi_doc"] += 1

    # expected_doc_ids coverage — overlap with the retrieved evidence docs.
    expected_doc_ids = set(case.get("expected_doc_ids") or [])
    if not expected_doc_ids:
        slice_payload["expected_doc_coverage"]["no_expected"] += 1
    elif expected_doc_ids & evidence_doc_ids:
        slice_payload["expected_doc_coverage"]["expected_in_evidence"] += 1
    else:
        slice_payload["expected_doc_coverage"]["expected_not_in_evidence"] += 1

    # retry_count bucket.
    slice_payload["retry_count"][_retry_bucket(case.get("retry_count"))] += 1

    # query specificity — boolean keyword hit only; query text never copied.
    query_text = str(case.get("query") or "")
    if SPECIFICITY_REGEX.search(query_text):
        slice_payload["query_specificity"]["keyword_hit"] += 1
    else:
        slice_payload["query_specificity"]["no_hit"] += 1

    # aux booleans — count of True.
    for key in ("abstained", "term_match", "doc_match"):
        if bool(case.get(key)):
            slice_payload["aux_true"][key] += 1


def _build_slice_counts(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per-category slice counts derived from ``case_results``.

    Re-uses ``classify_failure`` (ADR 0059 SoT) so the per-category ``n``
    matches the top-level ``failure_category_counts``. When ``case_results``
    is absent (e.g. a pre-#1239 summary), every category is emitted with a
    zeroed slice so downstream consumers can rely on the full shape.
    """
    slices: dict[str, dict[str, Any]] = {
        category: _empty_slice() for category in SAFE_CATEGORIES
    }
    case_results = summary.get("case_results")
    if not isinstance(case_results, list):
        return slices
    for case in case_results:
        if not isinstance(case, dict):
            continue
        category = classify_failure(case)
        if category is None or category not in slices:
            continue
        _accumulate_case(slices[category], case)
    return slices


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
        # v2 (issue #1239): adds the ADR 0005-safe ``slice_counts`` block.
        "schema_version": 2,
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
        # Per-category slice counts (issue #1239) — empty when the summary
        # predates case_results emission. Counts only; see _build_slice_counts.
        "slice_counts": _build_slice_counts(summary),
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

    lines.extend(_render_slice_markdown(aggregate))

    return "\n".join(lines) + "\n"


def _render_dim_table(title: str, dim: dict[str, int]) -> list[str]:
    """One sub-table for a single slice dimension (bucket → count)."""
    out = [f"**{title}**", "", "| bucket | count |", "|---|---:|"]
    for bucket, count in dim.items():
        out.append(f"| `{bucket}` | {count} |")
    out.append("")
    return out


def _render_slice_markdown(aggregate: dict[str, Any]) -> list[str]:
    """Per-category slice tables (issue #1239). Counts only — no raw data.

    Renders only categories with at least one case, ranked by descending
    ``n``, so the markdown stays bounded on real-eval inputs.
    """
    slice_counts = aggregate.get("slice_counts") or {}
    lines: list[str] = ["## Per-category slices (issue #1239)", ""]
    lines.append(
        "Counts re-derived from `case_results` via "
        "`eval.scorers.failure_classifier.classify_failure` (ADR 0059 SoT). "
        "Every value is a count or a fail-closed enum bucket — no per-case "
        "text, query, or doc id crosses the ADR 0005 boundary."
    )
    lines.append("")

    ranked = sorted(
        (c for c in SAFE_CATEGORIES if slice_counts.get(c, {}).get("n", 0) > 0),
        key=lambda c: slice_counts[c]["n"],
        reverse=True,
    )
    if not ranked:
        lines.append(
            "_No `case_results` in the source summary — slice block is "
            "zeroed (regenerate from a post-#1239 real-eval run)._"
        )
        lines.append("")
        return lines

    for category in ranked:
        payload = slice_counts[category]
        lines.append(f"### `{category}` (n={payload['n']})")
        lines.append("")
        lines.extend(_render_dim_table("query_type", payload["query_type"]))
        lines.extend(
            _render_dim_table(
                "hardcase_categories (multi-tag)", payload["hardcase_categories"]
            )
        )
        lines.extend(
            _render_dim_table("evidence cardinality", payload["evidence_cardinality"])
        )
        lines.extend(
            _render_dim_table(
                "expected_doc coverage", payload["expected_doc_coverage"]
            )
        )
        lines.extend(_render_dim_table("retry_count", payload["retry_count"]))
        lines.extend(
            _render_dim_table("query specificity", payload["query_specificity"])
        )
        lines.extend(_render_dim_table("aux signals (True count)", payload["aux_true"]))

    return lines


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
