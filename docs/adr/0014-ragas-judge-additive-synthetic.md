# 0014: 합성 표면에 RAGAS 스타일 LLM 평가자를 추가 enrichment 로

- **Status**: Superseded
- **Superseded by**: [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) § "LLM-judge gate layers"
- **Date**: 2026-05-11
- **Related**: [ADR 0006](./0006-llm-judge-on-real-data-only.md) 정제; [ADR 0001](./0001-preserve-naive-baseline.md), [ADR 0003](./0003-structured-answer-citation-contract.md), [ADR 0004](./0004-verifier-retry-policy.md), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) 보존; [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) 백엔드 패턴 재사용
- **Deciders**: hskim

## TL;DR

- 공개 합성 표면에 RAGAS 4 메트릭 (faithfulness / answer_relevance / context_precision / context_recall) 평가자를 opt-in enrichment 로 추가.
- 기본 `stub`, 라이브 백엔드는 토큰 budget cap + 콘텐츠 해시 캐싱으로 비용 bound.
- ADR 0006 gate-only 결정 보존; 본 평가자는 enrichment 메트릭만 기여, 상태 결정 미참여.

## 배경

[ADR 0006](./0006-llm-judge-on-real-data-only.md) 이 LLM-as-judge 를 세 가지 유효 사유 (외부 dep, 쿼리당 토큰 비용, 공개 CI 경로의 재현성 난이도) 로 실데이터 eval 표면에 한정. *gating* 메트릭에는 여전히 유효. 그러나 시니어 reviewer 에게 보이는 갭:

> "공개 합성 accuracy=0.906 수치는 검색-grounded 이나 LLM-graded 아님. reviewer 의 첫 본능은 *judged by what?*"

결정론 검증기는 **grounding 엄밀성** (claim-인용 정합, 근거 coverage, 형식 준수) 에는 답하지만 RAGAS 스타일 read 가 표면화하는 다차원 품질 질문 미답:

1. **Faithfulness** — 답변 claim 이 인용된 근거에 실제 등장하는가?
2. **Answer relevance** — 답변이 쿼리를 다루는가, 드리프트 하는가?
3. **Context precision** — 검색된 근거의 몇 % 가 on-topic 인가?
4. **Context recall** — 근거가 답변 필요분을 cover 하는가?

이들은 *enrichment* 신호이지 gate 아님. 시니어 리뷰는 결정론 수치와 함께 보길 원함; 어떤 것도 대체하지 않음.

[ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) 의 같은 형태 (LLM 합성을 추가 분석 변형, 추출형 기준선 미대체) 가 여기 적용: **RAGAS 평가자를 기존 표면 옆에 추가, 기존 메트릭 미대체, 기본 CI 는 결정론·무료.**

## 결정

RAGAS 스타일 LLM 평가자가 **공개 합성 eval 표면** 의 **opt-in 추가 enrichment** 로 허용:

- **기본 off.** `BIDMATE_JUDGE_BACKEND=stub` 가 CI 기본. Stub 은 결정론·네트워크 없음·비용 0, 공개 CI workflow (`pr-eval.yml`) 가 평가자 호출 안 함. ADR 0004 재현성 유지.
- **Opt-in 유료 모드.** `BIDMATE_JUDGE_BACKEND=openai_compatible` (또는 `anthropic`) 가 케이스별 프롬프트로 RAGAS 4 점수를 JSON 응답 1회로 요구. `make smoke-with-judge` 또는 `python3 eval/llm_judge.py` 로 수동 호출. 자동 CI 호출 없음.
- **콘텐츠 해시 캐싱.** 각 `(query, summary, evidence[:3])` SHA256 해시가 `reports/judge_cache/` (gitignored) 캐시 파일로 매핑. 입력 불변 재실행은 토큰 비용 0. 캐시 무효화는 재해싱; 기존 입출력 discipline 으로 충분.
- **토큰 budget cap.** `BIDMATE_JUDGE_TOKEN_BUDGET` (기본 200,000 입력 토큰 추정·전체 eval run 당). 도달 시 무제한 비용 누적 대신 continue refuse. 사용자가 env var 의도 override.

### 출력 스키마

케이스별 verdict (로컬, gitignored):

```json
{
  "id": "case_id",
  "faithfulness": 0.0–1.0,
  "answer_relevance": 0.0–1.0,
  "context_precision": 0.0–1.0,
  "context_recall": 0.0–1.0,
  "reason_short": "string, ≤ 200 chars"
}
```

Commit 가능 집계 (`reports/eval_summary.json` 의 `judge_ragas` 최상단):

```json
{
  "faithfulness": float,
  "answer_relevance": float,
  "context_precision": float,
  "context_recall": float,
  "n": int,
  "ci": { "<metric>": { "mean": ..., "ci_lo": ..., "ci_hi": ... } }
}
```

집계는 메트릭별 평균 ± 95% bootstrap CI, [`eval/bootstrap.py`](../../eval/bootstrap.py) 재사용. 케이스별 페이로드는 commit 경계 미통과; `scripts/run_real_eval_delta.py:SAFE_TOPLEVEL_KEYS` 가 `judge_ragas` 명시 sub-key allowlist whitelisting.

### ADR 0006 정제, supersede 아님

ADR 0006 gate-only 제한 유지: 결정론 검증기가 `answer.status` (supported / partial / insufficient) 소스 of truth 유지. RAGAS 평가자는 *enrichment 메트릭* 만 기여, 상태 결정 미참여. 두 표면은 다른 epistemic 목적:

- **ADR 0006 평가자** (실데이터, status 스타일): "모델의 근거 read 가 검증기 호출과 일치하는가?" — `agreement_with_verifier` 가 헤드라인.
- **ADR 0014 평가자** (합성, RAGAS 스타일): "답변이 4 품질 차원에서 어떻게 점수받는가?" — 각각 CI 동반 4 수치 점수.

동일 `scripts/llm_judge.py` 백엔드 인프라 (stub / openai_compatible / anthropic) 공존하되 다른 최상위 키 (`judge` ADR 0006, `judge_ragas` ADR 0014) 기록.

## 결과

**Wins**

- 공개 합성 수치가 동일 eval 셋에 *학습 안 된* 두 번째 의견 신호 획득. reviewer 의 "judged by what?" 에 구체 답.
- ADR 0006 과 동일 백엔드 관용구 — 새 auth flow·env var 없음 (`BIDMATE_JUDGE_API_KEY`, `BIDMATE_JUDGE_MODEL`, 선택 `BIDMATE_JUDGE_BASE_URL` 기존 존재).
- 캐싱으로 동일 케이스 셋에 대한 PR 간 재실행 무료 — opt-in 비용은 최초 실행 + 프롬프트 변경에 bound.
- ADR 0001 / 0003 / 0004 / 0005 불변식 무변경.

**Costs**

- opt-in 모드 사용 시 run 당 토큰 비용. budget cap (~$3-5 per 전체 eval run, Sonnet 4.6 + prompt cache, #164 추정) bound. budget enforcement 는 경고 아닌 hard refuse.
- 사용자가 알 env var 조합 1개 추가. stub 기본 + `make smoke-with-judge` 워크플로 오케스트레이션으로 완화.
- opt-in run 평가자 outage 시 해당 PR 의 RAGAS 메트릭 미계산. 결정론 eval 은 완료; `judge_ragas` 블록만 부재.

**Constraints (이전 ADR 들로부터 불변)**

- 공개 CI 는 외부 LLM 호출 금지. 컨벤션 강제: `pr-eval.yml` 가 평가자 호출 안 함 + stub 가 그 외 어디든 기본.
- Aggregate-only commit 경계 유지. `reports/judge_cache/` 케이스별 평가자 텍스트는 gitignored. 집계 sub-key 는 `scripts/run_real_eval_delta.py` 가 명시 allowlist 추출.

## 검토한 대안

- **RAGAS 직접 사용 (upstream 라이브러리).** Reject: 유료 framework dep 추가 + 어떤 모델 호출할지에 대한 자체 의견. 4 메트릭은 잘 정의됨; 50줄 백엔드 중립 구현이 프롬프트·캐싱·budget enforcement 완전 제어 + 동일 신호.
- **4 메트릭 결정론 계산 (토큰 overlap / cosine).** Reject: 기존 groundedness / citation_precision 의 fancier 버전. 핵심은 *다른 모델의 read* — 평가 받는 동일 검색 scaffolding 으로 메트릭 생성 시 동일 Goodhart 우려 (#169) 적용.
- **CI 를 RAGAS threshold 로 gate.** ADR 0006 과 같은 사유로 reject: 재현성·비용·외부 dep on *공개* 경로. 향후 강화는 raw RAGAS gate 아닌 Judge↔Human agreement floor (#169 / ADR 0013-pending) 필요.
- **기존 `judge` 최상위 키 합치기.** Reject: 스키마 차이 (status 스타일 vs 4 수치) + 표면 차이 (실데이터 vs 합성). 별도 최상위 키 공존이 privacy 경계 audit 더 쉬움.
