# Cross-encoder reranker ablation

Tracks issue #163 (Phase 1.3). Adds a cross-encoder reranker as an additive ablation on top of the existing 60/25/15 dense + lexical + metadata blend.

## Scope

The current `agentic_full` rerank in [`rag_core.retrieve`](../rag_core.py) is a hardcoded score blend (0.60 dense + 0.25 lexical + 0.15 metadata when `metadata_first=True`). Cross-encoder rerankers are the next standard layer in modern retrieval stacks — adding one as an ablation tests whether the blend leaves precision on the table.

This page documents the integration; measurement is the local-run step (see *Reproduction* below).

## Design

* **Dispatch point**: after the existing 60/25/15 blend's `scored.sort()` and **before** the `top_k` cut + comparison balance. The cross-encoder re-scores the top-N highest-blend-score candidates (N = `min(30, top_k × 3)`), squashes logits via sigmoid into `[0,1]`, and re-sorts. The blend supplies the recall funnel; the cross-encoder adds precision-at-k.
* **Module**: [`rag_rerank.py`](../rag_rerank.py) — mirrors the `rag_synthesis.py` lazy-import + stub-default + env-var-gated pattern.
* **Preset flag**: `rerank_cross_encoder: bool`, defaults `False` on all 3 existing presets (`naive_baseline`, `agentic_full`, `agentic_full_llm`). New ablation row `full_reranker` in [`eval/config.yaml`](../eval/config.yaml) flips it to `true`.
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

Measurement pending — append below after running the reproduction commands. Two contracts to verify:

1. **Stub backend invariant**: `full_reranker` row in `eval_summary.json` is byte-equal to the `full` row (no behavior delta under CI default).
2. **Real backend delta**: at least one of `bge` / `cohere` / `bge_ko` produces a measurable precision lift vs `full` (target: citation_precision or retrieval_recall@5 in the bootstrap CI band that does not overlap `full`'s band).

```
TBD — paste relevant rows from
reports/{stub,bge,bge_ko,cohere}_rerank/eval_summary.json here.
```

## Why no ADR

This is a stub-default additive ablation under [ADR 0011](adr/0011-llm-synthesis-as-additive-ablation.md): an opt-in backend pipeline, gated behind an env var, with CI continuing to run the stub identity path. No load-bearing decision is replaced — the 60/25/15 blend remains the recall funnel; the cross-encoder is a *precision-at-k* refinement on top. If a future PR replaces the blend with a cross-encoder (or removes it), that requires a new ADR per the CLAUDE.md "ADR threshold".

## Risks

* **Score-floor regression** — verifier `min_evidence_score` is tuned for normalized scores. The sigmoid squash + Cohere `[0,1]`-clamp both ensure scores stay in range. Tests assert this in `tests/test_cross_encoder_rerank.py::RerankSigmoidSquashTest`.
* **Verifier retry interaction** — verifier may re-call `retrieve()`. `plan["rerank_cross_encoder"]` propagates through the retry since it's a plan dict key like `rerank`. Validated by the end-to-end normalize_run_config test.
* **Stub determinism** — stub MUST be pure identity (no re-sort, no score change). Otherwise `full` vs `full_reranker` under stub backend diverges and CI's hashing-backend invariant breaks. Locked by `RerankStubBackendTest::test_stub_backend_is_identity`.
* **Latency** — BGE-reranker on CPU adds ~80–200ms per query × 42 queries ≈ 5–10s extra eval time. Real-data eval over 100 docs scales linearly. Document the latency cost in PR descriptions when switching default.

## See also

- [`rag_rerank.py`](../rag_rerank.py) — backend dispatch
- [`rag_synthesis.py`](../rag_synthesis.py) — pattern this module mirrors
- [`tests/test_cross_encoder_rerank.py`](../tests/test_cross_encoder_rerank.py) — contract tests
- [ADR 0011](adr/0011-llm-synthesis-as-additive-ablation.md) — additive-ablation pattern
- [ADR 0001](adr/0001-preserve-naive-baseline.md) — naive_baseline invariant (cross-encoder never triggers on naive_baseline)
- [`docs/embedding-ablation.md`](embedding-ablation.md) — Phase 1.2 sibling cycle (#161)
