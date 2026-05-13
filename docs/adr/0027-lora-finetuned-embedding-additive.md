# 0027: LoRA-fine-tuned embedding adapter as additive ablation

- **Status**: proposed
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

<!-- TODO(user): fill in the rationale for keeping the adapter merge
     at index-build time (offline) rather than per-query inference.
     Cover: (1) merge_and_unload() inference cost vs the load cost
     amortized once per index, (2) why we don't need to support
     query-time hot-swap, (3) how this composes with the existing
     `data/embedding-ablation/<slug>/` per-model directory pattern
     introduced in #174. Reference your own thinking here — this is
     the kind of design rationale future-you needs to recall, and
     ghost-written justification rots fast. -->

## Consequences

<!-- TODO(user): fill in the operator-facing consequences. Suggested
     bullets to expand or replace with your own framing:

     Easier:
     - The "have you fine-tuned a model?" interview signal is now
       grounded in a reproducible artifact (notebook + HF Hub repo
       + invariance test).
     - The additive-ablation pattern (ADR 0011/0017/0023) gains a
       fourth example, reinforcing that "new capability = new env-
       var + new ablation row, never a default swap."

     Costs / honesty:
     - New optional dep (PEFT) — install path is
       `requirements-lora.txt`, not `requirements.txt`.
     - New artifact class: HF Hub-hosted binary. Supply-chain rule
       (SHA pinning) is the mitigation; reviewers must check the
       SHA on every change.
     - The `full` pipeline delta is expected to be ~0 pp on the
       n=42 public synthetic surface (Phase 1.2 invariance). The
       writeup (`docs/embedding-finetune.md`) must lead with the
       `naive_baseline_finetuned` delta and publish the `full`
       null as a deliberate result — not hide it. -->

## Alternatives considered

<!-- TODO(user): fill in each alternative with your reasoning for
     rejecting it. Skeleton bullets:

     - **Full fine-tune of the base encoder.** Rejected because …
     - **Merge LoRA into the base and re-upload the merged checkpoint
       to HF Hub.** Rejected because the ablation surface needs to
       compare base vs adapted, which a merged checkpoint hides.
     - **Pin adapter by HF tag or branch instead of commit SHA.**
       Rejected because a silent re-push to the same tag changes
       eval results without changing the repo SHA — supply-chain
       hole the current pattern is designed to close.
     - **Train both KURE-v1 and BGE-M3 adapters and compare.**
       Deferred — BGE-M3's asymmetric dense/sparse/multi-vector
       heads complicate the LoRA target decision; KURE-v1's
       symmetric encoder needs only one LoRA head and is the
       Korean-market signal. Future ADR if revisited. -->

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
