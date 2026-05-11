---
layout: page
title: 실패 분류로 백로그 생성하기
date: 2026-05-11
permalink: /blog/2026-05-failure-taxonomy-backlog/
---

> 결론: 평가 실패는 *데이터*다. ad-hoc로 고치는 대신 카테고리 → root cause → 코드 위치 → Impact/Effort → GitHub 이슈로 매핑하면, 백로그가 *자동으로* 우선순위화된다.
> 본 프로젝트의 6 카테고리 분류는 4개의 머지된 PR(#69, #71, #72, #73)을 생성했고, 매핑 자체가 추적 가능한 artifact로 남는다.

## 흔한 함정: "버그 → 즉시 fix"

평가에서 실패 케이스가 나오면 자연스러운 반응은 *이걸 어떻게 고치지?* 다. 한 케이스를 깊게 들여다보고, 코드 한 곳을 손보고, 다시 평가를 돌려 통과하면 끝. 이 흐름이 빠르고 만족스럽다.

문제는 두 가지다.

1. **개별 fix가 다른 케이스에 영향을 미치는지 모른다.** 어떤 카테고리의 실패인지 라벨링하지 않으면, "verifier를 풀어 false abstention을 줄였더니 false positive가 늘었다" 같은 trade-off가 사후에 발견된다.
2. **백로그가 *없다*.** 다음에 무엇을 우선할지가 *느낌*으로 결정된다. 시간이 한정된 상황에서 H/Impact L/Effort 항목보다 L/Impact H/Effort 항목을 먼저 잡는 일이 빈번하게 일어난다.

이 글은 본 프로젝트가 사용한 *반대 흐름*을 정리한다. 분류 → 매핑 → 우선순위 → 이슈/PR. artifact는 [`docs/real-data-failure-taxonomy.md`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/real-data-failure-taxonomy.md) 에 184줄로 남아있다.

## 단계 1 — 실패를 *분류 가능한 단위*로 본다

real-data 평가셋(N=21, 17 answerable + 4 intended-abstention)에서 12건이 실패. 이 12건을 6 카테고리로 분리했다.

| ID | 카테고리 | 빈도 | 주요 신호 |
|---|---|---:|---|
| C1 | 메타데이터/엔터티 정규화 | 3/12 | retrieval miss + retry 후에도 `topic_not_grounded` |
| C2 | 발주기관/사업명 모호성 | 2/12 | 동일 substring 다수 후보 → 잘못된 후보 fallback |
| C3 | 청크 경계/섹션 오류 | 0 (C1/C2에 가려짐) | (단독 분리 불가) |
| C4 | 후속 질문 문맥 소실 | 3/12 | `context_resolution=resolved` 인데 retrieval 빈 결과 |
| C5 | 인용 불일치/약한 근거 | 4/12 | `citation_term_match=False` |
| C6 | 잘못된 abstention | 9/12 | `retry_trigger_reason=topic_not_grounded×2` |

C6이 9/12로 압도적이지만, [실패 분류 문서](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/real-data-failure-taxonomy.md)는 "이는 C1/C2/C4의 retrieval 약점이 곧장 false abstention으로 직결된 결과"라고 해석한다. **즉 C6은 *증상*이고 C1/C2/C4가 *원인*** — 분류가 인과 구조까지 드러낸다.

분류의 핵심은 **카테고리 정의가 코드 위치를 가리킨다**는 점이다. C5는 `rag_core.py:2052` `make_citation`을, C6은 `rag_core.py:1843` `verify_evidence`를 지목한다. 한 줄짜리 라벨이 아니라 *수정 후보 코드*가 카테고리 정의에 박혀있다.

## 단계 2 — 카테고리 → root cause → 수용 조건

각 카테고리마다 4-필드 분석을 작성한다.

```
- 사용자 관점 증상
- 추정 원인 (코드 경로 포함)
- 코드 변경 후보 (rag_core.py:line 단위)
- 수용 조건 힌트 (어떤 측정값으로 fix 완료를 판정할지)
```

예시 — **C6 (잘못된 abstention)**:

> **증상**: 답변 가능했어야 할 12건 중 9건이 abstention으로 끝남. retry trigger는 일관되게 `topic_not_grounded × 2` (strict + relaxed 두 단계 모두 거부).
>
> **추정 원인**: `verify_evidence` ([rag_core.py:1843](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/rag_core.py#L1843))의 topic grounding 기준이 너무 엄격해 부분 매칭 evidence를 모두 거절. relaxed 단계에서도 evidence 임계값이 strict와 거의 동일하게 작동.
>
> **코드 변경 후보**: `rag_core.py:1843` partial topic grounding 모드 도입, `rag_core.py:1222` relaxed threshold 완화.
>
> **수용 조건**: 본 카테고리 9건 중 절반 이상이 `partial` 또는 `supported`로 회복, 의도된 abstention 3건(P-13~15)은 그대로 유지(false negative 방지).

수용 조건이 정량으로 박혀 있어 *PR이 끝났는지 / 안 끝났는지*가 측정 가능하다. 이 조건이 그대로 GitHub 이슈의 "Acceptance criteria" 섹션으로 넘어간다.

## 단계 3 — Impact/Effort grid가 PR 순서를 결정한다

분류만으로는 부족하다. 어떤 카테고리부터 잡을지가 *Impact × Effort* 그리드로 정렬된다.

| 우선순위 | ID | 제목 | Impact | Effort | 상태 |
|---|---|---|---|---|---|
| **P0** | R2-test | retrieval loop 회귀 테스트 추가 | H | S | (도구) |
| **P0** | C6-1 | 부분 매칭 evidence 허용 (false abstention 감축) | H | M | **[#69 머지](https://github.com/hskim-solv/BidMate-DocAgent/pull/88)** ✅ |
| **P1** | C5-1 | citation chunk text ↔ claim term 정렬 검증 | H | S | (백로그) |
| **P1** | C4-1 | resolved entity를 retrieval query에 inline | H | S | **[#71 머지](https://github.com/hskim-solv/BidMate-DocAgent/pull/115)** ✅ |
| **P1** | C1-1 | 부분 substring/약어 entity의 retrieval 시드 보강 | H | M | (백로그) |
| **P2** | C2-1 | single-turn entity 모호성 clarification status | M | M | **[#72 머지](https://github.com/hskim-solv/BidMate-DocAgent/pull/116)** ✅ |
| **P3** | C3-1 | chunk boundary probe 설계 + 진단 강화 | M | M | **[#73 머지](https://github.com/hskim-solv/BidMate-DocAgent/pull/109)** ✅ (probe set) |

이 표는 분류 PR(#47)의 결과물이고, 후속 4 PR이 *이 표에 따라* 만들어졌다. 우선순위는 *문서가 권고*했고 PR들은 *그 권고대로* 진행됐다.

핵심은 — **그 표 없이 우선순위가 결정됐다면 다른 순서로 진행됐을 가능성이 높다.** 직관적으로 C5(인용 불일치, 4건)가 C4(후속 질문, 3건)보다 더 시급해 보일 수 있다. 하지만 Effort×Impact를 정량으로 보면 P1 동급이고, 시작점은 R2 핫픽스 + C6(symptom의 절반 이상)가 된다.

## Walk-through: C6 → 이슈 #69 → 머지

C6 한 카테고리만 끝까지 따라가 본다.

1. **발견** (실데이터 평가): 12 실패 중 9건이 C6 패턴.
2. **분류** (`real-data-failure-taxonomy.md:136-147`): 코드 위치 `rag_core.py:1843`, 수용 조건 "9건 중 절반 회복 + intended abstention 3건 유지".
3. **이슈 생성** (Issue #69): 위 분석을 그대로 본문에. branch `<type>/issue-69-<slug>` 컨벤션(ADR 0007)으로 추적.
4. **PR 구현** ([#88](https://github.com/hskim-solv/BidMate-DocAgent/pull/88)): `verify_evidence`에 `allow_partial_topic`, `PARTIAL_TOPIC_GROUNDING_MIN_FRACTION=0.5` 추가.
5. **공개 + 실데이터 평가 비교** ([previous post](../2026-05-public-synthetic-private-real/)):
   - public synthetic n=42: 회귀 없음 ✅
   - private real n=21: accuracy +0.118, *intended abstention −0.500* ⚠️
6. **결정 → 머지 + follow-up 이슈**. *부분* 수용 조건만 만족했음을 명시(false-positive 절반은 별도 issue로). 분류 → PR → 결과의 *불완전*까지 artifact로 남는다.

이 흐름의 어떤 단계도 *직관*에 의존하지 않는다. 매 단계가 코드/문서/평가 결과로 추적된다.

## 일반화 — taxonomy 생성을 위한 5가지 원칙

1. **카테고리 정의는 *코드 위치*를 가리켜야 한다.** "Retrieval issue" 같은 추상 라벨은 아무도 못 쓴다. `rag_core.py:1843` 처럼 행단위로 가리킨다.
2. **케이스 수를 카테고리 옆에 적는다.** "C6: 9/12" 라는 한 줄이 우선순위 그리드 절반을 결정한다.
3. ***증상* vs *원인* 카테고리를 구분한다.** 둘 다 분류하되 인과 관계를 명시(C6은 C1/C2/C4의 결과).
4. **수용 조건을 정량으로.** "절반 회복 + 3건 유지" 처럼 *측정 가능한* 형태. PR 머지 여부가 측정값으로 결정된다.
5. **분류 사이클을 평가 사이클에 묶는다.** 매 real-eval 후 taxonomy 갱신이 *PR 의무*가 되면 *문서가 stale*해지지 않는다.

## 분류라는 artifact의 부수 효과

taxonomy는 채용/리뷰어에게도 강한 신호다.

- *"버그를 어떻게 발견하나요?"* → real-eval n=21 + 6 카테고리 분류 (구체적 artifact 보유)
- *"우선순위는 어떻게 정하나요?"* → Impact × Effort 그리드 (문서로 박혀 있음)
- *"어떤 fix가 어떤 카테고리를 닫았나요?"* → PR #69 (C6), #71 (C4), #72 (C2) (매핑 추적 가능)

"체계적인 엔지니어링 규율"이라는 추상 단어가 *artifact로 환원*된다.

---

- 실패 분류 본문: [`docs/real-data-failure-taxonomy.md`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/real-data-failure-taxonomy.md)
- 매핑된 PR: [#69 C6](https://github.com/hskim-solv/BidMate-DocAgent/pull/88), [#71 C4](https://github.com/hskim-solv/BidMate-DocAgent/pull/115), [#72 C2](https://github.com/hskim-solv/BidMate-DocAgent/pull/116), [#73 C3 probe](https://github.com/hskim-solv/BidMate-DocAgent/pull/109)
- 관련 ADR: [0004 (verifier retry)](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0004-verifier-retry-policy.md), [0005 (eval split)](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0005-eval-split-public-synthetic-private-local.md)
- 이전 글: [Public synthetic + Private real, 두 평가 surface](../2026-05-public-synthetic-private-real/)

이 글로 Phase 4 블로그 시리즈가 완결됩니다. 시스템 전체 그림은 [1-page architecture deep-dive](../../architecture-deep-dive/)에서 한 페이지로 정리됩니다.
