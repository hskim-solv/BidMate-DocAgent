# 0058: Phase 3.5 mode-winner 결정 — Scenario A (default 를 hybrid BM25+BGE-M3 dense, RRF k=60 으로 전환)

- **Status**: accepted (kordoc-corpus measurement landed 2026-05-19; Scenario A finalized)
- **Date**: 2026-05-19 (Status accepted); 2026-05-18 (Status proposed)
- **Deciders**: hskim
- **Related**: [ADR 0001](0001-preserve-naive-baseline.md), [ADR 0005](0005-eval-split-public-synthetic-private-local.md), [ADR 0010](0010-hybrid-bm25-dense-retrieval-rrf.md), [ADR 0021](0021-bge-m3-completes-phase-1-3.md), [ADR 0025](0025-cost-frontier-defer-until-real-baselines.md), [ADR 0032](0032-eval-saturation-routed-subset.md), [ADR 0049](0049-kordoc-replaces-pyhwp-backend.md), PR #966 (Phase 3.5 measurement), PR #956 (Phase 3, retracted), issue #957, issue #997, issue #1022 (m3 cloud-GPU follow-up)

> **ADR number renumbered 0056 → 0057 → 0058** (2026-05-19) — 동시 충돌 두 건을 피하기 위함: ADR 0056 은 PR #987 (`rationality_judge`, issue #969) 로 머지 + ADR 0057 은 PR #988 (`bm25s additive backend`) 로 머지. 최종 번호 `0058` 은 ADR README.md 의 "Reserve the next number with the CLI before drafting" 규약을 따름.

## Context

ADR 0010 (2026-05-11) 은 `retrieval_backend ∈ {dense, hybrid}` 를 default `dense` 로 accept 하면서 BGE-M3 multi-channel (sparse + colbert) 은 자체 ablation 으로 deferred 했다. hybrid knob 의 real-data 측정(measurement)은 ADR 0032 (torch≥2.6 install) 에 의해 2026-05-13 까지 막혀 있었다. Phase 3 (PR #956) 가 첫 real-data 측정이고, Phase 3.5 (PR #966) 가 BGE-M3 을 세 번째 arm 으로 추가했다.

처음 두 시도는 오도하는(misleading) 근거(evidence)를 냈다. Phase 3 (PR #956) 는 `hybrid_bm25_k{30,60,100}` 세 변형이 모두 byte-identical 이라 보고하고 그 평탄함을 BM25 채널 지배(dominance) 탓으로 돌렸다. 그 결론은 틀렸다 — Phase 3 runner 가 second-stage `apply_fusion_and_reranking` 없이 `retrieve_candidates` (candidate 생성만) 를 호출해서 hybrid·m3 backend 의 per-case ranking 이 chunk_id 삽입 순서로 collapse 했다 (placeholder score = 0.0). Phase 3.5 (PR #966) 는 runner 배선(wire-up)을 고쳤지만 인덱스 빌드에 `--src data/data_list.csv` 를 써서 CSV `text`-column loader 로 라우팅됐고, Phase 3 가 쓴 26,376-chunk kordoc-추출 코퍼스 대신 898-chunk 코퍼스를 냈다. 그 측정은 internally valid 하지만 (3 변형이 동일 898-chunk 코퍼스 공유, paired CI delta 는 unbiased) 절대 `chunk_recall@k` 수치는 Phase 3 와 비교 불가이고 chunk-count caveat 가 REPORT.md Notes 를 지배했다.

본 ADR 의 근거는 kordoc-rebuilt 재측정이다: 동일 100 docs, 동일 chunking 전략 (`fixed`, `max_chars=520`, `overlap_sentences=1`), Phase 3 가 쓴 동일 chunking config, 단 이번엔 BGE-M3 1024-dim semantic 임베딩 위에서 `apply_fusion_and_reranking` 배선을 고쳐 실행. retraction 이력은 PR #966 의 REPORT.md Notes 와 본 ADR 의 Context 에 보존해 audit trail 을 정직하게 유지한다 (absolute rule #5).

## Decision

**Scenario A 승리**: `agentic_full` 과 `metadata_first` preset 의 `retrieval_backend` default 를 `dense` 에서 `hybrid` (BGE-M3 dense + BM25 위 RRF k=60) 로 전환. **`naive_baseline` preset 은 `dense` 유지 (ADR 0001 불변량 byte-identical)** — default 변경은 non-baseline preset 에만 적용.

`m3` (BGE-M3 dense + sparse + colbert 위 3-way RRF) 은 **cloud-GPU follow-up 으로 deferred** — 16GB Apple Silicon 의 로컬 측정 시도가 m3 cache 빌드 완료 전에 unified memory 를 소진했다 (33GB swap pool 소비 + system crash). 이 deferral 은 absolute rule #5 에 따른 정직한 보고; m3 multi-channel 질문은 cloud-GPU one-off run 을 위해 open 상태로 남는다 (~$1 budget; A10/T4 GPU 로 <30 min 완료 예상).

### Evidence (from `reports/retrieval/phase35_m3_20260518T214937Z_kordoc_no_m3/REPORT.md`)

측정: kordoc 26,376 chunks, n=221 cases, dense_m3 vs hybrid_bm25_k60_m3, paired bootstrap CI 95%, seeds 17/23/29.

이 측정은 [ADR 0005](0005-eval-split-public-synthetic-private-local.md) **private-local** 표면 (real100 코퍼스, gitignored; aggregate REPORT 만 commit 가능) 에서 실행 — public-synthetic 표면 아님. ADR 0005 에 따라 모든 신규 eval 표면은 한 쪽을 택하고, 이건 strictly-local 이므로 여기 절대 `chunk_recall@k` 수치는 reviewer-reproducible 아님 (paired CI delta + commit 된 REPORT 가 audit trail).

**Overall metrics** (hybrid_bm25_k60_m3 vs dense_m3, all SIG = paired CI fully above 0):
- `chunk_recall@10`: 0.288 → 0.340 (**+0.052 SIG**, CI +0.020/+0.088)
- `MRR`: 0.515 → 0.625 (**+0.110 SIG**, CI +0.056/+0.165)
- `ndcg@10`: 0.318 → 0.383 (**+0.065 SIG**, CI +0.032/+0.099)
- Latency p50: 559ms → 757ms (1.35x; ranking 품질 향상 대비 수용 가능)

**Per-category winners** (recall@10, paired CI vs dense_m3):
- `overall`: hybrid +0.052 SIG
- `multi_hop` (n=93): hybrid +0.043 SIG
- `distractor_heavy` (n=42): hybrid +0.067 SIG
- `long_context` (n=9): hybrid +0.133 SIG
- `no_answer` (n=2), `ambiguous_query` (n=1), `uncategorized` (n=13): NOT SIGNIFICANT (small N 또는 all-equal CI)

**Phase 3 PR #956 결론 retracted**: "BM25 channel dominance → hybrid_bm25 SIG-negative" 는 틀렸다. Phase 3 runner 버그 (`apply_fusion_and_reranking` 호출 누락, PR-H #994 에서 수정) 가 hybrid_k 변형을 chunk_id 삽입 순서로 collapse 시켰다. 수정 + semantic 임베딩 적용 시 hybrid_bm25 는 지배적 hardcase 카테고리에서 SIG-positive 다.

## Consequences

**Scenario A 적용** (default 가 `hybrid` 로 전환):
- README 가 default-mode framing 을 업데이트해야 함; `eval/config.yaml` `agentic_full` preset annotation 이 뒤집힘 (follow-up 구현 PR, 본 ADR 에 의해 블록 안 됨)
- BM25 의존성 (`rank_bm25`) 이 production 에 load-bearing 화 (이미 `requirements.txt` 에 있어 install footprint 불변)
- Latency 예산: kordoc 26k 측정에서 p50 기준 dense 의 1.35x (757ms vs 559ms)

**본 ADR 이 lock 하는 것**:
- 향후 모든 ablation runner 의 `apply_fusion_and_reranking` 배선 — Phase 3 PR #956 버그 재발 금지 (Phase 3 는 PR-H #994 에서 수정)
- `data/index/real100_m3` 의 kordoc-as-source-of-truth 규약 (production semantic 인덱스에 csv_text fallback 없음; PR #966 closeout 의 `BIDMATE_KORDOC_CACHE_DIR` bypass 가 enable)
- Apple Silicon 에서 향후 m3-channel 측정을 위한 runner-side m3 colbert batching 패턴 (`scripts/phase35_m3_ablation.py::_prime_m3_index_cache_and_colbert`)
- memory-constrained 측정 환경을 위한 `BIDMATE_SKIP_M3_VARIANT=1` env var (issue #997 에서 도입)

**Deferred** (m3 multi-channel 질문):
- 16GB Apple Silicon unified memory 는 26k chunks 용 BGE-M3 colbert cache 를 담을 수 없음 (per-token per-chunk 벡터 ≈ 10-15GB, 거기에 model weights + activations → swap thrashing + system crash 관측). Local-only m3 측정 infeasible.
- **50-doc subset 확인 (2026-05-19)**: ADR-0058 이후 50-doc subset 을 on-prem proxy 빌드 (`data/index/real50_m3`, ~13k chunks) 로 실행한 시도가 8GB swap pool 완전 소진 + ~12.5% CPU efficiency (swap-thrash 가 compute 지배) 로 40m55s 간 stall. subset 절반 크기가 wall-time 을 절반으로 줄이지 못함 → `BIDMATE_M3_USE_FP16=1` + `BIDMATE_M3_INT8_CACHE=1` tuning 무관하게 on-prem fallback 전략 실패.
- Cloud-GPU one-off (Modal/RunPod ~$1, A10/T4 GPU 로 <30 min 예상) — **[issue #1022](https://github.com/hskim-solv/BidMate-DocAgent/issues/1022) 에서 추적**. `agentic_full` default flip 에 블로커 없음 — m3 는 ADR 0010 에 따라 항상 research opt-in 예정이었음.

## Alternatives considered

- **default 를 `m3` (3-way RRF) 로 전환** — 기각. `m3` 가 일부 카테고리에서 가장 강한 SIG lift 를 보여도 dense 대비 2.2x latency + ~10GB colbert cache footprint 가 측정된 modest gain 대비 production 배포를 정당화 못 함. Research opt-in only.
- **코퍼스 확장 대기를 위해 결정 defer** — 기각. 100-doc real100 이 오늘의 production target 코퍼스; 향후 코퍼스 확장 (ADR 0050 / 0052 trajectory) 이 자체 ablation 으로 질문 재오픈 가능. Defer 하면 ADR 0010 의 "deferred" status 가 영구 limbo 에 남음.
- **BGE-M3 대신 Phase 3 의 hashing 인덱스에서 재실행** — 본 ADR 대체로는 기각 (PR-H 가 retraction note 별도 추적). hashing 의 score-collision 동작은 다른 질문; Phase 3.5 축은 "production semantic 임베딩이 답을 바꾸는가?"

## Verification

<!-- verifies-key: reports/retrieval/phase35_m3_20260518T214937Z_kordoc_no_m3/REPORT.md:Per-category winner -->
<!-- verifies-key: docs/adr/0010-hybrid-bm25-dense-retrieval-rrf.md:BGE-M3 ablation closeout -->
<!-- verifies-key: eval/config.yaml:retrieval_backend -->

kordoc-corpus REPORT.md 의 Per-category winner 섹션이 본 결정의 load-bearing 근거다. ADR 0010 은 여기로 되짚는 closeout 섹션을 획득해야 함 (PR-G). `eval/config.yaml` 은 scenario A 또는 B default 를 명시 반영해야 함 (annotation 또는 value 변경). 참조 파일이 keyed 섹션을 잃으면 `scripts/_governance.py --lint-adr-consequences` linter 가 본 ADR 을 flag 한다.
