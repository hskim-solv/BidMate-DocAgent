# 0026: Cross-encoder reranker default stays stub-identity; real-backend measurement deferred

- **Status**: Superseded
- **Superseded by**: [ADR 0025](./0025-cost-frontier-defer-until-real-baselines.md) § "Cross-encoder reranker deferral"
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (baseline preserved), [ADR 0002](./0002-metadata-first-retrieval.md) (the metadata-first routing that shadows the rerank step), [ADR 0019](./0019-embedding-default-stays-minilm.md) (mirror pattern — measurement-gated default-stays), [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) (the deferred-then-closed loop precedent), [ADR 0025](./0025-cost-frontier-defer-until-real-baselines.md) (sibling deferral pattern, accepted 2026-05-12), [`docs/retrieval/cross-encoder-reranker.md`](../retrieval/cross-encoder-reranker.md) (working reference), [`docs/eval/ablation-results.md`](../eval/ablation-results.md) (current ablation table), [`rag_reranker.py`](../../rag_reranker.py) (`Reranker` Protocol + `CrossEncoderReranker` default), issues [#163](https://github.com/hskim-solv/BidMate-DocAgent/issues/163), [#345](https://github.com/hskim-solv/BidMate-DocAgent/issues/345), [#412](https://github.com/hskim-solv/BidMate-DocAgent/issues/412), PR [#358](https://github.com/hskim-solv/BidMate-DocAgent/pull/358)

## Context

Three retrieval-side surfaces interact with the reranking question and
each is in a different state of measurement:

1. **`rerank: true` blend** (the 60/25/15 dense + lexical + metadata
   blend in [`rag_core.retrieve`](../../rag_core.py)) — present on the
   `full` ablation preset.
2. **`Reranker` Protocol + `CrossEncoderReranker` default**
   ([`rag_reranker.py`](../../rag_reranker.py), introduced by issue
   [#345](https://github.com/hskim-solv/BidMate-DocAgent/issues/345)
   / PR [#358](https://github.com/hskim-solv/BidMate-DocAgent/pull/358))
   — consumed by [`rag_retrieval.apply_fusion_and_reranking`](../../rag_retrieval.py) (extracted from `rag_core.py` in PR-H1a, issue #459)
   only when `plan["rerank_cross_encoder"]` is set. Surfaced as the
   `full_reranker` preset in [`eval/config.yaml`](../../eval/config.yaml)
   `line 143-149` (`rerank: true` + `rerank_cross_encoder: true`).
3. **Cross-encoder backends** (`bge`, `bge_ko`, `cohere`) selected via
   `BIDMATE_RERANK_BACKEND`. CI default is `stub` —
   [`docs/retrieval/cross-encoder-reranker.md`](../retrieval/cross-encoder-reranker.md)
   describes the dispatch and explicitly states: *"`full_reranker` row
   byte-equals `full` under stub"* (line 25). Stub is a pure-identity
   pass-through; the test
   `tests/test_cross_encoder_rerank.py::RerankStubBackendTest::test_stub_backend_is_identity`
   locks this invariant.

The current ablation table ([`docs/eval/ablation-results.md`](../eval/ablation-results.md))
shows that on the public synthetic surface (n=42), the **first** surface
already moves 0pp:

| Run | Accuracy | Groundedness | Citation precision | Abstention |
|---|---:|---:|---:|---:|
| `full` (rerank on, blend only) | 0.906 | 0.929 | 0.905 | 1.000 |
| `no_rerank` (rerank off entirely) | 0.906 | 0.929 | 0.905 | 1.000 |

Three observations follow:

- **The `rerank: true` blend has zero measured quality lift over
  `no_rerank` on this surface.** Hypothesis (consistent with
  [ADR 0002](./0002-metadata-first-retrieval.md) and the `0pp-on-full`
  pattern documented in [ADR 0019](./0019-embedding-default-stays-minilm.md)):
  metadata-first filtering routes around dense retrieval for most
  queries, leaving very little for a post-retrieval reorder to
  improve.
- **`full_reranker` under stub is byte-identical to `full` by
  construction**, not by empirical accident. The 0 delta there is an
  architectural invariant, not a measurement finding.
- **No real cross-encoder backend has been measured on this repo's eval
  surface.** [`docs/retrieval/cross-encoder-reranker.md`](../retrieval/cross-encoder-reranker.md)
  §Results closes with *"Measurement pending — append below after
  running the reproduction commands."* The `bge` / `bge_ko` / `cohere`
  commands ship but the runs require user-environment setup (model
  download or API key) that has not been performed.

So the question this ADR closes is: *given (a) the blend already shows
0 lift, (b) cross-encoder under stub is identity by design, and (c)
real backends are unmeasured, should the `Reranker` Protocol surface
and `CrossEncoderReranker` default stay in the codebase?* The
measurement-gated deferral pattern from [ADR 0019](./0019-embedding-default-stays-minilm.md)
→ [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) and sibling
[ADR 0025](./0025-cost-frontier-defer-until-real-baselines.md) applies
naturally here: lock the decision now, document the re-open conditions
that would flip the default to a real backend.

[ADR 0023](./0023-hyde-query-expansion-ablation.md) (proposed)
already cross-references [ADR 0020](./0020-protocol-based-pluggability.md)
(proposed, skeleton-only) for the convention these Protocols follow;
this ADR is downstream of both — it decides the **default behaviour**
within the convention, not the convention itself.

## Decision

Keep the `Reranker` Protocol surface and `CrossEncoderReranker` default
in [`rag_reranker.py`](../../rag_reranker.py); keep
`BIDMATE_RERANK_BACKEND=stub` (identity) as the CI default so
`full_reranker ≡ full` by construction. Do **not** remove the rerank
seam despite the 0pp synthetic delta — real backends are unmeasured
and the Protocol is the seam for HyDE-reranker / LLM-as-reranker
follow-ups.

Knobs locked by this decision:

- [`eval/config.yaml`](../../eval/config.yaml) preset rows stay in the
  matrix: `full` (`rerank: true`), `no_rerank` (`rerank: false`), and
  `full_reranker` (`rerank: true` + `rerank_cross_encoder: true`).
- `BIDMATE_RERANK_BACKEND` env-var dispatches `stub` (CI default) |
  `bge` | `bge_ko` | `cohere`. Default stays `stub` until a re-open
  condition fires.
- `default_reranker()` factory in [`rag_reranker.py`](../../rag_reranker.py)
  remains the single dispatch hook — future LLM-as-reranker /
  HyDE-reranker implementations swap the adapter, not the seam.

Boundary clarification: this ADR decides the **default behaviour**
inside the Protocol convention introduced by
[ADR 0020](./0020-protocol-based-pluggability.md). It does *not*
re-decide whether the Protocol itself should exist — that is
ADR 0020's territory.

## Re-open conditions

Following the gate pattern from
[ADR 0019](./0019-embedding-default-stays-minilm.md) and sibling
[ADR 0025](./0025-cost-frontier-defer-until-real-baselines.md), this
ADR re-opens — and the `stub` default flips — when **all three** hold:

1. A maintainer runs at least one of the `bge` / `bge_ko` / `cohere`
   backends to completion against the public synthetic eval surface
   (n=42) and appends the result table to
   [`docs/retrieval/cross-encoder-reranker.md`](../retrieval/cross-encoder-reranker.md)
   §Results.
2. **At least one** of those backends shows a `full_reranker` lift of
   **≥ +3pp** on `accuracy` OR `citation_precision`, with
   non-overlapping bootstrap 95% CIs vs. `full` on the public
   synthetic surface. X = 3 is intentional: relaxed below
   [ADR 0019](./0019-embedding-default-stays-minilm.md)'s "≥ +5pp on
   full" gate because a precision-targeted post-retrieval reorder can
   be a portfolio signal at a smaller absolute lift than an embedding
   swap.
3. A follow-up ADR (numbered `002x` or higher) is opened to flip the
   `BIDMATE_RERANK_BACKEND` default from `stub` to the winning
   backend, documenting the latency / cost trade-off (~80-200ms /
   query CPU for `bge`, ~$2 / 1k searches for `cohere` per
   [`docs/retrieval/cross-encoder-reranker.md`](../retrieval/cross-encoder-reranker.md)).

If condition 1 lands but condition 2 does not (the 0pp pattern holds
across real backends too), this ADR stays `accepted` and
[`docs/retrieval/cross-encoder-reranker.md`](../retrieval/cross-encoder-reranker.md)
§Results gets the measurement appendix without an ADR replacement —
same loop shape as [ADR 0019](./0019-embedding-default-stays-minilm.md)
→ [ADR 0021](./0021-bge-m3-completes-phase-1-3.md).

## Consequences

**Wins**

- Future LLM-as-reranker / HyDE-reranker plugs into the same Protocol
  without re-litigating the seam —
  [`rag_reranker.py`](../../rag_reranker.py) stays the single swap
  point.
- `full` / `no_rerank` / `full_reranker` ablation rows in
  [`eval/config.yaml`](../../eval/config.yaml) stay aligned; the
  senior-positioning narrative has a concrete "additive ablation"
  example that extends [ADR 0001](./0001-preserve-naive-baseline.md).
- The stub-identity invariant preserves CI determinism — adopting a
  real backend is opt-in per environment, never a CI-default flip.
  The byte-equality test
  `tests/test_cross_encoder_rerank.py::RerankStubBackendTest::test_stub_backend_is_identity`
  locks this.
- Reviewer-facing honesty: the "0 delta on synthetic" framing is now
  ADR-backed (no fabricated lift), and the unmeasured real backends
  surface as a re-open trigger rather than a hidden todo.

**Costs**

- Maintenance cost for an unused real-backend code path (the BGE /
  Cohere dispatch inside [`rag_rerank.py`](../../rag_rerank.py)).
  Mitigated by the never-raise fallback contract — `stub` is the
  always-safe path and any unknown / failing backend silently degrades
  to identity.
- A reviewer who asks "you have a cross-encoder reranker but it does
  nothing?" gets a nuanced answer ("identity under CI default, real
  backends unmeasured") rather than a single sentence. The Context
  section above carries the supporting evidence.
- The decision can be misread as "rerankers don't matter" rather than
  "rerankers don't matter *on this corpus under stub*". Mitigation:
  the re-open conditions name the corpus (public synthetic, n=42) and
  the backends (`bge` / `bge_ko` / `cohere`) explicitly.

## Alternatives considered

1. **Remove the `Reranker` Protocol entirely (rollback PR
   [#358](https://github.com/hskim-solv/BidMate-DocAgent/pull/358)).**
   The Protocol is the seam future LLM-as-reranker / HyDE work plugs
   into. Removing it would re-fragment retrieval-side pluggability —
   the convention codified in
   [ADR 0020](./0020-protocol-based-pluggability.md) — for no
   measurement gain on this surface. Net loss.
2. **Flip `BIDMATE_RERANK_BACKEND` default to `bge_ko`
   unconditionally.** No measurement exists yet; defaulting to a real
   backend would force every CI run to download ~1.1 GB and pay
   ~80-200ms / query, all without empirical justification.
   [ADR 0019](./0019-embedding-default-stays-minilm.md)'s "no default
   flip without ≥ +Xpp evidence" rule applies the same way here.
3. **Default to identity reranker (= remove `rerank_cross_encoder`
   from `full_reranker`).** The `full_reranker` preset exists *for*
   exercising the cross-encoder path. Removing the flag collapses
   `full_reranker` into `full` and erases the ablation surface — the
   opposite of what an additive-ablation regime (extends
   [ADR 0001](./0001-preserve-naive-baseline.md)) is for.
4. **Switch to a different cross-encoder model
   (`BAAI/bge-reranker-large`,
   `mixedbread-ai/mxbai-rerank-large-v1`).** Out of scope. This ADR
   decides whether to keep the surface, not which model belongs as
   default. Once a real-backend measurement lands (re-open
   condition 1), a follow-up ADR can address model choice without
   re-litigating the seam.
5. **Run the real-backend measurement now (close issue
   [#163](https://github.com/hskim-solv/BidMate-DocAgent/issues/163)
   fully in this ADR).** The measurement requires ~1.1 GB of model
   downloads (`bge`) or a Cohere API key (`cohere`), neither of which
   is on a docs-PR's critical path. Documenting the deferral first
   and measuring later is the same loop shape as
   [ADR 0019](./0019-embedding-default-stays-minilm.md) →
   [ADR 0021](./0021-bge-m3-completes-phase-1-3.md).

## See also

- [`docs/retrieval/cross-encoder-reranker.md`](../retrieval/cross-encoder-reranker.md) — design + reproduction commands; the doc this ADR locks the *decision* behind.
- [`docs/eval/ablation-results.md`](../eval/ablation-results.md) — `full` vs `no_rerank` numbers cited above.
- [`rag_reranker.py`](../../rag_reranker.py) — `Reranker` Protocol surface and `CrossEncoderReranker` default.
- [`tests/test_cross_encoder_rerank.py`](../../tests/test_cross_encoder_rerank.py) — the stub-identity invariant tests.
- [ADR 0019](./0019-embedding-default-stays-minilm.md) → [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) — the measurement-gated deferral pattern this ADR follows.
- [ADR 0025](./0025-cost-frontier-defer-until-real-baselines.md) — sibling deferral ADR (same date, same pattern).
