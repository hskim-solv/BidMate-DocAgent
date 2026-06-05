from __future__ import annotations

from eval.naive_rag.metrics import (
    contains_terms,
    summarize_case_metrics,
    summarize_latency,
    summarize_metric,
    unique_ids,
)


def test_unique_ids_strips_blanks_and_preserves_first_occurrence() -> None:
    assert unique_ids(["  c1 ", "", "c2", "c1", "  ", "c3", "c2"]) == [
        "c1",
        "c2",
        "c3",
    ]


def test_contains_terms_counts_case_insensitive_matches_and_missing_terms() -> None:
    assert contains_terms("Alpha beta ALPHA", ["alpha", "BETA", "gamma"]) == 2 / 3
    assert contains_terms("anything", ["", "  "]) is None


def test_summarize_metric_reports_numeric_count_and_missing_values() -> None:
    assert summarize_metric([1, None, 3.0, "skip"], total=5) == {
        "mean": 2.0,
        "n": 2,
        "missing": 3,
    }


def test_summarize_metric_clamps_missing_when_total_is_smaller_than_values() -> None:
    assert summarize_metric([1, 2, 3], total=1) == {
        "mean": 2.0,
        "n": 3,
        "missing": 0,
    }


def test_summarize_case_metrics_and_latency_use_declared_totals() -> None:
    cases = [{"score": 1.0}, {"score": None}, {"other": 5}]

    assert summarize_case_metrics(cases, ("score",))["score"] == {
        "mean": 1.0,
        "n": 1,
        "missing": 2,
    }
    assert summarize_latency([30, None, 10, "skip", 20]) == {
        "mean": 20.0,
        "p50": 20.0,
        "p95": 20.0,
        "n": 3,
        "missing": 2,
    }
