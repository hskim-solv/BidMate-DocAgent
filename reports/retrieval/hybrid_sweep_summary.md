# Hybrid Sweep Decision

This report is aggregate-only. It contains no raw questions, answers, evidence text, document identifiers, chunk identifiers, filenames, or local paths.

## Decision

- Final decision: `keep dense baseline and abandon hybrid for now`
- Selected variant: `hybrid_bm25_dense_v1_k20_dense100_bm2520`
- #1448 reference: `NO-GO unless a sweep candidate is classified as winner_found`

Recall@10-only gains are insufficient when MRR@5, nDCG@5, citation, or latency regresses because the system must retrieve the right evidence early, cite it correctly, and stay within the existing latency envelope.

## Dense Baseline

| Variant | Recall@5 | Recall@10 | MRR@5 | nDCG@5 | Citation | p50 ms | p95 ms | retrieval_miss |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| full_dense_top20 | 0.195 | 0.254 | 0.410 | 0.267 | - | 1318.5 | 3162.2 | 0 |

## Hybrid Variants

| Variant | k | Dense pool | BM25 pool | dR@5 | dR@10 | dMRR@5 | dnDCG@5 | dCitation | dP50 ms | dP95 ms | dMiss | Classification |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| hybrid_bm25_dense_v1_k20_dense20_bm2520 | 20 | 20 | 20 | -0.005 | +0.003 | -0.091 | -0.048 | 0.000 | +452.8 | -564.0 | 0 | ranking_regression, latency_regression |
| hybrid_bm25_dense_v1_k20_dense20_bm2550 | 20 | 20 | 50 | -0.017 | -0.005 | -0.103 | -0.061 | 0.000 | +790.5 | +46.5 | 0 | ranking_regression, latency_regression |
| hybrid_bm25_dense_v1_k20_dense20_bm25100 | 20 | 20 | 100 | -0.016 | -0.007 | -0.107 | -0.061 | 0.000 | +592.1 | -384.6 | 0 | ranking_regression, latency_regression |
| hybrid_bm25_dense_v1_k20_dense50_bm2520 | 20 | 50 | 20 | -0.011 | +0.005 | -0.112 | -0.059 | 0.000 | +1039.9 | +378.4 | 0 | ranking_regression, latency_regression |
| hybrid_bm25_dense_v1_k20_dense50_bm2550 | 20 | 50 | 50 | -0.027 | -0.007 | -0.121 | -0.070 | 0.000 | +1029.4 | +235.7 | 0 | ranking_regression, latency_regression |
| hybrid_bm25_dense_v1_k20_dense50_bm25100 | 20 | 50 | 100 | -0.026 | -0.008 | -0.122 | -0.069 | 0.000 | +1156.8 | +434.0 | 0 | ranking_regression, latency_regression |
| hybrid_bm25_dense_v1_k20_dense100_bm2520 | 20 | 100 | 20 | -0.004 | +0.006 | -0.108 | -0.056 | 0.000 | +296.3 | -849.3 | 0 | recall_only_gain, ranking_regression, latency_regression |
| hybrid_bm25_dense_v1_k20_dense100_bm2550 | 20 | 100 | 50 | -0.017 | -0.006 | -0.116 | -0.065 | 0.000 | +204.6 | -1127.7 | 0 | ranking_regression, latency_regression |
| hybrid_bm25_dense_v1_k20_dense100_bm25100 | 20 | 100 | 100 | -0.016 | -0.006 | -0.117 | -0.065 | 0.000 | +219.2 | -1131.3 | 0 | ranking_regression, latency_regression |
| hybrid_bm25_dense_v1_k60_dense20_bm2520 | 60 | 20 | 20 | -0.005 | +0.003 | -0.087 | -0.047 | 0.000 | +178.7 | -1174.9 | 0 | ranking_regression, latency_regression |
| hybrid_bm25_dense_v1_k60_dense20_bm2550 | 60 | 20 | 50 | -0.021 | -0.005 | -0.107 | -0.064 | 0.000 | +196.4 | -1113.4 | 0 | ranking_regression, latency_regression |
| hybrid_bm25_dense_v1_k60_dense20_bm25100 | 60 | 20 | 100 | -0.024 | -0.010 | -0.133 | -0.076 | 0.000 | +182.9 | -1166.6 | 0 | ranking_regression, latency_regression |
| hybrid_bm25_dense_v1_k60_dense50_bm2520 | 60 | 50 | 20 | -0.017 | +0.001 | -0.113 | -0.062 | 0.000 | +236.8 | -1145.0 | 0 | ranking_regression, latency_regression |
| hybrid_bm25_dense_v1_k60_dense50_bm2550 | 60 | 50 | 50 | -0.034 | -0.017 | -0.134 | -0.080 | +0.008 | +243.4 | -1091.5 | 0 | ranking_regression, citation_regression, latency_regression |
| hybrid_bm25_dense_v1_k60_dense50_bm25100 | 60 | 50 | 100 | -0.053 | -0.027 | -0.162 | -0.100 | +0.051 | +238.9 | -1104.6 | 0 | ranking_regression, citation_regression, latency_regression |
| hybrid_bm25_dense_v1_k60_dense100_bm2520 | 60 | 100 | 20 | -0.013 | +0.001 | -0.120 | -0.064 | 0.000 | +209.0 | -1129.3 | 0 | ranking_regression, latency_regression |
| hybrid_bm25_dense_v1_k60_dense100_bm2550 | 60 | 100 | 50 | -0.020 | -0.004 | -0.132 | -0.075 | 0.000 | +251.5 | -1137.9 | 0 | ranking_regression, latency_regression |
| hybrid_bm25_dense_v1_k60_dense100_bm25100 | 60 | 100 | 100 | -0.037 | -0.016 | -0.150 | -0.091 | +0.017 | +236.2 | -1074.8 | 0 | ranking_regression, citation_regression, latency_regression |
| hybrid_bm25_dense_v1_k100_dense20_bm2520 | 100 | 20 | 20 | -0.005 | +0.003 | -0.088 | -0.048 | 0.000 | +205.2 | -1111.4 | 0 | ranking_regression, latency_regression |
| hybrid_bm25_dense_v1_k100_dense20_bm2550 | 100 | 20 | 50 | -0.021 | -0.005 | -0.108 | -0.065 | 0.000 | +184.0 | -1161.4 | 0 | ranking_regression, latency_regression |
| hybrid_bm25_dense_v1_k100_dense20_bm25100 | 100 | 20 | 100 | -0.024 | -0.010 | -0.134 | -0.077 | 0.000 | -88.6 | -1493.5 | 0 | ranking_regression |
| hybrid_bm25_dense_v1_k100_dense50_bm2520 | 100 | 50 | 20 | -0.017 | +0.001 | -0.115 | -0.062 | 0.000 | -71.5 | -1506.2 | 0 | ranking_regression |
| hybrid_bm25_dense_v1_k100_dense50_bm2550 | 100 | 50 | 50 | -0.034 | -0.017 | -0.137 | -0.080 | +0.008 | -50.2 | -1457.7 | 0 | ranking_regression, citation_regression |
| hybrid_bm25_dense_v1_k100_dense50_bm25100 | 100 | 50 | 100 | -0.053 | -0.030 | -0.164 | -0.100 | +0.059 | -28.5 | -1487.8 | 0 | ranking_regression, citation_regression |
| hybrid_bm25_dense_v1_k100_dense100_bm2520 | 100 | 100 | 20 | -0.018 | +0.001 | -0.124 | -0.067 | 0.000 | -60.9 | -1486.1 | 0 | ranking_regression |
| hybrid_bm25_dense_v1_k100_dense100_bm2550 | 100 | 100 | 50 | -0.026 | -0.005 | -0.136 | -0.079 | 0.000 | -44.6 | -1479.4 | 0 | ranking_regression |
| hybrid_bm25_dense_v1_k100_dense100_bm25100 | 100 | 100 | 100 | -0.044 | -0.020 | -0.160 | -0.097 | +0.034 | -77.9 | -1521.5 | 0 | ranking_regression, citation_regression |

## Notes

- `winner_found` requires a material Recall@5 or Recall@10 gain and no MRR@5, nDCG@5, citation, or latency regression.
- Missing required metrics are classified as `failed_experiment`; missing `retrieval_miss` is displayed as `-`, not zero.
- Timestamped sweep outputs remain local and gitignored.
