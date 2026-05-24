# 0039: HWP 구조 hardcase taxonomy

- **Status**: proposed
- **Date**: 2026-05-14
- **Deciders**: hskim-solv
- **Related**: issue #646, ADR 0001, ADR 0005, retired aggregate policy, ADR 0036, [docs/real-data/private-hardcase-benchmark.md](../real-data/private-hardcase-benchmark.md)

## TL;DR

- 공개 fixture smoke가 문서 구조 실패 cover 못 함 — HWP 구조 hardcase 4 카테고리(`table_heavy`, `ocr_noisy`, `rotated_or_skewed`, `layout_broken`)를 fixture/private aggregate에서 측정 가능하게 정의.
- 합성 fixture만 사용(비공개 콘텐츠 0), ADR 0001/0005 불변식 보존.
- 후속 PR이 fixture/태그 추가 + HWP loader 분석 변형 측정 가능화.

## 배경

ADR 0036 (#641)이 HwpNativeLoader를 pyhwp-gated 기본값으로 도입, 비공개 100-doc eval corpus를 96% HWP로 만들었다. 그러나 공개 fixture smoke는 HWP fixture가 없고 기존 hardcase 항목이 논리·검색 discrimination만 cover — 문서 구조 실패는 아님.

[`docs/real-data/private-hardcase-benchmark.md:24-31`](../real-data/private-hardcase-benchmark.md)이 비공개 surface 전용 다섯 문서 구조 슬라이스 (`scanned_pdf`, `rotated_or_skewed`, `table_heavy`, `mixed_layout`, `noisy_ocr`) 정의. 공개 `by_hardcase_category` 집계 ([`eval/run_eval.py:618`](../../eval/run_eval.py))는 case config에서 발견한 모든 카테고리 태그를 자동 버킷팅하므로 태그 추가는 코드 변경 불필요 — 어떤 슬라이스가 공개 도입 안전한지 정책 결정만 필요.

이 taxonomy 없이는 HWP loader 선택(csv-text vs native vs native_tables, ADR 0036)이 citation precision 또는 table-cell recall에 미치는 영향을 fixture/private aggregate에서 분리해 보기 어렵다.

## 결정

HWP 구조 hardcase 4 카테고리 — `table_heavy`, `ocr_noisy`, `rotated_or_skewed`, `layout_broken` — 를 eval taxonomy에 인정. 비공개 문서 콘텐츠 없는 fixture 또는 private/internal aggregate만 사용. 이 카테고리 태그된 case는 세 제약 모두 충족 필수:

1. **ADR 0001 baseline 불변식**: 태깅은 additive; 기존 case의 retrieval, verifier, answer 경로를 변경 금지.
2. **ADR 0005 공개 경계**: fixture는 재배포 가능 합성 JSON (기존 `eval/fixtures/smoke_rfp/raw/rfp_agency_*.json` 스키마 매칭); scanned/OCR 추출 비공개 snippet 금지.
3. **Aggregate forward-only**: 신규 `by_hardcase_category` 키 도입은 series break 생성; 과거 snapshot은 `—`로 렌더, backfill 불필요.

후속 PR이 이 taxonomy 활성화: PR-A가 합성 HWP fixture + 초기 태그된 case 추가; PR-D가 loader 분석 변형 데이터(PR-C)가 table vs layout 실패에 가장 discriminated된 query 타입 확인 후 추가 case 태그.

## 결과

- `eval_summary.json`의 `by_hardcase_category`가 4개 신규 키 획득; 기존 22 슬라이스 무영향.
- Aggregate reports can expose `table_heavy` citation precision and `layout_broken` groundedness alongside `naive_baseline` / `agentic_full`.
- HWP loader 분석 변형(PR-C: `hwp_csv_text` / `hwp_native` / `hwp_native_tables`)이 이 구조 슬라이스 대비 측정 가능해짐.
- pyhwp 미설치 CI 실행 green 유지: fixture는 JSON이므로 `_resolve_loader` ([`ingestion.py:377`](../../ingestion.py)) 미호출.
- 신규 비공개 hardcase 슬라이스 추가하는 팀은 공유 `by_hardcase_category` namespace 이름 충돌 회피 위해 이 리스트 체크 필요.

## 검토한 대안

- **`scanned_pdf`와 `mixed_layout`도 인정**: deferred. Scanned-PDF fixture는 image 데이터 또는 비공개 콘텐츠 leakage 위험 OCR-corpus 세그먼트 필요; `mixed_layout`은 `layout_broken`과 의미적 overlap, 공개 사용 전 disambiguation 가이드 필요.
- **모든 구조 슬라이스 비공개 only 유지**: 기각. ADR 0036 loader 영향이 공개 fixture schema에서 전혀 보이지 않으면 capability 주장을 reviewer가 재현 가능한 형태로 확인하기 어렵다.
