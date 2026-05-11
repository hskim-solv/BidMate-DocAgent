---
layout: page
title: Extractive를 1급 baseline로 유지하는 이유
date: 2026-05-11
permalink: /blog/2026-05-extractive-baseline/
---

> 결론: LLM 합성이 더 화려한 결과를 만들어도 extractive baseline은 *기본값으로* 살려둔다.
> 새 기법은 baseline 옆에 *측정 가능한 ablation*으로만 추가한다. 통계가 효과를 확증하기 전까지 default를 바꾸지 않는다.

## 왜 이 결정이 필요했는가

BidMate-DocAgent는 RFP/제안요청서를 읽고 grounded answer를 생성하는 시스템이다. 초기 설계 시점부터 두 갈래가 있었다.

- **Extractive**: retrieved evidence chunk에서 claim을 *그대로 발췌*해 citation과 함께 반환한다. 외부 LLM을 호출하지 않으므로 결정적이고, hallucination이 구조적으로 불가능하다.
- **LLM 합성**: 같은 evidence를 LLM에 넘겨 자연스러운 산문 답변을 생성한다. 가독성과 추론 표현력이 좋다.

LLM 합성이 *읽는 맛*에서 우위인 것은 일찍 분명해졌다. 그렇다면 기본 파이프라인을 LLM 합성으로 두는 것이 자연스러워 보인다. 하지만 그렇게 하지 않았고, 그 이유와 측정 근거를 정리한다.

## 결정 — ADR 0001

[ADR 0001](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0001-preserve-naive-baseline.md)이 그 정책을 단 한 문장으로 잠근다.

> "Every advanced component adds latency, complexity, and a surface for regressions. Without a side-by-side comparison run on the same cases, it is impossible to tell whether the extra machinery actually improves quality on a given query slice — or just shifts the failure mode."

핵심은 두 가지다. **(1)** advanced 구성요소는 비용을 *동반*한다. **(2)** baseline 옆에 두지 않으면 *질 개선*인지 *실패 모드 이동*인지 알 수 없다.

## 코드 강제: 기본값이 곧 ADR

ADR은 문서지만, 결정을 강제하는 것은 코드다. 본 프로젝트에서 그 강제점은 두 곳이다.

```python
# rag_core.py
DEFAULT_PIPELINE = "naive_baseline"

def pipeline_cli_choices() -> list[str]:
    return ["naive_baseline", "agentic_full", "agentic_full_llm"]
```

```yaml
# eval/config.yaml
primary_run: naive_baseline
```

`pipeline_cli_choices()`에서 `naive_baseline`을 빼는 행위 자체가 ADR 0001을 revisit하겠다는 *명시적 신호*다. `eval/config.yaml`의 `primary_run`은 매 평가 호출마다 baseline 컬럼이 자동 생성되도록 한다 — "baseline은 코드에는 남아있는데 더 이상 측정하지 않는다"는 형태로 silently rot하는 길을 차단한다.

## 측정 증거: 정량으로 ADR을 지탱한다

n=42 공개 평가셋 + 1000-resample bootstrap 95% CI 측정 결과(README 성능표에서 발췌)는 두 가지 사실을 드러낸다.

| 지표 | naive_baseline | agentic_full | 해석 |
|---|---|---|---|
| Answer Accuracy | 0.844 ± 0.12 | 0.906 ± 0.12 | **CI 겹침** — n=42에서는 통계적으로 약함 |
| Citation Precision | 0.512 ± 0.12 | 0.905 ± 0.08 | **CI 분리** — metadata-first + verifier의 *진짜* 효용 |

이 두 줄을 한 번에 보여주는 게 baseline 유지의 핵심 가치다. *Accuracy만 보면* "n=42에서 통계 효과 없음"으로 결론을 내릴 위험이 있고, *citation precision까지 보면* "agentic pipeline은 grounding 정확도에서 통계적으로 우월"이라는 정직한 결론에 도달한다. baseline 컬럼이 없었다면 우리는 둘 중 한 결론만 보고 있었을 것이다.

같은 표에서 `no_verifier_retry` ablation은 accuracy는 동일(0.906)하지만 groundedness가 0.929 → 0.762 (-16.7pp)로 떨어진다. **무엇이 무엇 덕분에 작동하는지**는 baseline + ablation grid가 있어야 *비로소* 보인다.

## Real-data 회귀를 잡은 사례 — 이슈 #69

baseline의 가치는 통계 표에서만 드러나는 것이 아니다. 회귀를 *조기에* 잡는다.

이슈 [#69](https://github.com/hskim-solv/BidMate-DocAgent/pull/88) 은 verifier의 relaxed 단계에서 partial-topic grounding을 허용해 false abstention을 줄이는 변경이었다. 공개 synthetic 평가(n=42)에서는 *회귀 없음*으로 보였다 — accuracy 그대로, citation precision 그대로. 그런데 private real-data 측정에서 intended-abstention 케이스 4건 중 2건이 `insufficient` → `partial`로 잘못 분류되는 것이 잡혔다([실데이터 기록](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/private-100-doc-experiments.md)).

만약 synthetic 평가만 봤다면 이 회귀는 머지된 후 사용자가 production에서 발견했을 것이다. baseline + dual eval이 *같이* 작동했기 때문에 조기 검출이 가능했다. 이 사례는 다음 글([Public synthetic + Private real](./)) 에서 다룬다.

## ADR 0011: 새 기법은 *교체*가 아니라 *additive ablation*으로

2026년 LLM 합성 ablation을 추가하면서도 위 원칙은 깨지지 않았다. [ADR 0011](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0011-llm-synthesis-as-additive-ablation.md)은 이렇게 결정한다.

- 새 preset `agentic_full_llm` 추가 — `prompt_profile=llm_synthesis`
- 기본 CLI 값은 그대로 `naive_baseline`
- LLM이 evidence에 없는 chunk_id를 인용하면 결과 *거부* + extractive 렌더러로 fallback
- 공개 CI는 `stub` 백엔드(결정적, pass-through)로 zero-regression 계약 잠금

이 패턴이 ADR 0001의 *모양 그 자체*다. 새 기능을 추가하되 baseline은 그대로, 측정 가능한 ablation 한 줄로만 들어간다. 이렇게 하면 "advanced 옵션이 켜져서 production에 들어갔는데 정작 측정해보니 약했다"는 시나리오가 발생하지 않는다.

## 일반화 — 다른 프로젝트에 그대로 적용 가능한 4가지

1. **Baseline을 *기본값으로* 둔다.** "선택하면 켜지는" 옵션이 아니라 "끄지 않으면 켜지는" 디폴트. 옵션 선택을 안 해본 사용자도 baseline의 결과를 보게 된다.
2. **모든 advanced component는 ablation으로 들어간다.** 매 평가 호출에서 ablation 컬럼이 *자동 생성*되도록 평가 설정에 못 박는다.
3. **CI는 bootstrap CI까지 같이 본다.** `mean` 값 비교는 n=42에서 noise일 수 있다. CI 겹침 여부가 *진짜 효과*의 임계점이다.
4. **두 surface로 측정한다.** synthetic만으로는 못 잡는 회귀가 있다 — 다음 글의 주제.

## 다음 글에서

[Public synthetic + Private real, 두 평가 surface](./) — 두 surface를 어떻게 *코드 강제 경계*로 동시에 유지하는지, 그리고 이슈 #69 회귀가 *왜* 공개 평가에서 잡히지 않았는지의 메커니즘.

---

- 관련 ADR: [0001](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0001-preserve-naive-baseline.md), [0011](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0011-llm-synthesis-as-additive-ablation.md)
- 측정 표: [README §핵심 성능표](https://github.com/hskim-solv/BidMate-DocAgent#%ED%95%B5%EC%8B%AC-%EC%84%B1%EB%8A%A5%ED%91%9C-%EC%8B%A4%EC%B8%A1)
- 회귀 incident: [docs/private-100-doc-experiments.md](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/private-100-doc-experiments.md)
