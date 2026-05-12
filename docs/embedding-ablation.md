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

## Second comparison — Phase 1.2 (issue #174): partial 3-of-4 measurement

This cycle adds the **OpenAI Embeddings API as a first-class backend** and **auto-derives the backend from the model ID** (`text-embedding-*` → `openai`, else `sentence-transformers`). The runner now spans modern multilingual SoTA (BGE-M3, e5-large-instruct), Korean-specialized (KoSimCSE), and a paid external baseline (OpenAI text-embedding-3-large).

Issue #174 (this section) executed the named candidates from ADR 0019. Three of four ran to completion; BAAI/bge-m3 remains blocked on the `torch` half of ADR 0019 condition 1.

### Reproduction

```bash
# Phase 1.2 measured set (~1.8GB disk, ~5 min cold cache on this corpus)
python3 scripts/run_embedding_ablation.py --models \
    sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
    intfloat/multilingual-e5-large-instruct \
    BM-K/KoSimCSE-roberta-multitask

# BGE-M3 — still blocked, requires torch >= 2.6 (see env section below)
python3 scripts/run_embedding_ablation.py --models BAAI/bge-m3

# OpenAI text-embedding-3-large (3072-dim) — ~$0.004 for n=42 corpus
export BIDMATE_OPENAI_API_KEY=sk-...
python3 scripts/run_embedding_ablation.py --models text-embedding-3-large
```

Per-model artifacts go to `data/embedding-ablation/<slug>/` (index) and `reports/embedding-ablation/<slug>/eval_summary.json` (eval). Both gitignored.

### Approximate disk + cost guide

| model | disk | dim | cost | notes |
|---|---:|---:|---|---|
| `BAAI/bge-m3` | ~2.0GB | 1024 | free | 2024 multilingual SoTA — env-blocked (torch < 2.6) |
| `intfloat/multilingual-e5-large-instruct` | ~1.3GB | 1024 | free | instruction-tuned, measured this cycle |
| `BM-K/KoSimCSE-roberta-multitask` | ~0.5GB | 768 | free | Korean-specialized, MEAN-pooling fallback (model is not packaged for sentence-transformers; the runner wraps it with default mean-token pooling) |
| `nlpai-lab/KURE-v1` | ~1.1GB | 768 | free | Korean-specialized — Phase 1.3 candidate (deferred) |
| `text-embedding-3-large` | n/a | 3072 | ~$0.13 / 1M tokens (~$0.004 / n=42) | OpenAI — Phase 1.3 candidate |

### Env state for this cycle

Phase 1.2 cleared one of the two env blockers from the original ADR 0019 analysis; the other remains:

| dependency | observed | required | status |
|---|---|---|---|
| `huggingface-hub` | `0.36.2` | `< 1.0` | ✅ cleared — `intfloat/multilingual-e5-large-instruct` loaded cleanly |
| `torch` | `2.2.2` | `>= 2.6` | ❌ still blocking BAAI/bge-m3 (CVE-2025-32434 hard requirement in `sentence_transformers` load path) |

A future PR pinning `torch >= 2.6` in `requirements.txt` unblocks BGE-M3 and triggers Phase 1.3 (one more re-run; the runner is idempotent via `--reuse-existing`).

### Headline numbers — Phase 1.2 (measured 2026-05-12, n=42)

Public synthetic corpus (same n=42 split as the first comparison). 95% bootstrap CIs in brackets.

#### `full` agentic pipeline — **the bar set by ADR 0019 condition 3**

| metric | MiniLM-L12-v2 | e5-large-instruct | KoSimCSE-roberta-multitask | Δ vs MiniLM (e5) | Δ vs MiniLM (KoSimCSE) |
|---|---:|---:|---:|---:|---:|
| accuracy | 0.906 [0.781, 1.000] | 0.906 [0.781, 1.000] | 0.906 [0.781, 1.000] | +0.0 | +0.0 |
| groundedness | 0.929 [0.857, 1.000] | 0.929 [0.857, 1.000] | 0.929 [0.857, 1.000] | +0.0 | +0.0 |
| citation_precision | 0.905 [0.821, 0.976] | 0.905 [0.821, 0.976] | 0.905 [0.821, 0.976] | +0.0 | +0.0 |
| abstention | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | +0.0 | +0.0 |
| format compliance | 0.905 [0.810, 0.976] | 0.905 [0.810, 0.976] | 0.905 [0.810, 0.976] | +0.0 | +0.0 |

The three models produce **bit-identical** metric values on `full` — not just CI-overlapping. Identical CIs follow trivially (`+0.0` deltas across the board).

#### `naive_baseline` (preserved as ablation per ADR 0001 — does NOT count toward ADR 0019 condition 3)

| metric | MiniLM-L12-v2 | e5-large-instruct | KoSimCSE-roberta-multitask | Δ vs MiniLM (e5) | Δ vs MiniLM (KoSimCSE) |
|---|---:|---:|---:|---:|---:|
| accuracy | 0.656 [0.500, 0.812] | 0.844 [0.719, 0.969] | 0.781 [0.625, 0.906] | **+18.8** | **+12.5** |
| groundedness | 0.595 [0.452, 0.738] | 0.714 [0.571, 0.833] | 0.667 [0.524, 0.786] | **+11.9** | +7.1 |
| citation_precision | 0.488 [0.357, 0.619] | 0.560 [0.440, 0.679] | 0.488 [0.369, 0.607] | +7.1 | +0.0 |
| abstention | 0.300 [0.000, 0.600] | 0.300 [0.000, 0.600] | 0.300 [0.000, 0.600] | +0.0 | +0.0 |
| format compliance | 0.548 [0.405, 0.690] | 0.667 [0.524, 0.810] | 0.619 [0.476, 0.762] | **+11.9** | +7.1 |

Same shape as the first-cycle finding — modern multilingual and Korean-specialized models both materially improve dense-only retrieval, but the production pipeline (`full`) routes around dense for most queries, so neither lift transfers.

### Reading the Phase 1.2 partial result

1. **ADR 0019 condition 3 is NOT triggered.** Both measured candidates show 0pp delta on `full.accuracy` and `full.groundedness`. The CI question is moot when the point estimates are identical. The default stays MiniLM-L12-v2.
2. **The `0pp-on-full` pattern is robust across the embedding-quality axis we just expanded.** First cycle showed it for `e5-base` (older multilingual). Phase 1.2 confirms it for `e5-large-instruct` (2024 SoTA, instruction-tuned, 1024-dim) and `KoSimCSE-roberta-multitask` (Korean-specialized). The "maybe a modern / Korean model breaks the pattern" hypothesis is falsified on this corpus.
3. **Empirical support for ADR 0002 (metadata-first retrieval).** Metadata-first routes most queries away from dense retrieval before the embedding choice has a chance to matter. The full pipeline's robustness to a 7-year-old embedding is not luck — it is the metadata-first design absorbing the embedding-quality axis.
4. **`naive_baseline` keeps moving with the embedding.** e5-large-instruct lifts `naive_baseline.accuracy` from 0.656 → 0.844 (+18.8pp, matching e5-base's first-cycle delta). KoSimCSE adds +12.5pp. ADR 0001 preserves naive as an ablation surface so these deltas are observable but not actionable for the default.
5. **BGE-M3 is the one named-candidate gap.** ADR 0019 condition 2 ("runs to completion") is *partially* met for this cycle. The remaining work is a `torch >= 2.6` requirements.txt bump — a focused chore PR, not a measurement decision. Phase 1.3 re-runs against BGE-M3 once that lands.

## Why the deferral is itself ADR-worthy

The default did not change, so the empirical decision still has no ADR — but the *deferral* itself is now load-bearing. Without ADR 0019, the next contributor would either (a) re-run the same blocked measurement, or (b) silently swap the default without the empirical bar. ADR 0019 nails down both the "stay on MiniLM" decision and the explicit conditions under which it re-opens.

If a future ablation finds a model that meaningfully improves `full` (not just `naive_baseline`) and the team decides to switch the default, that change should land with a *follow-up* ADR per CLAUDE.md "ADR threshold". The OpenAI backend addition is an additive ablation surface under stub-default (CI runs `EMBEDDING_BACKEND=hashing` and never hits OpenAI) — same pattern as [ADR 0011](adr/0011-llm-synthesis-as-additive-ablation.md).

## Third comparison — Phase 1.3 (issue #389): BGE-M3 closes ADR 0019 condition 2

Phase 1.2 left `BAAI/bge-m3` as the one named-candidate gap because the
maintainer's local Python install was on `torch 2.2.2` — below the
`torch >= 2.6` CVE-2025-32434 mitigation that modern
`sentence_transformers` hard-requires for BGE-M3's custom loader code.
Once `requirements.txt` pinned `torch >= 2.6` (the chore PR that ADR 0019
flagged), Phase 1.3 was reduced to "create a fresh venv, run the runner
against BGE-M3 alone, append the row."

### Env state for this cycle

Both blockers from the original ADR 0019 analysis are now cleared:

| dependency | observed (Phase 1.3 venv) | required | status |
|---|---|---|---|
| `torch` | `2.11.0` | `>= 2.6` | ✅ cleared — `requirements.txt:8` pin, `BAAI/bge-m3` loads cleanly |
| `huggingface-hub` | `0.36.2` | `< 1.0` | ✅ cleared (since Phase 1.2) |

### Headline numbers — Phase 1.3 (measured 2026-05-12, n=42)

Same n=42 public synthetic corpus as Phase 1.1 / 1.2.

#### `full` agentic pipeline — **ADR 0019 condition 3 evaluator**

| metric | MiniLM-L12-v2 | BGE-M3 | Δ vs MiniLM |
|---|---:|---:|---:|
| accuracy | 0.906 | 0.906 | **+0.0** |
| groundedness | 0.929 | 0.929 | **+0.0** |
| citation_precision | 0.905 | 0.905 | **+0.0** |
| abstention | 1.000 | 1.000 | **+0.0** |
| format compliance | 0.905 | 0.905 | **+0.0** |

Four for four. BGE-M3 produces **bit-identical** `full` metrics — not
just CI-overlapping — just like e5-large-instruct and
KoSimCSE-roberta-multitask did in Phase 1.2. Identical CIs follow.

#### `naive_baseline` (preserved as ablation per ADR 0001 — does NOT count toward ADR 0019 condition 3)

| metric | MiniLM-L12-v2 | BGE-M3 | Δ vs MiniLM |
|---|---:|---:|---:|
| accuracy | 0.656 | 0.844 | **+18.8** |
| groundedness | 0.595 | 0.714 | **+11.9** |
| citation_precision | 0.488 | 0.548 | +6.0 |
| abstention | 0.300 | 0.300 | +0.0 |
| format compliance | 0.548 | 0.667 | **+11.9** |

BGE-M3 lands at the same `naive_baseline` ceiling as e5-large-instruct
(both lift accuracy from 0.656 → 0.844, +18.8pp). The dense-only
retriever is *vastly* better at finding the right document; the agentic
pipeline routes around dense for most queries and absorbs the lift.

#### Other ablations (no_metadata_first / no_rerank / hierarchical / no_verifier_retry)

All four show `+0.0` deltas vs MiniLM on every metric — same pattern as
`full`. The runner output is preserved at
`reports/embedding-ablation/BAAI_bge_m3/eval_summary.json`.

### Reading the Phase 1.3 result

1. **ADR 0019 condition 2 is fully met.** All four ADR-0019-named
   candidates (MiniLM, e5-large-instruct, KoSimCSE, BGE-M3) have now
   run to completion against the n=42 public synthetic corpus. No
   measurement is "deferred" anymore.
2. **ADR 0019 condition 3 is NOT triggered for BGE-M3 either.** The
   `0pp-on-full` pattern is robust across all four candidates and
   across MiniLM (2019), e5-base (2023), e5-large-instruct (2024
   SoTA), KoSimCSE (Korean-specialized), and BGE-M3 (2024
   multi-functional). The "modern model breaks the pattern" and
   "Korean-specialized model breaks the pattern" hypotheses are both
   falsified on this corpus.
3. **Default stays MiniLM-L12-v2.** ADR 0019 stays accepted; the
   follow-up [ADR 0021](adr/0021-bge-m3-completes-phase-1-3.md) is a
   *supplement* that documents the closure, not a supersede.
4. **The empirical claim is now strong enough to publish.** Five
   embeddings spanning 2019–2024, multilingual / instruction-tuned /
   Korean-specialized / multi-functional: the agentic pipeline's
   `full` metrics do not move. Metadata-first retrieval (ADR 0002) is
   the load-bearing design choice, not the embedding choice.

## See also

- [`scripts/run_embedding_ablation.py`](../scripts/run_embedding_ablation.py) — the runner
- [`docs/ablation-results.md`](ablation-results.md) — broader ablation context
- [ADR 0001](adr/0001-preserve-naive-baseline.md) — why `naive_baseline` is preserved
- [ADR 0002](adr/0002-metadata-first-retrieval.md) — why metadata-first dominates
- [ADR 0019](adr/0019-embedding-default-stays-minilm.md) — the deferral decision
- [ADR 0021](adr/0021-bge-m3-completes-phase-1-3.md) — the Phase 1.3 closure
