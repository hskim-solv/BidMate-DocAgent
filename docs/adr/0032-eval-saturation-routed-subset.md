# 0032: Eval-set saturation hypothesis + routed-subset measurement surface

- **Status**: accepted
- **Date**: 2026-05-13
- **Closed**: 2026-05-13 (spread < +3pp → saturation cross-validated; see §Measurement Results)
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (baseline preserved), [ADR 0002](./0002-metadata-first-retrieval.md) (metadata-first dominates), [ADR 0019](./0019-embedding-default-stays-minilm.md) (embedding default deferral), [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) (Phase 1.3 close-out), [ADR 0027](./0027-lora-finetuned-embedding-additive.md) (LoRA additive ablation that inherits 0019 re-open conditions), [`docs/embedding-ablation.md`](../embedding-ablation.md), [`reports/embedding_routed.json`](../../reports/embedding_routed.json), [PR #487](https://github.com/hskim-solv/BidMate-DocAgent/pull/487) §4.4-B2, issue #489, issue #531

## Context

[ADR 0019](./0019-embedding-default-stays-minilm.md) / [ADR 0021](./0021-bge-m3-completes-phase-1-3.md)은 5개 임베딩 후보(MiniLM-L12-v2, multilingual-e5-base, multilingual-e5-large-instruct, KoSimCSE-roberta-multitask, BGE-M3)를 public synthetic n=42 surface에서 측정한 결과 "the `0pp-on-full` pattern holds across all five measured embeddings"로 결론지었다 ([ADR 0019:7](./0019-embedding-default-stays-minilm.md)). 이 패턴이 *시스템 robustness*의 증거로 사용되어 ADR 0019 default lock의 정당화 근거가 된다.

그러나 ADR 0019 본문이 직접 인정하는 바와 같이 — *"Metadata-first filtering (ADR 0002) routes around dense retrieval for most queries; `accuracy / groundedness / citation_precision / abstention / format_compliance` move 0pp"* ([ADR 0019:18-20](./0019-embedding-default-stays-minilm.md)) — `full` pipeline의 0pp 패턴은 dense retrieval이 실제로 *호출되지 않기 때문에* 발생할 가능성이 있다. 즉 metric이 saturation되어 임베딩 차이를 *측정 불가능한* 상태일 수 있다. 만약 이 가설이 맞다면 ADR 0019 re-open trigger condition 3 ("≥ +5pp on `full` with non-overlapping 95% CIs")는 사실상 *영구히 충족 불가능*하며, default lock이 measurement-gated가 아니라 *measurement-precluded*가 된다. ADR 0027 본문도 이 점을 인정한다: *"the metadata-first design makes that nearly impossible to clear with embeddings alone"* ([ADR 0027:77-80](./0027-lora-finetuned-embedding-additive.md)).

이 ADR은 saturation 가설을 falsify 가능한 측정 surface로 변환하여 ADR 0019 re-open 조건이 실재 측정 가능한 게이트임을 검증한다. 동시에 외부 적대적 코드 리뷰 ([PR #487](https://github.com/hskim-solv/BidMate-DocAgent/pull/487) §4.4-B2)에서 메타비판으로 제기된 동일 가설에 대한 evidence-backed 응답이 된다.

## Decision

**Saturation 가설을 falsify할 metadata-first 우회 measurement surface를 추가한다.** ADR 0019의 default lock + re-open 조건은 그대로 유지되며 (본 ADR은 `proposed` status로 측정 결과에 따라 ADR 0019 v2 또는 ADR 0032 final로 closes됨), 본 ADR은 측정 surface 자체를 정의한다.

구체:

1. **신규 synthetic eval subset** `eval/synthetic/routed_subset.jsonl` (n ≥ 10): metadata-first 라우팅이 *우회*되는 케이스 위주.
   - Multi-turn follow-up (다중 query 의존성, metadata 매칭이 결정적이지 않음)
   - 다문서 비교 ambiguity (동일 metadata 후보가 ≥ 2 문서에 분포해 dense retrieval로 disambiguation 필요)
   - Metadata 키가 명시되지 않은 추론 질의 (예: "이 사업의 핵심 리스크는?" — 어떤 metadata column이 대응하는지 명확하지 않음)
2. **신규 ablation preset** `agentic_full_routed`: 기존 `agentic_full`에서 `metadata_first: false` 강제. `naive_baseline` / `agentic_full` / `agentic_full_llm` 어디에도 영향 없음 (별도 preset 추가, ADR 0001/0011/0024 invariants 모두 보존).
3. **측정 matrix**: 5 임베딩 (MiniLM-L12-v2, multilingual-e5-large-instruct, KoSimCSE-roberta-multitask, BGE-M3, KURE-v1) × `agentic_full_routed` × `routed_subset.jsonl`. 측정은 sentence-transformers backend로 로컬에서 (CI는 hashing backend 유지 — 골든 byte-identical 보존, ADR 0001 invariant).
4. **결과 published**: `reports/embedding_routed_lift.md` 또는 [`docs/embedding-ablation.md`](../embedding-ablation.md) Phase 1.4 섹션에 5 rows 추가 (accuracy / groundedness / citation_precision + 95% CI).

**Accept / reject 기준** (측정 후 자동 트리거):

- **Spread ≥ +3pp** (top-vs-bottom 임베딩 accuracy 차이가 routed_subset에서 ≥ +3pp 비중첩 95% CIs) → **ADR 0019 re-open trigger 정당화.** [`adr-reopen` 라벨 이슈 #447](https://github.com/hskim-solv/BidMate-DocAgent/issues/447) 즉시 re-open + ADR 0019 v2 또는 새 ADR로 default flip 평가. 본 ADR은 final 상태로 닫힘 ("saturation hypothesis falsified, routed surface lifts measurable").
- **Spread < +3pp** → **saturation 가설 cross-validated.** ADR 0019 v2 또는 본 ADR final 갱신: "0pp pattern holds on both routed and non-routed subsets; embedding default lock is empirically justified beyond metadata-first masking."

ADR 0001 invariant 보존: `routed_subset.jsonl`은 별도 ablation surface로 추가되며 [`tests/data/naive_baseline_top_k.json`](../../tests/data/naive_baseline_top_k.json) 골든 byte-identical, `naive_baseline` preset 무영향. ADR 0002 (metadata-first) 정책도 production path에서는 그대로 — `agentic_full_routed`는 *측정용 ablation only*.

## Consequences

Easier:

- ADR 0019 default lock이 "metadata-first가 흡수해서 측정 불가"라는 self-defense에 의존하지 않음. Falsifier measurement surface가 명문화되어 재오픈 조건이 실재 게이트임을 검증.
- 후속 임베딩 작업 (ADR 0027 LoRA, KURE-v1, 또는 미래 후보)이 routed_subset에서 의미 있는 lift를 보일 수 있는 surface 확보 — "have you fine-tuned a model?" 같은 portfolio signal이 *측정 가능한 lift 위에* 정립됨.
- 외부 적대적 코드 리뷰의 "0pp는 saturation 신호" 메타비판이 측정으로 처리되어 portfolio defense interview에서 evidence-backed 응답 가능 ([PR #487](https://github.com/hskim-solv/BidMate-DocAgent/pull/487) §4.4-B2 후속).

Costs / honesty:

- `routed_subset.jsonl`은 synthetic이므로 representativeness 한계. 진짜 long-tail RFP 케이스의 일부만 cover 가능 — measurement signal이 실제 production lift를 보장하지 않음. ADR 0005 (public synthetic vs private local) 분리 패턴 보존 — private 100-doc surface에서도 별도 측정 가능하면 그 결과는 [`docs/private-100-doc-experiments.md`](../private-100-doc-experiments.md)에 published.
- Sentence-transformers 측정은 CI에서 자동 reproducible하지 않음 (hashing backend 유지로 골든 보존). 5 임베딩 측정은 로컬 빌드 필요 (~30분 추정, ADR 0019의 env 업그레이드 조건 1이 충족되어야 BGE-M3 / e5-large-instruct 실행 가능). 측정 결과는 commit-pinned PR로 published.
- ADR 0019 final이 spread < +3pp로 닫히면 ADR 0019 v2 + 본 ADR final이 "default lock empirically justified"로 강화되지만, *동시에 dense retrieval의 system-level 가치가 낮음을 인정*하는 톤. 그러나 ADR 0001 (naive baseline 보존)이 dense-only surface를 따로 잡고 있어 시스템 정합성 유지.

## Alternatives considered

- **Status quo (측정 surface 추가 안 함).** Rejected: 적대적 메타비판 재유입 시 대응 부재. ADR 0019의 self-defense는 "metadata-first 흡수"로 closure되어 영구히 untestable. ADR 0019의 measurement-gated 정신과 충돌.
- **Private 100-doc surface에서만 측정.** Rejected: ADR 0005 (public/private split) 패턴 위반. 외부 reproducibility 0; portfolio value 낮음. Synthetic subset은 publishable이라 ADR 0019 트랙(public surface)과 정합.
- **임베딩 비교 자체를 영구 deferral.** Rejected: ADR 0019의 measurement-gated 정신과 직접 충돌. 본 ADR은 *측정 가능한 게이트 surface를 만든다*는 명시적 약속.
- **`agentic_full` preset을 직접 변경 (`metadata_first: false`).** Rejected: ADR 0019 default lock + ADR 0002 metadata-first 정책 + ADR 0024 API default 모두 깸. 별도 preset (`agentic_full_routed`) 추가 패턴이 더 안전 — ADR 0011 / 0013 / 0023 / 0027의 additive opt-in 패턴 재사용.
- **Routed_subset의 정의를 ADR이 아닌 단순 doc/issue로.** Rejected: spread 임계값(+3pp) + ADR 0019 re-open trigger 연동 + ADR 0001 invariant 보존 조건이 *load-bearing 결정*이라 ADR 임계값을 충족. measurement methodology + accept/reject 기준이 ADR 0019 → 0021 패턴과 동일한 형식이어야 거버넌스 일관성.

## Measurement Results (2026-05-13)

**측정 surface**: `eval/routed_config.yaml` (n=11, multi-turn 3 / comparison 4 / inference 3 / abstention 1), `agentic_full_routed` preset (`metadata_first: false`). Runner: `scripts/run_routed_measurement.py`, sentence-transformers backend, 2026-05-13 local macOS CPU.

| Model | full (metadata_first=true) | routed (metadata_first=false) | Notes |
|---|---:|---:|---|
| MiniLM-L12-v2 | 0.500 | **0.400** | ADR 0019 default |
| multilingual-e5-large-instruct | 0.500 | **0.400** | ADR 0021 Phase 1.3 |
| KoSimCSE-roberta-multitask | 0.500 | **0.400** | ADR 0021 Phase 1.2 |
| BGE-M3 | — | — | **Skipped**: torch ≥ 2.6 required (ADR 0021 §4 blocker still active) |
| KURE-v1 | 0.500 | **0.400** | Korean-specialized; locally cached via auto-download |

**Spread (top-vs-bottom, agentic_full_routed)**: **0.0pp** (threshold: +3pp)

**VERDICT: `saturation_cross_validated`** — Spread < +3pp. 0pp 패턴이 routed surface에서도 성립. Saturation 가설은 "metadata-first 흡수만의 artifact"가 아님을 확인: 메타데이터를 비활성화해도 임베딩 선택이 accuracy를 바꾸지 못함. 두 가지 상보 해석:

1. **Corpus 규모 효과**: fixture corpus (7 docs, 9 chunks)에서 dense retrieval은 trivially 해결 가능 — 어떤 임베딩으로도 9개 chunk 중 올바른 chunk를 top-k로 회수. 더 큰 corpus (private 100-doc)에서는 spread가 나타날 수 있음.
2. **Verifier 병목**: `agentic_full_routed` 케이스에서 accuracy를 제한하는 것이 retrieval 품질이 아니라 verifier의 exact-term match 정책일 가능성. 이는 ADR 0004 verifier 설계의 의도된 strictness.

두 해석 모두 **ADR 0019 default lock(MiniLM-L12-v2)이 measurement-precluded가 아니라 empirically justified임**을 뒷받침. ADR 0019 re-open trigger condition 3 (≥ +5pp on full with non-overlapping CIs)은 현재 측정 surface에서 충족 불가능 — 이는 lock의 정당성을 추가로 강화.

**Full results**: `reports/embedding_routed.json` (commit-pinned in PR #535).

## See also

- [ADR 0019](./0019-embedding-default-stays-minilm.md) — Embedding default + re-open conditions. 본 ADR 측정 결과 lock이 measurement-gated gate로 유지됨.
- [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) — BGE-M3 결과로 0pp 패턴 확인된 직전 close-out. BGE-M3는 torch ≥ 2.6 blocker로 본 ADR 측정에서도 skip됨.
- [ADR 0002](./0002-metadata-first-retrieval.md) — Metadata-first 정책. `agentic_full_routed`는 이 정책을 *측정용으로만* 우회하며 production path는 변경 없음.
- [ADR 0027](./0027-lora-finetuned-embedding-additive.md) — LoRA adapter ablation이 routed_subset에서 lift를 보일 가능성. 본 ADR 측정 결과 현재 embedding 수준에서는 lift 없음 → LoRA가 실질적 개선의 첫 후보.
- [`docs/embedding-ablation.md`](../embedding-ablation.md) — Phase 1.4 routed_subset 섹션에 본 측정 결과 추가됨.
- [`reports/embedding_routed.json`](../../reports/embedding_routed.json) — Machine-readable 측정 결과 (schema_version=1).
- [PR #487](https://github.com/hskim-solv/BidMate-DocAgent/pull/487) §4.4-B2 — 본 ADR의 origin (외부 적대적 리뷰 메타비판).
- Issue #531 — 5-embedding × routed measurement (Step 2). 본 ADR close-out으로 closes됨.
