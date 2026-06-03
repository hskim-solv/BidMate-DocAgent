"""Regression guards for aggregate-only real100_v2 tier rendering."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.private_data_quality_audit_utils import assert_public_safe
from scripts.render_real100_v2_aggregates import TIERS, main, render_tiers


def _case(case_id: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": case_id,
        "answerable": True,
        "abstained": False,
        "chunk_recall_at_5": 0.0,
        "chunk_recall_at_10": 0.0,
        "chunk_mrr_at_5": 0.0,
        "chunk_ndcg_at_5": 0.0,
        "citation_precision": 0.0,
        "citation_grounding": 0.0,
        "abstention": None,
        "failure_category": "none",
        # Input may contain private per-case fields; output must not.
        "question": "PRIVATE QUESTION SENTINEL",
        "answer": "PRIVATE ANSWER SENTINEL",
        "doc_id": "PRIVATE_DOC",
        "chunk_id": "PRIVATE_CHUNK",
        "file_path": "/Users/example/private.rfp",
    }
    payload.update(overrides)
    return payload


def test_render_tiers_groups_metrics_and_unknown_cases_without_private_leak() -> None:
    summary = {
        "case_results": [
            _case(
                "easy-1",
                chunk_recall_at_5=1.0,
                chunk_recall_at_10=1.0,
                chunk_mrr_at_5=0.5,
                chunk_ndcg_at_5=0.75,
                citation_precision=0.25,
                citation_grounding=1.0,
            ),
            _case(
                "standard-1",
                abstained=True,
                chunk_recall_at_5=0.5,
                chunk_recall_at_10=1.0,
                failure_category="retrieval_miss",
            ),
            _case(
                "hard-1",
                answerable=False,
                abstained=True,
                abstention=1.0,
                failure_category="new_private_failure_label",
            ),
            _case("unmapped-1", chunk_recall_at_5=1.0),
        ]
    }
    question_tiers = {
        "easy-1": "easy_sanity",
        "standard-1": "standard_real",
        "hard-1": "hard_stress",
    }

    aggregate = render_tiers(summary, question_tiers)

    assert aggregate["profile_type"] == "private_real100_v2_benchmark_tiers"
    assert set(aggregate["tiers"]) == set(TIERS)
    assert aggregate["unknown_tier_case_count"] == 1
    assert aggregate["tiers"]["easy_sanity"]["n"] == 1
    assert aggregate["tiers"]["standard_real"]["n"] == 1
    assert aggregate["tiers"]["hard_stress"]["n"] == 1
    assert aggregate["tiers"]["easy_sanity"]["metrics"]["recall_at_5"] == {
        "mean": 1.0,
        "n": 1,
        "missing": 0,
    }
    assert aggregate["tiers"]["standard_real"]["abstention_outcomes"] == {
        "false_abstention": 1
    }
    assert aggregate["tiers"]["hard_stress"]["abstention_outcomes"] == {
        "correct_abstention": 1
    }
    assert aggregate["tiers"]["hard_stress"]["failure_distribution"] == {
        "unknown": 1
    }

    assert_public_safe(aggregate)
    rendered = json.dumps(aggregate, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "PRIVATE QUESTION SENTINEL",
        "PRIVATE ANSWER SENTINEL",
        "PRIVATE_DOC",
        "PRIVATE_CHUNK",
        "/Users/example/private.rfp",
        "case_results",
    ):
        assert forbidden not in rendered


def test_cli_writes_baseline_and_tier_aggregates(tmp_path: Path) -> None:
    summary_path = tmp_path / "eval_summary.json"
    questions_path = tmp_path / "questions.jsonl"
    baseline_out = tmp_path / "baseline.aggregate.json"
    tiers_out = tmp_path / "benchmark_tiers.aggregate.json"

    summary_path.write_text(
        json.dumps(
            {
                "num_predictions": 2,
                "accuracy": 0.5,
                "groundedness": 0.25,
                "citation_precision": 0.75,
                "citation_grounding": 1.0,
                "claim_citation_alignment": 0.5,
                "answer_format_compliance": 1.0,
                "abstention": None,
                "retry": 0.0,
                "case_results": [
                    _case("easy-1", chunk_recall_at_5=1.0),
                    _case(
                        "hard-1",
                        answerable=False,
                        abstained=False,
                        abstention=0.0,
                    ),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    questions_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "question_id": "easy-1",
                        "difficulty_tier": "easy_sanity",
                        "question": "PRIVATE QUESTION SENTINEL",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "question_id": "hard-1",
                        "difficulty_tier": "hard_stress",
                        "support_text": "PRIVATE SUPPORT SENTINEL",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rc = main(
        [
            "--eval-summary",
            str(summary_path),
            "--questions",
            str(questions_path),
            "--baseline-out",
            str(baseline_out),
            "--tiers-out",
            str(tiers_out),
        ]
    )

    assert rc == 0
    baseline = json.loads(baseline_out.read_text(encoding="utf-8"))
    tiers = json.loads(tiers_out.read_text(encoding="utf-8"))
    assert baseline["profile_type"] == "private_real100_v2_baseline"
    assert baseline["metrics"]["recall_at_5"] is None
    assert baseline["privacy"]["aggregate_only"] is True
    assert tiers["profile_type"] == "private_real100_v2_benchmark_tiers"
    assert tiers["tiers"]["easy_sanity"]["n"] == 1
    assert tiers["tiers"]["hard_stress"]["abstention_outcomes"] == {
        "missed_abstention": 1
    }
    assert_public_safe(baseline)
    assert_public_safe(tiers)
    rendered = json.dumps({"baseline": baseline, "tiers": tiers}, ensure_ascii=False)
    assert "PRIVATE QUESTION SENTINEL" not in rendered
    assert "PRIVATE SUPPORT SENTINEL" not in rendered


def test_committed_benchmark_tiers_artifact_matches_public_contract() -> None:
    path = Path("reports/real100_v2/benchmark_tiers.aggregate.json")
    aggregate = json.loads(path.read_text(encoding="utf-8"))

    assert aggregate["schema_version"] == 1
    assert aggregate["profile_type"] == "private_real100_v2_benchmark_tiers"
    assert set(aggregate["tiers"]) == set(TIERS)
    assert aggregate["privacy"] == {
        "aggregate_only": True,
        "chunk_ids_omitted": True,
        "doc_ids_omitted": True,
        "filenames_omitted": True,
        "paths_omitted": True,
        "per_case_rows_omitted": True,
        "raw_answers_omitted": True,
        "raw_evidence_omitted": True,
        "raw_questions_omitted": True,
        "raw_text_omitted": True,
    }
    for tier in TIERS:
        block = aggregate["tiers"][tier]
        assert {"n", "metrics", "abstention_outcomes", "failure_distribution"} <= set(block)
        assert {"recall_at_5", "recall_at_10", "mrr_at_5", "ndcg_at_5"} <= set(
            block["metrics"]
        )
    assert_public_safe(aggregate)
