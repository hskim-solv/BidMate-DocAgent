# ADR 0053 — Distinguishing-power 바닥(floor) ablation (`random` retrieval + `single_chunk` preset)

- Status: Accepted
- Implemented: #939 (2026-05-17) — `random` retrieval backend + `single_chunk` preset + `eval/config.yaml` floor ablation rows (`random_retrieval`, `single_chunk`) + regression tests (PR-5a); #946 (2026-05-17) — `scripts/distinguishing_power.py` gauge + 첫 n=221 측정 + `reports/real100/distinguishing_power.{md,aggregate.json}` (PR-5b)
- Date: 2026-05-17
- Authors: Hyunsoo Kim
- Related: ADR 0001 (naive_baseline 불변성), ADR 0005 (eval 분리(split)), ADR 0030 (leaderboard 표면), ADR 0044 (real-eval n trajectory — PR-B 에서 ADR 0052 로 superseded 진행 중)
- Issue: #938

## Context

`eval-framework-progressive-audit` skill (Phase 1, step 2) 은 **세 개의 "broken" 기준선(baseline)** 을 요구한다 — 유일한 역할은 눈에 띄게 실패하는 것이며, `random_retrieval`, `no_verifier`, `single_chunk` 이다. 기본 경로의 정확도(accuracy) / 근거성(groundedness)이 이들 중 하나의 noise 범위 안으로 무너지면, 기본 경로가 실질적 작업을 안 하고 있다는 신호다 — leaderboard 는 움직이지만 실제 역량은 측정되지 않는 Goodhart 형 함정.

`origin/main` 의 현재 상태:

- ✅ `no_verifier_retry` ablation row 는 이미 `eval/config.yaml:180` 에 존재 (`no_verifier` 바닥 커버).
- ❌ `random_retrieval` row 없음 — `VALID_RETRIEVAL_BACKENDS` 가 `{"dense", "hybrid", "m3"}` 였음. 결정적(deterministic) random ranking primitive 부재.
- ❌ `single_chunk` preset 없음 — 기존 모든 preset 은 `top_k ≥ 4` 검색.

이 두 바닥 없이는 leaderboard 가 **"우리 검색(retrieval)이 제 몫을 하는가?"** 에 답할 수 없다. Companion: PR-5b (issue TBD) 가 실제 delta-vs-floor 신호 계산용 `scripts/distinguishing_power.py` 추가.

## Decision

1. **`VALID_RETRIEVAL_BACKENDS` 확장** → `{"dense", "hybrid", "m3", "random"}`. 검증(validation)은 `rag_pipeline_presets.py` 에 있고 `rag_query.resolve_pipeline_config`, `rag_core.run_rag_query`, per-row eval loader 가 소비.

2. **`random` 을 short-circuit 분기로 구현** — `rag_retrieval.retrieve_candidates` 안에서 metadata filter 단계 **이후**, embedding / BM25 / M3 forward pass **이전** 에 발화. 필터된 각 후보(candidate)는 `SHA-256(query + "\x00" + chunk_id)` 에서 derive 한 `[0, 1]` uniform 점수를 받음 — `(query, chunk_id)` 별 결정적(deterministic)이라:
   - 같은 query 는 run 전반에서 같은 ranking 생산 (test-friendly, eval-reproducible).
   - 다른 query 는 다른 ordering 산출 (degenerate "항상 chunk-001 반환" 동작 회피).
   - 모델 호출 없음 — embedding / inference 비용 0. 구성상 CI-safe.

3. **`single_chunk` 파이프라인 preset 추가** — `PIPELINE_PRESETS` 에 `top_k=1`, 모든 post-retrieval enhancement off (`metadata_first=False`, `rerank=False`, `rerank_cross_encoder=False`, `verifier_retry=False`), `retrieval_backend="dense"`, `prompt_profile="minimal_grounded_extractive"`. 검색 엔지니어링 없이 contributor 가 손댈 법한 것을 mirror — "가장 가까운 chunk 하나만 잡으면?" 기준선.

4. **`eval/config.yaml` 에 두 ablation row 배선**:
   - `random_retrieval` — `pipeline: agentic_full` + `retrieval_backend: random` (full 파이프라인 형태 안에서 random-retrieval 효과를 isolate; 나머지 stack 은 켜진 상태 유지).
   - `single_chunk` — `pipeline: single_chunk` (위 preset 이 다른 모든 knob 운반).

5. **regression 테스트로 lock-in**: `tests/test_random_retrieval_regression.py` (5 tests: allow-list membership + diagnostics record + top-k 가 dense 와 다름 + determinism + cross-query differentiation), `tests/test_single_chunk_preset_regression.py` (4 tests: preset shape + top-k=1 end-to-end + verifier retry 없음).

## Why these two, why now

- **PR-B (ADR 0052, n=21 → n=200 hardcase 확장) 와의 순서(sequencing)**: distinguishing-power 신호는 noise floor 가 기본값과 바닥 사이 gap 아래인 n=200 에서만 의미 있음. PR-5b 의 첫 측정은 n=200 기준선 대상이므로, PR-5a (이 ADR) 가 baseline regen **이전** 에 착지해 floor row 가 n=200 baseline.aggregate.json 의 일부여야 함. 아니면 첫 distinguishing-power 측정이 floor 없는 기준선 대상이 되어 두 번째 baseline commit 을 강제.
- **`random_retrieval` 먼저** — 가장 깨끗한 "no signal" 레퍼런스이기 때문; `single_chunk` 은 약간 다른 질문에 답함 ("multi-chunk 검색이 제 몫을 하는가?"). 둘이 함께 두 distinguishing-power 축을 bracket.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| SHA-256 해시 대신 **`random.shuffle(candidates)`** | run 전반 비결정적 — eval 재현성 깨짐 (같은 eval row 가 매 CI run 마다 다른 메트릭 생산 → 실제 회귀 masking + flaky 실패 유발). |
| **Python `random.Random(seed=hash(query))` 사용** | `hash(query)` 가 Python 3 에서 프로세스별 salting (PEP 456) — 프로세스 전반 다른 결과 생산. SHA-256 은 portable. |
| **`single_chunk` 을 `eval/config.yaml` 전용 knob 로 (`naive_baseline` 에 `top_k: 1` override)** | preset 레벨 lock-in 상실. `top_k=4` 기본을 추가하는 미래 PR 이 floor 를 silently 깸. preset 항목이 의도를 명시화 + regression 테스트로 보호. |
| **`no_filter` 와 `no_chunking` 바닥도 추가 (full audit 목록)** | PR-5a 범위 밖 — `no_filter` 는 더 깊은 retrieval-side carve-out 필요, `no_chunking` 은 ingest-side 변경 필요. 첫 측정이 정당화하면 PR-5c/5d follow-up 으로 추적. |

## Consequences

### Positive
- leaderboard 가 두 개의 **반증 가능한(falsifiable) 하한(lower bound)** 획득 — `random_retrieval` 을 못 이기는 미래 "개선" 은 정의상 실제 개선 아님. 직접적 portfolio 주장: "우리는 절대 메트릭만이 아니라 distinguishing power 를 측정한다."
- PR-5b 의 `scripts/distinguishing_power.py` (follow-up) 가 모든 leaderboard 메트릭에 대해 `(default - floor) / (ceiling - floor)` 계산 가능 — "신호가 살아있는가" 단일 숫자 게이지(gauge).
- production 코드 경로 영향 0 — `random` short-circuit 은 `retrieval_backend` config 경유 opt-in; 기본 `dense` 무변경 (ADR 0001 byte-identity 불변식 보존).

### Negative
- eval 매트릭스에 ablation row 2개 추가 — `make eval-public` walltime 이 현재 per-row 비용의 ~2배 증가. 완화: `random` 은 가장 무거운 CI step (embedding) 을 skip 하므로 per-row 비용이 `naive_baseline` 대비 ~3배 빠름; net 추가는 작음.
- `retrieve_candidates` 의 `random` 분기가 아래 dense/hybrid/m3 경로와 공유하는 candidate-dict 빌드 코드(~30 LOC)를 중복. 비용이 유지보수 noise 가 되면 미래 cleanup 이 `_build_candidate_item` helper 로 factor out 가능.

### Invariance check
- **ADR 0001 (naive_baseline preset, byte-identity top-k)**: 무변경 — `naive_baseline` preset 항목 + `retrieval_backend="dense"` 기본 미수정.
- **ADR 0003 (answer contract schema_version=2)**: 무변경 — random/single_chunk 가 동일 evidence-dict shape 생산; answer renderer 는 retrieval backend 에 불변.
- **ADR 0005 (eval split public/private)**: 무변경 — 두 새 row 모두 `eval/config.yaml` (public synthetic 표면) 거주. real-eval 표면 (PR-B) 이 동일 preset registry 소비 → n=200 baseline.aggregate.json 이 floor 를 자동으로 pick up.
- **ADR 0030 (leaderboard surfaces)**: 확장이지 수정 아님 — 두 새 row 가 추가 컬럼으로 등장; 기존 컬럼 변화 없음.

## Out of scope

- **`scripts/distinguishing_power.py` + 첫 측정** — PR-5b follow-up. n=200 기준선 (PR-B) 에 block, PR-5a 자체엔 아님.
- **`no_filter` / `no_chunking` 바닥** — PR-5b 첫 측정이 기존 바닥 불충분 시 PR-5c/5d 후보.
- **`eval/real_config.local.yaml` 의 real-eval `random_retrieval` row** — eval-row provenance 일관성 위해 PR-B (n=200 baseline regen 과 페어) 에서 추가.
- **`_build_candidate_item` helper 추출 리팩터** — cleanup PR 까지 연기; 30-LOC 중복은 의도된 명료성이지 아직 technical debt 아님.

## Verification

<!-- verifies-key: rag_pipeline_presets.py:VALID_RETRIEVAL_BACKENDS -->
<!-- verifies-key: rag_pipeline_presets.py:single_chunk -->
<!-- verifies-key: rag_retrieval.py:retrieval_backend == "random" -->
<!-- verifies-key: tests/test_random_retrieval_regression.py:test_random_is_in_valid_retrieval_backends -->
<!-- verifies-key: tests/test_single_chunk_preset_regression.py:test_single_chunk_preset_shape -->
<!-- verifies-key: eval/config.yaml:random_retrieval -->

## References

- `eval-framework-progressive-audit` skill, Phase 1 step 2 (3-floors 체크리스트)
- `rag_retrieval.retrieve_candidates` — 구현 진입점
- `rag_pipeline_presets.VALID_RETRIEVAL_BACKENDS` / `PIPELINE_PRESETS` — config 단일 출처(single source of truth)
- `tests/test_random_retrieval_regression.py` + `tests/test_single_chunk_preset_regression.py` — lock 된 계약
- ADR 0001 (naive_baseline 불변성) — 보존 대상 불변식
- ADR 0044 → ADR 0052 (real-eval case 확장) — n=200 regen 이전 floor 착지 순서 근거

## Augmented by

- **ADR 0054** (`docs/adr/0054-conditional-on-answer-scorer-semantics.md`) — 첫 게이지 측정 (n=221, PR #946) 이 Goodhart 함정을 표면화: 5개 중 3개 품질 메트릭이 correct_refusal case 에서 vacuously-truthful 1.0 을 받아 high-abstention run 의 평균을 부풀림. ADR 0054 가 scorer semantics 를 수정 (품질 메트릭이 이제 실질적 답변 시도에 conditional); 이 ADR 의 게이지 공식은 무변경.
