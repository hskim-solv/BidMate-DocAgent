# 0058: Phase 3.5 mode-winner 결정 — Scenario A (default 를 hybrid BM25+BGE-M3 dense, RRF k=60 으로 전환)

- **Status**: accepted, amended by [ADR 0074](./0074-rfp-rag-stage-separation.md) (Phase 3.5 measurement landed 2026-05-19; Scenario A finalized)
- **Date**: 2026-05-19 (Status accepted); 2026-05-18 (Status proposed)
- **Deciders**: hskim
- **Related**: [ADR 0001](0001-preserve-naive-baseline.md), [ADR 0005](0005-eval-split-public-synthetic-private-local.md), [ADR 0010](0010-hybrid-bm25-dense-retrieval-rrf.md), [ADR 0021](0021-bge-m3-completes-phase-1-3.md), [ADR 0025](0025-cost-frontier-defer-until-real-baselines.md), [ADR 0032](0032-eval-saturation-routed-subset.md), [ADR 0049](0049-kordoc-replaces-pyhwp-backend.md), [ADR 0074](./0074-rfp-rag-stage-separation.md), PR #966 (Phase 3.5 measurement), PR #956 (Phase 3, retracted), issue #957, issue #997, issue #1022 (m3 cloud-GPU follow-up)

> **ADR number renumbered 0056 → 0057 → 0058** (2026-05-19) — 동시 충돌 두 건을 피하기 위함: ADR 0056 은 PR #987 (`rationality_judge`, issue #969) 로 머지 + ADR 0057 은 PR #988 (`bm25s additive backend`) 로 머지. 최종 번호 `0058` 은 ADR README.md 의 "Reserve the next number with the CLI before drafting" 규약을 따름.

## Context

ADR 0010 (2026-05-11) 은 `retrieval_backend ∈ {dense, hybrid}` 를 default `dense` 로 accept 하면서 BGE-M3 multi-channel (sparse + colbert) 은 자체 ablation 으로 deferred 했다. hybrid knob 의 real-data 측정(measurement)은 ADR 0032 (torch≥2.6 install) 에 의해 2026-05-13 까지 막혀 있었다. Phase 3 (PR #956) 가 첫 real-data 측정이고, Phase 3.5 (PR #966) 가 BGE-M3 을 세 번째 arm 으로 추가했다.

처음 두 시도는 오도하는(misleading) 근거(evidence)를 냈다. Phase 3 (PR #956) 는 `hybrid_bm25_k{30,60,100}` 세 변형이 모두 byte-identical 이라 보고하고 그 평탄함을 BM25 채널 지배(dominance) 탓으로 돌렸다. 그 결론은 틀렸다 — Phase 3 runner 가 second-stage `apply_fusion_and_reranking` 없이 `retrieve_candidates` (candidate 생성만) 를 호출해서 hybrid·m3 backend 의 per-case ranking 이 chunk_id 삽입 순서로 collapse 했다 (placeholder score = 0.0). Phase 3.5 (PR #966) 는 runner 배선(wire-up)을 고쳤지만 인덱스 빌드가 CSV `text` fallback 로 라우팅되어 Phase 3 가 쓴 26,376-chunk kordoc-추출 코퍼스 대신 **898-chunk insufficient corpus artifact** 를 냈다. 이 산출물은 retired invalid evidence 이며, 더 이상 본 ADR 의 load-bearing 근거로 쓰지 않는다.

본 ADR 의 역사적 결정은 남기되, 측정 근거(evidence) 상태는 정정한다.
현재 허용되는 private real100 Phase 3.5 측정 기준은 동일 100 docs · 동일
chunking 전략 위에서 kordoc cache/source 로 재빌드한 26k급 index 다. `scripts/phase35_m3_ablation.py`
는 `num_documents >= 50` 이고 `0 < num_chunks <= 1000` 인 index 를 측정 전
실패시켜 CSV fallback 산출물이 다시 근거로 들어오지 못하게 한다.

## Decision

**Scenario A 승리**: `agentic_full` 과 `metadata_first` preset 의 `retrieval_backend` default 를 `dense` 에서 `hybrid` (BGE-M3 dense + BM25 위 RRF k=60) 로 전환. **`naive_baseline` preset 은 `dense` 유지 (ADR 0001 불변량 byte-identical)** — default 변경은 non-baseline preset 에만 적용.

`m3` (BGE-M3 dense + sparse + colbert 위 3-way RRF) 은 **cloud-GPU follow-up 으로 deferred** — 16GB Apple Silicon 의 로컬 측정 시도가 m3 cache 빌드 완료 전에 unified memory 를 소진했다 (33GB swap pool 소비 + system crash). 이 deferral 은 absolute rule #5 에 따른 정직한 보고; m3 multi-channel 질문은 cloud-GPU one-off run 을 위해 open 상태로 남는다 (~$1 budget; A10/T4 GPU 로 <30 min 완료 예상).

**Amendment (ADR 0074):** hybrid retrieval 채택은 유지하지만, preset default를
eval claim의 암묵 근거로 쓰지 않는다. Claim-bearing eval row는
`retrieval_backend` 등 retrieval stage knob을 직접 선언해야 하며, dense control은
`full_dense`처럼 명시적으로 남긴다. API/demo default 또는 production preset
default는 retrieval 평가 baseline을 이동시키지 않는다.

### Retired Evidence

Retired invalid / insufficient corpus artifact: CSV fallback **898 chunks**,
n=221 cases, dense_m3 vs hybrid_bm25_k60_m3. 이 artifact 는 private real100
계열에서 요구하는 kordoc 26k급 corpus 가 아니므로 deleted report path 를
참조하지 않고, 수치도 future claim 의 근거로 사용하지 않는다.

이 정정은 public-fixture-smoke 표면에는 적용하지 않는다. Small fixture index 는
CI smoke 용이고, `num_documents >= 50` private real100 계열 산출물만 guard 대상이다.

**Phase 3 PR #956 결론 retracted**: "BM25 channel dominance → hybrid_bm25 SIG-negative" 는 틀렸다. Phase 3 runner 버그 (`apply_fusion_and_reranking` 호출 누락, PR-H #994 에서 수정) 가 hybrid_k 변형을 chunk_id 삽입 순서로 collapse 시켰다. 수정 + semantic 임베딩 적용 시 hybrid_bm25 는 지배적 hardcase 카테고리에서 SIG-positive 다.

## Consequences

**Scenario A 적용** (default 가 `hybrid` 로 전환):
- README 가 default-mode framing 을 업데이트해야 함; `eval/config.yaml` `agentic_full` preset annotation 이 뒤집힘 (follow-up 구현 PR, 본 ADR 에 의해 블록 안 됨)
- BM25 의존성 (`rank_bm25`) 이 production 에 load-bearing 화 (이미 `requirements.txt` 에 있어 install footprint 불변)
- Latency 예산: retired 898-chunk artifact 의 latency 수치는 더 이상 claim-bearing 근거가 아니다. Future Phase 3.5 수치는 kordoc 26k급 index 에서 다시 측정해야 한다.
- **Provenance 정정 (2026-05-22, issue #1285)**: 위 line 48 follow-up 을 구현한 PR #1000 의 `rag_pipeline_presets.py` 주석이 "eval `full` row 는 이미 explicit hybrid 이라 eval 에 영향 없음" 이라 잘못 주장했다. 실제로 `full` row 는 `retrieval_backend` 를 선언하지 않아 preset default 를 상속하므로, 이 flip 은 eval `full` (및 full_llm/no_rerank/retrieval_only/no_metadata_first) 행을 dense → hybrid 로 이동시켰다. 정정 (issue #1285): (1) `full` 행은 hybrid 유지 (canonical headline = production default 반영), (2) 본 ADR 의 dense-vs-hybrid 재현성을 위해 명시적 dense control 행 `full_dense` 를 `eval/config.yaml` 에 추가, (3) 위 false 주석을 정정. `full` 이 `hybrid_bm25` 와 기능적으로 동일해진 것은 의도된 것 (canonical headline vs #149 k=60 anchor) 이며 #800/#804 trap 과 무관함을 양쪽 행 주석에 명시.

**본 ADR 이 lock 하는 것**:
- 향후 모든 ablation runner 의 `apply_fusion_and_reranking` 배선 — Phase 3 PR #956 버그 재발 금지 (Phase 3 는 PR-H #994 에서 수정)
- `data/index/real100_m3` 의 kordoc-as-source-of-truth **목표** (`BIDMATE_KORDOC_CACHE_DIR` bypass 로 enable) — 898-chunk CSV fallback 산출물은 retired invalid artifact 이며, 향후 production 빌드가 csv_text 로 silent fallback 하지 않도록 guard 한다.
- Apple Silicon 에서 향후 m3-channel 측정을 위한 runner-side m3 colbert batching 패턴 (`scripts/phase35_m3_ablation.py::_prime_m3_index_cache_and_colbert`)
- memory-constrained 측정 환경을 위한 `BIDMATE_SKIP_M3_VARIANT=1` env var (issue #997 에서 도입)

**Deferred** (m3 multi-channel 질문):
- 16GB Apple Silicon unified memory 는 26k chunks 용 BGE-M3 colbert cache 를 담을 수 없음 (per-token per-chunk 벡터 ≈ 10-15GB, 거기에 model weights + activations → swap thrashing + system crash 관측). Local-only m3 측정 infeasible.
- **50-doc subset 확인 (2026-05-19)**: ADR-0058 이후 50-doc subset 을 on-prem proxy 빌드 (`data/index/real50_m3`, ~13k chunks) 로 실행한 시도가 8GB swap pool 완전 소진 + ~12.5% CPU efficiency (swap-thrash 가 compute 지배) 로 40m55s 간 stall. subset 절반 크기가 wall-time 을 절반으로 줄이지 못함 → `BIDMATE_M3_USE_FP16=1` + `BIDMATE_M3_INT8_CACHE=1` tuning 무관하게 on-prem fallback 전략 실패.
- Cloud-GPU one-off (Modal/RunPod ~$1, A10/T4 GPU 로 <30 min 예상) — **[issue #1022](https://github.com/hskim-solv/BidMate-DocAgent/issues/1022) 에서 추적**. `agentic_full` default flip 에 블로커 없음 — m3 는 ADR 0010 에 따라 항상 research opt-in 예정이었음.
  - **Closeout (2026-06-02, issue #1022 superseded)**: cloud-GPU 측정을 실행하지 않고 #1022 를 superseded 로 닫음. 사유 3가지. (1) 이슈 생성(2026-05-19) 이후 real100→real100_v2 마이그레이션이 이슈가 겨냥한 v1 표면(`data/index/real100_m3`, `make real-eval-semantic`, kordoc 26k corpus, n=221 문구)을 전부 archive-only 로 banned — `scripts/check_real100_v2_only.py` fail-closed 가드 + Makefile `real-eval-semantic` disabled(exit 2)가 강제. (2) Phase 2.0 ([PR #1394](https://github.com/hskim-solv/BidMate-DocAgent/pull/1394) / [ADR 0073](./0073-real100-retrieval-surface-keeps-minilm.md), 2026-05-23) 이 real100 retrieval 표면에서 BGE-M3(-korean) **dense** 채널을 측정 → recall@10 +2.0pp vs MiniLM, CI overlap (NS); ADR 0019 condition-3 미발동으로 MiniLM 유지, default-flip 후보는 BGE-M3 가 아니라 KURE-v1. (3) 본 ADR Decision 과 #1022 자체 decision-policies 가 "어느 m3 outcome 도 hybrid default 를 바꾸지 않음"을 사전 못박음 → 측정이 production 결정-무관. **정밀 구분**: #1394 는 dense 채널 임베딩 모델만 교체했고, m3 *multi-channel*(dense + sparse + colbert 3-way RRF) 슬라이버는 미측정 상태로 남는다. 향후 real100_v2-native m3 variant 가 별도 ablation 으로 재오픈할 수 있으나 default-flip 트리거가 아니므로 우선순위 낮음. Runner (`scripts/phase35_m3_ablation.py`) 와 batching 패턴은 그대로 보존 — 위 line 57 lock 유지.

## Alternatives considered

- **default 를 `m3` (3-way RRF) 로 전환** — 기각. `m3` 가 일부 카테고리에서 가장 강한 SIG lift 를 보여도 dense 대비 2.2x latency + ~10GB colbert cache footprint 가 측정된 modest gain 대비 production 배포를 정당화 못 함. Research opt-in only.
- **코퍼스 확장 대기를 위해 결정 defer** — 기각. 100-doc real100 이 오늘의 production target 코퍼스; 향후 코퍼스 확장 (ADR 0050 / 0052 trajectory) 이 자체 ablation 으로 질문 재오픈 가능. Defer 하면 ADR 0010 의 "deferred" status 가 영구 limbo 에 남음.
- **BGE-M3 대신 Phase 3 의 hashing 인덱스에서 재실행** — 본 ADR 대체로는 기각 (PR-H 가 retraction note 별도 추적). hashing 의 score-collision 동작은 다른 질문; Phase 3.5 축은 "production semantic 임베딩이 답을 바꾸는가?"

## Verification

<!-- verifies-key: docs/private-real-eval-inventory.md:Removed 898-Chunk History -->
<!-- verifies-key: tests/test_phase35_m3_ablation.py:test_guard_rejects_low_chunk_private_real100_index -->
<!-- verifies-key: eval/config.yaml:retrieval_backend -->

Inventory 문서와 Phase 3.5 guard test 가 retired 898-chunk artifact 의 재커밋과
재측정을 막는다. `eval/config.yaml` 은 scenario A 또는 B default 를 명시 반영해야
함 (annotation 또는 value 변경). 참조 파일이 keyed 섹션을 잃으면
`scripts/_governance.py --lint-adr-consequences` linter 가 본 ADR 을 flag 한다.
