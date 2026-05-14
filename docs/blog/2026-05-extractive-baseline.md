---
layout: page
title: "Extractive를 1급 baseline로 유지하는 이유"
date: 2026-05-14
permalink: /blog/2026-05-extractive-baseline/
---

> BidMate-DocAgent의 기본 답변 경로는 외부 LLM 호출이 없는 **extractive grounded answer**다. LLM synthesis(`agentic_full_llm`)는 *교체*가 아니라 *추가 가능한 ablation*이다 ([ADR 0001](../adr/0001-preserve-naive-baseline/), [ADR 0011](../adr/0011-llm-synthesis-as-additive-ablation/)).
>
> 2026년에 generative RAG가 디폴트가 된 시장에서 왜 거꾸로 가는가. 도메인이 다르기 때문이다.

## 한 문장

**입찰 RFP 도메인에서는 잘못된 답변보다 침묵이 비즈니스적으로 더 안전하다.** 이 비대칭성이 generative-as-default를 무력화시킨다.

## RFP 도메인이 generic RAG를 망가뜨리는 4가지 비대칭

1. **응답의 비용 함수가 비대칭.** 일반 챗봇은 hallucination 1건의 비용 = 사용자 신뢰 -1. 입찰 도메인은 hallucination 1건의 비용 = 응찰 실패 또는 평가점수 감점 — 정량화 가능한 손실. "그럴듯한 답"이 가장 비싼 답이다.
2. **평가위원이 인용을 본다.** RFP 답변은 사람이 채점한다. 근거 문서·페이지·청크를 명시하지 않으면 점수가 깎인다. Citation은 UX가 아니라 **점수 항목**이다.
3. **다기관 비교가 빈번.** "기관 A와 B의 보안 요구사항 차이"처럼 2~3개 RFP를 동시에 비교하는 질의가 RFP 도메인의 핵심 패턴이다. Generic top-k cut은 한쪽 문서를 starvation시키고, generator는 사라진 문서를 그럴듯하게 "보완"한다.
4. **HWP·표·별첨이 1급 시민.** 한국 공공 RFP의 절반은 HWP이고 핵심 요건은 표/별첨에 들어있다. 텍스트만 보는 RAG는 "어떻게든 답"하지만 그 답은 본문에서만 끌어온 부분 정보다.

이 네 가지는 *시스템 설계가 generic generative RAG에 맞춰지면 망가지는* 지점이다. 답변 정책이 침묵을 1급 상태로 인정하지 않으면, 검증·평가 surface가 hallucination을 비용으로 환산하지 않으면, retrieval가 비교 질의를 1급 패턴으로 다루지 않으면 — 도메인이 시스템을 거꾸로 압박한다.

## 그래서 extractive를 1급 baseline로 박은 4가지 이유

[README "Why extractive, not generative?"](https://github.com/hskim-solv/BidMate-DocAgent#why-extractive-not-generative)의 4가지 이유를 도메인 관점으로 다시 풀면:

| 이유 | 일반 RAG 관점 | RFP 도메인 관점 |
|---|---|---|
| 재현성 | "CI에서 같은 결과" | "평가위원이 같은 결과를 재현할 수 있어야 점수가 단단해진다" |
| 비용 영점 | "토큰 비용 0" | "retry policy는 latency 1축으로 단순화되어, 답변 시간 SLA가 가능" |
| LLM-as-judge confound 제거 | "self-consistency 편향 차단" | "evaluator의 같은 LLM 편향에 답변이 끌려가지 않음 — 검증의 독립성" |
| Citation grounding 내재화 | "hallucination 구조적 불가" | "답변에 청크 ID가 강제로 박혀 평가위원이 클릭 한 번에 원문 검증" |

오른쪽 컬럼은 일반 RAG 튜토리얼에 없는 항목이다. 도메인 비대칭성을 이해해야 보이는 부분.

## 측정: extractive가 졌는데 어떻게 1급인가

[현재 표](https://github.com/hskim-solv/BidMate-DocAgent#%ED%95%B5%EC%8B%AC-%EC%84%B1%EB%8A%A5%ED%91%9C-%EC%8B%A4%EC%B8%A1) 일부:

- **Answer Accuracy**: `agentic_full` 0.718±0.10 vs `naive_baseline` 0.782±0.10 — baseline이 높다 (n=100, 95% CI).
- **Citation Precision**: `agentic_full` 0.705 vs `naive_baseline` 0.525 — **+18.0pp** 우위.
- **Abstention Accuracy (intended)**: `agentic_full` 0.810 vs `naive_baseline` 0.238 — **+57.1pp** 우위.

겉으로 보면 accuracy에서 baseline이 이기는 *불편한 표*다. 일반 leaderboard 패션이라면 이걸 표 밖으로 빼버리거나 ablation을 변형해 baseline을 떨어뜨릴 것이다. 그러지 않은 이유:

1. **Accuracy 단일 metric은 RFP 도메인에서 거짓말을 한다.** 평가위원에게는 "답을 잘하느냐"보다 "근거를 명시하느냐(citation precision)"와 "모르면 모른다고 하느냐(abstention)"가 더 비싸다. `agentic_full`이 두 컬럼에서 모두 baseline을 큰 폭으로 이긴다.
2. **n=42 → n=100 확장 중([issue #570](https://github.com/hskim-solv/BidMate-DocAgent/issues/570))에서 CI 폭이 ×0.65 수축**할 예정. 현재 accuracy -6.4pp의 통계적 의미는 CI band 안에 들어있다.
3. **Baseline을 *남겨두는 것*이 1급 규율([ADR 0001](../adr/0001-preserve-naive-baseline/)).** 모든 ablation 표에 `naive_baseline` 행이 강제로 박힌다. 비교 가능한 단순 baseline 없이는 "어떤 컴포넌트가 실제로 효과를 냈는가" 질문에 답할 수 없다.

## generative가 망가지는 자리를 보존하기 위한 ADR

- [ADR 0001](../adr/0001-preserve-naive-baseline/) — `naive_baseline`은 `eval/config.yaml`에 영구 ablation 행. 절대 삭제 금지.
- [ADR 0003](../adr/0003-structured-answer-citation-contract/) — answer dict의 `status` 필드에 `supported` / `insufficient` / `error` 3-state. **insufficient는 fallback이 아니라 1급 상태다.**
- [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local/) — public synthetic + private real-eval의 이중 평가 surface. synthetic CI가 통과해도 real-eval에서 abstention 회귀가 잡히면 PR이 block된다 (실제 사례: [`#69` intended-abstention regression](../engineering-governance/#governance-saves-real-incidents-prevented)).
- [ADR 0011](../adr/0011-llm-synthesis-as-additive-ablation/) — `agentic_full_llm`은 *추가*되는 ablation. extractive를 *교체*하지 않는다.

## Trade-off — 솔직하게

Extractive는 잃는 게 있다:

- **생성 유창성** — 청크 텍스트의 인용 연결은 자연스러운 산문보다 끊어진다. 사용자가 청구서 형태의 답변에 익숙하지 않으면 어색.
- **합성 추론** — 한 문서에는 없고 두 문서에 분산된 정보를 *연결해 새로운 결론을 도출*하는 능력은 약하다. 다만 RFP 도메인에서 이런 결론은 평가위원이 직접 내려야 할 영역이라 generator의 역할이 아님.
- **소수 케이스의 accuracy** — 위 표의 -6.4pp가 그 비용이다.

이 비용을 받아들이는 이유는 **citation 18pp + abstention 57pp**가 도메인에서 더 비싼 자산이기 때문이다.

## 결론

Extractive를 1급 baseline로 유지한다는 결정은 *generative를 거부*하는 것이 아니다. LLM synthesis(`agentic_full_llm`)는 [추가된 ablation](../adr/0011-llm-synthesis-as-additive-ablation/)으로 측정 가능하게 켤 수 있다.

핵심은 *순서*다. **Extractive가 기본, generative가 옵션** — 도메인 비대칭성이 이 순서를 강제한다. 입찰 RFP에서는 "그럴듯한 답"이 "침묵"보다 비싸고, 평가위원은 citation을 본다.

일반화 가능한 RAG가 아니라 *일반화하지 않는* RAG — 그게 이 프로젝트의 변별점이다.

---

*시리즈 다른 글: Public synthetic + Private real 이중 평가 surface, 실패 분류로 백로그 생성하기 — 작성 중.*
