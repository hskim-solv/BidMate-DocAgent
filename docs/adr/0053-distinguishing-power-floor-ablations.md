# ADR 0053 — Distinguishing-power floor ablations (`random` retrieval + `single_chunk` preset)

- Status: Proposed
- Date: 2026-05-17
- Authors: Hyunsoo Kim
- Related: ADR 0001 (naive_baseline invariance), ADR 0005 (eval split), ADR 0030 (leaderboard surfaces), ADR 0044 (real-eval n trajectory — being superseded by ADR 0052 in PR-B)
- Issue: #938

## Context

The `eval-framework-progressive-audit` skill (Phase 1, step 2) calls for **three "broken" baselines** whose only job is to fail visibly — `random_retrieval`, `no_verifier`, and `single_chunk`. Any default whose accuracy / groundedness collapses to within noise of one of these is telling us the default isn't doing real work — a Goodhart-style trap where the leaderboard moves but no real capability is being measured.

Current state on `origin/main`:

- ✅ `no_verifier_retry` ablation row already exists in `eval/config.yaml:180` (covers the `no_verifier` floor).
- ❌ No `random_retrieval` row — `VALID_RETRIEVAL_BACKENDS` was `{"dense", "hybrid", "m3"}`. No deterministic random ranking primitive existed.
- ❌ No `single_chunk` preset — every existing preset retrieves `top_k ≥ 4`.

Without these two floors the leaderboard cannot answer **"does our retrieval pull weight?"**. Companion: PR-5b (issue TBD) adds `scripts/distinguishing_power.py` to compute the actual delta-vs-floor signal.

## Decision

1. **Extend `VALID_RETRIEVAL_BACKENDS`** to `{"dense", "hybrid", "m3", "random"}`. The validation lives in `rag_pipeline_presets.py` and is consumed by `rag_query.resolve_pipeline_config`, `rag_core.run_rag_query`, and the per-row eval loader.

2. **Implement `random` as a short-circuit branch** in `rag_retrieval.retrieve_candidates` that fires **after** the metadata filter step but **before** the embedding / BM25 / M3 forward passes. Each filtered candidate gets a uniform score in `[0, 1]` derived from `SHA-256(query + "\x00" + chunk_id)` — deterministic per `(query, chunk_id)` so:
   - The same query produces the same ranking across runs (test-friendly, eval-reproducible).
   - Different queries pull different orderings (avoids degenerate "always return chunk-001" behavior).
   - No model invocation — zero embedding / inference cost. CI-safe by construction.

3. **Add the `single_chunk` pipeline preset** to `PIPELINE_PRESETS` with `top_k=1`, all post-retrieval enhancements off (`metadata_first=False`, `rerank=False`, `rerank_cross_encoder=False`, `verifier_retry=False`), `retrieval_backend="dense"`, `prompt_profile="minimal_grounded_extractive"`. This mirrors what a contributor would reach for without retrieval engineering — the "what if we just grab the closest chunk?" baseline.

4. **Wire two ablation rows in `eval/config.yaml`**:
   - `random_retrieval` — `pipeline: agentic_full` + `retrieval_backend: random` (so we isolate the random-retrieval effect inside the full pipeline shape; the rest of the stack stays on).
   - `single_chunk` — `pipeline: single_chunk` (the preset above carries every other knob).

5. **Lock in via regression tests**: `tests/test_random_retrieval_regression.py` (5 tests: allow-list membership + diagnostics record + top-k differs from dense + determinism + cross-query differentiation) and `tests/test_single_chunk_preset_regression.py` (4 tests: preset shape + top-k=1 end-to-end + no verifier retry).

## Why these two, why now

- **Sequencing with PR-B (ADR 0052, n=21 → n=200 hardcase expansion)**: the distinguishing-power signal is only meaningful at n=200 where the noise floor is below the gap between defaults and floors. PR-5b's first measurement will be against the n=200 baseline, so PR-5a (this ADR) must land **before** the baseline regen so the floor rows are part of the n=200 baseline.aggregate.json. Otherwise the first distinguishing-power measurement would be against a baseline that doesn't contain the floors and would force a second baseline commit.
- **`random_retrieval` first** because it's the cleanest "no signal" reference; `single_chunk` answers a slightly different question ("does multi-chunk retrieval pull weight?"). Together they bracket the two distinguishing-power axes.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **`random.shuffle(candidates)`** instead of SHA-256 hash | Non-deterministic across runs — breaks eval reproducibility (the same eval row would produce different metrics each CI run, masking real regressions and creating flaky failures). |
| **Use Python `random.Random(seed=hash(query))`** | `hash(query)` is salted per process in Python 3 (PEP 456) — would produce different results across processes. SHA-256 is portable. |
| **`single_chunk` as an `eval/config.yaml`-only knob (`top_k: 1` override on `naive_baseline`)** | Loses the preset-level lock-in. A future PR that adds `top_k=4` default would silently break the floor. Preset entry makes the intent explicit and protected by the regression test. |
| **Add `no_filter` and `no_chunking` floors too (the full audit list)** | Out of scope for PR-5a — `no_filter` requires a deeper retrieval-side carve-out, `no_chunking` requires ingest-side changes. Tracked as PR-5c/5d follow-ups if the first measurement justifies them. |

## Consequences

### Positive
- The leaderboard gains two **falsifiable lower bounds** — any future "improvement" that doesn't beat `random_retrieval` is by definition not a real improvement. Direct portfolio claim: "we measure distinguishing power, not just absolute metrics."
- PR-5b's `scripts/distinguishing_power.py` (follow-up) can compute `(default - floor) / (ceiling - floor)` for every leaderboard metric — a single-number "is the signal alive" gauge.
- Zero production code path impact — the `random` short-circuit is opt-in via `retrieval_backend` config; default `dense` is unchanged (ADR 0001 byte-identity invariant preserved).

### Negative
- Adds 2 ablation rows to the eval matrix — `make eval-public` walltime increases by ~2 × current per-row cost. Mitigation: `random` skips the heaviest CI step (embedding), so its per-row cost is ~3× faster than `naive_baseline`; net add is small.
- The `random` branch in `retrieve_candidates` duplicates the candidate-dict build code (~30 LOC) shared with the dense/hybrid/m3 path below. A future cleanup can factor out a `_build_candidate_item` helper if the cost becomes maintenance noise.

### Invariance check
- **ADR 0001 (naive_baseline preset, byte-identity top-k)**: unchanged — `naive_baseline` preset entry and `retrieval_backend="dense"` default are not modified.
- **ADR 0003 (answer contract schema_version=2)**: unchanged — random/single_chunk produce the same evidence-dict shape; the answer renderer is invariant to retrieval backend.
- **ADR 0005 (eval split public/private)**: unchanged — both new rows live in `eval/config.yaml` (public synthetic surface). The real-eval surface (PR-B) consumes the same preset registry so n=200 baseline.aggregate.json will pick up the floors automatically.
- **ADR 0030 (leaderboard surfaces)**: extended, not modified — the two new rows show up as additional columns; no existing column changes.

## Out of scope

- **`scripts/distinguishing_power.py` + first measurement** — PR-5b follow-up. Blocks on n=200 baseline (PR-B), not on PR-5a itself.
- **`no_filter` / `no_chunking` floors** — PR-5c/5d candidates if PR-5b's first measurement shows the existing floors are insufficient.
- **Real-eval `random_retrieval` row in `eval/real_config.local.yaml`** — added in PR-B (paired with baseline regen at n=200) so the eval-row provenance is consistent.
- **Refactor to extract `_build_candidate_item` helper** — defer until cleanup PR; the 30-LOC duplication is intentional clarity, not technical debt yet.

## Verification

<!-- verifies-key: rag_pipeline_presets.py:VALID_RETRIEVAL_BACKENDS -->
<!-- verifies-key: rag_pipeline_presets.py:single_chunk -->
<!-- verifies-key: rag_retrieval.py:retrieval_backend == "random" -->
<!-- verifies-key: tests/test_random_retrieval_regression.py:test_random_is_in_valid_retrieval_backends -->
<!-- verifies-key: tests/test_single_chunk_preset_regression.py:test_single_chunk_preset_shape -->
<!-- verifies-key: eval/config.yaml:random_retrieval -->

## References

- `eval-framework-progressive-audit` skill, Phase 1 step 2 (the 3-floors checklist)
- `rag_retrieval.retrieve_candidates` — implementation entry point
- `rag_pipeline_presets.VALID_RETRIEVAL_BACKENDS` / `PIPELINE_PRESETS` — config single source of truth
- `tests/test_random_retrieval_regression.py` + `tests/test_single_chunk_preset_regression.py` — locked contracts
- ADR 0001 (naive_baseline invariance) — the invariant being preserved
- ADR 0044 → ADR 0052 (real-eval case expansion) — sequencing rationale for landing floors before n=200 regen
