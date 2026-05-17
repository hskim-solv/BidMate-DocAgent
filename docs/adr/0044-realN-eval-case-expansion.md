# 0044: real100 Eval Case 확장 — In-Place n 증가 정책

| Field       | Value                                     |
|-------------|-------------------------------------------|
| **Status**  | Accepted (Superseded by ADR 0052)         |
| **Date**    | 2026-05-14                                |
| **Issue**   | #732                                      |
| **Authors** | hskim-solv                                |
| **Tags**    | eval, real-data, dataset-cardinality      |
| **Superseded by** | ADR 0052 (n=21→221 step-change via LLM-assisted generator) |

## TL;DR

- ADR 0044: real100 eval 케이스를 n=21 → n≥30 → n≥50 로 in-place 확장 (같은 100-doc 코퍼스, 같은 path)
- 새 시리즈 분기 안 함 — `num_predictions` 가 n 추적, 비교 항상 n-aware
- 케이스 정의는 `eval/real_config.local.yaml` (gitignored) 유지, aggregate 만 공개

## 배경

real100 비공개 eval 표면 (`eval/real_config.local.yaml`, `reports/real100/`) 은 100개 비공개 RFP 문서를 인덱싱하지만 **n = 21 케이스** 만 평가한다. n = 21 에서 통계 신호 약함:

- Pool-recall 100% 신뢰구간 ±21pp (Wilson 95%)
- 단일 케이스 정확도 flip 이 헤드라인 +4.8pp 변동
- Silence threshold `max(5e-4, 0.5 / n_min)` (ADR 0030) 가 0.024 로 해소 — 의도한 수렴 신호보다 훨씬 큼

100개 문서 모두 이미 `data/index/real100/` 에 수집됨; 갭은 케이스지 문서 아님. 기존 코퍼스로 n 확장은 low-risk + high-signal.

## 결정

새 병렬 eval 시리즈 시작 대신 **같은 위치에서 케이스셋 확장** (같은 `reports/real100/` 시리즈, 같은 `eval/real_config.local.yaml` path).

근거:

1. **같은 코퍼스, 같은 인덱스.** 100-doc 코퍼스와 인덱스 미변경. Cardinality 는 *케이스* (쿼리) 지 문서 아님. 케이스 추가는 과거 검색 측정 무효화 안 함 — 통계 검정력 향상.

2. **`num_predictions` 가 n 추적.** 모든 `eval_summary.json` 스냅샷이 이미 `num_predictions` 기록 — 모든 기준선 비교의 권위 있는 n. `reports/real100/baseline.aggregate.json` 도 커밋 시점에 `num_predictions` 기록하므로 델타 비교 항상 n-aware.

3. **Silence threshold 자동 조정.** ADR 0030 정의 `δ_silence = max(5e-4, 0.5 / n_min)`. n 증가가 config 변경 없이 자동 threshold tighten.

4. **ADR 0005 경계 보존.** 케이스 정의 (쿼리 + 비공개 RFP 콘텐츠 참조 예상 답변) 는 `eval/real_config.local.yaml` (gitignored) 유지. ADR 0005 에 따라 aggregate 통계만 공개 커밋. 본 ADR 은 확장 결정 기록; 운영자가 로컬에서 케이스 추가 적용.

## 목표 Cardinality

**n ≥ 30** 단기 목표 (n = 21 에서). n = 30 일 때:

- Wilson 95% CI on recall 이 ±21pp → ±18pp 좁아짐
- 단일 케이스 flip 이 헤드라인 +3.3pp 변동 (n = 21 의 +4.8pp 대비)
- Silence threshold 0.017 로 tighten (0.024 대비)

장기 목표: n ≥ 50 (silence threshold ≤ 0.010, CI ≤ ±14pp).

## 케이스 선정 기준

새 케이스 충족 조건:

1. **검증 가능 expected terms** — expected_terms 가 인덱싱된 청크 텍스트에 verbatim 으로 출현 (합성/패러프레이즈 아님)
2. **다양한 query type** — single_doc, comparison, abstention 케이스 포함해 분포 균형
3. **문서 커버리지** — 기존 케이스가 다루지 않은 문서 선호해 코퍼스 활용 최대화
4. **안정적 ground truth** — expected 답변이 주관적 아닌 사실적 (예산, 날짜, 기술 요구사항)

## 결과

- `reports/real100/eval_summary.json` 이 각 확장 run 후 더 높은 `num_predictions` 보임. 다운스트림 스크립트 (리더보드, 델타 보고서) 가 summary 에서 `num_predictions` 자동 읽음
- 커밋된 `reports/real100/baseline.aggregate.json` 은 각 확장 run 후 `make real-eval-baseline-update` 로 업데이트해 새 n 을 공개 provenance chain 에 기록 필요
- 더 낮은 n 의 과거 기준선은 부호 비교 (델타 방향) 에 유효하지만 크기 비교에는 무효 — reviewer 가 기준선 bump 시 PR 설명에 n 변경 명시 필요

## 검토한 대안

**새 별도 시리즈 (`reports/real30/`)**: 거부. 리더보드 시계열을 이득 없이 분할; 100-doc 코퍼스 공유라 검색 측정 직접 비교 가능.

**비공개 데이터 확장 (새 문서) 으로만 증가**: 연기. 새 문서 수집은 ADR 0005 리뷰 + 인덱스 재빌드 필요. 기존 100-doc 코퍼스 내 케이스 확장이 마찰 더 낮은 즉시 개선.

## 참조

- ADR 0001 — naive_baseline 불변량 (영향 없음; 공개 합성 eval)
- ADR 0005 — eval 분리 경계 (비공개 데이터 gitignored 유지)
- ADR 0030 — 리더보드 silence threshold + n-aware 공식
- Issue #732 — 구현 추적
