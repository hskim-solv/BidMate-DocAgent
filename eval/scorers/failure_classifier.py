"""Phase 5 audit item 1 supply — rule-based failure-mode classifier.

Consumes a ``case_result`` dict emitted by ``eval.scorers.case.score_case()``
and returns one of 7 categories (or ``None`` for successful cases) so that
downstream dashboards (Phase 5 supply 2) and regression tests (Phase 5
supply 3) can ground on a single per-case label.

The taxonomy is what the audit (``docs/audits/eval-framework-phase5-audit.md``
item 1) prescribed; the implementation is deterministic and uses only
fields already present in the ``case_result`` dict (no trace-JSON
dependency, so no coupling to the gitignored ``reports/real100/traces/``
surface).

**First-match-wins ordering** is load-bearing — finding #1 of the Phase 5
audit (``abstention_outcomes.incorrect_answer == 87`` on the n=221 baseline)
must accumulate into ``verifier_false_negative`` for the integration test
to pass; flipping it ahead of ``retrieval_miss`` would silently mis-bucket
the 87 cases and make supply 2's dashboard misleading.

ADR 0059 locks the contract; ADR 0001 / 0003 / 0005 / 0006 / 0054 /
0055 / 0056 invariance is preserved (read-only consumer, no production
code path is touched).
"""
from __future__ import annotations

from typing import Any, Literal

FailureCategory = Literal[
    "retrieval_miss",
    "planner_under_decomposition",
    "verifier_false_negative",
    "verifier_false_positive",
    "generator_hallucination",
    "context_dilution",
    "unknown",
]

FAILURE_CATEGORIES: tuple[FailureCategory, ...] = (
    "retrieval_miss",
    "planner_under_decomposition",
    "verifier_false_negative",
    "verifier_false_positive",
    "generator_hallucination",
    "context_dilution",
    "unknown",
)

# ADR 0001 baseline ``top_k`` (eval/config.yaml ``naive_baseline`` preset).
# Used as the threshold above which ``context_dilution`` becomes a
# candidate category. The v1 ``context_dilution`` branch is intentionally
# disabled (see classify_failure body) because case_result lacks a direct
# chunk_id → doc_id mapping; supply 2's dashboard will surface the real
# distribution and that informs the v2 wiring.
DEFAULT_TOP_K = 4

# ``generator_hallucination`` threshold on claim_citation_alignment. Set
# arbitrarily at v1; supply 2's distribution should inform tuning. Lower
# values widen the "hallucination" net; 0.5 was chosen to match the
# alignment scorer's per-claim 0.5 acceptance threshold
# (``eval/scorers/alignment.py:89`` overlap ≥ 0.5 → supported).
HALLUCINATION_ALIGNMENT_THRESHOLD = 0.5

# ``planner_under_decomposition`` fires only on query types that require
# decomposition; single-doc / factual queries with a single attempt are
# the expected steady state, not under-decomposition.
DECOMPOSITION_REQUIRED_QUERY_TYPES: frozenset[str] = frozenset({"comparison", "multi_hop"})


def is_failed(case_result: dict[str, Any]) -> bool:
    """Return True when this case_result represents a failure worth classifying.

    Mirrors the success definitions implicit in ``eval/scorers/case.py``
    + ``eval/run_eval.py:_abstention_outcomes`` (PR #464):

    * ``answerable=True``: success iff ``accuracy == 1.0`` (the
      ``score_case`` accuracy branch already requires ``doc_match AND
      term_match AND not abstained``, which is the strictest success
      definition the scorer emits).
    * ``answerable=False``: success iff the case is a ``correct_refusal``
      (``abstained AND not has_evidence``); everything else
      (``incorrect_answer`` / ``boundary_partial`` per the 3-bin PR #464
      decomposition) is a failure worth classifying.
    """
    answerable = case_result.get("answerable", True)
    if answerable:
        return case_result.get("accuracy") != 1.0
    abstained = bool(case_result.get("abstained"))
    has_evidence = bool(case_result.get("evidence_doc_ids"))
    return not (abstained and not has_evidence)


def classify_failure(case_result: dict[str, Any]) -> FailureCategory | None:
    """Return a 7-category label for a failed case, or ``None`` for successes.

    Order matters — the first matching branch wins. The ordering is
    chosen so the Phase 5 audit finding #1 pattern
    (``answerable=False AND not abstained``, the 87/103 incorrect_answer
    rate) accumulates into ``verifier_false_negative`` instead of being
    silently swallowed by a more permissive branch.
    """
    if not is_failed(case_result):
        return None

    answerable = bool(case_result.get("answerable", True))
    abstained = bool(case_result.get("abstained"))
    evidence_doc_ids = set(case_result.get("evidence_doc_ids") or [])
    expected_doc_ids = set(case_result.get("expected_doc_ids") or [])
    term_match = bool(case_result.get("term_match"))

    # 1. verifier_false_negative — model answered an unanswerable query.
    #    This is Phase 5 audit (#992) finding #1: 87/103 unanswerable
    #    cases on n=221 baseline. Must come first so the 87 cases land
    #    here and not in ``unknown``.
    if not answerable and not abstained:
        return "verifier_false_negative"

    # 2. verifier_false_positive — model refused an answerable query
    #    even though the right terms WERE in evidence (the evidence
    #    contained the answer; verifier was the wrong gatekeeper).
    if answerable and abstained and term_match:
        return "verifier_false_positive"

    # 3. retrieval_miss — answerable AND the expected doc never reached
    #    evidence. Comes before planner under-decomposition because a
    #    single-attempt planner is correct behaviour when retrieval has
    #    already found everything; the bug is retrieval, not planning.
    if answerable and expected_doc_ids and not (expected_doc_ids & evidence_doc_ids):
        return "retrieval_miss"

    # 4. planner_under_decomposition — comparison / multi_hop queries
    #    that exited the planner loop after a single attempt. ``attempt_latency``
    #    is the per-stage attempt log emitted by ``score_case`` from
    #    ``diagnostics.filter_stage_attempts`` (eval/scorers/case.py:185-192).
    query_type = case_result.get("query_type")
    attempt_latency = case_result.get("attempt_latency") or []
    if query_type in DECOMPOSITION_REQUIRED_QUERY_TYPES and len(attempt_latency) <= 1:
        return "planner_under_decomposition"

    # 5. generator_hallucination — claim ↔ citation alignment fell below
    #    the per-claim acceptance floor. Uses the existing
    #    ``score_claim_citation_alignment`` output (eval/scorers/alignment.py:214)
    #    which is already part of case_result.
    cca = case_result.get("claim_citation_alignment")
    if isinstance(cca, (int, float)) and cca < HALLUCINATION_ALIGNMENT_THRESHOLD:
        return "generator_hallucination"

    # 6. context_dilution — v1 disabled. The audit's definition
    #    ("top_k > default AND expected doc at lower rank") needs a
    #    chunk_id → doc_id mapping that case_result doesn't expose
    #    today. Falls through to ``unknown`` until supply 2's dashboard
    #    reveals whether the v2 wiring is worth the schema extension.
    #    (Hazard H3 in plan.)

    # 7. unknown — failed but none of the above patterns matched.
    return "unknown"


def aggregate_failure_categories(case_results: list[dict[str, Any]]) -> dict[str, int]:
    """Return ``{category: count}`` for the 7-category taxonomy.

    All 7 keys are always present (count = 0 if no case hit that branch)
    so downstream consumers (supply 2 dashboard, supply 3 regression
    test) can rely on the dict shape without missing-key guards.
    """
    counts: dict[str, int] = {category: 0 for category in FAILURE_CATEGORIES}
    for case_result in case_results:
        category = classify_failure(case_result)
        if category is None:
            continue
        counts[category] += 1
    return counts
