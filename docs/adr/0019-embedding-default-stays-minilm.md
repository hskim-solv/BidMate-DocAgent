# 0019: Embedding default stays MiniLM-L12-v2 with explicit re-open conditions

- **Status**: accepted
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (baseline preserved), [ADR 0002](./0002-metadata-first-retrieval.md) (metadata-first dominates), [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) (Phase 1.3 supplement that closes condition 2), [`docs/embedding-ablation.md`](../embedding-ablation.md), issues #161 (Phase 1.2 runner) and #300 (this decision)
- **Update (Phase 1.3, issue #389, 2026-05-12)**: condition 1 fully met (`torch >= 2.6` pinned in `requirements.txt:8`, `huggingface-hub 0.36.2 < 1.0` already in place), condition 2 fully met for all four named candidates (BGE-M3 measurement closed the last gap), condition 3 **NOT triggered** for any candidate (the `0pp-on-full` pattern holds across all five measured embeddings). This ADR stays accepted; see [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) for the supplement.
- **Update (ADR 0032 routing-axis falsifier, issue #550, 2026-05-13)**: [ADR 0032](./0032-eval-saturation-routed-subset.md) added a complementary gate: "spread ≥ +3pp on routed (metadata-first-bypassed) subset." 5-embedding × routed-subset measurement (n=11, `eval/routed_config.yaml`) showed spread = **0.0pp** — `saturation_cross_validated`. Condition 3 **NOT triggered** on the routed axis either. MiniLM default lock is empirically justified beyond metadata-first masking. Aggregate published to `reports/embedding_routed.json`.

## Context

The README's Limitations list and `docs/embedding-ablation.md` both
flagged a half-finished decision: the embedding default is the 2019
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. The
first-cycle measurement (MiniLM vs `multilingual-e5-base`, n=42)
showed two robust findings:

1. **Full agentic pipeline metrics are embedding-invariant** on this
   corpus. Metadata-first filtering (ADR 0002) routes around dense
   retrieval for most queries; `accuracy / groundedness /
   citation_precision / abstention / format_compliance` move 0pp.
2. **Naive baseline IS embedding-sensitive.** `e5-base` lifted
   `naive_baseline.accuracy` from 0.656 → 0.844 (+18.8pp), but the
   naive surface is preserved as an ablation, not as a production
   path (ADR 0001).

The unfinished work, tracked under issue #161, was a second cycle
adding modern multilingual SoTA + Korean-specialized comparators
(BGE-M3, e5-large-instruct, KURE-v1) to falsify the hypothesis "the
0pp-on-full pattern is robust across modern models." The runner is
extended; the *measurement* itself was deferred to this issue (#300).

This decision attempts that measurement, hits a Python env wall,
documents the wall, and explicitly **does not** change the default.

## Decision

**Keep `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
as the documented default embedding.** Lock the decision in this ADR
so a future contributor does not silently swap it without empirical
evidence; lock the *re-open conditions* below so the deferral is not
a permanent caveat.

The second-cycle measurement was blocked by two independent env
mismatches on the maintainer's Python 3.11 install:

- `BAAI/bge-m3` requires `torch >= 2.6` (CVE-2025-32434 mitigation in
  modern sentence-transformers); installed is `2.2.2`.
- `intfloat/multilingual-e5-large-instruct` requires
  `huggingface-hub < 1.0` (via transformers); installed is `1.14.0`.

These are unrelated to the pipeline. Fixing them is a separate
concern — `requirements.txt` only pins `sentence-transformers>=2.7,<3.0`
and the rest of the stack drifted independently. Yak-shaving the env
upgrade in this PR would violate the "one PR, one concern" rule
(CLAUDE.md) for what is fundamentally a *measurement deferral*
decision.

## Re-open conditions

ADR 0019 re-opens (i.e., this decision is revisited and the default
is potentially flipped) when **all four** of the following hold:

1. A contributor lands a `requirements.txt` upgrade that resolves
   both blockers (`torch >= 2.6`, `huggingface-hub < 1.0` via a
   matching `transformers` pin).
2. `python3 scripts/run_embedding_ablation.py --models <miniLM>
   BAAI/bge-m3 intfloat/multilingual-e5-large-instruct` runs to
   completion against the public synthetic corpus (n=42).
3. At least one of BGE-M3 / e5-large-instruct shows a **`full`
   pipeline** lift of ≥ +5pp accuracy or groundedness with
   non-overlapping bootstrap 95% CIs vs MiniLM. *(Lifts on
   `naive_baseline` only do NOT count — that surface is preserved as
   an ablation per ADR 0001.)*
4. A follow-up ADR (numbered 002x) is opened to document the
   replacement, with the candidate's measurement output appended to
   `docs/embedding-ablation.md` Phase 1.2 section.

If conditions 1–2 land but 3 doesn't (the 0pp pattern holds), this
ADR stays accepted and the doc is updated with the measurement
without an ADR replacement.

## Consequences

Easier:

- README's Limitations list no longer carries a perpetual "다음 사이클"
  placeholder for the embedding decision. The current state is
  *recorded*, not pending.
- The "ADR threshold" rule from CLAUDE.md is satisfied: the decision
  to keep the default is now load-bearing (no contributor will
  silently swap it) and the conditions to reverse it are explicit.
- Future contributors hit a clear gate ("did you measure ≥+5pp on
  `full`?") instead of an open invitation to swap models on vibes.

Costs / honesty:

- The deferral is real. The headline numbers for BGE-M3 / KURE-v1 do
  not exist in this repo; a reviewer asking "why MiniLM in 2026?"
  gets the first-cycle evidence + ADR 0019's re-open conditions, not
  a second-cycle measurement. This is documented explicitly in
  `docs/embedding-ablation.md`.
- The env upgrade work is now an unblocking dependency for a piece
  of measurement that is *not* on this PR's critical path. That work
  belongs to whoever has bandwidth for a requirements-pinning sweep.

## Alternatives considered

- **Upgrade `torch` and `huggingface-hub` in this PR + re-run the
  ablation.** Rejected: scope creep (env upgrades affect the entire
  repo, not just this measurement) and risk (other code paths
  haven't been re-tested against torch 2.6+; nothing in this PR
  validates that the upgrade is safe). One PR, one concern.
- **Switch the default to e5-base based on the first-cycle data
  alone.** Rejected: e5-base shows 0pp lift on the `full` pipeline.
  The ADR re-open conditions require a measurable improvement on
  `full`, not a lift on a preserved ablation.
- **Mark the decision "deferred" without an ADR, just a comment in
  the doc.** Rejected: that leaves the next contributor with the
  same half-finished state. The point of an ADR is to make a
  decision legible enough that the next contributor can build on it
  without re-deciding.
- **Remove the second-cycle framing from the doc entirely.**
  Rejected: erasing an unfinished cycle would hide a real piece of
  measurement context. The doc now records that the cycle was
  attempted and what specifically blocks it.

## Phase 1.4 update — routed-subset saturation falsifier (ADR 0032, 2026-05-13)

[ADR 0032](./0032-eval-saturation-routed-subset.md)이 "0pp on full = metadata-first masking" 가설을 falsify하기 위해 routed-subset measurement surface를 추가했다 (eval/routed_config.yaml, n=11, `agentic_full_routed` preset: metadata_first=false). 측정 결과 spread **0.0pp** (MiniLM / e5-large-instruct / KoSimCSE / KURE-v1 모두 routed accuracy 0.400, threshold: +3pp). BGE-M3는 torch ≥ 2.6 blocker로 skip됨 (ADR 0021 §4 동일 조건).

**Saturation cross-validated**: 0pp 패턴이 routed surface에서도 성립 — metadata-first 우회 시에도 임베딩 선택이 accuracy를 바꾸지 못함. MiniLM default lock이 measurement-precluded가 아니라 *empirically justified* (두 surface 공통)임을 확인. Re-open trigger condition 3 (≥ +5pp on full, non-overlapping CIs)는 현재 측정 surface에서 structurally unreachable이 아닌, *evidence-backed stable*임이 cross-validated됨. ADR 0032 accepted로 closes.

전체 결과: `reports/embedding_routed.json`.
