# Embedding model ablation

Tracks issue #148. Updates the README's "Embedding 모델 ablation 미실행" caveat with a measured first comparison and a reproducible runner.

## Scope

The default embedding (since project inception) is the 2019 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. README has long flagged that this needs a comparison against modern multilingual models. This page is that comparison's first result + the path to extend it.

## Runner

```bash
# Default: compare MiniLM-L12-v2 vs multilingual-e5-base
python3 scripts/run_embedding_ablation.py

# Add more models — careful with disk (BGE-M3 ~2GB, e5-large ~1.3GB)
python3 scripts/run_embedding_ablation.py \
    --models \
        sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
        intfloat/multilingual-e5-base \
        intfloat/multilingual-e5-large \
        BAAI/bge-m3

# Reuse already-computed summaries (skip build_index/run_eval if cached)
python3 scripts/run_embedding_ablation.py --reuse-existing
```

The runner stores per-model artifacts under `data/embedding-ablation/<model_slug>/` (index) and `reports/embedding-ablation/<model_slug>/eval_summary.json`. Both are gitignored (per `outputs/*` + `reports/*` rules).

## First comparison — MiniLM-L12-v2 vs multilingual-e5-base

Run date: 2026-05-11. Public synthetic corpus (n=42; single_doc 14 / comparison 10 / follow_up 9 / abstention 9).

### Headline numbers (full pipeline)

| ablation | metric | MiniLM-L12-v2 | multilingual-e5-base | Δ (pp) |
|---|---|---:|---:|---:|
| `full` | accuracy | 0.906 | 0.906 | +0.0 |
| `full` | groundedness | 0.929 | 0.929 | +0.0 |
| `full` | citation_precision | 0.905 | 0.905 | +0.0 |
| `full` | abstention | 1.000 | 1.000 | +0.0 |
| `full` | format compliance | 0.905 | 0.905 | +0.0 |

### Where the embedding actually moves the needle

| ablation | metric | MiniLM-L12-v2 | multilingual-e5-base | Δ (pp) |
|---|---|---:|---:|---:|
| `naive_baseline` | accuracy | 0.656 | 0.844 | **+18.8** |
| `naive_baseline` | groundedness | 0.595 | 0.714 | **+11.9** |
| `naive_baseline` | citation_precision | 0.488 | 0.548 | +6.0 |
| `naive_baseline` | format compliance | 0.548 | 0.667 | **+11.9** |

All other agentic ablations (`hierarchical`, `no_metadata_first`, `no_rerank`, `no_verifier_retry`) show **0pp delta** in primary metrics.

### Chunk-level retrieval (human-annotated gold subset, n=10)

Issue [#175](https://github.com/hskim-solv/BidMate-DocAgent/issues/175) added explicit `gold_chunk_ids` to 8 `follow_up` + 2 `single_doc` chunk-boundary cases. Per-slice averages over the **annotated subset** (re-run 2026-05-11, `naive_baseline`, `hashing` backend):

| slice | n_annotated | chunk_recall@5 | chunk_MRR | chunk_nDCG@10 |
|---|---:|---:|---:|---:|
| single_doc (chunk-boundary probes) | 2 | 1.000 | 0.750 | 0.815 |
| follow_up | 8 | 0.750 | 0.750 | 0.750 |

Annotation outcome: heuristic-derived gold and human-annotated gold **agree on all 10 cases** — the 0.750 follow_up score reflects two multi-turn cases (`follow_up_state_a_security`, `follow_up_state_multi_step_a_deliverables`) where the retriever returns no chunks at all (tracked under issue [#57](https://github.com/hskim-solv/BidMate-DocAgent/issues/57) C4), not a gold-labeling artifact. Embedding-model comparisons can now distinguish retrieval misses from heuristic blind spots on these cases.

### Reading the result

1. **For the full agentic pipeline, the embedding choice is irrelevant on this corpus.** Metadata-first filtering (ADR 0002) bypasses dense retrieval for most queries, so a better embedding doesn't help. This is empirical validation of the metadata-first design — the pipeline is robust to a suboptimal embedding.
2. **For naive (dense-only) retrieval, the embedding choice matters a lot.** multilingual-e5-base lifts accuracy from 0.656 to 0.844 (+18.8pp). Most of that comes from the dense retriever finally finding the expected docs that MiniLM missed.
3. **No default change.** The CI path stays on `hashing` (per ADR 0001 reproducibility) and the README default stays on MiniLM-L12-v2 because the full pipeline metrics are identical. A future PR can revisit if a higher-impact corpus shows otherwise.
4. **Reviewer talking point.** A reviewer asking "why MiniLM in 2026?" gets a measured answer: "metadata-first filtering makes the agentic pipeline robust to embedding choice; we measured a +18.8pp accuracy lift on naive baseline with multilingual-e5-base but 0pp on the full pipeline."

## Second comparison — Phase 1.2 (issue #161): runner extended

This cycle adds the **OpenAI Embeddings API as a first-class backend** and **auto-derives the backend from the model ID** (`text-embedding-*` → `openai`, else `sentence-transformers`). The runner now spans modern multilingual SoTA (BGE-M3, e5-large-instruct), Korean-specialized (KURE-v1), and a paid external baseline (OpenAI text-embedding-3-large).

### Reproduction

```bash
# Modern multilingual + Korean-specialized (~4.4GB disk total, ~10 min cold cache)
python3 scripts/run_embedding_ablation.py --models \
    sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
    BAAI/bge-m3 \
    intfloat/multilingual-e5-large-instruct \
    nlpai-lab/KURE-v1

# OpenAI text-embedding-3-large (3072-dim) — ~$0.004 for n=42 corpus
export BIDMATE_OPENAI_API_KEY=sk-...
python3 scripts/run_embedding_ablation.py --models text-embedding-3-large
```

Per-model artifacts go to `data/embedding-ablation/<slug>/` (index) and `reports/embedding-ablation/<slug>/eval_summary.json` (eval). Both gitignored.

### Approximate disk + cost guide

| model | disk | dim | cost | notes |
|---|---:|---:|---|---|
| `BAAI/bge-m3` | ~2.0GB | 1024 | free | 2024 multilingual SoTA |
| `intfloat/multilingual-e5-large-instruct` | ~1.3GB | 1024 | free | instruction-tuned |
| `nlpai-lab/KURE-v1` | ~1.1GB | 768 | free | Korean-specialized |
| `text-embedding-3-large` | n/a | 3072 | ~$0.13 / 1M tokens (~$0.004 / n=42) | OpenAI |

### Headline numbers — Phase 1.2 (deferred, see ADR 0019)

**Attempted 2026-05-12; blocked on a Python environment mismatch that is out of scope for this measurement cycle.**

| model | attempted | blocker |
|---|---|---|
| `BAAI/bge-m3` | yes | sentence-transformers refuses load with `torch == 2.2.2` (CVE-2025-32434 hard requirement: `torch >= 2.6`). |
| `intfloat/multilingual-e5-large-instruct` | yes | transformers refuses load with `huggingface-hub == 1.14.0` (transformers requires `huggingface-hub < 1.0`). |
| `nlpai-lab/KURE-v1` | not attempted | Same env class as above is the expected blocker; deferred with the other two. |
| `text-embedding-3-large` | not attempted | Paid API; out of scope for the local-default decision. |

[ADR 0019](adr/0019-embedding-default-stays-minilm.md) records the resulting decision: **MiniLM-L12-v2 stays the documented default**, the first-cycle measurement (MiniLM vs e5-base) is the empirical justification, and the second cycle re-opens automatically the next time a contributor lands a Python env upgrade. The runner itself remains ready (it correctly surfaces the blocker rather than failing silently) so the experiment costs zero re-implementation when the env clears.

The first-cycle conclusion still applies:

- **Full pipeline metrics are embedding-invariant on this corpus** — metadata-first filtering (ADR 0002) routes around dense retrieval for most queries.
- **Naive baseline IS embedding-sensitive** — e5-base lifted accuracy +18.8pp over MiniLM on `naive_baseline`. The hypothesis worth testing in the next cycle is whether modern multilingual / Korean-specialized models break the `0pp on full` pattern. That hypothesis cannot be falsified yet.

## Why the deferral is itself ADR-worthy

The default did not change, so the empirical decision still has no ADR — but the *deferral* itself is now load-bearing. Without ADR 0019, the next contributor would either (a) re-run the same blocked measurement, or (b) silently swap the default without the empirical bar. ADR 0019 nails down both the "stay on MiniLM" decision and the explicit conditions under which it re-opens.

If a future ablation finds a model that meaningfully improves `full` (not just `naive_baseline`) and the team decides to switch the default, that change should land with a *follow-up* ADR per CLAUDE.md "ADR threshold". The OpenAI backend addition is an additive ablation surface under stub-default (CI runs `EMBEDDING_BACKEND=hashing` and never hits OpenAI) — same pattern as [ADR 0011](adr/0011-llm-synthesis-as-additive-ablation.md).

## See also

- [`scripts/run_embedding_ablation.py`](../scripts/run_embedding_ablation.py) — the runner
- [`docs/ablation-results.md`](ablation-results.md) — broader ablation context
- [ADR 0001](adr/0001-preserve-naive-baseline.md) — why `naive_baseline` is preserved
- [ADR 0002](adr/0002-metadata-first-retrieval.md) — why metadata-first dominates
- [ADR 0019](adr/0019-embedding-default-stays-minilm.md) — the deferral decision
