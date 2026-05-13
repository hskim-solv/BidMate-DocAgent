# 0031: BM25 Korean morphology tokenizer as additive ablation

- **Status**: accepted
- **Date**: 2026-05-13
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (naive_baseline invariant), [ADR 0010](./0010-hybrid-bm25-dense-retrieval-rrf.md) (hybrid BM25 baseline this layers on), [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) / [ADR 0013](./0013-observability-as-additive-pluggable-surface.md) (additive-opt-in backend pattern this reuses), [ADR 0019](./0019-embedding-default-stays-minilm.md) / [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) / [ADR 0025](./0025-cost-frontier-defer-until-real-baselines.md) / [ADR 0026](./0026-cross-encoder-reranker-deferral.md) (measurement-gated deferral pattern), issue #486, issue #150 (BM25_EXTRA precedent)

## Context

External senior review (2026-05) §A3-S3 correctly identified the
absence of a Korean morphology-aware tokenizer as a real retrieval gap.
The current BM25 path tokenizes via `re.compile(r"[A-Za-z0-9]+|[가-힣]+")`
plus the optional `bm25_extra` profile (issue #150) that strips
Korean particle suffixes from already-extracted tokens. Both treat
"입찰참여시작일" as one token and "입찰 참여 시작일" as three —
even though they refer to the same concept. BM25 recall on
multi-token Korean noun compounds suffers as a result.

Two complementary candidates exist:

- **`kiwipiepy`** — morphological analyzer with POS tagging, ships
  pure-Python wheels, no model download. Modest install footprint
  (~30MB). POS filter (체언 / 용언 / 수식어 / 외래어) drops
  retrieval-noise tokens (조사 / 어미 / punctuation) that the regex
  tokenizer leaves in.
- **`MeCab-ko`** or **`KoNLPy`** — stronger morphological analysis
  but heavier (C dependencies, system libraries, often platform-
  fragile). Out of scope for this ADR — `kiwipiepy` is the
  measurement-first slice.

The pattern from ADR 0019/0021 (embedding deferred-then-closed loop)
and ADR 0026 (cross-encoder reranker deferral) applies cleanly here:
add the surface as an additive ablation; default stays regex; flip
the default only if a measurement gate triggers a follow-up ADR.

## Decision

Introduce **`bm25_tokenizer: "regex" | "kiwi"`** as a new pipeline
config key in [`rag_pipeline_presets.py`](../../rag_pipeline_presets.py).

- All three presets (`naive_baseline`, `agentic_full`,
  `agentic_full_llm`) default to `"regex"`.
- New ablation row `full_kiwi` in
  [`eval/config.yaml`](../../eval/config.yaml) sets
  `bm25_tokenizer: kiwi` + `retrieval_backend: hybrid`.
- New function [`korean_lexicon.kiwi_tokens`](../../korean_lexicon.py)
  morpheme-tokenizes via kiwipiepy and POS-filters
  (`{NNG, NNP, NP, NR, VV, VA, VX, VCP, VCN, MM, MAG, MAJ, SL, SH, SN}`).
- BM25 cache key changes from `stopword_profile` to
  `(stopword_profile, tokenizer)` in
  [`rag_retrieval.get_or_build_bm25`](../../rag_retrieval.py) so the
  `(shared, kiwi)` corpus stays cached separately from the
  `(shared, regex)` default.
- Query-side tokens are also kiwi-tokenized when `tokenizer="kiwi"`
  so corpus and query share the same morpheme surface (otherwise
  BM25 IDF distributions wouldn't align).

### Never-raise contract

The kiwi path is **strictly opt-in and silently degrades** when
unavailable:

- `korean_lexicon.kiwi_tokens` lazy-imports `kiwipiepy`. If the
  import fails (missing wheel, unusual platform) it returns `None`.
- `rag_retrieval._chunk_tokens_for_bm25`, on a `None` return,
  falls back to the regex tokens path — bit-identical to the
  control row.
- `rag_retrieval.bm25_scores_for_index` does the same for the
  query side.

Net effect: under CI / environments without kiwipiepy, `full_kiwi`
is byte-equal to `hybrid_bm25` on `eval_summary.json`. The row
exercises plumbing; the LLM column is not a quality claim on the
public CI surface unless the wheel is installed.

### Contract preservation

- **ADR 0001 (naive_baseline)**: All three presets carry
  `bm25_tokenizer: "regex"`. The `naive_baseline` golden
  ([`tests/data/naive_baseline_top_k.json`](../../tests/data/naive_baseline_top_k.json),
  gated by
  [`tests/test_naive_baseline_ranking_invariance.py`](../../tests/test_naive_baseline_ranking_invariance.py))
  is bit-identical because `naive_baseline` runs with
  `retrieval_backend: dense` and never invokes BM25 anyway. The
  explicit `"regex"` value protects against silent future changes
  that might enable BM25 on `naive_baseline`.
- **ADR 0010 (hybrid BM25)**: The hybrid ablation rows
  (`hybrid_bm25`, `hybrid_bm25_extra_stopwords`, `hybrid_bm25_k30_*`,
  etc.) keep `bm25_tokenizer: "regex"` implicitly via the default →
  the existing eval delta numbers stay byte-equal.
- **ADR 0003 (answer/citation contract)**: no schema change. The
  `bm25_tokenizer` key surfaces in `eval_summary.json` row metadata
  but does not modify `answer.claims` / `answer.citations`.
- **ADR 0023 (HyDE)** / **ADR 0026 (cross-encoder reranker)**:
  orthogonal to this ADR. `bm25_tokenizer` is independent of
  `query_expansion` and `rerank_cross_encoder`.

## Re-open conditions

This ADR re-opens — and the `bm25_tokenizer` default may flip to
`kiwi` — when **all three** hold:

1. A maintainer runs the public synthetic eval surface (n=42) with
   `bm25_tokenizer: kiwi` and `kiwipiepy` installed, producing a
   real `full_kiwi` row in `eval_summary.json` (rather than the
   fallback-to-regex byte-equal row).
2. `full_kiwi` shows a lift of **≥ +3pp** on `accuracy` OR
   `citation_precision` vs `hybrid_bm25` (the natural control —
   same `retrieval_backend: hybrid`, only `bm25_tokenizer` differs),
   with non-overlapping bootstrap 95% CIs. The +3pp threshold
   matches ADR 0026's reranker gate (smaller absolute lift accepted
   for precision-targeted post-retrieval / pre-retrieval changes).
3. A follow-up ADR (numbered `003x` or higher) is opened to flip
   the `bm25_tokenizer` default, documenting the CI install
   footprint impact (~30MB extra wheel) and whether the change
   warrants making `kiwipiepy` a hard CI dependency or keeping the
   silent fallback.

If condition 1 lands but condition 2 does not (the `0pp-on-hybrid`
pattern that ADR 0019/0021 found for embeddings holds for BM25
tokenizers too), this ADR stays `accepted` and the public synthetic
eval surface gets the measurement appendix without an ADR
replacement — same loop shape as ADR 0019 → 0021.

## Consequences

**Wins**

- The retrieval surface gains a Korean-morphology-aware BM25 ablation
  cell that the external review correctly flagged. The eval matrix
  grows by one row; `full_kiwi` delta against `hybrid_bm25` is
  always visible (or, under CI fallback, demonstrably zero).
- ADR 0001 invariant preserved by a default-value choice
  (`"regex"`) and a never-raise fallback path. Removing kiwi later
  is a one-line removal in `eval/config.yaml`; no schema bump.
- Adds a third concrete ablation-by-default-key example (after
  `query_expansion` ADR 0023 and `bm25_stopword_profile` issue #150)
  to the repo idiom — additive Protocol-shaped backend dispatch
  with measurement gating.

**Costs**

- One additional pipeline config key for users to understand.
  Mitigated by the default being `"regex"` (no behavior change) and
  the never-raise contract (missing wheel doesn't break anything).
- `kiwipiepy>=0.17` added to `requirements.txt` — modest install
  footprint (~30MB), pure-Python wheels for major platforms. The
  lazy-import + None-fallback means runtime is robust even if
  installation skipped this dep (e.g. minimal Docker layer).
- Query-side kiwi tokenization re-tokenizes the regex tokens by
  re-joining them. This is approximate but matches the corpus side:
  corpus chunks are kiwi-tokenized from raw text, query tokens are
  kiwi-tokenized from the regex-built token list. Strictly correct
  alternative would be to pass the original query string to
  `bm25_scores_for_index` — deferred as a refactor; the present
  surface is enough for the measurement.

**Constraints (unchanged)**

- ADR 0001: `naive_baseline` golden bit-identical (verified by
  `tests/test_naive_baseline_ranking_invariance.py`).
- ADR 0003: answer / citation contract unchanged; no
  `schema_version` bump.
- ADR 0010: existing hybrid BM25 ablation rows byte-equal — only
  the new `full_kiwi` row exercises the kiwi path.

## Alternatives considered

- **Replace the regex tokenizer entirely with kiwi.** Rejected:
  conflicts with ADR 0001's "preserve the baseline" invariant.
  Forcing every install to pull a 30MB dep also breaks the minimal-
  footprint deployment story. The additive-row pattern follows the
  ADR 0019 / 0026 deferred-then-closed loop precisely.
- **Add kiwi as a stopword profile (`bm25_stopword_profile: "kiwi"`).**
  Rejected: the existing stopword profiles share a tokenizer (regex)
  and differ only in post-processing. Conflating the tokenizer axis
  with the stopword axis under one knob would force a two-dimensional
  semantic into a single string, hurt cache-key clarity, and surprise
  any future ADR that wants to combine `bm25_tokenizer: kiwi` with
  `bm25_stopword_profile: bm25_extra`.
- **MeCab-ko / KoNLPy instead of kiwipiepy.** Out of scope — bigger
  install (C deps, system libraries, often platform-fragile).
  Future ADR can swap the kiwi backend for MeCab-ko under the same
  `bm25_tokenizer` key (e.g. `"mecab"`) if measurement justifies it.
  The Protocol surface stays.
- **Bake kiwi corpus into `index.json` at build time.** Rejected:
  doubles index size when both profiles are needed (and the
  per-`(profile, tokenizer)` cache is already lazy and process-
  local). The current build → cache loop happens on first eval row
  use; cost is amortized.
- **Use jamo-level n-grams instead of morphemes.** Considered, not
  adopted — different surface (character n-grams) needs a different
  ablation row; the morphological tokenizer choice this ADR addresses
  is independent.

## See also

- [`korean_lexicon.kiwi_tokens`](../../korean_lexicon.py) — the
  morpheme-tokenization implementation + POS filter.
- [`rag_pipeline_presets.VALID_BM25_TOKENIZERS`](../../rag_pipeline_presets.py)
  — the validator surface.
- [`rag_retrieval._chunk_tokens_for_bm25`](../../rag_retrieval.py)
  + `get_or_build_bm25` + `bm25_scores_for_index` — the dispatch
  sites.
- [`eval/config.yaml`](../../eval/config.yaml) — the `full_kiwi`
  ablation row.
- ADR 0019 → ADR 0021 — the measurement-gated deferral pattern this
  ADR follows.
- Issue [#486](https://github.com/hskim-solv/BidMate-DocAgent/issues/486).
