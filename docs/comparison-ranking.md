# Balanced Comparison Ranking

## Problem

For comparison queries (e.g. "기관 A와 기관 B의 보안 요구사항 차이는?") the legacy retrieval cut was a plain global top-k sort. When one comparison target's vocabulary dominates the question or the corpus has asymmetric chunk counts, all top-k slots can be filled by a single document. Downstream effects:

- The verifier flags `missing_comparison_doc` / `missing_comparison_entity` and triggers retries (extra latency).
- When retries also fail (because the bias is structural), the answer becomes a partial / one-sided comparison.

## Approach

A coverage-aware top-k cut is applied **inside `retrieve()` after scoring**, gated on `query_type == "comparison" AND target_count >= 2`. The cut:

1. Picks `min_per_target` highest-scoring chunks per comparison target.
2. Fills the remaining slots from globally-sorted candidates by score.
3. Preserves the score-descending order in the returned list.

The selection happens **before** the verifier sees the evidence, so a fair pool reduces spurious retries while still allowing genuine target-absent cases to abstain.

`select_supporting_evidence` (entity-grouped, used at answer time) is unchanged and acts as a downstream safety net.

## Configuration

The behavior is gated by a `comparison_balance` config bundle attached to a pipeline preset:

```python
DEFAULT_COMPARISON_BALANCE = {
    "enabled": True,
    "min_per_target": 1,   # guaranteed slots per comparison target
    "k_per_target": 3,     # adaptive top_k per target
    "headroom": 2,         # extra slots beyond k_per_target * target_count
    "max_top_k": 12,       # absolute ceiling on adaptive top_k
}
```

- `agentic_full` ships with this config enabled.
- `naive_baseline` does **not** include the key — the baseline retrieval path is unchanged.
- Disable per-call via `run_rag_query(..., comparison_balance={"enabled": False})`.

When enabled and `target_count >= 2`, `make_plan` sets:

```text
top_k = clamp(k_per_target * target_count + headroom, 6, max_top_k)
```

For 2 targets: `top_k = clamp(8, 6, 12) = 8`. For 3 targets: `top_k = clamp(11, 6, 12) = 11`.

## Target identification

In `comparison_targets_for_analysis(analysis)`:

- If `analysis["matched_doc_ids"]` has ≥2 entries, balancing groups by `chunk.doc_id`.
- Else if `analysis["entities"]` (matched agencies) has ≥2 entries, balancing groups by `chunk.agency`.
- Otherwise the helper is a no-op equivalent to `scored[:top_k]`.

doc_ids are preferred because they are unique; agency fallback handles cases where the analyzer matched agencies but not doc_ids.

## Diagnostics

The plan dict gains a `comparison_coverage` field whenever the query is a comparison with ≥2 targets, regardless of whether balancing is enabled:

```json
{
  "comparison_coverage": {
    "targets": ["asym-agency-a", "asym-agency-b"],
    "target_field": "doc_id",
    "before": {"asym-agency-a": 6, "asym-agency-b": 1},
    "after":  {"asym-agency-a": 7, "asym-agency-b": 1},
    "balanced": true,
    "min_per_target": 1
  }
}
```

This is also surfaced in `diagnostics.filter_stage_attempts[].comparison_coverage` so per-stage retries are debuggable.

## Eval metric

`eval/run_eval.py` computes two coverage metrics per `query_type == "multi_doc"` case with ≥2 expected doc_ids:

- `comparison_target_recall` = `|expected_doc_ids ∩ evidence_doc_ids| / |expected_doc_ids|` — measured against the FINAL evidence (post `select_supporting_evidence` topic-grounding trim). Sensitive to topic-grounding failures, not just retrieval coverage.
- `comparison_pool_recall` = `|expected_doc_ids ∩ pool_doc_ids| / |expected_doc_ids|` — measured against the post-balance retrieval pool (read from `plan.comparison_coverage.after`). Isolates the effect of balancing from downstream verifier/topic trimming.

Both are aggregated in `metric_block` as means plus a `*_full_coverage_rate` (fraction with recall == 1.0). They only appear under `by_query_type["multi_doc"]` and `by_hardcase_category["one_sided_comparison"]` (or any slice with qualifying cases) so headline numbers stay clean.

`comparison_pool_recall` is the cleanest signal that the balanced top-k cut is doing its job; `comparison_target_recall` is the user-visible answer-quality signal that depends on both balancing and topic grounding.

## When it helps

- **Asymmetric vocabulary**: question phrasing matches one target's domain terms, even though both targets are relevant. Example: "품질관리 관점에서 기관 A와 기관 B의 차이는?" ("품질관리" is heavy in agency A; agency B uses "데이터 거버넌스" / "drift").
- **Asymmetric chunk count**: one document has many short chunks, the other has fewer / longer ones.
- **Asymmetric metadata signal strength**: one target has a high-confidence metadata match, the other only a weak fuzzy match.

## When it does NOT help

- **Target genuinely absent from corpus**: balancing cannot synthesize evidence. The verifier still flags `missing_comparison_doc`; the answer abstains. This is locked in by `tests/test_fuzzy_retrieval.py::test_partial_comparison_keeps_supported_claims_and_missing_target`.
- **Single-doc and follow-up queries**: explicit no-op via the `query_type == "comparison" AND target_count >= 2` gate.
- **Genuinely one-sided answers**: e.g. "기관 A의 …" — these never reach the comparison branch.

## How to disable

- **Per-call**: `run_rag_query(..., comparison_balance={"enabled": False})`. The plan still records `comparison_coverage` for observability.
- **Globally**: pick `naive_baseline` preset. The baseline preset has no `comparison_balance` key, so balancing is off by construction.

## Implementation pointers

- `rag_core.py::DEFAULT_COMPARISON_BALANCE` — default config.
- `rag_core.py::comparison_targets_for_analysis` — target extraction.
- `rag_core.py::apply_comparison_balance` — the balanced cut.
- `rag_core.py::make_plan` — adaptive top_k.
- `rag_core.py::reassemble_parent_sections` — hierarchical-mode wiring.
- `rag_core.py::summarize_stage_attempt` — per-stage diagnostics.
- `eval/run_eval.py::score_case` / `metric_block` — eval metric.
- `tests/test_fuzzy_retrieval.py::BalancedComparisonRerankTest` — coverage tests.
