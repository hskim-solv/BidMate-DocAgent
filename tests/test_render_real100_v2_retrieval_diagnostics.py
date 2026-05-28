from __future__ import annotations

import json
from pathlib import Path

from scripts.render_real100_v2_retrieval_diagnostics import (
    build_diagnostics,
    main,
    render_markdown,
)


def _retrieved(ids: list[str], docs: list[str] | None = None) -> list[dict[str, object]]:
    docs = docs or [f"doc-{idx}" for idx, _ in enumerate(ids, start=1)]
    return [
        {
            "rank": rank,
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "section": "PRIVATE SECTION",
            "text_preview": "PRIVATE TEXT",
        }
        for rank, (chunk_id, doc_id) in enumerate(zip(ids, docs), start=1)
    ]


def _case(
    *,
    gold_ids: list[str],
    retrieved_ids: list[str],
    answerable: bool = True,
    gold_docs: list[str] | None = None,
    retrieved_docs: list[str] | None = None,
    query_type: str = "single_doc",
    failure_category: str | None = None,
    metadata_candidate_count: int = 0,
    doc_match: bool = True,
    metadata_ambiguous: bool = False,
    filter_stage: str = "strict",
    recall5: float | None = None,
    recall10: float | None = None,
    mrr5: float | None = None,
    ndcg5: float | None = None,
) -> dict[str, object]:
    evidence = [
        {"doc_id": doc_id, "chunk_id": chunk_id}
        for doc_id, chunk_id in zip(gold_docs or [], gold_ids)
    ]
    return {
        "answerable": answerable,
        "gold_chunk_ids": gold_ids,
        "gold_evidence": evidence,
        "retrieved_chunks": _retrieved(retrieved_ids, retrieved_docs),
        "query_type": query_type,
        "failure_category": failure_category,
        "metadata_candidate_count": metadata_candidate_count,
        "doc_match": doc_match,
        "metadata_ambiguous": metadata_ambiguous,
        "filter_stage": filter_stage,
        "chunk_recall_at_5": recall5,
        "chunk_recall_at_10": recall10,
        "chunk_recall_at_20": recall10,
        "chunk_mrr_at_5": mrr5,
        "chunk_mrr": mrr5,
        "chunk_ndcg_at_5": ndcg5,
        "chunk_ndcg_at_10": ndcg5,
        "context_precision_at_5": 0.25,
        "context_recall_at_5": recall5,
        "query": "PRIVATE QUERY",
        "answer": "PRIVATE ANSWER",
    }


def _summary(cases: list[dict[str, object]]) -> dict[str, object]:
    return {
        "num_predictions": len(cases),
        "case_results": cases,
        "index_citation_metadata_coverage": {
            "chunks_total": 100,
            "chunks_with_page_span": 0,
            "page_span_coverage": 0.0,
            "coverage_reason": "index_lacks_page_region_metadata",
        },
    }


def test_build_diagnostics_classifies_retrieval_buckets() -> None:
    all_top5 = _case(
        gold_ids=["g1", "g2"],
        gold_docs=["doc-a", "doc-a"],
        retrieved_ids=["g1", "g2", "x1"],
        retrieved_docs=["doc-a", "doc-a", "doc-x"],
        recall5=1.0,
        recall10=1.0,
        mrr5=1.0,
        ndcg5=1.0,
    )
    ranked_low = _case(
        gold_ids=["low-a", "low-b"],
        gold_docs=["doc-b", "doc-b"],
        retrieved_ids=["low-a", "x2", "x3", "x4", "x5", "low-b"],
        retrieved_docs=["doc-b", "doc-x", "doc-y", "doc-z", "doc-w", "doc-b"],
        metadata_candidate_count=2,
        doc_match=False,
        filter_stage="relaxed",
        recall5=0.5,
        recall10=1.0,
        mrr5=0.5,
        ndcg5=0.5,
    )
    not_in_pool = _case(
        gold_ids=["miss-a"],
        gold_docs=["doc-c"],
        retrieved_ids=[f"x{i}" for i in range(10)],
        retrieved_docs=[f"doc-{i}" for i in range(10)],
        failure_category="verifier_false_negative",
        recall5=0.0,
        recall10=0.0,
        mrr5=0.0,
        ndcg5=0.0,
    )
    duplicate = _case(
        gold_ids=["dup-g"],
        gold_docs=["doc-d"],
        retrieved_ids=["dup-g", "x11", "x12"],
        retrieved_docs=["doc-d", "doc-d", "doc-e"],
        metadata_ambiguous=True,
        failure_category="verifier_false_positive",
        recall5=1.0,
        recall10=1.0,
        mrr5=1.0,
        ndcg5=1.0,
    )
    unanswerable = _case(
        gold_ids=[],
        retrieved_ids=[],
        answerable=False,
        query_type="abstention",
        failure_category="abstention_failure",
    )

    report = build_diagnostics(_summary([all_top5, ranked_low, not_in_pool, duplicate, unanswerable]))

    assert report["population"]["num_predictions"] == 5
    assert report["exclusive_retrieval_status"]["counts"]["all_gold_top5"] == 2
    assert report["exclusive_retrieval_status"]["counts"]["all_gold_top10_not_top5"] == 1
    assert report["exclusive_retrieval_status"]["counts"]["not_in_candidate_pool"] == 1
    assert report["failure_buckets"]["not_in_candidate_pool"] == 1
    assert report["failure_buckets"]["ranked_too_low_after_top5"] == 1
    assert report["failure_buckets"]["boundary_or_window_candidate"] == 1
    assert report["failure_buckets"]["metadata_filter_candidate"] == 2
    assert report["failure_buckets"]["duplicate_or_near_duplicate_candidate"] == 3
    assert report["failure_buckets"]["multi_evidence_failure"] == 1
    assert report["failure_buckets"]["verifier_false_negative"] == 1
    assert report["failure_buckets"]["verifier_false_positive"] == 1
    assert report["failure_buckets"]["answer_generation_or_abstention"] == 1
    assert report["page_metadata_blocker"]["status"] == "blocked_for_page_and_window_claims"
    assert report["next_task_decision"]["preferred_next_task"] == "T-2026-0032"


def test_markdown_and_json_do_not_copy_private_strings() -> None:
    secret = "SECRET_DOC_ID"
    report = build_diagnostics(
        _summary(
            [
                _case(
                    gold_ids=["SECRET_CHUNK_ID"],
                    gold_docs=[secret],
                    retrieved_ids=["SECRET_CHUNK_ID"],
                    retrieved_docs=[secret],
                )
            ]
        ),
        source={
            "input_artifact": "external_private/eval_summary.json",
            "input_location_redacted": True,
            "input_basename": "eval_summary.json",
            "input_sha256_12": "abc123def456",
        },
    )
    rendered = json.dumps(report, ensure_ascii=False) + render_markdown(report)

    for forbidden in (
        "SECRET_DOC_ID",
        "SECRET_CHUNK_ID",
        "PRIVATE QUERY",
        "PRIVATE ANSWER",
        "PRIVATE TEXT",
        "PRIVATE SECTION",
    ):
        assert forbidden not in rendered
    assert "real100_v2" in rendered
    assert "Legacy `real100`/v1/221/kordoc evidence is not used" in rendered


def test_cli_writes_aggregate_outputs_and_rejects_legacy_input(tmp_path: Path) -> None:
    v2_dir = tmp_path / "reports" / "real100_v2"
    v2_dir.mkdir(parents=True)
    summary = v2_dir / "eval_summary.json"
    out_json = tmp_path / "retrieval.aggregate.json"
    out_md = tmp_path / "retrieval.md"
    summary.write_text(json.dumps(_summary([])), encoding="utf-8")

    rc = main(["--summary", str(summary), "--out-json", str(out_json), "--out-md", str(out_md)])

    assert rc == 0
    written = json.loads(out_json.read_text(encoding="utf-8"))
    assert written["profile_type"] == "private_real100_v2_retrieval_diagnostics"
    assert written["privacy"]["aggregate_only"] is True
    assert "`T-2026-0029`" in out_md.read_text(encoding="utf-8")

    legacy_dir = tmp_path / "reports" / "real100"
    legacy_dir.mkdir(parents=True)
    legacy_summary = legacy_dir / "eval_summary.json"
    legacy_summary.write_text(json.dumps(_summary([])), encoding="utf-8")

    assert main(["--summary", str(legacy_summary), "--out-json", str(out_json), "--out-md", str(out_md)]) == 1
