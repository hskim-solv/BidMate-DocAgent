# doc-B (rfp_agency_b_mlops_governance) — Sub-STOP outline v4

- doc_id: `rfp-agency-b-mlops-governance`
- title: 기관 B 데이터 거버넌스 및 MLOps 자동화 RFP
- agency: 기관 B
- project: 데이터 거버넌스 및 MLOps 자동화
- domain: MLOps
- project_aliases: `엠엘옵스 자동화`, `데이터 MLOps`
- live path: `data/raw/rfp_agency_b_mlops_governance.json`
- live backup: `data/raw/rfp_agency_b_mlops_governance.v1_pre_distractor.json` (104 sections, pre-distractor 시점)
- partial source: `docs/eval/axis-a-rebuild/m4a_doc_b_partial_2a.json` (54 sec, v3 pre-distractor) + `m4a_doc_b_partial_2b.json` (50 sec, doc-A pattern pre-distractor)
- outline pattern source: `docs/eval/axis-a-rebuild/m4a_doc_a_outline.md` v4 (doc-A 와 동일 패턴, doc-B keyword swap)

## v4 변경점 (vs doc-A 패턴 baseline, 2026-05-17)

- 가드 8 임계: **≤ 0.3171** (axis B real 100-doc p75 31.10% + bootstrap 95% CI upper margin 0.61%p; `distractor_definitions.md` §5.2/§6.1 v3 박제)
- 가드 10 (topical) 측정식: `topical_count(text, TOPICAL_KEYWORDS_DOC_B)` ≥ 5 — 본 outline §3.5 박제 dict 사용 (`distractor_definitions.md` §6.1.1 v3 박제 방식)
- 가드 8 한글-only 측정 (전체 char 기준 금지)
- sub-STOP 2c 합본 후 α' v2 (25-template × 1 sentence with heading inject) 패턴 적용 예정 — doc-A 채택 사례 reuse

## 1. doc-B 핵심 anchor 매트릭스

| 분류 | anchor | 위치 (live heading idx) |
|------|--------|------------------------|
| 사업 | 기관 B / 데이터 거버넌스 / MLOps 자동화 | §1 (0-11) |
| 사업 alias | 엠엘옵스 자동화 / 데이터 MLOps | metadata.project_aliases |
| 거버넌스 FR | FR-009 데이터 거버넌스 정책 관리 | §2.5 FR (46) |
| MLOps FR | FR-004 MLOps 자동화 파이프라인 | §2.5 FR (41) |
| lineage FR | FR-002 데이터 lineage 추적 | §2.5 FR (39) |
| 모델 모니터링 | FR-007 모델 모니터링 (drift 감지) | §2.5 FR (44) |
| 데이터 표준 | FR-001 데이터 표준 정의 및 카탈로그 | §2.5 FR (38) |
| 배포 | FR-005 모델 배포 및 롤백 | §2.5 FR (42) |
| 산출물 1 | 데이터 표준 사전 | §2.8 (79) |
| 산출물 2 | MLOps 운영 가이드 | §2.8 (80) |
| 산출물 3 | 모니터링 대시보드 | §2.8 (81) |
| 일정 단계 | 파일럿 환경 구성 (3개월) / 운영 전환 (5개월) | §2.8 (75-76) |
| NFR 감사 | NFR-008 감사 추적성 목표 | §2.6 NFR (61) |

## 2. anchor preservation (positive must_include / negative absence)

### 2.1 positive must_include (sub-STOP 2a + 2b 합본 기준, 변경 금지)
- "기관 B", "MLOps", "데이터 거버넌스", "MLOps 자동화", "엠엘옵스 자동화", "데이터 MLOps"
- "FR-001 데이터 표준 정의 및 카탈로그"
- "FR-002 데이터 lineage 추적"
- "FR-004 MLOps 자동화 파이프라인"
- "FR-007 모델 모니터링 (drift 감지)"
- "FR-009 데이터 거버넌스 정책 관리"
- "NFR-008 감사 추적성 목표"
- "데이터 표준 사전" (산출물 1)
- "MLOps 운영 가이드" (산출물 2)
- "모니터링 대시보드" (산출물 3)
- "파일럿 환경 구성"
- "운영 전환"

### 2.2 negative absence (절대 등장 금지)
- "AI 품질관리 플랫폼" (doc-A 의 project — doc-B 와 혼동 금지)
- "품관플", "AI품플" (doc-A aliases)
- "FR-013 알람 정책 관리" 의 doc-A 표현 (doc-B 도 FR-013 알람 정책 관리 가 있으므로 표현 자체는 negative 가 아님 — 하지만 "AI품플" 같은 doc-A alias 만 negative)
- "MVP 4개월" (doc-A 단계 표현 — doc-B 는 "파일럿 3개월 / 운영 전환 5개월" 사용)
- "기관 A" (오타 방지, **measurement 식: `re.findall(r"기관 A(?![가-힣A-Za-z])", text)` — word boundary 강화**; 본문 "공공기관의 AI" / "공공기관 AI/ML" 같은 substring 우연 매치 회피, 2026-05-17 박제)

## 3. acceptance 13 guards

| # | guard | 측정 식 | 임계 |
|---|-------|---------|------|
| 1 | sections (main heading 단위) | `len(d['sections'])` | ≥ 100 (target 110) |
| 2 | total chars | `len(all_text)` | (info) |
| 3 | Korean chars | `len([c for c in all_text if '가'<=c<='힣'])` | ≥ 22,000 (target 30,000) |
| 4 | GFM separator rows | `re.findall(r'^\|[\s\-:|]+\|$', all_text, re.M)` | ≥ 50 |
| 5 | table count (≈ separator) | (same) | (info) |
| 6 | kor chars / section | `kor_chars / n_sections` | 200 - 450 |
| 7 | (= guard 8) reserved | — | — |
| 8 | **5-gram dup ratio (한글-only, v4 bootstrap CI margin)** | `korean = "".join(c for c in text if "가"<=c<="힣"); grams=[korean[i:i+5] for i in range(len(korean)-4)]; (len(grams)-len(set(grams)))/len(grams)` | **≤ 0.3171 (axis B real 100-doc p75 31.10% + bootstrap 95% CI upper margin 0.61%p)** |
| 9 | positive must_include | for each anchor in §2.1: `assert anchor in text` | 모두 PASS |
| 10 | topical distractor pair ≥ 5 | `topical_count(text, TOPICAL_KEYWORDS_DOC_B)` ≥ 5 — §3.5 박제 dict | ≥ 5 (t1-t5) |
| 11 | lexical distractor variant ≥ 6 | `sum(1 for v in DOC_B_LEXICAL_VARIANTS if v in text)` | ≥ 6 |
| 12 | counterfactual 박제 ≥ 3 | `sum(text.count(t) for t in COUNTERFACTUAL_TOKENS)` | ≥ 3 |
| 13 | near-duplicate sentence pair (Jaccard 3-gram ≥ 0.8) ≥ 5 | `near_duplicate_count(text, 0.8)` | ≥ 5 |

## 3.5 distractor 박제 matrix (v4, doc-B 맞춤)

### topical distractor (t1-t5)

| # | 정답 anchor | 박제 위치 | topical 비-정답 표현 | 박제 위치 |
|---|------------|-----------|---------------------|-----------|
| t1 | "FR-009 데이터 거버넌스 정책 관리" | §2.5 FR (46) | "데이터 거버넌스 운영 규정" | §2.7 보안 (72 인근) |
| t2 | "FR-004 MLOps 자동화 파이프라인" | §2.5 FR (41) | "MLOps 운영 가이드" | §2.8 산출물 2 (80) |
| t3 | "FR-007 모델 모니터링 (drift 감지)" | §2.5 FR (44) | "모니터링 대시보드" | §2.8 산출물 3 (81) |
| t4 | "FR-002 데이터 lineage 추적" | §2.5 FR (39) | "학습 데이터셋 버전 관리" | §2.5 FR-012 (49) |
| t5 | "NFR-008 감사 추적성 목표" | §2.6 NFR (61) | "감사 로그 보존 정책" | §2.7 보안 (71) |

`TOPICAL_KEYWORDS_DOC_B = {`
- `'t1': ["데이터 거버넌스 운영 규정"],`
- `'t2': ["MLOps 운영 가이드"],`
- `'t3': ["모니터링 대시보드"],`
- `'t4': ["학습 데이터셋 버전 관리"],`
- `'t5': ["감사 로그 보존 정책"],`

`}`

### lexical distractor (l1-l8)

| # | 정답 표현 | lexical variant (모두 박제, ≥ 6 등장 필수) |
|---|-----------|-------------------------------------------|
| l1 | "데이터 거버넌스" | "데이터거버넌스" (no space) |
| l2 | "MLOps" | "엠엘옵스" (한글 음역) |
| l3 | "MLOps 자동화" | "MLOps자동화" (no-space variant) — 주: "데이터 MLOps" 는 §2.1 positive must_include (project_alias) 이므로 lexical distractor 에서 제외 (positive ↔ distractor 카운트 분리, 사용자 결정 2026-05-17) |
| l4 | "데이터 표준 사전" | "데이터표준 사전" (no-space variant) |
| l5 | "데이터 lineage" | "데이터 계보" (한글 의역 — 단, primary 정답은 lineage) |
| l6 | "PM" | "프로젝트 매니저" |
| l7 | "프로젝트 매니저" | "프로젝트 책임자" |
| l8 | "MLOps 엔지니어" | "ML 운영자" |

`DOC_B_LEXICAL_VARIANTS = ['데이터거버넌스', '엠엘옵스', 'MLOps자동화', '데이터표준 사전', '데이터 계보', '프로젝트 매니저', '프로젝트 책임자', 'ML 운영자']`

⚠️ lexical 측정 trivial 회피 (2026-05-17 사용자 결정):
- l2 "엠엘옵스" 는 positive "엠엘옵스 자동화" 안 substring 으로 자동 PASS 되면 trivial 박제이므로 **단독 등장 (예: "엠엘옵스 운영 체계") inject 별도 필수**
- l3 "MLOps자동화" no-space variant 는 positive "MLOps 자동화" (with space) 와 char-level 다름 → substring 매치 무방
- positive must_include anchor (예: "데이터 MLOps") 는 lexical variant 카운트에서 제외 — anchor 1건 두 역할 겸할 수 없음

### counterfactual 박제 (≥ 3)

§2.10 부속서 변경 이력 절 신규 추가 시 다음 token 들 ≥ 3회:
- "초안" / "최종" / "변경 이력" / "구버전" / "신버전" / "폐기" / "대체" / "이전"

예시: "MLOps 운영 가이드는 초안에서 최종까지 3회 변경 이력 등재, 구버전은 부속서에 폐기 보관"

### near-duplicate (n1-n5, 문장 Jaccard 3-gram ≥ 0.8)

NFR-001~008 의 8개 NFR section 들의 acceptance 문장이 거의 동일 패턴으로 작성됨 (예: "본 NFR-XXX 의 임계 미달 시 단계 전환 보류 사유로 처리한다. 시정 결과는 부속서에 등재한다."). near-duplicate pair 자연 생성 ≥ 5.

## 4. 합성 budget 추정 (v4)

- 110 main heading × 본문 평균 ~290 kor chars = ~32,000 kor chars
- α' v2 expansion (25-template × 1 sentence with heading inject, doc-A 채택) 추가 시 +2,000~3,000 kor chars
- 최종 expected: ~25,000~30,000 kor chars (가드 3 ≥ 22,000 PASS)
- dup expected: ~28-31% (α' v2 + heading inject; doc-A α' v2 = 31.51%, doc-B 도 유사 예상)

## 5. sub-STOP 구성

| STOP | scope | 산출물 | 가드 검증 시점 |
|------|-------|--------|---------------|
| 2a v4 | §1 사업개요 + §2.1~2.5 FR (54 sec, partial 2a 의 distractor 재합성) | `m4a_doc_b_partial_2a_v4.json` | 2a 단독 가드 일부 + 2b 합본 후 13 가드 전체 |
| 2b v1 | §2.6 NFR + §2.7 보안 + §2.8 일정·산출물 + §2.9 평가 + §2.10 부속서 (50 sec, partial 2b 의 distractor 재합성) | `m4a_doc_b_partial_2b_v1.json` | 합본 후 13 가드 전체 |
| 2c α' v2 | 합본 + α' 25-template × 1 sentence heading inject | `m4a_doc_b_full_v2.json` | 13/13 PASS 목표 |
| 3 promote | data/raw 갱신 + verdict 박제 | `data/raw/rfp_agency_b_mlops_governance.json` 갱신 | live 13 가드 final |

## 6. doc-A vs doc-B 패턴 차이 (정직 박제)

| 항목 | doc-A | doc-B |
|------|-------|-------|
| domain | AI 품질 | MLOps |
| project_aliases | 품관플 / AI품플 | 엠엘옵스 자동화 / 데이터 MLOps |
| 정답 anchor 분포 | FR-001~016 + NFR | FR-001~016 + NFR-001~008 (NFR ID 부여 — doc-A 와 차이) |
| topical distractor 핵심 | 보안/품질/MVP | 거버넌스/MLOps/lineage/감사 |
| lexical variant 핵심 | 품질지표 변형 / AI 한글 음역 / MLOps 인력 명칭 | 데이터 거버넌스/MLOps/lineage 변형 / 인력 명칭 |
| 일정 단계 표현 | "MVP 4개월·최종 검수 6개월" | "파일럿 3개월·운영 전환 5개월" |
| §2.6 분류 | NFR 7대 영역 (성능/보안/가용성/...) | NFR-001~008 ID 매트릭스 (성능/가용성/확장성/보안/운영성/호환성/무결성/감사) |

→ doc-A 패턴 reuse 가능하나 위 6개 차이는 doc-B 합성 시 explicit 박제 필요. 특히 "MVP 4개월" 표현은 doc-B 에 등장 금지 (§2.2 negative absence).
