# 0009: 별도 스크립트로 외부 기준선 비교

(원래 [#155](https://github.com/hskim-solv/BidMate-DocAgent/pull/155) 와 함께 ADR 0008 로 작성, [#144](https://github.com/hskim-solv/BidMate-DocAgent/pull/144) 의 동시 evidence-boundary ADR 와 충돌 회피 위해 0009 로 renumber — [docs/adr/README.md](./README.md) 의 "numbers are never reused" rule.)

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) 확장; [ADR 0006](./0006-llm-judge-on-real-data-only.md) 백엔드 패턴 재사용
- **Deciders**: hskim

## TL;DR

- 외부 기준선(LangChain·LlamaIndex) 비교를 별도 스크립트 + 별도 리포트로 분리.
- `eval/config.yaml` ablation 에 추가 안 함 — 의존성·비용·메트릭 비대칭이 부적합.
- 대칭 가능 메트릭만 비교 표, 비대칭은 `null` 로 명시(공백 아님).

## 배경

[ADR 0001](./0001-preserve-naive-baseline.md) 가 *내부* 컨트롤로 `naive_baseline` 보존 — 모든 분석 변형이 "추가 기제 값 하나?" 비교 내장. [README Limitations](../../README.md) 가 명시 갭 flag: *외부* 프레임워크 대비 비교 없음. *"왜 LangChain `RetrievalQA` 또는 LlamaIndex `QueryEngine` 안 쓰고 커스텀?"* reviewer 질문에 `Why extractive, not generative?` 의 prose 답변만 있고 측정 없음.

LangChain/LlamaIndex 를 `eval/config.yaml` 의 추가 분석 변형으로 넣는 건 잘못된 shape:

1. **다른 의존성 프로필.** `langchain`·`langchain-community`·`faiss-cpu`·`llama-index`·`sentence-transformers` 가 100–300 MB 전이 의존 — 나머지 프로젝트 불필요. `requirements.txt` 추가가 기여자·CI job 모두 과세
2. **다른 비용 프로필.** 충실한 LangChain 비교는 LLM(Anthropic/OpenAI) 필요. ADR 0004 / ADR 0006 에 따라 공개 CI 경로는 deterministic + free 유지; paid API 묶이면 invariant 깨짐
3. **비대칭 메트릭 커버리지.** LangChain `RetrievalQA` 는 `result`(free-text) + `source_documents` 반환. 우리 구조화 `claims[].citations[].chunk_id` shape(ADR 0003) emit 안 함. 우리 메트릭 일부(`citation_precision`·`citation_region_precision`·`claim_citation_alignment`·`answer_format_compliance`)는 외부 시스템이 underlying 신호 생성 안 할 때 defensible 의미 없음

올바른 shape: **별도 orchestration 스크립트** + 양 시스템이 fair 경쟁 가능한 메트릭만 커버하는 작은 parallel 리포트.

## 결정

외부 기준선은 `scripts/compare_external_baselines.py` 에 위치, `reports/external_baselines.json` 에 기록. `eval/config.yaml` 의 `ablation_runs` **아님**, `make smoke` / `pr-eval.yml` / `make eval` 의 일부 **아님**.

### 대칭 메트릭 subset

시스템 간 fair 정의 메트릭만 비교 표에 보고:

| 메트릭 | 우리 파이프라인 | LangChain RetrievalQA | LlamaIndex QueryEngine |
|---|---|---|---|
| `accuracy` (term 매치 + doc 매치) | ✓ | ✓ | ✓ |
| `retrieval_recall@k` (expected_doc_ids ⊆ retrieved) | ✓ | ✓ | ✓ |
| `latency_ms` (쿼리당 wall-clock) | ✓ | ✓ | ✓ |
| `citation_precision` (chunk-level) | ✓ | ✗ (no chunk_id contract) | ✗ |
| `claim_citation_alignment` | ✓ | ✗ | ✗ |
| `abstention_accuracy` | ✓ (first-class status) | ✗ (free-text "I don't know" only) | ✗ |
| `answer_format_compliance` | ✓ (ADR 0003 JSON) | ✗ | ✗ |

비대칭 컬럼은 외부 컬럼에 `null` 로 기록(생략 아님) — 향후 reader 가 외부 시스템이 *어떤* 차원을 address 안 하는지 확인 가능. 이 자체가 "왜 커스텀?" 질문의 답이다.

### 백엔드 pluggability

ADR 0006 패턴 재사용, `BIDMATE_EXTERNAL_BACKEND` 선택:

* `stub` (default) — deterministic fixture. `expected_terms` 파생 템플릿 응답으로 API shape(free-text + source_documents) 모방. 네트워크 없음. 테스트 + API key 없는 기여자용. stub 은 *경쟁 주장 안 함* — CI 에서 plumbing 검증용
* `langchain` — `langchain.chains.RetrievalQA` + `HuggingFaceEmbeddings`(우리 default 임베딩 매치) + FAISS + `ChatAnthropic`(Claude). `pip install langchain langchain-community langchain-anthropic faiss-cpu sentence-transformers` + `ANTHROPIC_API_KEY` 필요
* `llamaindex` — `llama_index.core.query_engine.RetrieverQueryEngine` + 동일 임베딩 + LLM. 동일 install footprint

### Cadence

수동. retrieval/답변 생성 중대 변경 PR 작성자가 외부 비교를 로컬 재실행:

```bash
BIDMATE_EXTERNAL_BACKEND=langchain ANTHROPIC_API_KEY=... \\
  python3 scripts/compare_external_baselines.py
```

relative 비교가 중대 shift 시 결과 aggregate(`reports/external_baselines.json`)를 PR 첨부. CI 자체는 live 백엔드 호출 절대 X.

### Commit 경계

`reports/external_baselines.json` 은 aggregate 레벨에서 **committable**(메트릭당 mean ± CI, n 케이스, 백엔드, 모델). 케이스별 외부 답변은 privacy/licensing 미audit LLM 생성 텍스트 포함; git-ignored `reports/external_baselines.local.json` 에 위치 — real-data 표면용 ADR 0005 split 미러.

## 결과

**Wins**

- "왜 LangChain 안 써?" 질문이 양 시스템이 address 하는 메트릭에서 측정 가능한 답 확보
- ADR 0001 invariant 유지: `naive_baseline` + `agentic_full` / `agentic_full_llm` 은 내부 컨트롤
- 공개 CI 는 deterministic·free·offline 유지(ADR 0004 / ADR 0006). 외부 백엔드는 opt-in side road
- 백엔드 추상화는 ADR 0006(`BIDMATE_JUDGE_BACKEND`) + ADR 0011(`BIDMATE_SYNTHESIS_BACKEND`)이 이미 확립한 동일 idiom — reader 1회 학습

**Costs**

- 비교가 **설계상 비대칭**. 캐주얼 reader 가 N/A 컬럼을 외부 시스템 약점으로 오독 가능; README 내러티브가 비대칭을 feature 표면 결정으로 framing 필요, 버그 아님
- 유지할 추가 스크립트 2개(`langchain`/`llamaindex` 백엔드 각각 upstream API churn 자체 보유). 각 백엔드 < 50 라인이라 bus factor 비용은 작지만 non-zero
- `reports/external_baselines.json` 의 pre-computed 샘플 비교는 refresh 안 하면 stale. `reports/real100/` 의 동일 cadence 컨벤션이 완화

**Constraint (불변)**

- ADR 0001 — `naive_baseline` 은 `pipeline_cli_choices()` 유지
- ADR 0003 — 답변 schema 손대지 않음
- ADR 0004 — 공개 CI 는 외부 LLM endpoint 호출 X
- ADR 0005 — 케이스별 LLM 생성 텍스트는 local 유지

## 검토한 대안

- **LangChain/LlamaIndex 를 `eval/config.yaml` 분석 변형 run 으로 추가.** Context 섹션 세 이유(의존성·비용·비대칭 메트릭)로 reject
- **accuracy 만 비교.** Reject: accuracy 단독은 RFP 시스템에서 divergence 가 실제 중요한 citation/abstention/format 차원 은닉, n=42 의 accuracy CI([`eval/bootstrap.py`](../../eval/bootstrap.py))는 단독 기준으로 쓰기엔 너무 넓음
- **외부 비교 완전 스킵, prose 의존.** Reject: 외부 시스템에 대한 prose 주장은 정확히 프로젝트가 회피하려는 unmeasured 단언. ADR 0001 의 내부 기준선 방어가 재귀 적용 — agentic 파이프라인이 naive 대비 측정 가치 있다면 가장 인기 외부 프레임워크 대비도 측정 가치

## 첫 실행 결과

**Stub 백엔드 (committed, 2026-05-11)**

`python3 scripts/compare_external_baselines.py` 를 default `BIDMATE_EXTERNAL_BACKEND=stub` 으로 공개 synthetic n=42 표면에 실행, aggregate 를 `reports/external_baselines.json` 에 commit:

| metric | stub result | note |
|---|---|---|
| `accuracy` | 1.000 (CI: [1.000, 1.000]) | stub 가 완벽한 템플릿 답변 반환 — 품질 주장 아님 |
| `retrieval_recall@k` | 1.000 (CI: [1.000, 1.000], n=32) | stub 가 모든 expected doc 검색 |
| `latency_ms` (p50/p95) | 0 ms / 0 ms | 실제 retrieval 없음 |
| `citation_precision` | null | 비대칭 메트릭 — 외부 시스템이 chunk_id 미생성 |
| `claim_citation_alignment` | null | 비대칭 메트릭 |
| `abstention_accuracy` | null | 비대칭 메트릭 |
| `answer_format_compliance` | null | 비대칭 메트릭 |

stub run 이 plumbing end-to-end 입증: `compare_external_baselines.py` 가 `eval/dev_queries_v1_summary.md` 에서 케이스 로드, stub 백엔드 실행, bootstrap CI aggregate, committable aggregate shape 작성. `tests/test_external_baselines.py` 가 CI 에서 이 경로 커버.

**실제 LangChain 백엔드 (deferred)**

`BIDMATE_EXTERNAL_BACKEND=langchain` 실행은 `langchain langchain-community langchain-anthropic faiss-cpu sentence-transformers` + `ANTHROPIC_API_KEY` 필요. ADR 0004 / ADR 0006 에 따라 공개 CI 는 deterministic + free 유지; 실제 백엔드 run 은 opt-in 로컬 operation. [issue #449](https://github.com/hskim-solv/BidMate-DocAgent/issues/449) 추적. 그 run 랜딩 시 `reports/external_baselines.json` 에 `"backend": "langchain"` row 갱신 + ADR 0025 재오픈 조건(`reports/external_baselines.json` 가 `backend != "stub"` 인 ≥1 항목, n ≥ 32) 충족.
