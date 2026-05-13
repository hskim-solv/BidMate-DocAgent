# 0027: LoRA-fine-tuned embedding adapter as additive ablation

- **Status**: Superseded
- **Superseded by**: [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) § "Additive opt-in pattern (generalization)"
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (naive baseline invariant), [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) (additive-opt-in pattern), [ADR 0019](./0019-embedding-default-stays-minilm.md) (re-open criteria for swapping the default), [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) (Phase 1.3 closure), issue #179

## Context

Phase 1.2 ([ADR 0019](./0019-embedding-default-stays-minilm.md)) and
Phase 1.3 ([ADR 0021](./0021-bge-m3-completes-phase-1-3.md)) measured
four off-the-shelf embedding candidates (MiniLM-L12-v2, e5-large-instruct,
KoSimCSE-roberta-multitask, BGE-M3) on the public n=42 synthetic
surface. All four produced bit-identical metrics on the `full`
pipeline because metadata-first retrieval (ADR 0002) routes around
the dense vector for most queries. On `naive_baseline` (dense-only,
ADR 0001 invariant) BGE-M3 and e5-large-instruct lift accuracy
+18.8 pp (0.656 → 0.844), confirming the dense vector still matters
when the pipeline cannot route around it.

Issue #179 adds a *trained* embedding artifact — a LoRA-fine-tuned
adapter over `nlpai-lab/KURE-v1` — covering the "pretrain →
fine-tune → evaluate" cycle that Phases 1.2 and 1.3 deliberately
left out (off-the-shelf only). The portfolio motivation is the
"have you fine-tuned a model?" interview signal for senior AI
engineer roles in the Korean market; the technical motivation is
testing whether domain-specialized embeddings recover the dense-only
lift the metadata-first pipeline currently masks.

The trained adapter is a third-party artifact: a PEFT delta hosted
on the public Hugging Face Hub, loaded at index-build time by
`rag_core.embed_texts` via `peft.PeftModel.from_pretrained(...)
.merge_and_unload()`. This introduces a new artifact class to the
repo — pinned, optional, and reviewable — and the ADR codifies how
it integrates with the additive-ablation pattern that ADRs 0011,
0017, and 0023 established.

## Decision

The LoRA adapter is added as an **additive ablation**, gated by an
environment variable, with the default (env unset) bit-identical to
pre-#434 behavior.

**Three load-bearing rules:**

1. **`rag_core.embed_texts` extension is env-var gated.** The PEFT
   branch executes only when `BIDMATE_EMBEDDING_LORA_ADAPTER` is set
   to a path or HF Hub repo id. When unset (CI default), the function
   is byte-identical to its pre-#434 implementation. PEFT is imported
   lazily *inside* the conditional, so the hashing-only public CI
   never needs the package installed.
2. **Two new ablation rows are added to `eval/config.yaml`** —
   `agentic_full_finetuned` (clones `full`) + `naive_baseline_finetuned`
   (clones `naive_baseline`). The `embedding_model` and
   `embedding_lora_adapter` keys on these rows are documentation read
   by `scripts/run_embedding_ablation.py` at index-build time; they
   are silently dropped by `eval/run_eval.normalize_run_config` so on
   the default deterministic surface the **correctness metrics**
   (`accuracy`, `groundedness`, `citation_precision`, `abstention`,
   `answer_format_compliance` — the canonical `REPRODUCIBLE_METRICS`
   set) are byte-equal to the parent rows'. Latency / `stage_latency`
   drifts μs-scale run-to-run — universal across every ablation, not a
   contract break (mirrors the same exclusion in
   `tests/test_eval_reproducibility_regression.py`). A regression
   test (`tests/test_finetuned_ablation_baseline_invariant.py`) pins
   both the structural (normalize_run_config) and the end-to-end
   (eval_summary correctness-metric) layers of the invariant.
3. **The HF Hub-hosted adapter is pinned by commit SHA** in
   `eval/config.yaml` (`<repo>@<sha>` form), not by tag or branch.
   This closes the silent-republish supply-chain hole: a re-push to
   the same tag would change eval results without changing the repo
   SHA. Pinning by SHA means every adapter swap is a git diff.

The CLI default stays `naive_baseline` (ADR 0001). The function-level
default `model_name` in `embed_texts` stays
`paraphrase-multilingual-MiniLM-L12-v2` ([ADR 0019](./0019-embedding-default-stays-minilm.md)).
This ADR does *not* trigger the ADR 0019 re-open criteria — those
require ≥ +5 pp lift on the `full` pipeline with non-overlapping 95%
CIs; per Phase 1.2 the metadata-first design makes that nearly
impossible to clear with embeddings alone.

## Why "adapter only at index-build time, not query time"

`rag_core.embed_texts` (line 566–586) merges the adapter once at first
call, then caches the result in `MODEL_CACHE` under a
`(model_name, local_only, adapter_path)` key.

**(1) `merge_and_unload()` cost is amortized, not repeated.**
`PeftModel.merge_and_unload()` rewrites the full base-model weight
tensor in memory — it's a one-time cost that produces a plain
`SentenceTransformer` with no PEFT overhead. Doing this per-query
would mean paying that cost for every encode call. Caching in
`MODEL_CACHE` means the merge happens once per process lifetime
(or once per index-build run), after which query-time embedding is
as fast as the non-adapted path.

**(2) Query-time hot-swap is not a use case here.**
The `data/embedding-ablation/<slug>/` directory pattern (issue #174)
persists the embedded chunk vectors for each adapter variant under a
slug. Switching adapters at query time would require those vectors
to have been built under the new adapter — i.e., a full index rebuild.
There is no in-flight re-embedding; the adapter choice is fixed when
`scripts/build_index.py` runs. Supporting hot-swap would add
complexity (adapter version tracking per stored vector, invalidation
on adapter change) with no payoff for the offline-batch eval use case.

**(3) Composition with the `data/embedding-ablation/<slug>/` pattern.**
`scripts/build_index.py` reads `BIDMATE_EMBEDDING_LORA_ADAPTER` and
folds it into the run slug, so each (base model, adapter) combination
lands in its own directory. Calling `embed_texts` at query time reuses
the same `MODEL_CACHE` entry — both paths share the same merge result.
The pattern parallels how `BIDMATE_EMBEDDING_BACKEND` and
`BIDMATE_EMBEDDING_MODEL` already version separate index directories.

## Consequences

**Easier:**
- The "have you fine-tuned a model?" interview signal is now
  grounded in a reproducible artifact: a Colab-runnable training
  notebook (`notebooks/embedding_finetune.ipynb`), an HF Hub adapter
  pinned by SHA in `eval/config.yaml`, and a byte-equality invariance
  test (`tests/test_finetuned_ablation_baseline_invariant.py`).
- The additive-ablation pattern (ADR 0011/0017/0023) gains a fourth
  instance — reinforcing that "new capability = new env-var + new
  ablation row, never a default swap."
- Removing the adapter later is a one-line change: unset
  `BIDMATE_EMBEDDING_LORA_ADAPTER`. The default path is byte-identical
  to pre-#434 behavior; no migration needed.

**Costs / honesty:**
- New optional dep (PEFT) — install path is `requirements-lora.txt`,
  not `requirements.txt`. The hashing-only CI path never imports PEFT.
- New artifact class: HF Hub-hosted binary. The SHA-pinning rule
  (`<repo>@<sha>` in `eval/config.yaml`) closes the silent-republish
  supply-chain hole; every adapter bump is a git diff.
- The `full` pipeline delta is expected to be ~0 pp on the n=42 public
  synthetic surface (Phase 1.2 / ADR 0021 invariance: metadata-first
  routing absorbs embedding variance). `docs/embedding-finetune.md`
  leads with the `naive_baseline_finetuned` delta [TBD — issue #179]
  and publishes the `full` null as a deliberate result, not an omission.
- `MODEL_CACHE` uses a 3-tuple key `(model_name, local_only,
  adapter_path)`. A process that loads both adapted and unadapted
  variants holds two full model copies in memory simultaneously.

## Alternatives considered

- **Full fine-tune of the base encoder.** Rejected: full fine-tune
  requires retraining all encoder weights, which (a) demands a much
  larger labeled dataset than the synthetic pairs from
  `scripts/generate_finetune_pairs.py`, (b) loses the ability to
  compare base vs fine-tuned on the same index, because the base
  weights are gone, and (c) makes the HF Hub artifact a 400 MB
  checkpoint rather than a ~4 MB PEFT delta. LoRA preserves the
  base for side-by-side ablation — exactly what the eval surface needs.

- **Merge LoRA into the base and re-upload the merged checkpoint to
  HF Hub.** Rejected: the ablation surface (`naive_baseline` vs
  `naive_baseline_finetuned`) requires comparing the same base model
  with and without the adapter. A merged checkpoint makes that
  impossible without storing two full checkpoints. The PEFT delta
  approach keeps the diff visible and the comparison structurally
  correct. (`merge_and_unload()` happens locally at runtime for
  inference speed; the HF Hub stores the delta only.)

- **Pin adapter by HF tag or branch instead of commit SHA.** Rejected:
  a re-push to the same tag would silently change eval results without
  any git diff in this repo — exactly the supply-chain hole the SHA-pin
  pattern is designed to close. SHA pinning means every adapter version
  bump is a reviewable one-line change in `eval/config.yaml`.

- **Train both KURE-v1 and BGE-M3 adapters and compare.** Deferred:
  BGE-M3's asymmetric dense/sparse/colbert multi-vector architecture
  complicates the LoRA target layer decision (separate adapters per
  head vs a unified projection). KURE-v1's symmetric encoder needs
  only one LoRA target and is the natural Korean-market signal for this
  domain. Revisiting BGE-M3 fine-tuning is tracked as a follow-up; a
  new ADR would be needed to decide the head-targeting strategy.

## See also

- [`rag_core.py`](../../rag_core.py) — `embed_texts` LoRA branch + `MODEL_CACHE` 3-tuple key.
- [`eval/config.yaml`](../../eval/config.yaml) — the two new
  `ablation_runs` rows + `latency_budgets` entries.
- [`requirements-lora.txt`](../../requirements-lora.txt) — optional PEFT install path.
- [`scripts/generate_finetune_pairs.py`](../../scripts/generate_finetune_pairs.py) — synthetic pair generation (issue #433).
- `notebooks/embedding_finetune.ipynb` *(issue #435, not yet landed)* — training notebook.
- `docs/embedding-finetune.md` *(issue #435, not yet landed)* — model card + measured results.
- [`tests/test_finetuned_ablation_baseline_invariant.py`](../../tests/test_finetuned_ablation_baseline_invariant.py) — pins the byte-equality invariant.
- [ADR 0019](./0019-embedding-default-stays-minilm.md) — re-open criteria for swapping the embedding default (NOT triggered by this ADR).
- [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) — Phase 1.3 closure (off-the-shelf measurement).
