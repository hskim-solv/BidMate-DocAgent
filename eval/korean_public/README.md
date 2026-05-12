# Korean public RAG bench surface

Supplementary out-of-domain Korean evaluation surface for the
BidMate pipeline. **Never CI-gated** and **never replaces** the
public synthetic ([`eval/config.yaml`](../config.yaml)) or private
real-data surfaces. See [ADR 0018](../../docs/adr/0018-korean-public-rag-bench.md)
for the scope boundary and rationale.

## Quick start

```bash
make korean-public-eval
```

This is one-time-download + run:

1. `make korean-public-fetch` (auto-run as a dependency) downloads the
   official **KorQuAD 2.1 dev_00** ZIP (~93 MB) into
   `data/korean_public/` (gitignored), strips HTML, deterministically
   samples N=150 answerable questions with seed=17.
2. `python eval/korean_public/run.py` builds an in-memory index over
   the sampled articles, runs each question through `rag_core.run_rag_query`
   (`naive_baseline` pipeline by default, hashing embedding backend),
   and writes aggregate + per-case results to
   `reports/korean_public/eval_summary.json` (gitignored).

The fetcher prints a `sample sha256:` line — use it to verify the
sample is byte-identical across hosts.

## Metrics

All metrics are reported with bootstrap 95% CI bands (seed=17, 1000
resamples — the same machinery as the synthetic surface).

| metric | what it tests |
|---|---|
| `retrieval_recall_at_top_k` | Did any of the top-k retrieved chunks come from the gold article? |
| `answer_substring_match` | Is the gold answer string a substring of `answer_text`? |
| `citation_doc_precision` | Of the citations produced, what fraction point to the gold article? |
| `citation_coverage` | Fraction of cases that produced *any* citation. |
| `latency.{p50_ms, p95_ms}` | Wall-clock per query (informational only). |

## Why the numbers will be low

Reading the headline numbers as a *cross-domain transfer* signal,
not as a Korean-NLP benchmark score:

* The pipeline is RFP-domain-specialized — `metadata_first` retrieval,
  comparison-aware top-k, 조사-stripped tokenizer, alias auto-extraction
  are tuned for structured Korean RFP text.
* KorQuAD 2.x is freeform Wikipedia HTML. Retrieval falls back to
  pure dense (hashing backend) with no metadata to filter on.
* Answer policy is extractive: the system emits ground-truthy
  evidence chunks with citations, but does NOT reformulate them to
  match short-phrase answers like `"1"` or `"1,200만 화소"`.
  `answer_substring_match` measures whether the gold string survives
  *anywhere* in the rendered answer, which is the most generous
  rendering of "did we cite the right place".

Low scores here are the *expected* trade-off of a domain-specialized
system, documented for the senior reviewer who asks "한국어 일반 텍스트
에서도 동작합니까?".

## What this surface deliberately does **not** measure

- **SOTA Korean RAG** — not the goal. Use HAE-RAE, K-MMLU, or KLUE-MRC
  leaderboards for that comparison.
- **Predictiveness of RFP performance** — KorQuAD scores do not
  forecast our private 100-doc real-data numbers. The two surfaces
  measure orthogonal axes.
- **Anything CI-gating** — the workflow never invokes this surface,
  so a slow refactor that doesn't change pipeline correctness will
  not be punished by KorQuAD distribution drift.

## Files

| path | purpose |
|---|---|
| `fetch_korquad.py` | Download + sample + write `korquad_dev_sample.json`. |
| `run.py` | Build index, run pipeline, write `eval_summary.json`. |
| `data/korean_public/` | Raw zip + sample JSON (gitignored). |
| `reports/korean_public/` | Per-run aggregates (gitignored). |

## License

KorQuAD 2.x is licensed CC BY-ND 2.0 KR (©LG CNS). We fetch the
dataset on demand and never redistribute it; the sampled derivative
also stays gitignored. When publishing any downstream metric,
attribute the source as `KorQuAD 2.1 (©LG CNS, CC BY-ND 2.0 KR)`.
