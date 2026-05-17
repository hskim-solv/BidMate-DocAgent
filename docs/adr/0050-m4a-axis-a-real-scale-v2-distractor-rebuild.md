# 0050: M4-A axis-A real_scale_v2_distractor 재구축 + H/I/J/K 코퍼스 확장

- **Status**: proposed
- **Date**: 2026-05-17
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (naive_baseline ranking 불변), [ADR 0003](./0003-structured-answer-citation-contract.md) (답변 계약 schema_version=2), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) (eval 분리 경계), [ADR 0030](./0030-leaderboard-silence-threshold.md) (silence threshold; axis-A 신호 회복), [ADR 0044](./0044-realN-eval-case-expansion.md) (realN 케이스 확장 lineage), issue [#911](https://github.com/hskim-solv/BidMate-DocAgent/issues/911) (본 ADR)

## TL;DR

- axis-A 9-section ceiling 효과 제거 위해 `real_scale_v2_distractor` 새 annotation scale 도입 (doc-A/B/C 100+ sections)
- H/I/J/K 4개 신규 corpus 파일 추가 (Phase 1 Step 3 hook, 현재 consumer 0)
- ADR 0001 naive_baseline scoring logic + ADR 0003 schema_version=2 미터치

## 배경

axis-A annotation v1 이 합성 doc-A/B/C 를 각 9 sections 로 cap. 공개 합성 표면 모든 측정 run 이 13/13 PASS 반환 — axis-A 신호를 silent 포화시킨 **ceiling effect**. Phase 1 Step 2.5 trajectory dump (PR #910) 가 모든 케이스가 9-section 예산 내 fit 해 axis-A 판별력 0.

비공개 코퍼스 100-doc profiling pass (`docs/eval/axis-a-rebuild/axis_b_real_measurement.md` v4) 가 calibration anchor 제공: Upstage `heading1` 중앙값 ≈ doc 당 100 main 헤딩, kordoc cross-check 중앙값 39,511 한국어 자/doc. v1 의 9 sections 가 실제 분포의 1/10 — 모든 axis-A 측정이 "파이프라인이 tiny portfolio 처리 가능한가" 답이지 "실제 RFP 처리 가능한가" 아님.

별도로, Phase 1 Step 3 (n=200) 확장용 4개 corpus 변형 draft: **H** (long-context 마커, 70KB body), **I** (distractor 마커 — adversarial near-miss 섹션), **J** (lexical-overlap — golden top-k 쿼리와 collide 하는 vocabulary), **K** (medical-imaging 도메인 — vocabulary shift). 4개 모두 *미래 hook* (본 PR 내 consumer count 0) 이지만 지금 land 가 corpus 확장 stack 을 axis-A 두 번 터치 안 하고 additive 유지.

## 결정

`axis_a_scale="real_scale_v2_distractor"` 을 합성 doc-A/B/C 의 새 axis-A annotation scale 로 채택 + `data/raw/` 에 4개 새 corpus 파일 H/I/J/K 추가.

- **Scale anchor**: Upstage `heading1` 동등성 — sections 는 top-level outline 항목, sub-bullet 과 테이블 row 는 count 안 함. Section 수: doc-A = 103, doc-B = 105, doc-C = 102
- **지원 메타데이터 필드 6개** doc 당 추가 (additive — `evidence[].metadata` 는 ADR 0003 따라 open): `axis_a_acceptance_verdict`, `axis_a_scale_anchor`, `axis_a_scale_distractor_ref`, `axis_a_scale_measurement_ref`, `axis_a_scale_outline_ref`, `section_definition`
- **메타데이터가 cite 하는 reference 문서** (`distractor_definitions.md`, `m4a_doc_{a,b,c}_outline.md`, `axis_b_real_measurement.md`) 가 `reports/axis_a_rebuild/` (`reports/*` 규칙 아래 gitignored) 에서 `docs/eval/axis-a-rebuild/` 로 이동, cite URL 이 in-tree resolve
- **H/I/J/K** committed 되지만 unused — 본 PR 내 어떤 프리셋, eval config, 테스트도 참조 안 함. Phase 1 Step 3 n=200 확장 hook
- **인덱스 + golden 재생성** (`data/index/{index.json,embeddings.npy}` + `tests/data/{naive_baseline_top_k,answer_contract_shape}.json`). chunks: 9 → 383 (~42× 성장, 9 → 310 section-count fan-out + 4개 새 코퍼스 driven)
- **ADR 0001 naive_baseline scoring logic 미터치**. golden shift 는 corpus 변경의 *필연적 결과*, ranking-algorithm 변경 아님 — `naive_baseline_top_k.json` 가 새 corpus 대비 새 (chunk_id, score) pair 기록, 그러나 같은 `rag_core.run_rag_query(pipeline="naive_baseline")` 호출이 생산
- **ADR 0003 답변 계약 `schema_version=2` 보존**. 새 메타데이터 필드는 `evidence[].metadata` 내 additive; 계약 surface (`answer.{status, status_reason, query_type, claims, summary, insufficiency}` + top-level `evidence` + `answer_text`) 모양 동일

## 결과

- **axis-A 신호 capacity 회복**. 9-section ceiling 사라짐 — axis-A 측정이 이제 100+ sections portfolio 를 50, 10 과 구분 가능. 13/13 포화는 Phase 1 Step 3 케이스 land 시 측정 가능 pass/fail 분포로 spread 예상
- **인덱스 5MB → 아직** (`embeddings.npy` 13,952 → 588,416 bytes, ~42×). 50MB git-friendly threshold 미만; Phase 1 Step 3 가 n=200 케이스 추가하면 binary 가 LFS 재고 필요
- **`tests/data/naive_baseline_top_k.json` golden shift**. 새 corpus 가 새 chunk_id + score 생산. 테스트 불변 계약 — "같은 파이프라인 호출이 같은 답변" — 보존 (`tests/test_naive_baseline_ranking_invariance.py` 새 golden 대비 통과); 기저 expected 값이 정당하게 drift
- **H/I/J/K Phase 1 Step 3 까지 consumer-0**. 4개 새 corpus 파일 존재하나 아직 어떤 프리셋이나 eval 케이스도 load 안 함. 의도적 staging — corpus rebuild 내 land 가 corpus-확장 stack 을 1개 ADR 로 유지, 그러나 파일이 declarative-only 인 window 생성
- **Reference doc 위치 마이그레이션**. 사전 측정 노트 + 메타데이터 `*_ref` 필드에서 cite 한 `reports/axis_a_rebuild/*.md` 경로가 이제 `docs/eval/axis-a-rebuild/*.md`. 5개 파일 (axis_b_real_measurement, distractor_definitions, m4a_doc_{a,b,c}_outline) + doc-A/B/C JSON 내 `*_ref` 문자열이 lockstep sed-rewrite. 운영자-로컬 raw 측정 파일 (`reports/axis_a_rebuild/*.json`) 은 audit-trail 로 tree 외부 유지 (재현성 surface 아님)
- **ADR 0001 baseline-비교 계약 intact**. `make real-eval-delta` 가 새 인덱스 대비 실행 — `kordoc_rate` / `by_metadata_field` / `abstention_calibration` aggregation 이 corpus 모양 (주어진 corpus 에 deterministic) 이라 메트릭 read 는 shift 하지만 *계약* (키 존재, 값이 선언 범위 내) 은 유지
- **`reports/axis_a_rebuild/` 디렉토리 운영자-로컬 유지**. 디렉토리는 `reports/*` 아래 gitignored 유지; 5개 `.md` reference 문서만 tree 로 마이그레이션. raw JSON 측정 dump 는 로컬 유지

## 검토한 대안

- **v1 9-section scale 유지 + rebuild 를 Phase 1 Step 3 로 연기**. 거부: 13/13 ceiling 이 지금부터 Phase 1 Step 3 까지 모든 측정을 axis-A-blind 화. Phase 1 Step 2.5 trajectory dump (PR #910 에서 막 머지) 가 axis-A 가 trajectory 모든 케이스에 포화면 진단 가치의 절반 잃음
- **doc-A 만 rebuild, doc-B/C 는 v1 hold**. 거부: doc 간 axis-A 비교가 한 doc 이 다른 scale 일 때 noisy 화. Single-doc rebuild 가 ceiling 문제를 calibration 문제로 trade
- **2개 PR 로 split (axis-A rebuild 먼저, H/I/J/K corpus 두 번째)**. 거부: H/I/J/K corpus 도 `data/index/` rebuild 강제, golden 재생성 강제. 인덱스 rebuild + golden regen 2회 수행은 조직적 이득 없이 main-red 위험 window 2배 — 둘 다 production-code 영향 없는 순수 corpus 변경
- **더 작은 scale anchor 사용 (예: Upstage `heading1` 대신 `heading2`)**. 거부: 100-doc 측정이 `heading1` 이 도메인 전문가 reading model 의 "main section" 매치 레벨임 보임; `heading2` 는 doc 당 300+ sections (테이블 row, sub-clause) 생산, 청킹 전략 headroom 초과

## Verification

<!-- verifies-key: data/raw/rfp_agency_a_ai_quality.json:"axis_a_scale": "real_scale_v2_distractor" -->
<!-- verifies-key: data/raw/rfp_agency_b_mlops_governance.json:"axis_a_scale": "real_scale_v2_distractor" -->
<!-- verifies-key: data/raw/rfp_agency_c_chatbot.json:"axis_a_scale": "real_scale_v2_distractor" -->
<!-- verifies-key: docs/eval/axis-a-rebuild/distractor_definitions.md:real_scale_v2_distractor -->
<!-- verifies-key: tests/test_naive_baseline_ranking_invariance.py:GOLDEN_PATH -->
<!-- verifies-key: tests/test_answer_contract_snapshot.py:GOLDEN_PATH -->
