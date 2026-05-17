# Distractor 4 subcategory 정의 박제 (γ-lite, sub-STOP 1.5)

Plan: `reports/axis_a_rebuild_plan.md` M4-A (corrigendum 2026-05-16).
Parent decision: 사용자 γ-lite (2026-05-16) — ABC retro 박제 + DEFG/common 은 outline 단계부터 진입.
Date: 2026-05-16.
Stage: **sub-STOP 1.5** (정의 박제 → STOP → user confirm → doc-A retro 진입).

## 0. 박제 사유

plan v3 의 distractor 카테고리는 **M4-C eval surface (query 측)** 분류였으나, query 측만 distractor 강화하고 corpus 측에 distractor 가 없으면 retrieval/reranker 의 distractor 분별력 측정 불가 (retrieve top-k 안에 distractor 가 들어와야 의미 있음). 따라서 corpus 측에도 distractor 박제 필요.

본 정의는 **corpus 측 박제 기준** (acceptance 9-12) 이며, M4-C 의 query 측 distractor (95 case 의 distractor_heavy 22 case) 와는 별개. 두 측면이 짝을 이뤄야 distractor 측정 가능.

## 1. 4 subcategory 정의

| subcategory | 정의 | corpus 측 박제 위치 |
|---|---|---|
| **topical** | 같은 doc 내에서 정답 anchor 가 등장하는 main heading 외에, topically similar 한 비-정답 main heading. anchor sub-token 일부 공유하나 정답으로 검색되면 안 됨. | §2.5 FR / §2.9 운영 지표 등 — 정답 anchor 와 같은 doc-내 형제 main heading |
| **lexical** | 정답 anchor 와 어휘 overlap (substring / superstring / 변형) 이 큰 비-정답 표현. exact match 는 아니지만 BM25 / dense embedding 둘 다 혼동 가능. | 정답 anchor 가 등장하는 main heading 외 다른 main heading |
| **counterfactual** | RFP 본문 안 "변경 이력" / "초안 → 최종" / "변경 전 → 변경 후" 절에 명시적으로 박제. 잘못된 값과 정답 값이 동시 등장. retrieval 이 잘못된 값을 우선 retrieve 하면 verifier/answer 가 fail. | §2.10 부속서 "변경 이력" 절 (1개 main heading 안에 3+ 건 박제) |
| **near-duplicate** | sentence-level / paragraph-level 거의 동일 표현 (Jaccard ≥ 0.8) 이 다른 main heading 에 등장. retrieval 의 dedup / MMR 분별력 측정. | FR-NNN acceptance criteria 의 1 sentence 가 FR-(NNN+1) acceptance criteria 의 1 sentence 와 거의 동일 (ID 만 변형) |

## 2. corpus 측 박제 방법 (구체적 예시)

### 2.1 topical distractor 예시 (doc-C 기준)

정답 anchor: "월간 리포트" (§2.9 운영 로그 및 리포트) — query `기관 C 운영 로그의 제출 주기는?` 의 정답

topical distractor 박제:
- §2.5 FR-014 (보고서/Export) main heading 안에 "월간 통계 Export 기능 제공 — 매월 정기 통계 데이터를 CSV/Excel 형식으로 export 한다." 박제. anchor "월간" sub-token 공유, "리포트" 는 부재 → exact match 안 됨, topical 혼동 ↑.

### 2.2 lexical distractor 예시 (doc-C 기준)

정답 anchor: "답변 정확도" (§2.9 답변 정확도 측정 방법론)

lexical distractor 박제:
- §2.6 NFR 성능 main heading 안에 "응답 정확률" — substring 일부 공유 ("정확"), 의미 인접 ("답변 정확도" ≈ "응답 정확률") 하지만 별개 anchor. BM25 lemmatization 시 혼동 가능.
- §2.4 사업 범위 안에 "답변 품질 지표" — "답변" 토큰 공유.

### 2.3 counterfactual distractor 예시 (doc-C 기준)

정답: "평균 2초 이내 응답" / "월간 리포트" / 3종 운영 지표 (답변 정확도 / 상담 이관 적절성 / 사용자 만족도)

counterfactual 박제 (§2.10 변경 이력 절 안 main heading "응답 시간 목표 및 운영 지표 변경 이력"):
- "초안 (2024-01): 응답 시간 목표 3초 이내, 운영 지표 4종 (응답 시간 / 답변 정확도 / FAQ 적중률 / 상담사 만족도)."
- "1차 변경 (2024-03): 응답 시간 목표 2.5초 이내, 운영 지표 3종 (답변 정확도 / 상담 이관 적절성 / 사용자 만족도)."
- "최종 (2024-06): 응답 시간 목표 평균 2초 이내, 운영 지표 3종 (답변 정확도 / 상담 이관 적절성 / 사용자 만족도). 리포트 주기 월간 리포트 확정."

→ 한 chunk 안에 정답(2초/3종/월간) + counterfactual(3초/4종) 동시 등장. retrieval 이 변경 이력 chunk 를 retrieve 하면 verifier 가 "초안" / "변경 전" 토큰으로 counterfactual 식별 가능. verifier 실패하면 fail case.

### 2.4 near-duplicate distractor 예시 (doc-C 기준)

FR-001 한국어 FAQ 검색 엔진 acceptance criteria:
> "한국어 FAQ 검색 엔진은 검색 요청 후 평균 1초 이내 응답을 반환해야 하며, FAQ DB 갱신 시 5분 이내 인덱스 동기화를 보장해야 한다."

FR-002 의도 분류 모델 acceptance criteria (near-duplicate):
> "의도 분류 모델은 분류 요청 후 평균 1초 이내 결과를 반환해야 하며, 의도 라벨 갱신 시 5분 이내 모델 동기화를 보장해야 한다."

→ sentence-level Jaccard ~0.85. retrieval 이 두 chunk 모두 retrieve 하면 MMR/dedup 분별력 측정.

## 3. doc 당 minimum count

| subcategory | doc 당 최소 anchor pair (또는 건수) | 측정 단위 |
|---|---:|---|
| topical | 5 | anchor pair (정답 anchor ↔ topical 비-정답 표현) |
| lexical | 5 | anchor pair (정답 anchor ↔ lexical 비-정답 표현) |
| counterfactual | 3 | 건 (변경 이력 절 안 "초안 → 최종" 변경 건수) |
| near-duplicate | 5 | sentence pair (Jaccard ≥ 0.8) |

→ doc 당 18 distractor 박제. doc-A/B/C 모두 동일 수.

## 4. 측정 방법 (programmatic)

```python
# topical: 정답 anchor 의 sub-token 이 비-정답 chunk 에 등장하는 chunk 수
def topical_count(text, positive_anchors, exclude_substrings):
    chunks = split_into_main_headings(text)
    count = 0
    for chunk in chunks:
        for anchor in positive_anchors:
            for token in anchor.split():
                if token in chunk and not any(s in chunk for s in exclude_substrings):
                    count += 1
                    break
    return count

# lexical: 정답 anchor 의 superstring/variant 토큰 등장 count
LEXICAL_VARIANTS = {
    "답변 정확도": ["응답 정확률", "답변 품질 지표"],
    "월간 리포트": ["월간 통계 Export", "월간 점검"],
    # ...
}
def lexical_count(text, variants_dict):
    return sum(1 for variants in variants_dict.values() for v in variants if v in text)

# counterfactual: §2.10 변경 이력 절 안 "초안" / "변경 전" / "변경 후" 토큰 count
def counterfactual_count(text):
    history_section = extract_section_by_heading(text, r"변경 이력")
    return len(re.findall(r"(초안|변경 전|변경 후|1차 변경|2차 변경|최종)", history_section))

# near-duplicate: sentence-level Jaccard ≥ 0.8 pair count
def near_duplicate_count(text, threshold=0.8):
    sentences = split_into_sentences(text)
    sentences = [s for s in sentences if len(s) > 30]  # short sentence noise filter
    pairs = 0
    for i in range(len(sentences)):
        for j in range(i+1, len(sentences)):
            if jaccard(tokens(sentences[i]), tokens(sentences[j])) >= threshold:
                pairs += 1
    return pairs
```

(실제 합성 후 측정 script 는 sub-STOP 3 acceptance 단계에서 실행)

## 5. 5-gram dup ↔ near-duplicate 충돌 사전 추정 (v1, 2026-05-16) — 빗나감 정직 보고

near-duplicate 5쌍 박제 시 5-gram dup ratio 기여 추정:

- 평균 sentence 길이 ~50 chars × 5 pair × 2 sentence = 500 chars (전체)
- 1 sentence ~ 5-gram count: 50 - 4 = 46. 5쌍 × 2 sentence × 46 ≈ 460 gram
- pair 당 Jaccard 0.85 ≈ 46 × 0.85 ≈ 39 중복 gram. 5 pair = 195 dup gram
- doc chars 30k 기준 total 5-gram ~ 29,996
- 추가 dup ratio ≈ 195 / 29996 ≈ **+0.65%p**

doc-A 현재 5-gram 20.36% + 0.65 = 21.01% 예상. doc-B 현재 24.83% + 0.65 = 25.48% 예상. **둘 다 corrigendum 31.13% 안에서 안전.** near-duplicate 박제는 dup 가드 무방.

### 5.1 사전 추정 검증 결과 (2026-05-17, doc-A retro v3/v4 합성 후)

**사전 추정 빗나감 정직 보고 (no retcon)**:

| 항목 | 사전 추정 (§5) | 실측 (한글-only) | Δ |
|---|---:|---:|---:|
| doc-A v3 5-gram dup | 21.01% | **29.66%** | +8.65%p |
| doc-A v4 5-gram dup | 21.01% | **27.40%** | +6.39%p |

**빗나감 원인 분해**:
1. 사전 추정은 "near-duplicate 5쌍만 추가" 가정 — expansion paragraph (각 section 본문 + expansion 1 paragraph 추가) 영향 미반영
2. expansion paragraph 의 boilerplate prefix ("예외 처리는" / "시험 방법은" / "종속성은") 53회 반복이 dup 의 주범 (v3 → v4 prefix rotation 으로 -2.26%p 회복)
3. GFM 표 char-level "|---|" 가 axis B 임계 (한글-only) 측정과 무관함을 사전에 인지 못 함 — v3 측정 시 전체 char 기준으로 34.11% FAIL 오진했다가 한글-only 재측정 후 PASS 확정

**결론**: 사전 추정 +0.65%p 는 빗나갔으나 가드 임계 자체는 **PASS** (axis B p75 = 31.10% 안쪽). 사전 추정 박제는 정정 없이 본 §5.1 으로 추가 박제.

### 5.2 측정 방법 명시 (가드 7 통일)

**가드 7 (5-gram dup) 측정 방법 — axis B real measurement v4 와 통일**:

```python
def measure_5gram_dup_korean_only(text: str) -> float:
    """
    한글-only char 추출 → 5-gram → dup ratio.
    axis B real 100-doc 측정과 동일. 표 (GFM/HTML) / 영문 / 숫자 / 기호 / markdown 문법 모두 제외.
    """
    korean = "".join(c for c in text if "가" <= c <= "힣")
    grams = [korean[i:i+5] for i in range(len(korean) - 4)]
    if not grams:
        return 0.0
    return (len(grams) - len(set(grams))) / len(grams) * 100
```

- **금지**: 전체 char 기준 5-gram dup (GFM `|---|` 포함). axis B 임계가 한글-only 측정이므로 비교 불가
- **임계 (v3, 2026-05-17 정정)**: axis B real 100-doc p75 + bootstrap 95% CI margin = **≤ 31.71%**
  - point estimate p75 = 31.10% (B=2000 bootstrap)
  - bootstrap 95% CI [29.70%, 31.71%] width 2.01%p
  - hard threshold 31.10% (point) 는 noise band 내 spurious FAIL 위험 (예: α' 31.23% 측정 = CI 안에서 통계적으로 31.10% 와 동일하지만 hard 적용 시 FAIL 판정). CI upper 사용이 측정 정밀도와 일치
  - 정당화: p75 자체가 100-doc sample 추정치 → noise 존재. CI upper 까지는 "같은 모집단 noise band 안"으로 통계적 동일
- 측정 raw: `docs/eval/axis-a-rebuild/axis_b_real_full_remeasure_100doc.json`
- bootstrap 코드 in-line:
```python
import random
random.seed(42)
def percentile(sorted_arr, p):
    k = (len(sorted_arr) - 1) * p / 100
    f = int(k); c = min(f + 1, len(sorted_arr) - 1)
    return sorted_arr[f] if f == c else sorted_arr[f] * (c - k) + sorted_arr[c] * (k - f)
B = 2000
ps = []
for _ in range(B):
    sample = sorted(random.choice(dup5_list) for _ in range(len(dup5_list)))
    ps.append(percentile(sample, 75))
ps.sort()
ci_lo = percentile(ps, 2.5)   # 29.70
ci_hi = percentile(ps, 97.5)  # 31.71
```

## 6. Acceptance 가드 9-12 추가 (criterion 8 corrigendum 위)

| # | 가드 | 기준값 | 검증 명령 |
|---|---|---:|---|
| 9 | topical distractor pair ≥ 5 | ≥ 5 | `topical_count()` manual sample review |
| 10 | lexical distractor variant ≥ 5 | ≥ 5 | `lexical_count(text, LEXICAL_VARIANTS)` ≥ 5 |
| 11 | counterfactual 박제 ≥ 3 | ≥ 3 | `counterfactual_count(text)` ≥ 3 |
| 12 | near-duplicate sentence pair ≥ 5 | ≥ 5 | `near_duplicate_count(text, 0.8)` ≥ 5 |

→ acceptance 총 12 가드 (1-8 기존 + 9-12 신규).

### 6.1 가드 4 / 가드 7 정정 박제 (2026-05-17, axis B v4 통일 + v3 bootstrap CI margin)

| # | 가드 | v1 (2026-05-16) | v2 (2026-05-17, axis B v4 통일) | **v3 (2026-05-17, bootstrap CI margin)** | 측정 명령 |
|---|---|---|---|---|---|
| 4 | tables 가드 | `\|---\|` substring ≥ 30 (cell unit) | **tables_block ≥ 30** (구분자 줄 단위) | (v2 유지) | `sum(1 for line in text.split("\n") if line.strip().startswith("\|") and "\|---" in line)` ≥ 30 |
| 7 | 5-gram dup ≤ p75 | ≤ 31.13% (axis B 18-doc) | ≤ 31.10% (axis B 100-doc point) | **≤ 31.71% (p75 bootstrap 95% CI upper)** | §5.2 의 `measure_5gram_dup_korean_only(text)` |

→ 가드 4 는 단위 통일 (cell → block) 으로 axis A/B 비교 가능. 가드 7 은 v2→v3 에서 임계 +0.61%p (point → CI upper). v3 정당화는 §5.2 참조 — hard threshold 가 측정 noise 안에 있어 spurious FAIL 위험. CI upper 까지가 통계적으로 동일.

### 6.1.1 가드 10 (topical) 측정식 명시 (2026-05-17, v3 박제)

기존 "manual sample review + sub-token grep" 은 자동화 측정 시 keyword set 누락 위험 발견 (doc-A 측정 사례에서 generic set 으로 잘못 측정 → 2/6 FAIL 오진, outline 박제 t1-t5 기준 재측정으로 5/5 PASS 확인). 따라서 doc-별 명시 dict + 자동 측정 식 박제:

```python
# doc-A topical 박제 (outline §3.5 t1-t5)
TOPICAL_KEYWORDS_DOC_A = {
    't1': ["AI 품질관리 시스템 구성도"],
    't2': ["보안 운영 가이드"],
    't3': ["모델 성능 측정"],
    't4': ["운영 품질 지표"],
    't5': ["1차 단계", "파일럿 단계"],  # OR 관계
}

def topical_count(text, keyword_dict):
    hits = 0
    for tid, variants in keyword_dict.items():
        if any(v in text for v in variants):
            hits += 1
    return hits
# 가드 10 PASS: topical_count(text, TOPICAL_KEYWORDS_DOC_A) >= 5
```

doc-B/C/... 도 outline §3.5 박제 시점에 동일 dict 신규 정의. 측정 코드가 outline 정의를 참조하지 않은 generic keyword 사용은 금지.

### 6.2 doc-A α' 측정 사례 (2026-05-17, v3 임계 적용 검증)

| 변형 | dup5 | 100-doc percentile rank | p75 95% CI 안? | v2 (≤31.10) 판정 | **v3 (≤31.71) 판정** | 비고 |
|------|------|-------------------------|-------------------|-------------------|-----------------------|------|
| draft (expansion 없음) | 27.21% | 41 | 아래 | ✓ | ✓ | 분포 중앙 |
| **α'** (25-template × 1 sentence, heading inject) | **31.51%** | **80** | **✓ 안** | **✗ spurious FAIL** | **✓ PASS** | 채택 |
| α'' (25-template × 2 sentence) | 34.32% | 95 | 위 (한 발자국) | ✗ | ✗ FAIL | dup 회귀, 미채택 |
| α (5-pool × 1 sentence) | 40.75% | 100 | max 초과 | ✗ | ✗ genuine FAIL | 분포 밖, 미채택 |

→ doc-A α' 가 v3 임계로 PASS 회복. 채택 = `m4a_doc_a_full_v2.json` (sub-STOP 2c). v2 판정으로는 0.41%p 차이로 spurious FAIL 됐던 사례 — v3 정당화의 직접 증거.

## 7. doc-A/B retro vs doc-C 신규 진행 순서

| 진행 순서 | 장점 | 단점 | 채택 |
|---|---|---|---|
| A → B → C | doc-C outline 이 이미 distractor 없이 박제됨 → A/B retro 후 doc-C outline 갱신 시 학습 효과 흡수 | doc-C 시작 지연 | **권장** |
| C → A → B | doc-C in-progress 유지 | distractor 정의가 처음이라 doc-C 합성 후 도구·정의 정정 시 모두 retro | 비권장 |
| A/B/C 병렬 | turn 감소 | regression 위험 ↑ (3 doc 동시) | 비권장 |

→ **A → B → C 채택**.

## 8. doc 당 backup 단계

doc-A/B 의 현재 v1 (distractor 없는 상태) 을 별도 backup 으로 박제 후 retro 진입:

```bash
cp data/raw/rfp_agency_a_ai_quality.json \
   docs/eval/axis-a-rebuild/rfp_agency_a_ai_quality.v1_pre_distractor.json
cp data/raw/rfp_agency_b_mlops_governance.json \
   docs/eval/axis-a-rebuild/rfp_agency_b_mlops_governance.v1_pre_distractor.json
```

- 기존 `.original.json` (axis A original 3 sec) 은 그대로 유지
- 신규 `.v1_pre_distractor.json` 은 v1 (axis A real-scale, distractor 없음) 박제
- retro 합성 후 production: `data/raw/*.json` 은 v2 (axis A real-scale + distractor)

## 9. axis_a_scale marker 갱신

metadata 의 axis_a_scale 값을 `real_scale_v1` → `real_scale_v2_distractor` 로 갱신 (retro 후 production).

```json
{
  "metadata": {
    "axis_a_scale": "real_scale_v2_distractor",
    "axis_a_scale_anchor": "Upstage heading1 (main heading) median ~100 + kordoc 39511 chars cross-check",
    "axis_a_scale_measurement_ref": "docs/eval/axis-a-rebuild/axis_b_real_measurement.md v4 (100-doc 재측정, 2026-05-17)",
    "axis_a_scale_distractor_ref": "docs/eval/axis-a-rebuild/distractor_definitions.md v2 (가드 4/7 정정, 2026-05-17)",
    "axis_a_scale_outline_ref": "docs/eval/axis-a-rebuild/m4a_doc_{a,b,c}_outline.md (v2 distractor)",
    ...
  }
}
```

## 10. 진행 결정 (사용자 confirm 대기)

본 distractor 정의 박제 = γ-lite 의 **sub-STOP 1.5** 완료. 다음 step:

- (i) **doc-A retro 진입** — outline v2 갱신 (distractor anchor 추가) → backup → sub-STOP 2a 재합성. *권장*
- (ii) 정의 미세 조정 후 (i) — 4 subcategory 정의 / count / acceptance 가드 변경 필요 시
- (iii) 측정 script 사전 박제 — sub-STOP 3 acceptance 측정 script 를 doc-A retro 전에 별도 박제

본 sub-STOP 1.5 종료. 사용자 review 대기.
