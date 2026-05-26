# Hybrid Sweep Decision

이 문서는 private hybrid BM25+dense RRF sweep의 winner/no-winner 판정 규칙을
고정한다. 산출물은 aggregate-only이며 raw query, answer, evidence, doc_id,
chunk_id, filename, local path를 포함하지 않는다.

## Decision Surface

- Input: local `aggregate.json` from the private hybrid sweep harness.
- Public-safe outputs:
  - `reports/retrieval/hybrid_sweep_summary.md`
  - `reports/retrieval/hybrid_sweep_summary.aggregate.json`
- Timestamped sweep run directories remain gitignored.
- Retrieval, verifier, prompt, chunking, reranker, answer generation, and runtime
  defaults are unchanged.

## Winner Rule

A hybrid variant is `winner_found` only when it has a material Recall@5 or
Recall@10 gain against `full_dense_top20` and does not regress on all guardrails:

- MRR@5 and nDCG@5 must not regress.
- Citation precision or citation accuracy must not regress. If those are absent,
  the citation guardrail aggregate must not worsen.
- Latency p50 and p95 must remain within the configured tolerance.

Recall@10-only gains are insufficient. For this DocAgent system, the right
evidence must appear early enough for answer generation and citation selection;
a recall gain that pushes gold evidence lower in rank can still reduce MRR@5,
nDCG@5, and citation quality. If citation or latency also worsens, the hybrid
variant is not a product improvement even if Recall@10 moves upward.

## #1448 Reference

PR #1448 remains `NO-GO`: its single hybrid arm improved Recall@10 slightly but
regressed MRR@5, nDCG@5, citation accuracy, and latency. The sweep can overturn
that only if a new candidate is classified as `winner_found`.

## Final Decision Mapping

- `winner_found` -> `promote selected hybrid variant`
- all candidates missing required comparable metrics -> `mark hybrid as failed experiment`
- otherwise -> `keep dense baseline and abandon hybrid for now`

The other possible next-step choices, `run reranker after hybrid` and
`run metadata/page-aware recovery first`, require separate evidence surfaces and
are not selected by this summarizer.
