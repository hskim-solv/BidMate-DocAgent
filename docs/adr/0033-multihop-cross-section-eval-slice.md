# 0033: Multi-hop cross-section eval slice를 직교 saturation falsifier로

- **Status**: accepted
- **Date**: 2026-05-13
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (naive_baseline 불변식), [ADR 0002](./0002-metadata-first-retrieval.md) (메타데이터 우선 배경), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) (public/private eval 분리), [ADR 0010](./0010-hybrid-bm25-dense-retrieval-rrf.md) (하이브리드 BM25), [ADR 0019](./0019-embedding-default-stays-minilm.md) (임베딩 default lock), [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) (Phase 1.3 closure), [ADR 0032](./0032-eval-saturation-routed-subset.md) (saturation falsifier — routed axis), issue #533

## TL;DR

- ADR 0032(routing axis)에 이은 두 번째 직교 saturation falsifier: query complexity axis.
- 50개 다단계(multi-hop) 합성 query slice를 추가 — ≥ 2 비연속 섹션/문서 근거 합성 필요. LLM judge 필터로 단일 chunk 답변 가능 query 거부.
- ADR 0019 re-open 조건 보완. 결과에 따라 saturation 가설 routing/complexity 축 모두 판정 가능.

## 배경

[ADR 0032](./0032-eval-saturation-routed-subset.md)는 saturation 가설의 **routing 축**을 다룬다: 메타데이터 우선이 다수 공개 합성 query에서 dense 검색을 우회해 default `full` 파이프라인에서 임베딩 spread가 측정 불가. `agentic_full_routed` 프리셋(`metadata_first: false`)이 그 축을 실제 측정 surface로 변환.

**두 번째 직교 saturation 축이 있다**: 쿼리 복잡도. 공개 합성 n=42 surface는 *단일 hop* 쿼리 우세 — 답이 단일 연속 chunk/섹션에 있는 질문. 단일 hop에서는 다섯 임베딩 모두 적절한 BM25 / 하이브리드 fallback으로 같은 top-k chunk에 도달 가능, 임베딩 품질과 무관하게 정확도 메트릭 saturation. 이 축은 메타데이터 우선 라우팅과 독립:

- Routed-subset 쿼리(`metadata_first: false`)도 답이 한 chunk에 있으면 여전히 단일 hop.
- 메타데이터 우선 쿼리도 답이 ≥ 2 섹션/문서 근거 합성을 요구하면 multi-hop (이 경우 `full` 파이프라인의 근거 집계 단계에서 검색 라우팅이 이미 강제됨).

**Multi-hop 쿼리** — 답이 ≥ 2 비연속 섹션/문서 근거 결합을 요구하는 경우 — 는 검색·집계 단계를 더 강하게 작동시킨다:

1. Dense 벡터가 nearest neighbour 하나가 아니라 두 관련 섹션 모두 surface해야 함.
2. 검증기가 단일 chunk로 완전히 뒷받침되지 않는 주장을 근거 연결.
3. 답변 빌더가 여러 `evidence_text` span 합성.

분석 변형 행이 multi-hop에서 ≥ +5pp spread, 단일 hop에서 ≈ 0pp를 보이면 saturation은 *쿼리 복잡도 기인*(단일 hop surface가 불충분 discriminator). 두 surface 모두 ≈ 0pp면 시스템이 분석 변형 매트릭스 전반에 진정으로 robust — 0pp 발견이 *eval 설계 artifact가 아닌* publishable positive 결과.

**ADR 0032와 연결**: 두 saturation falsifier는 *함께* 실행되도록 설계. ADR 0032가 routing 축을 falsify, ADR 0033이 복잡도 축을 falsify. 두 결과를 모두 읽으면 0pp 패턴이 routing 기인인지, 복잡도 기인인지, 둘 다인지, 어느 쪽도 아닌지 — saturation 가설의 4분면 판정 가능.

## 결정

**50개 multi-hop cross-section 합성 eval subset**을 별도 측정 슬라이스로 추가. 슬라이스는 additive: 기존 eval config, `naive_baseline` 골든, ADR 0001/0003/0005 불변식 무변.

### 이 ADR 범위 (결정 기록 only)

본 ADR은 결정과 수락 기준만 문서화. 구현 산출물은 별도 follow-up:

- `scripts/synthesize_multihop_queries.py` — 합성 스크립트
- `eval/dev_queries_multihop_v1.jsonl` — 50개 합성 데이터셋
- `eval/config.yaml`의 multi-hop eval 슬라이스 추가 (load-bearing; PR의 5b real-eval-delta 필요)

### 쿼리 합성 전략

세 query 타입이 별개 multi-hop 패턴을 cover:

1. **Cross-section within a document** — 답이 같은 RFP §2 조건과 §5 값의 결합. 예: "입찰 참여 기준 금액이 충족될 경우 보증금 납부 방식은?" (§입찰 조건의 조건 + §계약 보증금의 값).

2. **Cross-document comparison** — 답이 ≥ 2 별개 RFP의 동일 필드(예: 계약 기간) 비교. `eval/config.yaml`의 `comparison` 타입에 부분 cover되지만, 기존 슬라이스가 *반드시* ≥ 2 chunk를 요구하지 않을 수 있어 — 신규 multi-hop 쿼리는 단일 chunk 답변 거부 검증 필수.

3. **Multi-step conditional reasoning** — 답이 chain 추적 시에만 도달: "X applies when Y, Y는 §3에서 Z로 정의". 각 단계는 개별 검색 가능하지만 올바른 답은 chain 필요.

### LLM 평가자 품질 필터

합성 쿼리는 LLM 평가자(`eval/synthetic_judge.py` / `eval/llm_judge.py`)의 커스텀 `multihop_valid` rubric을 거쳐 단일 chunk 답변 가능 쿼리를 **거부**. `multihop_valid: true` 쿼리만 `eval/dev_queries_multihop_v1.jsonl`에 진입. 평가자 prompt는 reproducibility 위해 데이터셋과 함께 로깅.

### 측정 surface

- Eval config: `eval/multihop_config.yaml`(ADR 0032 Step 1의 `eval/routed_config.yaml` 패턴 미러링).
- 분석 변형 행: 최소 `naive_baseline`, `agentic_full`, `agentic_full_routed`(ADR 0032 surface, cross-axis 비교용), ADR 0019/0021의 5 임베딩 후보.
- 백엔드: sentence-transformers (실 임베딩); hashing은 multi-hop spread 측정에 무의미.
- 보고 메트릭: `accuracy`, `groundedness`, `citation_precision` + bootstrap 95% CIs (ADR 0032와 동일).

### 수락 기준

| 결과 | 해석 | ADR 결과 |
|---|---|---|
| Multi-hop 슬라이스에서 분석 변형 spread ≥ +5pp | 복잡도 축이 실재 discriminator; 단일 hop surface는 복잡도 saturated | ADR 0019 re-open 조건 보완: routed subset에 더해 multi-hop 슬라이스 필요 |
| ADR 0032 routed surface와 결합 시에만 spread ≥ +5pp | 두 축 동시 필요 | ADR 0019 re-open 조건 보완: *두* surface 모두 필요 |
| Multi-hop 슬라이스(두 routing 모드) spread < 5pp | 시스템 진정으로 robust; saturation은 쿼리 복잡도 기인 아님 | ADR 0033 negative 결과 `accepted` close; 단일 hop surface 임베딩 비교에 충분 선언 |

세 결과 모두 방향에 무관하게 `docs/eval/embedding-ablation.md` Phase 1.4 섹션에 published. Negative 결과(spread < 5pp)가 가장 해석 가능 — 0pp 발견이 아키텍처의 실재 property임을 확정하고 eval 설계 artifact가 아님.

### ADR 0001 / 0005 보존

- `eval/config.yaml`은 이 PR에서 변경 없음. Multi-hop 슬라이스는 별도 `eval/multihop_config.yaml`(additive, opt-in, `eval/routed_config.yaml`과 동일 패턴).
- `naive_baseline` 골든 byte 무변.
- Multi-hop 데이터셋은 *합성* (동일 공개 도메인 RFP fixture에서 생성), ADR 0005 공개 합성 surface 내부. 비공개 데이터 unused.
- CI는 결정론적 공개 surface 위해 `EMBEDDING_BACKEND=hashing` 유지; multi-hop 실 임베딩 실행은 opt-in 로컬 only.

## 결과

**이득**

- 두 번째 직교 saturation falsifier 축 추가. ADR 0032와 함께 0pp on `full`이 routing 기인인지, 복잡도 기인인지, 어느 쪽도 아닌지 판정 가능.
- Multi-hop 합성 자체가 portfolio signal: cross-section query 구축 + LLM 평가자 필터가 *좋은 eval discriminator 이해*를 입증 — 단순 모델 실행 아닌.
- Negative 결과(spread < 5pp)는 publishable: 시스템이 테스트 범위 내 쿼리 복잡도에 진정 robust 의미, ADR 0002 메타데이터 우선 설계 스토리 강화.

**비용**

- 50개 합성에 LLM 평가자 필터링 실행 필요(~50 API 호출; 일회성, 데이터셋 commit 후 CI에서 재생성 안 함).
- `eval/multihop_config.yaml`이 두 번째 병렬 config 파일 추가 (`eval/routed_config.yaml`과 동일 유지보수 패턴).
- 측정에 실 임베딩(sentence-transformers) 필요, CI hashing 백엔드 아님. 결과는 비공개 실행 산출물로 `docs/eval/embedding-ablation.md`에 published — ADR 0021 Phase 1.3 동일 패턴.

**제약 (불변)**

- ADR 0001: `naive_baseline` 불변식 보존.
- ADR 0003: answer/citation 계약 무변.
- ADR 0005: 데이터셋 공개 합성 유지 (비공개 RFP 데이터 미사용).

## ADR 0032 관계

| | ADR 0032 | ADR 0033 |
|---|---|---|
| **Falsify saturation 축** | Routing (메타데이터 우선이 dense 우회) | Complexity (단일 hop이 임베딩 미구별) |
| **메커니즘** | `agentic_full_routed` 프리셋(`metadata_first: false`) | Multi-hop 50개 데이터셋 (≥ 2 chunk 합성 강제) |
| **Config** | `eval/routed_config.yaml` | `eval/multihop_config.yaml` (follow-up) |
| **ADR 0001 영향** | 없음 | 없음 |
| **의존성** | 독립 | 독립; 동시 실행 권장 |

## 검토한 대안

- **기존 `eval/dev_queries_v1.jsonl`에 multi-hop 항목 확장.** 기각: 기존 데이터셋은 공개 CI surface로 골든 byte pinned. Multi-hop 추가는 골든 변경 + `schema_version` bump 필요. 별도 `dev_queries_multihop_v1.jsonl`이 additive.
- **`eval/config.yaml`의 `comparison` query 타입을 multi-hop proxy로.** 기각: 비교 슬라이스는 다문서 *메타데이터* 비교 측정(예: 두 사업 계약 기간), 파이프라인 내 ≥ 2 비연속 근거 span 결합 미요구 — 두 문서의 같은 컬럼 lookup은 두 단일 hop 호출로 답변 가능. 이 ADR의 multi-hop 정의는 *답*이 단일 chunk로 구성 불가 필요.
- **50개는 부족; 200개 사용.** 반론: ADR 0032가 routed subset에서 n ≥ 10 사용 — primary signal이 spread 존재 여부지 magnitude 추정이 아니기 때문. 50개는 ≥ 5pp spread 감지 power 충분 (n=50에서 절대 ≈ 2.5 항목) + 합성 비용 관리. 초기 50개가 borderline이면 follow-up으로 100개 확장.
- **LLM 평가자 필터링 생략, 모든 합성 쿼리 포함.** 기각: `multihop_valid` 필터 없으면 단일 hop 쿼리(자동 생성 쉬움)가 multi-hop signal 희석. 필터가 "multi-hop" 라벨 신뢰성 메커니즘.

## See also

- [ADR 0032](./0032-eval-saturation-routed-subset.md) — 동반 routing 축 saturation falsifier.
- [ADR 0019](./0019-embedding-default-stays-minilm.md) + [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) — 이 ADR이 보완하는 임베딩 default lock re-open 조건.
- [`eval/routed_config.yaml`](../../eval/routed_config.yaml) — 이 ADR의 `eval/multihop_config.yaml`이 따를 패턴.
- [`eval/synthetic_judge.py`](../../eval/synthetic_judge.py) / [`eval/llm_judge.py`](../../eval/llm_judge.py) — 품질 필터가 재사용할 LLM 평가자 인프라.
- `eval/dev_queries_multihop_v1.jsonl` — 데이터셋 산출물 (Phase 1.5: n=15 stubs).
- `scripts/synthesize_multihop_queries.py` — 실 LLM 합성 follow-up PR 스크립트.
- `docs/eval/embedding-ablation.md` — Phase 1.4 섹션; 실 합성으로 stub 대체 후 Phase 1.5 결과 추가.

## Phase 1.5 update (2026-05-14, closes #667)

**Status change**: proposed → accepted (인프라 완성, stub 배치).

`eval/dev_queries_multihop_v1.jsonl` n=3 stub → **n=15** (각 `multihop_type` 5개) 확장:

| `multihop_type` | Count | Example query |
|---|---|---|
| `cross_section_within_doc` | 5 | 입찰 자격 조건과 보증금 면제 조건의 교차 요건 |
| `cross_document_comparison` | 5 | D01/D02 입찰 보증금 납부 조건 비교 |
| `multi_step_conditional` | 5 | 낙찰 거부 시 보증금 처리 절차 |

전체 15개 항목 `multihop_valid: true`, non-empty `must_include` 토큰 리스트. `gold_answer`는 `make synthesize-multihop` 실 RFP 실행 전까지 stub (`[STUB — requires real LLM synthesis]`) 유지.

**회귀 가드**: `tests/test_multihop_chunking_regression.py` 3 cases 추가:
- 데이터셋 크기 게이트 (min 15 rows)
- 스키마 validity (모든 row 필수 필드)
- Multi-hop 구조 테스트 (must_include 토큰이 ≥ 2 합성 섹션 span)

**ADR 0001 불변식 보존**: `eval/config.yaml` 및 `eval/dev_queries_v1.jsonl`(primary 골든 surface) 무변.
