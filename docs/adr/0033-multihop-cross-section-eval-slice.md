# 0033: Multi-hop cross-section eval slice as orthogonal saturation falsifier

- **Status**: proposed
- **Date**: 2026-05-13
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (naive_baseline invariant), [ADR 0002](./0002-metadata-first-retrieval.md) (metadata-first context), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) (public/private eval split), [ADR 0010](./0010-hybrid-bm25-dense-retrieval-rrf.md) (hybrid BM25 retrieval), [ADR 0019](./0019-embedding-default-stays-minilm.md) (embedding default lock), [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) (Phase 1.3 closure), [ADR 0032](./0032-eval-saturation-routed-subset.md) (saturation falsifier — routed axis), issue #533

## Context

[ADR 0032](./0032-eval-saturation-routed-subset.md) addresses the
**routing axis** of the saturation hypothesis: metadata-first filtering
bypasses dense retrieval for the majority of public synthetic queries,
making embedding-level spreads unmeasurable on the default `full`
pipeline. The `agentic_full_routed` preset (`metadata_first: false`)
turns that axis into a real measurement surface.

There is a **second, orthogonal saturation axis**: query complexity.
The public synthetic n=42 surface contains predominantly *single-hop*
queries — questions whose answer is locatable in a single contiguous
chunk or section. For single-hop queries, all five tested embeddings
can reach the same top-k chunk given adequate BM25 / hybrid fallback,
so correctness metrics saturate regardless of embedding quality. This
axis is independent of whether metadata-first routing runs:

- A routed-subset query (`metadata_first: false`) can still be
  single-hop if the answer lives in one chunk.
- A metadata-first query can still be multi-hop if the answer requires
  synthesizing evidence from ≥ 2 sections or documents (though
  retrieval routing in that case is already forced by the `full`
  pipeline's evidence aggregation stage).

**Multi-hop queries** — where the correct answer requires combining
evidence from ≥ 2 non-contiguous sections or documents — force the
retrieval and aggregation stages to work harder:

1. The dense vector must surface both relevant sections (not just the
   nearest neighbour).
2. The verifier must ground a claim that no single chunk fully
   supports.
3. The answer builder must synthesize across multiple
   `evidence_text` spans.

If ablation rows show ≥ +5pp spread on multi-hop queries but ≈ 0pp on
the single-hop surface, the saturation is *query-complexity-driven*
(and the single-hop surface is an insufficient discriminator). If both
surfaces show ≈ 0pp, the system is genuinely robust across the ablation
matrix and the 0pp finding is *not* an artifact of query design — which
is a publishable positive result.

**Connection to ADR 0032**: the two saturation falsifiers are designed
to be run *together*. ADR 0032 falsifies the routing axis; ADR 0033
falsifies the complexity axis. A maintainer reading both results will
know whether the 0pp pattern is routing-driven, complexity-driven,
both, or neither — the four quadrants of the saturation hypothesis.

## Decision

Add a **50-item multi-hop cross-section synthetic eval subset** as a
separate measurement slice. The slice is additive: existing eval config,
`naive_baseline` golden, and ADR 0001/0003/0005 invariants are
untouched.

### Scope of this ADR (decision record only)

This ADR documents the decision and acceptance criteria. The
implementation artifacts are separate follow-up work:

- `scripts/synthesize_multihop_queries.py` — synthesis script
  (follow-up issue; not in this PR)
- `eval/dev_queries_multihop_v1.jsonl` — 50-item synthesized dataset
  (follow-up issue)
- `eval/config.yaml` change to add the multi-hop eval slice
  (load-bearing; requires real-eval-delta in that PR's item 5b)

### Query synthesis strategy

Three query types cover distinct multi-hop patterns:

1. **Cross-section within a document** — the answer requires combining
   a condition stated in §2 with a value stated in §5 of the same RFP.
   Example: "입찰 참여 기준 금액이 충족될 경우 보증금 납부 방식은?"
   (condition in §입찰 조건, value in §계약 보증금).

2. **Cross-document comparison** — the answer requires comparing the
   same field (e.g. 계약 기간) across ≥ 2 distinct RFP documents.
   Already partially covered by the `comparison` query type in
   `eval/config.yaml`, but the existing comparison slice may not
   *require* ≥ 2 chunks to answer correctly — new multi-hop queries
   must be validated to reject single-chunk answers.

3. **Multi-step conditional reasoning** — the answer is only reachable
   by following a chain: "X applies when Y, and Y is defined as Z in
   §3". Each step is retrievable individually but the correct answer
   requires the chain.

### LLM-judge quality filter

Synthesized queries go through the LLM judge
(`eval/synthetic_judge.py` / `eval/llm_judge.py`) with a custom
`multihop_valid` rubric that **rejects** any query answerable from a
single chunk. Only queries with `multihop_valid: true` enter
`eval/dev_queries_multihop_v1.jsonl`. The judge prompt is logged
alongside the dataset for reproducibility.

### Measurement surface

- Eval config: a separate `eval/multihop_config.yaml` mirroring the
  pattern of `eval/routed_config.yaml` (ADR 0032 Step 1).
- Ablation rows: at minimum `naive_baseline`, `agentic_full`,
  `agentic_full_routed` (the ADR 0032 surface, for cross-axis
  comparison), and the 5 embedding candidates from ADR 0019/0021.
- Backend: sentence-transformers (real embeddings); hashing backend
  not meaningful for multi-hop spread measurement.
- Metrics reported: `accuracy`, `groundedness`, `citation_precision`
  + bootstrap 95% CIs (same surface as ADR 0032).

### Acceptance criteria

| Outcome | Interpretation | ADR consequence |
|---|---|---|
| Spread ≥ +5pp across ablation rows on multi-hop slice | Complexity axis is a real discriminator; single-hop surface was complexity-saturated | ADR 0019 re-open condition amended: multi-hop slice required in addition to routed subset |
| Spread ≥ +5pp only when combined with ADR 0032 routed surface | Both axes needed simultaneously | ADR 0019 re-open condition amended to require *both* surfaces |
| Spread < 5pp on multi-hop slice (both routing modes) | System genuinely robust; saturation is not query-complexity-driven | ADR 0033 closes as `accepted` with negative result; single-hop surface declared sufficient for embedding comparison |

All three outcomes are published in the `docs/embedding-ablation.md`
Phase 1.4 section regardless of direction. A negative result (spread
< 5pp on multi-hop) is the most interpretable outcome — it confirms
the 0pp finding is a real property of the architecture, not an
eval-design artifact.

### ADR 0001 / 0005 preservation

- `eval/config.yaml` is not modified in this PR. The multi-hop slice
  lives in a separate `eval/multihop_config.yaml` (additive, opt-in,
  same pattern as `eval/routed_config.yaml`).
- `naive_baseline` golden bytes are not modified.
- The multi-hop dataset is *synthetic* (generated from the same
  public-domain RFP fixtures), so it stays within the ADR 0005
  public synthetic surface. No private data used.
- CI continues to use `EMBEDDING_BACKEND=hashing` for the deterministic
  public surface; multi-hop real-embedding runs are opt-in local only
  (same as ADR 0032 measurement runs).

## Consequences

**Wins**

- Adds the second orthogonal saturation-falsifier axis. Together with
  ADR 0032, this lets a reader determine whether 0pp on `full` is
  routing-driven, complexity-driven, or neither.
- Multi-hop synthesis is itself a portfolio signal: cross-section query
  construction + LLM-judge filter demonstrates understanding of
  *what makes a good eval discriminator* — not just running models.
- Negative result (spread < 5pp) is publishable: it means the pipeline
  is genuinely robust to query complexity in the tested range, which
  strengthens the ADR 0002 metadata-first design story.

**Costs**

- 50-item synthesis requires running the LLM judge for filtering
  (~50 API calls; one-time cost, dataset committed and not regenerated
  in CI).
- `eval/multihop_config.yaml` adds a second parallel config file to
  maintain (same maintenance pattern as `eval/routed_config.yaml`).
- Measurement requires real embeddings (sentence-transformers), not
  CI hashing backend. Results are private-run artifacts published to
  `docs/embedding-ablation.md` — same pattern as ADR 0021 Phase 1.3
  results.

**Constraints (unchanged)**

- ADR 0001: `naive_baseline` invariant preserved.
- ADR 0003: answer/citation contract unchanged.
- ADR 0005: dataset stays public synthetic (generated, not from
  private RFP data).

## Relationship to ADR 0032

| | ADR 0032 | ADR 0033 |
|---|---|---|
| **Saturation axis falsified** | Routing (metadata_first bypasses dense retrieval) | Complexity (single-hop queries don't discriminate embeddings) |
| **Mechanism** | `agentic_full_routed` preset (`metadata_first: false`) | Multi-hop 50-item dataset (forces ≥2 chunk synthesis) |
| **Config** | `eval/routed_config.yaml` | `eval/multihop_config.yaml` (follow-up) |
| **ADR 0001 impact** | None | None |
| **Dependency** | Independent | Independent; recommended to run both simultaneously |

## Alternatives considered

- **Extend the existing `eval/dev_queries_v1.jsonl` with multi-hop
  items.** Rejected: the existing dataset is the public-CI surface
  whose golden bytes are pinned. Adding multi-hop items there changes
  the golden and requires a `schema_version` bump. A separate
  `dev_queries_multihop_v1.jsonl` is additive.
- **Use the `comparison` query type already in `eval/config.yaml`
  as the multi-hop proxy.** Rejected: the comparison slice measures
  multi-document *metadata* comparison (e.g. 두 사업의 계약 기간
  비교), but does not require combining ≥ 2 non-contiguous evidence
  spans within the pipeline — a lookup of the same column in two
  documents can be answered with two single-hop calls. The multi-hop
  definition here requires the *answer* to be non-constructible from
  any single chunk.
- **50 items is too few; use 200.** Counter: ADR 0032 uses n ≥ 10 for
  the routed subset because the primary signal is presence of spread,
  not magnitude estimation. 50 items provides enough power to detect
  ≥ 5pp spread (≈ 2.5 items in absolute terms at n=50) while keeping
  synthesis cost manageable. If the initial 50-item run shows
  borderline results, a follow-up can extend to 100.
- **Skip LLM-judge filtering; include all synthesized queries.**
  Rejected: without the `multihop_valid` filter, single-hop queries
  (which are easier to auto-generate) would dilute the multi-hop
  signal. The filter is the mechanism that makes the dataset's
  "multi-hop" label trustworthy.

## See also

- [ADR 0032](./0032-eval-saturation-routed-subset.md) — the companion
  routing-axis saturation falsifier.
- [ADR 0019](./0019-embedding-default-stays-minilm.md) + [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) —
  the embedding default lock whose re-open conditions this ADR
  supplements.
- [`eval/routed_config.yaml`](../../eval/routed_config.yaml) — pattern
  this ADR's `eval/multihop_config.yaml` will follow (follow-up PR).
- [`eval/synthetic_judge.py`](../../eval/synthetic_judge.py) /
  [`eval/llm_judge.py`](../../eval/llm_judge.py) — the LLM-judge
  infrastructure the quality-filter will reuse.
- `eval/dev_queries_multihop_v1.jsonl` — follow-up PR artifact.
- `scripts/synthesize_multihop_queries.py` — follow-up PR script.
- `docs/embedding-ablation.md` — Phase 1.4 section where results will
  be published.
