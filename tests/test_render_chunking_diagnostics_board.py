"""Regression guard for the local chunking diagnostics HTML board."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.render_chunking_diagnostics_board import build_board, main, render_html


def _specs() -> list[dict[str, object]]:
    return [
        {
            "name": "current",
            "chunking_strategy": "fixed",
            "chunk_max_chars": 520,
            "chunk_overlap_sentences": 1,
            "num_documents": 2,
            "num_chunks": 20,
            "section_detection_rate": 0.0,
        },
        {
            "name": "larger",
            "chunking_strategy": "fixed",
            "chunk_max_chars": 1040,
            "chunk_overlap_sentences": 1,
            "num_documents": 2,
            "num_chunks": 10,
            "section_detection_rate": 0.0,
        },
    ]


def _raw_results() -> dict[str, object]:
    return {
        "current": {
            "latency_ms": {"p50": 10.0, "p95": 20.0},
            "per_case": [
                {
                    "qid": "PRIVATE_CASE_A",
                    "chunk_recall@5": 0.5,
                    "chunk_recall@10": 0.5,
                    "mrr": 0.25,
                    "ndcg@10": 0.3,
                },
                {
                    "qid": "PRIVATE_CASE_B",
                    "chunk_recall@5": None,
                    "chunk_recall@10": None,
                    "mrr": None,
                    "ndcg@10": None,
                },
            ],
        },
        "larger": {
            "latency_ms": {"p50": 8.0, "p95": 12.0},
            "per_case": [
                {
                    "qid": "PRIVATE_CASE_A",
                    "chunk_recall@5": 1.0,
                    "chunk_recall@10": 1.0,
                    "mrr": 0.5,
                    "ndcg@10": 0.6,
                }
            ],
        },
    }


def _deltas() -> dict[str, object]:
    return {
        "larger": {
            "chunk_recall@10": {
                "mean_current": 0.5,
                "mean_other": 1.0,
                "mean_diff": 0.5,
                "ci_lo": -0.1,
                "ci_hi": 0.9,
            }
        }
    }


def _eda() -> dict[str, object]:
    return {
        "axis2_chunk_health": {
            "corpus_chunk_health": {
                "total_chunks": 30,
                "empty_chunks": 0,
                "near_empty_chunks": 1,
                "length_chars": {"mean": 430.0, "p95": 517.0},
                "mid_sentence_cut_ratio": 0.25,
            },
            "per_doc_chunk_count": {"mean": 15.0, "p95": 18.0},
        }
    }


def _multi_chunk() -> dict[str, object]:
    return {
        "population": {
            "num_predictions": 2,
            "multi_chunk_gold_cases": 2,
            "multi_chunk_top10_evidence_failures": 1,
        },
        "retrieval_outcome_by_k": {
            "5": {
                "all_gold_retrieved": 1,
                "partial_gold_retrieved": 0,
                "no_gold_retrieved": 1,
                "not_observable": 0,
            },
            "10": {
                "all_gold_retrieved": 1,
                "partial_gold_retrieved": 0,
                "no_gold_retrieved": 1,
                "not_observable": 0,
            },
        },
        "evidence_split": {},
        "expected_impact": {},
        "candidate_pool_expansion": {},
    }


def test_build_board_uses_aggregate_metrics_only() -> None:
    board = build_board(
        specs=_specs(),
        raw_results=_raw_results(),
        deltas=_deltas(),
        eda=_eda(),
        multi_chunk=_multi_chunk(),
    )

    assert board["current"]["num_chunks"] == 20
    assert board["best_recall10"]["name"] == "larger"
    assert board["multi_chunk"]["top10_failure_rate"] == 0.5
    assert board["variants"][0]["metrics"]["chunk_recall@10"]["mean"] == 0.5


def test_html_has_required_sections_and_no_private_case_ids() -> None:
    board = build_board(
        specs=_specs(),
        raw_results=_raw_results(),
        deltas=_deltas(),
        eda=_eda(),
        multi_chunk=_multi_chunk(),
    )
    html = render_html(board)

    assert "<!doctype html>" in html
    assert "Chunking Diagnostics Board" in html
    assert "Chunking Variants" in html
    assert "Recall@10 Delta vs Current" in html
    assert "Chunk Health Snapshot" in html
    assert "Multi-chunk Evidence Retrieval" in html
    assert "PRIVATE_CASE_A" not in html
    assert "PRIVATE_CASE_B" not in html
    assert "<script" not in html


def test_cli_writes_html(tmp_path: Path) -> None:
    phase2 = tmp_path / "phase2"
    phase2.mkdir()
    (phase2 / "chunking_specs.json").write_text(json.dumps(_specs()), encoding="utf-8")
    (phase2 / "raw_results.json").write_text(json.dumps(_raw_results()), encoding="utf-8")
    (phase2 / "deltas.json").write_text(json.dumps(_deltas()), encoding="utf-8")
    eda = tmp_path / "eda.aggregate.json"
    multi = tmp_path / "multi.aggregate.json"
    out = tmp_path / "chunking.html"
    eda.write_text(json.dumps(_eda()), encoding="utf-8")
    multi.write_text(json.dumps(_multi_chunk()), encoding="utf-8")

    rc = main(
        [
            "--phase2-dir",
            str(phase2),
            "--eda",
            str(eda),
            "--multi-chunk",
            str(multi),
            "--out-html",
            str(out),
        ]
    )

    assert rc == 0
    assert out.exists()
    assert "Chunking Diagnostics Board" in out.read_text(encoding="utf-8")
