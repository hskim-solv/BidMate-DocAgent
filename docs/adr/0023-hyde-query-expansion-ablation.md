# 0023: HyDE query expansion as additive ablation

- **Status**: proposed
- **Date**: 2026-05-12
- **Related**: extends [ADR 0001](./0001-preserve-naive-baseline.md); preserves [ADR 0003](./0003-structured-answer-citation-contract.md); reuses backend pattern from [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) / [ADR 0020](./0020-protocol-based-pluggability.md); follows the retrieval refactor that landed in [#342](https://github.com/hskim-solv/BidMate-DocAgent/pull/342) + [#358](https://github.com/hskim-solv/BidMate-DocAgent/pull/358)
- **Deciders**: hskim

## Context

Retrieval in [`rag_retrieval.retrieve_candidates`](../../rag_retrieval.py) embeds the
raw user query, then scores chunks via dense cosine + lexical Jaccard
+ metadata + (optionally) BM25 before fusion / rerank. The dense
embedding compares one short, often colloquial Korean query against
formal `합니다`-체 RFP passages — exactly the kind of vocabulary gap
that motivated [Gao et al. 2022's HyDE](https://arxiv.org/abs/2212.10496)
on TREC. Failure-analysis traces on the public synthetic set repeatedly
show top-K misses where the gold chunk uses domain-specific 행정 vocabulary
that the query does not.

After PR #342 split `retrieve()` into `retrieve_candidates` +
`apply_fusion_and_reranking`, and PR #358 introduced the `Reranker`
Protocol, the dense-embedding call site is a single line
(now in [`rag_retrieval.retrieve_candidates`](../../rag_retrieval.py), extracted from `rag_core.py:L1780` in PR-H1b / issue #461) — a clean seam for a
pre-retrieval query-rewrite stage. The question is not *whether* HyDE
should plug in here, but how to add it without:

1. shifting the bit-identical `naive_baseline` golden
   (`tests/data/naive_baseline_top_k.json`, ADR 0001 invariant);
2. coupling HyDE to the `Reranker` Protocol — those are different
   pipeline stages with different I/O shapes; and
3. silently changing BM25 / lexical / metadata scoring, whose tokens
   come from upstream `analysis` (not the raw query string) and should
   stay invariant under query expansion.

## Decision

HyDE query expansion is permitted as an **additive** ablation path,
not a replacement, via a dedicated Protocol seam parallel to (and
separate from) the `Reranker` Protocol of ADR 0020.

- A new module [`rag_query_expansion.py`](../../rag_query_expansion.py)
  defines:
  - `@runtime_checkable QueryExpander` Protocol with one method —
    `expand(query: str, *, plan: dict) -> tuple[str, dict]`.
  - `IdentityExpander` (default) — returns the query unchanged, meta
    `{"backend": "identity", "fell_back": False}`. Deterministic, no
    network, no SDK requirement.
  - `HyDEExpander` (opt-in) — lazy-imports `anthropic`, generates a
    2-3 sentence hypothetical RFP-style answer via
    `claude-haiku-4-5-20251001`, returns the passage. **Never-raise**:
    any backend failure (SDK missing, key missing, API error, empty
    response) returns `(query, meta_with_fell_back=True)`. No exception
    escapes into retrieval orchestration.
  - `default_expander(plan)` factory — dispatches on
    `plan["query_expansion"]` (`"identity"` | `"hyde"`,
    case-insensitive); unknown values silently fall through to identity.
- A new `query_expansion` key in `PIPELINE_CONFIG_KEYS`
  ([`rag_pipeline_presets.py`](../../rag_pipeline_presets.py)).
  `naive_baseline`, `agentic_full`, and `agentic_full_llm` all carry
  `query_expansion: "identity"` so existing eval rows stay bit-equal.
- A new ablation row `full_hyde` in
  [`eval/config.yaml`](../../eval/config.yaml) sets
  `query_expansion: hyde`. Under public CI (no `ANTHROPIC_API_KEY`)
  the never-raise fallback makes `full_hyde` byte-equal to `full` on
  `eval_summary.json`. The row is meaningful when an operator runs
  `BIDMATE_QUERY_EXPANSION_BACKEND=hyde` with a key in scope.
- `rag_retrieval.retrieve_candidates` calls `default_expander(plan)` once,
  passes the returned text to `embed_query_for_index`, and writes
  `plan["query_expansion_meta"]`. The raw `query` parameter is
  unchanged; BM25 / lexical / metadata branches downstream consume
  `analysis.tokens` so they remain invariant.

### Contract preserved (ADR 0001, ADR 0003)

- `naive_baseline` keeps `query_expansion: "identity"`. The
  identity passthrough returns `query == query` (Python identity by
  string equality), so `embed_query_for_index(expanded, …)` is byte-
  identical to the pre-PR `embed_query_for_index(query, …)`. The
  golden `tests/data/naive_baseline_top_k.json` is unchanged and
  `tests/test_naive_baseline_ranking_invariance.py` is the gate.
- ADR 0003's `schema_version: 2` is untouched. HyDE never sees
  `claims`, `citations`, or any answer field — it operates strictly
  before retrieval scoring.

### Backend pluggability

Reuses the ADR 0011 / ADR 0020 backend pattern:
`BIDMATE_QUERY_EXPANSION_BACKEND`:

- `identity` (default) — no LLM, no network. Same as not setting it.
- `hyde` — Anthropic Claude API (Haiku 4.5 default;
  `BIDMATE_QUERY_EXPANSION_MODEL` overrides). Requires
  `ANTHROPIC_API_KEY`. Single-shot prompt; temperature 0.0; system
  prompt cached via `cache_control: ephemeral` so cost on a repeated
  eval run is amortized after the first call.

### Cadence

- **Public synthetic CI**: identity backend. `full_hyde` row appears
  in `eval_summary.json` byte-equal to `full` (fallback path keeps the
  golden stable). The row exercises the plumbing; the LLM column is
  not a quality claim on the public surface.
- **Real-data eval**: `BIDMATE_QUERY_EXPANSION_BACKEND=hyde`. Per-query
  expanded passages stay local (ADR 0005); aggregate metric deltas
  (recall@k, citation_precision, claim_alignment) commit through the
  ADR 0005 aggregate boundary.
- **Live demo**: identity backend by default. A future toggle could
  flip to hyde on user request — out of scope here.

## Consequences

**Wins**

- The retrieval surface gains a query-side LLM rewrite that mirrors
  the answer-side LLM synthesis already present (ADR 0011). The eval
  matrix grows by one column; the `full_hyde` delta against `full` is
  always visible (or, under CI fallback, demonstrably zero).
- Mechanically additive: ADR 0001's invariant is preserved by a
  default-value choice (`"identity"`) and a passthrough class, both
  testable. Removing HyDE later is a one-line eval/config.yaml diff;
  no schema bump required.
- A second Protocol that follows ADR 0020 strengthens the case for
  Protocol-based pluggability as a repo idiom (VectorStore #176 →
  Reranker #345 → QueryExpander #396).
- Sets up the multi-query ablation as a natural follow-up — it would
  add a second `QueryExpander` implementation (e.g. `MultiQueryExpander`)
  alongside `HyDEExpander`. No new Protocol needed.

**Costs**

- One more environment variable family for users to understand.
  Mitigated by the default being `identity` (no key, no SDK, no
  behavior change). The variable family mirrors `BIDMATE_SYNTHESIS_*`
  and `BIDMATE_RERANK_*` exactly.
- Token spend per live-eval run on the hyde column. Bounded by manual
  cadence on real-data (~ 100 cases × cached system prompt × Haiku
  pricing). At Haiku list-price ($1 / 1M input, $5 / 1M output) the
  marginal cost per case is < $0.001 — well under the ADR 0011
  envelope.
- An extra Protocol module to maintain. Mitigated by the fact that
  `IdentityExpander` is 12 lines and `HyDEExpander` is mostly
  prompt + never-raise wrapping; the surface is genuinely small.

**Constraints (unchanged)**

- ADR 0001: `naive_baseline` carries `query_expansion: "identity"`
  and the golden invariance test is the merge gate.
- ADR 0003: answer schema and `claims` / `citations` are untouched.
  No `schema_version` bump.
- ADR 0005: per-case expanded passages stay local. Aggregate deltas
  commit through the existing aggregate boundary.
- ADR 0020: the new Protocol is a sibling of `Reranker`, not a
  reuse — see "Alternatives" below.

## Alternatives considered

- **Replace the raw query with HyDE everywhere.** Rejected: conflicts
  with ADR 0001's preservation argument. Also breaks BM25 / lexical
  parity, since those tokens come from `analysis` upstream and would
  need a parallel rewrite. The dense-only seam at `retrieve_candidates`
  line 1780 is the minimum-surface-area insertion point.
- **Reuse the `Reranker` Protocol for HyDE.** Rejected: `Reranker.rerank`
  takes `(query, list[chunk_dict])` and returns reordered chunks; HyDE
  takes `query` and returns a string. The signatures and the pipeline
  stages are different (post-retrieval reorder vs pre-retrieval
  rewrite). Cramming both into one Protocol would force a tagged-union
  return type and obscure the pipeline shape. ADR 0020 already says
  pluggability via single-responsibility Protocols is the idiom — that
  argument cuts both ways here.
- **Add HyDE behind a CLI flag, not a named preset / ablation row.**
  Rejected: ADR 0001 / ADR 0011's "silent paths rot" argument applies.
  If HyDE is worth shipping, the `full_hyde` row should run on every
  eval invocation so its delta against `full` is always visible (or,
  under fallback, provably zero on the synthetic surface).
- **Generate multiple hypothetical passages and fuse the embeddings
  (multi-query HyDE).** Rejected for this ADR: bigger surface area
  (fusion strategy: average? max-pool? RRF on retrieved candidates?)
  and a fusion knob that interacts with the existing RRF in
  `apply_fusion_and_reranking`. Tracked as a follow-up issue; would
  add a `MultiQueryExpander` implementation under the same Protocol.
- **Pin HyDE prompt to Korean public-sector RFP language exclusively.**
  Considered, not adopted in this PR: prompt tuning needs the real-eval
  delta to inform the loop. The current bilingual prompt asks for
  formal Korean 합니다-체 output and is a single-shot baseline. A
  follow-up issue tracks Korean-RFP genre fine-tuning once we have
  one real-eval cycle's evidence to point at.
