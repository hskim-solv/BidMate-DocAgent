# 0002: Metadata-first retrieval strategy

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: [`rag_core.py`](../../rag_core.py), [`docs/design-background.md`](../design-background.md), [`docs/real-data/real-data-failure-taxonomy.md`](../real-data/real-data-failure-taxonomy.md)

## Context

RFP queries are usually about *a specific agency / project / section*
(e.g. "기관 A의 보안 통제 요구사항"). Generic dense or BM25 retrieval
returns lexically similar chunks across the corpus and frequently
mixes the wrong agency's content with the right one. The failure mode
is silent: the answer can look plausible while citing the wrong
document, which is exactly what a reviewer cannot accept.

The corpus, by contrast, carries reliable metadata: `agency`,
`project`, `section`, document type. Anchoring retrieval to those
facets first turns out to be the cheapest large win available.

## Decision

The default retrieval strategy resolves a metadata target (agency /
project / section) **before** ranking chunks by content similarity.
When metadata is resolvable, retrieval is filtered to the matching
slice; only within that slice are content scores used. When metadata
is ambiguous, the system surfaces the ambiguity rather than picking
silently. When no metadata signal applies, retrieval falls back to
content-only ranking.

The knob: the `metadata_first` flag in the pipeline preset. It is
`true` for `agentic_full` and `false` for `naive_baseline`, which
makes the contribution measurable as an ablation
(`no_metadata_first`).

## Consequences

**Wins**

- Cross-agency contamination drops sharply on the comparison and
  single-doc query types where it dominated the failure mix.
- The `citation_doc_precision` metric, which previously punished
  metadata-blind retrievals, becomes usable as a quality signal
  rather than a noise floor.
- Reviewer-facing artifacts (`outputs/answer.json`,
  `reports/eval_summary.json`) include a metadata-resolution
  diagnostic block, so failures are debuggable without re-running
  the query.

**Costs**

- Retrieval quality is now bounded by metadata-extraction quality.
  When the corpus has imperfect metadata, this strategy concentrates
  the damage instead of averaging it out.
- A whole new failure category emerges — *metadata ambiguity* — that
  requires its own handling (see issue #72). The system must surface
  the ambiguity rather than guessing, which complicates the answer
  contract (ADR 0003).

## Alternatives considered

- **Content-only retrieval with reranker.** Rejected as the default:
  it still mixes agencies on the queries that matter most.
  Preserved as an ablation (`naive_baseline`, `no_metadata_first`)
  for comparison.
- **Hybrid scoring with a metadata bonus term.** Rejected: harder to
  reason about, harder to ablate cleanly, and prone to silent failure
  when the bonus is tuned wrong.
