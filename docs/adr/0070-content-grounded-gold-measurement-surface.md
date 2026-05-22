# ADR 0070 — Content-grounded gold 을 additive 측정 표면으로

- Status: Accepted
- Implemented: #1347 — `scripts/gen_content_grounded_gold.py` (`generate_cases`), `docs/audits/construct-validity-gold-grounding-inspection.md`
- Date: 2026-05-23
- Authors: Hyunsoo Kim
- Related: ADR 0001 (naive_baseline byte-identical), ADR 0005 (private/public eval 분리), ADR 0029 (case-proposer human-gate), ADR 0048 (realN metrics), ADR 0052 (n=221), ADR 0054 (conditional-on-answer scorer), ADR 0059 (failure-mode classifier), ADR 0068 (oracle 천장)
- Issue: #1347

## Context

real-100 (ADR 0052, n=221) 헤드라인 정확도가 **0.085** (hashing) 에 고착. 5-lever null cascade audit (`docs/audits/construct-validity-gold-grounding-inspection.md`) 가 천장의 binding constraint 를 **파이프라인이 아니라 gold 의 construct-validity 결함**으로 확정했다:

1. **답변측 채점 artifact** — committed gold 의 `expected_terms` 가 `data/data_list.csv` 카탈로그(budget/agency/deadline)에서 파생됐는데, 그 표면형이 색인된 **본문에 부재**. 채점기 `contains_all_terms` (정규화 없는 conjunctive 부분문자열) 가 본문-부재 term 에 0점 → 파이프라인이 정답을 내도 fail, `verifier_false_negative` (49/221) 로 오분류.
2. **검색축 변별력 마비** — catalog gold 위에선 `retrieval_miss` 가 모든 임베딩/검색 lever 에서 평평(~83) → 임베딩 품질 차이가 측정 불가.

oracle 주입 (ADR 0068) 으로 retrieval 을 완전 우회해도 Δacc≈0 — 정답 문서를 줘도 본문에 채점 term 이 없어 무변. 즉 현재 gold 위에서는 어떤 파이프라인 개선도 헤드라인에 *측정되지 않는다*.

## Decision

1. **신규 결정론 생성기 `scripts/gen_content_grounded_gold.py`** — `expected_terms` 를 *문서 본문의 verbatim 구절* 로 삼는 single_doc 케이스를 만든다 (`generate_cases(chunks, n)`). 문서당 단일-doc-고유 content 2-gram 이 든 문장에서 구절·anchor 추출. **LLM 없음, 결정론** (doc_id 정렬 순회).

2. **query leak 제거** — query 는 `'{anchor}' 관련 …` 형태로 distinctive content anchor 만 포함, **project명 불포함**. 초기 pilot 의 `「{project}」` 는 gold 문서를 retriever 에 호명하는 leak 이었다 (leak-control 측정: 정확도 0.15→0.683 의 차이가 leak 기여). leak 제거는 single_doc retrieval 을 공정한 검정으로 만들고, catalog gold 가 가렸던 **검색축 headroom 을 복원**한다.

3. **catalog gold 와 병존 (additive, 비대체)** — 기존 `eval/real_config.local.yaml` 의 카탈로그-gold 케이스는 그대로 유지. content-grounded gold 는 별도 표면으로 추가. 헤드라인 게이트 이전(migration)은 human-review 통과 full set 확정 후 별도 결정.

4. **채점 계약 무변** — 기존 `contains_all_terms` / `score_case` 재사용. 결함은 *채점기*가 아니라 *gold 구성*에 있었으므로, scorer 는 손대지 않는다 (ADR 0054 semantics 보존).

5. **데이터 경계 (ADR 0005)** — 생성 산출물 `reports/proposed/*.local.yaml` 은 verbatim 비공개 본문 구절을 담으므로 **gitignored, 커밋 금지**. 커밋 대상은 *생성기 + aggregate 수치*뿐. eval 설정(`eval/exp_cg_*.local.yaml`)도 local-only.

6. **ADR 0029 human-gate** — 생성기는 *proposal* yaml 을 emit; 약체 anchor(약 1/4) 는 reviewer 가 trim 후 채택. 자동 채택 아님.

## Why these specific choices

| 결정 | 근거 |
|---|---|
| 결정론 verbatim-phrase (LLM 없음) | 재현·무료·CI-safe. ADR 0001 오프라인 SSoT 정신. 본문 발췌라 "genuinely retrievable + exact-match scorable" 보장. |
| query 에 project명 제거 | pilot 의 7.5× 가 leak artifact 였음을 leak-control 이 입증. leak-free 가 정직한 retrieval 검정 + 임베딩 lever 변별력 복원. |
| catalog gold 병존 (비대체) | catalog gold 도 by_metadata_field (ADR 0048) 등 다른 측정엔 유효. 헤드라인 migration 은 full-set human-review 후 별 결정 — 성급한 교체 회피. |
| scorer 무변 | 결함은 gold 측. 채점기 정규화는 별 lever (audit lever 4: partial-credit 0.061, marginal) → ADR 0054 확장 issue 로 분리. |
| 생성 yaml gitignored | verbatim 본문 = 비공개 RFP 데이터. ADR 0005 경계상 aggregate 만 commit. |
| single_doc 단일-fact 범위 한정 | verbatim-phrase 는 본질적으로 single-fact. 약한 multi_hop 위조보다 정직한 범위 선언 + follow-up 분리. |

## Consequences

- **신규 측정 표면 추가** — content-grounded gold arm 이 (a) 답변측 채점 artifact 제거 (`verifier_false_negative` 49→0), (b) catalog gold 가 가렸던 검색축 headroom 노출 (leak-free hashing 83% miss, movable) 을 emit. Wave 1c/2 의 임베딩·검색 lever 가 비로소 변별력을 가짐.
- **헤드라인 정확도 게이트 후속 migration 의 prerequisite** — full-set human-review 후, real-100 헤드라인을 content-grounded gold 로 이전할지 별도 ADR/issue 에서 결정.
- production code path 0 변경 — `run_rag_query`, `api/`, `eval/config.yaml`, `eval/real_config.local.yaml` 의 catalog 케이스 무수정. 기본 오프라인 경로 SSoT 불변.
- 자기-교정 기록 — pilot 7.5× → leak-control 분해 → 정직한 1.75× 로 정정한 과정을 audit 에 명시 (측정 rigor 표면).

## Invariance check

- **ADR 0001** (`naive_baseline` byte-identical) — 파이프라인/scorer/preset 무변경. 생성기는 eval-하네스 입력만 추가. naive_baseline golden 회귀 무영향.
- **ADR 0005** (private/public 분리) — 생성 yaml + eval 설정 + `reports/real100_cg*` 전부 gitignored. 커밋 = 생성기 코드 + aggregate 수치만. per-case 본문 비커밋.
- **ADR 0029** (case-proposer human-gate) — 생성기는 reviewable proposal 을 emit, 자동 채택 아님.
- **ADR 0054** (conditional-on-answer scorer) — 채점기 재사용, semantics 무변.
- **ADR 0059** (failure-mode classifier) — 동일 분류기로 측정; content gold 에서 `verifier_false_negative` 소멸이 artifact 제거의 직접 증거.

## Verification

<!-- verifies-key: scripts/gen_content_grounded_gold.py:def generate_cases -->
<!-- verifies-key: tests/test_content_grounded_gold.py:class GenerateCasesContractTest -->

## Out-of-scope

- **헤드라인 게이트 migration** — content-grounded gold 로 real-100 헤드라인을 교체할지는 full-set human-review 후 별 결정.
- **multi_hop/comparison 난이도 arm** — verbatim-phrase 로 생성 불가, 다른 방식 필요 (별 issue).
- **검색축 lever 재측정** — leak-free content gold 위 MiniLM/BGE-M3/hybrid ablation (catalog gold 에서 masked 였던 신호) — 별 issue.
- **채점기 숫자/날짜 정규화** — audit lever 4 (partial-credit 0.061, marginal) → ADR 0054 확장 issue.
