# BGE-M3 multi-channel retrieval spike (`retrieval_backend = "m3"`)

Tracks issue #151. Honest measurement of BGE-M3's three retrieval channels
fused via N-way RRF, compared head-to-head against the MiniLM hybrid
baseline (`hybrid_bm25`, ADR 0010).

## Why a spike (not an ADR yet)

ADR 0010's "Alternatives considered" (lines 72-85) explicitly defers the
BGE-M3 sparse + ColBERT multi-vector channels to a separate ablation,
because the original hybrid PR bundled an embedding-model swap and the
sparse-channel contribution would have been confounded. ADR 0021 then
measured BGE-M3 as a **dense embedding** on `full` and found no lift, so
the model stayed un-defaulted. The hypothesis this spike tests is the
one ADR 0021 could not: **BGE-M3's value lives in the multi-channel
output, not the dense channel alone.**

This is the same measure-first pattern that took ADR 0019 → ADR 0021. If
this spike shows meaningful lift over `hybrid_bm25`, a follow-up PR
persists the sparse + colbert vectors on disk (index schema bump 2 → 3)
and writes ADR 0025 as a supplement to ADR 0010. If the lift isn't
there, this doc records the negative result and the channels stay
deferred.

## Scope

- **Three-channel encoding** via `FlagEmbedding.BGEM3FlagModel`:
  - dense (1024-dim L2-normalized vector per text — replaces nothing,
    parallels the existing dense channel from whatever the index used)
  - sparse (SPLADE-style `{token_id: weight}` dict per text)
  - multi-vector / ColBERT (per-token `(T_i, 1024)` matrix per text;
    late-interaction max-sim sum at scoring time)
- **N-way RRF fusion** in [`rag_core.apply_fusion_and_reranking`](../../rag_core.py)
  — the existing 2-way `hybrid` math (`rrf_k / 2.0` normalization)
  generalizes to `rrf_k / N` for N=3.
- **Opt-in, in-memory only.** Sparse + colbert outputs are computed once
  per index per process at the first m3 query and cached as
  `index["_m3_cache"]`. No disk format change, no `index.json` schema
  bump for the spike (`INDEX_SCHEMA_VERSION` stays at 2).
- **Public-CI surface unchanged.** `pr-eval.yml` runs with
  `EMBEDDING_BACKEND=hashing` and the `m3_*` ablation rows are opt-in,
  so the synthetic CI never installs `FlagEmbedding`.

## Runner

```bash
# Install the optional dependency
pip install -r requirements-m3.txt

# Sanity check — m3 row in eval/config.yaml is opt-in; the default
# config.yaml runs all rows, but the m3 row will raise without the
# dependency installed.
python3 eval/run_eval.py \
  --index_dir data/index \
  --output_dir outputs \
  --config eval/config.yaml

# Optional — just the m3 row (faster iteration during the spike)
python3 eval/run_eval.py \
  --index_dir data/index \
  --output_dir outputs/m3_spike \
  --config eval/config.yaml \
  --runs m3_full
```

For the real-data eval (load-bearing per CLAUDE.md item 5b — `rag_core.py`
and `eval/config.yaml` are both in `LOAD_BEARING_PATHS`):

```bash
make real-eval
make real-eval-delta
```

Results land in `reports/eval_summary.json` under the `m3_full` row, and
the deltas vs the `hybrid_bm25` and `full` controls appear in
`reports/real_eval_delta.json`.

## Results

_To be filled in by the implementer after the eval runs. Append rows
to the table below and to `docs/eval/ablation-results.md`._

| Ablation | recall@5 | MRR@10 | faithfulness | citation_precision | p50 latency (s) | p95 latency (s) | peak RSS delta (MB) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `naive_baseline` (control) | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `full` (control) | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `hybrid_bm25` (control) | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `m3_full` | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

## Decision rule

Ship the ADR 0025 supplement (and the follow-up PR that persists sparse
+ colbert to disk via `INDEX_SCHEMA_VERSION = 3`) iff **all three** hold
on the private 100-doc real-data surface:

1. `m3_full` recall@5 ≥ `hybrid_bm25` recall@5 + 0.03 (3 absolute
   percentage points; the synthetic-eval noise floor is well below
   this).
2. `m3_full` faithfulness ≥ `hybrid_bm25` faithfulness − 0.01 (no
   meaningful regression).
3. `m3_full` p95 latency ≤ 2 × `hybrid_bm25` p95 (the multi-vector path
   is expected to be slower; this is the budget before it becomes
   user-visible).

Otherwise, this spike stands as the negative result and the channels
stay deferred. The ablation row remains in `eval/config.yaml` as opt-in
so future implementers can re-run with different BGE-M3 model sizes or
fusion weights without re-introducing the wiring.

## Why option (a) for the corpus-side compute

Three options were considered for the corpus-side sparse + colbert
computation:

- **(a) Compute every chunk at first m3 query, cache in-memory.** —
  Chosen. One forward pass per process. Cheap engineering, honest
  sparse-recall measurement.
- (b) Lazy on dense top-K only. Cheaper but caps sparse recall to
  whatever the dense channel already surfaced — defeats the spike's
  measurement intent (sparse's contribution gets confounded with dense
  recall).
- (c) Sparse upfront, colbert lazy on top-K. Best memory profile but
  two code paths to maintain for a measurement-only change. Re-visit if
  (a)'s in-memory colbert tensors blow the runner — the spike report
  records peak RSS so the trade-off can be revisited.

## Known risks

- **FlagEmbedding install footprint.** Pulls torch (already pinned),
  datasets, peft. Mitigation: opt-in `requirements-m3.txt`;
  `M3Encoder.__init__` raises a clear actionable error on missing dep.
  Public CI never installs it.
- **In-memory ColBERT cost.** ~1k chunks × T_i × 1024 × float32 ≈
  100 MB ballpark for the real-data corpus. The spike report's
  peak-RSS row records the actual cost; if it overwhelms the eval
  runner, option (c) becomes the productionization path.
- **`naive_baseline` bit-identity.** The m3 path is gated on
  `retrieval_backend == "m3"`. The default `dense` path never imports
  `rag_m3`. The existing
  `tests/test_naive_baseline_ranking_invariance.py` snapshot is the
  ratchet.
- **Encoding asymmetry.** BGE-M3's reference docs use `is_query` to
  differentiate query vs document encoding; the model itself is
  symmetric and the wrapper omits the flag for simplicity. If a
  follow-up measurement shows asymmetric scoring lift, the flag adds
  cleanly.
