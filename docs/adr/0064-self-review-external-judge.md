# ADR 0064 — Self-review external-LLM cross-rating judge

- Status: Proposed
- Date: 2026-05-19
- Authors: Hyunsoo Kim
- Related: ADR 0006 (real-data LLM-judge), ADR 0012 (synthetic stub-default judge), ADR 0016 (judge↔human agreement gate), ADR 0056 (rationality_judge measurement surface)
- Augments: red-team self-critique (private plan `~/.claude/plans/iterative-stirring-balloon.md`) — 자기참조 cycle (외부 anchor 0개) + 인프라:사용 15:1 + signal 6 외부 노출
- Issue: #1032

## Context

`/self-review-quarterly` skill 의 5축 collaboration 채점은 **LLM 판정자 = self-review 보고서 작성자** 의 폐쇄 루프. self-critique 에서 식별된 구조적 결함 4가지:

1. **자기참조 cycle (외부 anchor 0개)** — `feedback_portfolio_evaluation.md` → `project_portfolio_plan.md` → `feedback_q2_2026_collaboration_review.md` → `feedback_agent_utilization_strategy.md` → 다시 rubric 의 순환. 외부 검증 (peer review / 다른 판정자) 0개. rubric 결함이 cycle 마다 복제.
2. **인프라:사용 15:1** — self-review skill 도입 (PR #488) 후 15+ 인프라 PR (#499 / #597 / #604 / #723 / #729 / #745 / #747 / #748 / #771 / #783 / #885 / #1013 / #505 ...) 구축했지만 실제 실행 산물은 `docs/self-review/Q2-2026.md` **1개**. 측정 인프라 구축이 활동 목적이 됨 (Goodhart's law).
3. **판정 비재현성** — 같은 분기에 `docs/self-review/Q2-2026.md` (5축 1✓4△, 2026-05-13 관측) 와 메모리 `feedback_q2_2026_collaboration_review.md` (재진단 거버넌스ROI △→✓ 회복) 가 불일치. 같은 raw signal 에 LLM session/시점마다 다른 등급.
4. **signal 6 외부 노출 위험** — PR #505 가 "Claude 협업 측정" 을 채용 시그널로 포지셔닝. 외부 reviewer 가 코드를 열면 위 결함 발견 → signal 6 가 역효과.

해결 = **외부 LLM anchor** 도입으로 자기참조 cycle 을 깸. 단 paid-API "신규" 의존성을 만들지 않기 위해 **기존 LLM judge 인프라 재사용** (ADR 0006 / 0012 / 0056 의 `eval/judges/judge_common.build_openai_client` + stub-default 패턴).

## Decision

1. **신규 judge `eval/judges/self_review_judge.py`** — 기존 judge 패턴 (`synthetic_judge.py` / `rationality_judge.py`) 동일 구조.
   - 시그니처: `judge_self_review(stats: dict, operator_verdicts: dict[str, str] | None = None, *, backend: str = "stub") -> tuple[dict, dict]` — `(local, aggregate)`.
   - 입력: `scripts/claude-hooks/_self_review.py --quarter <Qx-YYYY> --emit-stats` 출력 stats.

2. **두 backend** (ADR 0012 stub-default 패턴):
   - **`stub`** — deterministic. SKILL.md 라인 127-140 임계값 표를 직접 적용 (보류했던 결정론 채점기를 흡수). 비용 0, CI 경로. **3 자기 통과 가드 포함**: `evidence_age_days < 1.0` 자동 △ (시계열 순환논증 차단) / `pretooluse_loadbearing_fires == 0` 자동 ✗ (Goodhart 침묵 차단) / `prs_evaluated < 10` 자동 △ (sample sanity).
   - **`openai_compatible`** — `build_openai_client()` + `call_openai_json()` 로 외부 LLM (`BIDMATE_JUDGE_MODEL`, vendor-agnostic) 에게 같은 rubric prompt 전달. opt-in (env 미설정 시 `RuntimeError`, stub-only 경로 무비용).

3. **Verdict 어휘 = `JUDGE_STATUSES` 재사용** — `✓ → supported`, `△ → partial`, `✗ → insufficient`. 기존 `judge_agreement.py` 의 `cohens_kappa` / `compute_agreement` 를 LABELS 매핑만으로 재사용.

4. **inter-rater agreement** — operator verdict (`docs/self-review/Qx-YYYY.md` 5축 파싱) vs judge verdict → `cohens_kappa`. aggregate = `{n, cohens_kappa, agreement_rate, confusion}`. 결과는 `reports/self_review_agreement/<Qx-YYYY>.json` (committable, body excerpt 0).

5. **신규 의존성 0** — `openai>=2.36.0` 은 이미 `requirements-dev.txt` (opt-in). production 미import. stub backend 는 stdlib only.

## Why these specific choices

| 결정 | 근거 |
|---|---|
| 외부 LLM anchor | 자기참조 cycle 을 깨는 방법은 다른 판정자. 사람 평가자는 섭외 의존 (dead-code 위험), 외부 LLM 은 자동 + 재현 |
| 기존 judge 인프라 재사용 | B 도구화의 "인프라 또 쌓기" (16:1) 함정 회피. 새 코드 50-80줄, 재사용 ~200줄 |
| stub = 결정론 채점기 흡수 | 보류한 결정론 채점기를 별도 PR 대신 judge 의 stub backend 로 — 단일 surface |
| `✓/△/✗ → JUDGE_STATUSES` 3값 | `judge_agreement.py` 의 kappa/rho 를 LABELS 매핑만으로 재사용 |
| opt-in openai backend | CLAUDE.md `Non-goals` "신규 paid-API 의존성" 준수 — 기존 opt-in dep 재사용, stub 이 기본 |

## Consequences

**긍정:**

- 자기참조 cycle 에 외부 판정자 1개 도입 — agreement κ < 0.6 (Cohen's "substantial" 미만, ADR 0016 기준) 시 rubric 자체 의심 신호.
- stub backend 가 결정론 채점기 역할 — LLM session noise 제거 + CI 재현성 100%.
- 기존 judge 패밀리 일관 — 유지보수 표면 단일.

**부정 / 위험:**

- stats 시점 불일치 — `docs/self-review/Q2-2026.md` (2026-05-13 관측) 와 현재 `--emit-stats` 재생성분이 그 사이 commit/memory 변화로 다를 수 있음. agreement 측정의 noise. prototype 한계로 명시.
- "LLM 이 LLM 채점" — same-family 편향. 다른 vendor 모델 권장하지만 완전한 외부성 (사람) 아님.
- agreement 가 인프라:사용 비율을 직접 고치지 않음 — 실행 규율 (분기 1회 실제 돌리기) 은 별도. 이 judge 도 안 돌리면 16:1 이 됨.

## Verification

<!-- verifies-key: eval/judges/self_review_judge.py:judge_self_review -->
<!-- verifies-key: tests/test_self_review_judge.py:test_stub_backend_deterministic -->
<!-- verifies-key: tests/test_self_review_judge.py:test_verdict_status_mapping -->
<!-- verifies-key: tests/test_self_review_judge.py:test_agreement_against_operator -->

후속 검증:

- Q2-2026 stats 로 stub + (사용자 key 설정 시) openai backend 1회 실행 → operator (1✓4△) 와 agreement.
- agreement κ < 0.6 → SKILL.md rubric 또는 임계값 재설계 (ADR 0016 substantial-agreement 기준 차용).

## Alternatives considered

1. **사람 평가자** — 가장 강한 외부 anchor (완전한 다른 판정자). 단 섭외 의존, 안 구해지면 aspirational dead-code. 외부 LLM 이 자동 + 재현 가능해 first step 으로 우선.
2. **결정론 채점기 단독 (외부 LLM 없이)** — LLM 주관 제거하나 자기참조 cycle 은 그대로 (rubric 본인 작성). 외부 anchor 아님. 본 ADR 의 stub backend 로 흡수.
3. **신규 Anthropic SDK 직접 추가** — paid-API 신규 의존성 (`Non-goals`). 기존 `openai_compatible` (vendor-agnostic) 가 `base_url` + `model` 지정으로 Anthropic 모델도 호출 가능.
