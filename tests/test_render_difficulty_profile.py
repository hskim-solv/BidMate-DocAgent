from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.render_difficulty_profile import (
    assert_public_safe,
    build_aggregate,
    main,
    render_markdown,
)


SECRET_QUERY = "SECRET RAW QUESTION amount deadline score"
SECRET_ANSWER = "SECRET RAW ANSWER"
SECRET_DOC = "SECRET-DOC-001"
SECRET_CHUNK = "SECRET-CHUNK-001"
SECRET_TEXT = "SECRET RAW EVIDENCE budget 1000000 deadline 2026-01-01 score 90"
SECRET_PATH = "/Users/example/private/source.pdf"


def _index(with_chunks: bool = True) -> dict:
    payload = {"schema_version": 2}
    if with_chunks:
        payload["chunks"] = [
            {
                "doc_id": SECRET_DOC,
                "chunk_id": SECRET_CHUNK,
                "text": SECRET_TEXT,
                "section": "SECRET SECTION",
                "title": "SECRET TITLE",
            },
            {
                "doc_id": "SECRET-DOC-002",
                "chunk_id": "SECRET-CHUNK-002",
                "text": "| item | value |\n| budget | 200 |",
            },
        ]
    return payload


def _case(**overrides: object) -> dict:
    case = {
        "id": "SECRET-CASE-ID",
        "query": SECRET_QUERY,
        "answer": SECRET_ANSWER,
        "answerable": True,
        "expected_doc_ids": [SECRET_DOC],
        "expected_terms": ["budget", "deadline"],
        "gold_evidence": [{"doc_id": SECRET_DOC, "chunk_id": SECRET_CHUNK}],
        "gold_chunk_ids": [SECRET_CHUNK],
        "retrieved_chunks": [
            {
                "rank": 1,
                "doc_id": SECRET_DOC,
                "chunk_id": SECRET_CHUNK,
                "text_preview": SECRET_TEXT,
                "path": SECRET_PATH,
            }
        ],
        "chunk_recall_at_5": 1.0,
        "chunk_recall_at_10": 1.0,
        "chunk_mrr_at_5": 1.0,
        "chunk_ndcg_at_5": 1.0,
        "citation_precision": 1.0,
        "accuracy": 1.0,
        "abstention": None,
        "failure_category": None,
        "hardcase_categories": [],
    }
    case.update(overrides)
    return case


def _summary(cases: list[dict], *, primary_run: str = "naive_baseline") -> dict:
    return {
        "primary_run": primary_run,
        "pipeline": primary_run,
        "num_predictions": len(cases),
        "case_results": cases,
    }


def _serialize_outputs(aggregate: dict) -> str:
    return json.dumps(aggregate, ensure_ascii=False, sort_keys=True) + render_markdown(aggregate)


def test_privacy_guard_rejects_forbidden_keys_and_absolute_paths() -> None:
    with pytest.raises(ValueError):
        assert_public_safe({"query": "raw"})
    with pytest.raises(ValueError):
        assert_public_safe({"safe": "/Users/example/private/file.pdf"})


def test_schema_bucketization_and_no_raw_content_rendered() -> None:
    cases = [
        _case(),
        _case(
            query="What is the table score?",
            expected_doc_ids=[SECRET_DOC, "SECRET-DOC-002"],
            expected_terms=["score", "table", "budget", "deadline"],
            gold_evidence=[
                {"doc_id": SECRET_DOC, "chunk_id": SECRET_CHUNK},
                {"doc_id": "SECRET-DOC-002", "chunk_id": "SECRET-CHUNK-002"},
            ],
            gold_chunk_ids=[SECRET_CHUNK, "SECRET-CHUNK-002"],
            chunk_recall_at_5=0.5,
            chunk_recall_at_10=1.0,
            chunk_mrr_at_5=0.5,
            chunk_ndcg_at_5=0.5,
            citation_precision=0.0,
            accuracy=0.0,
            failure_category="retrieval_miss",
            hardcase_categories=["distractor_heavy"],
        ),
        _case(
            query="missing fact",
            answerable=False,
            expected_doc_ids=[],
            expected_terms=[],
            gold_evidence=[],
            gold_chunk_ids=[],
            chunk_recall_at_5=None,
            chunk_recall_at_10=None,
            chunk_mrr_at_5=None,
            chunk_ndcg_at_5=None,
            citation_precision=None,
            accuracy=None,
            abstention=1.0,
            failure_category=None,
        ),
    ]

    aggregate = build_aggregate(_summary(cases), _index())

    assert aggregate["schema_version"] == 1
    assert aggregate["profile_type"] == "private_real_eval_difficulty_profile"
    assert set(aggregate["difficulty_axes"]) >= {
        "answerability",
        "gold_doc_cardinality",
        "gold_chunk_cardinality",
        "expected_terms_count",
        "date_like_question",
        "amount_like_question",
        "score_like_question",
        "table_like_evidence",
        "similar_clause_distractor_proxy",
        "gold_evidence_count",
        "gold_chunk_length",
        "lexical_overlap",
    }
    assert aggregate["difficulty_axes"]["answerability"]["answerable"]["n"] == 2
    assert aggregate["difficulty_axes"]["answerability"]["unanswerable"]["n"] == 1
    assert aggregate["difficulty_axes"]["gold_doc_cardinality"]["multi_doc"]["n"] == 1
    assert aggregate["difficulty_axes"]["gold_chunk_cardinality"]["multi_chunk"]["n"] == 1
    assert aggregate["difficulty_axes"]["expected_terms_count"]["2_3"]["n"] == 1
    assert aggregate["difficulty_axes"]["expected_terms_count"]["4_plus"]["n"] == 1
    assert aggregate["difficulty_axes"]["table_like_evidence"]["true"]["n"] == 1
    assert aggregate["difficulty_axes"]["similar_clause_distractor_proxy"]["true"]["n"] == 1
    assert aggregate["difficulty_axes"]["lexical_overlap"]["high"]["n"] >= 1
    assert aggregate["overall_outcomes"]["metrics"]["recall_at_10"]["mean"] == 1.0
    assert aggregate["diagnostics"]["unique_failed_cases"] == 1
    assert aggregate["diagnostics"]["top_failure_slices"]
    assert aggregate["diagnostics"]["top_failure_slices"][0]["share_of_all_failures"] == 1.0

    rendered = _serialize_outputs(aggregate)
    for forbidden in (
        SECRET_QUERY,
        SECRET_ANSWER,
        SECRET_DOC,
        SECRET_CHUNK,
        SECRET_TEXT,
        SECRET_PATH,
        "SECRET SECTION",
        "SECRET TITLE",
        "SECRET-CASE-ID",
    ):
        assert forbidden not in rendered
    for forbidden_key in (
        '"query"',
        '"answer"',
        '"gold_evidence"',
        '"retrieved_chunks"',
        '"doc_id"',
        '"chunk_id"',
        '"path"',
    ):
        assert forbidden_key not in json.dumps(aggregate, ensure_ascii=False)


def test_missing_optional_fields_degrade_to_missing_unknown_buckets() -> None:
    case = _case()
    for key in (
        "expected_terms",
        "gold_evidence",
        "citation_accuracy",
        "citation_precision",
        "abstention_outcomes",
        "hardcase_categories",
    ):
        case.pop(key, None)
    case["expected_doc_ids"] = []
    case["gold_chunk_ids"] = []

    aggregate = build_aggregate(_summary([case]), _index())

    assert aggregate["difficulty_axes"]["expected_terms_count"]["missing"]["n"] == 1
    assert aggregate["difficulty_axes"]["gold_doc_cardinality"]["unknown"]["n"] == 1
    assert aggregate["difficulty_axes"]["gold_chunk_cardinality"]["none"]["n"] == 1
    assert aggregate["difficulty_axes"]["lexical_overlap"]["missing"]["n"] == 1
    assert aggregate["overall_outcomes"]["metrics"]["citation_precision"]["missing"] == 1


def test_non_naive_rejected_unless_explicitly_allowed() -> None:
    summary = _summary([_case()], primary_run="full")
    with pytest.raises(ValueError):
        build_aggregate(summary, _index())

    aggregate = build_aggregate(summary, _index(), allow_non_naive=True)
    assert aggregate["run"]["is_naive_primary"] is False


def test_main_exits_nonzero_when_required_index_chunks_absent(tmp_path: Path) -> None:
    summary_path = tmp_path / "eval_summary.json"
    index_path = tmp_path / "index.json"
    out_json = tmp_path / "difficulty.aggregate.json"
    out_md = tmp_path / "difficulty.md"
    summary_path.write_text(json.dumps(_summary([_case()])), encoding="utf-8")
    index_path.write_text(json.dumps(_index(with_chunks=False)), encoding="utf-8")

    rc = main(
        [
            "--summary",
            str(summary_path),
            "--index",
            str(index_path),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ]
    )

    assert rc == 1
    assert not out_json.exists()
    assert not out_md.exists()


def test_main_allow_non_naive_writes_outputs(tmp_path: Path) -> None:
    summary_path = tmp_path / "eval_summary.json"
    index_path = tmp_path / "index.json"
    out_json = tmp_path / "difficulty.aggregate.json"
    out_md = tmp_path / "difficulty.md"
    summary_path.write_text(json.dumps(_summary([_case()], primary_run="full")), encoding="utf-8")
    index_path.write_text(json.dumps(_index()), encoding="utf-8")

    rc = main(
        [
            "--summary",
            str(summary_path),
            "--index",
            str(index_path),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--allow-non-naive",
        ]
    )

    assert rc == 0
    written = json.loads(out_json.read_text(encoding="utf-8"))
    assert written["schema_version"] == 1
    assert SECRET_QUERY not in out_md.read_text(encoding="utf-8")
