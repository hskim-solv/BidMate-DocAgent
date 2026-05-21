# Pre-registration — ADR 0064 openai_compatible cross-rating run

- Date: 2026-05-21
- Author: Hyunsoo Kim
- Related: ADR 0064 (self-review external-LLM cross-rating judge), PR #1087 (stub first-run), issue #1109
- Status: locked **before** any `openai_compatible` run

## Why pre-register

ADR 0064 의 stub first-run 은 operator(Q2) 대비 raw 0/5 / κ −0.389 를 냈다. 이 숫자는 세 가설로 갈린다:

- **(a) rubric underspecified** — 같은 SKILL.md 임계값의 두 충실한 구현이 갈린다 (operationalize 안 됨).
- **(b) stats 시점 드리프트** — stub 과 operator 가 시점 다른 evidence 를 채점, 애초에 같은 걸 안 봤다 (confound).
- **(c) operator self-grade inflation** — 자기채점이 부풀려졌고 mechanical 이 더 정직 (= 원 red-team 비판이 맞음).

세 가설은 후속 액션이 완전히 다르다 (rubric 손봐라 / 타이밍 고쳐라 / 자기채점 폐기). `openai_compatible` 결과를 **받은 뒤** 어느 가설인지 고르면 자기참조로 회귀한다. 그래서 결과 도착 *전에* 예측과 판별 규칙을 여기 박는다 — 명시된 prior 에 데이터를 떨어뜨려야 falsifiable 하다.

## 전제조건 (이게 먼저)

(b) 가 살아있는 한 (a)·(c) 를 오염시켜 분리 불가다. 따라서 **시점정합이 해석가능성의 전제조건**이며, 순서 `시점정합 stats → openai_compatible run` 은 불변이다. 드리프트 안 고치고 진짜 LLM 을 돌리면 두 번째 해석불가 숫자가 하나 더 생길 뿐.

- Q2 stats 는 복원 불가 (hook-fires.log·memory·git 이 그 사이 변함) → Q2 0/5 는 *교정 대상이 아니라 폐기 대상*.
- 해석 가능한 첫 실행 = operator + stub + openai 를 **동일한 현재 스냅샷 하나**에 동시 채점.

## 진단 비교 (무엇을 검정하나)

**openai-vs-stub, 동일 현재 스냅샷.** operator 는 끼우지 않는다 — operator 는 timepoint + 정체성 confound 가 둘 다 붙어 진단력이 약하다. stub(결정론 rubric 구현) 과 openai(LLM rubric 구현) 는 *같은 임계값 prompt 의 두 충실한 구현*이라, 둘이 갈리면 confound 없이 "rubric 이 안 잠긴다" 만 남는다.

## 예측 (점)

κ(openai, stub) ∈ **0.3–0.6 (moderate)**. perfect 아님, 음수 아님.

근거: 둘 다 같은 임계값 prompt → 날카로운 임계값 축(#3 fires>0 & ≥2 action, #4 numeric lag, #2 skip_rate band)은 수렴해야 정상. 모호/복합 축(#1 "Explore≥2 **AND** Read/session≤10" 의 AND + ratio 퍼지, #5 stub 이 5-B 만 구현)에서 갈릴 것.

## 판별 규칙 (FROZEN — 사후 이동 금지)

| κ(openai, stub) | 결론 | 후속 액션 |
|---|---|---|
| ≥ 0.7 | rubric operationalize 됨 → Q2 발산은 operator 고유 | **(c)** self-grade 가 outlier, mechanical 이 더 정직. 자기채점 신뢰성 재검토 |
| ≤ 0.4 | 같은 스냅샷 두 충실한 구현도 못 수렴 | **(a)** rubric underspecified → 임계값 sharpen (자기채점 폐기까지는 아님) |
| 0.4–0.6 | 축별 분해 | 날카로운 축 수렴 + 모호한 축 발산이면 (a) 가 특정 축에 국소화 |

## (a)/(c) 사이 lean (weak prior)

**(a) ~55% / (c) ~30% / mixed 15%.**

이유 — Q2 operator-vs-stub 발산이 **양방향**이었다 (operator 가 #1·#2 엔 관대, #4·#5 엔 엄격). 순수 inflation (c) 면 **단방향**이어야 한다. 양방향·축별 idiosyncratic 은 underspecification (a) 의 지문. 단 #1·#2 개별로는 operator 가 약한 시그널에 관대 → (c) 냄새도 있어 (c) 를 0 으로 두지 않는다.

**경고**: 이 lean 은 confound 된 Q2 데이터에서 뽑았으니 약하다 — 그래서 *prior* 지 결론이 아니다. fresh openai-vs-stub run (독립 데이터) 에 대고 떨어뜨려야 의미.

## Lock

데이터를 보고 위 임계값(0.4 / 0.7) 또는 lean 을 사후 이동하지 않는다. 이동이 필요하면 이 문서에 *추가 기록*으로 남기되, 원 prior 는 지우지 않는다.

## 이 문서가 pre-register 하지 *않는* 것

- 제시 순서 교정 (Q2-2026.json + ADR Verification 의 5행 매트릭스 head / κ 패밀리 각주 강등) — 별도 follow-up.
- 시점정합 stats 수집 메커니즘 (collector `evidence_age_days` emit + same-snapshot 재채점) — 별도 follow-up, 단 위 전제조건상 openai run 보다 먼저.

## Outcome (2026-05-21) — 예측 falsified

원 prior·Lock 절은 위 그대로 둔다 (규약: 사후 이동 금지, 추가 기록만).

- **실행**: `--backend openai_compatible`, model `gpt-4.1`. (gpt-5.x 계열 전체가 `temperature=0` 거부 → 판정자 코드의 temp=0 하드코딩과 비호환. temp=0 지원 최신 OpenAI 모델로 폴백. 별도 follow-up: `judge_common` temperature 설정화로 gpt-5.x 해금.)
- **스냅샷**: `ae08bc6c8ffb2f0e8514ace0bbb0596f7796fe4b46268834ef33640d38356ce2` (stub과 동일 = 시점정합 충족, (b) 통제).
- **결과**: openai-vs-stub **raw 5/5, κ = +1.000** (weighted linear/quadratic +1.0/+1.0, ρ +1.0). 산출: `reports/self_review_agreement/Q2-openai-vs-stub.json`. (gpt-4.1 은 프롬프트에 신호+임계값만 받음 — stub 판정 미노출, 독립 일치.)

**판정 (잠긴 규칙 적용):**

- 예측 κ ∈ 0.3–0.6 / lean (a) ~55% → **빗나감 (falsified).**
- κ = 1.0 ≥ 0.7 → **(c) 구간.** 결정론 stub 과 독립 외부 LLM 이 동일 스냅샷에서 판정 100% 일치 = 규칙(rubric)은 **operationalize 된다.** → **(a) underspecified 반증.** 따라서 Q2 operator-vs-stub 0/5 불일치는 규칙 모호성이 아니라 **operator 가 outlier** → **(c) 지지** (자기채점 deviation; 원 red-team 비판 뒷받침).

**남은 caveat:**

1. **n=5, 단일 스냅샷.** 완전 일치는 *이 스냅샷의 값들이 임계값 경계에서 멀어* 두 구현이 안 갈렸다는 것. 모든 신호값에서 무모호 증명 아님 — 경계 근처 값 재검정 필요.
2. **(c) ↔ (b) 완전 분리는 미완.** 이 실험은 openai·stub 를 같은 스냅샷에 돌려 (b) 를 통제했으므로 (a) 반증은 깨끗하다. 하지만 "operator 가 부풀렸다" 의 직접 증명은 **operator 가 동일 스냅샷을 *blind* (consensus 미노출) 재채점**해야 닫힌다. Q2 operator 는 복원불가 스냅샷 → 그 비교엔 (b) 잔존. → 남은 깨끗한 검정.
3. **gpt-4.1 (gpt-5.x 아님).** temp=0 제약. 단 *약한* 모델이 결정론 인코딩과 완전 일치한 것은 "규칙 무모호" 를 약화가 아니라 **강화**한다 (강한 모델이 더 갈릴 이유 없음).
