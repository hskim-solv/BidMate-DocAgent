# 0016: 실데이터 eval 의 calibration gate 로 Judge-Human Agreement

- **Status**: proposed
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [#169](https://github.com/hskim-solv/BidMate-DocAgent/issues/169), [ADR 0006](./0006-llm-judge-on-real-data-only.md)

## TL;DR

- `judge.agreement_with_verifier` (ADR 0006) 는 closed-loop 위험 — 동일 RAG·fixture·프롬프트로 검증기-평가자 공동 회귀 미감지.
- 사람이 30개 케이스 spot-label 한 CSV 로 Spearman ρ + Cohen κ 측정, **κ ≥ 0.6** 임계.
- κ 임계 미달 시 평가자 verdict 미신뢰 — 해당 run-window 의 신뢰 gate (CI 단계 아님).

## 배경

[ADR 0006](./0006-llm-judge-on-real-data-only.md) 이 실데이터 eval 표면에 `judge.agreement_with_verifier` — 즉 평가자 ↔ 결정론 검증기 agreement (`scripts/llm_judge.py`) — 보고하는 LLM 평가자 도입. 외부 코드 리뷰가 이를 *closed loop* 로 flag: 동일 RAG·fixture·평가자 프롬프트. 메트릭이 평가자 verdict 가 사람 reviewer verdict 와 일치하는지 검증 안 함 — 검증기·평가자 둘 다에 숨은 회귀가 드롭으로 표면화 안 됨.

closed-loop 위험은 private-100 표면에 구체적: 높은 `judge.agreement_with_verifier` (≈ 0.95) 가 검증기-사람 reviewer 간 spot-check 불일치와 양립. 출시된 메트릭은 둘 다 flag 안 함.

## 결정

**평가자 ↔ 사람 agreement** 를 LLM 평가자의 calibration gate 로. 메커니즘:

- 사람이 42-케이스 실데이터 표면의 stratified subset (20-30개) 을 `single_doc`, `comparison`, `follow_up`, `abstention` 쿼리 타입 가로질러 spot-label. 첫 iteration 은 pass 당 labeler 1명 충분 (inter-annotator κ deferred).
- [`eval/judge_agreement.py`](../../eval/judge_agreement.py) 가 side-by-side CSV (`case_id, judge_status, human_status`) 받아 **Spearman ρ** + **Cohen κ** + 클래스별 confusion matrix 보고. 상태 어휘는 ADR 0006 `judge_status` 와 동일 `(supported, partial, insufficient)` 3종.
- **임계: κ ≥ 0.6** ("substantial agreement", Landis & Koch 1977). κ 임계 미달 = 해당 pass 평가자 verdict 가 품질 신호로 미신뢰; reviewer 가 정제 프롬프트로 재실행하거나 직접 사람 리뷰로 폴백.
- calibration 은 해당 *run-window 에서 평가자 신뢰 gate*, CI 단계 아님 — 라벨이 희소 + 임계 판단이 자동화 아닌 reviewer 판단.

라벨 자체는 ADR 0005 **private** 측 (private RFP 케이스 사람 리뷰) 거주, git-ignored. 집계 κ + ρ 만 PR / 케이스 스터디 narrative 노출; 케이스별 CSV 는 `reports/real100/judge_agreement.local.csv` 잔류.

## 결과

- closed-loop 루프홀 봉쇄: 검증기-평가자 공동 회귀가 calibration pass 실행 시 미감지 통과 불가.
- 사람 labeling 비용 추가 (~30분 per 30-케이스 pass). 평가자 프롬프트·모델·검증기 정책 변경 시만 calibration 실행으로 완화.
- `(supported, partial, insufficient)` 를 agreement 축으로 lock — ADR 0006 과 동일 어휘. 다른 축 (인용 정밀도, 근거 완전성) 은 본 범위 외.
- 기존 [`eval/run_eval.py:compute_run_manifest`](../../eval/run_eval.py) 의 `commit_sha + config_sha256` 재현성 필드 의존 → labeled CSV 가 항상 특정 평가자 run 에 묶임. 해당 wiring 은 이미 in place (#169 deliverable, 사전 머지).

## 검토한 대안

- **ADR 0006 그대로.** Goodhart 위험 수용. 외부 리뷰가 closed loop 를 명시 flag + private-100 spot-check 가 우려 지지 → reject.
- **LLM 평가자를 다른 모델로 교체.** 비용 증가 + 사람 ground truth 대비 certify 안 함. 교체가 closed-loop 문제 제거 안 함 — loop 중심만 재배치.
- **Multi-labeler inter-annotator κ.** 더 강한 보장이나 첫 calibration pass 가 labeler 가용성에 deferred. follow-up 으로 연기 — agreement 메트릭 변경 없이 나중에 layer 가능.
