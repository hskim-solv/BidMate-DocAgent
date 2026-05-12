---
layout: page
title: 외부 시니어 리뷰 → 사실 정정 + ADR 매트릭스
date: 2026-05-12
permalink: /blog/2026-05-external-review-followup/
---

> 결론: 외부 코드 리뷰의 권고 50%+가 이미 ADR로 결정돼 있었거나(때로는 정반대 방향으로), 측정 후 명시적으로 거부된 항목이었다.
> 이 글은 (1) 사실 정정 매트릭스, (2) 측정-게이트 거부 매핑, (3) 진짜 미구현 영역의 PR 시퀀스를 *한 문서*에 모아 같은 권고가 재유입될 때 즉시 회신 가능하게 만든다.

## 컨텍스트

`2026-05` 외부 시니어 엔지니어 리뷰(약 1만 단어, 코드 레벨 4축 분석: 아키텍처 / LLM·에이전트 / 문서 처리 / 프로덕션 준비도)를 수령했다. 리뷰 작성자가 "GitHub 웹뷰 기반이며 `git clone` 후 실행해 보지 않았다"라고 *명시적으로* 캐비엣을 단 것이 결정적이었다 — 캐비엣 자체는 honest reporting이지만, 검증을 안 한 만큼 *세부 사실 오류*가 발생할 여지가 있었기 때문이다.

받은 직후 한 작업은 단 하나: **권고 항목별로 코드/ADR/CI 실제 상태를 1-by-1로 검증**. 결과는 두 갈래로 갈렸다.

1. **놓친 구현이 많음** — HyDE, cross-encoder Protocol, LLM synthesis, Dockerfile, `pyproject.toml`, `.env.example`, FastAPI 운영 서버, 26 ADRs, 71 테스트, ruff/coverage 설정 — 전부 *이미 존재*. 웹뷰 한계 + 리뷰 시점의 정보 부족이 만든 오해.
2. **측정 후 거부된 권고가 많음** — bge-m3 임베딩 교체, cross-encoder rerank 도입, cost-accuracy frontier, "Why not LangGraph" ADR 등 — 모두 *측정-게이트 ADR* 또는 *역방향 결정*으로 이미 처리. 단순 재시도는 ADR 위반.

이 글은 그 검증 결과를 *재유입 방지용 단일 문서*로 남긴다. portfolio 면접에서 같은 권고가 나왔을 때 5분 안에 답할 수 있는 ammo이자, 본인이 6개월 후 같은 질문을 다시 받았을 때 "왜 그렇게 결정했는지"를 재검색 없이 회신할 수 있게 하는 안전망이다.

## §1. 리뷰가 놓친 구현 (이미 존재)

웹뷰 기반 리뷰가 자주 놓치는 패턴: *opt-in / lazy-import / Protocol-based pluggability*. 본 저장소는 이 패턴을 ADR 0001(naive baseline 보존)을 위해 의도적으로 채택했기에, 표면에 단순한 코드만 보이고 *대안 경로는 env-var 뒤에 숨어 있다*. 리뷰는 default behavior만 보고 "없음"으로 결론지은 항목이 많다.

| 리뷰 주장 | 실제 상태 | 코드 위치 |
|---|---|---|
| HyDE 없음 | **구현됨 + ADR 결정** | [`rag_query_expansion.py`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/rag_query_expansion.py) `HyDEExpander` (Anthropic Haiku), [ADR 0023](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0023-hyde-query-expansion-ablation.md), `BIDMATE_QUERY_EXPANSION_BACKEND=hyde` |
| Cross-encoder reranker 없음 | **Protocol + default 구현 존재** (ADR로 defer 결정) | [`rag_reranker.py`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/rag_reranker.py) `CrossEncoderReranker`, [ADR 0026](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0026-cross-encoder-reranker-deferral.md), `BIDMATE_RERANK_BACKEND=bge\|bge_ko\|cohere` dispatch |
| LLM 호출 전무 | **opt-in으로 wired** (lazy import) | [`rag_synthesis.py`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/rag_synthesis.py) `_anthropic_backend` / `_openai_compatible_backend`, `BIDMATE_SYNTHESIS_BACKEND=stub\|anthropic\|openai_compatible` |
| Dockerfile 없음 | **존재** | [`Dockerfile`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/Dockerfile) |
| `pyproject.toml` 없음 (ruff/lint 없음) | **존재** (단 룰셋 좁음: `E9,F63,F7,F82`) | [`pyproject.toml`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/pyproject.toml) `tool.ruff` + `tool.coverage` |
| `.env.example` 없음 | **존재** | [`.env.example`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/.env.example) |
| FastAPI는 의존성만 있고 활용 안 됨 | **운영 중인 API 서버** (ADR 0024가 기본 preset 결정) | [`api/main.py`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/api/main.py), [`api/schemas.py`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/api/schemas.py) |
| ADR 12개+ | **27개** (0001-0027, 0020 결번) | [`docs/adr/`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/) |
| `rag_core.py` 4,350 LOC god-file (단일 모듈) | **4,201 LOC** + 이미 20개 top-level 모듈로 PR-E 분해 진행 중 | `rag_pipeline_presets.py`, `rag_conversation_state.py`, `korean_lexicon.py`, `rag_query_expansion.py`, `rag_reranker.py`, `rag_synthesis.py`, `rag_observability.py`, `rag_vector_store.py` 등 |
| 테스트 가시성 낮음 | **71개 테스트 파일 + coverage 설정** | [`tests/`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/tests/), `pyproject.toml`의 `tool.coverage` (branch tracking, 14 모듈) |

리뷰가 *상황적으로* 옳았다고 해석할 수 있는 부분도 있다. CI default가 `stub`/`identity`/`hashing`인 경로가 많아서 "내부 dispatch"는 보여도 "default가 무엇인가"가 한눈에 들어오지 않는다. 이건 ADR 0011 ("LLM synthesis as additive ablation")이 의도한 trade-off — *재현 가능성 우선, real backend는 operator가 opt-in* — 의 비용이다. 향후 README 표면에 "default surface" 표를 1개 추가하면 같은 오해 재유입을 줄일 수 있다 (별도 issue로 추적).

## §2. 측정-게이트로 거부된 권고 (재시도 = ADR 위반)

ADR 0019 → 0021의 **deferred-then-closed loop** 패턴이 본 저장소의 핵심 거버넌스 도구다. 결정을 미루되 *재오픈 조건을 명문화* — 그 조건이 충족되는 순간 작업이 자동으로 시작된다. 리뷰가 권고한 다음 항목들은 모두 이 패턴 안에서 거부된 상태이며, 같은 권고를 다시 받았을 때 *재오픈 조건을 만족했는가*만 점검하면 답이 즉시 나온다.

| 리뷰 권고 | 거부 ADR | 재오픈 조건 (요약) |
|---|---|---|
| A3-S1: bge-m3로 임베딩 교체 ablation | [ADR 0019](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0019-embedding-default-stays-minilm.md) + [ADR 0021](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0021-bge-m3-completes-phase-1-3.md) | 5개 임베딩(MiniLM/e5-base/e5-large-instruct/KoSimCSE/BGE-M3) 측정 완료, 모두 `full` row +0.0pp. 새 후보가 ≥+5pp + 비중첩 95% CI일 때 재오픈. `naive_baseline` 리프트는 ADR 0001 invariant상 카운트 안 됨. |
| A3-S2: cross-encoder rerank ablation | [ADR 0026](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0026-cross-encoder-reranker-deferral.md) | Protocol/dispatch 존재 + stub default 유지. `BIDMATE_RERANK_BACKEND` 1개 백엔드(bge/bge_ko/cohere)가 `full_reranker`에서 ≥+3pp 측정 시 재오픈. |
| A4-S8: cost-accuracy frontier (LLM-on 행 + cost 컬럼) | [ADR 0025](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0025-cost-frontier-defer-until-real-baselines.md) | 인-리포 ablation 14개 모두 token cost = 0 (README §Limitations "비용 영점"). `external_baselines.json`이 stub인 동안 frontier는 1차원으로 붕괴. 실측 external baseline 1개+ + ADR 0015 token 집계 wiring 후 재오픈. |
| A1-S3: README "Agentic" 1단락 (수사 수정) | [ADR 0024](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0024-agentic-full-llm-as-api-default.md) | "behavior, not prose" 원칙으로 API 기본 preset을 `agentic_full_llm`으로 flip하여 해결 완료. CLI default는 ADR 0001로 `naive_baseline` 보존. |
| A1-S2: ADR "Why custom Python over LangGraph" | [ADR 0022](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0022-langgraph-orchestration-stage-1.md) | 실제 방향은 **반대** — LangGraph stage 1 (single-node passthrough, opt-in `BIDMATE_ORCHESTRATOR=langgraph`) 도입 중. "Why not LangGraph" ADR은 의도와 충돌. |
| A2-S5: Ragas / DeepEval 도입 | [ADR 0014](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0014-ragas-judge-additive-synthetic.md) | 이미 accepted (RAGAS-style multi-axis judge, additive). |
| A4-S3: Langfuse 통합 도입 | [ADR 0013](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0013-observability-as-additive-pluggable-surface.md) | 패턴 accepted. Langfuse는 backend 추가로만 가능 (별도 issue로 추적). |
| A2-S4: Pydantic v2 answer schema | [CLAUDE.md](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/CLAUDE.md) "Prohibited" | dict가 ADR 0003 contract. "왜 dict인가" 보강 ADR 0030이 별도 issue로 트래킹. |

각 거부 ADR은 *재오픈 조건을 명문화*하므로, 외부 리뷰가 동일 권고를 다시 가져왔을 때 "이미 ADR에서 거부됨"보다 더 정확한 답은 *"재오픈 조건 N개 중 X개가 미충족이다, 그 X개를 채우는 방법은…"* 가 된다. 게으른 답이 아니라 *측정 가능한 답*이 된다.

각 거부 ADR에 대응하는 **재오픈 tracking issue**를 [`adr-reopen`](https://github.com/hskim-solv/BidMate-DocAgent/labels/adr-reopen) 라벨로 5개 생성해 backlog에 등록했다. 측정 조건이 트리거되는 순간 작업이 자연스럽게 시작되도록.

## §3. 리뷰가 맞게 식별한 미구현 영역 (실제 ROI)

리뷰가 *정확히* 짚은 미구현 영역. 거부 ADR과 충돌하지 않고, 본 저장소의 portfolio 목표(senior AI engineer / Korean stack + LLM Ops)와 정렬되는 항목.

| 영역 | 현 상태 | 후속 PR |
|---|---|---|
| 한국어 형태소 분석기 | 없음 (`re.compile(r"[A-Za-z0-9]+\|[가-힣]+")` + 조사 후처리만) | PR-B1: kiwipiepy BM25 profile (ADR 0028 신규) |
| HWP 표 / 이미지 추출 | native loader는 plain text only ([`ingestion.py:193-196`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/ingestion.py)) | PR-C1: cell-level table extraction (issue #167 follow-up) |
| Prompt injection 방어 | 코드 없음 | PR-D1: `screen_query` + `redact_pii` (ADR 0029 신규) |
| PII 마스킹 | 코드 없음 | PR-D1 (동일) |
| Async FastAPI | `api/main.py`가 sync | 별도 issue (HTTP throughput 측정 후 결정) |
| mypy / bandit / pip-audit | 없음 (ruff는 좁은 룰셋만) | PR-E1: CI quality.yml 신규 |
| Tool / function calling | 도구 추상화 자체 없음 | 별도 issue (`compare_budgets` 같은 RFP 도메인 tool 1개부터) |
| `rag_core.py` 4,201 LOC | PR-E 분해 진행 중 | PR-H1: `rag_retrieval.py` 추출 (issue 신규) |
| LangGraph orchestrator | [ADR 0022](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0022-langgraph-orchestration-stage-1.md) proposed | PR-G1: stage 1 (single-node passthrough) implementation |
| DOCX 지원 | 미지원 | 우선순위 낮음 (RFP는 HWP 우세) |
| LayoutLMv3 / ColPali | 명시적으로 미사용 ([`visual_ingestion.py:7-8`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/visual_ingestion.py)) | PR-F1: 1-page comparison spike (Stage 3) |

전체 PR 시퀀스(A1~H1)는 `/Users/hskim/.claude/plans/bidmate-docagent-rippling-feigenbaum.md` 플랜 문서에 노력 추정 + 의존 관계 + 검증 명령어와 함께 등록됨.

## 메타 — 외부 리뷰를 받을 때의 프로세스

이번 사이클에서 효과 있던 절차를 한 문장씩 정리.

1. **검증부터.** 리뷰 작성자의 캐비엣을 *자동으로* "사실 검증 필요" 신호로 해석. 본 케이스는 작성자가 명시했지만, 명시 없어도 default가 "verify before act."
2. **권고당 ADR 매핑.** 각 권고를 *항상* 기존 ADR과 매칭 시도. 매칭이 있으면 거부, 매칭이 없으면 진짜 갭. 매핑 자체가 본 글의 §1.2 표.
3. **재오픈 조건을 issue화.** 거부는 끝이 아니라 *대기 상태*. 측정-게이트 ADR의 조건을 `adr-reopen` 라벨 issue로 변환해 backlog에 항상 visible.
4. **portfolio 산출물로 회수.** 검증 결과 자체를 단일 문서로 만들어 면접/재유입 회신용 ammo로 사용. 이번 사이클의 코드 변경은 0줄이지만 portfolio value는 ADR 5개 추가에 준한다.

리뷰의 *디테일*은 절반 이상 빗나갔지만, *문제 의식*은 정확했다 — "Agentic이 LLM 없이 가능한가?", "god-file의 분해는 어디까지?", "production 보안 검증은?" 같은 질문들. 이 질문들에 측정-게이트로 답할 수 있는 시스템을 *이미* 갖춰 둔 것이 이번 사이클의 최대 학습이다.

## 관련 자료

- 후속 PR 시퀀스 플랜: `/Users/hskim/.claude/plans/bidmate-docagent-rippling-feigenbaum.md`
- 거부 ADR 재오픈 tracking: [`adr-reopen` label](https://github.com/hskim-solv/BidMate-DocAgent/labels/adr-reopen)
- 측정-게이트 패턴의 origin: [ADR 0019](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0019-embedding-default-stays-minilm.md) → [ADR 0021](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0021-bge-m3-completes-phase-1-3.md)
- ADR Index 전체: [`docs/adr/README.md`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/README.md)
