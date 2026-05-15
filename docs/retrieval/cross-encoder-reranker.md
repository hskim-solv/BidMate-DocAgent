# Cross-encoder reranker ablation

Tracks issue #163 (Phase 1.3). Adds a cross-encoder reranker as an additive ablation on top of the existing 60/25/15 dense + lexical + metadata blend.

## Scope

The current `agentic_full` rerank in [`rag_core.retrieve`](../../rag_core.py) is a hardcoded score blend (0.60 dense + 0.25 lexical + 0.15 metadata when `metadata_first=True`). Cross-encoder rerankers are the next standard layer in modern retrieval stacks — adding one as an ablation tests whether the blend leaves precision on the table.

This page documents the integration; measurement is the local-run step (see *Reproduction* below).

## Design

* **Dispatch point**: after the existing 60/25/15 blend's `scored.sort()` and **before** the `top_k` cut + comparison balance. The cross-encoder re-scores the top-N highest-blend-score candidates (N = `min(30, top_k × 3)`), squashes logits via sigmoid into `[0,1]`, and re-sorts. The blend supplies the recall funnel; the cross-encoder adds precision-at-k.
* **Module**: [`rag_rerank.py`](../../rag_rerank.py) — mirrors the `rag_synthesis.py` lazy-import + stub-default + env-var-gated pattern.
* **Preset flag**: `rerank_cross_encoder: bool`, defaults `False` on all 3 existing presets (`naive_baseline`, `agentic_full`, `agentic_full_llm`). New ablation row `full_reranker` in [`eval/config.yaml`](../../eval/config.yaml) flips it to `true`.
* **Postcondition guard**: every reordered `chunk_id` must be a subset of the input. Violations fall back to input order with `meta["fallback_reason"] = "chunk_id_postcondition_violation"`.
* **Score normalization**: cross-encoder logits aren't in `[0,1]`. The verifier's score floor at `rag_core.py` ~L2254 (threshold 0.18) was tuned for the normalized blend; sigmoid squash keeps it working without per-backend branches. Cohere's `relevance_score` is already normalized, so the Cohere branch skips sigmoid and clamps instead.

## Backends

Selected via `BIDMATE_RERANK_BACKEND` (defaults `stub`):

| backend | model default | env vars | cost | notes |
|---|---|---|---|---|
| `stub` | (none) | — | free | Identity pass-through. **CI default.** `full_reranker` row byte-equals `full` under stub. |
| `bge` | `BAAI/bge-reranker-v2-m3` | `BIDMATE_RERANK_MODEL` | free | ~1.1GB local download. ~80–200ms / query CPU. |
| `bge_ko` | `dragonkue/bge-reranker-v2-m3-ko` | `BIDMATE_RERANK_MODEL` | free | Korean-finetuned. Same FlagEmbedding code path as `bge`. |
| `cohere` | `rerank-3.5-multilingual` | `BIDMATE_COHERE_API_KEY` or `COHERE_API_KEY`, `BIDMATE_RERANK_MODEL` | ~$2 / 1k searches (~$0.084 for n=42) | Network call. Scores already in [0,1] (no sigmoid). |

## Reproduction

```bash
# CI-default stub (no-op identity — full_reranker row byte-equals full)
bash scripts/test.sh
python3 eval/run_eval.py --config eval/config.yaml --output_dir reports/stub_rerank

# BGE-reranker-v2-m3 local (FlagEmbedding required)
pip install FlagEmbedding
export BIDMATE_RERANK_BACKEND=bge
python3 eval/run_eval.py --config eval/config.yaml --index_dir data/index --output_dir reports/bge_rerank

# Korean-finetuned variant
export BIDMATE_RERANK_BACKEND=bge_ko
python3 eval/run_eval.py --config eval/config.yaml --index_dir data/index --output_dir reports/bge_ko_rerank

# Cohere rerank-3.5-multilingual (paid)
pip install cohere
export BIDMATE_RERANK_BACKEND=cohere BIDMATE_COHERE_API_KEY=...
python3 eval/run_eval.py --config eval/config.yaml --index_dir data/index --output_dir reports/cohere_rerank
```

## Headline numbers

### Pipeline bug fix (issue #448)

Prior to this fix, `rerank_cross_encoder: true` in `eval/config.yaml`'s `full_reranker` row was
silently discarded — the flag was read in `eval/run_eval.py` but never propagated through
`run_rag_query → _build_run_context → _RunContext → make_plan → plan dict`. As a result,
`full_reranker` was byte-equal to `full` regardless of `BIDMATE_RERANK_BACKEND`.

Fixed in the same PR by wiring `rerank_cross_encoder` through:
- `rag_query.py:make_plan` (added parameter + plan dict key)
- `rag_core.py:_build_run_context` / `_RunContext` / `_phase_retrieve_loop`
- `eval/run_eval.py` call to `run_rag_query`

### Measurement: bge_ko backend (2026-05-13, n=100 synthetic, hashing embeddings)

```
EMBEDDING_BACKEND=hashing BIDMATE_RERANK_BACKEND=bge_ko
eval config: /tmp/eval_reranker_only.yaml (naive_baseline + full + full_reranker)
index:       data/index (hashing embeddings, ADR 0001 public synthetic)
```

**Overall metrics (95% bootstrap CI, n=100):**

| run | accuracy | Δ vs full | citation_precision | Δ vs full | n |
|---|---|---|---|---|---|
| naive_baseline | 0.782 [0.679–0.872] | — | 0.525 [0.450–0.610] | — | 100 |
| full | 0.718 [0.615–0.821] | — | 0.705 [0.625–0.780] | — | 100 |
| full_reranker (bge_ko) | 0.590 [0.487–0.692] | **−12.8pp** | 0.705 [0.620–0.785] | 0pp | 100 |

**Per-query-type accuracy (full vs full_reranker):**

| query_type | full | full_reranker | Δ |
|---|---|---|---|
| single_doc (n=34) | 0.882 | 0.735 | −14.7pp |
| comparison (n=24) | 0.500 | 0.292 | −20.8pp |
| follow_up (n=21) | 0.700 | 0.700 | 0pp |
| abstention (n=21) | 0.000 | 0.000 | 0pp |

**Abstention decomposition (correct_refusal / incorrect_answer / boundary_partial):**

| run | correct_refusal | incorrect_answer | boundary_partial |
|---|---|---|---|
| naive_baseline | 6 | 16 | 0 |
| full | 18 | 4 | 0 |
| full_reranker (bge_ko) | **22** | **0** | 0 |

**Latency (ms per query, warm):**

| run | p50 | p95 | mean |
|---|---|---|---|
| naive_baseline | 1.7 ms | 3.1 ms | 1.9 ms |
| full | 2.6 ms | 4.6 ms | 2.6 ms |
| full_reranker (bge_ko) | 2822 ms | 9435 ms | 3559 ms |

### ADR 0026 re-open verdict (issue #448)

**Condition** (ADR 0026 re-open threshold): ≥+3pp accuracy **or** citation_precision lift with
non-overlapping 95% CIs vs `full`.

**Result**: −12.8pp accuracy, 0pp citation_precision. CIs overlap (full: [0.615–0.821],
full_reranker: [0.487–0.692]; overlap region [0.615–0.692]).

**Verdict: REJECTED.** The "0pp-on-full pattern holds" — bge_ko reranker does not meet the
re-open threshold on hashing embeddings.

**Root cause**: hashing embeddings are non-semantic (bag-of-character n-grams); the reranker
re-scores semantic relevance, but the top-k input candidates are already ordered by a non-semantic
blend. The reranker's semantic preference diverges from the hashing blend's ordering, producing
worse recall for answerable queries. The comparison query type is hit hardest (−20.8pp) because
comparison needs multi-source diversity that the reranker collapses.

**Abstention improvement is real but insufficient**: bge_ko pushes all incorrect_answer abstentions
to correct_refusal (4→0 incorrect, 18→22 correct). This is a precision gain on unanswerable cases,
but accuracy on answerable cases dominates.

**Follow-up gate**: re-evaluate with semantic embeddings (e.g. `BAAI/bge-m3`) once a real-embedding
index is available in CI. On a semantically-ranked candidate list, the reranker's precision-at-k
benefit has a fair opportunity to manifest. Track as a blocked follow-up on ADR 0026.

## Why no ADR

This is a stub-default additive ablation under [ADR 0011](../adr/0011-llm-synthesis-as-additive-ablation.md): an opt-in backend pipeline, gated behind an env var, with CI continuing to run the stub identity path. No load-bearing decision is replaced — the 60/25/15 blend remains the recall funnel; the cross-encoder is a *precision-at-k* refinement on top. If a future PR replaces the blend with a cross-encoder (or removes it), that requires a new ADR per the CLAUDE.md "ADR threshold".

## Risks

* **Score-floor regression** — verifier `min_evidence_score` is tuned for normalized scores. The sigmoid squash + Cohere `[0,1]`-clamp both ensure scores stay in range. Tests assert this in `tests/test_cross_encoder_rerank.py::RerankSigmoidSquashTest`.
* **Verifier retry interaction** — verifier may re-call `retrieve()`. `plan["rerank_cross_encoder"]` propagates through the retry since it's a plan dict key like `rerank`. Validated by the end-to-end normalize_run_config test.
* **Stub determinism** — stub MUST be pure identity (no re-sort, no score change). Otherwise `full` vs `full_reranker` under stub backend diverges and CI's hashing-backend invariant breaks. Locked by `RerankStubBackendTest::test_stub_backend_is_identity`.
* **Latency** — BGE-reranker on CPU adds ~80–200ms per query × 42 queries ≈ 5–10s extra eval time. Real-data eval over 100 docs scales linearly. Document the latency cost in PR descriptions when switching default.

## See also

- [`rag_rerank.py`](../../rag_rerank.py) — backend dispatch
- [`rag_synthesis.py`](../../rag_synthesis.py) — pattern this module mirrors
- [`tests/test_cross_encoder_rerank.py`](../../tests/test_cross_encoder_rerank.py) — contract tests
- [ADR 0011](../adr/0011-llm-synthesis-as-additive-ablation.md) — additive-ablation pattern
- [ADR 0001](../adr/0001-preserve-naive-baseline.md) — naive_baseline invariant (cross-encoder never triggers on naive_baseline)
- [`docs/eval/embedding-ablation.md`](../eval/embedding-ablation.md) — Phase 1.2 sibling cycle (#161)
