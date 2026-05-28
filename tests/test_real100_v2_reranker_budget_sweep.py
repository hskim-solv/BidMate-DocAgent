from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_real100_v2_reranker_budget_sweep import (  # noqa: E402
    VariantSpec,
    _TopNForcingReranker,
    build_aggregate,
    classify_variants,
    render_markdown,
)


def _variant(
    name: str,
    *,
    topn: int | None = None,
    recall10: float = 0.40,
    mrr5: float = 0.30,
    ndcg5: float = 0.35,
    p95: float = 100.0,
    fallback: float = 0.0,
    citation_issue: float = 0.0,
    rerank_delta: float | None = None,
) -> dict:
    return {
        "name": name,
        "parameters": {
            "retrieval_backend": "hybrid",
            "top_k": 20,
            "rrf_k": 60,
            "dense_pool": 30 if topn is not None else None,
            "bm25_pool": 30 if topn is not None else None,
            "rerank_cross_encoder": topn is not None,
            "reranker_top_n": topn,
        },
        "num_cases": 10,
        "reranker_provenance": {
            "backend": "stub" if topn is not None else "disabled",
            "model": "stub" if topn is not None else "disabled",
            "fallback": {"count": int(fallback * 10), "rate": fallback, "denominator": 10},
            "candidates_scored_mean": float(topn or 0),
            "latency_ms": {"p50": 1.0 if topn is not None else None, "p95": 2.0 if topn is not None else None, "count": 10 if topn is not None else 0},
        },
        "metrics": {
            "candidate_pool": {
                "pre_rerank_recall_at_topn": recall10,
                "post_rerank_recall_at_topn": recall10,
                "pre_rerank_mrr_at_topn": mrr5,
                "post_rerank_mrr_at_topn": mrr5,
                "pre_rerank_ndcg_at_topn": ndcg5,
                "post_rerank_ndcg_at_topn": ndcg5,
            },
            "reranker_precision": {
                "rerank_delta_mrr": rerank_delta,
                "rerank_delta_ndcg_at_10": rerank_delta,
            },
            "final_retrieval": {
                "recall_at_5": recall10 - 0.05,
                "recall_at_10": recall10,
                "mrr_at_5": mrr5,
                "ndcg_at_5": ndcg5,
            },
            "citation_guardrail": {
                "citation_or_page_metadata_issue": {"count": int(citation_issue * 10), "rate": citation_issue, "denominator": 10}
            },
            "latency_ms": {"p50": p95 / 2, "p95": p95, "count": 10},
        },
    }


def test_classifies_winner_when_precision_gain_has_no_regressions() -> None:
    variants = [
        _variant("control_no_cross_encoder_top20"),
        _variant("reranker_budget_pool30_topn20_top20", topn=20, recall10=0.405, mrr5=0.31, ndcg5=0.36, rerank_delta=0.01),
    ]

    decision = classify_variants(variants, {"overall_budget": {"hard_no_go_ceiling_ms": 200.0}})

    assert decision["overall_classification"] == "winner"
    assert decision["selected_variant"] == "reranker_budget_pool30_topn20_top20"
    assert decision["variants"][0]["classifications"] == ["winner"]


def test_classifies_recall_only_gain_with_ranking_and_latency_regressions() -> None:
    variants = [
        _variant("control_no_cross_encoder_top20"),
        _variant("reranker_budget_pool30_topn30_top20", topn=30, recall10=0.43, mrr5=0.25, ndcg5=0.34, p95=250.0, rerank_delta=-0.02),
    ]

    decision = classify_variants(variants, {"overall_budget": {"hard_no_go_ceiling_ms": 200.0}})

    assert decision["overall_classification"] == "recall_only_gain"
    assert decision["variants"][0]["classifications"] == [
        "recall_only_gain",
        "ranking_regression",
        "latency_regression",
    ]


def test_topn_wrapper_forces_requested_budget_and_records_topn_ids() -> None:
    class FakeReranker:
        def rerank(self, query: str, candidates: list[dict], *, top_n: int):
            return list(reversed(candidates[:top_n])) + candidates[top_n:], {
                "backend": "fake",
                "model": "fake",
                "top_n": top_n,
                "candidates_scored": top_n,
                "fell_back": False,
            }

    candidates = [{"chunk_id": f"c{i}"} for i in range(5)]
    wrapper = _TopNForcingReranker(FakeReranker(), 2)

    reordered, meta = wrapper.rerank("q", candidates, top_n=30)

    assert [item["chunk_id"] for item in reordered[:2]] == ["c1", "c0"]
    assert meta["requested_top_n"] == 30
    assert meta["forced_top_n"] == 2
    assert meta["pre_rerank_topn"] == ["c0", "c1"]
    assert meta["post_rerank_topn"] == ["c1", "c0"]


def test_build_aggregate_and_markdown_are_privacy_safe(tmp_path: Path) -> None:
    index = {"build": {"version": 1}, "embedding": {"backend": "hashing"}, "documents": [1], "chunks": [1, 2]}
    specs = [
        VariantSpec("control_no_cross_encoder_top20", "hybrid", 20, False, None),
        VariantSpec("reranker_budget_pool30_topn20_top20", "hybrid", 20, True, 20, 30, 30),
    ]
    config = tmp_path / "real100_v2" / "fake_config.local.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("cases: []\n", encoding="utf-8")

    aggregate = build_aggregate(
        config_path=config,
        index=index,
        specs=specs,
        variants=[_variant("control_no_cross_encoder_top20"), _variant("reranker_budget_pool30_topn20_top20", topn=20, rerank_delta=0.01)],
        latency_budget={"profile_type": "private_real100_v2_latency_cost_budget", "overall_budget": {"hard_no_go_ceiling_ms": 200.0}, "cost_budget": {"status": "not_observable"}},
        cases_requested=10,
        cases_evaluated=3,
    )
    rendered = render_markdown(aggregate)

    assert aggregate["profile_type"] == "private_real100_v2_reranker_candidate_budget"
    assert aggregate["run_scope"]["subset_run"] is True
    assert "raw questions" in rendered
    assert "/Users/" not in json.dumps(aggregate)


@pytest.mark.parametrize(
    "payload",
    [
        [{"name": "control_no_cross_encoder_top20"}, {"name": "bad", "metrics": {"doc_id": "x"}}],
        [{"name": "control_no_cross_encoder_top20"}, {"name": "bad", "metrics": {"evidence": []}}],
    ],
)
def test_privacy_guard_rejects_raw_private_keys(payload: list[dict]) -> None:
    config = REPO_ROOT / "reports" / "real100_v2" / "baseline.aggregate.json"
    index = {"build": {}, "embedding": {}, "documents": [], "chunks": []}
    with pytest.raises(ValueError, match="privacy guard|aggregate artifact failed"):
        build_aggregate(
            config_path=config,
            index=index,
            specs=[],
            variants=payload,
            latency_budget={},
            cases_requested=1,
            cases_evaluated=1,
        )
