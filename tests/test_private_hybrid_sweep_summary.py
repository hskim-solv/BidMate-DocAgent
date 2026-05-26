from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.summarize_private_hybrid_sweep import (  # noqa: E402
    build_summary,
    main,
    render_markdown,
)


def _variant(
    name: str,
    *,
    rrf_k: int | None = None,
    dense_pool: int | None = None,
    bm25_pool: int | None = None,
    recall5: float | None = 0.50,
    recall10: float | None = 0.60,
    mrr5: float | None = 0.40,
    ndcg5: float | None = 0.45,
    citation: float | None = 0.70,
    p50: float | None = 100.0,
    p95: float | None = 200.0,
    retrieval_miss: dict | None = None,
) -> dict:
    backend = "hybrid" if name.startswith("hybrid_") else "dense"
    metrics: dict[str, object] = {
        "recall_at_5": recall5,
        "recall_at_10": recall10,
        "mrr_at_5": mrr5,
        "ndcg_at_5": ndcg5,
        "latency_ms": {"p50": p50, "p95": p95, "count": 10},
    }
    if citation is not None:
        metrics["citation_precision"] = citation
    if retrieval_miss is not None:
        metrics["retrieval_miss"] = retrieval_miss
    return {
        "name": name,
        "parameters": {
            "retrieval_backend": backend,
            "rrf_k": rrf_k,
            "dense_pool": dense_pool,
            "bm25_pool": bm25_pool,
            "top_k": 20,
        },
        "num_cases": 10,
        "metrics": metrics,
    }


def _aggregate(*variants: dict) -> dict:
    return {
        "schema_version": 1,
        "artifact_type": "private_hybrid_retrieval_sweep_aggregate",
        "privacy_boundary": "aggregate_only_no_raw_content_or_identifiers",
        "sweep": {"baseline": "full_dense_top20", "candidate": "hybrid_bm25_dense_v1"},
        "variants": [_variant("full_dense_top20"), *variants],
    }


def test_winner_selection_promotes_hybrid_variant() -> None:
    payload = _aggregate(
        _variant(
            "hybrid_bm25_dense_v1_k60_dense50_bm2550",
            rrf_k=60,
            dense_pool=50,
            bm25_pool=50,
            recall5=0.51,
            recall10=0.62,
            mrr5=0.40,
            ndcg5=0.45,
            citation=0.701,
            p50=102.0,
            p95=205.0,
        )
    )

    summary = build_summary(payload)

    assert summary["decision"]["final"] == "promote selected hybrid variant"
    assert summary["decision"]["selected_variant"] == "hybrid_bm25_dense_v1_k60_dense50_bm2550"
    assert summary["variants"][0]["primary_classification"] == "winner_found"


def test_recall_only_gain_with_regressions_keeps_dense_baseline() -> None:
    payload = _aggregate(
        _variant(
            "hybrid_bm25_dense_v1_k60_dense50_bm2550",
            rrf_k=60,
            dense_pool=50,
            bm25_pool=50,
            recall5=0.50,
            recall10=0.62,
            mrr5=0.35,
            ndcg5=0.40,
            citation=0.60,
            p50=120.0,
            p95=230.0,
        )
    )

    summary = build_summary(payload)
    row = summary["variants"][0]

    assert summary["decision"]["final"] == "keep dense baseline and abandon hybrid for now"
    assert row["primary_classification"] == "recall_only_gain"
    assert row["classifications"] == [
        "recall_only_gain",
        "ranking_regression",
        "citation_regression",
        "latency_regression",
    ]


def test_guardrail_citation_delta_is_inverted_for_selected_no_winner() -> None:
    baseline = _variant("full_dense_top20", citation=None)
    baseline["metrics"]["citation_chunk_guardrail"] = {
        "citation_or_page_metadata_issue": {"count": 1, "rate": 0.10, "denominator": 10}
    }
    better_guardrail = _variant(
        "hybrid_bm25_dense_v1_k20_dense20_bm2520",
        rrf_k=20,
        dense_pool=20,
        bm25_pool=20,
        citation=None,
        recall10=0.62,
        mrr5=0.35,
        ndcg5=0.40,
        p50=120.0,
    )
    better_guardrail["metrics"]["citation_chunk_guardrail"] = {
        "citation_or_page_metadata_issue": {"count": 0, "rate": 0.00, "denominator": 10}
    }
    worse_guardrail = _variant(
        "hybrid_bm25_dense_v1_k20_dense20_bm2550",
        rrf_k=20,
        dense_pool=20,
        bm25_pool=50,
        citation=None,
        recall10=0.62,
        mrr5=0.35,
        ndcg5=0.40,
        p50=120.0,
    )
    worse_guardrail["metrics"]["citation_chunk_guardrail"] = {
        "citation_or_page_metadata_issue": {"count": 2, "rate": 0.20, "denominator": 10}
    }
    payload = {
        "schema_version": 1,
        "artifact_type": "private_hybrid_retrieval_sweep_aggregate",
        "privacy_boundary": "aggregate_only_no_raw_content_or_identifiers",
        "sweep": {"baseline": "full_dense_top20", "candidate": "hybrid_bm25_dense_v1"},
        "variants": [baseline, worse_guardrail, better_guardrail],
    }

    summary = build_summary(payload)

    assert summary["decision"]["final"] == "keep dense baseline and abandon hybrid for now"
    assert summary["decision"]["selected_variant"] == "hybrid_bm25_dense_v1_k20_dense20_bm2520"
    rows = {row["name"]: row for row in summary["variants"]}
    assert rows["hybrid_bm25_dense_v1_k20_dense20_bm2520"]["deltas_vs_dense"]["citation"] == -0.10
    assert rows["hybrid_bm25_dense_v1_k20_dense20_bm2550"]["deltas_vs_dense"]["citation"] == 0.10


@pytest.mark.parametrize(
    "leaky_payload",
    [
        {"variants": [_variant("full_dense_top20"), {"name": "hybrid_bad", "query": "raw private"}]},
        {
            "variants": [
                _variant("full_dense_top20"),
                {"name": "hybrid_bad", "metrics": {"doc_id": "private-doc"}},
            ]
        },
        {
            "variants": [
                _variant("full_dense_top20"),
                {"name": "hybrid_bad", "metrics": {"filename": "private.pdf", "evidence": []}},
            ]
        },
        {
            "variants": [
                _variant("full_dense_top20"),
                {"name": "hybrid_bad", "metrics": {"safe": "/Users/example/private.pdf"}},
            ]
        },
    ],
)
def test_privacy_guard_rejects_raw_fields_and_paths(leaky_payload: dict) -> None:
    leaky_payload.setdefault("sweep", {"baseline": "full_dense_top20"})
    with pytest.raises(ValueError, match="privacy guard"):
        build_summary(leaky_payload)


def test_missing_required_metric_blocks_winner_instead_of_zero_fill() -> None:
    payload = _aggregate(
        _variant(
            "hybrid_bm25_dense_v1_k20_dense20_bm2520",
            rrf_k=20,
            dense_pool=20,
            bm25_pool=20,
            recall10=0.80,
            ndcg5=None,
        )
    )

    summary = build_summary(payload)
    row = summary["variants"][0]

    assert row["primary_classification"] == "failed_experiment"
    assert "ndcg_at_5" in row["missing_metrics"]
    assert summary["decision"]["final"] == "mark hybrid as failed experiment"


def test_retrieval_miss_explicit_zero_is_distinct_from_missing() -> None:
    payload = _aggregate(
        _variant(
            "hybrid_bm25_dense_v1_k20_dense20_bm2520",
            rrf_k=20,
            dense_pool=20,
            bm25_pool=20,
            retrieval_miss={"count": 0, "rate": 0.0, "denominator": 10},
        ),
        _variant(
            "hybrid_bm25_dense_v1_k60_dense20_bm2520",
            rrf_k=60,
            dense_pool=20,
            bm25_pool=20,
        ),
    )
    payload["variants"][0]["metrics"]["retrieval_miss"] = {
        "count": 0,
        "rate": 0.0,
        "denominator": 10,
    }

    summary = build_summary(payload)
    explicit = summary["variants"][0]
    missing = summary["variants"][1]

    assert explicit["metrics"]["retrieval_miss_count"] == 0
    assert explicit["deltas_vs_dense"]["retrieval_miss"] == 0
    assert missing["metrics"]["retrieval_miss_count"] is None
    assert missing["deltas_vs_dense"]["retrieval_miss"] is None

    md = render_markdown(summary)
    assert "| hybrid_bm25_dense_v1_k20_dense20_bm2520 | 20 | 20 | 20 |" in md
    assert "| hybrid_bm25_dense_v1_k60_dense20_bm2520 | 60 | 20 | 20 |" in md


def test_markdown_table_rendering_is_stable_and_sorted() -> None:
    payload = _aggregate(
        _variant("hybrid_bm25_dense_v1_k60_dense20_bm2520", rrf_k=60, dense_pool=20, bm25_pool=20),
        _variant("hybrid_bm25_dense_v1_k20_dense20_bm2520", rrf_k=20, dense_pool=20, bm25_pool=20),
    )

    summary = build_summary(payload)
    first = render_markdown(summary)
    second = render_markdown(summary)

    assert first == second
    table = first.split("## Hybrid Variants", 1)[1]
    assert table.index("hybrid_bm25_dense_v1_k20_dense20_bm2520") < table.index(
        "hybrid_bm25_dense_v1_k60_dense20_bm2520"
    )
    assert "| Variant | k | Dense pool | BM25 pool | dR@5 | dR@10 |" in first


def test_main_writes_summary_artifacts_from_explicit_aggregate(tmp_path: Path) -> None:
    aggregate_path = tmp_path / "aggregate.json"
    out_md = tmp_path / "summary.md"
    out_json = tmp_path / "summary.aggregate.json"
    aggregate_path.write_text(
        json.dumps(
            _aggregate(
                _variant(
                    "hybrid_bm25_dense_v1_k60_dense50_bm2550",
                    rrf_k=60,
                    dense_pool=50,
                    bm25_pool=50,
                    recall10=0.62,
                )
            )
        ),
        encoding="utf-8",
    )

    rc = main(["--aggregate", str(aggregate_path), "--out-md", str(out_md), "--out-json", str(out_json)])

    assert rc == 0
    assert out_md.exists()
    assert out_json.exists()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["artifact_type"] == "private_hybrid_sweep_decision_summary"
