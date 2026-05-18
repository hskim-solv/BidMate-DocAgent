# 0058: Phase 3.5 mode-winner decision — BGE-M3 multi-channel vs dense vs BM25-hybrid on real100

- **Status**: proposed (finalize after kordoc-corpus measurement lands)
- **Date**: 2026-05-18
- **Deciders**: hskim
- **Related**: [ADR 0001](0001-preserve-naive-baseline.md), [ADR 0010](0010-hybrid-bm25-dense-retrieval-rrf.md), [ADR 0021](0021-real-eval-axis-design.md), [ADR 0025](0025-spike-mode-m3-channels.md), [ADR 0032](0032-torch-26-unblock.md), [ADR 0049](0049-kordoc-replaces-pyhwp-backend.md), PR #966 (Phase 3.5 measurement), PR #956 (Phase 3, retracted), issue #957

> **ADR number renumbered 0056 → 0057 → 0058** (2026-05-19) to avoid two concurrent collisions: ADR 0056 was merged via PR #987 (`rationality_judge`, issue #969) + ADR 0057 was merged via PR #988 (`bm25s additive backend`). Final number `0058` per ADR README.md "Reserve the next number with the CLI before drafting" convention.

## Context

ADR 0010 (2026-05-11) accepted `retrieval_backend ∈ {dense, hybrid}` with `dense` as the default and noted that BGE-M3 multi-channel (sparse + colbert) was deferred to its own ablation. Real-data measurement of the hybrid knob was blocked by ADR 0032 (torch≥2.6 install) until 2026-05-13. Phase 3 (PR #956) was the first real-data measurement; Phase 3.5 (PR #966) added BGE-M3 as the third arm.

The first two attempts produced misleading evidence. Phase 3 (PR #956) reported all three `hybrid_bm25_k{30,60,100}` variants byte-identical and attributed the flatness to BM25 channel dominance. That conclusion was wrong — the Phase 3 runner called `retrieve_candidates` (candidate generation only) without the second-stage `apply_fusion_and_reranking`, so the per-case ranking collapsed to chunk_id insertion order for the hybrid and m3 backends (placeholder score = 0.0). Phase 3.5 (PR #966) fixed the runner wire-up but used `--src data/data_list.csv` for the index build, which routed through the CSV `text`-column loader and produced an 898-chunk corpus instead of the 26,376-chunk kordoc-extracted corpus that Phase 3 used. That measurement is internally valid (3 variants share the same 898-chunk corpus, paired CI deltas are unbiased) but the absolute `chunk_recall@k` numbers cannot be compared to Phase 3 and the chunk-count caveat dominated the REPORT.md Notes.

This ADR's evidence is the kordoc-rebuilt re-measurement: same 100 docs, same chunking strategy (`fixed`, `max_chars=520`, `overlap_sentences=1`), same chunking config Phase 3 used, but now over the BGE-M3 1024-dim semantic embeddings with the `apply_fusion_and_reranking` wire-up fixed. The retraction history is preserved in PR #966's REPORT.md Notes and in this ADR's Context to keep the audit trail honest (absolute rule #5).

## Decision

<!-- FINALIZE: pick scenario A or B based on kordoc measurement results landing in
     reports/retrieval/phase35_m3_<TS>_kordoc/REPORT.md -->

**Scenario A — kordoc measurement shows SIG hybrid or m3 lift on recall@10 + MRR**:
> Switch `retrieval_backend` default from `dense` to `hybrid` (RRF k=60 over BGE-M3 dense + BM25). Preserve `ADR 0001` `naive_baseline` byte-identical by leaving the `naive_baseline` preset on `dense`; the default change applies only to `agentic_full` and `metadata_first`. `m3` (3-way RRF over BGE-M3 dense + sparse + colbert) remains opt-in for research-scale workloads (2.2x latency vs hybrid).

**Scenario B — recall@10 NULL WINNER + partial SIG MRR on multi_hop (csv_text result pattern)**:
> Keep `retrieval_backend: dense` default per ADR 0010 (default validated, not contradicted by measurement). Document `hybrid_bm25_k60` as a measured-positive ranking-quality knob for multi_hop-heavy workloads (paired CI MRR multi_hop +X SIG; 1.2x latency vs dense). `m3` is NOT recommended for production — partial MRR lift + 2.2x latency does not justify the operational cost (~10GB colbert cache, FlagEmbedding opt-in dep).

In both scenarios the production knob `retrieval_backend` remains the single point of swap. The default `naive_baseline` preset stays `dense` regardless of scenario.

## Consequences

**Scenario A wins** (default switches to `hybrid`):
- README must update default-mode framing; `eval/config.yaml` `agentic_full` preset annotation flips
- BM25 dependency (`rank_bm25`) becomes load-bearing for production (was already in `requirements.txt` so install footprint unchanged)
- Latency budget: ~1.2x dense at p50 (~853 vs ~699 ms on the csv_text 898-chunk measurement; kordoc 26k may differ)

**Scenario B wins** (default stays `dense`):
- ADR 0010's default validated by measurement (the gauge ADR 0010 promised has now fired)
- `hybrid_bm25_k60` documented as a per-route knob for multi_hop-heavy workloads — README "When to use" section gains an entry
- `m3` formally moves from "deferred" to "tested-and-rejected for prod" status (still available for research)

**Both scenarios lock**:
- The `apply_fusion_and_reranking` wire-up in any future ablation runner — Phase 3 PR #956 bug must not recur (PR-H optional retraction note proposed)
- The kordoc-as-source-of-truth convention for `data/index/real100_m3` (no csv_text fallback for production semantic indexes)
- The runner-side m3 colbert batching pattern (`scripts/phase35_m3_ablation.py::_prime_m3_index_cache_and_colbert`) for future m3-channel measurements on Apple Silicon

## Alternatives considered

- **Switch default to `m3` (3-way RRF)** — Rejected. Even if `m3` shows the strongest SIG lift on some categories, the 2.2x latency vs dense and the ~10GB colbert cache footprint do not justify production deployment for the modest measured gain. Research opt-in only.
- **Defer the decision pending corpus expansion** — Rejected. 100-doc real100 is the production target corpus today; future corpus expansion (ADR 0050 / 0052 trajectory) can re-open the question with its own ablation. Deferring would leave ADR 0010's "deferred" status permanently in limbo.
- **Re-run on Phase 3's hashing index instead of BGE-M3** — Rejected as a substitute for this ADR (PR-H tracks the retraction note separately). Hashing's score-collision behavior is a different question; the Phase 3.5 axis is "does the production semantic embedding change the answer?"

## Verification

<!-- verifies-key: reports/retrieval/phase35_m3_20260518T??????Z_kordoc/REPORT.md:Per-category winner -->
<!-- verifies-key: docs/adr/0010-hybrid-bm25-dense-retrieval-rrf.md:BGE-M3 ablation closeout -->
<!-- verifies-key: eval/config.yaml:retrieval_backend -->

The Per-category winner section of the kordoc-corpus REPORT.md is the load-bearing evidence for this decision. ADR 0010 must gain a closeout section pointing back here (PR-G). `eval/config.yaml` must reflect the scenario A or B default explicitly (annotation or value change). The `scripts/_governance.py --lint-adr-consequences` linter will flag this ADR if the referenced files lose the keyed sections.
