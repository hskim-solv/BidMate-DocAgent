from __future__ import annotations

import json
from pathlib import Path

from scripts.render_multi_chunk_retrieval_strategy import (
    build_strategy_report,
    main,
    render_markdown,
)


def _aggregate(
    *,
    multi_cases: int = 99,
    failures: int = 97,
    same_doc: int = 0,
    multi_doc: int = 0,
    unknown: int = 99,
    after_top10: int = 0,
    all_after_top10: int = 0,
    not_observable: int = 97,
    pool_or_rerank: int = 0,
    query_decomposition: int = 0,
    section_expansion: int = 0,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": {
            "basename": "eval_summary.json",
            "location": "external_private/eval_summary.json",
            "location_redacted": True,
            "sha256_12": "abc123def456",
        },
        "population": {
            "num_predictions": 221,
            "multi_chunk_gold_cases": multi_cases,
            "multi_chunk_top10_evidence_failures": failures,
        },
        "retrieval_outcome_by_k": {
            "5": {
                "all_gold_retrieved": 2,
                "partial_gold_retrieved": 35,
                "no_gold_retrieved": 57,
                "not_observable": 5,
            },
            "10": {
                "all_gold_retrieved": 2,
                "partial_gold_retrieved": 0,
                "no_gold_retrieved": 14,
                "not_observable": 83,
            },
            "20": {
                "all_gold_retrieved": 2,
                "partial_gold_retrieved": 0,
                "no_gold_retrieved": 14,
                "not_observable": 83,
            },
        },
        "evidence_split": {
            "same_doc": same_doc,
            "multi_doc": multi_doc,
            "unknown": unknown,
        },
        "candidate_pool_expansion": {
            "missing_gold_seen_after_top10": after_top10,
            "all_missing_gold_seen_after_top10": all_after_top10,
            "not_observable_due_to_depth": not_observable,
        },
        "expected_impact": {
            "pool_or_rerank_candidate": pool_or_rerank,
            "query_decomposition_candidate": query_decomposition,
            "section_expansion_candidate": section_expansion,
            "unknown_due_to_limited_depth": not_observable,
        },
        "structured_overlap": {
            "multi_chunk_gold_cases": {
                "hardcase_table_heavy": 0,
                "metadata_field_structured": 0,
                "case_source_format": {"other": multi_cases},
            },
            "top10_evidence_failures": {
                "hardcase_table_heavy": 0,
                "metadata_field_structured": 0,
                "case_source_format": {"other": failures},
            },
        },
    }


def test_current_shape_recommends_defer_until_page_metadata_recovery() -> None:
    report = build_strategy_report(_aggregate())

    assert report["recommendation"] == "defer_until_page_metadata_recovery"
    assert report["recommendation_set"] == ["defer_until_page_metadata_recovery"]
    assert report["run_order"] == "after_page_metadata_recovery"
    assert "evidence_split_unknown_dominant" in report["decision_reasons"]
    assert report["privacy"]["aggregate_only"] is True


def test_renderer_emits_json_and_markdown(tmp_path: Path) -> None:
    input_path = tmp_path / "multi_chunk.aggregate.json"
    out_json = tmp_path / "strategy.aggregate.json"
    out_md = tmp_path / "strategy.md"
    input_path.write_text(json.dumps(_aggregate()), encoding="utf-8")

    rc = main(
        [
            "--input",
            str(input_path),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ]
    )

    assert rc == 0
    written = json.loads(out_json.read_text(encoding="utf-8"))
    assert written["recommendation_set"] == [written["recommendation"]]
    assert written["source"]["input_artifact"] == "external_private/multi_chunk.aggregate.json"
    md = out_md.read_text(encoding="utf-8")
    assert "`defer_until_page_metadata_recovery`" in md
    assert "after page metadata recovery" in md


def test_defer_priority_beats_pool_section_query_and_reranker_signals() -> None:
    report = build_strategy_report(
        _aggregate(
            same_doc=20,
            multi_doc=20,
            unknown=60,
            after_top10=7,
            all_after_top10=5,
            not_observable=60,
            pool_or_rerank=5,
            query_decomposition=20,
            section_expansion=20,
        )
    )

    assert report["recommendation"] == "defer_until_page_metadata_recovery"
    assert "evidence_split_unknown_dominant" in report["decision_reasons"]


def test_candidate_pool_priority_is_deterministic_when_not_deferred() -> None:
    report = build_strategy_report(
        _aggregate(
            multi_cases=10,
            failures=10,
            same_doc=6,
            multi_doc=4,
            unknown=0,
            after_top10=3,
            all_after_top10=2,
            not_observable=0,
            pool_or_rerank=2,
            query_decomposition=4,
            section_expansion=6,
        )
    )

    assert report["recommendation"] == "candidate_pool_expansion"
    assert report["recommendation_set"] == ["candidate_pool_expansion"]


def test_missing_optional_fields_are_defaulted_safely() -> None:
    report = build_strategy_report({})
    md = render_markdown(report)

    assert report["recommendation"] == "defer_until_page_metadata_recovery"
    assert report["population"]["multi_chunk_gold_cases"] == 0
    assert report["evidence_split"]["counts"] == {
        "same_doc": 0,
        "multi_doc": 0,
        "unknown": 0,
    }
    assert "Multi-Chunk Retrieval Strategy Decision" in md


def test_private_like_input_fields_are_not_rendered() -> None:
    secret = "비밀기관_원문"
    aggregate = _aggregate()
    aggregate["query"] = secret
    aggregate["answer"] = "PRIVATE ANSWER"
    aggregate["doc_id"] = "SECRET_DOC_ID"
    aggregate["chunk_id"] = "SECRET_CHUNK_ID"
    aggregate["path"] = "/Users/example/private/file.pdf"
    aggregate["section"] = "PRIVATE SECTION"
    aggregate["evidence_split"]["비공개"] = 10  # type: ignore[index]
    aggregate["structured_overlap"]["top10_evidence_failures"]["case_source_format"][secret] = 1  # type: ignore[index]

    report = build_strategy_report(aggregate)
    rendered = json.dumps(report, ensure_ascii=False) + render_markdown(report)

    for forbidden in (
        secret,
        "PRIVATE ANSWER",
        "SECRET_DOC_ID",
        "SECRET_CHUNK_ID",
        "/Users/example/private/file.pdf",
        "PRIVATE SECTION",
        "비공개",
    ):
        assert forbidden not in rendered
