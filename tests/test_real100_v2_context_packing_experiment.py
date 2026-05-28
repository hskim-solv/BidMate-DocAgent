from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_real100_v2_context_packing_experiment import (  # noqa: E402
    build_aggregate,
    classify_variants,
    evidence_first_selector,
    render_markdown,
)


def _evidence(chunk_id: str, *, text: str, score: float, doc_id: str = "d", section: str = "s") -> dict:
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "section": section,
        "text": text,
        "score": score,
    }


def _variant(name: str, *, accuracy: float, citation: float, p95: float) -> dict:
    return {
        "name": name,
        "variant": name,
        "num_cases": 10,
        "invariants": {
            "retrieval_behavior": "unchanged",
            "reranker_behavior": "unchanged",
            "answer_schema": "unchanged",
        },
        "metrics": {
            "response_quality": {
                "accuracy": accuracy,
                "groundedness": accuracy,
                "answer_format_compliance": 1.0,
            },
            "citation": {
                "citation_precision": citation,
                "claim_citation_alignment": citation,
            },
            "abstention": {"abstention": 0.0, "insufficient_status_count": 0},
            "token_cost": {
                "input_tokens_mean": None,
                "output_tokens_mean": None,
                "cost_estimate_usd_mean": None,
                "status": "not_observable_from_prediction_diagnostics",
            },
            "latency_ms": {"p50": p95 / 2, "p95": p95, "count": 10},
        },
    }


def test_evidence_first_prefers_topic_match_and_dedupes() -> None:
    evidence = [
        _evidence("a", text="unrelated", score=0.99, section="s1"),
        _evidence("b", text="납품 일정 포함", score=0.50, section="s2"),
        _evidence("b-dup", text="납품 일정 포함", score=0.40, section="s2"),
    ]

    selected = evidence_first_selector({"topics": ["납품 일정"]}, evidence)

    assert [item["chunk_id"] for item in selected] == ["b", "a"]


def test_classification_blocks_citation_regression() -> None:
    decision = classify_variants(
        [
            _variant("control_context_default", accuracy=0.50, citation=0.80, p95=100.0),
            _variant("context_evidence_first", accuracy=0.60, citation=0.70, p95=100.0),
        ],
        {"baseline_latency": {"hard_ceiling_ms": 500.0}},
    )

    assert decision["overall_classification"] == "citation_regression"
    assert decision["variants"][0]["classifications"] == ["citation_regression"]


def test_classification_selects_winner_when_answer_and_citation_hold() -> None:
    decision = classify_variants(
        [
            _variant("control_context_default", accuracy=0.50, citation=0.80, p95=100.0),
            _variant("context_evidence_first", accuracy=0.60, citation=0.80, p95=100.0),
        ],
        {"baseline_latency": {"hard_ceiling_ms": 500.0}},
    )

    assert decision["overall_classification"] == "winner"
    assert decision["selected_variant"] == "context_evidence_first"


def test_build_aggregate_and_markdown_are_privacy_safe(tmp_path: Path) -> None:
    config = tmp_path / "real100_v2" / "config.local.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("cases: []\n", encoding="utf-8")
    index = {"build": {}, "embedding": {}, "documents": [1], "chunks": [1, 2]}

    aggregate = build_aggregate(
        config_path=config,
        index=index,
        variants=[
            _variant("control_context_default", accuracy=0.50, citation=0.80, p95=100.0),
            _variant("context_evidence_first", accuracy=0.60, citation=0.80, p95=100.0),
        ],
        latency_budget={"profile_type": "private_real100_v2_latency_cost_budget", "baseline_latency": {"hard_ceiling_ms": 500.0}},
        cases_requested=10,
        cases_evaluated=3,
    )

    rendered = render_markdown(aggregate)

    assert aggregate["profile_type"] == "private_real100_v2_context_packing"
    assert aggregate["decision"]["overall_classification"] == "winner"
    assert aggregate["run_scope"]["paired_delta_valid"] is False
    assert "raw case prompts" in rendered
    assert "/Users/" not in json.dumps(aggregate)
