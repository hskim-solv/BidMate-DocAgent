# Senior-Positioning Narrative

이 문서는 채용 리뷰어 또는 면접관이 BidMate Agent를 보고 **"이 결과물이 시니어 엔지니어링 시그널을 얼마나 보여주는가?"** 를 빠르게 판단할 수 있도록 정리한 narrative다.

기존 reviewer 문서와의 역할 분담:

- [`portfolio-case-study.md`](./portfolio-case-study.md): 7가지 포트폴리오 질문에 대한 답 (왜/무엇을/어떻게)
- [`reviewer-evidence-pack.md`](./reviewer-evidence-pack.md): 5분 데모 흐름과 대표 질의·산출물 위치
- [`engineering-governance.md`](./engineering-governance.md): 코드/ADR/테스트/평가/리뷰 산출물이 서로 어떻게 강제되는가
- **이 문서**: 위 자료들을 어떤 **시니어 시그널**로 읽어야 하는지 — 인터뷰 답변 톤으로 정리

내용을 새로 만들지 않고 기존 자료를 어디서 어떻게 봐야 하는지 가리킨다.

## 시니어 시그널 한눈에 보기

| 시그널 | 어디서 확인하나 |
|---|---|
| 아키텍처 결정이 **사후 합리화가 아닌 기록된 결정**으로 남아있다 | [`docs/adr/`](./adr/README.md) — 30개 ADR (23 accepted / 7 proposed), status-tracked, supersession chains 명시 |
| **측정 가능한 성공 기준**을 미리 잡고 그 기준으로 평가한다 | [`portfolio-case-study.md` §2](./portfolio-case-study.md), [`eval/config.yaml`](../eval/config.yaml), README headline 표 |
| 합성 평가의 한계를 알고 **공개/비공개 평가 분리**로 보완한다 | [ADR 0005](./adr/0005-eval-split-public-synthetic-private-local.md), [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md) |
| **실패를 분류·우선순위화**한 뒤 백로그로 만든다 | [`docs/real-data-failure-taxonomy.md`](./real-data-failure-taxonomy.md), 메타 이슈 #49 |
| 회귀가 **다시 발생하지 않도록 테스트로 잠근다** | `tests/test_*_regression.py`, [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md)의 Real-data Decision Log |
| **거버넌스가 코드와 같이 진화**한다 (rule book → 규칙 → 자동화) | [`CLAUDE.md`](../CLAUDE.md), [`docs/engineering-governance.md`](./engineering-governance.md), `.github/workflows/` |
| **재현 가능한 시연**으로 주장 가능한 수치만 README에 올린다 | `make smoke`, `scripts/update_readme_metrics.py --check`, README "핵심 성능표" |

## 시니어 시그널 1 — 아키텍처 결정의 추적성

각 ADR은 **하나의 의사결정**을 다룬다. 19개를 빠르게 읽고 나면, 이 시스템에서 어떤 선택이 load-bearing인지와 supersession chain이 명확해진다.

| ADR | 상태 | 결정 | 시니어 관점에서 왜 중요한가 |
|---|---|---|---|
| [0001](./adr/0001-preserve-naive-baseline.md) | accepted | naive baseline을 ablation으로 보존 | 후속 retrieval 변경의 효과를 항상 baseline 대비로 측정 가능 |
| [0002](./adr/0002-metadata-first-retrieval.md) | accepted | metadata-first retrieval | 의미 유사도 단독의 함정(기관·문서 단위 제약 누락)을 회피한 trade-off |
| [0003](./adr/0003-structured-answer-citation-contract.md) | accepted | answer/citation 계약 (`schema_version: 2`) | 후속 변경이 silent contract drift를 만들 수 없게 잠금 |
| [0004](./adr/0004-verifier-retry-policy.md) | accepted | strict→relaxed verifier staging | latency 비용을 인정하면서 partial coverage를 잡는 명시적 정책 |
| [0005](./adr/0005-eval-split-public-synthetic-private-local.md) | accepted | 공개 합성 vs 비공개 로컬 평가 분리 | 외부 공개 제약과 일반화 한계를 인정하면서 reproducibility를 지키는 설계 |
| [0006](./adr/0006-llm-judge-on-real-data-only.md) | accepted | LLM-judge는 real-data 표면에서만 (refines 0004) | 공개본의 결정성과 실제 신호를 동시에 살리는 비대칭 결정 |
| [0007](./adr/0007-issue-linked-branch-naming.md) | accepted | issue-linked 브랜치 네이밍 (`<type>/issue-N`) | 추적성을 doc이 아니라 CI(`branch-and-issue-check.yml`)로 강제 |
| [0008](./adr/0008-evidence-boundary.md) | accepted | evidence boundary defense | prompt injection을 contract surface에서 차단 — 보안 의식의 명시화 |
| [0009](./adr/0009-external-baseline-comparison.md) | proposed | LangChain/LlamaIndex 외부 baseline 분리 비교 (extends 0001) | "왜 자체 구축?" 질문에 비대칭 metric(citation/grounding)으로 정량 답변 |
| [0010](./adr/0010-hybrid-bm25-dense-retrieval-rrf.md) | accepted | hybrid BM25 + dense + RRF | retrieval 보강은 *추가 ablation*으로만; 단일 backend로 결합 안 함 |
| [0011](./adr/0011-llm-synthesis-as-additive-ablation.md) | proposed | LLM 합성은 additive ablation (extends 0001, preserves 0003) | answer_text 렌더링만 LLM 교체; claims/citations/status는 결정적 verifier가 그대로 결정 |
| [0012](./adr/0012-llm-judge-on-public-synthetic.md) | accepted | LLM-judge on public synthetic, stub-default (refines 0006, reuses 0011) | judge backend는 결정적 stub으로 CI 통과; real backend는 운영자 옵트인 |
| [0013](./adr/0013-observability-as-additive-pluggable-surface.md) | accepted | observability를 additive·pluggable·fail-closed로 | trace backend(LangFuse/OTel) 장애가 query를 깨뜨리지 않음; LLM Ops 의식의 코드화 |
| [0014](./adr/0014-ragas-judge-additive-synthetic.md) | accepted | RAGAS judge as additive enrichment (extends 0012) | 외부 표준 메트릭으로 cross-validation; 결정적 stub-default 유지 |
| [0015](./adr/0015-cost-telemetry-additive.md) | accepted | cost telemetry as additive observability (extends 0011, 0013) | per-query `cost_estimate_usd` + `cache_read_tokens` 캡처 — LLM Ops 핵심 시그널을 계약 위반 없이 추가 |
| [0016](./adr/0016-judge-human-agreement.md) | proposed | Judge↔human agreement as calibration gate (refines 0006) | verifier-judge co-regression 차단 — 0006의 LLM-judge를 human spot-label과 Cohen's κ + Spearman ρ로 정합 검증, 두 자동평가가 같은 방향으로 잘못 가는 회귀를 게이트로 잡음 |
| [0017](./adr/0017-llm-metadata-extraction-additive.md) | proposed | LLM metadata extraction as additive backend (extends 0011) | metadata 추출도 LLM additive ablation으로 — 0011 backend 패턴 재사용, 결정적 추출기 baseline은 ADR 0002 metadata-first 경로에 그대로 보존 |
| [0018](./adr/0018-korean-public-rag-bench.md) | accepted | Korean public RAG bench (KorQuAD 2.1) as supplementary out-of-domain surface (extends 0005) | "한국어 일반 텍스트에서도 동작합니까?" 질문에 공개 재현 가능한 한 줄 명령(`make korean-public-eval`)으로 답변 — 합성 surface와 분리, CI 게이트가 *아님* |
| [0019](./adr/0019-embedding-default-stays-minilm.md) | accepted | embedding 디폴트 = MiniLM-L12-v2 잠금 + 재오픈 조건 명시 (extends 0002) | 2차 사이클 측정이 env mismatch로 deferred됐을 때 *deferral 자체*를 ADR로 잠금 — 다음 contributor가 같은 실험을 다시 시도하지 않고, "디폴트 교체"의 empirical bar(`full` 파이프라인 ≥+5pp)도 명시 |
| [0021](./adr/0021-bge-m3-completes-phase-1-3.md) | accepted | BGE-M3 Phase 1.3 측정 완료, ADR 0019 condition 2 closure (supplements 0019) | deferred 결정이 *실제로 닫히는 과정*까지 ADR로 박음. 4개 named candidate + 5개 임베딩(2019–2024) cross-architecture 측정으로 `0pp-on-full` 패턴이 empirical support 받는 단계까지 도달 |
| [0022](./adr/0022-langgraph-orchestration-stage-1.md) | accepted | LangGraph orchestrator path for agentic_full presets — stages 1+2 (passthrough → 3-node analyze / retrieve_loop / build_answer; `_phase_*` helpers shared with direct path; opt-in via `BIDMATE_ORCHESTRATOR=langgraph`) | "Agentic" 라벨에 코드 실체를 붙이는 epic. stage 1에서 dispatch + 단일-노드 passthrough로 JSON-identity 회귀를 잠근 뒤, stage 2가 `rag_core`에서 `_phase_analyze` / `_phase_retrieve_loop` / `_phase_build_answer`를 추출 — 직접 경로와 graph 경로가 *같은 phase 코드*를 호출하므로 JSON-identity는 by construction. multi-node 분해 + 조건부 edge(early return ⇒ END)가 LangSmith/Langfuse(ADR 0013)에서 per-stage trace로 인지됨. ADR 0001 `naive_baseline`은 직접 경로 유지. |
| [0023](./adr/0023-hyde-query-expansion-ablation.md) | proposed | HyDE query expansion as additive ablation (extends 0001, preserves 0003) | Reranker Protocol과 별도 Protocol seam — 쿼리↔문서 어휘 갭(공식체 RFP vs 일상 질의)을 LLM 가상답변 임베딩으로 메우는 ablation. `IdentityExpander` 디폴트로 ADR 0001 골든 비트동일 유지 |
| [0024](./adr/0024-agentic-full-llm-as-api-default.md) | accepted | API surface default preset = `agentic_full_llm`; backend default stays `stub` (complements 0011; CLI default stays `naive_baseline` per 0001) | "Agentic RAG" 라벨에 *기본 API surface*를 맞추는 절충안. preset만 flip하고 synthesis backend default(`stub`)는 유지 — CI 결정성 + cost 0 보존. CLI / function-level / backend 3개 default 경계를 회귀 테스트로 잠금. |
| [0025](./adr/0025-cost-frontier-defer-until-real-baselines.md) | accepted | cost-accuracy frontier을 외부 baseline 실측이 land할 때까지 deferral (defers #177; backs README §Limitations "비용 영점"; follows 0019 → 0021 pattern) | "왜 비용 축 frontier plot이 없냐?"에 modeled-cost 가짜 그림 대신 measurement-gated deferral로 응답. self-hosted 전부 cost=0이라 in-repo ablation들은 x=0에 모임 → 외부 baseline(`backend != "stub"`) 실측이 들어와야 비로소 의미 — 그 조건을 ADR로 잠금. #124의 latency-quality Pareto frontier가 그동안 portfolio asset. |
| [0026](./adr/0026-cross-encoder-reranker-deferral.md) | accepted | cross-encoder reranker 기본값 = stub-identity 유지, 실 backend(bge / bge_ko / cohere) 측정 deferral (mirrors 0019/0025 pattern) | `full` vs `no_rerank`가 공개 합성에서 이미 0pp (ADR 0002 metadata-first가 dense 위 reorder를 무의미하게 함). `full_reranker`는 CI stub 디폴트에서 `full`과 by-construction 비트동일. Protocol 표면은 향후 HyDE-reranker / LLM-as-reranker seam으로 보존 — 측정 효과 없으나 *측정이 안 됐다*는 점을 ADR로 잠금. |
| [0027](./adr/0027-lora-finetuned-embedding-additive.md) | proposed | LoRA-fine-tuned embedding adapter as additive ablation, env-var gated (`BIDMATE_EMBEDDING_LORA_ADAPTER`), HF Hub adapter pinned by commit SHA (extends 0001 / 0011 / 0019; does NOT trigger 0019 re-open) | "have you fine-tuned a model?" 인터뷰 질문에 reproducible artifact(Colab 노트북 + HF Hub adapter)로 답. Phase 1.2/ADR 0019에서 metadata-first가 embedding variance를 흡수한다는 것이 확인됐으므로 `full` 행은 ~0pp가 honest 결과 — 그래서 dense-only `naive_baseline_finetuned` 행을 같이 land해서 측정 가능한 표면을 분리. HF Hub adapter는 `<repo>@<sha>` SHA pin으로 silent re-push supply-chain 차단. |
| [0028](./adr/0028-security-screen-additive.md) | accepted | Prompt-injection screen (query-side, diagnostic-only) + PII redaction (ingestion-time, opt-in via `BIDMATE_INGEST_REDACT_PII`) as additive security layer (extends 0008 to query side; preserves 0001 / 0003 / 0005) | ADR 0008이 evidence 측 injection 방어라면 0028은 query 측 보완. 5개 한국 RFP 도메인 + 3개 영문 일반 패턴의 regex floor — Llama Guard 같은 ML 분류기는 측정-게이트로 미루고 결정적 floor부터. PII는 default off + 단일 env-var 토글로 ADR 0001 byte-identical 유지. "production 보안 어떻게?" 질문에 측정 가능한 답 + ADR 0008과 짝을 이루는 surface 설계. |
| [0029](./adr/0029-real-data-case-proposer-additive.md) | proposed | Real-data case proposer as additive semi-supervised eval-set growth (extends 0005 / 0006; reuses 0011 / 0012 backend pattern; preserves 0001 / 0003 / 0004 / 0008; calibration mirrors 0016) | ADR 0005가 case 본문 commit을 막아 N=100에 묶인 private real-data eval을 사람-검수 게이트로 확장. proposer 자체를 ADR 0011 additive-ablation 패턴(stub-default + opt-in live, 0012 미러)으로 만들고, `proposer_accept_rate` / `field_edit_rate`만 commit boundary 위로 올림 — case 본문은 안 보이지만 "proposer가 얼마나 믿을 만한지"는 git log에 남는다. 자동 라벨링 시스템 자체를 정량 평가한다는 ADR 0016 패턴 재사용. "private eval을 어떻게 확장하셨나요?" 질문에 측정-게이트 답 + commit boundary 유지 설계. |
| [0030](./adr/0030-leaderboard-headline-includes-agentic-full.md) | accepted | Leaderboard headline expands to render `agentic_full` alongside `naive_baseline` as parallel time series; ADR 0001 baseline preserved, `ablation_full` aggregate key added to history snapshots (extends ADR 0001 / ADR 0024 visibility surface) | ADR 0001이 보장하는 baseline 결정성과 ADR 0024가 운영 surface로 잡은 `agentic_full`을 leaderboard에서 *동시에* 가시화. "안 변하는 baseline" 옆에 "움직이는 full"을 두는 것이 정체된 메트릭이 아니라 *의도된 두 축*임을 시각으로 증명. `ablation_full` aggregate sub-key는 ADR 0005 화이트리스트 패턴(`judge_ragas` 0012, `retry_effectiveness` #120) 그대로 — 정수/실수 스칼라 + bootstrap CI 만 통과. forward-only 마이그레이션으로 기존 21개 snapshot에는 키 부재, 새 cron 부터 자동 채워짐. |
| [0031](./adr/0031-bm25-korean-morphology-additive.md) | accepted | BM25 Korean morphology tokenizer (`bm25_tokenizer: "regex" \| "kiwi"`) as additive ablation, kiwipiepy lazy-imported with never-raise fallback to regex (extends 0010 / 0011; preserves 0001 / 0003; follows 0019 → 0021 / 0026 measurement-gated pattern) | 외부 리뷰 §A3-S3가 정확히 짚은 한국어 형태소 분석기 부재를 측정-게이트 ablation으로 충당. `re.compile(r"[A-Za-z0-9]+\|[가-힣]+")` regex가 "입찰참여시작일" vs "입찰 참여 시작일"을 다르게 토큰화하는 갭을 kiwipiepy 체언/용언/수식어/외래어 POS filter로 정렬. 새 config key + `full_kiwi` 행 + never-raise 폴백 — 휠 누락 환경에서 byte-equal to `hybrid_bm25`. ADR 0019 → 0021 deferred-then-closed 패턴 그대로 — 측정 ≥+3pp lift 시 follow-up ADR로 default flip 가능. "Korean tokenizer 어떻게 했어요?" 질문에 measurable answer + 추가 30MB dep을 hard CI required로 만들지 않은 trade-off 설명. |

**인터뷰 talking point 1 (real-data 회귀)**: "ADR 0005가 없었다면 공개본의 abstention 회귀(#69의 `1.000 → 0.500` 사건)는 아무도 보지 못했을 것이다. 공개 합성만 보던 시기에는 1-of-2 incidental overlap 패턴이 잡히지 않았다." — 근거: [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md) 2026-05-11 entry.

**인터뷰 talking point 2 (additive ablation 규율)**: "ADR 0011은 LLM 합성을 *추가*하지만 ADR 0001의 extractive baseline을 *대체하지 않는다*. `agentic_full_llm` preset은 같은 claims/citations에 answer_text만 LLM으로 렌더링하고, evidence에 없는 chunk_id를 인용하면 거부되고 extractive로 fallback. ADR 0013의 observability도 같은 패턴 — additive + fail-closed. 새 기능이 들어와도 기존 measurement surface가 손상되지 않게 보존한다는 규율이다."

**인터뷰 talking point 3 (보안 contract)**: "ADR 0008은 prompt injection 방어를 *답변 contract의 일부*로 정의한다. evidence boundary 마커로 LLM이 외부 텍스트를 instruction이 아닌 데이터로 보도록 강제 — 검증 가능한 자리(테스트 `test_prompt_injection_regression.py`)에 보안이 잠겨있어야 시니어 코드 리뷰에서 통과한다."

## 시니어 시그널 2 — 측정의 엄격성

엔지니어가 "성능이 좋아졌다"고 말할 때 시니어 리뷰어가 보는 것은 **무엇을 어떻게 측정했는가**다.

이 프로젝트의 측정 시스템은 다음과 같이 분리되어 있다.

```
공개 합성 표면 (eval/config.yaml)        비공개 real-data 표면 (eval/real_config.local.yaml)
  - PR마다 CI에서 자동 실행                  - 운영자 머신에서만 실행 (ADR 0005)
  - 결정성 보장 (낮은 분산)                  - 실제 분포 신호 (높은 분산)
  - reproducible: make smoke                 - aggregate-only commit (private)
  - 보장: contract / regression              - 보장: real-world generalization
```

리뷰어가 측정 엄격성을 점검할 때 볼 곳:

- **CI eval delta**: 모든 PR에 자동 코멘트되는 metric diff (`.github/workflows/pr-eval.yml`). PR #98이 `abstention 0.857 → 1.000`을 어떻게 surface했는지 보면 됨.
- **Real-data Decision Log**: [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md)의 Decision Log 섹션. 변경별 before/after aggregate, status distribution, 결정의 이유까지 기록.
- **README headline 표**: `scripts/update_readme_metrics.py --check`가 CI에서 강제. README의 숫자는 손으로 적을 수 없다.

**인터뷰 talking point**: "synthetic abstention이 perfect score(1.000)인데도 real-data abstention이 0.500이라는 사실을 발견하지 못했다면, 이 시스템은 silent regression 위에서 성능을 주장하고 있었을 것이다. ADR 0005는 그 격차를 일부러 surface한다."

## 시니어 시그널 3 — 실패를 시스템적으로 다룬다

실패는 발생하는 것이 아니라 **분류되고, 우선순위가 매겨지고, 회귀 가드로 잠긴다**.

- 실패 분류: [`docs/real-data-failure-taxonomy.md`](./real-data-failure-taxonomy.md) — 6개 카테고리(C1–C6) + 9개 우선순위 백로그
- 회귀 가드: `tests/test_*_regression.py` 패턴. 각 테스트의 docstring이 originating issue를 링크 — 예: `tests/test_partial_topic_grounding.py`는 #69, #89를 모두 링크
- 결정 기록: 변경마다 [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md)의 Decision Log entry로 ablation 비교 + 채택 이유 + reproducibility recipe 남김

**인터뷰 talking point**: "issue #69(`PARTIAL_TOPIC_GROUNDING_MIN_FRACTION = 0.5`)는 `accuracy +0.118`을 기록했지만 `intended-abstention`을 회귀시켰다. 합성 표면이 잡지 못한 이 trade-off를 ADR 0005 기반의 비공개 평가가 잡았고, 후속 issue #89가 `matched ≥ 2` 구조적 floor로 해결했다 — 회귀 가드(`test_relaxed_rejects_one_of_two_partial_topic_match`)와 합성 케이스(`abstention_one_of_two_topic_overlap`)를 함께 추가해 다음번 합성 CI에서도 잡히게 만들었다."

이 한 사건이 **C6(false abstention) 실패 카테고리 → real-data로 발견 → ablation 비교 → 구조적 fix → 회귀 잠금**의 full loop을 모두 보여준다.

## 시니어 시그널 4 — 거버넌스가 코드와 같이 진화한다

규칙은 문서에만 적혀있는 것이 아니라 **자동화로 강제**된다.

| 규칙 | 어디에 적혀있나 | 어떻게 강제되나 |
|---|---|---|
| Pre-PR 7-item 체크리스트 | [`.github/pull_request_template.md`](../.github/pull_request_template.md) | PR template + 리뷰 게이트 |
| Real-data delta 첨부 (load-bearing 변경) | [`.github/pull_request_template.md`](../.github/pull_request_template.md) §5b | `.githooks/pre-push` 옵션 hook + PR 가이드 |
| ADR threshold | [`CLAUDE.md`](../CLAUDE.md) §"Core principles" + [`docs/adr/README.md`](./adr/README.md) | 리뷰어 명시적 질문 |
| Public/private eval 분리 | [ADR 0005](./adr/0005-eval-split-public-synthetic-private-local.md) | `scripts/run_real_eval_delta.py`의 `SAFE_TOPLEVEL_KEYS` / `FORBIDDEN_KEYS` enforcement |
| Answer contract immutability | [ADR 0003](./adr/0003-structured-answer-citation-contract.md) | `score_answer_format` in `eval/run_eval.py` |
| README metrics ↔ report 동기화 | `scripts/update_readme_metrics.py` + CI gate | `scripts/update_readme_metrics.py --check` (CI) |
| Naive baseline 보존 | [ADR 0001](./adr/0001-preserve-naive-baseline.md) | `eval/config.yaml`의 `naive_baseline` ablation 매번 실행 |

거버넌스가 어떻게 anti-pattern을 차단하는지는 [`engineering-governance.md` §"Anti-patterns this governance is designed to prevent"](./engineering-governance.md) 참조.

## 시니어 시그널 5 — 재현성을 갖춘 시연

리뷰어가 클론한 직후 한 명령으로 시스템을 돌려볼 수 있다.

```bash
make smoke      # build_index → sample query → eval → README check
make reproduce  # smoke + SHA-256 over the environment-invariant metric subset
```

- 외부 API/네트워크 의존 없음 (`EMBEDDING_BACKEND=hashing`)
- 결정성 (`hashing` backend) → 같은 입력에 같은 출력
- 산출물: `outputs/answer.json`, `reports/eval_summary.json`
- **크로스머신 재현성 증명**: `make reproduce`가 `eval_summary.json`에서 latency·timestamp 같은 host-dependent 필드를 제거한 후 SHA-256을 계산한다. 같은 해시가 다른 머신(Linux container 등)에서 나오면 결정성 주장이 *증명 가능*한 형태로 backing된다 — `BASELINE=<hash> make reproduce`로 비교 시 mismatch는 exit 2.

운영 데모는 [`docs/api-demo.md`](./api-demo.md)의 FastAPI 한 줄 startup으로 분리되어 있다 — playground이지만 measurement source는 절대 아님 ([`engineering-governance.md` table](./engineering-governance.md) 참조).

**구조화 로깅**: `BIDMATE_LOG_FORMAT=json make demo`로 stdout JSON 로그를 흘려보내면 stage별 `query_start`/`query_complete` 이벤트가 `query_hash`/`latency_ms`/`status`/`retry_count`/`abstained` 필드와 함께 떨어진다. 로그 aggregation(CloudLogging/ELK/Datadog)에 그대로 꽂아 운영 관찰성을 확장 가능. 구현은 [`bidmate_logging.py`](../bidmate_logging.py).

## 인터뷰에서 받을 만한 질문과 답의 위치

| 질문 | 답이 있는 곳 |
|---|---|
| "왜 RAG에서 generation 모델보다 retrieval/verification에 더 투자했나요?" | [`portfolio-case-study.md` §3, §5](./portfolio-case-study.md) |
| "성능 숫자를 어떻게 신뢰할 수 있나요?" | 이 문서 §2 + README "핵심 성능표" + `make smoke` |
| "real-data와 synthetic의 격차를 어떻게 다루나요?" | [ADR 0005](./adr/0005-eval-split-public-synthetic-private-local.md) + [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md) |
| "회귀 발생을 어떻게 막나요?" | 이 문서 §3 + `tests/test_*_regression.py` |
| "한국어 RFP의 메타데이터 기반 retrieval은 어떤 trade-off가 있나요?" | [ADR 0002](./adr/0002-metadata-first-retrieval.md) + [`docs/retrieval-hardening.md`](./retrieval-hardening.md) |
| "abstention/insufficient는 왜 별도 status로 두었나요?" | [ADR 0003](./adr/0003-structured-answer-citation-contract.md) + [`docs/answer-policy.md`](./answer-policy.md) |
| "prompt injection은 어떻게 막나요?" | [ADR 0008](./adr/0008-evidence-boundary.md) + `tests/test_prompt_injection_regression.py` |
| "LangChain/LlamaIndex 안 쓰고 왜 자체 구축?" | [ADR 0009](./adr/0009-external-baseline-comparison.md) — 비대칭 metric(citation/abstention)을 외부 시스템이 producer 못하는 게 정량 답변 |
| "LLM-as-judge bias는 어떻게 다루나요?" | [ADR 0012](./adr/0012-llm-judge-on-public-synthetic.md) + [ADR 0014](./adr/0014-ragas-judge-additive-synthetic.md) — stub-default + RAGAS cross-check |
| "운영에서 latency/cost/trace는 어떻게 봅니까?" | [ADR 0013](./adr/0013-observability-as-additive-pluggable-surface.md) + [`docs/observability.md`](./observability.md) — LangFuse/OTel pluggable, fail-closed |
| "토큰 비용은 어떻게 추적하나요? prompt caching hit rate는요?" | [ADR 0015](./adr/0015-cost-telemetry-additive.md) — `diagnostics.synthesis.cost_estimate_usd` + `cache_read_tokens` + `cache_write_tokens`; price card는 `rag_synthesis.PRICING_PER_MTOK_USD`, 회귀 가드는 `tests/test_synthesis_cost_telemetry.py` |
| "p95 latency SLO는 어떻게 enforce하나요?" | `eval/config.yaml::latency_budgets`에 per-ablation 절대 ceiling 선언 → `make check-latency` (또는 PR workflow의 "Latency SLO check" step)이 violation 시 CI fail. 회귀 게이트(품질)와 SLO 게이트(latency)를 분리 — host variance 노이즈로 인한 거짓 fail 방지. 구현: `scripts/check_latency_slo.py`, 회귀 가드 `tests/test_check_latency_slo.py` |
| "한국어 일반 텍스트에서도 동작합니까?" | [ADR 0018](./adr/0018-korean-public-rag-bench.md) + `make korean-public-eval` — KorQuAD 2.1 dev 150건 out-of-domain 측정. 점수가 낮은 것이 *load-bearing*: RFP-도메인 특화 시스템의 generalization 한계를 명시적으로 노출. 구현: [`eval/korean_public/`](../eval/korean_public/README.md) |
| "2026년에 왜 2019년 MiniLM 임베딩?" | [ADR 0019](./adr/0019-embedding-default-stays-minilm.md) + [`docs/embedding-ablation.md`](./embedding-ablation.md) — 1차 측정: full 파이프라인은 metadata-first filtering(ADR 0002) 덕분에 embedding-invariant (0pp Δ). 2차 사이클은 env mismatch로 deferred, ADR 0019가 재오픈 조건(env 업그레이드 + `full` ≥+5pp)을 잠금 |
| "확장한다면 다음 우선순위는?" | [`portfolio-case-study.md` §7](./portfolio-case-study.md) + 메타 이슈 #49 |

## 이 프로젝트가 입증하지 않는 것 (정직한 범위)

시니어 시그널은 **무엇을 입증하지 않는지 명확히 말하는 것**도 포함한다.

- **대규모 generalization 성능**: 공개 합성 평가는 N=37, 비공개 real-data 표면은 N=21. 둘 다 일반화 주장의 근거가 아니라 **흐름·계약 검증**의 surface다. README는 이 한계를 명시한다 ([`portfolio-case-study.md` §2 마지막 문단](./portfolio-case-study.md)).
- **상업적 LLM 의존성에서의 성능**: 공개본은 결정성을 위해 hashing embedding + extractive answer를 사용한다. 운영 환경에서 dense embedding + LLM generation을 결합할 경우의 실측치는 별도 surface가 필요.
- **현존 RFP QA 솔루션과의 직접 비교**: 이 프로젝트는 비교 벤치마크가 아니라 **하나의 설계 결정 흐름**의 portfolio다. 절대 SOTA 주장이 아니다.

## 읽는 순서 (시간 예산별)

**5분 — 리뷰 우선**
1. [`reviewer-evidence-pack.md`](./reviewer-evidence-pack.md) (5-min demo + 대표 질의)
2. README "핵심 성능표"

**15분 — 포트폴리오 평가**
1. 이 문서 §"시니어 시그널 한눈에 보기" 표
2. [`production-readiness.md`](./production-readiness.md) — 운영 surface 1-pager (health, observability, cost, SLO, regression gate, reproducibility)
3. [`portfolio-case-study.md`](./portfolio-case-study.md) §3, §5, §7
4. ADR 0005 + 0003 (load-bearing 결정 둘만)

**30분 — 깊이 있는 평가**
1. [`engineering-governance.md`](./engineering-governance.md) 전체
2. ADR 6개 모두 (5분씩)
3. 이 문서 §3의 #69 → #89 case study
4. [`docs/private-100-doc-experiments.md`](./private-100-doc-experiments.md) Decision Log 1–2 entries

## 인터뷰 quick reference

이 섹션은 *참조 lookup*이 아닌 *실연 material*이다. 위 §"인터뷰에서 받을 만한 질문과 답의 위치" 표가 "X 질문 받으면 Y 찾으면 된다"라면, 여기는 "X 질문 받으면 그대로 말하면 된다."

### 30초 자기소개

> "BidMate-DocAgent는 **한국어 RFP 도메인-특화 RAG**입니다. 일반 영어 벤치(KMMLU/MMLU) 점수 경쟁이 아니라, 한국 B2B/공공 입찰 시장의 비교 질의에서 발생하는 한쪽 문서 starvation 패턴을 발견하고 막은 게 차별점입니다. **comparison-aware balanced top-k** + **metadata-first retrieval** + **extractive grounded-answer 계약**으로 hallucination을 구조적으로 차단하고, **공개 합성 + 비공개 real-data + KorQuAD 2.1 한국어 공개셋** 세 표면으로 silent regression을 분리 탐지합니다. 운영 시그널 측에서는 **30개 ADR**, prompt-caching 적용 **cost telemetry**, fail-closed **observability(LangFuse/OTel)**, **CI 회귀 게이트**까지 완성했습니다."

읽는 시간 ≈ 30초. 면접 첫 답으로 그대로 사용 가능. 상대가 "좀 더 자세히"를 물으면 §1, 측정 의문에는 §2, 운영 의문에는 [`production-readiness.md`](./production-readiness.md)로 넘어간다.

### 5분 데모 스크립트

라이브 데모는 [HF Spaces](https://huggingface.co/spaces/hskim-solv/bidmate-docagent) 또는 로컬 `make demo` (http://localhost:8501) 둘 다 동일. cold-start 30–60초를 감안해 시작 전에 미리 한 번 깨워둘 것.

| 시간 | 행동 | 말할 내용 |
|---|---|---|
| 0:00–0:30 | HF Spaces 또는 `make demo` 오픈. 3개 preset 라디오(`naive_baseline` / `agentic_full` / `agentic_full_llm`) 보여주기 | "추가 설정 없이 브라우저에서 바로 라이브. 같은 질의에 대해 extractive vs LLM 합성 응답을 side-by-side 비교할 수 있도록 ablation을 UI에 노출했습니다." |
| 0:30–1:30 | Comparison 질의 실행 — 예: `기관 A와 기관 B의 AI 요구사항 차이 알려줘`. answer + claim 별 chunk_id citation 보여주기 | "이 프로젝트의 핵심 기여는 RFP 비교 질의에서 한쪽 문서 starvation을 막는 **balanced top-k retrieval**입니다. 일반 RAG 튜토리얼엔 없는 도메인-특화 ranking이고, 모든 claim이 evidence chunk_id로 추적되므로 hallucination이 구조적으로 불가능합니다." |
| 1:30–2:30 | Abstention 질의 실행 — 예: `기관 A의 양자암호 적용 방안은?`. 🔴 `status: insufficient` 명시 보여주기 | "evidence가 부족할 때 답을 만들어내는 대신 **명시적으로 abstain**합니다. ADR 0003에서 `insufficient`를 1급 status로 두었습니다. 검토자가 *불확실성*을 알 수 있어야 자동화에 의존할 수 있습니다." |
| 2:30–3:30 | 답변 아래 "🔍 View trace" 클릭 → LangFuse / OTel UI. retrieve / verify per-attempt span, retry 발생 시 attempt_index=1 span 보여주기 | "LLM Ops observability는 **fail-closed 옵셔널 surface**입니다. `BIDMATE_TRACE_BACKEND=langfuse` 한 줄로 켜고, 끄면 zero overhead noop. 백엔드 장애가 query를 절대 깨뜨리지 않습니다(ADR 0013)." |
| 3:30–4:30 | `outputs/answer.json` 또는 FastAPI 응답의 `diagnostics.synthesis` 펼치기. `cost_estimate_usd`, `tokens_in/out`, `cache_read_tokens > 0` 보여주기 | "Anthropic prompt caching이 시스템 프롬프트 + 도구 정의에 활성화돼 있고, 두 번째 호출의 `cache_read_input_tokens > 0`가 실제로 캐시 hit하는 증명입니다. `cost_estimate_usd`는 ADR 0015의 order-of-magnitude regression 시그널 — Anthropic 콘솔이 billing source of truth라는 점을 명시적으로 밝힙니다." |
| 4:30–5:00 | README headline 표 + GitHub Pages [leaderboard](https://hskim-solv.github.io/BidMate-DocAgent/leaderboard/) 열기 | "README 숫자는 `scripts/update_readme_metrics.py --check`로 CI gate에서 강제되고, leaderboard는 main merge마다 자동 누적됩니다. ADR 0005 aggregate-only 경계가 `extract_aggregate`로 defense-in-depth 적용돼 비공개 per-case 데이터는 새지 않습니다." |

### 면접 빠른 답변 카드

위 데모를 끝낸 뒤 받을 가능성이 높은 follow-up과 각 답이 살아있는 위치:

| 면접관 질문 | 답할 위치 / talking point |
|---|---|
| "왜 generative 모델이 아닌 extractive?" | 데모 1:30–2:30 step + ADR 0003 "4가지 이유" (재현성 / 비용 영점 / judge confound 제거 / hallucination 구조적 불가능) |
| "abstention을 어떻게 평가했나?" | ADR 0003 + 합성 abstention 9 cases + #69 → #89 case (이 문서 §3) |
| "observability와 cost를 어떻게?" | 데모 2:30–4:30 + [`production-readiness.md`](./production-readiness.md) (한 페이지 reviewer reference) |
| "측정을 어떻게 신뢰?" | 이 문서 §2 + bootstrap 95% CI + 3-surface 분리(ADR 0005 / 0018) |
| "회귀를 어떻게 막나?" | 이 문서 §3 + CI quality regression gate(`pr-eval.yml`) + `tests/test_*_regression.py` |
| "한국어 RAG 일반화는?" | KorQuAD 2.1 supplementary surface (ADR 0018) + "domain mismatch는 의도된 신호" 프레이밍 |
| "LangChain / LlamaIndex와 비교?" | ADR 0009 external baseline comparison — *옆 ablation*이지 교체가 아님 (ADR 0001 invariant) |
| "왜 2026년에 2019년 MiniLM 임베딩?" | ADR 0019의 4가지 명시적 re-open 조건 — "deferral도 ADR로 닫는다" |
