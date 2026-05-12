"""Per-case eval scorers split out of ``eval/run_eval.py`` (issue #259).

Public surface mirrors the original ``run_eval.py`` exports so existing
imports keep working. Aggregation, orchestration, and the CLI driver
remain in ``eval/run_eval.py``.
"""
from eval.scorers.alignment import score_claim_citation_alignment
from eval.scorers.case import score_case
from eval.scorers.chunk_metrics import (
    chunk_mrr,
    chunk_ndcg_at_k,
    chunk_recall_at_k,
    derive_gold_chunk_ids,
)
from eval.scorers.citation import score_citation_grounding
from eval.scorers.format import score_answer_format

__all__ = [
    "chunk_mrr",
    "chunk_ndcg_at_k",
    "chunk_recall_at_k",
    "derive_gold_chunk_ids",
    "score_case",
    "score_citation_grounding",
    "score_claim_citation_alignment",
    "score_answer_format",
]
