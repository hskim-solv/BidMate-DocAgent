# 0046: Out-of-distribution evaluation 도메인 — 한국어 법률 계약서

- **Status**: accepted
- **Date**: 2026-05-15
- **Related**: [ADR 0005](./0005-eval-split-public-synthetic-private-local.md)
  · [ADR 0018](./0018-korean-public-rag-bench.md) · [ADR 0002](./0002-metadata-first-retrieval.md)
  · issue #822
- **Deciders**: hskim

## TL;DR

- 한국어 법률 계약서를 OOD eval 도메인으로 선정 (RFP 와 구조 인접, 공개 데이터 가용)
- 최소 바: `accuracy(ood_legal-full) ≥ 0.6 × accuracy(rfp-full)`
- 평가 표면만 추가, 제품 범위 확장 아님 — 일반화 체크

## 배경

현재 평가 표면 두 레이어:

| Surface | Source | n | Domain |
|---------|--------|---|--------|
| 공개 합성 | [`eval/config.yaml`](../../eval/config.yaml) | ~30 | 한국어 RFP (합성) |
| 비공개 real-data | `eval/real_config.local.yaml` (gitignored, ADR 0005) | n=21 → n≥30 (ADR 0044) | 한국어 RFP (비공개) |
| 보조 | ADR 0018 통한 KorQuAD / 뉴스 QA | 가변 | 일반 한국어 위키 / 뉴스 |

두 RFP 표면 모두 같은 lexicon, 같은 메타데이터 family (발주기관 / 사업명 / 공고번호 / 기간), 같은 비교 쿼리 패턴 공유. ADR 0018 의 한국어 공개 RAG bench 는 *일반 한국어* 테스트지만 문서 구조 (백과/뉴스) 가 RFP 와 질적으로 다름 — tokenizer / embedding 품질 stress 지, BidMate 파이프라인이 설계된 **구조적 검색 패턴** (메타데이터 우선, 비교 인식 균형 top-k, 검증기 topic 근거) 아님.

reviewer 가 *"이 숫자들이 RFP *처럼 보이는* 다른 도메인에서 유지되는가?"* 물으면 답 없음. 유일한 공개 신호는 ADR 0018 의 일반 언어 bench, 정보 제공하기엔 구조적으로 너무 멀음.

이는 senior-portfolio 갭 — **단일 도메인 정확도는 1차원 신호**. 본 ADR 은 RFP 와 구조 인접하지만 비공개 코퍼스 밖에서 가져온 도메인 추가로 갭을 닫는다.

## 결정

OOD 평가 도메인은 **한국어 법률 계약서** (서비스 ToS, 표준 계약, NDA, 정부 모델 약관). 세 가지 이유, 가중치 순:

1. **RFP 와 구조 인접.** 두 도메인 공유:
   - 섹션 / 조항 / 하위 조항 계층 (제 N 조, 제 N 항)
   - Named-party 메타데이터 (갑·을 vs 발주기관·수행기관)
   - 날짜 / 금액 / 기간 필드
   - 비교 쿼리 자연스러움 ("갑과 을의 책임 차이", "표준 약관 대비 추가 조항")

   메타데이터 우선 검색 (ADR 0002) 과 비교 균형 top-k 전략이 *transfer* 해야 함 — 실제로 그러는지 측정이 핵심.

2. **공개 데이터 가용.** 한국어 법률 계약서는 법무부, 공정거래위원회 표준약관 시리즈, 정부24, 국가법령정보센터에서 public domain 으로 공개. 합성 변형 생성이 비공개 RFP 자료 미터치로 가능. ADR 0005 커밋 경계 보존.

3. **기존 공개 bench 와 직교.** ADR 0018 (한국어 공개 RAG bench) 가 범용 한국어 텍스트 cover. *또 다른* 일반 언어 bench 추가는 새것 측정 안 함. 법률 계약은 RFP 와 같은 검색 primitive (named-entity / 메타데이터 / 번호 매긴 섹션) pull 하지만 다른 vocabulary 라 vocabulary 단독 귀속 정확도 drop 이 정보 제공.

### 구체 범위 (계획, E2-E4 에서 land)

| PR | Output |
|----|--------|
| E2 | `data/ood_synthetic_legal/` 의 50개 합성 법률 계약 문서; single_doc / 비교 / 추출 / 보류 cover 하는 per-doc 질문 |
| E3 | `eval/config.yaml`: 새 프리셋 `ood_legal` (법률 코퍼스 대비 `agentic_full` 분석 변형 set mirror); `eval/run_ood_eval.py` 실행; `eval/synthetic_judge.py` 의 LLM judge config 확장 |
| E4 | `reports/ood_eval.md` 의 RFP-vs-OOD 델타 표; 리더보드에 *naive_baseline* / *agentic_full* 옆 *OOD* 컬럼 추가; readme metric sync 통상 gated (issue #739) |

### 최소 바 불변량

OOD 분석 변형은 `agentic_full` 이 OOD 에서 `≥ 0.6 × accuracy(RFP-full)` 도달 + 공개 합성 RFP run 의 95% CI 비중첩 시 **통과**. 이는 *승격* 임계값 아님 — senior-signal *바닥*: 미만은 파이프라인이 RFP-특정 lexicon 에 overfit 한다는 의미, 발표 숫자는 일반화 경고 동반해야.

임계값이 의도적 낮음 (RFP 정확도의 60%, 80% 아님) — 법률 vocabulary 가 RFP 와 sharp 하게 다름, 40% drop 은 파이프라인 실패 신호 없이 plausible. 60% 미만 *cliff* 가 신호.

### 본 ADR 이 *아닌* 것

- 법률 계약 검색이 BidMate 제품 범위라는 주장 아님. *평가* 표면 전용
- ADR 0044 의 비공개 real-data 케이스셋 확장 대체 아님. real-data 측정이 primary 신호 유지; OOD 는 일반화 체크
- 승격 경로 아님. 리더보드 ranking 없음, GitHub release badge 없음 — 비교 컬럼 + 델타 표만

## 검토한 대안

### (a) 학술 논문 / 과학 기사

*거부*: 구조적으로 너무 멀음. 섹션 구조는 section / subsection 이지만 메타데이터 family (저자 / venue / year / DOI) 는 RFP 에 analog 없음. 비교 쿼리 부자연 (RFP reviewer 가 두 입찰 비교하듯 연구자가 "논문 A 와 B 의 방법론 비교" 안 함). false-positive 위험 (*어떤* 정확도 drop 이든 파이프라인 아닌 도메인 탓).

### (b) 의료 / 임상 문서

*거부*: 한국어 public-domain 의료 텍스트 sparse (HIPAA-style 프라이버시 규범 적용). 합성 생성이 검증 불가 주장 생성 위험 — judge 신호 corrupt.

### (c) 영어 RFP

*거부*: 한국어 lexicon (`korean_lexicon` 모듈) + morphology-aware tokenizer (ADR 0031) bypass. 한 번에 변수 너무 많이 변경 — 모든 델타 해석 불가.

### (d) 두 번째 도메인 대신 더 큰 RFP 비공개 set

*OOD* 대체로 *거부*: 같은 도메인 스케일은 CI tighten 하지만 일반화 테스트 안 함. ADR 0044 가 이미 이 축 cover.

## 결과

**Wins**

- 포트폴리오가 발표된 OOD 일반화 숫자 획득 — 단순 RFP 정확도가 전달 못 하는 두 번째 신호 축
- RFP-특정 lexicon overfit 뒤에 숨은 파이프라인 회귀가 visible 화
- ADR 0002 (메타데이터 우선) + 비교 균형 검색 전략이 일반 언어 체크 아닌 구조적 인접 체크 획득

**Costs**

- 합성 법률 코퍼스 생성 주의 필요: 조항 텍스트가 비공개 문서 미복사로 plausible 해야; judge prompt 가 법률 전문성 가정 금지
- 추가 eval 프리셋 = 추가 CI 분 + 추가 리더보드 컬럼. 수용 가능 트레이드오프; `eval/config.yaml` 의 per-preset gating 이 latency SLO 처리
- `korean_lexicon` 모듈에 새 도메인 glossary 항목 추가 — *contract clause* / *party* / *standard clause* / *amendment* (E2 / E3 PR 가 추가)

**미변경**

- ADR 0001 `naive_baseline` 불변량: 기준선 프리셋 변경 없음; OOD 는 *새* 프리셋 추가지 수정 아님
- ADR 0003 답변 계약: 미변경. 법률 계약 답변이 같은 dict schema 사용
- ADR 0005 경계: 법률 코퍼스 데이터가 `data/ood_synthetic_legal/` (공개 합성) 만 거주. 비공개 법률 코퍼스 repo 진입 없음

### 재오픈 조건

본 ADR 은 다음 시 재평가:

- OOD 바닥 (≥ 0.6 × RFP 정확도) 가 큰 마진으로 miss (< 0.4 × RFP) — 도메인이 정보 제공하기엔 너무 멀음
- 다른 OOD 도메인 (예: 한국어 학술 논문 vocabulary-matched 코퍼스 출시) 가 명백히 더 RFP 인접
- 제품 범위가 실제로 법률 계약 검색 서비스로 이동 — 이 시점 법률 코퍼스가 더 이상 OOD 아님

## Verification

본 ADR 은 plan-only. 의존하는 두 전제조건은 PR 시점에 체크; E2 / E3 / E4 PR 이 바닥 불변량 lift.

<!-- verifies-key: eval/config.yaml:naive_baseline -->
<!-- verifies-key: docs/adr/0018-korean-public-rag-bench.md:Korean public -->

E2 / E3 / E4 PR 은 다음을 보여야:

1. `data/ood_synthetic_legal/` 가 ≥ 50 문서로 존재 (E2)
2. `eval/config.yaml` 에 `ood_legal` 프리셋 (E3)
3. `reports/ood_eval.md` 가 RFP↔OOD 델타 표 (E4)
4. 바닥 불변량 `accuracy(ood_legal-full) ≥ 0.6 × accuracy(rfp-full)` 유지
5. RFP 표면에서 ADR 0001 `naive_baseline` 프리셋 미변경
