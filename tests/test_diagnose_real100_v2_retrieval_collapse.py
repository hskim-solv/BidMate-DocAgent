from __future__ import annotations

from scripts.diagnose_real100_v2_retrieval_collapse import build_report, render_markdown


def _retrieved(chunk_ids: list[str], doc_ids: list[str]) -> list[dict[str, object]]:
    return [
        {"rank": rank, "chunk_id": chunk_id, "doc_id": doc_id, "text_preview": "PRIVATE"}
        for rank, (chunk_id, doc_id) in enumerate(zip(chunk_ids, doc_ids), start=1)
    ]


def _case(gold_chunks: list[str], gold_docs: list[str], retrieved_chunks: list[str], retrieved_docs: list[str]) -> dict[str, object]:
    return {
        "answerable": True,
        "gold_chunk_ids": gold_chunks,
        "gold_evidence": [
            {"chunk_id": chunk_id, "doc_id": doc_id}
            for chunk_id, doc_id in zip(gold_chunks, gold_docs)
        ],
        "retrieved_chunks": _retrieved(retrieved_chunks, retrieved_docs),
        "query": "PRIVATE QUERY SHOULD NOT LEAK",
        "answer": "PRIVATE ANSWER SHOULD NOT LEAK",
    }


def _summary(*, label: str, cases: list[dict[str, object]], manifest: dict[str, object]) -> dict[str, object]:
    return {
        "num_predictions": len(cases),
        "case_results": cases,
        "run_manifest": manifest,
        "index_citation_metadata_coverage": {
            "chunks_total": 10,
            "chunks_with_page_span": 10 if label == "current" else 0,
            "page_span_coverage": 1.0 if label == "current" else 0.0,
        },
    }


def test_build_report_compares_chunk_and_doc_retrieval_without_raw_case_leakage() -> None:
    current = _summary(
        label="current",
        manifest={
            "embedding_backend": "sentence-transformers",
            "embedding_model_id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            "chunking_strategy": "section",
            "chunker_version": "chunker.section.v1",
            "vector_store_backend": "chroma",
            "config_sha256": "abc123",
        },
        cases=[
            _case(["gold-a"], ["doc-a"], ["miss-1", "miss-2"], ["doc-x", "doc-y"]),
            _case(["gold-b"], ["doc-b"], ["miss-3", "miss-4"], ["doc-b", "doc-z"]),
        ],
    )
    backup = _summary(
        label="backup",
        manifest={
            "embedding_backend": "hashing",
            "embedding_model_id": "local-hashing-bow",
            "chunking_strategy": "fixed",
            "chunker_version": "chunker.fixed.v1",
            "config_sha256": "def456",
        },
        cases=[
            _case(["gold-a"], ["doc-a"], ["gold-a", "miss-2"], ["doc-a", "doc-y"]),
            _case(["gold-b"], ["doc-b"], ["miss-3", "gold-b"], ["doc-z", "doc-b"]),
        ],
    )

    report = build_report(current, backup)

    assert report["schema_version"] == 1
    assert report["profile_type"] == "private_real100_v2_retrieval_collapse_diagnosis"
    assert report["current"]["retrieval"]["chunk_hit_at_5"] == 0.0
    assert report["current"]["retrieval"]["doc_hit_at_5"] == 0.5
    assert report["comparison"]["doc_hit_at_5_delta_current_minus_backup"] == -0.5
    assert report["comparison"]["chunk_hit_at_5_delta_current_minus_backup"] == -1.0
    assert report["diagnosis"]["primary_signal"] == "doc_ranking_collapse_not_chunk_id_only"
    assert report["diagnosis"]["baseline_comparability"] == "not_comparable_stack_changed"
    assert "case_results" not in str(report)
    assert "PRIVATE QUERY" not in str(report)


def test_render_markdown_keeps_reviewer_summary_aggregate_only() -> None:
    report = build_report(
        _summary(label="current", cases=[_case(["g"], ["d"], ["x"], ["z"])], manifest={"embedding_backend": "sentence-transformers", "chunking_strategy": "section"}),
        _summary(label="backup", cases=[_case(["g"], ["d"], ["g"], ["d"])], manifest={"embedding_backend": "hashing", "chunking_strategy": "fixed"}),
    )

    rendered = render_markdown(report)

    assert "T-2026-0076" in rendered
    assert "doc_ranking_collapse_not_chunk_id_only" in rendered
    assert "PRIVATE" not in rendered


def test_build_report_marks_retrieval_knob_changes_as_incomparable() -> None:
    current = _summary(
        label="current",
        manifest={
            "embedding_backend": "sentence-transformers",
            "embedding_model_id": "safe-model",
            "chunking_strategy": "section",
            "chunker_version": "chunker.section.v1",
            "vector_store_backend": "chroma",
            "retrieval_backend": "hybrid",
            "retrieval_mode": "parent_section",
            "retrieval_top_k": 8,
            "retrieval_rerank": True,
            "bm25_backend": "okapi",
            "bm25_tokenizer": "regex",
            "bm25_stopword_profile": "shared",
        },
        cases=[_case(["g"], ["d"], ["x"], ["z"])],
    )
    backup = _summary(
        label="backup",
        manifest={
            "embedding_backend": "sentence-transformers",
            "embedding_model_id": "safe-model",
            "chunking_strategy": "section",
            "chunker_version": "chunker.section.v1",
            "vector_store_backend": "chroma",
            "retrieval_backend": "dense",
            "retrieval_mode": "flat",
            "retrieval_top_k": 5,
            "retrieval_rerank": False,
            "bm25_backend": "bm25s",
            "bm25_tokenizer": "kiwi",
            "bm25_stopword_profile": "none",
        },
        cases=[_case(["g"], ["d"], ["g"], ["d"])],
    )

    report = build_report(current, backup)

    assert report["comparison"]["baseline_comparability"] == "not_comparable_stack_changed"
    assert "retrieval_backend" in report["comparison"]["changed_stack_fields"]
    assert "retrieval_top_k" in report["comparison"]["changed_stack_fields"]
    assert "bm25_tokenizer" in report["comparison"]["changed_stack_fields"]


def test_manifest_redacts_local_model_paths_before_json_and_markdown_rendering() -> None:
    current = _summary(
        label="current",
        manifest={
            "embedding_backend": "sentence-transformers",
            "embedding_model_id": "/Users/hskim/private/model.bin",
            "chunking_strategy": "section",
        },
        cases=[_case(["g"], ["d"], ["x"], ["z"])],
    )
    backup = _summary(
        label="backup",
        manifest={
            "embedding_backend": "sentence-transformers",
            "embedding_model_id": "data/private/model.bin",
            "chunking_strategy": "section",
        },
        cases=[_case(["g"], ["d"], ["g"], ["d"])],
    )

    report = build_report(current, backup)
    rendered = render_markdown(report)

    assert report["current"]["run_manifest"]["embedding_model_id"] == "[redacted-local-path]"
    assert report["backup"]["run_manifest"]["embedding_model_id"] == "[redacted-local-path]"
    assert "/Users/hskim" not in str(report)
    assert "data/private/model.bin" not in str(report)
    assert "/Users/hskim" not in rendered
    assert "data/private/model.bin" not in rendered
