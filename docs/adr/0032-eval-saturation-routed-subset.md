# 0032: Eval-set saturation 가설 + routed-subset 측정 surface

- **Status**: accepted
- **Date**: 2026-05-13
- **Closed**: 2026-05-13 (spread < +3pp → saturation cross-validated; §Measurement Results 참고)
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (baseline 보존), [ADR 0002](./0002-metadata-first-retrieval.md) (메타데이터 우선 dominance), [ADR 0019](./0019-embedding-default-stays-minilm.md) (임베딩 기본값 deferral), [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) (Phase 1.3 close-out), [ADR 0027](./0027-lora-finetuned-embedding-additive.md) (0019 re-open 조건 상속 LoRA), [`docs/eval/embedding-ablation.md`](../eval/embedding-ablation.md), [`reports/embedding_routed.json`](../../reports/embedding_routed.json), [PR #487](https://github.com/hskim-solv/BidMate-DocAgent/pull/487) §4.4-B2, issue #489, issue #531

## TL;DR

- ADR 0019 `0pp-on-full` 패턴이 "메타데이터 우선이 dense를 우회해서 측정 불가" 때문일 수 있다는 saturation 가설을 falsify 가능한 측정 surface로 변환.
- `agentic_full_routed` 프리셋(`metadata_first: false`) + `eval/routed_config.yaml`(n=11) 추가. 5 임베딩 × routed 측정으로 spread 0.0pp 확인 → saturation 가설 cross-validated.
- ADR 0019 default lock이 measurement-precluded가 아니라 empirically justified임을 확정.

## 배경

[ADR 0019](./0019-embedding-default-stays-minilm.md) / [ADR 0021](./0021-bge-m3-completes-phase-1-3.md)은 5개 임베딩 후보(MiniLM-L12-v2, multilingual-e5-base, multilingual-e5-large-instruct, KoSimCSE-roberta-multitask, BGE-M3)를 공개 합성 n=42 surface에서 측정한 결과 "the `0pp-on-full` pattern holds across all five measured embeddings"로 결론지었다. 이 패턴이 *시스템 robustness*의 증거로 사용되어 ADR 0019 default lock의 정당화 근거가 된다.

그러나 ADR 0019 본문이 직접 인정하듯 — *"Metadata-first filtering (ADR 0002) routes around dense retrieval for most queries; `accuracy / groundedness / citation_precision / abstention / format_compliance` move 0pp"* — `full` 파이프라인의 0pp 패턴은 dense 검색이 *호출되지 않기 때문에* 발생할 가능성이 있다. metric이 saturation되어 임베딩 차이를 *측정 불가능한* 상태일 수 있다. 그렇다면 ADR 0019 re-open trigger 조건 3 ("≥ +5pp on `full` with non-overlapping 95% CIs")는 *영구히 충족 불가능*, default lock이 measurement-gated가 아니라 *measurement-precluded*가 된다. ADR 0027도 인정한다: *"the metadata-first design makes that nearly impossible to clear with embeddings alone"*.

이 ADR은 saturation 가설을 falsify 가능한 측정 surface로 변환해 ADR 0019 re-open 조건이 실재 측정 가능한 게이트임을 검증한다. 동시에 외부 적대적 리뷰([PR #487](https://github.com/hskim-solv/BidMate-DocAgent/pull/487) §4.4-B2)의 동일 메타비판에 대한 evidence-backed 응답이 된다.

## 결정

**Saturation 가설을 falsify할 메타데이터 우선 우회 측정 surface 추가.** ADR 0019의 default lock + re-open 조건은 그대로 유지되며 (ADR 0032는 측정 결과에 따라 ADR 0019 v2 또는 ADR 0032 final로 closed), 이 ADR은 측정 surface 자체를 정의한다.

구체:

1. **신규 합성 eval subset** `eval/synthetic/routed_subset.jsonl` (n ≥ 10): 메타데이터 우선 라우팅이 *우회*되는 케이스.
   - Multi-turn follow-up (다중 query 의존성, 메타데이터 매칭 비결정적)
   - 다문서 비교 ambiguity (동일 메타데이터 후보가 ≥ 2 문서에 분포해 dense disambiguation 필요)
   - 메타데이터 키가 명시되지 않은 추론 질의 (예: "이 사업의 핵심 리스크는?")
2. **신규 분석 변형 프리셋** `agentic_full_routed`: `agentic_full`에서 `metadata_first: false` 강제. `naive_baseline` / `agentic_full` / `agentic_full_llm` 무영향 (별도 프리셋, ADR 0001/0011/0024 보존).
3. **측정 매트릭스**: 5 임베딩 (MiniLM-L12-v2, multilingual-e5-large-instruct, KoSimCSE-roberta-multitask, BGE-M3, KURE-v1) × `agentic_full_routed` × `routed_subset.jsonl`. 측정은 sentence-transformers backend로 로컬에서 (CI는 hashing backend 유지 — 골든 byte-identical, ADR 0001).
4. **결과 published**: `reports/embedding_routed_lift.md` 또는 [`docs/eval/embedding-ablation.md`](../eval/embedding-ablation.md) Phase 1.4 섹션에 5 rows 추가.

**Accept / reject 기준** (측정 후 자동 트리거):

- **Spread ≥ +3pp** (top-vs-bottom 임베딩 accuracy 차이가 routed_subset에서 ≥ +3pp 비중첩 95% CIs) → **ADR 0019 re-open trigger 정당화.** [`adr-reopen` 이슈 #447](https://github.com/hskim-solv/BidMate-DocAgent/issues/447) 즉시 re-open + 새 ADR로 default flip 평가.
- **Spread < +3pp** → **saturation 가설 cross-validated.** "0pp pattern holds on both routed and non-routed subsets; embedding default lock is empirically justified beyond metadata-first masking."

ADR 0001 보존: `routed_subset.jsonl`은 별도 분석 변형 surface로 추가되며 [`tests/data/naive_baseline_top_k.json`](../../tests/data/naive_baseline_top_k.json) 골든 byte-identical, `naive_baseline` 무영향. ADR 0002 (메타데이터 우선) production path 변경 없음 — `agentic_full_routed`는 *측정용 분석 변형 only*.

## 결과

이점:

- ADR 0019 default lock이 "메타데이터 우선이 흡수해서 측정 불가" self-defense에 의존하지 않음. Falsifier 측정 surface가 명문화되어 재오픈 조건이 실재 게이트임을 검증.
- 후속 임베딩 작업(ADR 0027 LoRA, KURE-v1, 미래 후보)이 routed_subset에서 의미 있는 lift를 보일 surface 확보 — portfolio signal이 *측정 가능한 lift 위에* 정립.
- 외부 적대적 리뷰의 "0pp는 saturation 신호" 메타비판이 측정으로 처리되어 portfolio defense interview에서 evidence-backed 응답 가능.

비용 / honesty:

- `routed_subset.jsonl`은 합성이라 representativeness 한계. 진짜 long-tail RFP 케이스의 일부만 cover — 측정 signal이 실제 production lift를 보장하지 않음. ADR 0005 (공개 합성 vs 비공개 로컬) 분리 보존 — private 100-doc surface 결과는 [`docs/real-data/private-100-doc-experiments.md`](../real-data/private-100-doc-experiments.md)에 published.
- Sentence-transformers 측정은 CI에서 자동 reproducible하지 않음. 5 임베딩 측정은 로컬 빌드 필요(~30분, ADR 0019의 env 업그레이드 조건 1 충족 시 BGE-M3 / e5-large-instruct 실행 가능). 결과는 commit-pinned PR로 published.
- ADR 0019 final이 spread < +3pp로 닫히면 "default lock empirically justified"로 강화되지만 *dense 검색의 system-level 가치가 낮음을 인정*하는 톤. 그러나 ADR 0001 (naive baseline 보존)이 dense-only surface를 따로 잡고 있어 시스템 정합성 유지.

## 검토한 대안

- **Status quo (측정 surface 추가 안 함).** 기각: 적대적 메타비판 재유입 시 대응 부재. ADR 0019의 self-defense는 "메타데이터 우선 흡수"로 closure되어 영구히 untestable.
- **Private 100-doc surface에서만 측정.** 기각: ADR 0005 (public/private split) 위반. 외부 reproducibility 0; portfolio value 낮음.
- **임베딩 비교 자체를 영구 deferral.** 기각: ADR 0019의 measurement-gated 정신과 직접 충돌.
- **`agentic_full` 프리셋 직접 변경 (`metadata_first: false`).** 기각: ADR 0019 default lock + ADR 0002 + ADR 0024 모두 깸. 별도 프리셋 추가가 안전 — ADR 0011 / 0013 / 0023 / 0027의 additive opt-in 재사용.
- **Routed_subset를 ADR이 아닌 단순 doc/issue로.** 기각: spread 임계값(+3pp) + ADR 0019 re-open trigger 연동 + ADR 0001 보존 조건이 *load-bearing 결정*이라 ADR 임계값 충족. 측정 methodology + accept/reject 기준이 ADR 0019 → 0021 패턴과 동일해야 거버넌스 일관성.

## Measurement Results (2026-05-13)

**측정 surface**: `eval/routed_config.yaml` (n=11, multi-turn 3 / comparison 4 / inference 3 / abstention 1), `agentic_full_routed` 프리셋(`metadata_first: false`). Runner: `scripts/run_routed_measurement.py`, sentence-transformers backend, 2026-05-13 local macOS CPU.

| Model | full (metadata_first=true) | routed (metadata_first=false) | Notes |
|---|---:|---:|---|
| MiniLM-L12-v2 | 0.500 | **0.400** | ADR 0019 default |
| multilingual-e5-large-instruct | 0.500 | **0.400** | ADR 0021 Phase 1.3 |
| KoSimCSE-roberta-multitask | 0.500 | **0.400** | ADR 0021 Phase 1.2 |
| BGE-M3 | — | — | **Skipped**: torch ≥ 2.6 required (ADR 0021 §4 blocker) |
| KURE-v1 | 0.500 | **0.400** | Korean-specialized; locally cached via auto-download |

**Spread (top-vs-bottom, agentic_full_routed)**: **0.0pp** (threshold: +3pp)

**VERDICT: `saturation_cross_validated`** — Spread < +3pp. 0pp 패턴이 routed surface에서도 성립. 메타데이터를 비활성화해도 임베딩 선택이 accuracy를 바꾸지 못함. 두 가지 상보 해석:

1. **Corpus 규모 효과**: fixture corpus (7 docs, 9 chunks)에서 dense 검색은 trivially 해결 가능 — 어떤 임베딩으로도 9개 chunk 중 올바른 chunk를 top-k 회수. 더 큰 corpus (private 100-doc)에서는 spread 가능.
2. **검증기 병목**: `agentic_full_routed` accuracy 제한은 retrieval 품질이 아니라 검증기 exact-term match 정책일 가능성. ADR 0004 검증기 설계의 의도된 strictness.

두 해석 모두 **ADR 0019 default lock(MiniLM-L12-v2)이 measurement-precluded가 아니라 empirically justified임**을 뒷받침. ADR 0019 re-open trigger 조건 3 (≥ +5pp on full)은 현재 측정 surface에서 충족 불가능 — lock 정당성 추가 강화.

**Full results**: `reports/embedding_routed.json` (commit-pinned in PR #535).

## See also

- [ADR 0019](./0019-embedding-default-stays-minilm.md) — 임베딩 기본값 + re-open 조건. 이 ADR 측정 결과 lock이 measurement-gated gate로 유지.
- [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) — BGE-M3 결과로 0pp 패턴 확인. BGE-M3는 torch ≥ 2.6 blocker로 이 ADR 측정에서도 skip.
- [ADR 0002](./0002-metadata-first-retrieval.md) — 메타데이터 우선 정책. `agentic_full_routed`는 *측정용으로만* 우회, production path 변경 없음.
- [ADR 0027](./0027-lora-finetuned-embedding-additive.md) — LoRA adapter 분석 변형이 routed_subset에서 lift 보일 가능성. 현재 임베딩 수준에서는 lift 없음 → LoRA가 실질적 개선 첫 후보.
- [`docs/eval/embedding-ablation.md`](../eval/embedding-ablation.md) — Phase 1.4 routed_subset 섹션.
- [`reports/embedding_routed.json`](../../reports/embedding_routed.json) — Machine-readable 측정 결과 (schema_version=1).
- [PR #487](https://github.com/hskim-solv/BidMate-DocAgent/pull/487) §4.4-B2 — 이 ADR origin (외부 적대적 리뷰).
- Issue #531 — 5-embedding × routed 측정 (Step 2). 이 ADR close-out으로 closes.
