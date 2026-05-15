# 0021: BGE-M3 closes ADR 0019 condition 2; default embedding stays MiniLM

- **Status**: accepted
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (baseline preserved), [ADR 0002](./0002-metadata-first-retrieval.md) (metadata-first dominates), [ADR 0019](./0019-embedding-default-stays-minilm.md) (the deferral), [ADR 0032](./0032-eval-saturation-routed-subset.md) (routing-axis falsifier, 2026-05-13), [`docs/eval/embedding-ablation.md`](../eval/embedding-ablation.md) Phase 1.3, issue #389
- **Update (ADR 0032 routing-axis falsifier, 2026-05-13)**: [ADR 0032](./0032-eval-saturation-routed-subset.md) ran the complementary routed-subset measurement (n=11, metadata-first bypassed). BGE-M3 was skipped in that run (torch < 2.6 on the test machine — same env blocker noted in ADR 0021 §Decision). The 4 measured models all showed spread = 0.0pp on the routed subset, confirming the saturation cross-validation finding. The env upgrade needed for BGE-M3 in the routing-axis run remains tracked in the ADR 0032 measurements table.

## Context

[ADR 0019](./0019-embedding-default-stays-minilm.md) deferred the
embedding-default decision behind four explicit re-open conditions:

1. `requirements.txt` upgrade resolving the two env blockers
   (`torch >= 2.6`, `huggingface-hub < 1.0`).
2. `python3 scripts/run_embedding_ablation.py --models <MiniLM>
   BAAI/bge-m3 intfloat/multilingual-e5-large-instruct` runs to
   completion against the n=42 public synthetic corpus.
3. At least one of BGE-M3 / e5-large-instruct shows a **`full`
   pipeline** lift of ≥ +5pp accuracy or groundedness with
   non-overlapping bootstrap 95% CIs vs MiniLM. *(Lifts on
   `naive_baseline` only do NOT count — that surface is preserved as
   an ablation per ADR 0001.)*
4. A follow-up ADR (numbered 002x) is opened to document the
   replacement, with the candidate's measurement output appended to
   `docs/eval/embedding-ablation.md` Phase 1.2 section.

Phase 1.2 (issue #174) cleared three candidates — e5-large-instruct,
KoSimCSE-roberta-multitask, and OpenAI text-embedding-3-large /
e5-base from the first cycle — leaving BGE-M3 as the lone gap. The
`torch >= 2.6` requirement landed in `requirements.txt:8` between
Phase 1.2 and this issue. Phase 1.3 (issue #389) fills the gap.

This ADR is the **condition 4** companion to Phase 1.3 — it is
explicitly **not** a supersede of ADR 0019.

## Decision

**Keep `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
as the documented default embedding.** ADR 0019 remains *accepted*;
this ADR adds the Phase 1.3 evidence and marks ADR 0019 condition 2
as fully met.

### What Phase 1.3 measured

Reproduction (clean `.venv` with `torch 2.11.0`, `sentence_transformers
2.7.0`, `huggingface-hub 0.36.2`):

```
python3 scripts/run_embedding_ablation.py \
    --models sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
             BAAI/bge-m3
```

`full` agentic pipeline (n=42, BGE-M3 vs MiniLM):

| metric | MiniLM | BGE-M3 | Δ |
|---|---:|---:|---:|
| accuracy | 0.906 | 0.906 | **+0.0** |
| groundedness | 0.929 | 0.929 | **+0.0** |
| citation_precision | 0.905 | 0.905 | **+0.0** |
| abstention | 1.000 | 1.000 | **+0.0** |
| format compliance | 0.905 | 0.905 | **+0.0** |

Bit-identical, not just CI-overlapping. Same shape as Phase 1.2
results for e5-large-instruct and KoSimCSE-roberta-multitask.

`naive_baseline` (preserved ablation per ADR 0001; does NOT count):

| metric | MiniLM | BGE-M3 | Δ |
|---|---:|---:|---:|
| accuracy | 0.656 | 0.844 | **+18.8** |
| groundedness | 0.595 | 0.714 | **+11.9** |
| citation_precision | 0.488 | 0.548 | +6.0 |
| format compliance | 0.548 | 0.667 | **+11.9** |

BGE-M3 lifts dense-only retrieval just as much as e5-large-instruct
does. The agentic pipeline absorbs the lift via metadata-first
routing (ADR 0002).

### ADR 0019 condition reconciliation

| condition | status after Phase 1.3 |
|---|---|
| 1. requirements.txt env upgrade | ✅ met (`torch >= 2.6` pinned, `huggingface-hub` already at `0.36.2 < 1.0`) |
| 2. runs to completion | ✅ met for all four named candidates (MiniLM / e5-large-instruct / KoSimCSE / BGE-M3) |
| 3. ≥+5pp `full` lift with non-overlapping CIs | ❌ NOT triggered for any candidate (all `+0.0` on `full`) |
| 4. follow-up ADR documenting replacement OR closure | ✅ this ADR |

Condition 3 is the binding gate, and it was not triggered. ADR 0019's
`If conditions 1–2 land but 3 doesn't (the 0pp pattern holds), this
ADR stays accepted and the doc is updated with the measurement
without an ADR replacement.` clause applies — except this ADR was
opened anyway, as the supplement that **explicitly closes the
deferral** so the next contributor does not re-litigate it.

## Consequences

- `DEFAULT_EMBEDDING_MODEL` in `rag_core.py` stays
  `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.
- `EMBEDDING_BACKEND=hashing` stays the CI / smoke-test default for
  reproducibility (no model download, no GPU).
- The `0pp-on-full` finding now has 5 measured embedding pivots
  (MiniLM 2019, e5-base 2023, e5-large-instruct 2024 SoTA, KoSimCSE
  Korean-specialized, BGE-M3 multi-functional). The next contributor
  who wants to re-open the question needs a candidate that visibly
  shifts the `full` row — not another modern multilingual or
  Korean-specialized model, because those are exhausted.
- Issue #389 closes once this ADR + the Phase 1.3 section of
  `docs/eval/embedding-ablation.md` land. Raw `eval_summary.json` lives
  under `reports/embedding-ablation/` (gitignored — reproducible by
  re-running the runner against the public synthetic corpus).

## Re-open conditions (inherited from ADR 0019)

The original ADR 0019 re-open conditions remain in effect for any
*future* embedding candidate. Adding `nlpai-lab/KURE-v1` or another
non-listed candidate to the runner and finding a `full` lift would
re-trigger condition 3 and open a fresh follow-up ADR. The
measurement infrastructure (`scripts/run_embedding_ablation.py`) is
the same; no new tooling needed.

## Phase 1.4 update — ADR 0032 routed-subset saturation falsifier (2026-05-13)

본 ADR에서 기록한 "0pp on full" 패턴이 metadata-first absorption artifact인지를 [ADR 0032](./0032-eval-saturation-routed-subset.md)가 routed-subset measurement surface (n=11, `agentic_full_routed`)로 falsify 시도했다. 결과: MiniLM / e5-large-instruct / KoSimCSE / KURE-v1 모두 routed accuracy 0.400, spread **0.0pp** (threshold +3pp). Saturation cross-validated. BGE-M3 Phase 1.4 측정도 torch ≥ 2.6 blocker로 동일하게 skip됨.

## See also

- [`docs/eval/embedding-ablation.md`](../eval/embedding-ablation.md) Phase 1.3 —
  full Phase 1.3 numbers and reading guide.
- [ADR 0001](./0001-preserve-naive-baseline.md) — why `naive_baseline`
  lifts do not trigger a default change.
- [ADR 0002](./0002-metadata-first-retrieval.md) — the load-bearing
  design choice that the `0pp-on-full` pattern empirically supports.
- [ADR 0019](./0019-embedding-default-stays-minilm.md) — the deferral
  this ADR closes.
- [ADR 0032](./0032-eval-saturation-routed-subset.md) — Phase 1.4 routed-subset measurement. "0pp on full"이 saturation artifact가 아님을 cross-validate.
- [ADR 0037](./0037-kure-v1-closes-phase-1-5.md) — Phase 1.5 KURE-v1 n=100 formal measurement. issue #447 close.
