# real-100 정확도 천장의 construct-validity inspection (gold-grounding 결함)

| field | value |
|---|---|
| Issue | #1347 |
| Trigger | 18-component 실험 로드맵 Wave 0–1 (oracle 천장 ADR 0068) |
| Source measurement | `reports/real100/batch1_full_primary.json` (catalog gold, hashing, n=221); content-grounded gold 3-way (hashing, n=60): leak-free / leak-control |
| Date | 2026-05-23 |
| Author | Hyunsoo Kim |
| Strict-forbid | **production 파이프라인 fix 0건** + **per-case 비공개 본문 인용 0건** (ADR 0005 경계, 본 문서는 aggregate/LOC-count audit 만) |

## 요약(Executive summary)

real-100 (n=221) end-to-end 정확도가 **0.085** (hashing) 에 고착돼 있다. 5개의 독립 lever 를 차례로 흔들어도 정확도가 움직이지 않는 **null cascade** 가 관측됐고, oracle 주입 (ADR 0068) 으로 retrieval 을 완전 우회해도 정확도가 오르지 않았다.

진단 결과 — 기존 gold 는 **두 개의 구별되는 결함**을 동시에 갖고 있었다:

1. **답변측 채점 artifact (확정).** gold `expected_terms` 는 `data/data_list.csv` **카탈로그 메타데이터** (예산 정수/기관/마감일) 에서 파생됐는데, 그 표면형이 색인된 **본문(body) 텍스트에 부재**하다. 채점기 `contains_all_terms` 는 정규화 없는 **연결(conjunctive) 부분문자열 매칭**이라, 파이프라인이 의미상 정답을 내도 본문-부재 term 하나에 case 전체가 0점 → `verifier_false_negative` 로 오분류.
2. **검색축 변별력 마비 (확정).** catalog gold 위에서는 `retrieval_miss` 가 모든 검색/임베딩 lever 에서 평평(~83/221) → 임베딩 품질 차이가 *측정되지 않음* (artifact 천장에 가림).

**교정 + 정직한 분해.** `expected_terms` 를 *문서 본문에서 그대로 발췌한 verbatim 구절* 로 바꾼 content-grounded gold (60-case, 동일 hashing) 를 **동일 문서/동일 term 위에서 query 변형만 바꿔** 측정:

| 변형 | accuracy | retrieval_miss | verifier_false_negative |
|---|---:|---:|---:|
| catalog gold (baseline, n=221) | 0.085 | 83 (37.6%) | 49 |
| content gold, query 에 project명 **leak** (n=60) | **0.683** | 8 (13%) | 0 |
| content gold, **leak-free** v1 (n=60) | **0.15** | 50 (83%) | 0 |

**해석 (중요 — self-correction):** 초기 25-case pilot 이 보인 0.64(=7.5×) 는 *파이프라인 품질이 아니라* 쿼리가 `「{project}」` 로 gold 문서를 호명한 **leak** 때문이었다. leak-control 이 이를 0.683 으로 재현 → pilot 점프의 대부분이 leak 기여로 분리됨. 순수 content-grounding 의 정직한 효과는:

- **답변측 채점 artifact 제거** — `verifier_false_negative` 49 → **0** (두 변형 모두). 카탈로그-gold 가 만든 거짓 검증실패가 사라짐 = 1번 결함의 직접 교정.
- **정확도 0.085 → 0.15 (~1.75×)** — leak 없이 본문-grounding 만의 기여.
- **검색축 변별력 복원** — leak-free 에서 `retrieval_miss` 가 hashing 으로 50/60(83%) = artifact 천장이 가리던 **임베딩 headroom 이 비로소 노출**. 이 표면 위에서 BGE-M3/hybrid 가 실제로 움직일 여지가 생김 (catalog gold 에선 측정 불가였던 것).

즉 천장의 binding constraint 는 **(1) 답변측 채점 artifact + (2) catalog gold 의 변별력 마비** 두 가지였고, content-grounded gold 는 (1) 을 제거하고 (2) 를 측정 가능한 retrieval headroom 으로 전환한다.

## 5-lever null cascade (catalog gold 위에서 천장이 파이프라인이 아님을 보인 증거)

| # | lever | 측정 | 정확도 효과 | 해석 |
|---|---|---|---|---|
| 1 | 검색 row-knob (backend/rrf_k/mode/top_k, batch1) | `reports/real100/batch1_*` 4-arm | retrieval_miss flat ~83, acc 무변 | 검색 파라미터로 안 풀림 |
| 2 | embedding swap hashing→MiniLM | acc 0.085→0.093 | Δ+0.008, **paired-CI 0 포함 → 유의하지 않음**; retrieval_miss 83→88 | catalog gold 위에선 임베딩 효과 측정 불가 |
| 3 | oracle perfect-doc 주입 (ADR 0068, retrieval 완전 우회) | gold doc chunk 직접 verify+answer 투입 | Δacc ≈ 0.000 | 정답 문서를 줘도 본문에 채점 term 부재 → 무변 |
| 4 | 채점 정규화 what-if (EXACT→NORMALIZED all-terms) | `/tmp/rescore_whatif.txt`, 답변가능 n=117 | 0.051→0.051 (회복 0) | 표기 문제 아니라 **본문 부재** 문제 |
| 5 | gold 를 본문-grounded 로 교체 (leak-free) | hashing, n=60 | 0.085→**0.15** + vfn 49→0 | **유일하게 채점 artifact 를 제거 + 변별력 복원한 lever** |

lever 1–4 (파이프라인/채점 측 변형) 는 catalog gold 위에서 전부 무효(null) — 신호의 위치가 파이프라인이 아니라 **측정 표면(gold)** 임을 가리킨다. lever 5(데이터/gold 측 변형) 만 천장을 움직인다.

## construct 결함의 메커니즘

- gold `expected_terms` 출처 = `data_list.csv` 카탈로그 (budget/agency/deadline) — 색인 파이프라인은 이를 chunk **메타데이터**로 적재 (예: budget = 정수 필드).
- 채점기 `contains_all_terms` = 답변 텍스트 + evidence 텍스트 결합 후 **소문자 부분문자열 AND 매칭** (정규화·숫자포맷·동의어 없음).
- 카탈로그 표면형(콤마 금액 문자열, ISO 날짜 등) 이 본문에 그대로 없으면 — 파이프라인이 의미상 정답을 내도 — term-match fail → case 0점, verifier 는 본문 근거 부재로 정당하게 보류 → `verifier_false_negative` 로 오분류.
- oracle 가 천장을 못 올린 이유도 동일: 정답 문서를 줘도 그 *본문*에 채점 term 이 없으니 conjunctive 매칭이 여전히 fail.

## generator (`scripts/gen_content_grounded_gold.py`) 설계

- 문서당 가장 긴 비-TOC chunk 에서, **단일 doc 에만 등장하는 content 2-gram** 이 든 문장을 찾아 그 verbatim 구절을 `expected_terms` 로, 한 키워드를 anchor 로 추출 (결정론, LLM 없음).
- **leak 제거:** query 에 project명을 넣지 않음 (`'{anchor}' 관련 ...`). pilot 이 넣었던 `「{project}」` 가 gold 문서를 retriever 에 호명 → leak. 위 분해가 이 leak 의 정확도 기여(0.15→0.683)를 정량화.
- **boilerplate 거부:** 별지/서식/배점/공동수급/여백 등 form·section 토큰, OCR 띄어쓰기(`사 업 명`), ASCII-only anchor(OCR/path artifact) 필터.
- 출력 = `reports/proposed/*.local.yaml` (gitignored) — verbatim 본문 구절이라 ADR 0005 경계상 **커밋 금지**. ADR 0029 human-gate 로 약체 케이스(약 1/4) 정제 후 채택.

## pilot/v1 의 한계 (caveat)

1. **단조로운 case 형태** — 전부 single_doc · 단일-fact. verbatim-phrase 방식은 본질적으로 single-fact 라 multi_hop/comparison/distractor 난이도 arm 은 **다른 방식 필요 → follow-up 분리** (약한 multi-hop 위조 회피).
2. **anchor query 의 sparsity** — leak-free anchor-only query 는 자연 질의보다 sparse → hashing 에서 83% miss. 이는 *버그가 아니라 의도된 retrieval headroom* (임베딩 lever 측정용). 단 anchor 가 약한 케이스는 human-review 로 제거 필요.
3. **n=60 + generator 미정제** — ADR 0029 human-review 미통과 상태의 *proposal*. 약체 anchor(협의/그룹 등) 존재 → reviewer trim 전제.

## 가설 ranking (post-inspection)

1. **[강 신호, 확정]** catalog gold 는 (1) 답변측 채점 artifact + (2) 검색축 변별력 마비 두 결함을 가짐. content-grounded gold 가 (1) 제거(vfn 49→0) + (2) 를 측정 가능 headroom(83% miss, movable)으로 전환.
2. **[강 신호, self-correction]** pilot 7.5× 는 query-leak artifact. 정직한 content-grounding 정확도 lift = 0.085→0.15(~1.75×). 헤드라인에 7.5× 인용 금지.
3. **[중 신호]** leak-free content gold 위에서는 **임베딩/검색 lever (Wave 1c/2) 가 비로소 변별력**을 가짐 — catalog gold 에서 inert 했던 MiniLM/BGE-M3/hybrid 를 재측정할 가치 발생.

## 후속 issue 후보

| 후보 | scope | priority |
|---|---|:---:|
| (this) #1347 — content-grounded gold generator + ADR 0070 (새 측정 표면) + human-review trim | `scripts/`+`docs/` ; aggregate-only commit | high |
| Issue — 검색축 lever 재측정 (leak-free content gold 위 MiniLM/BGE-M3/hybrid) | `eval/` ablation; catalog gold 에서 masked 였던 신호 | high |
| Issue — multi_hop/comparison content-grounded 난이도 arm (다른 생성 방식) | `eval/` dataset; verbatim-phrase 로 불가 | medium |
| Issue — 채점기 숫자/날짜 정규화 (lever 4 partial-credit 0.061) | `eval/scorers/`; ADR 0054 확장 | low |

## 범위 밖(Out-of-scope)

- production 파이프라인 fix (검색/검증/임베딩) — 본 audit 는 *천장의 위치*만 확정; 교정 gold 위에서 재측정 후 별 PR.
- 비공개 RFP 본문/카탈로그 실값의 외부 전송·커밋 (ADR 0005/0012 관할).

## Verification

- 인용 수치 검증: `reports/real100/batch1_full_primary.json::accuracy == 0.0847…`, `failure_category_counts.retrieval_miss == 83`, `…verifier_false_negative == 49`; content gold leak-free `reports/real100_cggold/eval_summary.json::accuracy == 0.15`, `retrieval_miss == 50`, `verifier_false_negative == 0`; leak-control `reports/real100_cgleak/eval_summary.json::accuracy == 0.683`, `retrieval_miss == 8`. (모든 `*.local.yaml` 입력 + `reports/real100_cg*` 는 gitignored — aggregate 수치만 본 문서에 인용.)
- 채점 정규화 what-if 는 `/tmp/rescore_whatif.txt` (답변가능 n=117, EXACT 0.051 = NORMALIZED 0.051) — ad-hoc, 비커밋.
- oracle Δacc≈0 은 ADR 0068 주입 경로(`run_rag_query_with_oracle_evidence`)로 측정 — 경로 회귀는 `tests/test_oracle_evidence_injection.py` 가 고정.
- 모든 slice 는 aggregate/LOC-count 형식 — per-case 비공개 본문 텍스트는 ADR 0005 경계를 넘지 않음.
