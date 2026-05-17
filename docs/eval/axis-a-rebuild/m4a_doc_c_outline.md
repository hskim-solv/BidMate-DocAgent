# M4-A doc-C outline + anchor preservation (v2 — distractor 박제, doc-A/B v4 패턴 reuse)

Plan: `reports/axis_a_rebuild_plan.md` M4-A.
Distractor 정의: `docs/eval/axis-a-rebuild/distractor_definitions.md` v3 (γ-lite + bootstrap CI margin, 2026-05-17).
Measurement anchor: `docs/eval/axis-a-rebuild/axis_b_real_measurement.md` v4 (100-doc 재측정).
Reference: doc-A v4 (`m4a_doc_a_outline.md` — α' v2 13/13 PASS), doc-B v4 (`m4a_doc_b_outline.md` — 13/13 PASS, doc-A 패턴 reuse).
Date: 2026-05-17 (v2 — distractor 13 가드 + doc-A/B 학습 사전 적용).
Stage: **sub-STOP 1 (v2)** (outline distractor 갱신 → user review → sub-STOP 2a v1 신규 합성).

## v2 변경점 (vs v1, 2026-05-17)

- distractor 박제 진입 (γ-lite sub-STOP 1.5 → doc-A/B retro 후 doc-C 신규)
- 가드 8개 → **13개** (1-8 기존 + 9-13 distractor: positive/topical/lexical/counterfactual/near-dup)
- 가드 8 임계: `≤ 0.3113` (v1, axis B 18-doc) → **`≤ 0.3171`** (axis B real 100-doc p75 31.10% + bootstrap 95% CI upper margin 0.61%p; `distractor_definitions.md` §5.2/§6.1 v3 박제)
- 가드 8 한글-only 측정 명시 (전체 char 기준 금지)
- §3.5 distractor anchor matrix 신규 추가 (topical 5쌍 / lexical 8 variant / counterfactual ≥ 3 / near-dup ≥ 5)
- §3.2 negative anchor word-boundary regex 사전 검토 (doc-B 에서 "기관 A" substring false positive 발견 사례 reuse)
- metadata.axis_a_scale: `real_scale_v1` → **`real_scale_v2_distractor`**
- sub-STOP 2c 합본 후 α' v2 (25-template × 1 sentence with heading inject) 패턴 사전 적용 — doc-A/B 채택 사례 reuse
- doc-A/B 학습 사전 적용: cps 280-300 사전 설계 / lexical trivial 회피 (positive substring 안 lexical 박제 금지) / schema heading 통일

## 0. doc-C 원본 + plan target

원본 `data/raw/rfp_agency_c_chatbot.json` (3 sec / ~440 chars / 0 표):
- title: "기관 C 고객지원 챗봇 고도화 RFP"
- agency: "기관 C", project: "고객지원 챗봇 고도화"
- project_aliases: ["챗봇 고도화", "고객지원 챗봇"]
- domain: "chatbot"
- 사업 개요 / AI 요구사항 (한국어 FAQ 검색·의도 분류·상담 이관 추천·평균 2초 이내) / 평가 및 운영 (답변 정확도·상담 이관 적절성·사용자 만족도·월간 리포트)

Plan v3 target (M4-A 표 row 56):
| chars | sections | cps | tables_cell | tables_block |
|---:|---:|---:|---:|---:|
| 28,000 | 100-110 | ~280-330 | 100-120 | 70-80 |

## 1. doc-C 신규 schema (5 필드 보존, sections 만 확장)

```json
{
  "doc_id": "rfp-agency-c-chatbot",
  "title": "기관 C 고객지원 챗봇 고도화 RFP",
  "agency": "기관 C",
  "project": "고객지원 챗봇 고도화",
  "metadata": {
    "domain": "chatbot",
    "document_type": "synthetic_public_sample",
    "axis_a_scale": "real_scale_v2_distractor",
    "axis_a_scale_anchor": "Upstage heading1 (main heading) median ~100 + kordoc 39511 chars cross-check",
    "axis_a_scale_measurement_ref": "docs/eval/axis-a-rebuild/axis_b_real_measurement.md v4 (100-doc 재측정)",
    "axis_a_scale_distractor_ref": "docs/eval/axis-a-rebuild/distractor_definitions.md v3 (bootstrap CI margin + topical dict, 2026-05-17)",
    "axis_a_scale_outline_ref": "docs/eval/axis-a-rebuild/m4a_doc_c_outline.md v2 + m4a_doc_c_partial_2a_v1.json + m4a_doc_c_partial_2b_v1.json + m4a_doc_c_full_v2.json",
    "project_aliases": ["챗봇 고도화", "고객지원 챗봇"],
    "section_definition": "main_heading (Upstage heading1 등가, chapter+section level, sub-bullet 미포함)"
  },
  "sections": [ ... 100-110개 main heading ... ]
}
```

- 기존 5 top-level 필드 (doc_id / title / agency / project / metadata) 보존
- 기존 3 metadata 필드 (domain / document_type / project_aliases) 보존
- axis_a_scale marker 5개 추가 (doc-A/B 와 동일 패턴)
- sections schema 불변 (heading + text), markdown 표는 text 안 inline

## 2. section group outline (총 100-110 main heading / 100-120 tables_cell / 70-80 tables_block)

각 group 의 main heading / 표 분배는 Upstage `heading1` median ~100/doc 의 **100-110%** 시뮬레이션. cps ~280-330 (kordoc 39511 / 100 = 395 의 70-83%).

### 2.1 group 분배표

| group | main headings | chars (kor) | cps | tables_cell | tables_block | sub-STOP |
|---|---:|---:|---:|---:|---:|---|
| §2.2 사업 개요 | 11-13 | 3,300-3,800 | ~300 | 11-13 | 7-9 | 2a |
| §2.3 추진 배경 및 필요성 | 9-11 | 2,700-3,200 | ~300 | 10-12 | 6-8 | 2a |
| §2.4 사업 범위 | 13-15 | 3,800-4,400 | ~300 | 13-15 | 9-11 | 2a |
| §2.5 기능 요구사항 (FR) | 15-17 | 5,200-5,800 | ~340 | 20-24 | 14-17 | 2a |
| §2.6 비기능 요구사항 (NFR) | 11-13 | 3,200-3,800 | ~300 | 15-18 | 10-12 | 2b |
| §2.7 데이터 및 보안 | 10-12 | 3,000-3,500 | ~300 | 12-14 | 8-10 | 2b |
| §2.8 일정 및 산출물 | 8-10 | 2,200-2,700 | ~280 | 8-10 | 5-7 | 2b |
| §2.9 평가 및 운영 | 10-12 | 3,000-3,500 | ~300 | 10-13 | 7-9 | 2b |
| §2.10 부속서 | 6-8 | 1,800-2,300 | ~280 | 5-8 | 4-6 | 2b |
| **합계** | **93-111** | **28,200-33,000** | **~290-330** | **104-127** | **70-89** | |

→ 중간값 **102 main heading / 30,600 chars / 300 cps / 116 tables_cell / 80 tables_block**. axis B Upstage heading1 median ~100 의 ~102% (정확 anchor).

### 2.2 사업 개요 (~12 main heading, ~3,500 chars + ~12 표) — sub-STOP 2a

main heading 예시 (각각 ~290 chars body + 표 inline):
- 사업 명칭 및 발주 기관 (anchor: "기관 C", "고객지원 챗봇 고도화")
- 사업 개요 (anchor §원본 본문: "고객지원 챗봇 고도화", "반복 문의", "자동 처리", "상담원 이관 기준")
- 사업 추진 의의 및 배경
- 사업 목적 및 기대효과
- 사업 추진 체계 및 거버넌스
- 사업 추진 원칙 및 의사결정 구조
- 사업 KPI 정의 및 핵심 지표 (anchor: "답변 정확도", "상담 이관 적절성", "사용자 만족도" 사전 언급 가능)
- 사업 리스크 개요
- 사업 범위 요약 (§2.4 로의 연결)
- 사업 추진 전략 요약
- 사업 결과물 요약 (§2.8 로의 연결)
- 사업 종료 후 운영 체계 (anchor: "월간 리포트" 사전 언급 가능)

- positive anchor: "기관 C", "고객지원 챗봇 고도화", project_aliases "챗봇 고도화", "고객지원 챗봇", "반복 문의", "상담원 이관 기준"
- **chunk-001 강제 anchor**: §2.2 초반 main heading 안에 "2초", "주요 문의" 자연스럽게 사전 언급 가능 (F.U. case `follow_up_c_response_target` 가 chunk-001 매칭 보장). 단 본 매칭은 §2.6 NFR 의 응답시간 절을 포함하는 chunking 결과에 의존 — overlap chunking 시 처음 chunk 가 §2.6 까지 포함 가능. 안전책: §2.2 KPI heading 에서 "2초" + "주요 문의" 도 1회 paraphrase 없이 등장.

### 2.3 추진 배경 및 필요성 (~10 main heading, ~2,900 chars + ~11 표) — sub-STOP 2a

main heading 예시:
- 정책 환경 분석 (정부 디지털 민원 정책 / 공공기관 챗봇 도입 가이드라인)
- 내부 운영 환경 분석 (SWOT / 기존 챗봇 한계 / 상담원 부담 수치)
- 시장 동향 및 벤치마킹 (국내 콜센터 챗봇 / 글로벌 LLM 챗봇)
- 표준 동향 (KCC 챗봇 운영 가이드 / KOLAS / TTA)
- 사업 추진 필요성 종합 및 우선순위
- 이해관계자 요구 및 Pain Point (고객 / 상담원 / 운영팀)
- 추진 시 리스크 분석
- 정책 정합성 확보 방안
- 외부 감사 대응 방안
- 변화 관리 전략

### 2.4 사업 범위 (~14 main heading, ~4,000 chars + ~14 표) — sub-STOP 2a

main heading 예시:
- 사업 범위 개요 (기능/비기능/데이터/인프라/외부연계/산출물)
- 기능적 범위 분류
- 비기능적 범위 분류
- **AI 요구사항 개요** (anchor: "한국어 FAQ 검색", "의도 분류", "상담 이관 추천")
- 데이터 범위 (FAQ DB / 대화 로그 / 의도 라벨 / 학습 데이터)
- 인프라 범위
- 외부 연계 범위 (CRM / 콜센터 / 인증 / 알림)
- 사업 제외 범위
- 단계별 범위 (1차/2차/3차)
- 산출물 범위 종합 및 의존성
- 위탁 범위 / 직접 수행 범위
- IP 귀속 및 라이선스 범위
- 협력 및 인수인계 범위
- 사용자 그룹 및 권한 범위
- positive anchor: "한국어 FAQ 검색", "의도 분류", "상담 이관 추천"

### 2.5 기능 요구사항 FR (~16 main heading, ~5,500 chars + ~22 표) — sub-STOP 2a

각 FR main heading 은 acceptance criteria 본문 + 표 inline. sub-bullet 은 body 안 list 로 inline.

main heading 예시:
- FR 전체 구조 및 ID 매트릭스
- FR-001 한국어 FAQ 검색 엔진 (anchor: "한국어 FAQ 검색")
- FR-002 의도 분류 모델 (anchor: "의도 분류")
- FR-003 상담 이관 추천 엔진 (anchor: "상담 이관", "상담 이관 추천")
- FR-004 다중 턴 대화 컨텍스트 관리
- FR-005 fallback / 미해결 시나리오 처리
- FR-006 다이얼로그 흐름 관리
- FR-007 슬롯 충진 및 엔티티 추출
- FR-008 답변 템플릿 관리
- FR-009 운영자 콘솔 및 대시보드
- FR-010 챗봇 학습 데이터 관리 (FAQ 추가 / 의도 라벨 추가)
- FR-011 외부 시스템 연동 (CRM / 인증 / 알림)
- FR-012 배포 및 롤백
- FR-013 알람 정책 관리
- FR-014 보고서 / Export (anchor: "월간 리포트" 1회 등장 가능)
- FR-015 챗봇 카드 / 메타데이터
- FR-016 모델 / FAQ / 의도 버전 추적

### 2.6 비기능 요구사항 NFR (~12 main heading, ~3,500 chars + ~18 표) — sub-STOP 2b

main heading 예시:
- NFR 전체 구조 및 매트릭스
- **성능 (anchor: "평균 2초 이내", "주요 문의", 동시접속, 처리량)**
- 보안 (K-ISMS-P / 암호화 / 망분리)
- 보안 통제 매트릭스
- **가용성 (운영 가능 시간 / 서비스 연속성 / 장애 대응 시한)** ← **"SLA" 약어 부재 필수** (abstention_c_availability)
- 확장성 (horizontal scale / multi-tenant)
- 운영 (모니터링 / 백업 / 장애 대응)
- 운영 인력 요구
- 호환성 (OS / 브라우저 / 모바일)
- 유지보수성 및 접근성
- 표준 준수 (KCC 챗봇 운영 가이드 / TTA 표준 연계)
- NFR 시험 및 검증 절차

- positive anchor: "평균 2초 이내", "주요 문의" (F.U. case `follow_up_c_response_target` 의 expected_terms)
- **negative anchor (필수)**: "SLA" 약어 본문 / 표 / 부속서 어디에도 등장 금지. "서비스 수준 협약" 등 풀어쓰기도 회피하고 "운영 가능 시간" / "서비스 연속성" / "장애 대응 시한" 으로만 표현.

### 2.7 데이터 및 보안 (~11 main heading, ~3,200 chars + ~13 표) — sub-STOP 2b

main heading 예시:
- 데이터 분류 및 보호 등급 (FAQ DB / 대화 로그 / 의도 라벨)
- 개인정보 비식별화 / 마스킹
- 개인정보 처리 방침
- 데이터 라이프사이클 관리
- 데이터 보존 기간 및 폐기 (대화 로그 / 의도 라벨 / FAQ 변경 이력)
- 보안 통제 운영 절차
- 보안 감사 및 교육 주기
- 침해 사고 대응 단계 및 보고 시한
- 보안 패치 및 취약점 점검
- 데이터 백업 및 이동 보안
- 데이터 폐기 검증

### 2.8 일정 및 산출물 (~9 main heading, ~2,500 chars + ~10 표) — sub-STOP 2b

main heading 예시:
- 추진 일정 개요
- 단계별 일정 (착수 / 설계 / 구현 / 검수)
- 단계 전환 기준 및 마일스톤
- 단계별 산출물 분류
- 필수 산출물 (FAQ DB / 의도 분류 모델 / 상담 이관 정책서 / 운영자 매뉴얼)
- 산출물 상세 및 검수 기준
- 산출물 IP / 라이선스 / form factor
- 산출물 인계 절차
- 운영 전환 절차

### 2.9 평가 및 운영 (~11 main heading, ~3,200 chars + ~11 표) — sub-STOP 2b

main heading 예시:
- 평가 기준 종합 및 가중치
- 평가 절차
- 정량 평가 항목 및 배점
- **운영 지표 종합 (anchor: "운영 지표", "답변 정확도", "상담 이관 적절성", "사용자 만족도")**
- **답변 정확도 측정 방법론 (anchor: "답변 정확도")**
- 상담 이관 적절성 측정 방법론 (anchor: "상담 이관 적절성")
- 사용자 만족도 측정 방법론 (anchor: "사용자 만족도")
- **운영 로그 및 리포트 (anchor: "운영 로그", "월간 리포트")**
- 수행 조직 요건 (PM / NLP 엔지니어 / 챗봇 trainer / 운영 담당자)
- 직무별 인력 요구 및 자격
- 제안서 작성 / 제출 / 평가 일정

- positive anchor: "답변 정확도", "상담 이관 적절성", "사용자 만족도", "월간 리포트", "운영 로그", "운영 지표"

### 2.10 부속서 (~7 main heading, ~2,100 chars + ~7 표) — sub-STOP 2b

- 용어 정의 (FR / NFR / FAQ / 의도 분류 / 상담 이관 / fallback / dialog flow)
- 약어 (다수, **"SLA" 제외** — 약어 목록에 SLA 등록 금지)
- 참고 표준 (KCC / TTA / ISO 9241 / OWASP)
- 부속 양식 안내
- 변경 이력
- 작성자 / 검토자 / 승인 정보
- 추가 안내사항

### 2.11 표 크기 분포 (총 ~116 tables_cell / ~80 tables_block)

| 크기 | 개수 (cell unit) | row × col | 평균 chars/표 | 총 chars |
|---|---:|---|---:|---:|
| 작은 표 | 48 | 2-3 × 2-3 | ~80 | ~3,840 |
| 중간 표 | 48 | 4-7 × 3-4 | ~180 | ~8,640 |
| 큰 표 | 20 | 8+ × 4+ | ~380 | ~7,600 |
| 합계 | 116 | | | ~20,080 |

본문 chars 30k + 표 chars 20k + heading/숫자/JSON overhead 5k = **~55k total chars output**. Claude extended-output 한계 내 안전 (doc-A 합성 결과 ~26k 후속 합성도 통과).

## 3. Anchor preservation 매핑 표

### 3.1 Positive anchor (정확 표현 보존 필요, paraphrase 금지)

| anchor (정확 표현) | 등장 group | 의존 case (eval/config.yaml line) |
|---|---|---|
| "기관 C" | 전 group | 모든 doc-C case (L460/L593/L722/L740/L816/L876/L938/L1376/L1391/L1405/L1564/L1726/L1743/L1837 등) |
| "고객지원 챗봇 고도화" | §2.2 | L1376 (`기관 C 챗봇 고도화 사업의 목표는?`) |
| project_aliases "챗봇 고도화" | metadata + §2.2 sample | L1376 |
| project_aliases "고객지원 챗봇" | metadata + §2.2 sample | L1376 |
| "한국어 FAQ 검색" | §2.4 AI 요구사항 개요, §2.5 FR-001 | (원본 RFP 핵심 anchor, 후속 case 확장 시 필수) |
| "의도 분류" | §2.4, §2.5 FR-002 | L1749 (`기관 B와 기관 C의 AI 기술 요구사항을 비교해줘`) |
| "상담 이관" | §2.4 FR-003, §2.2 KPI | L465/L729/L732 (`기관 C의 챗봇 응답 시간 목표는?`, `기관 A와 기관 C의 AI 요구사항 초점 차이는?`) |
| "상담원 이관" | §2.2 사업 목적, §2.4 AI 요구사항 개요, §2.5 FR-003 | L1842 (`follow_up_c_project_goal` — `이 사업의 목표가 뭐야?` "반복 문의" + "상담원 이관" exact match) |
| "상담 이관 추천" | §2.4, §2.5 FR-003 | (원본 RFP) |
| "상담 이관 적절성" | §2.9 운영 지표 | L598/L943 (`기관 C가 운영 지표로 사용하는 항목은?`, `기관 C의 운영 지표 세 가지는?`) |
| "2초" | §2.2 KPI, §2.6 성능 | L464/L880/L1395/L1398 (`기관 C의 챗봇 응답 시간 목표는?`, `follow_up_c_response_target`, `기관 C 챗봇의 응답 속도 목표는?`) |
| "주요 문의" | §2.2 KPI, §2.6 성능 | L881/L887 (`follow_up_c_response_target` chunk-001 강제 매칭) |
| "답변 정확도" | §2.9 운영 지표, 측정 방법론 | L597/L601/L610/L942/L949 |
| "사용자 만족도" | §2.9 운영 지표, 측정 방법론 | L821/L824 (`comparison_one_sided_chatbot_focus`) + 원본 RFP |
| "운영 지표" | §2.9 운영 지표 종합 | L595 (`기관 C가 운영 지표로 사용하는 항목은?`) |
| "운영 로그" | §2.9 운영 로그 및 리포트 | (원본 RFP) |
| "월간 리포트" | §2.9 운영 로그 및 리포트, §2.5 FR-014 | L1409/L1411/L1732/L1735 (`기관 C 운영 로그의 제출 주기는?`, `기관 B와 기관 C의 보고 방식을 비교해줘`) |

→ **17 positive anchor 모두 정확 표현 보존**. 합성 시 paraphrase 금지 (`must_include` / `expected_terms` 가 exact match).

⚠️ "상담 이관" vs "상담원 이관" 은 **substring 으로 겹치나 별개 anchor**:
- "상담 이관" — 챗봇 → 상담원으로 문의를 이관하는 행위
- "상담원 이관" — `follow_up_c_project_goal` 의 expected_terms exact match. "상담원 이관 기준" 처럼 자연어 안에 등장하면 두 anchor 모두 자동 매칭됨.
→ 합성 시 "**상담원 이관 기준**" / "**상담원 이관 정책**" / "**상담원 이관 추천**" 등 "상담원 이관" 을 포함하는 표현을 §2.2 / §2.4 / §2.5 FR-003 에서 자연스럽게 사용.

### 3.2 Negative anchor (부재 유지, word-boundary regex 사전 검토)

| 부재 키워드 | measurement 식 | 의존 case |
|---|---|---|
| **"SLA"** | `re.findall(r"\bSLA\b", text)` (영문 word boundary) | **abstention_c_availability (L2030)** — 약어 본문/표/부속서 어디에도 금지. 풀어쓰기 ("서비스 수준 협약") 도 회피 권장. |
| "결제" | `re.findall(r"결제(?![가-힣])", text)` (한글 뒤 negative lookahead — "결제일/결제계좌/결제수단" 같은 복합어도 금지 효과) | abstention_missing_payment (L1038) — `기관 C의 결제 기능 연동 요구사항은?` |
| "블록체인" / "blockchain" | substring (단어 충분히 길어 우연 매치 없음) | 공통 negative (다른 doc 의 abstention) |
| "양자암호" | substring | 공통 negative |
| "드론" | substring | 공통 negative |
| "기관 A" / "기관 B" / "기관 D" | `re.findall(r"기관 [ABD](?![가-힣A-Za-z])", text)` (word boundary; doc-B 실측 사례 reuse — "공공기관 AI" substring false positive 회피) | 다른 doc 와 혼동 금지 (오타 방지) |

→ **8 negative anchor 모두 신규 corpus 에 등장 금지** (5개 기존 + "기관 A/B/D" 3개 추가, word-boundary 적용).

**위험 영역 사전 검토**:
- `§2.4 외부 연계 범위` 에서 "결제" 등장 위험 — 외부 연계 예시는 CRM / 콜센터 / 인증 / 알림 / 메시징으로만 한정.
- `§2.6 가용성 / §2.10 약어` 에서 "SLA" 등장 위험 — heading 자체에서 "SLA" 단어 금지, "운영 가능 시간" / "서비스 연속성" / "장애 대응 시한" 으로만 표현.
- `§2.3 정책 환경 분석` 에서 "공공기관 AI" substring 우연 매치 위험 — doc-B 사례 reuse 하여 "공공기관의 AI" (조사 '의' 추가) 로 사전 회피.

### 3.3 Comparison anchor (multi-doc comparison case)

| comparison axis | doc-C side anchor |
|---|---|
| A vs C AI 요구사항 초점 (L722) | "챗봇" + "상담 이관" 강조 (§2.4) |
| B vs C 운영 지표 / 모니터링 (L740) | "답변 정확도" 강조 (§2.9) |
| B vs C 사용자 만족도 (L816) | "사용자 만족도" 강조 (§2.9). doc-B 측 "모니터링 대시보드" anchor 는 doc-C 와 무관. |
| C vs D 사업 목표 (L1564) | "챗봇" 강조 (§2.2) |
| B vs C 보고 방식 (L1726) | "월간 리포트" 강조 (§2.9) |
| B vs C AI 기술 요구사항 (L1743) | "의도 분류" 강조 (§2.4, §2.5 FR-002) |

### 3.4 Multi-step (multi-hop) anchor

| qid (multi_step) | doc-C side anchor |
|---|---|
| L1837 (multi_step / nested compare) | "기관 C" + 다른 doc 비교 (자세한 anchor 는 config.yaml inspect 필요) |

### 3.5 Distractor anchor matrix (v2, doc-C 맞춤)

#### topical distractor (t1-t5)

| # | 정답 anchor | 박제 위치 | topical 비-정답 표현 | 박제 위치 |
|---|------------|-----------|---------------------|-----------|
| t1 | "월간 리포트" | §2.9 운영 로그 및 리포트 | "월간 통계 Export" | §2.5 FR-014 (보고서/Export) |
| t2 | "답변 정확도" | §2.9 운영 지표 | "응답 품질 지표" | §2.6 NFR 성능 |
| t3 | "한국어 FAQ 검색" | §2.4 AI 요구사항 / §2.5 FR-001 | "FAQ 카탈로그 검색" | §2.7 데이터 분류 |
| t4 | "의도 분류" | §2.4 / §2.5 FR-002 | "의도 라벨 관리" | §2.7 데이터 / §2.5 FR-010 |
| t5 | "상담 이관" | §2.4 / §2.5 FR-003 | "상담 분배 정책" | §2.4 외부 연계 / §2.7 |

`TOPICAL_KEYWORDS_DOC_C = {`
- `'t1': ["월간 통계 Export"],`
- `'t2': ["응답 품질 지표"],`
- `'t3': ["FAQ 카탈로그 검색"],`
- `'t4': ["의도 라벨 관리"],`
- `'t5': ["상담 분배 정책"],`

`}`

#### lexical distractor (l1-l8)

| # | 정답 표현 | lexical variant (모두 박제, ≥ 6 등장 필수) |
|---|-----------|-------------------------------------------|
| l1 | "답변 정확도" | "응답 정확률" (1글자 변형) |
| l2 | "상담 이관" | "상담배정" (의역, substring 충돌 없음) |
| l3 | "고객지원 챗봇" | "고객지원챗봇" (no-space variant) |
| l4 | "한국어 FAQ 검색" | "한국어FAQ 검색" (no-space variant) |
| l5 | "운영 로그" | "운영 기록" (suffix 변형) |
| l6 | "PM" | "프로젝트 매니저" |
| l7 | "NLP 엔지니어" | "자연어처리 엔지니어" (한글 의역) |
| l8 | "운영 담당자" | "운영자" (축약, substring 충돌 없음 — "운영 담당자" 안에 "운영자" 미포함) |

`DOC_C_LEXICAL_VARIANTS = ['응답 정확률', '상담배정', '고객지원챗봇', '한국어FAQ 검색', '운영 기록', '프로젝트 매니저', '자연어처리 엔지니어', '운영자']`

⚠️ lexical 측정 trivial 회피 (doc-B 사례 reuse):
- l1 "응답 정확률" / l2 "상담배정" / l5 "운영 기록" / l7 "자연어처리 엔지니어" — 정답과 char-level 다른 표현, substring 충돌 없음
- l3 "고객지원챗봇" / l4 "한국어FAQ 검색" — no-space variant, 정답 (with space) 와 char-level 분리
- l6 "프로젝트 매니저" — positive "PM" (영문 2글자) 의 한글 풀어쓰기, 별도 inject 필수
- l8 "운영자" — positive "운영 담당자" 안에 미포함 (substring 매치 안 됨), 별도 inject 필수

#### counterfactual 박제 (≥ 3, distractor_definitions.md §2.3 예시 reuse)

§2.10 부속서 "응답 시간 목표 및 운영 지표 변경 이력" main heading 신규 추가 시 다음 token 들 ≥ 3회:
- "초안" / "1차 변경" / "최종" / "변경 이력" / "구버전" / "신버전" / "폐기" / "대체" / "이전"

예시 (distractor_definitions.md §2.3 reuse + 산출물 변경 추가):
- "초안 (2024-01): 응답 시간 목표 3초 이내, 운영 지표 4종 (응답 시간 / 답변 정확도 / FAQ 적중률 / 상담사 만족도)"
- "1차 변경 (2024-03): 응답 시간 목표 2.5초 이내, 운영 지표 3종 (답변 정확도 / 상담 이관 적절성 / 사용자 만족도)"
- "최종 (2024-06): 응답 시간 목표 평균 2초 이내, 운영 지표 3종 (답변 정확도 / 상담 이관 적절성 / 사용자 만족도), 리포트 주기 월간 리포트 확정. 구버전 (4종 분류) 은 폐기 처리되어 신버전 분류로 대체"

→ counterfactual chunk 안에 정답 (2초 / 3종 / 월간) + 잘못된 값 (3초 / 4종) 동시 등장. retrieval 이 변경 이력 chunk 를 retrieve 하면 verifier 가 "초안" / "구버전" 토큰으로 counterfactual 식별 가능.

#### near-duplicate (n1-n5, 문장 Jaccard 3-gram ≥ 0.8)

FR-001~016 의 16개 FR section 들의 acceptance criteria 1 sentence 가 거의 동일 패턴으로 작성됨 (예: "본 FR-XXX 의 acceptance 시 단위 시험과 통합 시험을 동시에 통과한다. 시정 결과는 부속서에 등재한다."). near-duplicate pair 자연 생성 ≥ 5 (16C2 = 120 pair 가능, 임계 ≥ 5 안전).

대체 박제 가능: NFR 영역별 acceptance 동일 패턴 (NFR-성능 / NFR-보안 / NFR-가용성 / ...). 단 doc-C 의 NFR 은 영역 분류만 (ID 부여 없음) 이므로 FR 패턴 채택 권장.

## 4. 합성 가드 (acceptance, v2 distractor — 13 가드)

| # | 가드 | 검증 방법 | 기준값 |
|---|---|---|---:|
| 1 | sections (main heading) | `len(d['sections'])` | ≥ 95 (target 100-110) |
| 2 | total chars | `len(all_text)` | (info) |
| 3 | Korean chars | `len([c for c in text if '가'<=c<='힣'])` | ≥ 22,000 (target 28,000) |
| 4 | GFM separator rows | `re.findall(r'^\|[\s\-:|]+\|$', text, re.M)` | ≥ 70 (target 116) |
| 5 | table count (≈ separator) | (same) | (info) |
| 6 | kor chars / section | `kor_chars / sections` | 200-450 (target ~290) |
| 7 | (= guard 8) reserved | — | — |
| 8 | **5-gram dup (kor-only, v4 bootstrap CI margin)** | `korean = "".join(c for c in text if "가"<=c<="힣"); grams=[korean[i:i+5] for i in range(len(korean)-4)]; (len(grams)-len(set(grams)))/len(grams)` | **≤ 0.3171 (axis B real 100-doc p75 31.10% + bootstrap 95% CI upper margin 0.61%p)** |
| 9 | 17 positive anchor 정확 표현 | `for kw in POSITIVES: assert kw in text` | 모두 PASS |
| 10 | topical distractor pair ≥ 5 | `topical_count(text, TOPICAL_KEYWORDS_DOC_C)` ≥ 5 — §3.5 박제 dict | ≥ 5 (t1-t5) |
| 11 | lexical distractor variant ≥ 6 | `sum(1 for v in DOC_C_LEXICAL_VARIANTS if v in text)` | ≥ 6 |
| 12 | counterfactual 박제 ≥ 3 | `sum(text.count(t) for t in COUNTERFACTUAL_TOKENS)` | ≥ 3 |
| 13 | near-duplicate sentence pair (Jaccard 3-gram ≥ 0.8) ≥ 5 | `near_duplicate_count(text, 0.8)` | ≥ 5 |
| neg | 8 negative anchor 부재 (word-boundary, §3.2 박제 regex) | `for pat in NEGATIVES_REGEX: assert len(re.findall(pat, text))==0` | 0/8 |

## 5. 합성 budget 추정

### 5.1 multi-turn sub-STOP 분할 (doc-A/B 와 동일 패턴)

- sub-STOP 2a: §2.2-2.5 main heading **~52** / chars **~16,000** / 표 ~60 / 표 chars ~10,000 → output ~28,000 chars
- sub-STOP 2b: §2.6-2.10 main heading **~50** / chars **~14,000** / 표 ~56 / 표 chars ~10,000 → output ~25,000 chars
- sub-STOP 3: 합본 + acceptance + sample review

각 sub-STOP 의 output 25-28k chars 는 Claude extended-output 한계 내 안전 (doc-A/B 실측 검증).

### 5.2 doc-A/B 학습된 design rule (사전 적용, v2 갱신)

- **cps 280-300 으로 sub-STOP 2a 부터 두꺼운 body 설계** (doc-B 1차 cps 219 → expansion 후 295 의 시행착오 회피).
- **본문 paragraph 2개 + GFM 표** (doc-A/B 합본 후 α' v2 25-template heading inject 로 dup 안정화) — sub-STOP 2c 시점에서 α' inject 적용.
- **5-gram dup 자연 발생 ~20-30% 예상** + α' inject 후 ~27-31% (doc-A α' v2 31.51% / doc-B α' v2 29.24%). v4 임계 31.71% 안에서 안전.
- **negative anchor "SLA" 사전 회피** — outline 단계에서 §2.6 / §2.10 heading 에 "SLA" 단어 금지, 합성 시 운영 가능 시간 / 서비스 연속성 / 장애 대응 시한으로만 표현.
- **negative anchor "기관 A/B/D" word-boundary 사전 적용** — 본문 "공공기관 AI" 같은 substring 우연 매치 회피 위해 "공공기관의 AI" (조사 '의' 추가) 로 사전 회피.
- **lexical trivial 회피 (doc-B 사례 reuse)** — l1~l8 모두 정답 표현과 char-level 분리 (l2 "상담배정" / l5 "운영 기록" / l8 "운영자" 등 substring 우연 매치 없도록 사전 설계).
- **schema heading 통일** — 2a / 2b 모두 `heading` field 사용 (doc-A 의 title vs heading 혼재 silent measurement bug 회피).

## 6. sub-STOP 구성 (v2)

| STOP | scope | 산출물 | 가드 검증 시점 |
|------|-------|--------|---------------|
| 1 v2 | distractor 박제 outline 갱신 | `m4a_doc_c_outline.md` v2 (본 갱신) | — |
| 2a v1 | §2.2~§2.5 사업/배경/범위/FR (~54 sec, distractor 6 inject 포함) | `m4a_doc_c_partial_2a_v1.json` | 2a 단독 가드 일부 + 2b 합본 후 13 가드 전체 |
| 2b v1 | §2.6~§2.10 NFR/보안/일정/평가/부속서 (~50 sec, distractor inject + sec 51 신규 변경 이력 부속서) | `m4a_doc_c_partial_2b_v1.json` | 합본 후 13 가드 전체 |
| 2c α' v2 | 합본 + α' 25-template × 1 sentence heading inject | `m4a_doc_c_full_v2.json` | 13/13 PASS 목표 |
| 3 promote | data/raw 갱신 + verdict 박제 | `data/raw/rfp_agency_c_chatbot.json` 갱신 (LIVE) | live 13 가드 final |

## 7. doc-A vs doc-B vs doc-C 패턴 차이 (정직 박제)

| 항목 | doc-A | doc-B | doc-C |
|------|-------|-------|-------|
| domain | AI 품질 | MLOps | chatbot |
| project_aliases | 품관플 / AI품플 | 엠엘옵스 자동화 / 데이터 MLOps | 챗봇 고도화 / 고객지원 챗봇 |
| live pre-distractor | 104 sec v1 (backup) | 104 sec v1 (backup) | **3 sec original** (신규 합성 필요) |
| positive anchor 수 | 16 | 17 | 17 |
| negative anchor 수 | 4 (substring) | 5 (4 substring + 1 wb) | **8 (5 + wb 3개 추가)** |
| §2.6 분류 | NFR 7대 영역 | NFR-001~008 ID | NFR 영역 분류 (ID 없음) |
| 일정 단계 표현 | "MVP 4개월·최종 검수 6개월" | "파일럿 3개월·운영 전환 5개월" | (구체 단계 없음, 도메인 특수) |
| topical 핵심 | 보안/품질/MVP | 거버넌스/MLOps/lineage/감사 | 챗봇/FAQ/상담 이관/운영 지표 |
| lexical 핵심 | 품질지표 변형 / AI 한글 음역 | 데이터 거버넌스/MLOps no-space / 인력 명칭 | 답변 정확도/상담 이관 의역 / no-space variant |
| near-dup 패턴 | FR-NNN acceptance 변형 | NFR-001~008 acceptance 동일 | FR-001~016 acceptance 동일 |

→ doc-A/B 패턴 reuse 가능하나 위 차이 사항은 doc-C 합성 시 explicit 박제 필요. 특히 (1) live 신규 합성, (2) negative 8개 (word-boundary 3개), (3) NFR ID 없음, (4) 일정 단계 표현 부재 가 doc-A/B 와 다름.

## 8. 진행 결정 (사용자 confirm 대기)

본 outline v2 박제 = M4-A doc-C 의 **sub-STOP 1 (v2)** 완료. 다음 step 후보:

- (i) **sub-STOP 2a v1 신규 합성** — §2.2-2.5 의 ~54 main heading / ~16k kor chars / ~55 표 / cps ~290 / distractor 6 inject (l1~l5 + t3/t4/t5 일부 cross-link). doc-A/B 학습 사전 적용. *권장*
- (ii) outline v2 미세 조정 후 (i) — distractor matrix anchor 추가/누락 / lexical variant 교체
- (iii) topical/lexical 사전 합의 추가 — 예: l8 "운영자" 가 너무 일반적이라 다른 표현으로 교체 필요 시

본 sub-STOP 1 (v2) 종료. 사용자 review 대기.
