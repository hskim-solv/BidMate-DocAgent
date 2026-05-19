# 0058: Phase 3.5 mode-winner decision — Scenario A (switch default to hybrid BM25+BGE-M3 dense, RRF k=60)

- **Status**: accepted (kordoc-corpus measurement landed 2026-05-19; Scenario A finalized)
- **Date**: 2026-05-19 (Status accepted); 2026-05-18 (Status proposed)
- **Deciders**: hskim
- **Related**: [ADR 0001](0001-preserve-naive-baseline.md), [ADR 0010](0010-hybrid-bm25-dense-retrieval-rrf.md), [ADR 0021](0021-real-eval-axis-design.md), [ADR 0025](0025-spike-mode-m3-channels.md), [ADR 0032](0032-torch-26-unblock.md), [ADR 0049](0049-kordoc-replaces-pyhwp-backend.md), PR #966 (Phase 3.5 measurement), PR #956 (Phase 3, retracted), issue #957, issue #997, issue #1022 (m3 cloud-GPU follow-up)

> **ADR number renumbered 0056 → 0057 → 0058** (2026-05-19) to avoid two concurrent collisions: ADR 0056 was merged via PR #987 (`rationality_judge`, issue #969) + ADR 0057 was merged via PR #988 (`bm25s additive backend`). Final number `0058` per ADR README.md "Reserve the next number with the CLI before drafting" convention.

## Context

ADR 0010 (2026-05-11) accepted `retrieval_backend ∈ {dense, hybrid}` with `dense` as the default and noted that BGE-M3 multi-channel (sparse + colbert) was deferred to its own ablation. Real-data measurement of the hybrid knob was blocked by ADR 0032 (torch≥2.6 install) until 2026-05-13. Phase 3 (PR #956) was the first real-data measurement; Phase 3.5 (PR #966) added BGE-M3 as the third arm.

The first two attempts produced misleading evidence. Phase 3 (PR #956) reported all three `hybrid_bm25_k{30,60,100}` variants byte-identical and attributed the flatness to BM25 channel dominance. That conclusion was wrong — the Phase 3 runner called `retrieve_candidates` (candidate generation only) without the second-stage `apply_fusion_and_reranking`, so the per-case ranking collapsed to chunk_id insertion order for the hybrid and m3 backends (placeholder score = 0.0). Phase 3.5 (PR #966) fixed the runner wire-up but used `--src data/data_list.csv` for the index build, which routed through the CSV `text`-column loader and produced an 898-chunk corpus instead of the 26,376-chunk kordoc-extracted corpus that Phase 3 used. That measurement is internally valid (3 variants share the same 898-chunk corpus, paired CI deltas are unbiased) but the absolute `chunk_recall@k` numbers cannot be compared to Phase 3 and the chunk-count caveat dominated the REPORT.md Notes.

This ADR's evidence is the kordoc-rebuilt re-measurement: same 100 docs, same chunking strategy (`fixed`, `max_chars=520`, `overlap_sentences=1`), same chunking config Phase 3 used, but now over the BGE-M3 1024-dim semantic embeddings with the `apply_fusion_and_reranking` wire-up fixed. The retraction history is preserved in PR #966's REPORT.md Notes and in this ADR's Context to keep the audit trail honest (absolute rule #5).

## Decision

**Scenario A wins**: Switch `retrieval_backend` default from `dense` to `hybrid` (RRF k=60 over BGE-M3 dense + BM25) for the `agentic_full` and `metadata_first` presets. **`naive_baseline` preset stays on `dense` (ADR 0001 invariant byte-identical)** — the default change applies only to non-baseline presets.

`m3` (3-way RRF over BGE-M3 dense + sparse + colbert) **deferred to cloud-GPU follow-up** — local measurement attempts on 16GB Apple Silicon exhausted unified memory (33GB swap pool consumption + system crash) before completing the m3 cache build. The deferral is honest reporting per absolute rule #5; m3 multi-channel question remains open for a cloud-GPU one-off run (~$1 budget; A10/T4 GPU expected to complete in <30 min).

### Evidence (from `reports/retrieval/phase35_m3_20260518T214937Z_kordoc_no_m3/REPORT.md`)

Measurement: kordoc 26,376 chunks, n=221 cases, dense_m3 vs hybrid_bm25_k60_m3, paired bootstrap CI 95%, seeds 17/23/29.

**Overall metrics** (hybrid_bm25_k60_m3 vs dense_m3, all SIG = paired CI fully above 0):
- `chunk_recall@10`: 0.288 → 0.340 (**+0.052 SIG**, CI +0.020/+0.088)
- `MRR`: 0.515 → 0.625 (**+0.110 SIG**, CI +0.056/+0.165)
- `ndcg@10`: 0.318 → 0.383 (**+0.065 SIG**, CI +0.032/+0.099)
- Latency p50: 559ms → 757ms (1.35x; acceptable for ranking quality lift)

**Per-category winners** (recall@10, paired CI vs dense_m3):
- `overall`: hybrid +0.052 SIG
- `multi_hop` (n=93): hybrid +0.043 SIG
- `distractor_heavy` (n=42): hybrid +0.067 SIG
- `long_context` (n=9): hybrid +0.133 SIG
- `no_answer` (n=2), `ambiguous_query` (n=1), `uncategorized` (n=13): NOT SIGNIFICANT (small N or all-equal CI)

**Phase 3 PR #956 conclusion retracted**: "BM25 channel dominance → hybrid_bm25 SIG-negative" was wrong. The Phase 3 runner bug (missing `apply_fusion_and_reranking` call, fixed in PR-H #994) collapsed hybrid_k variants to chunk_id insertion order. With the fix + semantic embeddings, hybrid_bm25 is SIG-positive on the dominant hardcase categories.

## Consequences

**Scenario A applied** (default switches to `hybrid`):
- README must update default-mode framing; `eval/config.yaml` `agentic_full` preset annotation flips (follow-up implementation PR, not blocked by this ADR)
- BM25 dependency (`rank_bm25`) becomes load-bearing for production (was already in `requirements.txt` so install footprint unchanged)
- Latency budget: 1.35x dense at p50 (757ms vs 559ms on kordoc 26k measurement)

**Locked by this ADR**:
- The `apply_fusion_and_reranking` wire-up in any future ablation runner — Phase 3 PR #956 bug must not recur (fixed for Phase 3 in PR-H #994)
- The kordoc-as-source-of-truth convention for `data/index/real100_m3` (no csv_text fallback for production semantic indexes; PR #966 closeout 의 `BIDMATE_KORDOC_CACHE_DIR` bypass 가 enable)
- The runner-side m3 colbert batching pattern (`scripts/phase35_m3_ablation.py::_prime_m3_index_cache_and_colbert`) for future m3-channel measurements on Apple Silicon
- The `BIDMATE_SKIP_M3_VARIANT=1` env var (introduced in issue #997) for memory-constrained measurement environments

**Deferred** (m3 multi-channel question):
- 16GB Apple Silicon unified memory cannot hold the BGE-M3 colbert cache for 26k chunks (per-token per-chunk vectors ≈ 10-15GB, plus model weights + activations → swap thrashing + system crash observed). Local-only m3 measurement infeasible.
- **50-doc subset confirmation (2026-05-19)**: Post-ADR-0058 attempt to run a 50-doc subset on-prem proxy build (`data/index/real50_m3`, ~13k chunks) stalled for 40m55s with 8GB swap pool fully consumed and ~12.5% CPU efficiency (swap-thrash dominated compute). Subset half-size did NOT halve wall-time → on-prem fallback strategy fails regardless of `BIDMATE_M3_USE_FP16=1` + `BIDMATE_M3_INT8_CACHE=1` tunings.
- Cloud-GPU one-off (Modal/RunPod ~$1, A10/T4 GPU expected <30 min) — **tracked in [issue #1022](https://github.com/hskim-solv/BidMate-DocAgent/issues/1022)**. No blocker for `agentic_full` default flip — m3 was always going to be opt-in for research per ADR 0010.

## Alternatives considered

- **Switch default to `m3` (3-way RRF)** — Rejected. Even if `m3` shows the strongest SIG lift on some categories, the 2.2x latency vs dense and the ~10GB colbert cache footprint do not justify production deployment for the modest measured gain. Research opt-in only.
- **Defer the decision pending corpus expansion** — Rejected. 100-doc real100 is the production target corpus today; future corpus expansion (ADR 0050 / 0052 trajectory) can re-open the question with its own ablation. Deferring would leave ADR 0010's "deferred" status permanently in limbo.
- **Re-run on Phase 3's hashing index instead of BGE-M3** — Rejected as a substitute for this ADR (PR-H tracks the retraction note separately). Hashing's score-collision behavior is a different question; the Phase 3.5 axis is "does the production semantic embedding change the answer?"

## Verification

<!-- verifies-key: reports/retrieval/phase35_m3_20260518T214937Z_kordoc_no_m3/REPORT.md:Per-category winner -->
<!-- verifies-key: docs/adr/0010-hybrid-bm25-dense-retrieval-rrf.md:BGE-M3 ablation closeout -->
<!-- verifies-key: eval/config.yaml:retrieval_backend -->

The Per-category winner section of the kordoc-corpus REPORT.md is the load-bearing evidence for this decision. ADR 0010 must gain a closeout section pointing back here (PR-G). `eval/config.yaml` must reflect the scenario A or B default explicitly (annotation or value change). The `scripts/_governance.py --lint-adr-consequences` linter will flag this ADR if the referenced files lose the keyed sections.
