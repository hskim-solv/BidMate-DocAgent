# 0010: Hybrid BM25 + dense 검색 + RRF 융합

(원래 [#159](https://github.com/hskim-solv/BidMate-DocAgent/pull/159) 에서 ADR 0009 로 랜딩, 먼저 랜딩한 동시 [`0009-external-baseline-comparison.md`](./0009-external-baseline-comparison.md) 와 파일시스템 충돌 해결 위해 0010 으로 renumber.)

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: [`rag_core.py`](../../rag_core.py), [ADR 0001](0001-preserve-naive-baseline.md), [ADR 0002](0002-metadata-first-retrieval.md), issue #119

## TL;DR

- `retrieval_backend ∈ {dense, hybrid}` 직교 knob 추가, default `dense` (ADR 0001 보존).
- `hybrid` 는 BM25 + dense 를 RRF(`k=60`) 융합 — score-scale 튜닝 회피.
- 희소-결정적 term(법령명·사업 코드·약칭) lexical 매치 갭 해결, 새 모델 의존성 없음.

## 배경

현재 검색은 `dense + lexical(Jaccard 토큰 overlap + topic substring) + 메타데이터` 가중([`rag_core.py:1832`](../../rag_core.py:1832)). lexical scorer 는 set-overlap 만 — term frequency·IDF 없음 — 한국어 RFP 쿼리를 지배하는 희소-결정적 term(법령명·사업 코드·기관 약칭·사업 식별번호)의 exact match 를 under-weight 한다. dense 만으로는 hashing fallback 에서 충돌하고 MiniLM 하에서 paraphrastic 이웃에 의해 희석. ADR 0002 가 *entity* 축(메타데이터 우선) anchor; *term* 축은 미해결.

BM25 는 lexical-match 기준선의 오랜 표준; RRF(Reciprocal Rank Fusion)는 score-scale 정규화 없이 두 이종 ranking 결합. 둘 다 well-understood·deterministic·모델 의존성 없음. BGE-M3 식 학습 sparse 검색도 동일 갭을 닫지만 임베딩 모델을 동시 변경 — 이슈 risks 섹션이 지적한 confound, 자체 분석 변형으로 deferred.

## 결정

직교 파이프라인 knob `retrieval_backend` 추가, 값 `{"dense", "hybrid"}`, 두 프리셋 모두 default `"dense"`. `"hybrid"` 시 dense cosine + BM25(`index.json` 의 chunk-token corpus) 양쪽으로 candidate ranking, RRF `k=60` 융합:

> `score = 1/(60 + rank_dense) + 1/(60 + rank_bm25)`

기존 `dense + lexical + metadata` 가중 경로는 `retrieval_backend == "dense"` 일 때 verbatim 보존. BM25 는 [`rag_core.py:450`](../../rag_core.py:450) 의 regex tokenizer 재사용(KoNLPy 없음, 이전 결정); `BM25Okapi` 인덱스는 lazy 빌드 + index 객체에 캐시(`index["_bm25"]`) — `index.json` schema 불변. 진단 필드 `bm25`·`rank_rrf` 가 기존 `dense/lexical/metadata` 옆에 `score_parts` 에 추가.

## 결과

**Wins**

- 희소-term 쿼리(사업 코드·약칭·외래어/한자 표기) lexical-match 갭 해결, 새 모델 비용 없음
- `retrieval_backend` 가 `retrieval_mode`(flat/hierarchical, ADR 0002) + `metadata_first` 와 직교 — 기존 6 row 옆 신규 row 로 clean ablation 가능
- default `"dense"` 가 `naive_baseline` bit-for-bit 보존 — ADR 0001 충족
- RRF 가 weighted fusion 의 score-scale 튜닝(dense ∈ [0,1] vs BM25 ∈ [0,∞)) 회피

**Costs**

- 신규 의존성 `rank_bm25` (pure-Python, MIT). CI + demo 환경에 pip install 1개 추가
- lazy BM25 빌드가 인덱스 첫 쿼리에 ~O(N·avg_tokens) 추가; 인덱스 객체 lifetime 동안 캐시
- `score_parts` schema 가 키 2개 증가. *진단* 필드이지 ADR 0003 답변 계약 일부 아님 — `schema_version` bump 불필요

## 한국어 형태소 tokenizer 레이어 (ADR 0031, 통합)

ADR 0031 이 이 ADR 의 hybrid BM25 표면 위에 직교 분석 변형으로 `bm25_tokenizer: "regex" | "kiwi"` 추가. ADR 0031 은 여기서 Superseded; 주요 결정 아래.

**결정 (ADR 0031, accepted 2026-05-13):** `rag_pipeline_presets.py` 에 `bm25_tokenizer` config 키 도입. 세 프리셋 모두 `"regex"` default(ADR 0001 + ADR 0010 baseline byte-equality 보존). `eval/config.yaml` 에 신규 분석 변형 row `full_kiwi` — `bm25_tokenizer: kiwi` + `retrieval_backend: hybrid`. `korean_lexicon.kiwi_tokens` 가 `kiwipiepy` lazy import — import 실패 시 regex 로 fallback(never-raise contract).

**재오픈 조건** (셋 모두 충족 시 kiwi 가 default):
1. 공개 synthetic eval (n=42) 가 kiwipiepy 설치 상태로 실행, real(non-fallback) `full_kiwi` row 생성
2. `full_kiwi` 가 `hybrid_bm25` 대비 `accuracy` 또는 `citation_precision` 에서 ≥ +3pp 향상 + 비중첩 95% CI
3. install footprint(~30MB `kiwipiepy`) + hard CI dep 화 여부를 문서화하는 후속 ADR

**Invariant:** ADR 0001 `naive_baseline` golden bit-identical (naive_baseline 은 `retrieval_backend: dense` 사용, BM25 절대 호출 X). 기존 hybrid row byte-equal.

## 검토한 대안

- **BGE-M3 sparse 채널** — 동일 갭 닫고 multi-vector 표현 동반. *이* ADR 에서 reject — 임베딩 모델 swap 번들; BM25 기여 분리 측정 위해 별도 ablation 으로 deferred
- **Weighted dense + BM25 fusion** — viable 하나 이종 score scale 에 가중치 둘 선택·방어 필요. RRF 가 그 튜닝 표면 완전 제거; RRF 가 너무 coarse 증명되면 follow-up RRF-k sweep 이 가중치 재튜닝보다 저렴
- **기존 Jaccard lexical scorer 를 BM25 로 교체** — Reject: `naive_baseline` 동작 silent 변경(ADR 0001 위반) + BM25 효과를 preserved-baseline 계약과 분리 불가
- **SPLADE / ColBERT late interaction** — 범위 외; hybrid_bm25 가 여전히 측정 가능한 real-data 갭 남기면 재고
