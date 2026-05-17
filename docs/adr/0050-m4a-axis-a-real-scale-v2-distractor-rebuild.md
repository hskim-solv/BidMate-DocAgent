# 0050: M4-A axis-A real_scale_v2_distractor rebuild + H/I/J/K corpus expansion

- **Status**: proposed
- **Date**: 2026-05-17
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (naive_baseline ranking invariance), [ADR 0003](./0003-structured-answer-citation-contract.md) (answer contract schema_version=2), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) (eval split boundary), [ADR 0030](./0030-leaderboard-silence-threshold.md) (silence threshold; axis-A signal recovery), [ADR 0044](./0044-realN-eval-case-expansion.md) (realN case expansion lineage), issue [#911](https://github.com/hskim-solv/BidMate-DocAgent/issues/911) (this ADR)

## Context

axis-A annotation v1 capped synthetic doc-A/B/C at 9 sections each. Every measured run on the public-synthetic surface returned 13/13 PASS — a **ceiling effect** that silently saturated the axis-A signal. Phase 1 Step 2.5 trajectory dumps (PR #910) had no axis-A discriminating power because every case fit inside the 9-section budget.

A 100-document profiling pass on the private corpus (`docs/eval/axis-a-rebuild/axis_b_real_measurement.md` v4) gave the calibration anchor: Upstage `heading1` median ≈ 100 main headings/doc, kordoc cross-checked median 39,511 Korean chars/doc. v1's 9 sections was 1/10 the real distribution — every axis-A measurement was answering "does the pipeline handle tiny portfolios" rather than "does it handle real RFPs."

Separately, four corpus variants were drafted for the Phase 1 Step 3 (n=200) expansion: **H** (long-context marker, 70KB body), **I** (distractor marker — adversarial near-miss sections), **J** (lexical-overlap — vocabulary that collides with golden top-k queries), **K** (medical-imaging domain — vocabulary shift). All four are *future hooks* (consumer count 0 inside this PR) but landing them now keeps the corpus expansion stack additive rather than touching axis-A twice.

## Decision

Adopt `axis_a_scale="real_scale_v2_distractor"` as the new axis-A annotation scale for synthetic doc-A/B/C, and add four new corpus files H/I/J/K to `data/raw/`.

- **Scale anchor**: Upstage `heading1` equivalence — sections are top-level outline entries, sub-bullets and table rows do not count. Section counts: doc-A = 103, doc-B = 105, doc-C = 102.
- **Six supporting metadata fields** added per doc (additive — `evidence[].metadata` is open per ADR 0003): `axis_a_acceptance_verdict`, `axis_a_scale_anchor`, `axis_a_scale_distractor_ref`, `axis_a_scale_measurement_ref`, `axis_a_scale_outline_ref`, `section_definition`.
- **Reference documents** that the metadata cites (`distractor_definitions.md`, `m4a_doc_{a,b,c}_outline.md`, `axis_b_real_measurement.md`) move from `reports/axis_a_rebuild/` (gitignored under the `reports/*` rule) to `docs/eval/axis-a-rebuild/` so the cited URLs resolve in-tree.
- **H/I/J/K** are committed but unused — no preset, no eval config, no test references them inside this PR. They become hooks for the Phase 1 Step 3 n=200 expansion.
- **Index + golden regenerated** (`data/index/{index.json,embeddings.npy}` + `tests/data/{naive_baseline_top_k,answer_contract_shape}.json`). chunks: 9 → 383 (~42× growth, driven by the 9 → 310 section-count fan-out and the 4 new corpora).
- **ADR 0001 naive_baseline scoring logic untouched**. The golden shift is the *necessary consequence* of changing the corpus, not a ranking-algorithm change — `naive_baseline_top_k.json` records new (chunk_id, score) pairs against the new corpus, but the same `rag_core.run_rag_query(pipeline="naive_baseline")` call produces them.
- **ADR 0003 answer contract `schema_version=2` preserved**. The new metadata fields are additive inside `evidence[].metadata`; the contract surface (`answer.{status, status_reason, query_type, claims, summary, insufficiency}` + top-level `evidence` + `answer_text`) is shape-identical.

## Consequences

- **axis-A signal capacity recovered**. The 9-section ceiling is gone — axis-A measurements can now distinguish portfolios with 100+ sections from ones with 50 from ones with 10. The 13/13 saturation is expected to spread into a measurable pass/fail distribution as Phase 1 Step 3 cases land.
- **Index 5MB → not yet** (`embeddings.npy` 13,952 → 588,416 bytes, ~42×). Below the 50MB git-friendly threshold; if Phase 1 Step 3 adds n=200 cases the binary will need an LFS reconsideration.
- **`tests/data/naive_baseline_top_k.json` golden shifted**. New corpus produces new chunk_ids and scores. The test's invariance contract — "same pipeline call gives same answer" — is preserved (`tests/test_naive_baseline_ranking_invariance.py` passes against the new golden); the underlying expected values legitimately drift.
- **H/I/J/K consumer-0 until Phase 1 Step 3**. The four new corpus files exist but no preset or eval case loads them yet. This is intentional staging — landing them inside the corpus rebuild keeps the corpus-expansion stack to one ADR, but it does create a window where the files are declarative-only.
- **Reference doc location migrated**. The `reports/axis_a_rebuild/*.md` paths cited from prior measurement notes and from the metadata `*_ref` fields are now `docs/eval/axis-a-rebuild/*.md`. Five files (axis_b_real_measurement, distractor_definitions, m4a_doc_{a,b,c}_outline) plus their `*_ref` strings inside doc-A/B/C JSON are sed-rewritten in lockstep. Operator-local raw measurement files (`reports/axis_a_rebuild/*.json`) stay outside the tree as audit-trail (not reproducibility surface).
- **ADR 0001 baseline-comparison contract intact**. `make real-eval-delta` runs against the new index — its `kordoc_rate` / `by_metadata_field` / `abstention_calibration` aggregations are corpus-shaped (deterministic for a given corpus), so the metric reads shift but the *contract* (those keys present, values within their declared ranges) holds.
- **`reports/axis_a_rebuild/` directory remains operator-local**. The directory is still gitignored under `reports/*`; only the five `.md` reference documents migrate into the tree. The raw JSON measurement dumps stay local.

## Alternatives considered

- **Keep v1 9-section scale and defer rebuild to Phase 1 Step 3**. Rejected: the 13/13 ceiling makes every measurement between now and Phase 1 Step 3 axis-A-blind. Phase 1 Step 2.5 trajectory dumps (just merged in PR #910) lose half their diagnostic value if axis-A is saturated for every case in the trajectory.
- **Rebuild doc-A only, hold doc-B/C at v1**. Rejected: axis-A comparisons across docs become noisy when one doc is on a different scale. Single-doc rebuild trades the ceiling problem for a calibration problem.
- **Split this into 2 PRs (axis-A rebuild first, H/I/J/K corpus second)**. Rejected: the H/I/J/K corpus also forces an `data/index/` rebuild, which forces a golden regeneration. Doing index rebuild + golden regen twice doubles the main-red risk window for no organizational benefit — both are pure corpus changes with no production-code impact.
- **Use a smaller scale anchor (e.g. Upstage `heading2` instead of `heading1`)**. Rejected: 100-doc measurement showed `heading1` is the level that matches "main section" in domain experts' reading model; `heading2` would produce 300+ sections per doc (table rows, sub-clauses), past the chunking-strategy headroom.

## Verification

<!-- verifies-key: data/raw/rfp_agency_a_ai_quality.json:"axis_a_scale": "real_scale_v2_distractor" -->
<!-- verifies-key: data/raw/rfp_agency_b_mlops_governance.json:"axis_a_scale": "real_scale_v2_distractor" -->
<!-- verifies-key: data/raw/rfp_agency_c_chatbot.json:"axis_a_scale": "real_scale_v2_distractor" -->
<!-- verifies-key: docs/eval/axis-a-rebuild/distractor_definitions.md:real_scale_v2_distractor -->
<!-- verifies-key: tests/test_naive_baseline_ranking_invariance.py:GOLDEN_PATH -->
<!-- verifies-key: tests/test_answer_contract_snapshot.py:GOLDEN_PATH -->
