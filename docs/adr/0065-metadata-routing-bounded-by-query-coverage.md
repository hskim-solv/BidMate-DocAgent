# ADR 0065 — 메타데이터 라우팅은 질의 커버리지로 한정된다

- **Status**: Accepted
- **Date**: 2026-05-21
- **Related**: [0058](./0058-phase35-mode-winner.md) (hybrid 기본), [0002](./0002-metadata-first-retrieval.md) (메타데이터 우선 검색), [0001](./0001-preserve-naive-baseline.md) (baseline 불변), [0005](./0005-eval-split-public-synthetic-private-local.md) (eval 분리); PR #1108, issue #1107, issue #1113

## Context

검색 평가(retrieval-eval) 4단계 프로토콜의 Phase 4(메타데이터/필터링 ablation)를 real100 kordoc 26k 인덱스에서 측정했다 (PR #1108, n=114 답변 가능 케이스, paired CI 95%, seed 17/23/29, planner-bypass).

오라클(oracle) 메타데이터 — 답변 가능 케이스의 `expected_doc_ids[0]` 에서 조회한 정답 agency/project — 를 주입하면 4개 변형(`soft_agency` / `prefilter_agency` / `prefilter_project`) 모두 `no_metadata` 대비:

- `chunk_recall@10` **+0.21~0.22** (유의), 지배적 `multi_hop` 집단(cohort, n=93)은 **+0.23~0.24**;
- `MRR` +0.40~0.48, `ndcg@10` +0.30~0.35 (모두 유의);
- 강한 사전 필터(hard pre-filter)는 후보 풀을 26k 청크 → 1개 문서/기관으로 줄여 p50 지연시간(latency)을 3892ms → ~253ms (**~15배**), recall 은 동등하거나 우위 — Pareto-dominant.

**그러나 이 천장은 반사실적(counterfactual)이다.** 오라클은 텍스트에 기관/사업을 전혀 언급하지 않는 질의에도 정답 메타데이터를 주입했다. 운영(production) 검색은 질의 텍스트만 가진다. 재현 가능한 커버리지(coverage) 분석(`scripts/phase4_query_metadata_coverage.py`, `COVERAGE.md`)이 답변 가능 질의 n=118 을 의미 분류했다:

| 분류 | n | % | gold 존재 |
|---|---|---|---|
| metadata-identifiable | 40 | 33.9% | 37/40 |
| content-query | 77 | 65.3% | 77/77 |
| underspecified | 1 | 0.8% | 0/1 |

`metadata-identifiable` 만이 질의에서 도출 가능한 메타데이터로 라우팅(routing)할 수 있는 집단이다 (정답 기관/사업이 질의와 char-4gram 공유). 나머지 65.3% 는 사업 *내부* 내용(기능/스펙/요구사항)을 묻고 정답 청크가 거의 항상 존재하나(77/77) 라우팅으로 거를 메타데이터 신호가 없다.

## Decision

1. **메타데이터 라우팅은 ~34% `metadata-identifiable` 집단으로 한정된 좁은 선택적(opt-in) 부가 기능으로 다룬다 — 운영 기본값 변경이 아니다.** 오라클 +0.22 는 실현 가능한 이득이 아니라 "질의가 메타데이터를 명시했다면" 의 반사실적 상한이다.
2. **나머지 ~66% 의 주된 검색 지렛대(lever)는 내용 매칭(content matching)** — ADR 0058 `hybrid` 기본 + Phase 2 청킹(chunking) + Phase 3 순위(ranking) — 로 유지한다.
3. **운영 메타데이터 라우팅 손잡이(knob) 도입은 현실 질의 시점 추출기(query-time extractor, NER 또는 LLM 추출) 측정에 종속(gated)한다** (issue #1107 후속). 측정은 `follow_up` 집단 분리 + 약한/강한 필터(soft/hard filter) 비교 + 오라클 대비 실제 회수율을 포함한다. 외부/유료 추출기를 쓸 경우 ADR 0061 3조건(opt-in / baseline byte-identical / 데이터 경계) 준수.
4. `scripts/phase4_metadata_ablation.py` + `scripts/phase4_query_metadata_coverage.py` 가 이 결정의 재현 가능한 측정 표면(measurement surface)이다.

## Consequences

- 검색 기본(ADR 0058 `hybrid`) 불변, 새 운영 손잡이 보류. ADR 0002(메타데이터 우선)는 `metadata_first` 프리셋 한정 — 본 ADR 이 그 현실 적용 범위를 ~34% 로 정량화한다.
- 현실 추출기 측정(decision 3) 전에는 메타데이터 라우팅을 운영 lever 로 재고하지 않는다.
- 지연시간 Pareto(강한 사전 필터 ~15배) 결과를 향후 라우팅 설계 근거로 기록.
- ADR 0001 baseline byte-identical + ADR 0005 private/public 경계 보존: **committable** 산출물(`REPORT.md` / `deltas.json` / `metadata_specs.json`)은 qid + 카테고리 + 지표값만(문서/청크 텍스트 0). 단 현실 변형의 per-case `raw_results.json` 은 추출 품질 채점용 gold/extracted agency·project **실값**(= `data/data_list.csv` 비공개 카탈로그, pre-commit 하드 블록 ADR 0005 입력)을 담으므로 **strictly-local** — 커밋 금지, 로컬 재생성(`scripts/phase4_realistic_metadata_ablation.py`). 오라클 ablation(PR #1108)의 raw 는 agency/project 가 없어 committable 인 것과 대비된다 (경계 위반 정정: issue #1143).

## Alternatives considered

- **오라클 사전 필터를 지금 운영 손잡이로 채택** — +0.22 + 15배 지연시간 이득이 매력적이나 반사실적이고 현실 추출기가 없어 기각.
- **메타데이터 라우팅 전면 폐기** — ~34% 집단은 실재하는 좁은 기회라 기각 (decision 3 으로 측정 후 재평가).
- **본 ADR 을 현실 추출기 측정 후로 연기** — 한정 프레이밍 자체가 후속 측정의 전제를 고정하는 유용한 잠정 계약이고, 사용자 합의 시퀀스도 ADR-먼저라 기각.

## Verification

<!-- verifies-key: reports/retrieval/phase4_metadata_20260520T032829Z_kordoc/COVERAGE.md:query 의미 분류 -->
<!-- verifies-key: reports/retrieval/phase4_metadata_20260520T032829Z_kordoc/REPORT.md:카테고리별 winner -->
<!-- verifies-key: eval/config.yaml:retrieval_backend -->

- 커버리지 분류(34% / 66% / 0.8%)는 `COVERAGE.md` 의 `query 의미 분류` 표 — `scripts/phase4_query_metadata_coverage.py` 로 재현 (동일 인덱스+config → byte-identical).
- 오라클 천장(+0.21~0.22 유의)은 `REPORT.md` 의 `카테고리별 winner` + paired CI delta 표.
- 운영 검색 기본 불변은 `eval/config.yaml` 의 `retrieval_backend` (ADR 0058 의 `hybrid`, 본 ADR 로 미변경).
