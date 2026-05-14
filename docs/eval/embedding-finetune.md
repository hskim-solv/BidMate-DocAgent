# Embedding LoRA fine-tune — KURE-v1 on Korean RFP pairs

> **Status.** Skeleton committed in #435; measured numbers + model-card
> rationale filled in #179 after the adapter is trained on Colab.
> Sections marked `TODO(user)` are the *cognitive-ownership* surfaces —
> author them in your own framing rather than letting the agent draft them.

- **Related**: issue [#179](https://github.com/hskim-solv/BidMate-DocAgent/issues/179), [ADR 0027](./adr/0027-lora-finetuned-embedding-additive.md), [ADR 0019](./adr/0019-embedding-default-stays-minilm.md), [ADR 0021](./adr/0021-bge-m3-completes-phase-1-3.md).
- **Notebook**: [`notebooks/embedding_finetune.ipynb`](../notebooks/embedding_finetune.ipynb) — Colab T4-runnable end-to-end.
- **Adapter**: `bidmate/embedding-lora-kure-rfp-ko-v1` on Hugging Face Hub *(uploaded in #179; SHA pinned in [`eval/config.yaml`](../eval/config.yaml))*.

## TL;DR

<!-- TODO(user): one-paragraph honest framing. Suggested skeleton:

  - Phase 1.2 (ADR 0019) measured 4 off-the-shelf embeddings → bit-identical
    `full` metrics → metadata-first design absorbs embedding variance.
  - This work adds the *trained* artifact (LoRA on KURE-v1) — the embedding-
    fine-tune cycle Phases 1.2/1.3 deliberately left out.
  - Headline measurement is `naive_baseline_finetuned` vs `naive_baseline`
    (dense-only surface where embedding actually matters); the `full` row
    is published as a deliberate null delta, not hidden.

  Write this in your own words — interview answers come out of this paragraph. -->

## Training data

| Statistic | Value |
|---|---|
| Source corpus | `data/raw/` — 7 public synthetic RFP JSON files (~10.7 KB) |
| Sub-chunks (at `max_chars=240`) | 25 |
| Queries per chunk | 200 (Anthropic backend, Claude Sonnet 4-6) |
| Total generated queries | <!-- TODO(user): paste stats.queries_generated from script output --> |
| Contamination-rejected | <!-- TODO(user): stats.queries_rejected --> |
| Rejection rate | <!-- TODO(user): stats.rejection_rate (must be < 5%) --> |
| Hard negatives per positive | 3 (BM25 rank window [3, 15]) |
| Train / val split | 90 / 10 deterministic by `sha1(query) % 10` |

**Schema reference**: [`data/training/sample.jsonl`](../data/training/sample.jsonl) — 25-row representative sample (committed; full 5k JSONL is `.gitignore`'d).

**Contamination guard**: the script rejects any generated query that
matches (lowercased, particle-stripped, 3-gram Jaccard ≥ 0.70) anything in
`eval/dev_queries_v1.jsonl`, `eval/multiturn_scenarios_v1.jsonl`, or
`eval/config.yaml` cases + `prior_turns`. Loud-fails if rejection rate > 5%.

## Hyper-parameters

| | Value |
|---|---|
| Base model | `nlpai-lab/KURE-v1` |
| LoRA `r` | 16 |
| LoRA `alpha` | 32 |
| LoRA `dropout` | 0.05 |
| `target_modules` | `query`, `key`, `value`, `dense` |
| `task_type` | `FEATURE_EXTRACTION` |
| Loss | `MultipleNegativesRankingLoss` |
| Epochs | 1 |
| Batch | 32 |
| LR | 2e-5 |
| Scheduler | cosine, 10 % warmup |
| AMP | on |
| Seed | 17 |

## Training curve

<!-- TODO(user): export `notebooks/_artifacts/training_curve.png` from the
     notebook and embed below. The image is gitignored — commit it to the
     HF Hub repo's model card README instead, or convert to a small inline
     ASCII summary. -->

## Eval deltas

### A. Dense-only surface (the headline)

`naive_baseline_finetuned` vs `naive_baseline` (KURE-v1 base) on the
public n=42 synthetic eval. **This is where the embedding actually
matters** — metadata-first (ADR 0002) does NOT route around dense here.

| Metric | KURE-v1 base | KURE-v1 + LoRA | Δ | 95 % bootstrap CI |
|---|---|---|---|---|
| accuracy | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |
| groundedness | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |
| citation_precision | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |

### B. Chunk-level retrieval (gold-annotated subset)

The 13 cases in `eval/config.yaml` with `gold_chunk_ids` — the
embedding-isolating surface, immune to metadata-first routing.

| Metric | KURE-v1 base | KURE-v1 + LoRA | Δ |
|---|---|---|---|
| chunk_recall@5 | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |
| chunk_MRR | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |

### C. `full` pipeline — the published null delta

`agentic_full_finetuned` vs `full` (KURE-v1 base). Per Phase 1.2 (ADR 0019)
the metadata-first pipeline absorbs embedding variance; expect ~0 pp ± 2 pp
with overlapping CIs. **Publish this anyway** — hiding it would misrepresent
where LoRA helps and where it doesn't.

| Metric | KURE-v1 base | KURE-v1 + LoRA | Δ | 95 % bootstrap CI |
|---|---|---|---|---|
| accuracy | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |
| groundedness | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |
| citation_precision | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |

## Model card

<!-- TODO(user): own this section. Suggested headings:

  - Base model + license inheritance
    (KURE-v1 → MIT; adapter inherits MIT)
  - Intended use
    (Korean RFP retrieval; do NOT use as a general-purpose Korean encoder
    — domain-narrow training data)
  - Training data description
    (synthetic queries from 7 public RFP samples; no real bidder data)
  - Known limitations
    (small training corpus, single-domain, query quality bounded by
    Claude's Korean fluency, no asymmetric query/passage split)
  - Ethical considerations
    (extractive grounding contract preserved by ADR 0003; the LoRA only
    changes vector content, not the answer-citation contract)

  These are the parts an external reader uses to judge the work — author
  in your own voice. -->

## Reproducibility

Pair regeneration (deterministic, byte-stable with `seed=17`):

```bash
python scripts/generate_finetune_pairs.py \
    --queries_per_chunk 200 \
    --neg_per_pos 3 \
    --seed 17 \
    --output data/training/embedding_pairs.jsonl
# Anthropic backend (paid): BIDMATE_PAIRGEN_BACKEND=anthropic + API key env vars
```

Training (Colab T4, ~30 min):

```
# Open notebooks/embedding_finetune.ipynb in Colab.
# Runtime → Change runtime type → T4 GPU.
# Run All. Adapter saves to lora_adapter/ and pushes to HF Hub.
```

Eval (operator-side, after the adapter is on HF Hub). `scripts/run_embedding_ablation.py`
appends an `__lora_<adapter>` suffix to its output slug when
`BIDMATE_EMBEDDING_LORA_ADAPTER` is set, so the two runs below write
to *separate* directories — no manual `mv` between runs.

```bash
# Run A — baseline KURE-v1 (no adapter)
python scripts/run_embedding_ablation.py --models nlpai-lab/KURE-v1
# → reports/embedding-ablation/nlpai_lab_KURE_v1/eval_summary.json

# Run B — LoRA-adapted KURE-v1
export BIDMATE_EMBEDDING_LORA_ADAPTER=bidmate/embedding-lora-kure-rfp-ko-v1
python scripts/run_embedding_ablation.py --models nlpai-lab/KURE-v1
# → reports/embedding-ablation/nlpai_lab_KURE_v1__lora_bidmate_embedding_lora_kure_rfp_ko_v1/eval_summary.json
unset BIDMATE_EMBEDDING_LORA_ADAPTER

# Diff the relevant ablation rows on the dense-only surface:
diff <(jq '.ablation.runs[] | select(.name=="naive_baseline")'           reports/embedding-ablation/nlpai_lab_KURE_v1/eval_summary.json) \
     <(jq '.ablation.runs[] | select(.name=="naive_baseline_finetuned")' reports/embedding-ablation/nlpai_lab_KURE_v1__lora_bidmate_embedding_lora_kure_rfp_ko_v1/eval_summary.json)
```

Without `BIDMATE_EMBEDDING_LORA_ADAPTER` set, `rag_core.embed_texts` is
bit-identical to pre-#434 behavior — the additive-ablation invariant
(ADR 0001 / 0025) is pinned by
[`tests/test_finetuned_ablation_baseline_invariant.py`](../tests/test_finetuned_ablation_baseline_invariant.py).
