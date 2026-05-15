---
name: retrieval-eval
description: |
  Drive a 4-phase retrieval measurement protocol (profiling → chunking ablation → mode ablation → metadata/filtering) on BidMate-DocAgent's existing retriever. Wires oracle sub-queries through `retrieve_candidates` (planner bypass), enforces paired bootstrap CI 95%, seed-3 averaging, and a hard STOP gate after each phase's ≤200-line markdown report. Acceptance checklist only — no code, no helpers, no abstraction over `eval/scorers/chunk_metrics.py` or `eval/bootstrap.py`.

  Trigger phrases: "retrieval recall 측정", "retrieval-eval start", "Phase 1 measurement", "oracle sub-queries 평가", "chunking ablation 돌려줘", "retrieval mode ablation", "hybrid vs dense 비교", "recall@k 측정". Trigger when the user names any of Phase 1-4 by number AND scopes it to retrieval (not verifier/answer/planner). Trigger even if the user does not say "skill".

  Do NOT trigger for: 4-axis / 5-axis self-review (use `self-review-quarterly`), ADR-to-signal portfolio mapping (use `adr-portfolio-signals`), PR shipping / ADR authoring (use `ship-pr`), verifier or answer-quality eval (out of scope until ≥2 concrete use cases exist), single ad-hoc recall@k spot-check without phase framing, or running `eval/run_eval.py` for end-to-end answer scoring.
---

# /retrieval-eval — 4-phase retrieval measurement protocol

Retrieval 단독 성능을 측정하고, 어디서 천장이 결정되는지 분리하기 위한 4-phase guide. **Guide + acceptance checklist 전용** — skill은 phase별 절차 / 체크리스트 / STOP gate만 제공하며, 코드 helper (oracle loader, paired bootstrap CI wrapper, report writer)는 포함하지 않는다. 각 phase 종료 시 사용자 승인 명시 ("진행" / "go" / "다음 phase") 전 다음 phase 진입 금지.

## Scope

- Retrieval entry point [rag_retrieval.py:314](../../../rag_retrieval.py) `retrieve_candidates(index, query, analysis, plan)` 한정. Planner / Verifier / Answer 측정은 **out of scope** (구체적 use case 2개 이상 생기기 전 base class 금지 — 사용자 절대 규칙).
- One phase per invocation. Phase 2-4는 직전 phase의 사용자 승인 영수증을 prerequisite로 가짐.
- Helper code inline 작성 금지. `eval/bootstrap.py` paired CI 미구현 같은 prerequisite gap은 **별개 PR**로 선행 머지 — skill 자체에서 작성 / 우회 거부.
- Verifier / answer 메트릭 mixed-in 금지. phase 도중 "verifier도 같이 보자" 요청 시 거부 + 별도 skill 신설 사유 안내.

## Prerequisites & known mismatches

다음 3개는 **사용자가 본문에 박은 가정과 실제 코드베이스 사이 mismatch**다. Phase 1 진입 전 사용자에게 inline announce.

### 1. Eval gold 필드 mismatch

- **사용자 가정**: `evals/*.jsonl` 에 `sub_queries / evidence_chunk_ids / reasoning_summary / difficulty` 필드.
- **실제**: gold 위치는 [eval/dev_queries_v1.jsonl](../../../eval/dev_queries_v1.jsonl), [eval/dev_queries_multihop_v1.jsonl](../../../eval/dev_queries_multihop_v1.jsonl), [eval/multiturn_scenarios_v1.jsonl](../../../eval/multiturn_scenarios_v1.jsonl). 필드는 `qid / question_type / target_doc_ids / target_projects / question / gold_answer / must_include / acceptable_aliases / should_abstain / parent_qid / notes`.
- **영향**: oracle sub-queries는 별도 파일 `eval/oracle_subqueries_v1.yaml` (qid → list[str]) 로 supply 필요. skill은 파일 존재만 검사하고 미존재 시 Phase 1 진입 거부.

### 2. Paired bootstrap CI 미구현

- **사용자 protocol 가정**: 모든 비교에 paired bootstrap CI 95%, "NOT SIGNIFICANT" 태그.
- **실제**: [eval/bootstrap.py](../../../eval/bootstrap.py) `bootstrap_ci(values, seed=None)` 단일 배열만 지원.
- **영향**: Phase 2 진입 prerequisite로 paired CI helper PR 선행 머지. helper 미존재 시 Phase 2 진입 거부 — "skill 안에서 helper 임시 작성"은 Refusal pattern (a).

### 3. `question_type` ↔ 5카테고리 mapping 미확정

- **사용자 protocol 5분류**: single-hop / multi-hop / long-context / distractor-heavy / no-answer.
- **실제 `question_type` 값**: "single_extract", "multihop", … (정확한 enum은 Phase 1 raw dump으로 확인).
- **영향**: Phase 1 진입 전 사용자에게 mapping 1회 확정 요청 (예: `{"single_extract": "single-hop", "multihop": "multi-hop", …}`). 확정 영수증 없으면 카테고리 분해 안 함.

## 4-phase workflow

각 phase: (a) prerequisite check → (b) protocol 본문 (사용자 verbatim) → (c) 보고 체크리스트 → (d) STOP gate.

### Phase 1 — Current retriever profiling

**Prerequisite**: oracle sub-queries YAML 존재 + `question_type` ↔ 카테고리 mapping 영수증.

**Protocol (사용자 verbatim)**:

1. 현재 retriever 구현 그대로 실행. 입력은 **oracle sub-queries** (planner 우회).
2. 위 metric 전부 계산. 카테고리별로 분해. raw per-query 결과 저장.
3. 보고: 가장 약한 카테고리 top 2, 실패 sample 10개 (query + retrieved chunks + gold chunks 비교).

**측정 대상**:

- `recall@k` (k ∈ {1, 3, 5, 10}) — gold `target_doc_ids` 대비
- `MRR`, `nDCG@10`
- Latency p50/p95, embedding/rerank 비용
- 카테고리별 분해 (single-hop / multi-hop / long-context / distractor-heavy / no-answer)

**보고 체크리스트**: ☐ raw 숫자 (recall@1,3,5,10 / MRR / nDCG@10 / latency p50,p95 / cost) ☐ 카테고리별 분해 (5분류) ☐ 약한 카테고리 top 2 ☐ 실패 sample 10개 (query + retrieved + gold + diff). 기존 metric은 [eval/scorers/chunk_metrics.py:42](../../../eval/scorers/chunk_metrics.py) `chunk_recall_at_k` / `chunk_mrr` / `chunk_ndcg_at_k` 재사용.

**STOP**: Phase 1 보고서 (≤ 200줄, 아래 template) 작성 → 사용자 명시 승인 전 Phase 2 진입 금지.

### Phase 2 — Chunking ablation

**Prerequisite**: Phase 1 사용자 승인 영수증 + paired bootstrap CI helper PR 머지 완료. helper 미존재 시 거부 + "[eval/bootstrap.py](../../../eval/bootstrap.py) `bootstrap_ci`는 단일 배열만 지원, paired 버전은 별도 PR 선행 필수" 안내.

**Protocol (사용자 verbatim)**:

1. 현재 chunking 전략 명시 (size, overlap, splitter). 변형 3개:
   - smaller chunks (e.g. 절반 크기 + overlap 비례 조정)
   - larger chunks (2배)
   - structure-aware splitter (heading/section 경계 사용)
2. 동일 oracle sub-queries로 4개 변형 비교. paired bootstrap CI 동반.
3. 카테고리별 winner 보고. 단일 winner가 없으면 명시.

**보고 체크리스트**: ☐ 4개 변형 (현재 + smaller + larger + structure-aware) recall@5 + paired CI 95% ☐ 카테고리별 winner ☐ 단일 winner 미존재 시 "NOT SIGNIFICANT" 태그 (CI가 0 가로지름) ☐ seed 3개 평균 ☐ chunking 전략 명세 (size / overlap / splitter)

**STOP**: Phase 2 보고서 → 사용자 승인 전 Phase 3 진입 금지.

### Phase 3 — Retrieval mode ablation

**Prerequisite**: Phase 2 사용자 승인 영수증 + Phase 2 winner chunking 확정.

**Protocol (사용자 verbatim)**:

1. 변형:
   - dense only (현재)
   - BM25 only
   - hybrid (RRF or weighted)
   - hybrid + cross-encoder reranker (top-50 → top-10)
2. Phase 2 winner chunking 기준으로 측정. 위 metric 전부 + cost 보고.
3. Pareto plot (recall@5 vs latency, recall@5 vs $/query).

**보고 체크리스트**: ☐ 4개 변형 metric 전부 + paired CI ☐ Pareto plot 2개 (recall@5 vs latency / recall@5 vs $/query) ☐ cost 측정 방법 (embedding $/1k tokens + rerank $/1k pairs) 명시 ☐ seed 3개 평균

**STOP**: Phase 3 보고서 → 사용자 승인 전 Phase 4 진입 금지.

### Phase 4 — Metadata / filtering

**Prerequisite**: Phase 3 사용자 승인 영수증.

**Protocol (사용자 verbatim)**:

1. RFP 문서 메타데이터 (섹션, 페이지, 발주처 등) 사용 가능 여부 확인.
2. Pre-filter (query-conditioned metadata filter) vs post-filter 비교. 메타데이터 적용 가능 카테고리 한정으로 측정.
3. 메타데이터로 recall이 올라가는 쿼리 패턴 식별.

**보고 체크리스트**: ☐ 사용 가능 메타데이터 enumeration ☐ pre-filter vs post-filter recall + paired CI (적용 가능 카테고리만) ☐ recall ↑ 쿼리 패턴 식별 (예: "발주처 명시 query는 metadata pre-filter로 +X pp")

**STOP**: Phase 4 보고서 → Acceptance section 체크리스트 전체 통과 후 skill 호출 종료.

## Common rules (every phase)

- **1줄 CLI 재현**. 모든 변형은 1줄 명령어로 재현 가능. 보고서에 명시.
- **Paired bootstrap CI 95%**. CI가 0 가로지르는 개선 주장은 **"NOT SIGNIFICANT"** 태그 동반. 태그 없이 보고 금지.
- **Seed 3개 평균**. 단일 seed 결과 보고 금지.
- **실행 로그**: `reports/retrieval/<run_id>/` 에 timestamp + git hash + config + per-example raw 결과 + aggregated metrics 저장. `<run_id>` = `YYYYMMDD-HHMM-<phase>-<variant>`.
- **STOP gate 영수증 키워드**: "진행" / "go" / "다음 phase" / "ok". 이외는 모두 질문으로 간주, phase 진입 금지.

## Absolute rules (사용자 verbatim, paraphrase 금지)

- **코드 먼저, 문서 마지막.** 실제 데이터에서 동작하는 코드와 측정된 숫자가 나오기 전엔 README, 다이어그램, 장문 docstring 금지.
- **Fake metric 금지.** 모든 숫자는 실제 실행 결과. 추정치, "expected" 값, 보간 금지. 재현 커맨드 함께 기록.
- **조기 추상화 금지.** 가장 단순한 동작 버전 먼저. 구체적 use case 2개 이상 생기기 전 base class/interface 설계 금지.
- **새 의존성은 정당화.** stdlib + pytest + pandas + 기존 deps 우선. 추가 시 한 줄 사유.
- **실패 정직 보고.** 이전 주장이 틀렸음이 드러나면 명시. 조용한 retcon 금지.

이 5개는 사용자가 본문에 박은 그대로. skill body 안에서도 paraphrase 금지.

## Phase report template

≤ 200줄 markdown. 미준수 시 STOP gate 통과 거부.

````markdown
# Phase N report — <variant or focus>

## 만든 파일 + LOC
- <file path>:<LOC> — <purpose>

## Raw 숫자
| metric | value | paired CI 95% | NOT SIGNIFICANT? |
|---|---|---|---|
| recall@5 | X | [a, b] | yes/no |
| MRR | … | … | … |
| nDCG@10 | … | … | … |
| latency p50/p95 | … | (CI 해당 없음) | n/a |
| cost $/query | … | (CI 해당 없음) | n/a |

## 카테고리 분해 (5분류)
| category | recall@5 | paired CI | weakness rank |
|---|---|---|---|
| single-hop | … | … | … |
| multi-hop | … | … | … |
| long-context | … | … | … |
| distractor-heavy | … | … | … |
| no-answer | … | … | … |

## 약한 카테고리 top 2 + 실패 sample
1. <category> — <why weak (1 line)>
   - sample 1-5: <query, retrieved chunks (top-5), gold chunks (target_doc_ids), diff>
2. <category> — <why weak>
   - sample 6-10: …

## 예상 ↔ 실제 gap
- 예상: <what I expected before running>
- 실제: <what raw numbers showed>
- 해석: <which hypothesis survives, which doesn't>

## 다음 phase 위험 + go/no-go 추천
- 위험 1: <prerequisite gap, data quality concern, etc.>
- 위험 2: …
- 추천: <go / hold for X / no-go>

## 재현
- 1줄 CLI: `<exact command>`
- git hash: `<sha>`
- config: `reports/retrieval/<run_id>/config.json`
- seed 3개 평균: yes (seeds = [a, b, c])
````

## Acceptance checklist (skill 호출 종료 직전)

종료 직전 모든 항목 확인. 미통과 시 종료 거부.

- ☐ Oracle sub-queries YAML 존재 (`eval/oracle_subqueries_v1.yaml`)
- ☐ Paired CI helper 존재 (Phase 2+ 진입한 경우)
- ☐ `question_type` ↔ 5카테고리 mapping 사용자 확정 영수증
- ☐ 모든 phase가 1줄 CLI 재현 가능
- ☐ seed 3개 평균 (단일 seed 결과 없음)
- ☐ Paired bootstrap CI 95% 동반 (Phase 2+)
- ☐ CI가 0 가로지른 metric은 "NOT SIGNIFICANT" 태그
- ☐ 로그 디렉터리 + git hash 기록 (`reports/retrieval/<run_id>/`)
- ☐ 모든 phase 보고서 ≤ 200줄
- ☐ 절대 규칙 5개 위반 0건 (코드 먼저 / fake metric / 조기 추상화 / 새 의존성 / 정직 보고)
- ☐ 모든 phase에 STOP gate 사용자 승인 영수증 존재 (해당 phase 진입 전 메시지 인용)

## Refusal patterns

다음 3개는 명시적 거부 + 사유 안내. 우회 요청해도 거부 유지.

- **(a) Helper 코드 inline 작성 요청** ("paired CI 함수 여기서 같이 짜줘", "oracle loader skill 안에서 한 줄 만들자").
  - 거부 문구: "이 skill은 guide + acceptance checklist 전용. helper는 별개 PR로 선행. 사유 — skill 유지보수 부담 최소화 + 사용자 절대 규칙 '조기 추상화 금지'."
- **(b) Verifier / answer 메트릭 mixed-in** ("retrieval 측정하는 김에 verifier f1도 같이 보자").
  - 거부 문구: "retrieval-eval은 [rag_retrieval.py:314](../../../rag_retrieval.py) `retrieve_candidates` 한정. verifier/answer는 별도 skill로 — 단, 구체적 use case 2개 이상 생기기 전 만들지 않음 (사용자 절대 규칙 '조기 추상화 금지')."
- **(c) STOP gate 우회 요청** ("Phase 1 보고서 안 써도 되니 Phase 2 바로 가자", "오케이 다 자동으로 한 번에 돌려").
  - 거부 문구: "STOP gate는 사용자가 본문에 '각 phase 종료 시 STOP, 내 승인 전 다음 phase 금지'로 박은 규칙. 우회 거부. Phase N 보고서 template을 먼저 채워달라."

## References

- 사용자 본문 protocol — 이 conversation 시작 시점 메시지 (`Component: Retrieval`).
- [rag_retrieval.py:314](../../../rag_retrieval.py) — retrieval entry `retrieve_candidates(index, query, analysis, plan)`.
- [eval/scorers/chunk_metrics.py:42](../../../eval/scorers/chunk_metrics.py) — `chunk_recall_at_k` / `chunk_mrr` / `chunk_ndcg_at_k`.
- [eval/bootstrap.py](../../../eval/bootstrap.py) — `bootstrap_ci` (단일 배열, paired 미구현).
- [eval/dev_queries_v1.jsonl](../../../eval/dev_queries_v1.jsonl) — eval gold + 실제 필드명 (mismatch 근거).
- [.claude/skills/ship-pr/SKILL.md](../ship-pr/SKILL.md) — STOP gate + approval-gate 컨벤션 참조.
- [.claude/skills/adr-portfolio-signals/SKILL.md](../adr-portfolio-signals/SKILL.md) — single-input + scope-decline 패턴.

## What this skill does NOT do

- Does NOT write helper code (oracle loader, paired CI wrapper, Pareto plot generator, report writer). All helpers live in `eval/` as standalone PRs.
- Does NOT cover verifier / answer-quality / planner ablation. 별도 skill 후보지만 use case 2개 이상 생기기 전 생성 금지.
- Does NOT auto-execute phase steps. skill은 절차 / 체크리스트 안내만, 실제 `retrieve_candidates` 호출은 사용자가 trigger.
- Does NOT bundle multiple phase reports. one phase = one invocation block, sequential.
- Does NOT generate fake / interpolated metrics under any circumstance. 사용자 절대 규칙 "fake metric 금지".
