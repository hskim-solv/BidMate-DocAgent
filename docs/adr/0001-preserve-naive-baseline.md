# 0001: agentic 파이프라인과 나란히 naive 기준선 유지

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: [`CLAUDE.md`](../../CLAUDE.md), [`docs/eval/ablation-results.md`](../eval/ablation-results.md), [`eval/config.yaml`](../../eval/config.yaml)

## TL;DR

- agentic 파이프라인 옆에 항상 `naive_baseline` 프리셋을 함께 유지·측정한다.
- 동일 케이스 side-by-side 비교 없이는 고급 컴포넌트의 품질 기여를 입증할 수 없다.
- CLI 기본값은 `naive_baseline` — 재현 경로가 가장 단순한 쪽이 default 이다.

## 배경

agentic 풀 파이프라인(메타데이터 우선 검색·재순위·검증기 retry·답변/인용 계약)은 컴포넌트마다 latency·복잡도·회귀 표면을 추가한다. 동일 케이스에 대한 side-by-side 비교가 없으면 추가 기제가 실제 품질을 올리는지 단지 실패 양상만 옮기는지 판별 불가다.

## 결정

프로젝트 lifetime 동안 `agentic_full` 옆에 실행 가능한 `naive_baseline` 프리셋을 유지한다. CLI 기본값은 `naive_baseline` 으로 두어 가장 재현 가능한 경로가 가장 단순한 경로가 되도록 한다. 두 프리셋 모두 [`eval/config.yaml`](../../eval/config.yaml) 의 분석 변형 run 으로 등장하며 매 eval 호출 시 측정된다.

knob: [`rag_core.py`](../../rag_core.py) 의 `pipeline_cli_choices()` 가 프리셋 목록의 단일 출처다. 여기서 `naive_baseline` 제거가 곧 이 ADR 재검토 신호다.

## 결과

**Wins**

- 모든 분석 변형 리포트에 기준선 컬럼이 포함 — 고급 컴포넌트의 품질 기여가 단언이 아닌 입증 가능
- 리뷰어는 agentic 스택을 몰라도 `make ask` 로 end-to-end 실행 가능
- agentic 회귀가 기준선보다 떨어지면 eval delta job 으로 자동 검출
- 이슈 triage 에 *"`naive_baseline` 에서도 재현되나?"* 라는 빠른 질문이 추가됨

**Costs**

- 두 코드 경로 유지 부담. CLI(`app.py`)·API(`api/main.py`)·`eval/run_eval.py` 모두 추상화 비용 부담
- README headline 메트릭에 baseline-vs-full gap 을 명시해야 함 — 아니면 시스템이 실제보다 약해 보임

## 기본 선택 재평가 기준 (ADR 0019, 통합)

ADR 0019 는 "default 유지" 결정을 재검토하는 패턴을 확립했다. 그 ADR 은 여기서 Superseded; 재오픈 조건만 load-bearing 으로 남는다.

**현재 default 유지**: 임베딩 모델로 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.

**재오픈 조건** (네 가지 모두 충족 시 default 교체):
1. `requirements.txt` 업그레이드로 `torch >= 2.6` + `huggingface-hub < 1.0` blocker 해소
2. `python3 scripts/run_embedding_ablation.py --models <miniLM> BAAI/bge-m3 intfloat/multilingual-e5-large-instruct` 가 public synthetic corpus(n=42) 에서 완주
3. 후보 중 최소 하나가 **`full` 파이프라인 기준** accuracy 또는 groundedness 에서 MiniLM 대비 ≥ +5pp 향상 + 비중첩 bootstrap 95% CI. (*`naive_baseline` 만의 향상은 카운트 X*)
4. 교체 후보를 문서화하는 후속 ADR

**Phase 1.3 업데이트 (issue #389, 2026-05-12):** 네 후보 모두 조건 1·2 충족 (BGE-M3 측정으로 마지막 gap 닫힘). 조건 3 미충족 — 5종 임베딩 전반에서 `0pp-on-full` 패턴 유지. 이 ADR 은 accepted 유지.

## 검토한 대안

- **agentic 출하 후 기준선 폐기.** Reject: 향후 변경에 *"추가 복잡도가 값을 하나?"* 질문에 답할 근거가 사라진다.
- **코드만 두고 eval 미실행.** Reject: 측정 안 하는 기준선은 썩는다. 측정 안 하면 보존 아님.
