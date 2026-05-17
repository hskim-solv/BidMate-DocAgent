# 0023: HyDE 쿼리 확장은 additive 분석 변형

- **Status**: proposed
- **Date**: 2026-05-12
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) 확장; [ADR 0003](./0003-structured-answer-citation-contract.md) 보존; [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) / [ADR 0020](./0020-protocol-based-pluggability.md) backend 패턴 재사용; [#342](https://github.com/hskim-solv/BidMate-DocAgent/pull/342) + [#358](https://github.com/hskim-solv/BidMate-DocAgent/pull/358) retrieval refactor 후속
- **Deciders**: hskim

## TL;DR

- [`rag_retrieval.retrieve_candidates`](../../rag_retrieval.py)는 raw 한국어 쿼리를 임베딩 → 격식 `합니다`-체 RFP passage와 대조; 도메인 어휘 갭으로 top-K miss 빈발.
- HyDE를 별도 `QueryExpander` Protocol(`Reranker`와 sibling)로 **additive 분석 변형** 추가 — 기본 `IdentityExpander`로 ADR 0001 invariant 보존.
- 신규 `full_hyde` 평가 행 + `BIDMATE_QUERY_EXPANSION_BACKEND` env. 공공 CI에서 never-raise fallback으로 `full`과 byte-equal 유지.

## 배경

[`rag_retrieval.retrieve_candidates`](../../rag_retrieval.py)는 raw 사용자 쿼리를 임베딩 → fusion / rerank 전 dense cosine + lexical Jaccard + metadata + (선택) BM25로 chunk 점수화. dense 임베딩은 짧은 구어체 한국어 쿼리 1개를 격식 `합니다`-체 RFP passage와 대조 — [Gao et al. 2022 HyDE](https://arxiv.org/abs/2212.10496)가 TREC에서 동기로 삼은 어휘 갭 그 자체. 공공 합성 set 실패 분석 trace에서 gold chunk가 쿼리에 없는 도메인 행정 어휘를 쓰는 top-K miss 반복 관찰.

PR #342가 `retrieve()`를 `retrieve_candidates` + `apply_fusion_and_reranking`으로 분리, PR #358이 `Reranker` Protocol 도입한 뒤 dense-embedding 호출 site는 한 줄(현 [`rag_retrieval.retrieve_candidates`](../../rag_retrieval.py); PR-H1b / issue #461로 `rag_core.py:L1780`에서 추출) — pre-retrieval 쿼리 rewrite stage의 깔끔한 seam. 문제는 HyDE 도입 *가부*가 아니라:

1. bit-identical `naive_baseline` golden(`tests/data/naive_baseline_top_k.json`, ADR 0001 invariant) 변동 없이,
2. HyDE를 `Reranker` Protocol과 결합하지 않고(다른 stage / 다른 I/O shape),
3. upstream `analysis`(raw 쿼리 아님)에서 오는 BM25 / lexical / metadata 점수화가 쿼리 확장 하에서도 invariant 유지

상태로 어떻게 추가할 것인가.

## 결정

HyDE 쿼리 확장은 **additive** 분석 변형 경로로 허용(교체 아님). ADR 0020의 `Reranker` Protocol과 병렬(분리) 전용 Protocol seam.

- 신규 모듈 [`rag_query_expansion.py`](../../rag_query_expansion.py):
  - `@runtime_checkable QueryExpander` Protocol — `expand(query: str, *, plan: dict) -> tuple[str, dict]` 단일 메서드.
  - `IdentityExpander`(default) — 쿼리 무변경 반환, meta `{"backend": "identity", "fell_back": False}`. 결정적, 네트워크/SDK 무관.
  - `HyDEExpander`(opt-in) — `anthropic` lazy-import, `claude-haiku-4-5-20251001`로 2-3 문장 가상 RFP-style 답변 생성, passage 반환. **Never-raise**: backend 실패(SDK 부재, key 부재, API error, empty response) 시 `(query, meta_with_fell_back=True)` 반환. retrieval orchestration으로 예외 escape 없음.
  - `default_expander(plan)` factory — `plan["query_expansion"]`(`"identity"` | `"hyde"`, case-insensitive) 디스패치; 미지값은 silently identity fallthrough.
- [`rag_pipeline_presets.py`](../../rag_pipeline_presets.py) `PIPELINE_CONFIG_KEYS`에 신규 `query_expansion` 키. `naive_baseline`, `agentic_full`, `agentic_full_llm` 모두 `query_expansion: "identity"` 운반 → 기존 eval row bit-equal.
- [`eval/config.yaml`](../../eval/config.yaml)에 신규 분석 변형 row `full_hyde`(`query_expansion: hyde`). 공공 CI(`ANTHROPIC_API_KEY` 부재) 하 never-raise fallback이 `full_hyde`를 `eval_summary.json`에서 `full`과 byte-equal로 유지. row는 operator가 key + `BIDMATE_QUERY_EXPANSION_BACKEND=hyde` 실행 시 의미.
- `rag_retrieval.retrieve_candidates`가 `default_expander(plan)` 1회 호출 → 반환 text를 `embed_query_for_index`에 전달 → `plan["query_expansion_meta"]` write. raw `query` 파라미터는 무변경; downstream BM25 / lexical / metadata 분기는 `analysis.tokens` 소비 → invariant.

### 보존 계약 (ADR 0001, ADR 0003)

- `naive_baseline`은 `query_expansion: "identity"` 유지. identity passthrough는 `query == query`(문자열 equality) 반환 → `embed_query_for_index(expanded, …)`가 PR 이전 `embed_query_for_index(query, …)`와 byte-identical. golden `tests/data/naive_baseline_top_k.json` 무변경 + `tests/test_naive_baseline_ranking_invariance.py`가 gate.
- ADR 0003 `schema_version: 2` 무변경. HyDE는 `claims` / `citations` / answer 필드를 보지 않음 — retrieval 점수화 이전에만 동작.

### Backend pluggability

ADR 0011 / ADR 0020 backend 패턴 재사용. `BIDMATE_QUERY_EXPANSION_BACKEND`:

- `identity`(default) — LLM/네트워크 무관. 미설정과 동일.
- `hyde` — Anthropic Claude API(Haiku 4.5 default; `BIDMATE_QUERY_EXPANSION_MODEL`로 override). `ANTHROPIC_API_KEY` 필요. single-shot prompt, temperature 0.0, system prompt `cache_control: ephemeral` 캐싱 → 반복 eval run에서 첫 호출 후 amortize.

### 주기

- **공공 합성 CI**: identity backend. `full_hyde` row가 `eval_summary.json`에 `full`과 byte-equal 등장(fallback이 golden stable 유지). plumbing 행사용; LLM 칼럼은 공공 표면 quality claim 아님.
- **Real-data eval**: `BIDMATE_QUERY_EXPANSION_BACKEND=hyde`. per-query 확장 passage는 로컬 잔류(ADR 0005); aggregate 메트릭 delta(recall@k, citation_precision, claim_alignment)는 ADR 0005 aggregate 경계 통과 commit.
- **Live demo**: 기본 identity. 향후 사용자 요청 시 hyde 토글은 본 ADR 범위 외.

## 결과

**Wins**

- retrieval 표면에 answer-side LLM synthesis(ADR 0011)와 mirror되는 query-side LLM rewrite 추가. eval matrix 1 칼럼 증가; `full_hyde` vs `full` delta가 항상 가시(CI fallback 하에서는 demonstrably zero).
- 기계적 additive: ADR 0001 invariant이 기본값(`"identity"`) + passthrough class로 보존(둘 다 testable). HyDE 제거는 후일 1줄 eval/config.yaml diff; schema bump 불필요.
- ADR 0020을 따르는 2번째 Protocol이 repo idiom으로서 Protocol-based pluggability를 강화(VectorStore #176 → Reranker #345 → QueryExpander #396).
- multi-query 분석 변형이 자연스러운 후속 — 동일 Protocol 하 2번째 `QueryExpander` 구현(예: `MultiQueryExpander`) 추가. 신규 Protocol 불필요.

**Costs**

- 사용자가 이해할 env 변수 family 1개 추가. 기본 `identity`(key/SDK/동작 변화 없음)로 완화. 변수 family는 `BIDMATE_SYNTHESIS_*` / `BIDMATE_RERANK_*`와 정확 mirror.
- hyde 칼럼 live-eval run당 토큰 비용. real-data 수동 주기 한정(~100 case × cached system prompt × Haiku pricing). Haiku list-price($1 / 1M input, $5 / 1M output) 기준 case당 marginal cost < $0.001 — ADR 0011 envelope 안.
- 유지할 Protocol 모듈 1개 추가. `IdentityExpander` 12줄 + `HyDEExpander` 대부분 prompt + never-raise wrapping — 표면 진정 작음.

**Constraints (불변)**

- ADR 0001: `naive_baseline`이 `query_expansion: "identity"` 운반 + golden invariance 테스트가 merge gate.
- ADR 0003: answer schema + `claims` / `citations` 무변경. `schema_version` bump 없음.
- ADR 0005: per-case 확장 passage 로컬 유지. aggregate delta는 기존 aggregate 경계 통과 commit.
- ADR 0020: 신규 Protocol은 `Reranker`의 sibling — 재사용 아님(아래 "검토한 대안" 참조).

## 검토한 대안

- **raw 쿼리를 HyDE로 전면 교체.** 기각: ADR 0001 보존 논거와 충돌. BM25 / lexical parity도 깨짐(토큰은 upstream `analysis`에서 옴 → 병렬 rewrite 필요). `retrieve_candidates` line 1780의 dense-only seam이 최소 표면 삽입점.
- **`Reranker` Protocol을 HyDE에 재사용.** 기각: `Reranker.rerank`는 `(query, list[chunk_dict])` → 재배치 chunk 반환; HyDE는 `query` → string 반환. signature + 파이프라인 stage 다름(post-retrieval reorder vs pre-retrieval rewrite). 단일 Protocol로 합치면 tagged-union return type 강제 + 파이프라인 shape 모호화. ADR 0020이 이미 single-responsibility Protocol을 idiom으로 천명 — 양쪽으로 cut.
- **named preset / 분석 변형 row 아닌 CLI flag로 HyDE 추가.** 기각: ADR 0001 / ADR 0011 "silent paths rot" 논거 적용. HyDE가 ship 가치 있다면 `full_hyde` row가 모든 eval invocation에 실행되어 `full` 대비 delta가 항상 가시(또는 fallback 하 provably zero on synthetic).
- **여러 가상 passage 생성 + 임베딩 fusion(multi-query HyDE).** 본 ADR 기각: 표면 더 큼(fusion 전략: average? max-pool? 검색 후보에 RRF?) + 기존 `apply_fusion_and_reranking` RRF와 상호작용하는 fusion knob. follow-up issue 추적; 동일 Protocol 하 `MultiQueryExpander` 구현 추가.
- **HyDE prompt를 한국 공공 RFP 어휘로만 pin.** 검토 후 미채택: prompt tuning은 real-eval delta로 loop informed 필요. 현 bilingual prompt는 격식 한국어 합니다-체 출력 요청 single-shot 기준선. 한국 RFP 장르 fine-tuning은 1 real-eval cycle 증거 확보 후 follow-up issue 추적.
