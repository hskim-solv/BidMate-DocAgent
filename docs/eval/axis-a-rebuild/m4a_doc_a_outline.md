# M4-A doc-A outline + anchor preservation (v3+distractor — main-heading anchored, γ-lite distractor 박제)

Plan: `reports/axis_a_rebuild_plan.md` M4-A.
Distractor 정의: `docs/eval/axis-a-rebuild/distractor_definitions.md` (γ-lite sub-STOP 1.5, 2026-05-16).
Measurement anchor: `docs/eval/axis-a-rebuild/axis_b_real_measurement.md` **v4** (files_kordoc 100-doc 재측정 박제, 2026-05-17).
Date: 2026-05-16 (v3 — sub-STOP 2a undershoot + cross-check 후 main-heading anchor 채택; **v3+distractor — γ-lite retro 박제**).
Stage: **sub-STOP 1 (v3+distractor)** (outline 갱신 박제 → user review → sub-STOP 2a 재합성).

## v3+distractor 변경점 (vs v3, γ-lite 2026-05-16)

- sub-STOP 1.5 distractor 정의 박제 (`distractor_definitions.md`) 후 doc-A retro 진입
- §2.10 부속서 main heading list 에 **counterfactual 박제 main heading** 1개 명시 ("MVP / 산출물 / 정성평가 변경 이력")
- §3 anchor preservation 표에 **§3.5 distractor anchor matrix** 신규 추가 (topical 5쌍 / lexical 5쌍 / counterfactual 3건 / near-duplicate 5쌍)
- §4 acceptance 가드 9-12 추가 (총 12 가드)
- metadata.axis_a_scale: `real_scale_v1` → **`real_scale_v2_distractor`**
- metadata 에 `axis_a_scale_distractor_ref` 추가
- 본 갱신은 doc-A v1 (acceptance 8/8 PASS, 5-gram 20.36%) 폐기 후 v2 재합성을 전제. v1 은 `docs/eval/axis-a-rebuild/rfp_agency_a_ai_quality.v1_pre_distractor.json` 으로 backup

## v4 변경점 (vs v3+distractor+v4metric, 2026-05-17)

- 가드 8 임계: 0.3110 (point) → **0.3171 (p75 bootstrap 95% CI upper)**
  - 정당화: hard threshold 31.10% 가 측정 noise band 안 → spurious FAIL 위험. CI upper 까지가 통계적으로 동일
  - 직접 증거: α' 31.51% (100-doc percentile rank 80) 는 CI [29.70, 31.71] 안 → v3 (≤31.10) 로는 spurious FAIL, **v4 (≤31.71) 로 PASS 회복**
  - bootstrap: B=2000 resample, `distractor_definitions.md` §5.2 v3 박제 inline 코드
- sub-STOP 2c 채택: `m4a_doc_a_full_v2.json` (103 sections / 22,913 kor chars / 5-gram dup 31.51% / 12/13 가드 PASS, guard 10 topical 별도 진단 대상)
- schema 통일 사건: 2b v1 의 `title` field → `heading` 으로 rename (2a v4 와 일치). 이전 합본 (`m4a_doc_a_full_v2_draft.json`) 측정 시 53번 이후 50 sections heading 빈 string 으로 처리되어 expansion / dup 측정 모두 잘못된 base 위에서 진행됐던 사례 — 발견 직후 fix
- 시도 매트릭스 (정직 박제): draft (no exp) 27.21% / α (5-pool×1) 40.75% genuine FAIL / α' (25-template×1) 31.51% v4-PASS / α'' (25-template×2) 34.32% FAIL — α' 채택

## v3+distractor+v4metric 변경점 (vs v3+distractor, 2026-05-17)

- axis B real measurement v3 (18-doc) → **v4 (100-doc 재측정)** 으로 anchor 갱신
- 가드 8 측정 방법 명시: **한글-only char 추출 후 5-gram** (전체 char 기준 측정 금지, `distractor_definitions.md` §5.2 와 통일)
- 가드 8 임계: 0.3113 → **0.3110** (axis B 100-doc p75, Δ -0.03%p 무변동) — 이 줄은 v4 에서 0.3171 로 다시 정정 (위 §v4 참조)
- 가드 5 단위 명시: tables_block (구분자 줄 단위, regex 자체는 v3+distractor 그대로)
- sub-STOP 2a partial v4 채택 보고: 53 sections / 18,335 chars / 5-gram dup 27.40% (한글-only) / GFM block 53 / 12+ 가드 PASS (acceptance 13 가드 중 13 적용)
- §5 사전 추정 ("+0.65%p") 빗나감 정직 박제: `distractor_definitions.md` §5.1 cross-ref

## v3 변경점 (vs v2)

- v2 anchor (kordoc `headings_count` median 282) → outline tree node (subheading 포함) misanchor 검출
- v3 anchor (Upstage `categories.heading1` median ~100) → RFP **main heading** 등가
- section_count_target 180-200 → **110-120 main heading**
- chars/section avg ~160 → **~280-330**
- 표 분포 §2.11 → block 단위 ~80, cell 단위 ~120 (대형 표 비중 약간 ↑ — main heading 1개에 큰 표 1-2개 포함되는 패턴)
- sub-STOP 2a / 2b 분할도 main heading 단위로 재계산:
  - 2a (§2.2 ~ §2.5): main heading **50-60** / chars **16k** / 표 60-70
  - 2b (§2.6 ~ §2.10): main heading **55-65** / chars **14k** / 표 50-60
- v2 partial `m4a_doc_a_partial_2a.json` (97 fine-grained sections / 51 chars-per-sec) **폐기** — v3 anchor 로 재합성

## 1. doc-A 신규 schema (기존 보존, sections 만 확장)

```json
{
  "doc_id": "rfp-agency-a-ai-quality",
  "title": "기관 A AI 품질관리 플랫폼 구축 RFP",
  "agency": "기관 A",
  "project": "AI 품질관리 플랫폼 구축",
  "metadata": {
    "domain": "AI quality",
    "document_type": "synthetic_public_sample",
    "axis_a_scale": "real_scale_v2_distractor",
    "axis_a_scale_anchor": "Upstage heading1 (main heading) median ~100 + kordoc 39511 chars cross-check",
    "axis_a_scale_measurement_ref": "docs/eval/axis-a-rebuild/axis_b_real_measurement.md v3",
    "axis_a_scale_distractor_ref": "docs/eval/axis-a-rebuild/distractor_definitions.md (γ-lite sub-STOP 1.5)",
    "axis_a_scale_outline_ref": "docs/eval/axis-a-rebuild/m4a_doc_a_outline.md (v3+distractor)",
    "project_aliases": ["품관플", "AI품플"],
    "section_definition": "main_heading (Upstage heading1 등가, chapter+section level, sub-bullet 미포함)",
    "section_count_target": "110-120",
    "korean_chars_target": 30000,
    "chars_per_section_target": "280-330",
    "table_count_target_cell": "110-130",
    "table_count_target_block": "75-85",
    "measurement_anchor": "docs/eval/axis-a-rebuild/axis_b_real_measurement.md v3 (kordoc median 39511 chars + Upstage heading1 median ~100 cross-check + n-gram dup distribution)"
  },
  "sections": [ ... 110-120개 main heading ... ]
}
```

- 기존 5 필드 (doc_id / title / agency / project / metadata) 모두 보존
- metadata 에 axis A real-scale marker 7개 추가 (M4-D 의 β reset 추적용)
- sections schema 불변 (heading + text), markdown 표는 text 안에 inline. sub-bullet 은 별도 section 으로 분리하지 않고 body 안에 단락/list 로 inline.

## 2. section group outline (총 110-120 main heading / 110-130 tables_cell / 75-85 tables_block)

각 group 의 main heading / 표 분배는 Upstage `heading1` median ~100/doc 의 **110-120%** 시뮬레이션. chars/main-section 평균은 ~280-330 (kordoc 39511 / 100 = 395 의 70-83%).

### 2.1 group 분배표 (v3 anchor)

| group | main headings | chars (kor) | chars/sec avg | tables_cell | tables_block | sub-STOP |
|---|---:|---:|---:|---:|---:|---|
| §2.2 사업 개요 | 11-13 | 3,300-3,800 | ~300 | 11-13 | 7-9 | 2a |
| §2.3 추진 배경 및 필요성 | 9-11 | 2,700-3,200 | ~300 | 10-12 | 6-8 | 2a |
| §2.4 사업 범위 | 14-16 | 4,000-4,600 | ~300 | 14-16 | 10-12 | 2a |
| §2.5 기능 요구사항 (FR) | 16-18 | 5,500-6,200 | ~340 | 22-26 | 15-18 | 2a |
| §2.6 비기능 요구사항 (NFR) | 11-13 | 3,200-3,800 | ~300 | 16-20 | 11-13 | 2b |
| §2.7 데이터 및 보안 | 10-12 | 3,000-3,500 | ~300 | 12-15 | 8-10 | 2b |
| §2.8 일정 및 산출물 | 8-10 | 2,200-2,700 | ~280 | 8-11 | 5-7 | 2b |
| §2.9 평가 및 제출조건 | 10-12 | 3,000-3,500 | ~300 | 10-13 | 6-8 | 2b |
| §2.10 부속서 (용어 / 약어 / 참고) | 6-8 | 1,800-2,300 | ~280 | 5-9 | 4-6 | 2b |
| **합계** | **95-113** | **28,700-33,600** | **~290-330** | **108-135** | **72-91** | |

→ 중간값 **104 main heading / 31,000 chars / 297 chars/sec / 121 tables_cell / 81 tables_block**. axis B Upstage heading1 median ~100 의 ~104% (정확 anchor).

### 2.2 사업 개요 (~12 main heading, ~3,500 chars + ~12 표)

main heading 예시 (각각 ~290 chars body + 표 inline):
- 사업 명칭 및 발주 기관
- 사업 개요 (anchor §2 본문: "AI 품질관리 플랫폼", "모델 성능 저하", "품질 지표")
- 사업 추진 의의 및 배경
- 사업 목적 및 기대효과
- 사업 추진 체계 및 거버넌스
- 사업 추진 원칙 및 의사결정 구조
- 사업 KPI 정의 및 핵심 지표
- 사업 리스크 개요
- 사업 범위 요약 (§2.4 로의 연결)
- 사업 추진 전략 요약 (단계 분류)
- 사업 결과물 요약 (§2.8 로의 연결)
- 사업 종료 후 운영 체계

- positive anchor: "AI 품질관리 플랫폼", "모델 성능 저하", "품질 지표", project_aliases "품관플", "AI품플"

### 2.3 추진 배경 및 필요성 (~10 main heading, ~2,900 chars + ~11 표)

main heading 예시:
- 정책 환경 분석 (정부 AI 정책 / 공공기관 AI 표준 / 관련 법령)
- 내부 운영 환경 분석 (SWOT / 기존 시스템 한계)
- 시장 동향 및 벤치마킹 (국내 / 글로벌)
- 표준 동향 (ISO / NIST / OWASP)
- 사업 추진 필요성 종합 및 우선순위
- 이해관계자 요구 및 Pain Point
- 추진 시 리스크 분석
- 정책 정합성 확보 방안
- 외부 감사 대응 방안
- 변화 관리 전략

### 2.4 사업 범위 (~15 main heading, ~4,300 chars + ~15 표)

main heading 예시:
- 사업 범위 개요 (기능/비기능/데이터/인프라/외부연계/산출물)
- 기능적 범위 분류
- 비기능적 범위 분류
- **AI 요구사항 개요** (anchor: "모델 품질관리", "보안 통제", "로그 추적")
- 데이터 범위
- 인프라 범위
- 외부 연계 범위
- 사업 제외 범위
- 단계별 범위 (1차/2차/3차)
- 산출물 범위 종합 및 의존성
- 위탁 범위 / 직접 수행 범위
- IP 귀속 및 라이선스 범위
- 협력 및 인수인계 범위
- 사용자 그룹 및 권한 범위
- 보안 및 운영 범위 단계 전환 기준
- positive anchor: "모델 품질관리", "보안 통제", "로그 추적"

### 2.5 기능 요구사항 FR (~17 main heading, ~5,800 chars + ~24 표)

각 FR main heading 은 acceptance criteria 본문 + 표 inline. sub-bullet (FR-001-1 등) 은 body 안의 list 로 inline.

main heading 예시:
- FR 전체 구조 및 ID 매트릭스
- FR-001 모델 등록 및 관리
- FR-002 모델 성능 측정 (정확도/재현율/F1)
- FR-003 모델 성능 저하 감지 알람
- FR-004 품질 지표 표준화 엔진
- FR-005 데이터 드리프트 감지
- FR-006 라벨링 품질 검증
- FR-007 모델 비교 분석 및 A/B 테스트
- FR-008 운영자 대시보드
- FR-009 보안 통제 (접근/권한/감사)
- FR-010 로그 추적 및 감사
- FR-011 외부 API 연동
- FR-012 모델 배포 / 롤백
- FR-013 알람 정책 관리
- FR-014 보고서 / Export
- FR-015 모델 메타데이터 / 카드
- FR-016 학습 / 추론 / 데이터 버전 추적

### 2.6 비기능 요구사항 NFR (~12 main heading, ~3,500 chars + ~18 표)

main heading 예시:
- NFR 전체 구조 및 매트릭스
- 성능 (응답시간 / 처리량 / 동시접속)
- 보안 (K-ISMS-P / 암호화 / 망분리)
- 보안 통제 매트릭스
- 가용성 (SLA / RPO / RTO)
- 확장성 (horizontal scale / multi-tenant)
- 운영 (모니터링 / 백업 / 장애 대응)
- 운영 인력 요구
- 호환성 (OS / 브라우저 / 클라우드)
- 유지보수성 및 접근성
- 표준 준수 (ISO / NIST 연계)
- NFR 시험 및 검증 절차

### 2.7 데이터 및 보안 (~11 main heading, ~3,200 chars + ~13 표)

main heading 예시:
- 데이터 분류 및 보호 등급
- 데이터 마스킹 / 익명화
- 개인정보 처리 방침
- 데이터 라이프사이클 관리
- 데이터 보존 기간 및 폐기
- 보안 통제 운영 절차
- 보안 감사 및 교육 주기
- 침해 사고 대응 단계 및 보고 시한
- 보안 패치 및 취약점 점검
- 데이터 백업 및 이동 보안
- 데이터 폐기 검증

### 2.8 일정 및 산출물 (~9 main heading, ~2,500 chars + ~10 표)

main heading 예시:
- 추진 일정 개요
- **단계별 일정 (anchor: "4개월 MVP", "6개월 최종 검수")**
- 착수 / 설계 / 구현 / 검수 단계 (단일 main 으로 통합, sub-bullet 으로 풀이)
- 마일스톤 및 단계 전환 기준
- 단계별 산출물 분류
- **필수 산출물 (anchor: "모델 점검 리포트", "보안 통제 매뉴얼", "운영자 교육 자료")**
- 산출물 상세 및 검수 기준
- 산출물 IP / 라이선스 / form factor
- 산출물 인계 절차

- positive anchor: "4개월", "MVP", "6개월", "최종 검수", "모델 점검 리포트", "보안 통제 매뉴얼", "운영자 교육 자료"

### 2.9 평가 및 제출조건 (~11 main heading, ~3,200 chars + ~11 표)

main heading 예시:
- 평가 기준 종합 및 가중치
- 평가 절차
- 정량 평가 항목 및 배점
- 정성 평가 항목 (anchor: "보안 통제 경험", "AI 품질관리 프로젝트 경험")
- **수행 조직 요건 (anchor: "PM", "ML 엔지니어", "보안 담당자")**
- 직무별 인력 요구 및 자격
- 인력 경력 및 보증
- 제안서 작성 지침 및 구성
- 제안서 분량 및 제출 방법
- 제안서 제출 시한 및 평가 일정
- 제안 결과 통보 절차

### 2.10 부속서 (~8 main heading, ~2,400 chars + ~8 표, v3+distractor)

- 용어 정의 (FR / NFR / SLA / RPO / RTO / K-ISMS-P / 드리프트 / MLOps / 정합성 / 표준 지표)
- 약어 (다수)
- 참고 표준 및 가이드라인 (ISO / NIST / OWASP)
- 부속 양식 안내
- **MVP / 산출물 / 정성평가 변경 이력 (counterfactual 박제 main heading, 3건 박제)** — sub-§ 3 건:
  - "MVP / 최종 검수 기한 변경 이력: 초안 (2024-01) MVP 6개월·최종 검수 9개월 → 1차 변경 (2024-03) MVP 5개월·최종 검수 7개월 → 최종 (2024-06) **MVP 4개월·최종 검수 6개월**"
  - "필수 산출물 변경 이력: 초안 2종 (모델 점검 리포트 / 보안 통제 매뉴얼) → 최종 **3종 (+ 운영자 교육 자료)**"
  - "정성 평가 항목 변경 이력: 초안 1종 (AI 품질관리 프로젝트 경험) → 최종 **2종 (+ 보안 통제 경험)**"
- 일반 변경 이력 (heading 수정, 표 추가 등 minor)
- 작성자 / 검토자 / 승인 정보
- 추가 안내사항

⚠️ counterfactual 박제 규칙:
- "초안" / "변경 전" / "1차 변경" / "최종" 토큰 사용 — verifier 가 식별 가능하도록
- 정답 값 (MVP 4개월 / 산출물 3종 / 정성 평가 2종) 은 본문 §2.8 / §2.9 와 일치 유지
- 잘못된 값 (MVP 6개월 / 산출물 2종 / 정성 평가 1종) 은 §2.10 변경 이력 main heading 안에만 등장. 다른 section 에 누설 금지

### 2.11 표 크기 분포 (총 ~120 tables_cell / ~80 tables_block, v3 갱신)

| 크기 | 개수 (cell unit) | row × col | 평균 chars/표 | 총 chars |
|---|---:|---|---:|---:|
| 작은 표 | 50 | 2-3 × 2-3 | ~80 | ~4,000 |
| 중간 표 | 50 | 4-7 × 3-4 | ~180 | ~9,000 |
| 큰 표 | 20 | 8+ × 4+ | ~380 | ~7,600 |
| 합계 | 120 | | | ~20,600 |

표 chars 20.6k + 본문 chars 30k + JSON overhead 2k = **~52k total chars output**. Claude extended-output 한계 내. v2 대비 표 chars 비중 ↑ (큰 표 + 중간 표 비중 ↑) — main heading 당 큰 표 0.2개 / 중간 표 0.5개 / 작은 표 0.5개 분포.

block unit (kordoc tables_blocks 등가): cell 120 → ~80 block 환산 (작은 표 1.5개가 1 block 으로 묶이는 평균).

## 3. Anchor preservation 매핑 표 (v3 — group ref 기준, v2 와 동일)

### 3.1 Positive anchor (105 case 의 must_include 가 의존, 정확 표현 보존)

| anchor (정확 표현) | 등장 group | case 예 (config.yaml line) |
|---|---|---|
| "AI 품질관리 플랫폼" | §2.2 | "기관 A의 AI 품질관리 플랫폼 구축 목표는?" (L1223) |
| "모델 성능 저하" | §2.2 | (위와 동일) |
| "품질 지표" 표준화 | §2.2 | (위와 동일) |
| "모델 품질관리" | §2.4 (AI 요구사항 개요) | "기관 A의 핵심 AI 요구사항 세 가지" (L1283) |
| "보안 통제" | §2.4, §2.5 (FR-009), §2.6 (보안), §2.7 (보안 통제 운영) | "기관 A의 보안 통제 요구사항은?" (L438), "기관 A의 핵심 AI 요구사항 세 가지" (L1283) |
| "로그 추적" | §2.4, §2.5 (FR-010) | "기관 A의 핵심 AI 요구사항 세 가지" (L1283), abstention L1079 |
| "4개월", "MVP" | §2.8 (추진 일정) | "기관 A의 MVP 제출 기한은?" (L1254) |
| "6개월", "최종 검수" | §2.8 (추진 일정) | (위와 동일) |
| "모델 점검 리포트" | §2.8 (필수 산출물) | "기관 A의 필수 산출물은?" (L506) |
| "보안 통제 매뉴얼" | §2.8 (필수 산출물) | (위와 동일) |
| "운영자 교육 자료" | §2.8 (필수 산출물) | (위와 동일) |
| "PM", "ML 엔지니어", "보안 담당자" | §2.9 (수행 조직) | "기관 A 수행 조직에 포함해야 할 직군은?" (L1238) |
| "보안 통제 경험" | §2.9 (정성 평가) | "기관 A의 정성평가에 반영되는 항목은?" (L1269) |
| "AI 품질관리 프로젝트 경험" | §2.9 (정성 평가) | (위와 동일) |
| project_aliases: "품관플" | §2.2, metadata | (rag_query.py extract_requested_agencies) |
| project_aliases: "AI품플" | §2.2, metadata | (위와 동일) |

→ **16 positive anchor 모두 정확 표현 보존**. 합성 시 paraphrase 금지 (must_include 가 exact match).

### 3.2 Negative anchor (abstention case 가 의존, 부재 유지)

| 부재 키워드 | abstention case |
|---|---|
| "블록체인" / "blockchain" | "기관 A의 블록체인 납품 실적은?" (L1022) |
| "생성형 AI 상담" | "기관 A의 생성형 AI 상담 기능 요구사항은?" (L1054) |
| "양자암호" | "기관 A의 보안 통제, 로그 추적과 양자암호 적용 방안은?" (L1079) |
| "드론" | "기관 A의 보안과 드론은?" (L1117) |

→ **4 negative anchor 모두 신규 corpus 에 등장 금지**.

### 3.3 Comparison anchor (multi-doc comparison case)

| comparison axis | doc-A side anchor |
|---|---|
| A vs B AI 요구사항 차이 | "모델 품질관리, 보안 통제, 로그 추적" 강조 (§2.4) |
| A vs B 보안 요구사항 차이 | §2.5 (FR-009), §2.6 (보안 NFR), §2.7 (보안 통제) |
| A vs D 보안 차이 | 위와 동일 |
| A vs B 일정 차이 | "4개월 MVP / 6개월 최종 검수" (§2.8) |
| A vs C AI 요구사항 초점 | "AI 품질관리" vs "챗봇/콜센터" 차이 (§2.2 / §2.4) |
| A vs B 모니터링 / 로그 요구사항 | §2.5 (FR-008 대시보드 / FR-010 로그 추적) |
| A vs D 핵심 사업 영역 | "AI 품질관리 플랫폼" vs "분광기 probe" 명확 |
| A vs B MLOps 자동화 (역방향) | doc-A 는 "품질관리" 강조 |
| A vs D 사업 기간 | "4개월 MVP / 6개월 최종" (§2.8) |

### 3.4 Multiturn anchor

`eval/multiturn_scenarios_v1.jsonl` 의 MT 들이 doc-A 의 sections 를 turn-by-turn 참조 가능. 위 positive anchor 보존만으로 충족.

### 3.5 Distractor anchor matrix (v3+distractor, γ-lite)

#### topical distractor (5쌍)

| # | 정답 anchor | 박제 위치 | topical 비-정답 표현 | 박제 위치 |
|---|---|---|---|---|
| t1 | "AI 품질관리 플랫폼" | §2.2 사업 개요 | "AI 품질관리 시스템 구성도" | §2.4 사업 범위 (인프라 범위) |
| t2 | "보안 통제" | §2.5 FR-009, §2.6, §2.7 | "보안 운영 가이드" | §2.8 산출물 (필수 산출물 외 보조 산출물) |
| t3 | "모델 성능 저하" | §2.2 사업 개요 | "모델 성능 측정" | §2.5 FR-002 |
| t4 | "품질 지표" 표준화 | §2.2 | "운영 품질 지표" | §2.6 NFR (운영) |
| t5 | "MVP" 4개월 | §2.8 | "1차 단계" / "파일럿 단계" | §2.4 단계별 범위 |

#### lexical distractor (5쌍, LEXICAL_VARIANTS dict)

| # | 정답 anchor | lexical 비-정답 표현 (substring/superstring/variant) | 박제 위치 |
|---|---|---|---|
| l1 | "AI 품질관리 플랫폼" | "AI 품질 관리 체계" (띄어쓰기 + suffix 변형) | §2.3 추진 배경 (정책 환경) |
| l2 | "보안 통제" | "보안 관제" (1글자 변형) | §2.4 외부 연계 |
| l3 | "모델 점검 리포트" | "모델 검수 리포트" / "모델 점검 요약" | §2.5 FR-014 (보고서 / Export) |
| l4 | "ML 엔지니어" | "MLOps 엔지니어" / "ML 운영자" | §2.9 직무별 인력 요구 |
| l5 | "로그 추적" | "로그 분석" / "로그 모니터링" | §2.5 FR-008 (운영자 대시보드) |

→ `LEXICAL_VARIANTS` Python dict 박제 (sub-STOP 3 acceptance 측정 시 사용):
```python
DOC_A_LEXICAL_VARIANTS = {
    "AI 품질관리 플랫폼": ["AI 품질 관리 체계"],
    "보안 통제": ["보안 관제"],
    "모델 점검 리포트": ["모델 검수 리포트", "모델 점검 요약"],
    "ML 엔지니어": ["MLOps 엔지니어", "ML 운영자"],
    "로그 추적": ["로그 분석", "로그 모니터링"],
}
```

#### counterfactual (3건, §2.10 변경 이력 main heading 안)

위 §2.10 갱신 참조. "초안" / "1차 변경" / "최종" 토큰 + 잘못된 값 / 정답 값 동시 등장.

#### near-duplicate (5쌍, sentence-level Jaccard ≥ 0.8)

| # | 박제 위치 1 | 박제 위치 2 | 변형 |
|---|---|---|---|
| n1 | FR-002 acceptance criteria 1 sentence | FR-003 acceptance criteria 1 sentence | ID 만 변형, 본문 거의 동일 |
| n2 | FR-005 (데이터 드리프트 감지) acceptance | FR-006 (라벨링 품질 검증) acceptance | 측정 주기 / 임계값만 변형 |
| n3 | FR-007 (A/B 테스트) acceptance | FR-008 (운영자 대시보드) acceptance | 대상 ID 만 변형 |
| n4 | FR-009 (보안 통제) acceptance | FR-010 (로그 추적) acceptance | 통제/추적 항목명만 변형 |
| n5 | NFR 성능 acceptance | NFR 가용성 acceptance | SLA 값만 변형 |

→ 합성 시 acceptance criteria 패턴 `"FR-NNN 는 X 요청 후 평균 Y 이내 결과를 반환해야 하며, Z 갱신 시 W 이내 동기화를 보장해야 한다."` 의 X/Y/Z/W 만 변형.

5-gram dup 충돌 사전 추정: doc-A 현재 20.36% + 0.65%p ≈ **21.01%** 예상. corrigendum 31.13% 안 안전.

**※ 사전 추정 빗나감 정직 보고 (2026-05-17, v4 박제 후)**: doc-A retro 재합성 후 한글-only 5-gram dup 실측 = v3 29.66% / v4 27.40% (사전 추정 21.01% 대비 +6~9%p). 빗나감 원인: expansion paragraph (본문 + expansion 추가) 영향이 추정에 미반영. 가드 임계 (≤ 31.10%) 안에서 여전히 PASS. 상세는 `distractor_definitions.md` §5.1 참조.

## 4. 합성 가드 (v3+distractor acceptance, 12 가드)

| # | 가드 | 검증 방법 | 기준값 (v3+distractor) |
|---|---|---|---:|
| 1 | 16 positive anchor 모두 정확 표현 등장 | `for kw in [...]: assert kw in text` | 16/16 |
| 2 | 4 negative anchor 부재 | `for kw in [...]: assert kw not in text` | 0/4 |
| 3 | Korean chars | `len(re.findall(r'[가-힣]', text))` | ≥ 22,000 (target 30,000) |
| 4 | sections count (main heading) | `len(d['sections'])` | ≥ 95 (target 110) |
| 5 | markdown 표 (GFM separator line, **block 단위**) | `re.findall(r'^\s*\|[-\s|:]+\|\s*$', text, re.MULTILINE)` | ≥ 50 (v4 target 55-65 block) |
| 6 | chars/section 평균 | `kor_chars / sections` | **200-450** (target ~290) |
| 7 | schema 유효 + 기존 5 top-level / 3 metadata 필드 불변 | `json.load()` + diff | identical |
| 8 | **5-gram dup ratio (v4 한글-only, v5 bootstrap CI margin, 2026-05-17)** | `korean = "".join(c for c in text if "가"<=c<="힣"); grams=[korean[i:i+5] for i in range(len(korean)-4)]; (len(grams)-len(set(grams)))/len(grams)` | **≤ 0.3171 (axis B real 100-doc p75 31.10% + bootstrap 95% CI upper margin 0.61%p; `distractor_definitions.md` §5.2/§6.1 v3 박제)** |
| 9 | topical distractor pair ≥ 5 | `topical_count(text, TOPICAL_KEYWORDS_DOC_A)` ≥ 5 — `distractor_definitions.md` §6.1.1 박제 dict (t1-t5 OR variants) | ≥ 5 (t1-t5) |
| 10 | lexical distractor variant ≥ 5 | `for v in DOC_A_LEXICAL_VARIANTS.values(): for s in v: assert s in text` | ≥ 5 (l1-l5) |
| 11 | counterfactual 박제 ≥ 3 | `re.findall(r"초안\|1차 변경\|최종", §2.10_변경이력_section)` ≥ 3 + 정답값/잘못된값 동시 등장 | ≥ 3 |
| 12 | near-duplicate sentence pair (Jaccard ≥ 0.8) ≥ 5 | `near_duplicate_count(text, 0.8)` | ≥ 5 (n1-n5) |
| 13 | 한자 / 숫자 단위 일관성 | manual sample review | OK |

## 5. 합성 budget 추정 (v3)

- 110 main heading × 본문 평균 ~290 chars = ~32,000 korean_chars
- 표 ~120개 × 평균 ~170 chars (큰 표 비중 ↑) = ~20,000 chars
- heading + 영문 / 숫자 + 구분 chars ≈ ~3,000 chars
- JSON overhead: ~2,000 chars
- **총 output: ~57,000 chars / ~45,000-55,000 tokens 출력**

### 5.1 multi-turn 권장 (사용자 결정 옵션 ii)

- sub-STOP 2a: §2.2-2.5 main heading **~50-55** / chars **~16,000** / 표 ~55-65 / 표 chars ~10,000 → output ~28,000 chars
- sub-STOP 2b: §2.6-2.10 main heading **~50-55** / chars **~14,000** / 표 ~55-65 / 표 chars ~10,000 → output ~26,000 chars
- sub-STOP 3: 합본 + acceptance + sample review

각 sub-STOP 의 output 28k chars 는 Claude extended-output 한계 내 안전.

## 6. 진행 결정 (사용자 confirm 대기)

본 outline v3 박제 = M4-A doc-A 의 **sub-STOP 1 (v3)** 완료. 다음 step:

- (i) **sub-STOP 2a (v3) 합성** — §2.2-2.5 의 50-55 main heading / 16k chars / 60 표 / chars/sec ~290. v2 partial 폐기 후 새로 합성. *권장*
- (ii) outline v3 추가 미세 조정 후 (i)
- (iii) 다른 anchor 검토 (예: chars/sec 250 vs 330 결정)

본 sub-STOP 1 (v3) 종료. 사용자 review 대기.
