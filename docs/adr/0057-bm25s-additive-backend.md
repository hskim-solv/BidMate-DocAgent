# 0057: BM25 backend을 `bm25s`로 추가 분석 변형

- **Status**: accepted
- **Date**: 2026-05-18
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (naive_baseline 불변식), [ADR 0010](./0010-hybrid-bm25-dense-retrieval-rrf.md) (하이브리드 BM25 기준선), [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) / [ADR 0013](./0013-observability-as-additive-pluggable-surface.md) / [ADR 0023](./0023-hyde-query-expansion-ablation.md) / [ADR 0031](./0031-bm25-korean-morphology-additive.md) (재사용되는 additive opt-in 백엔드 패턴), [issue #988](https://github.com/hskim-solv/BidMate-DocAgent/issues/988), context7 audit sweep 2026-05-18 (`~/.claude/plans/context7-fizzy-glade.md`)

## Context

context7 audit Tier 2 finding — 현재 `rag_retrieval.py:80` 가 `rank_bm25.BM25Okapi` (pure Python BM25) 를 lazy-import 한다. `bm25s` 는 numpy sparse matrix 기반 BM25 구현으로 큰 corpus (1000+ docs) 에서 100-500x 빠르고, method 다양성 (`robertson` / `lucene` / `atire` / `bm25+` / `bm25l`) + IDF mixing + `idf_method` 옵션을 제공한다.

100-doc 도메인에선 latency 차이가 sub-ms 수준이라 즉각적 가치는 작다. 그러나 향후 scale-out (1000+ docs 또는 다른 corpus 추가) 시 의미가 있고, modern API ergonomics (`bm25s.BM25(...).index(corpus).retrieve(query, k=N)`) 가 사용자 코드를 단순화한다. 더 중요한 가치는 **opt-in additive pattern 강화** — ADR 0011 (LLM synthesis), ADR 0023 (HyDE), ADR 0031 (kiwi tokenizer) 모두 같은 패턴 (default 미변경, opt-in 만 추가) 을 따른다.

사전 검증 (2026-05-18, `~/.claude/plans/context7-fizzy-glade.md` A8 sub-plan §사전 검증) 에서 `bm25s.BM25(method="robertson", k1=1.5, b=0.75)` 가 `rank_bm25.BM25Okapi` 와 **동일 corpus 토큰에 대해 ranking 100% 일치** 함을 확인했다 (한국어 RFP-ish corpus, multi-hit / single-term / IDF-effect / OOV 4 query). 절대 점수는 IDF 처리 차이로 다르지만, RRF fusion 은 ordering 만 사용하므로 fusion 후 결과는 bit-equal 이다. `lucene` (bm25s default), `atire` 는 마지막 두 위치 swap — 사용하지 않는다.

## Decision

[`rag_retrieval.py`](../../rag_retrieval.py) 에 **`bm25_backend: "okapi" | "bm25s"`** 파이프라인 config 키 추가. 네 프리셋 (`naive_baseline`, `agentic_full`, `agentic_full_llm`, `agent_react`) 모두 기본값 `"okapi"`. [`eval/config.yaml`](../../eval/config.yaml) 에 신규 분석 변형 행 `full_bm25s` 추가 (`bm25_backend: bm25s` + `retrieval_backend: hybrid`). [`requirements-bm25s.txt`](../../requirements-bm25s.txt) 신규 opt-in (`bm25s>=0.2,<1.0`); 기본 `requirements.txt` 에는 추가하지 않는다.

- `BIDMATE_BM25_BACKEND` env var (default `okapi`) 도 fallback 지원 — config 키가 우선, env 가 process-wide fallback.
- [`rag_retrieval._make_bm25_instance(corpus, backend)`](../../rag_retrieval.py) 신규 factory — `backend="okapi"` 시 `_BM25Okapi(corpus)`, `backend="bm25s"` 시 `_bm25s.BM25(method="robertson", k1=1.5, b=0.75).index(corpus)`.
- [`rag_retrieval.get_or_build_bm25`](../../rag_retrieval.py) cache key 가 `(profile, tokenizer)` → `(profile, tokenizer, backend, schema_version, chunk_count)`. okapi / bm25s 캐시 격리.
- [`rag_retrieval.bm25_scores_for_index`](../../rag_retrieval.py) 도 `backend` kwarg 받음. `bm25.get_scores(...)` 인터페이스가 두 backend 통일 (사전 검증).

### Never-raise vs typed-raise 계약

`bm25s` 경로는 **typed-raise** 다 (ADR 0031 의 kiwi `silently degrade` 와 다름):

- `_make_bm25_instance` 가 `_bm25s is None` 이면 `RuntimeError` raise + 설치 hint
- 이유: `bm25_backend="bm25s"` 는 명시적 opt-in 이므로 사용자가 의도해서 켠 것. silent fallback 은 측정 의도를 가린다 (`full_bm25s` 행이 `hybrid_bm25` 와 byte-equal 이 되어버려 lift 측정 불가능).
- 기본 `requirements.txt` 만 설치한 CI 에서 `full_bm25s` 행을 실행하면 build step 에서 실패하지만, **default `okapi` 경로는 영향 받지 않음** — `_bm25s is None` 이어도 `_BM25Okapi(corpus)` 는 정상 동작.

### 계약 보존

- **ADR 0001 (naive_baseline)**: 네 프리셋 모두 `bm25_backend: "okapi"` 보유. `naive_baseline` 골든 ([`tests/data/naive_baseline_top_k.json`](../../tests/data/naive_baseline_top_k.json), [`tests/test_naive_baseline_ranking_invariance.py`](../../tests/test_naive_baseline_ranking_invariance.py)) 이 bit-identical — `naive_baseline` 은 `retrieval_backend: dense` 라 BM25 호출 자체가 없다. 명시적 `"okapi"` 값은 BM25 를 silently bm25s 로 swap 하는 미래 변경으로부터 보호.
- **ADR 0010 (hybrid BM25)**: 기존 하이브리드 분석 변형 행 (`hybrid_bm25`, `hybrid_bm25_extra_stopwords`, `hybrid_bm25_k30_*` 등) 은 기본값으로 암묵적 `bm25_backend: "okapi"` → 기존 eval delta 수치 byte-equal.
- **ADR 0031 (kiwi tokenizer)**: `full_kiwi` 행은 `bm25_tokenizer: kiwi` + 기본 `bm25_backend: okapi`. 신규 `full_bm25s` 는 `bm25_tokenizer: regex` + `bm25_backend: bm25s`. 두 축 독립 — `full_bm25s_kiwi` 같은 조합 행은 본 ADR 범위 밖 (별도 ablation 필요 시 추가).
- **ADR 0003 (answer/citation 계약)**: 스키마 변경 없음. `bm25_backend` 키는 `eval_summary.json` 행 메타데이터에 노출되지만 `answer.claims` / `answer.citations` 는 변경 없음.

## Re-open 조건

additive opt-in 백엔드 (`bm25_backend: bm25s`) 추가 자체는 `accepted` — 구현·머지 완료 (PR #988), opt-in 으로 운영 중. 아래는 **default flip** (네 프리셋 기본값을 `okapi` → `bm25s` 로 변경) 만의 **deferred** 조건이다. 이 ADR 이 re-open 되어 `bm25_backend` 기본값이 `bm25s` 로 flip 되는 조건은 다음 **세 가지 모두** 충족:

1. 메인테이너가 공개 fixture smoke eval surface (n=42) 또는 비공개 real eval (n=100) 에서 `bm25_backend: bm25s` + `bm25s` 설치 상태로 실측 — `eval_summary.json` 에 실제 `full_bm25s` 행 (build-fail 이 아닌) 생성.
2. `full_bm25s` 가 `hybrid_bm25` (자연스러운 control — 같은 `retrieval_backend: hybrid`, `bm25_backend` 만 차이) 대비 다음 중 **하나 이상** 충족:
   - `accuracy` OR `citation_precision` 에서 ≥ +3pp lift, 95% bootstrap CI 비중첩 (ADR 0026 / ADR 0031 임계값 일치)
   - `latency_p95` ≥ -30% 단축, AND `accuracy` / `citation_precision` 동급 이상
   - [`tests/test_bm25_backend_parity.py`](../../tests/test_bm25_backend_parity.py) 의 `top-N overlap ≥ 95%` 가 real corpus 에서도 유지 (작은 fixture 와 다를 수 있음)
3. 후속 ADR (`005x` 이상 번호) 이 열려 `bm25_backend` 기본값 flip — CI 설치 footprint 영향 (`bm25s` + numpy sparse 추가) 및 base `requirements.txt` 에 `bm25s` 추가할지 opt-in 유지할지 결정 문서화.

조건 1 충족 + 조건 2 미충족 시 (ADR 0019/0021/0031 이 임베딩/토크나이저에서 발견한 `0pp-on-hybrid` 패턴이 BM25 backend 에도 성립), 이 ADR 은 `accepted` 상태 유지 (default flip 만 deferred) 하고 공개 fixture smoke eval surface 에 측정 부록만 추가 — 측정 폐루프 작동.

## Measurement

### 2026-05-22 — retrieval-channel A/B (top-N overlap, real-100)

[PR #1303](https://github.com/hskim-solv/BidMate-DocAgent/pull/1303) (issue #1299) 이 `bm25_backend` 를 `make_plan` → plan dict → `retrieve_candidates` 로 threading 하기 전까지 `full_bm25s` 행은 plan 에 backend 키가 도달하지 않아 silently okapi 로 fallback 했다 (`bm25s` 라벨이지만 실제 okapi 측정). #1303 머지 + `requirements-bm25s.txt` 설치 후, 비공개 real-100 corpus 에서 Re-open 조건 (1)+(2)-③ 을 실측했다.

**방법** — backend 변수만 격리한 retrieval-channel A/B. [`rag_retrieval.bm25_scores_for_index`](../../rag_retrieval.py) (파이프라인의 BM25 채널 그대로) 를 `backend="okapi"` / `backend="bm25s"` 두 번 호출, 동일 query tokens (regex tokenizer, `shared` stopword profile) 로 top-N chunk 집합 overlap 을 측정. corpus = real-100 인덱스 (26376 chunks, `hashing` 임베딩 빌드), queries = `eval/real_config.local.yaml` 의 221 케이스 질의. 풀 agentic 파이프라인 (planner / verifier / answer / rerank) 은 backend 와 무관하므로 우회 — 같은 run 안 inter-backend 비교. aggregate-only (ADR 0005; per-case chunk 텍스트 미노출).

| top-k | mean overlap | median | min | overlap≥0.95 비율 | exact 순서 일치 |
|------:|-------------:|-------:|----:|-----------------:|----------------:|
| 10    | 0.9819       | 1.00   | 0.60 | 91.4%           | 89.6%           |
| 30    | 0.9836       | 1.00   | 0.70 | 91.0%           | 88.2%           |
| 50    | 0.9854       | 1.00   | 0.62 | 90.5%           | 88.2%           |

(n=221, empty-token 질의 0건, `bm25s.BM25(method="robertson", k1=1.5, b=0.75)`)

**판정**

- **조건 (1) 충족** — real n=221, `bm25s` 설치 상태에서 실제 `bm25s` 스코어링 실행. divergence 존재 (exact 순서 일치 88–90%, min overlap 0.60) 자체가 okapi silent fallback 이 **아님**을 증명한다 (fallback 이었다면 overlap 이 전부 1.0). #1303 plumbing + backend dispatch 가 진짜로 `bm25s` 경로를 행사.
- **조건 (2)-③ 은 aggregate 로만 유지** — mean overlap 98.2–98.5% ≥ 0.95 이나, toy fixture 의 100% ranking parity 는 real corpus 에서 약화된다 (약 9–10% 질의가 overlap < 0.95, top-k 순서 완전 일치 ~88–90%). [`tests/test_bm25_backend_parity.py`](../../tests/test_bm25_backend_parity.py) 주석이 예고한 "larger fixtures or real corpora may erode this" 가 26376-chunk corpus 에서 실제 발생 — robertson vs okapi 의 IDF 분포 차이가 큰 corpus 의 tie-breaking 을 일부 바꾼다. 이 overlap 은 swap 의 **안전성** 신호이지 **개선** 신호가 아니다.
- **조건 (2)-①② 는 별도 측정하지 않음** — rankings 가 거의 동일 (mean 98%+) 한 데다 RRF fusion + rerank 가 다운스트림을 추가로 평탄화하므로 `accuracy` / `citation_precision` 의 ≥ +3pp lift 가능성은 희박하다. 100-doc 도메인 latency 차는 sub-ms (`bm25s` 의 100–500x 이득은 1000+ docs 에서만 발현). end-to-end accuracy delta 의 풀 파이프라인 측정은 parity 가 이미 높아 ROI 가 낮아 deferred.

**결정** — 조건 (1) 충족 + 조건 (2) 실질 미충족 (parity 는 안전성 신호일 뿐 lift 아님; ADR 0019/0021/0031 의 `0pp-on-hybrid` 패턴이 BM25 backend 에도 성립). 위 "Re-open 조건" 의 line — *조건 1 충족 + 조건 2 미충족 시 측정 부록만 추가* — 경로를 따라 **`bm25_backend` 기본값 flip 보류**, `bm25s` 는 opt-in additive 백엔드로 유지. 후속 ADR (조건 3) 은 열지 않는다. 측정 폐루프 작동.

### 2026-05-22 — 풀 파이프라인 end-to-end 측정 (비공개 real-100, n=221)

2026-05-22 의 retrieval-channel A/B (위 항목) 는 top-N overlap 만 측정하고 end-to-end accuracy / citation_precision / latency delta 는 deferred 였다. 이번에 그 deferred 분을 실측하여 re-open 조건 (1) + (2)-①② 충족 여부를 확정한다.

- **Surface**: 비공개 real-100 eval, n=221 cases (answerable 118 / abstention 103). subset 없이 전체 — full bootstrap 검정력 유지.
- **Index**: prebuilt `data/index/real100` (26376 chunks, `EMBEDDING_BACKEND=hashing` 오프라인 기본 경로). 재빌드 없이 prebuilt 재사용.
- **Control**: `full` (hybrid + okapi, metadata_first + rerank + verifier 풀 agentic 파이프라인). `full_bm25s` 와 **`bm25_backend` 만 차이** (둘 다 `retrieval_backend: hybrid`, `bm25_tokenizer: regex`) — 자연스러운 control. `bm25s` 0.3.9 설치 상태에서 `full_bm25s` 행이 build-fail 아닌 실제 행으로 생성됨 (**조건 (1) ✓**).

| metric | `full` (okapi) | `full_bm25s` | delta |
|---|---|---|---|
| accuracy | 0.1610  CI[0.0932, 0.2288] | 0.1610  CI[0.0932, 0.2288] | **+0.00 pp** (CI 완전 중첩) |
| citation_precision | 0.1045  CI[0.0593, 0.1582] | 0.1059  CI[0.0593, 0.1610] | **+0.14 pp** (CI 중첩) |
| latency_p95 | 4249.6 ms | 14500.8 ms | **+241%** (느려짐) |
| retrieve_ms (mean / p95) | 1168 / 2017 ms | 2627 / 7041 ms | +125% / +249% |

(accuracy / citation_precision CI 는 answerable n=118 기반.)

**판정**:

- **조건 (2)-① (≥ +3pp lift, 95% CI 비중첩): ✗ 미충족.** accuracy +0.00pp, citation_precision +0.14pp — 둘 다 임계값 3pp 미달이고 95% bootstrap CI 가 완전히 중첩한다.
- **조건 (2)-② (latency_p95 ≥ -30% 단축): ✗ 미충족.** 단축은커녕 +241% 악화. 26376-chunk 스케일에서 `bm25s` sparse-matrix 경로의 per-query `retrieve_ms` 가 okapi 대비 mean 2.25배 / p95 3.5배 느리다 — ADR Context 의 "100-doc 도메인에선 latency 차이가 sub-ms, 향후 1000+ docs scale-out 시 의미" 예측과 정합 (현 스케일에선 고정 오버헤드가 우세).
- 조건 (2)-③ (top-N overlap ≥ 95% on real corpus) 은 2026-05-22 retrieval A/B (overlap mean 98.2%@10) 로 이미 충족이나, 이는 *parity* 신호이지 *lift* 가 아니므로 default flip 의 근거가 되지 못한다.

**결론**: re-open 조건 (1) 충족 + (2)-①② 미충족 → `bm25_backend` 기본값 flip **보류 유지**. ADR 0019 / 0021 / 0031 이 임베딩 / 토크나이저 축에서 발견한 `0pp-on-hybrid` 패턴 (RRF fusion + cross-encoder rerank 가 채널 ranking 차이를 평탄화) 이 BM25 backend 축에서도 성립함이 end-to-end 로 확정. 2026-05-22 retrieval-overlap 기반 0pp 예상과 일치. `bm25s` 는 `okapi` 와 동등 품질이되 현 스케일에선 더 느리므로 opt-in additive 변형으로 유지.

**Caveats**: single run (seed 미평균), `full` → `full_bm25s` 순차 실행 (동일 머신). latency 절대값은 머신 부하 노이즈를 포함한다 — backend 무관 축인 `query_analysis_ms` 도 412 → 813ms 로 변동 (run-order / load 변동 시사). 단 latency 방향성 (bm25s 가 -30% 개선의 정반대로 명백히 느림) 은 robust 하여 조건 (2)-② 판정은 결정적. 결과는 aggregate-only (ADR 0005 경계 — per-case text / doc id 미노출).

## Consequences

**이득**

- 향후 scale-out (1000+ docs) 시 latency 100-500x 개선 가능 표면 확보. 100-doc 도메인에선 측정 가치 작지만 backend abstraction 자체가 future-proof.
- eval 매트릭스 1행 증가; `full_bm25s` 의 `hybrid_bm25` 대비 delta 가 항상 가시화 (CI install 시).
- ADR 0001 불변식이 기본값 선택 (`"okapi"`) + 네 프리셋 명시로 보존. 추후 bm25s 제거는 `eval/config.yaml` 한 줄 삭제 + `requirements-bm25s.txt` 삭제로 가능; 스키마 bump 없음.
- 저장소 관용구에 네 번째 구체적 "default 키 기반 분석 변형" 사례 추가 (`query_expansion` ADR 0023, `bm25_stopword_profile` issue #150, `bm25_tokenizer` ADR 0031 에 이어) — 측정 게이팅을 가진 additive Protocol 백엔드 dispatch.

**비용**

- 사용자가 이해해야 할 파이프라인 config 키 1개 추가. 기본값 `"okapi"` (동작 변경 없음) + typed-raise 계약 (silent fallback 없음) 으로 완화.
- `requirements-bm25s.txt` 신규 — opt-in install layer 1개 추가 (m3/graph/lora/observability 패턴 inherits, 사용자 cognitive load minimal).
- `bm25s` 경로 활성화 시 추가 ~10MB 설치 footprint (`bm25s` + `numpy` (이미 base) + `scipy` (이미 base)). minimal 환경에서 opt-in 으로 격리.
- kiwipiepy / mecab / khaiii 토크나이저와 `bm25s` backend 조합 행 (`full_bm25s_kiwi` 등) 은 본 ADR 범위 밖. 필요 시 후속 추가 (eval row 1개 추가 비용).

**제약 (불변)**

- ADR 0001: `naive_baseline` 골든 bit-identical ([`tests/test_naive_baseline_ranking_invariance.py`](../../tests/test_naive_baseline_ranking_invariance.py) 검증).
- ADR 0003: answer / citation 계약 불변; `schema_version` bump 없음.
- ADR 0010: 기존 하이브리드 BM25 분석 변형 행 byte-equal — 신규 `full_bm25s` 행만 새 경로 행사.
- ADR 0031: `bm25_tokenizer` 와 `bm25_backend` 는 직교 축. `full_kiwi` 행은 `bm25_backend: okapi` (기본), `full_bm25s` 는 `bm25_tokenizer: regex` (기본).

## Alternatives considered

- **rank_bm25 를 bm25s 로 전면 교체.** 기각: ADR 0001 "기준선 보존" 불변식과 충돌. 모든 설치가 `bm25s` + scipy 의존성을 강제로 끌어와 minimal-footprint 배포 스토리도 깨진다. 추가 행 패턴이 ADR 0019/0026/0031 deferred-then-closed 루프와 정확히 일치 — 측정 후 default flip 결정.
- **`bm25s.BM25(method="lucene")` 사용 (bm25s default).** 사전 검증에서 ranking 이 `BM25Okapi` 와 마지막 두 위치 swap — `robertson` 만큼 안전하지 않다. ES (Elasticsearch) 와의 absolute score parity 가 필요하면 향후 별도 ADR 로 결정.
- **`bm25s.BM25(method="atire")`.** Academic IR 표준이지만 `lucene` 과 같은 ranking 차이. 사용 안 함.
- **`bm25_backend` 를 env var 만으로 제어 (config key 추가 안 함).** 같은 eval run 안에서 `okapi` (hybrid_bm25 행) + `bm25s` (full_bm25s 행) 동시 측정 불가능 — env 는 process 전역. 본 ADR 의 측정 표면 핵심이 같은 run 안 inter-row 비교라 config key 필수.
- **`requirements.txt` 에 `bm25s` 추가하고 default backend swap.** 기각: scale-out 효과 측정 전 default 변경은 기준선 위반. 측정 게이트 후 후속 ADR 에서 결정.

## Verification

[`tests/test_bm25_backend_parity.py`](../../tests/test_bm25_backend_parity.py) 가 세 contract 를 lock:

1. `VALID_BM25_BACKENDS == {"okapi", "bm25s"}` — narrowed 명시
2. 네 프리셋 모두 `bm25_backend: "okapi"` 명시 (ADR 0001 + 0057 invariant)
3. `bm25s.BM25(method="robertson")` 가 `rank_bm25.BM25Okapi` 와 ranking 100% 일치 + top-10 overlap ≥ 95%
4. `get_or_build_bm25` 캐시 격리 (okapi / bm25s 인스턴스 분리)

`bm25s` 미설치 환경에서는 `pytest.importorskip("bm25s")` 로 contract 3+4 가 skip — minimal CI 정상 동작. contract 1+2 는 항상 실행.

ADR 0057 의 Re-open 조건 (1)+(2) 충족은 `eval_summary.json::ablation.runs[name="full_bm25s"]` vs `name="hybrid_bm25"` 의 metric delta 비교로 추적 — `scripts/distinguishing_power.py` 가운지 floor 보다 lift 가 크면 후속 ADR 가 default flip 검토.

<!-- verifies-key: rag_pipeline_presets.py:VALID_BM25_BACKENDS -->
<!-- verifies-key: rag_pipeline_presets.py:bm25_backend -->
<!-- verifies-key: eval/config.yaml:full_bm25s -->
<!-- verifies-key: tests/test_bm25_backend_parity.py:test_all_presets_default_to_okapi -->
<!-- verifies-key: tests/test_bm25_backend_parity.py:test_bm25s_robertson_ranking_matches_okapi -->

## See also

- [`rag_retrieval._make_bm25_instance`](../../rag_retrieval.py) — backend factory.
- [`rag_retrieval.get_or_build_bm25`](../../rag_retrieval.py) — cache + dispatch.
- [`rag_pipeline_presets.VALID_BM25_BACKENDS`](../../rag_pipeline_presets.py) — validator surface.
- [`requirements-bm25s.txt`](../../requirements-bm25s.txt) — opt-in install layer.
- [`eval/config.yaml`](../../eval/config.yaml) `full_bm25s` — 분석 변형 행.
- ADR 0019 → ADR 0021 / ADR 0031 — 이 ADR 이 따르는 측정 기반 deferral 패턴.
- context7 audit sweep 2026-05-18 (`~/.claude/plans/context7-fizzy-glade.md` § A8 Sub-Plan).
- Issue [#988](https://github.com/hskim-solv/BidMate-DocAgent/issues/988).
