from __future__ import annotations

from scripts.component_eval.verifier_drift_check import doc_matched, gold_retrieved


def test_gold_retrieved_is_true_when_any_gold_chunk_was_retrieved() -> None:
    assert gold_retrieved({"gold_chunk_ids": ["g1", "g2"], "retrieved_chunk_ids": ["r0", "g2"]}) is True


def test_gold_retrieved_is_false_for_missing_or_disjoint_gold_ids() -> None:
    assert gold_retrieved({"gold_chunk_ids": ["g1"], "retrieved_chunk_ids": ["r1"]}) is False
    assert gold_retrieved({"retrieved_chunk_ids": ["r1"]}) is False


def test_gold_retrieved_normalizes_numeric_ids_before_comparison() -> None:
    assert gold_retrieved({"gold_chunk_ids": [1001], "retrieved_chunk_ids": ["1001"]}) is True


def test_doc_matched_requires_all_expected_docs_in_evidence() -> None:
    assert doc_matched({"expected_doc_ids": ["d1", "d2"], "evidence_doc_ids": ["d0", "d1", "d2"]}) is True
    assert doc_matched({"expected_doc_ids": ["d1", "d2"], "evidence_doc_ids": ["d1"]}) is False


def test_doc_matched_is_false_without_expected_docs() -> None:
    assert doc_matched({"expected_doc_ids": [], "evidence_doc_ids": ["d1"]}) is False
    assert doc_matched({"evidence_doc_ids": ["d1"]}) is False


def test_doc_matched_normalizes_numeric_ids_before_comparison() -> None:
    assert doc_matched({"expected_doc_ids": [2026], "evidence_doc_ids": ["d0", "2026"]}) is True
