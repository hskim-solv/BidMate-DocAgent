# Axis B real ground truth — kordoc measurement (18 doc subset, v2)

측정일: 2026-05-15.
Source: `reports/parser_experiment/kordoc.jsonl` (18 row, 모두 `ok=true`).
Scope: **kordoc only** (anchor 박제). cross-check 1회는 Upstage `categories.heading1` 로 kordoc `headings_count` 의 *정의* 검증 — anchor 박제 아님, 진단 reasoning.
용도: axis A real-scale rebuild (ADR 0048 reserved) 의 size/structure anchor.

## v2 변경점 (2026-05-15, sub-STOP 2a undershoot 후속)

- v1 박제 후 sub-STOP 2a 합성 결과 chars/section 51 (target 158 의 32%) 발생
- 진단: kordoc `headings_count` 가 RFP 의 "main heading" 이 아니라 outline tree 전체 node (subheading 포함) 라고 의심
- cross-check (Upstage `categories.heading1`) 로 확인 — kordoc 282 vs Upstage heading1 ~100 = **2.8x** 차이. kordoc 은 subheading 포함, Upstage heading1 만 main heading.
- → **axis A 의 "section" 정의 결정**: Upstage `heading1` 등가 = **~100 main heading/doc**, chars/main-section ~**400** (39,511/100)
- v1 의 chars/section target 158 → v2 에서 **chars/main-section ~400** 로 anchor 재정의
- v1 의 section_count_target 180-200 → v2 에서 **100-120/doc** 으로 재anchor

## 1. TL;DR

| 지표 | median | p25 | p75 | min | max | 비고 |
|---|---:|---:|---:|---:|---:|---|
| `korean_chars` | **39,511** | 31,326 | 46,015 | 26,924 | 121,010 | 한글 (가-힣) 추출 char |
| `headings_count` | **282** | 149 | 477 | 10 | 519 | kordoc outline node 수 ≈ section 등가 |
| `tables_count` (gfm+html) | **165** | 131 | 208 | 76 | 426 | GFM + HTML 표 합 (작은 cell merge 분리 포함) |
| `tables_blocks` | **106.5** | 93 | 134 | 51 | 240 | semantic table block 단위 |
| `blocks_count` | 693 | 551 | 819 | 434 | 2,149 | 모든 IR block (text + table + heading + image) |
| `chars/section` 비율 | **158.0** | 118.3 | 250.0 | 68.3 | 2,950.3 | korean_chars / headings_count |
| `chars/table` 비율 | **235.4** | 215.2 | 284.1 | 113.5 | 384.3 | korean_chars / tables_count |

→ axis B real ground truth = 약 **40k 한글 chars / ~280 section / ~165 cell-table or ~106 table-block / ~158 chars/section / ~235 chars/table**.

## 2. Per-doc 측정값 (18 doc, korean_chars asc)

| short | size_KB | kor_chars | headings | tables (gfm+html) | tables_blocks | blocks | ch/sec | ch/tbl |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| doc_12.hwp | 1,138 | 26,924 | 380 | 164 | 84 | 601 | 70.9 | 164.2 |
| doc_04.hwp | 406 | 29,204 | 58 | 76 | 51 | 483 | 503.5 | 384.3 |
| doc_00.hwp | 236 | 29,468 | 249 | 85 | 71 | 759 | 118.3 | 346.7 |
| doc_05.hwp | 520 | 29,503 | **10** | 129 | 81 | 543 | 2,950.3 | 228.7 |
| doc_02.hwp | 280 | 31,326 | **11** | 131 | 104 | 434 | 2,847.8 | 239.1 |
| doc_01.hwp | 273 | 33,520 | 491 | 160 | 93 | 707 | 68.3 | 209.5 |
| doc_07.hwp | 592 | 36,593 | 149 | 166 | 93 | 679 | 245.6 | 220.4 |
| doc_14.hwp | 2,450 | 36,811 | 519 | 138 | 104 | 746 | 70.9 | 266.7 |
| doc_09.hwp | 848 | 38,225 | 242 | 160 | 134 | 551 | 158.0 | 238.9 |
| doc_03.hwp | 296 | 40,797 | 146 | 176 | 95 | 819 | 279.4 | 231.8 |
| doc_10.hwp | 881 | 44,771 | 243 | 208 | 140 | 546 | 184.2 | 215.2 |
| doc_06.hwp | 568 | 44,822 | 305 | 124 | 109 | 569 | 147.0 | 361.5 |
| doc_11.hwp | 1,028 | 45,278 | 477 | 399 | 124 | 782 | 94.9 | 113.5 |
| doc_08.hwp | 808 | 46,015 | 291 | 202 | 129 | 626 | 158.1 | 227.8 |
| doc_13.hwp | 1,200 | 51,317 | 413 | 206 | 117 | 939 | 124.3 | 249.1 |
| doc_15.hwp | 4,163 | 67,519 | 273 | 335 | 202 | 934 | 247.3 | 201.5 |
| doc_17.hwp | 23,546 | 78,059 | 505 | 209 | 163 | 895 | 154.6 | 373.5 |
| doc_16.pdf | 7,090 | 121,010 | 484 | 426 | 240 | 2,149 | 250.0 | 284.1 |

### Outlier note

- **doc_05.hwp / doc_02.hwp** — headings_count 10 / 11 (median 282 대비 4%). heading 인식 실패 가능성. chars/section 2,950 / 2,847 는 본 비율 계산에서 제외해야 정직. 단 raw median 158 은 18 doc 전체 기준 (outlier 포함도 변동 1 미만이므로 그대로 anchor).
- **doc_16.pdf** — 121k chars (median 의 3.0x). 단일 outlier. axis A target 산정에는 median 사용.
- **healthy subset** (headings ≥ 50, n=16): chars/section median 158 동일. outlier 영향 minor.

## 3. Axis A real-scale rebuild target (kordoc median 의 70-80%)

| 지표 | axis B median (kordoc) | doc A target (~76%) | 비고 |
|---|---:|---:|---|
| korean_chars | 39,511 | **30,000** | 70-80% 시뮬레이션 |
| sections | 282 | **180-200** | headings_count 등가 |
| tables (cell unit) | 165 | **120-130** | tables_count 등가 |
| tables (block unit) | 106 | **75-85** | tables_blocks 등가 |
| chars/section | 158 | **~150-160** | 분포 정합 |
| chars/table | 235 | **~230-250** | 분포 정합 |

### M4-A 9 doc 도메인 target

| doc | korean_chars target | sections target | tables (gfm+html) target |
|---|---:|---:|---:|
| A (AI 품질) | 30,000 | 180-200 | 110-130 |
| B (MLOps gov) | 30,000 | 180-200 | 120-140 |
| C (챗봇) | 28,000 | 170-190 | 100-120 |
| D (분광기) | 28,000 | 170-190 | 100-120 |
| E_main (수질) | 32,000 | 200-220 | 130-150 |
| E_supp (수질 supp) | 25,000 | 150-170 | 90-110 |
| F (smart factory) | 30,000 | 180-200 | 120-140 |
| G (교통) | 30,000 | 180-200 | 120-140 |
| common (제출조건) | 22,000 | 140-160 | 70-90 |

→ 총 ~255,000 chars / ~1,540-1,720 section / ~960-1,120 tables (cell). axis B 18-doc 의 median × 9 = 355k chars 대비 **72%**. block 단위로는 ~720-840 tables_blocks (axis B median 18-doc × 9 의 ~76%).

## 4. 1차 outline overshoot 분석

- 1차 outline (`m4a_doc_a_outline.md` v1): 54 sections / 98 tables / 35,000 chars target
- v1 chars/section 평균: 35,000 / 54 = **648** (kordoc median 158 의 4.1x) ← overshoot
- v1 sub-STOP 2a 실측 (§2.1-2.4): 31 sections / 47 tables / **8,814 chars** → section 평균 285 chars (kordoc median 의 1.8x, 그래도 plan 의 44%)
- → 진단: v1 section 수 (54) 가 너무 적어서 plan target chars 도달하려면 section 당 평균 648 char 필요. kordoc real 은 section 당 158 char (짧고 많은 구조).

## 5. 결론 (v1 — chars/section 158 anchor, sub-STOP 2a undershoot 후 폐기)

~~axis A doc A real-scale rebuild target: 30,000 korean_chars / 180-200 section / 110-130 tables (cell unit). outline v2 가 section 수를 ~190 으로 늘리고 section 당 평균 ~150 chars 로 분포 정합.~~

## 6. cross-check (v2 추가) — kordoc `headings_count` 정의 검증

### 6.1 측정값 (kordoc + cross-check parser, median)

| metric | kordoc | Upstage | Polaris | 의미 |
|---|---:|---:|---:|---|
| pages | — | **81** | **89.5** | RFP 페이지 수 |
| outline node / tree heading | **282** (headings_count) | — | — | 전체 outline node (kordoc) |
| main heading (Upstage heading1) | — | **~100** | — | RFP chapter+section 단위 |
| paragraph (Upstage) | — | ~100-170 | — | 본문 단락 |
| list (Upstage) | — | ~50-100 | — | bullet/numbering 항목 |
| total element / text_block | 693 (blocks) | **521** (n_elements) | 495 (text_blocks) / 632 (elements_total) | 모든 IR 요소 |
| tables | 165 (cell) / 106 (block) | 104 | 121 | 표 |

### 6.2 진단

- **kordoc 282 / Upstage page 81 = 3.48 heading/page** — RFP 페이지당 outline node 3-4개. main heading 만이면 1-2/page 가 자연. 즉 kordoc 은 subheading 까지 count.
- **kordoc 282 / Upstage heading1 ~100 = 2.8x** — kordoc 이 Upstage heading1 의 2.8배 = subheading2/3 까지 outline tree 에 포함하여 count 한 것으로 결론.
- **kordoc heading / kordoc block = 40.7%** — 모든 block 중 40% 가 heading. main+subheading 합산 시 이 비중이 정상.
- Upstage `categories.heading1` 가 RFP 의 진정한 main heading 등가 — 약 100/doc, page 당 1.2 main heading.

### 6.3 axis A 의 "section" 정의 결정

| 옵션 | "section" 등가 | sections/doc | chars/section | 평가 |
|---|---|---:|---:|---|
| (A) main heading 정의 | Upstage `heading1` | **100-120** | **~400** | kordoc 39511/100 = 395 chars/main. axis A 9 doc 기존 정의 (4-5 sections) 의 자연 scale-up. **권장** |
| (B) fine-grained outline 정의 | kordoc `headings_count` | 180-280 | 140-160 | outline v1/v2 가 시도. sub-STOP 2a 가 51 chars/section 으로 본문 빈약 |
| (C) text block 정의 | Polaris `text_blocks` | 450-550 | 70-90 | 너무 fine-grained, axis A 의 sections[] 와 맞지 않음 |

→ **(A) 채택**. axis A doc-A 의 sections target = **~110** (110-120 범위), chars/section avg ~400, body 는 단정 문장이 아니라 RFP 본문처럼 풀어 쓴 단락.

## 7. 결론 (v2 — main heading anchor)

| 지표 | axis B median (kordoc + cross-check) | doc A target (~76%) | sub-STOP 2a target | sub-STOP 2b target |
|---|---:|---:|---:|---:|
| sections (main heading) | 100 (Upstage heading1 등가) | **110-120** | ~50-60 | ~55-65 |
| korean_chars | 39,511 | **30,000** | ~16,000 | ~14,000 |
| chars/section avg | ~395 | **~280-330** | ~280-330 | ~280-330 |
| tables (gfm+html cell) | 165 | **110-130** | ~60-70 | ~55-65 |
| tables_block | 106 | **75-85** | ~40-45 | ~35-40 |

### 7.1 M4-A 9 doc target (v2 갱신)

| doc | korean_chars | sections (main heading) | tables_cell | chars/section avg |
|---|---:|---:|---:|---:|
| A (AI 품질) | 30,000 | 110-120 | 110-130 | ~280-330 |
| B (MLOps gov) | 30,000 | 110-120 | 120-140 | ~280-330 |
| C (챗봇) | 28,000 | 100-110 | 100-120 | ~280-330 |
| D (분광기) | 28,000 | 100-110 | 100-120 | ~280-330 |
| E_main (수질) | 32,000 | 120-130 | 130-150 | ~280-330 |
| E_supp (수질 supp) | 25,000 | 90-100 | 90-110 | ~280-330 |
| F (smart factory) | 30,000 | 110-120 | 120-140 | ~280-330 |
| G (교통) | 30,000 | 110-120 | 120-140 | ~280-330 |
| common (제출조건) | 22,000 | 80-90 | 70-90 | ~280-330 |

→ 총 ~255,000 chars / ~1,030-1,140 main heading / ~960-1,120 tables_cell. axis B kordoc median (per-doc main heading ~100) × 9 = ~900 main 대비 1,030-1,140 = 약 110-125% (sub-STOP 2a 의 fine-grained 197/doc 대비 정상화).

## 8. sub-STOP 2a 측정 회수 (v2 진단)

| metric | sub-STOP 2a 실측 | v1 target | v2 target | 도달률 (v2) |
|---|---:|---:|---:|---:|
| sections | 97 | ~96 | ~50-60 | **~170% (과다)** |
| korean_chars | 4,948 | ~15,900 | ~16,000 | 31% |
| chars/section | 51 | ~160 | ~280-330 | 17% |
| tables_cell | 40 | ~65 | ~60-70 | 63% |

→ v1 anchor 기준에서는 chars 만 undershoot 였으나, **v2 anchor 기준으로는 sections 도 1.7x 과다**. sub-STOP 2a partial 의 97 section 은 main heading 으로 합치면 약 35-40 section 등가 (sub-bullet 까지 1:2~3 비율).

본 measurement md v2 박제 종료. outline v3 진입 또는 사용자 결정 대기.

## v3 변경점 (2026-05-16, doc-B 합본 후 5-gram dup criterion 정정)

- doc-A / doc-B 합본 후 plan v3 criterion 8 (5-gram dup <5%) 측정 → doc-A 20.36% / doc-B 24.83% 모두 임의 floor 미달 발생
- 진단: 임의 5% floor 가 자연 한글 RFP 분포와 어긋남 의심 → axis B real 18-doc kordoc markdown 으로 직접 측정 (사용자 지시)
- 결과: axis B real 자연 분포 median **29.07%** (range 21.79-35.07%, p25-p75 25.42-31.13%) — 임의 5% floor 와 약 6배 차이
- 결론: criterion 8 자체가 비현실적 floor 였음. anchor-based 로 재정의 (사용자 결정 가2)

## 9. N-gram dup ratio anchor (v3 박제, axis B real 18-doc)

측정 source: `/private/tmp/kordoc_batch/doc_*.json` (kordoc parser 의 markdown 필드, 18 doc 모두 ok=true)
측정 방법: 한글 char (가-힣) 만 추출 → 연속 N-gram 빈도 Counter → `dups / total_grams` 비율 (`dups = Σ(count-1) for count>1`)

### 9.1 per-doc 측정값 (18 doc, korean_chars asc)

| short | kor_chars | 5-gram | 7-gram | 10-gram | 12-gram |
|---|---:|---:|---:|---:|---:|
| doc_12 | 26,924 | 28.65% | 20.67% | 15.47% | 13.48% |
| doc_04 | 29,204 | 25.42% | 14.78% | 8.03% | 5.92% |
| doc_00 | 29,468 | 21.79% | 13.58% | 8.49% | 6.49% |
| doc_05 | 29,503 | 24.52% | 16.03% | 11.16% | 9.41% |
| doc_02 | 31,326 | 24.46% | 15.08% | 9.01% | 6.83% |
| doc_01 | 33,520 | 26.66% | 16.48% | 9.75% | 7.42% |
| doc_07 | 36,593 | 24.94% | 15.65% | 10.40% | 8.59% |
| doc_14 | 36,811 | 29.67% | 19.61% | 13.11% | 10.85% |
| doc_09 | 38,225 | 31.13% | 20.00% | 12.43% | 9.61% |
| doc_03 | 40,797 | 26.40% | 16.16% | 9.88% | 7.70% |
| doc_10 | 44,771 | 28.21% | 17.73% | 11.36% | 8.86% |
| doc_06 | 44,822 | 35.07% | 25.11% | 18.53% | 16.12% |
| doc_11 | 45,278 | 29.07% | 19.29% | 13.25% | 11.17% |
| doc_08 | 46,015 | 33.60% | 23.35% | 16.31% | 13.68% |
| doc_13 | 51,317 | 29.32% | 18.63% | 11.96% | 9.74% |
| doc_15 | 67,519 | 32.23% | 20.99% | 13.55% | 10.92% |
| doc_17 | 78,059 | 33.95% | 22.96% | 15.53% | 12.75% |
| doc_16 | 121,010 | 29.61% | 17.28% | 10.33% | 8.24% |

### 9.2 summary (median / p25 / p75 / range)

| n-gram | median | p25 | p75 | min | max |
|---|---:|---:|---:|---:|---:|
| 5-gram | **29.07%** | 25.42% | 31.13% | 21.79% | 35.07% |
| 7-gram | **18.63%** | 16.03% | 20.67% | 13.58% | 25.11% |
| 10-gram | **11.96%** | 9.88% | 13.55% | 8.03% | 18.53% |
| 12-gram | **9.61%** | 7.70% | 11.17% | 5.92% | 16.12% |

### 9.3 top 10 5-grams across 18-doc (자연 한글 RFP 의 빈출 어구)

| 빈도 | 5-gram | 해석 |
|---:|---|---|
| 1,250 | 사항요구사 | "요구사항" 본문 주제어 |
| 1,250 | 항요구사항 | 동상 |
| 1,171 | 요구사항분 | 요구사항 분류 |
| 1,137 | 요구사항명 | 요구사항 명칭 |
| 1,125 | 구사항분류 | 동상 |
| 1,106 | 요구사항요 | 동상 |
| 1,105 | 구사항요구 | 동상 |
| 1,006 | 구사항명칭 | 동상 |
| 984 | 소프트웨어 | 도메인 주제어 |
| 977 | 요구사항상 | 동상 |

→ 자연 한글 RFP 는 본문 주제어 (요구사항 / 소프트웨어 등) 가 반복적으로 등장. 이는 도메인 특성이며, 합성 문서가 동일 패턴을 보이는 것은 자연. "다양성 부재"가 아님.

## 10. axis A 합성 doc 의 plan v3 criterion 8 정정 (v3 박제)

### 10.1 정정 전 (v2 / plan v3 원안)

| criterion | 임의 floor | 근거 |
|---|---|---|
| 5-gram dup | < 5% | (임의 박제, 자연 분포 측정 안 함) |

### 10.2 정정 후 (v3, 사용자 결정 가2 채택)

| criterion | anchor-based floor | 근거 |
|---|---|---|
| **5-gram dup** | **≤ axis B real p75 (31.13%)** | 합성이 자연 분포 상한 이내인지 검증 |

→ 합성 doc 가 자연보다 더 다양 (낮음) 한 것은 PASS. 자연보다 훨씬 반복적 (p75 초과) 인 것만 FAIL. 자연 한글 RFP 의 도메인 주제어 반복은 인정.

### 10.3 axis A 합성 doc-A / doc-B 정정 acceptance

| doc | 5-gram dup | 정정 전 (<5%) | 정정 후 (≤31.13%) |
|---|---:|---|---|
| rfp_agency_a_ai_quality | 20.36% | FAIL (이전 보고의 측정 누락) | **PASS** |
| rfp_agency_b_mlops_governance | 24.83% | FAIL | **PASS** |

→ 둘 다 plan v3 floor acceptance 8/8 PASS 로 정정.

본 measurement md v3 박제 종료. 다음 doc 합성 시 본 anchor 적용.

## v4 변경점 (2026-05-17, files_kordoc 100-doc 전수 재측정)

- v3 의 18-doc 표본 대신 사용자가 전처리한 `data/files_kordoc/*.md` 100-doc 전수 재측정 (사용자 요청)
- 측정 method 명시 + 분포 안정화 + 표 형식 차이 발견
- 핵심 결론: **5-gram dup 임계 무변동** (31.13 → 31.10, Δ -0.03%p). 18-doc 표본이 100-doc 분포를 잘 대표
- 부수 발견: 100-doc 전처리는 **모두 HTML 표 (GFM 0개)** — 표 형식이 18-doc kordoc 출력 (GFM 31 + HTML 54) 과 다름. 한글-only dup 측정에서는 무관 (양쪽 모두 표 char 제거)

## 11. files_kordoc 100-doc 재측정 (v4 박제)

측정 source: `/Users/hskim/Desktop/projects/BidMate-DocAgent/data/files_kordoc/*.md` (사용자 전처리 100 doc)
측정 raw: `docs/eval/axis-a-rebuild/axis_b_real_full_remeasure_100doc.json` (per-doc + summary)

### 11.1 측정 method 명시 (v4 박제, 모호성 제거)

| metric | 측정 방법 | 비고 |
|---|---|---|
| `chars` | `len(text)` | raw markdown 전체 char |
| `korean_chars` | `len([c for c in text if '가' <= c <= '힣'])` | 한글 음절 char only (영문/숫자/기호/markdown 문법 제외) |
| `korean_ratio` | `korean_chars / chars` | 한글 비율 |
| `dup_N` | korean-only char 추출 후 N-gram → `(n_grams - len(set(grams))) / n_grams` | **한글-only 5-gram dup** (markdown 표 / 영문 / 숫자 영향 배제) |
| `h1` / `h2` / `h3` | `re.match(r'^# [^#]', line)` 등 | markdown heading 줄 카운트 |
| `sections (h1+h2)` | h1 + h2 | main heading 단위 |
| `tables blocks` | GFM 구분자 줄 + HTML `<table>` open tag | block 단위 (논리적 표 1개) |
| `tables cell unit` | GFM 셀 + HTML `<td>`/`<th>` raw count | cell 단위 (개념적 셀 수, parser 별 정의 다양) |
| `GFM blocks` | `line.strip().startswith('|') and '|---' in line` | GFM 표만 카운트 |
| `HTML blocks` | `re.findall(r'<table\b', text)` | HTML 표만 카운트 |
| `paragraph blocks` | `\n\n` split 중 표/heading 제외 | 본문 단락 추정 |
| `chars / section` | `chars / (h1+h2)` | section density |
| `chars / table block` | `chars / tables_blocks` | table density |

### 11.2 100-doc 분포 (n=100)

| 지표 | min | p25 | median | p75 | p90 | max | mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| chars (total) | 48,750 | 85,675 | **99,927** | 124,493 | 162,405 | 268,877 | 110,011 |
| korean chars | 25,004 | 33,506 | **40,683** | 48,978 | 65,389 | 121,010 | 44,445 |
| korean ratio (%) | 32.8 | 38.6 | **40.0** | 42.5 | 45.1 | 64.1 | 40.7 |
| **3-gram dup (%)** | 46.1 | 51.2 | **53.9** | 55.9 | 59.0 | 62.1 | 53.9 |
| **5-gram dup (%)** | 21.7 | 25.5 | **28.3** | **31.1** | 33.6 | 35.3 | 28.4 |
| **7-gram dup (%)** | 12.7 | 15.6 | **18.1** | 20.8 | 22.8 | 25.1 | 18.3 |
| h1 | 0 | 12 | **47** | 159 | 246 | 420 | 92 |
| h2 | 0 | 16 | **63** | 190 | 293 | 737 | 120 |
| h3 | 0 | 18 | **52** | 116 | 202 | 675 | 86 |
| h1+h2+h3 | 3 | 143 | **291** | 411 | 567 | 899 | 297 |
| sections (h1+h2) | 1 | 31 | **222** | 317 | 440 | 782 | 212 |
| tables blocks | 2 | 53 | **74** | 98 | 125 | 207 | 78 |
| tables cell unit | 45 | 1,692 | **2,283** | 2,675 | 3,481 | 4,880 | 2,285 |
| **GFM blocks** | **0** | **0** | **0** | **0** | **0** | **0** | **0** |
| **HTML blocks** | 2 | 53 | **74** | 98 | 125 | 207 | 78 |
| paragraph blocks | 127 | 444 | **560** | 733 | 870 | 1,582 | 602 |
| chars/section | 127 | 324 | **477** | 3,533 | 9,134 | 60,572 | 3,744 |
| korean/section | 56 | 135 | **193** | 1,386 | 3,194 | 25,004 | 1,506 |
| chars/table block | 705 | 1,164 | **1,361** | 1,652 | 2,997 | 24,375 | 1,957 |

### 11.3 v3 (18-doc) vs v4 (100-doc) 비교

| 지표 | v3 (18-doc) median | v4 (100-doc) median | Δ | 정의 일치 여부 |
|---|---:|---:|---:|---|
| korean_chars | 39,511 | 40,683 | +1,172 | 일치 (한글 char 추출) |
| 5-gram dup median | 29.07% | 28.27% | -0.80%p | 일치 |
| **5-gram dup p75 (가드 임계)** | **31.13%** | **31.10%** | **-0.03%p** | **일치** |
| 7-gram dup median | 18.63% | 18.10% | -0.53%p | 일치 |
| tables_blocks median | 106.5 | 74.5 | -32 | **일치하지만 분포 다름** (전처리 출력 차이) |
| tables_count (cell) median | 165 | 2,283 | +2,118 | **정의 불일치** — v3 kordoc cell merge 분리 vs v4 HTML raw `<td>/<th>` |
| headings_count (kordoc outline) | 282 | — | — | v4 에 직접 등가 없음 |
| h1+h2+h3 (markdown heading) | — | 291 | — | v3 kordoc 282 와 유사 수치 (우연 일치 가능) |
| chars/section (kordoc) | 158 | — | — | v4 에 직접 등가 없음 |
| chars/(h1+h2) (v4) | — | 477 | — | h1+h2 정의 다름 |
| chars/table block | 235 | 1,361 | +1,126 | **정의 차이** (kordoc 표 vs HTML 표) |

### 11.4 정의 차이 해석 — 무엇이 단단해졌나, 무엇이 다른가

**단단해진 것 (v4 우위)**:
- **5-gram dup 분포** — n=18 → 100. p25/median/p75 모두 ±1%p 이내 일치. 18-doc 표본 신뢰성 확정. **임계 31.10% (= 사실상 31.13%) 그대로 유효**.
- **korean_chars median** — 거의 무변동. doc target chars 30k 유지.
- 신규 산출: **p90** (5-gram 33.60% / korean 65,389) — outlier 영향 분리한 conservative 추가 임계 가능.

**정의 통일 필요한 것 (v3 vs v4 비교 불가)**:
- **tables (cell unit)** — v3 의 165 (kordoc 의 cell merge 분리 알고리즘 결과) vs v4 의 2,283 (HTML `<td>/<th>` raw count). 측정 정의 자체가 다름. → **cell unit 비교 폐기 권고**. block 단위만 axis A/B 통일 측정.
- **headings_count** — v3 의 kordoc 282 outline node 와 v4 의 markdown h1+h2+h3 291 은 우연 수치 근접이지만 정의 다름. v2 의 cross-check 결과 (Upstage heading1 ~100 = main heading) 가 axis A "section" 등가로 결정된 상태 — v4 의 markdown h1 median 47 / h1+h2 222 와 직접 매칭 안 됨.

**표 형식 차이 (axis A vs axis B real 100-doc)**:
- axis A 합성: GFM `|---|` only
- axis B real 100-doc 전처리: HTML `<table>` only (GFM 0)
- 한글-only 5-gram dup 측정에서는 표 char 모두 제거 → **fair 비교**
- 표 개수 비교는 "block 단위" 로 통일하면 fair (GFM 구분자 줄 = 1 block, HTML `<table>` open = 1 block)

## 12. doc target 갱신 (v4)

v2 (sub-STOP 9.3) 의 main heading anchor (Upstage heading1 ~100) 는 변동 없음 — Upstage parser 재측정 없으므로 v2 결정 유지.
다만 **tables target 의 cell unit 은 폐기**, **block 단위만 사용**:

### 12.1 doc-A target (v4 갱신)

| 지표 | v2 target | v4 target | 변경 사유 |
|---|---:|---:|---|
| sections (main heading 등가) | 110-120 | 110-120 | 무변동 (Upstage heading1 anchor 유지) |
| korean_chars | 30,000 | 30,000 | 무변동 (median 39,511 → 40,683, +3% noise) |
| chars/section avg | ~280-330 | ~280-330 | 무변동 |
| tables_block | 75-85 | **55-65** | v4 median 74 × 0.76 = 56. v3 의 106 × 0.76 = 80 보다 낮음 |
| ~~tables (cell unit)~~ | ~~110-130~~ | **폐기** | parser 별 정의 불일치, block 단위로 통일 |

### 12.2 M4-A 9 doc target (v4 갱신)

| doc | korean_chars | sections (main heading) | tables_block (v4) | chars/section avg |
|---|---:|---:|---:|---:|
| A (AI 품질) | 30,000 | 110-120 | **55-65** | ~280-330 |
| B (MLOps gov) | 30,000 | 110-120 | **55-65** | ~280-330 |
| C (챗봇) | 28,000 | 100-110 | **50-60** | ~280-330 |
| D (분광기) | 28,000 | 100-110 | **50-60** | ~280-330 |
| E_main (수질) | 32,000 | 120-130 | **60-70** | ~280-330 |
| E_supp (수질 supp) | 25,000 | 90-100 | **45-55** | ~280-330 |
| F (smart factory) | 30,000 | 110-120 | **55-65** | ~280-330 |
| G (교통) | 30,000 | 110-120 | **55-65** | ~280-330 |
| common (제출조건) | 22,000 | 80-90 | **40-50** | ~280-330 |

→ 9 doc 총 tables_block ~480-545 (v3 v2 의 720-840 cell 폐기 후). axis B 100-doc median × 9 = 670 tables_block 대비 ~72-81% (76% target 정합).

### 12.3 doc-A v4 (현재 합성 중) acceptance 가드 정정

기존 acceptance 가드 4 (`GFM tables >= 30`) 는 cell unit 기준. v4 정정:

| # | 가드 | v2 기준 | v4 기준 | 측정 명령 |
|---|---|---|---|---|
| 4 | tables block ≥ 30 | (cell `\|---\|` substring count) | **block 단위 (GFM 구분자 줄)** | `sum(1 for line in text.split("\n") if line.strip().startswith("\|") and "\|---" in line)` |
| 7 | 5-gram dup ≤ 31.13% | 18-doc p75 | **≤ 31.10% (100-doc p75)** | korean-only char → 5-gram → `(n_grams - len(set)) / n_grams` |

→ doc-A partial 2a v4 의 측정값 (block 단위 53 / dup 27.40%) 둘 다 PASS 그대로.

## 13. 5-gram dup 임계 거의 무변동 — 사전 추정 (distractor_definitions.md §5) 정합성 정직 보고

`distractor_definitions.md` §5 의 사전 추정 "near-duplicate 5쌍 박제 시 +0.65%p" 는:
- 한글-only 측정 기준으로 했어야 fair
- 내가 doc-A v3 측정 시 **전체 char 기준** (GFM `\|---\|` 포함) 으로 34.11% 보고 → FAIL 오진
- 한글-only 재측정 시 v3 29.66%, v4 27.40% — 사전 추정 21.01% 대비 +6~9%p 빗나감 (여전히 추정보다는 큼)
- 빗나감 원인: expansion paragraph 자체 추가 (sub-STOP 1.5 추정에서 expansion 추가는 미반영)
- **그러나 가드 임계 31.10% 안쪽 PASS** — 정합성 정상

본 measurement md v4 박제 종료. doc-A 후속 sub-STOP 및 doc-B/C 합성은 v4 target 적용.
