# 0005: Eval 분리 — public synthetic vs private local

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: [`eval/config.yaml`](../../eval/config.yaml), [`eval/real_config.example.yaml`](../../eval/real_config.example.yaml), [`docs/real-data/private-100-doc-experiments.md`](../real-data/private-100-doc-experiments.md), [`docs/real-data/private-hardcase-benchmark.md`](../real-data/private-hardcase-benchmark.md), [`docs/real-data/real-data-failure-taxonomy.md`](../real-data/real-data-failure-taxonomy.md)

## TL;DR

- 공개 synthetic + 비공개 local 두 eval 표면을 나란히 유지한다.
- 공개 표면이 README 메트릭 anchor, 비공개 표면이 실패 taxonomy 근거.
- 어떤 새 eval 표면도 한쪽을 선택 — public-redistributable 또는 strictly local.

## 배경

평가에 상반된 두 요구가 있다:

- **공개 재현성.** repo clone 만으로 secret·paid API·재배포 불가 데이터 없이 의미 있는 eval 실행 가능해야. README 메트릭은 공개 artifact 로 뒷받침되어야
- **정직한 신호.** synthetic RFP 는 실제 조달 문서의 실패 모드(모호 메타데이터·스캔 PDF·distribution 외 phrasing)를 자극 안 함. 실패 taxonomy 의 실제 출처는 real-data eval

단일 eval set 으로 양쪽 다 못한다. 공개된 것은 그 자체로 최적화 대상이 되고, 공개 못 하는 것은 공개 주장의 anchor 가 될 수 없다.

## 결정

두 eval 표면을 side-by-side 유지:

- **공개 synthetic** (`eval/config.yaml`, `data/raw/`). 커밋, 매 PR 에서 CI 실행 가능(`make eval`, eval delta workflow), README 메트릭 구동. *"시스템이 여전히 주장한 계약을 출하 중인가?"* 의 단일 출처. 오프라인 실행 위해 hashing 임베딩 백엔드 사용
- **비공개 local** (`eval/real_config.example.yaml` 가 scaffold; 실제 config 와 corpus 는 git 외부). 실제 조달 문서에서 로컬 실행. *"어떤 실패 모드가 real 인가?"* 의 단일 출처. 출력(`reports/real100/`)·입력(`data/files/`, `data/data_list.csv`, 로컬 config)은 `.gitignore`d

경계는 example 파일 컨벤션(`*.example.yaml`) + `.gitignore` 가 강제. 모든 새 eval 표면은 한쪽을 선택 — public-redistributable 또는 strictly local.

## 결과

**Wins**

- CI eval delta job(`.github/workflows/pr-eval.yml`)이 자기가 무엇을 cover 하고 안 하는지 정직 — 공개 synthetic 표면만 측정
- 실패 taxonomy 와 우선순위 backlog 가 문서 leak 없이 real-data 관찰에 ground 가능
- 비밀유지가 파일별 판단이 아니라 컨벤션화

**Costs**

- config 두 벌 유지 부담. case schema 진화(필수 필드 추가·메트릭 키 추가) 시 양쪽 동시 갱신 필요 — 안 그러면 비공개 표면 silent drift
- README 메트릭이 real-data 가 보는 실패율을 under-report. 정직하게 메우려면 aggregate-delta 리포트(`docs/real-data/private-100-doc-experiments.md`) 필요
- reviewer 는 비공개 표면 숫자 재현 불가. aggregate/delta 리포트 + 공개 표면 재현성을 신뢰해야

## LLM-judge gate 레이어 (ADR 0006 / 0012 / 0014, 통합)

세 연속 ADR 이 두 eval split 위에 LLM-judge 표면을 쌓았다. 그 ADR 들은 여기서 Superseded; 결정은 유효.

**Gate 1 — real-data only (ADR 0006, accepted)**  
LLM-judge 는 `eval/real_config.local.yaml` run 에만 허용. 출력: 케이스별 `judge.local.json` (gitignored) + aggregate `judge.agreement_with_verifier` (committable). 백엔드: `BIDMATE_JUDGE_BACKEND` — `stub` | `openai_compatible`. deterministic verifier 가 게이트, judge 는 second opinion.

**Gate 2 — public synthetic stub-default (ADR 0012, accepted)**  
LLM-judge 는 `eval/config.yaml` 에 허용 — 단 CI 는 stub-only(`BIDMATE_SYNTHETIC_JUDGE_BACKEND=stub`, deterministic, network-free). live backend 는 `make synthetic-judge` 로 offline opt-in. committable aggregate: `reports/synthetic_judge.aggregate.json` (ADR 0005 allowlist). `faithfulness`·`answer_relevance`·`agreement_with_verifier` 추가.

**Gate 3 — RAGAS-style enrichment (ADR 0014, accepted)**  
4-metric RAGAS-style judge(`faithfulness`·`answer_relevance`·`context_precision`·`context_recall`)를 synthetic 표면에 additive 강화. content hash 캐시(`reports/judge_cache/`, gitignored). `BIDMATE_JUDGE_TOKEN_BUDGET` 로 hard token-budget cap. 케이스별 verdict 는 local 유지, `eval_summary.json:judge_ragas` aggregate 는 committable.

**공유 invariant (불변):** ADR 0004 재현성(CI 는 live LLM 호출 절대 X); ADR 0003 답변 계약(judge 는 `answer.status` 에 영향 절대 X); ADR 0005 commit 경계(케이스별 텍스트는 local 유지).

## 검토한 대안

- **공개만.** Reject: synthetic 데이터가 중요한 실패 모드 은닉; 잘못된 대상을 최적화하게 됨
- **비공개만.** Reject: 공개할 재현 가능한 것 없음; reviewer 가 주장 검증 불가
- **단일 config + 비공개 case 확장을 조건부 로드.** 고려. Reject: 두 표면이 다른 목적(PR gating vs real-data taxonomy)이고, 섞으면 둘 다 리뷰 방어 난도 ↑
