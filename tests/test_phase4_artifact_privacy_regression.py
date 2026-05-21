"""Regression guard for the Phase 4 eval-artifact privacy gate.

``scripts/_governance.py --check-phase4-privacy`` enforces that committable
Phase 4 retrieval-eval artifacts (``reports/retrieval/phase4*/*.json``) carry
only the ADR 0005 / ADR 0065 boundary fields (qid + categories + metric
values), never raw query text or per-case agency/project labels. Two merged
PRs leaked this data — #1108 (coverage.json ``sample_queries`` = raw query
text) and #1123 (raw_results.json ``gold_*`` / ``extracted_*`` labels). These
artifacts live OUTSIDE the pre-commit ``^reports/real[^/]*/`` path block, so a
content scan is the only thing that catches the leak. This test fails if any
tracked artifact regresses.
"""
from __future__ import annotations

from pathlib import Path

from scripts._governance import (
    PHASE4_PRIVATE_KEYS,
    find_private_keys,
    scan_phase4_artifacts_for_private_fields,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_forbidden_set_covers_both_leak_shapes() -> None:
    # Raw query text (coverage.json) AND per-case labels (raw_results.json)
    # must both be forbidden.
    for key in (
        "query",
        "sample_queries",
        "gold_agency",
        "gold_project",
        "extracted_agency",
        "extracted_project",
    ):
        assert key in PHASE4_PRIVATE_KEYS


def test_find_private_keys_flags_nested_occurrences() -> None:
    payload = {
        "config": {"index_dir": "data/index/real100_kordoc"},
        "stats": {"buckets": {"b1": {"n": 3, "sample_queries": ["q1", "q2"]}}},
        "no_metadata": {
            "per_case": [
                {"qid": "a", "gold_agency": "기관", "extracted_project": "사업"},
                {"qid": "b", "gold_agency": "기관2"},
            ]
        },
    }
    found = find_private_keys(payload)
    assert found["sample_queries"] == 1
    assert found["gold_agency"] == 2
    assert found["extracted_project"] == 1


def test_find_private_keys_ignores_safe_siblings() -> None:
    # Boolean / enum siblings must NOT trip the exact-key match — note
    # ``query_type`` and ``query_type_overall`` both contain the substring
    # "query" yet are legitimate aggregate fields.
    safe = {
        "per_case": [
            {
                "qid": "a",
                "query_type": "single_doc",
                "categories": ["multi_hop"],
                "has_gold_agency": True,
                "has_extracted_project": False,
                "agency_match": True,
                "project_match": False,
                "chunk_recall@10": 0.5,
                "mrr": 0.25,
            },
        ],
        "query_type_overall": {"single_doc": 10},
    }
    assert find_private_keys(safe) == {}


def test_tracked_phase4_artifacts_are_clean() -> None:
    # The real regression guard: no committed Phase 4 artifact may carry a
    # forbidden key. This assertion fails on the pre-fix tree (#1108 / #1123).
    violations = scan_phase4_artifacts_for_private_fields(str(REPO_ROOT))
    assert violations == [], "Phase 4 artifacts leak private fields: " + "; ".join(
        f"{rel}: {sorted(found)}" for rel, found in violations
    )
