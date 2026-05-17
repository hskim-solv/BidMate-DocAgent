# 0031: BM25 한국어 형태소 토크나이저를 추가 분석 변형으로

- **Status**: Superseded
- **Superseded by**: [ADR 0010](./0010-hybrid-bm25-dense-retrieval-rrf.md) § "Korean morphology tokenizer layer"
- **Date**: 2026-05-13
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (naive_baseline 불변식), [ADR 0010](./0010-hybrid-bm25-dense-retrieval-rrf.md) (이 ADR이 얹는 하이브리드 BM25 기준선), [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) / [ADR 0013](./0013-observability-as-additive-pluggable-surface.md) (재사용되는 additive opt-in 백엔드 패턴), [ADR 0019](./0019-embedding-default-stays-minilm.md) / [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) / [ADR 0025](./0025-cost-frontier-defer-until-real-baselines.md) / [ADR 0026](./0026-cross-encoder-reranker-deferral.md) (측정 기반 deferral 패턴), issue #486, issue #150 (BM25_EXTRA 선례)

## TL;DR

- 외부 시니어 리뷰가 지적한 한국어 형태소 인식 BM25 부재를 추가 분석 변형으로 메운다 — `bm25_tokenizer: "regex" | "kiwi"` 키 도입, 기본값은 `regex`.
- `kiwipiepy` lazy-import + None fallback으로 wheel 미설치 환경에서도 절대 raise하지 않음. CI에서는 `full_kiwi` 행이 `hybrid_bm25`와 byte-equal.
- ADR 0001 baseline 불변식 및 ADR 0019/0021 측정 기반 deferral 패턴 그대로 유지. 측정으로 +3pp 입증되면 후속 ADR에서 기본값 flip.

## 배경

외부 시니어 리뷰(2026-05) §A3-S3가 한국어 형태소 인식 토크나이저 부재를 실제 검색 갭으로 정확히 짚었다. 현재 BM25 경로는 `re.compile(r"[A-Za-z0-9]+|[가-힣]+")` + 선택적 `bm25_extra` 프로파일(issue #150, 이미 추출된 토큰에서 조사 제거)을 사용한다. 두 방식 모두 "입찰참여시작일"을 한 토큰, "입찰 참여 시작일"을 세 토큰으로 보고 같은 개념임을 인지하지 못한다. 한국어 다토큰 명사구의 BM25 recall이 손해를 본다.

두 가지 후보:

- **`kiwipiepy`** — POS 태깅 형태소 분석기, pure-Python wheel, 모델 다운로드 불필요. 설치 footprint ~30MB. POS 필터(체언/용언/수식어/외래어)가 조사·어미·문장부호 같은 검색 노이즈 토큰을 정리한다.
- **`MeCab-ko` / `KoNLPy`** — 더 강력하지만 C 의존성과 플랫폼 의존성이 크다. 이 ADR 범위 밖 — `kiwipiepy`가 측정 우선 슬라이스.

ADR 0019/0021(임베딩 deferred-then-closed) 및 ADR 0026(cross-encoder reranker deferral) 패턴이 그대로 적용된다: surface를 추가 분석 변형으로 도입, 기본값은 regex 유지, 측정 게이트가 발동하면 후속 ADR로 기본값 flip.

## 결정

[`rag_pipeline_presets.py`](../../rag_pipeline_presets.py)에 **`bm25_tokenizer: "regex" | "kiwi"`** 파이프라인 config 키 추가.

- 세 프리셋(`naive_baseline`, `agentic_full`, `agentic_full_llm`) 모두 기본값 `"regex"`.
- [`eval/config.yaml`](../../eval/config.yaml)에 신규 분석 변형 행 `full_kiwi` 추가 (`bm25_tokenizer: kiwi` + `retrieval_backend: hybrid`).
- [`korean_lexicon.kiwi_tokens`](../../korean_lexicon.py) 신규 함수가 kiwipiepy로 형태소 토큰화하고 POS 필터링(`{NNG, NNP, NP, NR, VV, VA, VX, VCP, VCN, MM, MAG, MAJ, SL, SH, SN}`).
- [`rag_retrieval.get_or_build_bm25`](../../rag_retrieval.py)의 BM25 캐시 키가 `stopword_profile`에서 `(stopword_profile, tokenizer)`로 변경 — `(shared, kiwi)`와 `(shared, regex)` 캐시 분리.
- `tokenizer="kiwi"`일 때 쿼리 토큰도 kiwi로 처리해 corpus와 query가 동일한 형태소 surface 공유 (BM25 IDF 분포 정렬 필요).

### Never-raise 계약

kiwi 경로는 **strictly opt-in이며 silently degrade**된다:

- `korean_lexicon.kiwi_tokens`가 `kiwipiepy`를 lazy-import. import 실패 시 `None` 반환.
- `rag_retrieval._chunk_tokens_for_bm25`가 `None` 반환 시 regex 토큰 경로로 fallback — control 행과 bit-identical.
- `rag_retrieval.bm25_scores_for_index`도 쿼리 측에서 동일 처리.

결과: kiwipiepy 없는 CI/환경에서 `full_kiwi`는 `hybrid_bm25`와 `eval_summary.json` 상 byte-equal. 행은 plumbing만 행사하며 wheel 미설치 시 공개 CI surface에서는 LLM 컬럼이 품질 주장이 되지 않는다.

### 계약 보존

- **ADR 0001 (naive_baseline)**: 세 프리셋 모두 `bm25_tokenizer: "regex"` 보유. `naive_baseline` 골든([`tests/data/naive_baseline_top_k.json`](../../tests/data/naive_baseline_top_k.json), [`tests/test_naive_baseline_ranking_invariance.py`](../../tests/test_naive_baseline_ranking_invariance.py))이 bit-identical — `naive_baseline`은 `retrieval_backend: dense`라 BM25 호출 자체가 없다. 명시적 `"regex"` 값은 BM25를 silently 활성화하는 미래 변경으로부터 보호.
- **ADR 0010 (hybrid BM25)**: 기존 하이브리드 분석 변형 행(`hybrid_bm25`, `hybrid_bm25_extra_stopwords`, `hybrid_bm25_k30_*` 등)은 기본값으로 암묵적 `bm25_tokenizer: "regex"` → 기존 eval delta 수치 byte-equal.
- **ADR 0003 (answer/citation 계약)**: 스키마 변경 없음. `bm25_tokenizer` 키는 `eval_summary.json` 행 메타데이터에 노출되지만 `answer.claims` / `answer.citations`는 변경 없음.
- **ADR 0023 (HyDE)** / **ADR 0026 (cross-encoder reranker)**: 직교. `bm25_tokenizer`는 `query_expansion` 및 `rerank_cross_encoder`와 독립.

## Re-open 조건

이 ADR이 re-open되어 `bm25_tokenizer` 기본값이 `kiwi`로 flip되는 조건은 다음 **세 가지 모두** 충족:

1. 메인테이너가 공개 합성 eval surface(n=42)에서 `bm25_tokenizer: kiwi` + `kiwipiepy` 설치 상태로 실측 — `eval_summary.json`에 실제 `full_kiwi` 행 (fallback byte-equal이 아님) 생성.
2. `full_kiwi`가 `hybrid_bm25`(자연스러운 control — 같은 `retrieval_backend: hybrid`, `bm25_tokenizer`만 차이) 대비 `accuracy` OR `citation_precision`에서 **≥ +3pp** lift, 95% bootstrap CI 비중첩. +3pp 임계값은 ADR 0026의 reranker 게이트와 일치 (precision 타깃 post/pre-retrieval 변경에는 더 작은 절대 lift 허용).
3. 후속 ADR(`003x` 이상 번호)이 열려 `bm25_tokenizer` 기본값 flip — CI 설치 footprint 영향(~30MB 추가) 및 `kiwipiepy`를 hard CI 의존성으로 만들지 silent fallback 유지할지 결정 문서화.

조건 1 충족 + 조건 2 미충족 시 (ADR 0019/0021이 임베딩에서 발견한 `0pp-on-hybrid` 패턴이 BM25 토크나이저에도 성립), 이 ADR은 `accepted` 상태 유지하고 공개 합성 eval surface에 측정 부록만 추가 — ADR 0019 → 0021 동일 루프.

## 결과

**이득**

- 외부 리뷰가 짚은 한국어 형태소 인식 BM25 분석 변형 셀 확보. eval 매트릭스 1행 증가; `full_kiwi`의 `hybrid_bm25` 대비 delta가 항상 가시화 (CI fallback 하에서는 실증적 0).
- ADR 0001 불변식이 기본값 선택(`"regex"`) + never-raise fallback으로 보존. 추후 kiwi 제거는 `eval/config.yaml` 한 줄 삭제로 가능; 스키마 bump 없음.
- 저장소 관용구에 세 번째 구체적 "default 키 기반 분석 변형" 사례 추가 (`query_expansion` ADR 0023, `bm25_stopword_profile` issue #150에 이어) — 측정 게이팅을 가진 additive Protocol 백엔드 dispatch.

**비용**

- 사용자가 이해해야 할 파이프라인 config 키 1개 추가. 기본값 `"regex"`(동작 변경 없음)와 never-raise 계약으로 완화.
- `requirements.txt`에 `kiwipiepy>=0.17` 추가 — ~30MB, 주요 플랫폼 pure-Python wheel. lazy-import + None-fallback으로 의존성 미설치 시(예: minimal Docker layer)도 런타임 robust.
- 쿼리 측 kiwi 토큰화는 regex 토큰을 re-join 후 다시 토큰화 — 근사적이지만 corpus 측과 일치 (corpus chunk는 raw text에서 kiwi 토큰화, query 토큰은 regex 토큰 리스트에서 kiwi 토큰화). 엄밀한 대안은 원본 쿼리 문자열을 `bm25_scores_for_index`에 전달하는 것 — 리팩토링 deferred; 현재 surface는 측정에 충분.

**제약 (불변)**

- ADR 0001: `naive_baseline` 골든 bit-identical (`tests/test_naive_baseline_ranking_invariance.py` 검증).
- ADR 0003: answer / citation 계약 불변; `schema_version` bump 없음.
- ADR 0010: 기존 하이브리드 BM25 분석 변형 행 byte-equal — 신규 `full_kiwi` 행만 kiwi 경로 행사.

## 검토한 대안

- **regex 토크나이저를 kiwi로 전면 교체.** 기각: ADR 0001 "기준선 보존" 불변식과 충돌. 모든 설치가 30MB 의존성을 강제로 끌어와 minimal-footprint 배포 스토리도 깨진다. 추가 행 패턴이 ADR 0019/0026 deferred-then-closed 루프와 정확히 일치.
- **kiwi를 stopword 프로파일로 (`bm25_stopword_profile: "kiwi"`).** 기각: 기존 stopword 프로파일은 토크나이저(regex)를 공유하고 후처리만 다르다. 토크나이저 축을 stopword 축과 한 knob에 합치면 2차원 의미를 단일 문자열에 강제 — 캐시 키 명확성을 해치고, `bm25_tokenizer: kiwi`와 `bm25_stopword_profile: bm25_extra` 조합을 원하는 미래 ADR이 놀란다.
- **kiwipiepy 대신 MeCab-ko / KoNLPy.** 범위 밖 — 더 큰 설치(C 의존성, 시스템 라이브러리, 플랫폼 의존성). 측정이 정당화하면 후속 ADR이 같은 `bm25_tokenizer` 키(예: `"mecab"`)로 백엔드 교체 가능. Protocol surface 유지.
- **`index.json`에 kiwi corpus를 빌드 시점에 굽기.** 기각: 두 프로파일 모두 필요 시 인덱스 크기 2배 (그리고 `(profile, tokenizer)`별 캐시는 이미 lazy + process-local). 현재 build → cache 루프는 첫 eval 행 사용 시 발생; 비용은 분할 상환.
- **형태소 대신 자모 n-gram.** 검토했으나 미채택 — 다른 surface(문자 n-gram)는 별도 분석 변형 행 필요; 이 ADR이 다루는 형태소 토크나이저 선택과 독립.

## See also

- [`korean_lexicon.kiwi_tokens`](../../korean_lexicon.py) — 형태소 토큰화 구현 + POS 필터.
- [`rag_pipeline_presets.VALID_BM25_TOKENIZERS`](../../rag_pipeline_presets.py) — validator surface.
- [`rag_retrieval._chunk_tokens_for_bm25`](../../rag_retrieval.py) + `get_or_build_bm25` + `bm25_scores_for_index` — dispatch 지점.
- [`eval/config.yaml`](../../eval/config.yaml) — `full_kiwi` 분석 변형 행.
- ADR 0019 → ADR 0021 — 이 ADR이 따르는 측정 기반 deferral 패턴.
- Issue [#486](https://github.com/hskim-solv/BidMate-DocAgent/issues/486).
