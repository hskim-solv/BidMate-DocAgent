# real100_v2 Aggregate Artifacts

`real100_v2` is a private RFP benchmark rebuild. This directory may contain only aggregate-only public-safe artifacts.

Allowed files:

- `parse_inventory.aggregate.json`
- `question_distribution.aggregate.json`
- `benchmark_tiers.aggregate.json`
- `baseline.aggregate.json`
- `metric_suite.aggregate.json`
- `metric_suite.md`
- `retrieval_diagnostics.aggregate.json`
- `README.md`

Raw eval summaries, traces, questions, answers, evidence, document IDs, chunk IDs, filenames, paths, parsed Markdown, converted PDFs, and per-case rows must remain ignored.

Private parse checkpoints from `scripts/build_private_real100_v2_parallel.py` are allowed only under ignored private index/output paths.

Interpretation policy: compare overall plus every tier. These artifacts are for interpretation and regression analysis, not cherry-picking improved slices for headline claims.
