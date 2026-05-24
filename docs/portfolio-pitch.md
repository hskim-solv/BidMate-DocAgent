# 면접에서 이 프로젝트를 설명하는 법

리뷰어/면접관에게 30초 ~ 2분 안에 이 프로젝트의 시니어 시그널을 전달하기 위한 피치 모음. 수치는 모두 README 메트릭 표(자동 생성, source of truth)와 ADR 에서 인용하며, 새 숫자를 만들지 않는다.

## 30초 피치

> 이 프로젝트에서 저는 RAG 파이프라인을 단순 구현한 것이 아니라, RFP 문서에서 실제로 발생하는 **검색 실패 · 근거 부족 · 비교 질의 편향을 failure mode 로 정의**하고, 이를 **baseline / ablation / eval / CI 로 검증 가능한 시스템**으로 만들었습니다.

핵심 한 문장: "RAG 데모를 만든 게 아니라, RFP 도메인의 실패 모드를 정의하고 그것을 막는 평가·CI·provenance 게이트를 소유했습니다."

## 3개 핵심 시그널

### 1. Baseline preservation (기준선 보존)

- `naive_baseline` 을 byte-identical 로 보존해 모든 개선을 *additive ablation* 으로만 측정한다. 새 기능이 기준선을 대체하지 않으므로, 어떤 변경이 무엇을 얼마나 바꿨는지 항상 분리 측정 가능하다.
- 근거: [ADR 0001](adr/0001-preserve-naive-baseline.md). `eval/config.yaml` 의 `naive_baseline` preset 은 제거 금지(거버넌스 규칙).
- 면접 답변: "개선을 자랑하기 전에, *비교 기준이 흔들리지 않는다*는 걸 먼저 보장했습니다. 그래서 모든 ablation 이 기준선 대비 정직한 delta 입니다."

### 2. Failure-mode-driven design (실패 모드 주도 설계)

- comparison starvation · metadata ambiguity · unsupported-question abstention · follow-up 문맥 소실 · citation drift 5개 실패 모드를 명시하고, 각각에 코드 경로 + 회귀 테스트로 대응한다.
- 근거: [실패 모드 케이스 스터디](case-studies/failure-modes.md) (정본 taxonomy [`docs/real-data/real-data-failure-taxonomy.md`](real-data/real-data-failure-taxonomy.md) C1–C6 대응).
- 면접 답변: "기능부터 쌓은 게 아니라, *이 도메인에서 무엇이 깨지는가*를 먼저 분류하고 거기서 설계를 역산했습니다. 예: 비교 질의에서 한쪽 문서가 검색 슬롯을 독식하는 starvation 을 발견하고 balanced top-k 로 막았습니다."

### 3. Eval/CI regression prevention (평가·CI 회귀 차단)

- PR 마다 회귀 게이트가 돌고, failure-rate ceiling 이 ratchet(단조 강화)되어 품질 후퇴를 머지 전에 차단한다. 공개 fixture smoke / 비공개 real-eval 을 분리해 서로 다른 목적(품질 회귀 감시 vs 난이도 상한 탐침)으로 운용한다.
- 근거: [pr-eval.yml](../.github/workflows/pr-eval.yml) · [ADR 0062](adr/0062-failure-rate-regression-contract.md) (회귀 ceiling 계약) · [ADR 0005](adr/0005-eval-split-public-synthetic-private-local.md) (eval 분리).
- 면접 답변: "측정은 일회성이 아니라 *상시 게이트*입니다. 회귀가 들어오면 CI 가 막고, 실패율 상한은 내려가기만 합니다."

## 안전성/품질 trade-off 를 정직하게 설명하기

면접관이 "그런데 `agentic_full` 이 raw accuracy 는 더 낮네요?"라고 물으면:

> "맞습니다. 그건 *실패한 최적화가 아니라 의도된 trade-off* 입니다. `agentic_full` 은 답변율을 극대화하도록 튜닝한 게 아니라, citation precision **+18.0pp** 와 abstention accuracy **+57.1pp** 를 얻는 safety-oriented 파이프라인입니다. RFP 의사결정 맥락에서는 근거 없는 답변보다 근거 있는 보류가 더 안전하니까요. 그래서 메트릭은 하나의 평탄한 aggregate report 가 아니라 slice 별로 읽어야 합니다."

real-eval hardcase(n=221, accuracy 16.10%)를 물으면:

> "그건 제품 성공 지표가 아니라 hardcase 스트레스 테스트입니다. 일부러 어려운 케이스로 실패 모드를 노출하고 ablation 변별력을 시험하는 용도라, 낮은 수치를 숨기지 않고 엔지니어링 증거로 드러냅니다." ([ADR 0052](adr/0052-real-eval-hardcase-expansion-to-200.md))

## STAR 정리 (핵심 기여 1건)

- **Situation**: 한국 공공/B2B RFP 는 길고 noisy 하며, 비교 질의에서 기관 문서 간 균형 잡힌 근거 수집이 어렵다.
- **Task**: 비교 질의에서 한쪽 문서가 누락되지 않도록 검색 결과를 균형화하되, 단일 문서 질의 비용은 늘리지 않는다.
- **Action**: 비교 target 별 `min_per_target ≥ 1` 을 보장하는 comparison-aware balanced top-k 를 설계·구현하고, asymmetric corpus / disabled / single-doc no-op 을 회귀 테스트로 고정했다 ([`tests/test_fuzzy_retrieval.py`](../tests/test_fuzzy_retrieval.py)).
- **Result**: 비교 질의에서 양쪽 기관이 모두 인용되는 동작을 구조적으로 보장(README 5초 비주얼 훅에서 재현). 일반 RAG 튜토리얼에 없는 도메인 특화 결정을 발견→설계→검증까지 소유했다.

> 추가 STAR ammo · slice 별 수치 분해: [`docs/rag-challenges-solved.md`](rag-challenges-solved.md) · [`docs/performance-evolution.md`](performance-evolution.md).
