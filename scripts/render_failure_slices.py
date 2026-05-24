#!/usr/bin/env python3
"""Per-category failure-mode slice renderer — audit-verifiability supply.

Reads ``reports/real100/eval_summary.json`` (gitignored, local-only) and
emits a committable aggregate JSON under
``reports/real100/failure_slices.aggregate.json`` holding **counts only**
slices for each failure category present in ``case_results``.

Motivation (issue #1243): the audit ``docs/audits/retrieval-miss-inspection.md``
cites slice distributions (query_type / hardcase / evidence presence /
expected-doc cardinality / aux signals) it extracted by hand from
``eval_summary.json::case_results``. That source is gitignored
(``.gitignore`` ``reports/real100/*``), so the slices were not reproducible
on a fresh checkout. This renderer makes them a committed, regenerable
artifact the audit's Verification section can point at.

Sibling renderers (same "gitignored summary -> committed aggregate"
pattern, all aggregate-only / ADR 0005-safe):

* ``scripts/render_failure_distribution.py`` (ADR 0075 top-level
  ``failure_category_counts``; this script is its per-case decomposition)
* ``scripts/distinguishing_power.py`` (ADR 0053 gauge)
* ``scripts/eda_real100.py`` (corpus EDA)

ADR 0005 boundary: only **cardinalities/counts** cross the commit boundary.
No query text, answer text, doc_id, or chunk_id is ever written — the
renderer counts categorical buckets (``query_type`` label, ``hardcase``
tag, len of ``expected_doc_ids``, empty-vs-non-empty evidence, boolean
aux signals) and discards the underlying values.

The per-case ``failure_category`` label is the ADR 0075 classifier output
(``eval/scorers/failure_classifier.py``); this renderer is a read-only
consumer.

CLI::

    python3 scripts/render_failure_slices.py
    python3 scripts/render_failure_slices.py --summary path/to/eval_summary.json
    python3 scripts/render_failure_slices.py --out-json Y.json

Exit codes::

    0 — wrote the artifact successfully
    1 — summary file missing / case_results missing / unexpected schema
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_SUMMARY = ROOT / "reports" / "real100" / "eval_summary.json"
DEFAULT_OUT_JSON = ROOT / "reports" / "real100" / "failure_slices.aggregate.json"

from eval.scorers.failure_classifier import FAILURE_CATEGORIES  # noqa: E402

# Mirror ``eval.scorers.failure_classifier.FAILURE_CATEGORIES`` via import so a
# schema drift surfaces in one place.
SAFE_CATEGORIES: tuple[str, ...] = FAILURE_CATEGORIES

# Bucket label used for cases whose ``hardcase_categories`` list is empty.
UNTAGGED = "_untagged"


def _load_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"eval_summary.json not found: {path}")
    with path.open() as fh:
        return json.load(fh)


def _case_results(summary: dict[str, Any]) -> list[dict[str, Any]]:
    raw = summary.get("case_results")
    if not isinstance(raw, list):
        raise ValueError(
            "eval_summary.json::case_results missing or not a list — make "
            "sure the file was generated with ADR 0075 taxonomy support so each "
            "case carries a `failure_category` label."
        )
    return raw


def _count(values: list[str]) -> dict[str, int]:
    """Stable count map: insertion-ordered keys, deterministic for tests."""
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return out


def _slice_one_category(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the counts-only slice block for one category's failed cases.

    Every value extracted is a categorical bucket or a boolean tally — no
    raw text, doc_id, or chunk_id crosses the ADR 0005 boundary.
    """
    query_types: list[str] = []
    hardcase_tags: list[str] = []
    cardinalities: list[str] = []
    evidence_empty = 0
    evidence_non_empty = 0
    abstained_true = 0
    term_match_true = 0
    doc_match_false = 0
    retry_count_eq_1 = 0

    for case in cases:
        query_types.append(str(case.get("query_type")))

        tags = case.get("hardcase_categories") or []
        if tags:
            hardcase_tags.extend(str(tag) for tag in tags)
        else:
            hardcase_tags.append(UNTAGGED)

        cardinalities.append(str(len(case.get("expected_doc_ids") or [])))

        if case.get("evidence_doc_ids"):
            evidence_non_empty += 1
        else:
            evidence_empty += 1

        if bool(case.get("abstained")):
            abstained_true += 1
        if bool(case.get("term_match")):
            term_match_true += 1
        if not bool(case.get("doc_match")):
            doc_match_false += 1
        if int(case.get("retry_count") or 0) == 1:
            retry_count_eq_1 += 1

    return {
        "total": len(cases),
        "by_query_type": _count(query_types),
        "by_hardcase": _count(hardcase_tags),
        "by_expected_cardinality": _count(cardinalities),
        "by_evidence_presence": {
            "empty": evidence_empty,
            "non_empty": evidence_non_empty,
        },
        "aux": {
            "abstained_true": abstained_true,
            "term_match_true": term_match_true,
            "doc_match_false": doc_match_false,
            "retry_count_eq_1": retry_count_eq_1,
        },
    }


def build_aggregate(summary: dict[str, Any]) -> dict[str, Any]:
    """Construct the committable counts-only slice aggregate."""
    case_results = _case_results(summary)
    by_category: dict[str, list[dict[str, Any]]] = {c: [] for c in SAFE_CATEGORIES}
    for case in case_results:
        category = case.get("failure_category")
        if category in by_category:
            by_category[category].append(case)

    categories = {
        category: _slice_one_category(cases)
        for category, cases in by_category.items()
        if cases
    }
    return {
        "schema_version": 2,
        "source": "reports/real100/eval_summary.json",
        "num_predictions": int(summary.get("num_predictions") or 0),
        "categories": categories,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render per-category failure-mode slice aggregate.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_SUMMARY,
        help=f"eval_summary.json path (default: {DEFAULT_SUMMARY})",
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
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(aggregate, indent=2, sort_keys=True) + "\n")
    print(f"[OK] Wrote {args.out_json}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
