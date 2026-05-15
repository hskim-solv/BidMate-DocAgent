# 0037: KURE-v1 closes ADR 0019 issue #447 re-open condition; default stays MiniLM

- **Status**: accepted
- **Date**: 2026-05-14
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (baseline preserved),
  [ADR 0002](./0002-metadata-first-retrieval.md) (metadata-first dominates),
  [ADR 0019](./0019-embedding-default-stays-minilm.md) (deferral),
  [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) (Phase 1.3 supplement),
  [ADR 0032](./0032-eval-saturation-routed-subset.md) (Phase 1.4 routed falsifier),
  [`docs/eval/embedding-ablation.md`](../eval/embedding-ablation.md) Phase 1.5, issue #447

## Context

[Issue #447](https://github.com/hskim-solv/BidMate-DocAgent/issues/447) opened a
re-open window for ADR 0019 / 0021 with three explicit conditions that must all hold
to trigger a default change:

1. A new embedding candidate **not** in the previously measured five (MiniLM, e5-base,
   e5-large-instruct, KoSimCSE, BGE-M3) is added to
   `scripts/run_embedding_ablation.py`.
2. The candidate runs to completion against the **public synthetic corpus** (n=100;
   originally n=42, expanded per issue #570).
3. The candidate shows a **`full` pipeline** lift of **≥ +5pp** accuracy or
   groundedness with non-overlapping bootstrap 95% CIs vs MiniLM. `naive_baseline`
   lifts do **not** count (ADR 0001 invariant).

`nlpai-lab/KURE-v1` was listed in the issue as the primary candidate — a
Korean-specialized embedding model (~1.1 GB, 768-dim) fine-tuned on Korean NLP tasks.
It was partially measured on the n=11 routed subset in [ADR 0032](./0032-eval-saturation-routed-subset.md)
(Phase 1.4), where it showed routed accuracy 0.400 — spread 0.0pp vs MiniLM.
This ADR delivers the formal n=100 full-corpus run that condition 2 requires.

### Env blocker and fix (issue #447 prerequisite)

Running `scripts/run_embedding_ablation.py` on the development machine required
resolving a compound Python-env issue:

| Symptom | Cause | Fix |
|---|---|---|
| `torch.load` crash in eval | `torch 2.2.2` installed; `sentence-transformers 2.7.0` requires `torch >= 2.6` (CVE-2025-32434) | `pip install "torch>=2.6,<2.7"` → `torch 2.6.0` |
| `BertModel` import error | `torchvision 0.17.2` (requires `torch==2.2.2`) broken after upgrade | `pip install "torchvision>=0.21,<0.22"` → `torchvision 0.21.0` |
| `m3_full` crashed instead of skipping | `FlagEmbedding` installed → `requires_module` gate passed; torch check still failed | Added `requires_torch_min_version: "2.6"` to `eval/config.yaml` `m3_full` row and corresponding gate to `eval/run_eval.ablation_runs()` |

The `requirements.txt` already declared `torch>=2.6`; the development environment had
drifted. The `requires_torch_min_version` gate is defensive infrastructure so future
contributors see a clean `[skip]` instead of a runtime crash on under-spec machines.

## Decision

**Keep `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` as the documented
default embedding.** ADR 0019 remains *accepted*; this ADR closes issue #447 by
delivering the formal Phase 1.5 measurement and confirming condition 3 was not triggered.

### What Phase 1.5 measured

Reproduction (torch 2.6.0, sentence_transformers 2.7.0, torchvision 0.21.0):

```
/opt/homebrew/opt/python@3.11/bin/python3.11 scripts/run_embedding_ablation.py \
    --models sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
             nlpai-lab/KURE-v1
```

**`full` agentic pipeline** (n=100, KURE-v1 vs MiniLM):

| metric | MiniLM | KURE-v1 | Δ |
|---|---:|---:|---:|
| accuracy | 0.731 | 0.718 | **−1.3** |
| groundedness | 0.750 | 0.750 | **+0.0** |
| citation_precision | 0.715 | 0.700 | **−1.5** |
| abstention | 0.818 | 0.818 | **+0.0** |
| format compliance | 0.620 | 0.620 | **+0.0** |

KURE-v1 is marginally worse on accuracy (−1.3pp) and citation (−1.5pp); identical on
groundedness, abstention, and format. Not only does it not reach the +5pp threshold —
it is net-negative. The `0pp-on-full` pattern holds for the sixth embedding pivot.

**`naive_baseline`** (preserved ablation per ADR 0001; does NOT count for condition 3):

| metric | MiniLM | KURE-v1 | Δ |
|---|---:|---:|---:|
| accuracy | 0.590 | 0.782 | **+19.2** |
| groundedness | 0.550 | 0.690 | **+14.0** |
| citation_precision | 0.440 | 0.530 | +9.0 |
| format compliance | 0.520 | 0.640 | +12.0 |

Korean-specialization lifts dense-only retrieval substantially — same shape as e5-base
(+18.8pp), e5-large-instruct, and BGE-M3 on the original n=42 corpus. The agentic
pipeline absorbs the lift via metadata-first routing (ADR 0002).

> **Note on corpus size**: The eval config was expanded from the original n=42 to n=100
> per issue #570 (stratified: +20 single_doc, +14 comparison, +12 follow_up, +12
> abstention). The ADR 0021 `full` numbers (accuracy 0.906, groundedness 0.929) reflect
> the n=42 corpus and are **not** directly comparable to the n=100 numbers here. The
> comparison within this ADR (KURE-v1 vs MiniLM, both on n=100) is internally
> consistent. The `0pp-on-full` claim remains valid: neither model dominates the other
> on the binding metrics.

### ADR 0019 condition reconciliation

| condition | status after Phase 1.5 |
|---|---|
| 1. candidate added to `scripts/run_embedding_ablation.py` | ✅ KURE-v1 was already in the docstring example (line 23) |
| 2. runs to completion against n=100 public synthetic corpus | ✅ this ADR |
| 3. ≥ +5pp `full` lift with non-overlapping CIs | ❌ NOT triggered (Δ = −1.3pp accuracy, +0.0pp groundedness) |
| 4. follow-up ADR documenting result | ✅ this ADR |

## Consequences

- `DEFAULT_EMBEDDING_MODEL` in `rag_core.py` stays
  `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.
- `EMBEDDING_BACKEND=hashing` stays the CI / smoke-test default (ADR 0001).
- The `0pp-on-full` pattern now covers **six measured embedding pivots**:
  MiniLM (2019), e5-base (2023), e5-large-instruct (2024 SoTA), KoSimCSE (Korean),
  BGE-M3 (multi-functional), KURE-v1 (Korean-specialized). Any future candidate that
  wants to re-open the question must demonstrate a `full` lift that none of these six
  achieved.
- `eval/run_eval.ablation_runs()` gains a `requires_torch_min_version` gate. The gate
  is transparent (stderr log on skip) and additive — no existing ablation rows are
  affected. The `m3_full` row is skipped on machines with `torch < 2.6`; it ran
  correctly on machines with `torch >= 2.6` before.
- Issue #447 closes once this ADR + the Phase 1.5 section of
  `docs/eval/embedding-ablation.md` land.

## See also

- [`docs/eval/embedding-ablation.md`](../eval/embedding-ablation.md) Phase 1.5 — full results
  and reading guide.
- [ADR 0001](./0001-preserve-naive-baseline.md) — why `naive_baseline` lifts do not
  trigger a default change.
- [ADR 0002](./0002-metadata-first-retrieval.md) — why metadata-first dominates.
- [ADR 0019](./0019-embedding-default-stays-minilm.md) — the original deferral.
- [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) — Phase 1.3 (BGE-M3) closure.
- [ADR 0032](./0032-eval-saturation-routed-subset.md) — Phase 1.4 routed-subset
  falsifier (KURE-v1 n=11 preliminary).
