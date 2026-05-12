# 0018: Korean public RAG bench as a supplementary out-of-domain surface

- **Status**: accepted
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (baseline preserved), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) (eval split discipline), [ADR 0012](./0012-llm-judge-on-public-synthetic.md) (additive surface pattern), [`eval/korean_public/`](../../eval/korean_public/), issue #295

## Context

The "Korean stack" portfolio positioning currently lives in code —
`text_normalize.py`'s 조사 stripper, `apply_comparison_balance` for
RFP-style multi-doc queries, alias auto-extraction — but has **no
publicly verifiable Korean-language number** backing it. The two
existing eval surfaces both have this gap:

- **Public synthetic** (`eval/config.yaml`, n=42): in-domain
  hand-written RFP cases. Reviewers can reproduce the numbers but
  the corpus *is* the same shape the pipeline was tuned on.
- **Private real-data** (operator-side, n=21, ADR 0005 commit
  boundary): in-domain real RFPs. Reviewers cannot reproduce.

A senior reviewer asking "한국어 일반 텍스트에서 retrieval / citation
파이프라인이 어떻게 동작합니까?" has nothing in the repo to point at.
Adding *any* commodity Korean RAG benchmark — even a low-score one —
closes this gap with a verifiable artifact.

KorQuAD 2.x is the dominant Korean MRC benchmark (CC BY-ND 2.0 KR,
SQuAD-shaped, long-document Wikipedia contexts). Its dev split is
publicly downloadable from the official mirror.

## Decision

Add a **supplementary, never-replacing, never-CI-gating** eval surface
that runs the existing `rag_core.run_rag_query` pipeline against a
deterministic 150-question sample of KorQuAD 2.1 dev. The surface is
isolated under `eval/korean_public/` so the ADR 0005 spirit
(synthetic-CI vs private-real-data separation) is preserved as a
*three-way* split going forward.

Concretely:

1. `eval/korean_public/fetch_korquad.py` downloads the official
   KorQuAD 2.1 dev_00 ZIP, strips HTML, deterministically samples
   N=150 answerable scoreable questions with `seed=17`. The raw
   archive is cached under `data/korean_public/` (gitignored — we
   never redistribute the corpus). The sample file itself
   (`data/korean_public/korquad_dev_sample.json`) is also gitignored;
   only its SHA-256 (printed by the fetcher) is suitable to commit if
   reproducibility recording is desired.
2. `eval/korean_public/run.py` builds the corpus (one document per
   sampled article, using the existing `build_index_payload_from_documents`
   path) and reports four metrics with bootstrap 95% CIs (seed=17,
   1000 resamples, the same machinery as the synthetic surface):
   - `retrieval_recall_at_top_k` (default top-k=5)
   - `answer_substring_match` (gold answer as substring of
     `answer_text`)
   - `citation_doc_precision` (citations pointing to the gold article)
   - `citation_coverage` (fraction of queries that produced any
     citation)
3. Output lives at `reports/korean_public/eval_summary.json`
   (gitignored under the existing `reports/*` pattern).
4. `make korean-public-eval` runs the script end-to-end.
5. **The synthetic CI eval (`pr-eval.yml`) does not invoke this
   surface.** This is intentional: KorQuAD numbers are properties of
   the upstream dataset distribution, not of pipeline correctness.
   Letting them gate PRs would punish refactors that don't change
   the pipeline at all.

## Consequences

Easier:

- The "한국어 일반 텍스트 generalization" question has a concrete,
  reproducible number a reviewer can run in <2 minutes.
- The same `bootstrap_ci` machinery + reproducibility-hash recipe
  from the synthetic surface extends naturally — running the eval
  on a Linux host should produce the same headline numbers (modulo
  wall-clock latency) as on macOS.
- New Korean public benchmarks (AI Hub 행정문서, MIRAcL Korean, …)
  can land as siblings under `eval/korean_public/` with the same
  shape — they slot in next to KorQuAD, not on top of it.

Costs / honesty:

- **The headline numbers will look bad relative to the synthetic
  surface.** First-cycle measurement on the hashing backend +
  naive_baseline pipeline returns retrieval_recall@5 ~ 0.500 and
  answer_substring_match ~ 0.013. **This is correct and
  load-bearing**: it documents that the pipeline is RFP-domain-
  specialized, not a general Korean QA system. README + senior-
  positioning will frame this as a *generalization sanity check*,
  not a target benchmark.
- The raw KorQuAD archive is large (~93MB). The fetch step is
  not free; the script caches aggressively so subsequent runs are
  near-instant.
- KorQuAD 2.x has many short-answer cases ("1", "1,200만 화소").
  `answer_substring_match` is permissive in their favor; an
  exact-match metric would score even lower. We report substring
  match by convention and document the trade-off in
  `eval/korean_public/README.md`.

What this ADR **does not** decide:

- Whether to commit a sample-file hash for cross-host reproducibility
  enforcement — separate decision once a real baseline is desired.
- Whether to fold KorQuAD numbers into the README headline metric
  table — initial cycle keeps them in a separate section to avoid
  conflating in-domain and out-of-domain claims.
- Whether to expand to KorQuAD 1.0 (short SQuAD-style passages) —
  out of scope; 2.x is the closer-to-RFP-shape variant.

## Alternatives considered

- **AI Hub 한국어 행정문서 QA** — most domain-matched, but the
  distribution requires Korean academic/institutional login. Killing
  reviewer reproducibility ("download requires Korean academic
  email") was a hard no.
- **MIRAcL Korean dev** — retrieval-only multilingual benchmark, no
  answer-string ground truth. Would test only one of our three
  signals; misses the citation-grounding axis the synthetic surface
  measures.
- **Build a small in-house Korean RAG fixture** — sidesteps license
  issues but adds yet another in-house dataset reviewers cannot
  validate against the outside world.
- **Replace the synthetic surface with KorQuAD** — would violate
  ADR 0001 (preserve the baseline) and ADR 0005 (synthetic-CI lives
  for contract testing). Strict additive-surface discipline applies
  here just as it did for ADRs 0011, 0013, 0014, 0015, 0017.
