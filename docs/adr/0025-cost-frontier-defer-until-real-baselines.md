# 0025: 외부 기준선 실측 도착 전까지 cost-accuracy frontier 보류

- **Status**: superseded by [ADR 0038](./0038-cost-model-and-frontier-interpretation.md)
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (기준선 보존), [ADR 0009](./0009-external-baseline-comparison.md) (외부 기준선 인프라), [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) (LLM 합성 backend), [ADR 0015](./0015-cost-telemetry-additive.md) (cost telemetry), [`scripts/plot_pareto.py`](../../scripts/plot_pareto.py) (#124 latency-quality frontier), issues #157 (외부 기준선 real backend — infra-only close) / #177 (본 결정)

## TL;DR

- 비용 axis 없이 frontier를 그리는 3가지 구조적 갭(in-repo ablation cost=0 / 외부 기준선 stub / 토큰 집계 미배선)으로 #177 보류.
- modeled-cost frontier는 측정을 가정처럼 가장 — "no fabricated numbers" 자세(ADR 0019/0021) 위배.
- [`scripts/plot_pareto.py`](../../scripts/plot_pareto.py)(latency p95 vs citation_precision)가 portfolio asset 유지. 3 재개 조건 충족 시 #177 재개.

## 배경

issue #177은 cost-accuracy frontier plot("the single most compelling LLM Ops portfolio image") 제안: x=$/query, y=accuracy bootstrap-CI band, dot=분석 변형, dashed=Pareto frontier. 의미 있는 plot 산출을 막는 구조적 갭 3가지:

1. **모든 in-repo 분석 변형 token cost = 0.** `reports/eval_summary.json.ablation.runs`의 14 변형 모두 self-hosted stack(BGE-M3 / hashing backend embedding + stub LLM on CI; user-env 실제 로컬 모델)에서 실행. [`README.md`](../../README.md) §Limitations에 "비용 영점" 속성으로 이미 명시. $/query x-axis에서 모든 in-repo 변형이 x=0으로 collapse → frontier가 1-D accuracy-only line으로 축소.
2. **외부 기준선 실측 부재.** [ADR 0009](./0009-external-baseline-comparison.md)가 side-by-side 비교 표면 정의; issue #157이 인프라 측 close(LangChain / LlamaIndex backend 연결, `make external-baselines-langchain` / `-llamaindex` 타겟 머지). 그러나 `reports/external_baselines.json`은 여전히 stub(`backend: "stub"`, `model: "stub"`, `accuracy: 1.0`, n=42) ship — 실제 Sonnet / Haiku / OpenAI 수치 산출 user-environment run은 별도 수동 단계, 미수행. 채워진 파일 없이 frontier는 cost-bearing dot 없음.
3. **토큰 진단이 eval 집계까지 미배선.** [ADR 0015](./0015-cost-telemetry-additive.md)가 LLM 합성 경로([`rag_synthesis.py`](../../rag_synthesis.py))에서 per-call `tokens_in / tokens_out` 출력. eval-time 집계(`case_results[i].tokens_*`) 미구현 → 비-stub backend 측정해도 in-repo dot $/query 계산은 측정이 아니라 모델링 필요.

issue #124가 latency-vs-citation_precision Pareto frontier([`scripts/plot_pareto.py`](../../scripts/plot_pareto.py), `make pareto`, `reports/pareto.md` + 선택 `reports/pareto.png`) 이미 ship. shape(Pareto highlight, 선택 matplotlib render, 14 변형 dot)은 #177이 상상한 artifact; 빠진 것은 순수 *cost axis*.

## 결정

**외부 기준선 real-backend 측정 도착 전까지 #177 보류.** 사이 modeled-cost frontier 산출 금지. 기존 [`plot_pareto.py`](../../scripts/plot_pareto.py) frontier(latency p95 vs citation_precision)가 cost-quality 추론용 portfolio asset 유지. [`README.md`](../../README.md) §Limitations "비용 영점" framing은 이제 caveat가 아니라 본 ADR이 backing.

보류를 open issue 코멘트가 아니라 ADR로 등재한 이유: (a) 위 분석은 non-obvious — "#177 open" 보는 미래 기여자가 modeled-cost plot에 하루 투자 후에야 신호 없음을 발견할 수 있음, (b) 프로젝트가 일관 적용으로 이득 보는 measurement-gated 결정 패턴(ADR 0019 → 0021) 보유.

## 재개 조건

ADR 0025는 다음 **모두** 충족 시 재개(#177 작업 재개 + frontier plot 생성):

1. `reports/external_baselines.json`에 `backend != "stub"` 엔트리(예: `langchain_openai_sonnet`, `llamaindex_anthropic_haiku`, `langchain_openai_text_embedding_3_large`) ≥ 1 + `metrics.accuracy.n >= 32`. 인프라 존재(#157 close); user-environment run만 pending.
2. [`rag_synthesis.py`](../../rag_synthesis.py)의 ADR 0015 `tokens_in / tokens_out` telemetry가 `eval_summary.json.case_results[i]`에 집계 *또는* cost 모델이 configurable lookup table(공공 2026-Q2 가격 기반 분석 변형당 $/query 추정)로 방어 + trade-off가 후속 ADR 문서화.
3. 후속 ADR(002x 이상) 생성 — 선택된 cost 모델 + frontier plot 해석(production sweet spot / accuracy ceiling / cheapest acceptable floor — 원본 #177 spec 3 reading anchor) 문서화.

조건 1 충족했으나 결과 plot이 real-backend dot 1-2개만이면 후속 ADR이 외부 기준선 real-run 주기가 frontier 지원 너무 빈약함 + 추가 보류 문서화 가능 — ADR 0019 → 0021 deferred-then-closed loop과 동일 패턴.

## 결과

쉬워진 점:

- **fabricated frontier ship 없음.** modeled-cost plot은 권위 있게 보이지만 공개 가격 가정을 측정처럼 인코딩. honest-portfolio 비용은 이미지 1 감소; honest-portfolio 이득은 repo 내 모든 plot이 실제 eval 파이프라인 통과한 수치 backing.
- **[`README.md`](../../README.md) §Limitations "비용 영점" 진술이 ADR backing.** "왜 분석 변형 표에 cost axis 없냐"는 reviewer 질문에 verbal 설명이 아니라 measurement-gated 답변.
- **[`scripts/plot_pareto.py`](../../scripts/plot_pareto.py)가 canonical Pareto artifact 유지** — `make pareto`, `reports/pareto.md`, 분석 변형 문서에 이미 wired. 기여자가 두 frontier script 중 선택 불필요.
- **보류 자체가 searchable.** #177 pickup 검토 다음 기여자는 분석 재실행 전 본 ADR 발견.

비용 / 정직:

- #177이 상상한 portfolio 이미지("the single most compelling LLM Ops portfolio image" — issue body)는 오늘 repo 부재. cost-vs-accuracy 관심 reviewer는 [`scripts/plot_pareto.py`](../../scripts/plot_pareto.py)(latency cost proxy) + #177 body 공개 token-price 표 안내 가능, 합성은 reader 몫.
- 재개 조건은 user-environment 측정 단계(real API key로 `make external-baselines-langchain` / `-llamaindex`를 합성 eval 표면에 실행) gate. in-repo 자동화 critical path 외 — maintainer가 API 예산 지출 선택 의존.
- issue #177은 본 ADR pending close. 재오픈은 위 조건 충족 또는 다른 framing으로 0025 supersede ADR 작성 필요.

## 검토한 대안

- **modeled-cost frontier 지금 build.** 공공 2026-Q2 가격(Sonnet 4.6 $3/$15 per 1M, Haiku 4.5 $0.80/$4, BGE-M3 self-hosted $0, text-embedding-3-large $0.13/1M) × 분석 변형당 토큰 추정으로 plot 1개 생성. *기각:* 추정이 측정이 아니라 prompt size에서 reverse-derived. estimate-as-measurement ship은 [ADR 0019](./0019-embedding-default-stays-minilm.md) / [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) "no fabricated numbers" 자세 위배.
- **latency-only frontier로 대체.** *기각:* [`scripts/plot_pareto.py`](../../scripts/plot_pareto.py)가 #124로 제공한 그대로. 다른 label로 같은 chart re-ship은 #177 목표 진전 없음.
- **토큰 집계 인프라 먼저(ADR 0015 → eval 파이프라인 배선), 그 뒤 frontier.** *기각:* scope creep — 배선은 eval 집계 경로 touch하는 multi-PR 노력 최소, 독립적 유용(per-query cost reporting). 자체 issue 소속. 본 ADR은 #177 *보류* 문서화 — 인프라 작업 아님.
- **#177 코멘트로 open 유지.** *기각:* 코멘트는 ADR cross-reference 손실(본 ADR은 `docs/adr/README.md` Index + 의존 graph 등장; GitHub 코멘트는 아님). measurement-gated 패턴(ADR 0019/0021)이 이런 loop close 프로젝트 정립 방식.
- **#177 `wontfix` close.** *기각:* #177 기저 아이디어는 건전 — 외부 기준선 real data 먼저 필요할 뿐. `wontfix`는 data 존재 시 작업 재개 자연스러움을 흐림.

## Cross-encoder reranker 보류 (ADR 0026, consolidated)

ADR 0026(accepted, 동일 일자)이 동일 measurement-gated 보류 패턴을 cross-encoder reranker 표면에 적용. ADR 0026은 여기서 Superseded; key 결정 아래.

**Decision (ADR 0026):** `Reranker` Protocol + `CrossEncoderReranker`를 `rag_reranker.py`에 유지. `BIDMATE_RERANK_BACKEND=stub`(identity)를 CI default 유지 — `full_reranker ≡ full` by construction. 0pp 합성 delta에도 seam 제거 금지; Protocol은 HyDE-reranker / LLM-as-reranker 후속 plug point.

**Context:** 공공 합성 표면(n=42)에서 `full`(rerank blend on) + `no_rerank`(rerank off)가 accuracy/groundedness/citation_precision/abstention byte-identical. `rerank: true` blend는 zero 측정 lift. Real backend(`bge`, `bge_ko`, `cohere`) 미측정.

**재개 조건** (default flip에 셋 다 필요):
1. `bge` / `bge_ko` / `cohere` 중 ≥ 1이 공공 합성 eval(n=42) 완주; 결과를 `docs/retrieval/cross-encoder-reranker.md` §Results에 추가.
2. 해당 backend가 `full` 대비 `accuracy` 또는 `citation_precision`에 `full_reranker` lift ≥ +3pp, 95% CI 비중첩.
3. 후속 ADR이 latency/cost trade-off 문서화 + `BIDMATE_RERANK_BACKEND` default flip.

## See also

- [`scripts/plot_pareto.py`](../../scripts/plot_pareto.py) — 오늘 ship되는 latency-quality Pareto frontier(#124 close).
- [`reports/external_baselines.json`](../../reports/external_baselines.json) — 현재 stub; real-backend 엔트리 획득 시 재개 trigger.
- [ADR 0019](./0019-embedding-default-stays-minilm.md) → [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) — 본 ADR이 따르는 measurement-gated 보류 패턴.
