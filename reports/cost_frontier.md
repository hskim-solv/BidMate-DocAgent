# Cost-accuracy frontier (ADR 0038)

Acceptable floor: accuracy > 0.70. CI band: 95% bootstrap (when populated). Self-hosted ablations are plotted at x=0 per ADR 0038.

## Anchors

- **Accuracy ceiling** (in-repo, self-hosted): `no_verifier_retry` — 0.805 [0.720–0.890]
- **Production sweet spot** (external, lowest-cost CI_lo > 0.70): — *no qualifying external backend*

## All points

| On frontier | Run | Cost (USD) | Accuracy | 95% CI | Type |
|---|---|---:|---:|---|---|
| ✓ | no_verifier_retry | $0 (self-hosted) | 0.805 | [0.720–0.890] | self-hosted |
| ✓ | retrieval_only | $0 (self-hosted) | 0.805 | [0.720–0.890] | self-hosted |
|  | naive_baseline | $0 (self-hosted) | 0.744 | [0.646–0.829] | self-hosted |
|  | naive_baseline_finetuned | $0 (self-hosted) | 0.744 | [0.646–0.829] | self-hosted |
|  | full | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | full_llm | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | full_llm_metadata | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | hierarchical | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | hybrid_bm25 | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | hybrid_bm25_k10 | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | hybrid_bm25_k30 | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | hybrid_bm25_k100 | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | hybrid_bm25_extra_stopwords | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | hybrid_bm25_k30_extra | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | full_kiwi | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | full_mecab | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | full_khaiii | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | full_reranker | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | full_hyde | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | agentic_full_finetuned | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | hwp_csv_text | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | hwp_native | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | hwp_native_tables | $0 (self-hosted) | 0.695 | [0.598–0.793] | self-hosted |
|  | m3_full | $0 (self-hosted) | 0.683 | [0.585–0.780] | self-hosted |
|  | no_rerank | $0 (self-hosted) | 0.671 | [0.561–0.768] | self-hosted |
|  | no_metadata_first | $0 (self-hosted) | 0.659 | [0.549–0.768] | self-hosted |

Frontier members (2): no_verifier_retry, retrieval_only.
