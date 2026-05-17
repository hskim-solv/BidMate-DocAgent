# 0012: 공개 합성 eval 에서 stub-기본 LLM 평가자

- **Status**: Superseded
- **Superseded by**: [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) § "LLM-judge gate layers"
- **Date**: 2026-05-11
- **Related**: [ADR 0006](./0006-llm-judge-on-real-data-only.md) 정제; [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) 백엔드 패턴 재사용; [ADR 0004](./0004-verifier-retry-policy.md) 재현성 보존
- **Deciders**: hskim

## TL;DR

- 공개 합성 표면에 stub-기본 LLM 평가자 추가 — CI 는 결정론 stub, opt-in 라이브 백엔드만 RAGAS 신호.
- ADR 0004 (재현성) + ADR 0005 (commit 경계) + ADR 0006 (실데이터 평가자) 모두 불변.
- 평가자는 두 번째 의견일 뿐 — `answer.status` 계약 (ADR 0003) 미변경.

## 배경

[ADR 0006](./0006-llm-judge-on-real-data-only.md) 이 **실데이터** eval 표면에 LLM 평가자를 도입하면서 공개 합성 버전은 다음 논리로 명시 reject:

> CI 에 feature flag 뒤로 평가자 배치. **Reject**: ADR 0004 재현성 논증이 공개 경로에 여전히 유효. PR 당 합성 케이스 토큰 소비도 정당화 불가 — 모델 없이 명확히 구분 가능.

라이브 평가자 호출에 대해서는 여전히 유효한 논리. 그러나 갭 존재: `docs/eval/ablation-results.md` 를 읽는 포트폴리오 reviewer 는 결정론 precision / recall / nDCG / `groundedness` (bool) 만 보고 그 외 없음. 공개 RAGAS 스타일 신호 부재 — faithfulness 도, answer-relevance 도 없음 — 모델 평가자가 도는 곳이 private `reports/real100/` 뿐이라.

[ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) 가 구조적으로 동일한 문제 해결: LLM 구동 분석 변형 (`agentic_full_llm`) 추가하되 `stub` 기본 백엔드로 공개 CI 결정론 유지. 라이브 백엔드는 env var opt-in. CI 가 네트워크 호출 안 하므로 ADR 0004 재현성 보존.

같은 패턴이 여기 적용. 합성 표면 **stub-기본** 평가자:

- CI 토큰 비용 0 (stub 가 검증기 미러링),
- 완전 재현 (결정론 stub + 결정론 집계),
- `make synthetic-judge` 를 라이브 백엔드로 돌리면 **on-demand** 로 RAGAS 스타일 신호 노출.

ADR 0006 가 reject 한 시나리오 ("CI 라이브 평가자") 는 여전히 reject. 본 ADR 이 도입한 시나리오 ("CI stub 평가자, 오프라인 opt-in 라이브") 는 구조적으로 다르며 ADR 0004 미위반.

## 결정

LLM-as-judge 가 **공개 합성 eval 표면** 에서 다음 조건으로 허용:

- **CI 는 stub 백엔드만.** `pr-eval.yml`, `make smoke`, `make eval`, `bash scripts/test.sh` 어디서도 라이브 LLM 호출 없음. Stub 모드는 결정론·네트워크 없음·run 간 byte-equal 집계.
- **라이브 백엔드는 오프라인 opt-in.** 실 faithfulness / answer-relevance 수치를 원하는 개발자가 `make eval` 후 `BIDMATE_SYNTHETIC_JUDGE_BACKEND=openai_compatible` + 공유 `BIDMATE_JUDGE_*` 자격으로 `make synthetic-judge` 실행. 결과 집계는 `reports/synthetic_judge.aggregate.json` 에 commit (ADR 0005 aggregate-only 경계). 케이스별 verdict 는 `reports/synthetic_judge.local.json` (git-ignored) 잔류.
- **평가자는 두 번째 의견, gate 아님.** 결정론 검증기의 `answer.status` 가 답변 시점 계약 유지 (ADR 0003). 합성 평가자는 평가 집계에만 기여; `run_rag_query` 반환값에 영향 없음.

### 계약

- 평가자가 `eval_summary.json` 케이스별 소비: `(query, answer.summary, evidence[:3].text, answer_status)`.
- 케이스별 출력:
  ```json
  {
    "judge_status": "supported" | "partial" | "insufficient",
    "judge_grounded": true | false,
    "faithfulness": 0.0,
    "answer_relevance": 0.0,
    "judge_reason_short": "≤ 200 chars"
  }
  ```
- Commit 가능 집계 (`reports/synthetic_judge.aggregate.json`):
  - `n`, `faithfulness_mean`, `answer_relevance_mean`, `grounded_rate`, **`agreement_with_verifier`**, `status_distribution`.
  - `by_query_type` 슬라이스에 동일 shape.
- 케이스별 `judge_reason_short`, raw 프롬프트·응답은 로컬 (ADR 0005 commit 경계).

### 백엔드 pluggability

`eval/synthetic_judge.py` 가 `scripts/llm_judge.py` 패턴 미러링:

- `stub` (기본) — 결정론. 구성상 `agreement_with_verifier == 1.0`. status 유래 fixture 점수 (예: supported → faithfulness 0.85) 가 downstream consumer 용 집계 스키마 채움 — 실 신호 주장 아님.
- `openai_compatible` — 일반 OpenAI 호환 엔드포인트. `BIDMATE_JUDGE_API_KEY`, `BIDMATE_JUDGE_MODEL`, 선택적 `BIDMATE_JUDGE_BASE_URL` 읽음 (실데이터 평가자와 공유 — 동일 모델이 두 표면 served).
- 백엔드 선택은 `BIDMATE_SYNTHETIC_JUDGE_BACKEND` (실데이터 `BIDMATE_JUDGE_BACKEND` 와 독립).

### 주기

공개 CI 는 라이브 신호 침묵 — stub 집계는 결정론 plumbing 만. 실 신호 원하는 개발자가 `make synthetic-judge` 를 라이브 백엔드로 수동 실행 + 결과 commit 된 집계 diff 를 PR 에 첨부, reviewer 가 `README.md` / `docs/eval/ablation-results.md` 렌더 표 확인.

## 결과

**Wins**

- 공개 reviewer 가 결정론 메트릭과 함께 RAGAS 스타일 faithfulness / answer-relevance 신호를 commit 된 집계 스냅샷에서 확인.
- ADR 0004 유지: CI 라이브 LLM 호출 없음, 모든 run 재현 가능·무료.
- ADR 0005 유지: 케이스별 평가자 텍스트는 commit 경계 넘지 않음.
- ADR 0006 유지: 실데이터 평가자 불변 (`scripts/llm_judge.py` 리팩터 없음).
- [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) 백엔드 dispatch 패턴 재사용 (stub vs openai_compatible) — 코드베이스 전반 "LLM 추가 방법" 일관 관용구.

**Costs**

- commit 집계는 검색·검증기 변경 후 재렌더 없으면 stale. 수동 주기로 완화 — 집계는 CI gate 가 아닌 스냅샷이므로 staleness 는 회귀가 아니라 "이 수치는 commit X 부터" 형태로 나타남.
- stub 모드 집계 값 (supported 시 faithfulness 0.85 등) 은 *실* 신호 아님. README 가 stub 모드 (plumbing) 와 라이브 run (실 신호) 출처를 명시.
- ADR 0005 allowlist 파일 1개 추가 (`reports/synthetic_judge.aggregate.json`). `reports/external_baselines.json` (ADR 0009) 기존 예외 미러링.

**Constraints (불변)**

- 공개 CI 는 외부 LLM 호출 금지. CI 가 `BIDMATE_SYNTHETIC_JUDGE_BACKEND=stub` 기본 + `pr-eval.yml` / `make smoke` 에서 `make synthetic-judge` 누락으로 컨벤션 강제.
- Aggregate-only commit 경계는 `judge_synthetic_summary` API 가 강제 — 집계 dict 만 commit 경로에 `write_text`; 케이스별 로컬 페이로드는 git-ignored 경로.

## 검토한 대안

- **공개 CI 에 feature flag 뒤 라이브 평가자.** ADR 0006 과 같은 이유로 reject: ADR 0004 재현성 + 대부분 명확 구분 가능한 케이스에 PR 당 토큰 소비 부당.
- **결정론 의미 유사도 (예: 임베딩 코사인).** Reject: *주제 관련성* 측정 — 옳은 어휘를 쓴 환각 요약과 충실한 요약을 구분 불가.
- **`scripts/llm_judge.py` 를 두 표면 처리하도록 리팩터.** Reject: 실데이터 평가자 (ADR 0006 commit 경계의 load-bearing) 변경의 blast radius 2배. 두 평가자가 ~100줄 프롬프트 + 백엔드 dispatch 공유; 중복이 더 저렴. 세 번째 평가자 표면 등장 시 revisit + `eval/judge_common.py` 추출.
- **`faithfulness` 만 보고; `answer_relevance` skip.** Reject: RAGAS 스타일 2-메트릭 쌍 (faithfulness + answer relevance) 이 reviewer 기대값 + 한 프롬프트로 둘 다 받는 한계 비용 0.
