---
name: eval-framework-progressive-audit
description: |
  Progressive 5-phase AUDIT of the BidMate-DocAgent agentic RAG evaluation framework.
  Diagnoses (does NOT build) gaps in component-level isolation, oracle ceilings, statistical
  rigor, process/trajectory metrics, and the closed error loop. Each phase ends in a STOP +
  raw-measurement report + gap table + supply proposal — real construction is a separate PR
  after explicit user approval.

  Trigger phrases (English): "audit eval framework", "eval framework audit", "component eval
  audit", "5-phase eval audit", "/eval-framework-progressive-audit".
  Trigger phrases (Korean): "eval 프레임워크 점검", "평가 프레임워크 audit", "컴포넌트 평가
  점검", "phased eval 점검 시작", "다음 phase 점검 진행" (이 skill이 이미 활성화된 컨텍스트에서).

  Do NOT trigger for: ad-hoc single-metric measurement, one-off retrieval debugging, eval
  config tweaks unrelated to the framework, generic RFP DocAgent work, or eval-result questions
  ("이번 run 결과 어때?"). Do NOT trigger when the user wants to BUILD harness code — this skill
  emits diagnoses + supply proposals only; actual construction is a separate skill/PR after
  audit findings are accepted. Also do NOT trigger for retrieval-only audit work — the sibling
  `/retrieval-eval` skill (PR #889) owns that 4-phase scope.
---

# /eval-framework-progressive-audit — 5-phase eval framework audit

## Context

`BidMate-DocAgent`는 RFP 문서 분석용 agentic RAG 시스템.
Pipeline: Query Analyzer → Planner → Retriever → Verifier/Retry → Answer Generator.

**점검 동기:**
- Eval set이 작아 통계적 검정력이 부족함이 의심됨
- Ablation 결과가 flat — eval set의 distinguishing power 부족 또는 component isolation 부재가 의심됨
- "Agentic" framing이 모호함 — 사실상 conditional pipeline일 가능성
- 과거에 documentation이 implementation보다 앞서 나가는 패턴이 반복됨

이 skill은 위 의심을 **데이터로 확정짓기 위한 audit** 프레임워크. 무엇이 부재한지 / 무엇이
측정 불가능한지를 phase 단위로 진단하고, 각 phase 종료 시 raw 측정 + gap table + supply
제안만 산출. 실제 harness 구축 / 신규 코드는 audit 결과를 사용자가 수용한 뒤 별개 PR.

`/retrieval-eval` skill (PR #889) 은 retriever 전용 4-phase audit 의 sibling — 이 skill은
프레임워크 전체 (planner + retriever + verifier + generator + 통합) 를 다룬다.

## Goal

다음을 진단(audit)할 수 있는 점검 프레임워크 운영.

1. 각 component를 oracle input으로 격리 측정할 수 있는 **인터페이스 부재 여부** 진단
2. Oracle ceiling (counterfactual 천장) 산출 **가능 여부** 진단
3. Noise와 진짜 개선을 통계적으로 구분할 **CI / multi-seed 운영 여부** 진단
4. Process metric (latency, retry count, $/query) **수집 범위** 진단 (`reports/eval_summary.json` `stage_latency` 등 기존 자산 활용도 포함)
5. Final answer 정확도뿐 아니라 **trajectory rationality 측정 여부** 진단
6. Failure taxonomy / failure distribution dashboard / closed loop (실패 → eval set 성장) **운영 여부** 진단

각 goal에 대해 audit 결과는 다음 셋 중 하나: `present` / `partial` / `absent`. 각 진단에는
raw 측정 (file path + LOC + 호출 위치) 근거 동반.

## 절대 규칙 (먼저 읽을 것)

- **코드 먼저, 문서 마지막.** Audit 결과 보고에도 동일 적용 — 실제 측정 + 실제 grep / file
  inspection 결과 없이 markdown 진단 작성 금지. "측정되지 않은 부재"는 부재가 아님.
- **Fake metric 금지.** 모든 숫자는 실제 데이터에서 실제 실행한 결과 또는 실제 file 내용
  근거여야 하며 재현 커맨드 (`grep`, `wc`, `python -c`) 가 기록되어야 함. "expected absent"
  같은 추정 금지.
- **조기 추상화 금지.** Audit 단계에서는 supply 제안만 — 실제 base class / interface 설계는
  audit 결과 수용 후 별개 PR. 진단 turn에 "그래서 이런 class를 만들자" 의 LOC 작성 금지.
- **새 의존성 추가 시 정당화 필수.** Audit 단계에서는 stdlib + pytest + pandas + 기존 deps
  로 측정만 — 신규 의존성 도입은 supply 제안 단계에서만 검토 (도입 자체는 별개 PR).
- **실패 정직 보고.** 어떤 phase에서 이전 phase의 진단이 틀렸음이 드러나면 phase report에
  명시적으로 보고할 것. 조용히 retcon 금지.

## Phased audit plan

순서대로 진행. 각 phase 종료 시 **STOP**하고 phase audit report (markdown, 200줄 이내)
작성: 무엇을 측정했는지 (raw 수치 + 재현 커맨드), 어떤 gap이 발견되었는지, supply 제안
(어떤 인터페이스 / 어떤 fixture 가 필요한지) 만 — 실제 구현 LOC 금지. 다음 phase 진행 전
사용자 명시 승인 필요.

### Phase 1 — Eval set audit

1. 현재 eval set 로드. 출력: n, query 길이 분포, gold answer 길이 분포, 카테고리 분포,
   no-answer 비율. 모든 jsonl set (`eval/dev_queries_v1.jsonl`,
   `eval/dev_queries_multihop_v1.jsonl`, `eval/multiturn_scenarios_v1.jsonl`,
   `eval/adversarial/prompt_injection_ko.jsonl`) 별도 측정.
2. **Distinguishing-power 측정.** 의도적으로 망가뜨린 baseline 3개 정의 제안:
   - `random_retrieval`: retriever를 random chunk sampling으로 교체
   - `no_verifier`: verifier/retry loop 제거
   - `single_chunk`: top-1 chunk만 사용, context assembly 없음

   `eval/config.yaml` 의 기존 ablation 메커니즘으로 이 3개 baseline 을 row 로 추가 **가능
   여부** 진단. 가능하면 supply 제안 (별개 PR), 불가능하면 차단 원인 진단.
3. **n ≥ 200 카테고리 균형** spec vs 실태 gap table 작성. 카테고리: Single-hop factual /
   Multi-hop / Ambiguous / No-answer / Distractor-heavy / Long-context. 각각 현재 분포를
   기존 4 카테고리 (single_extract / follow_up / compare / abstention) 와 매핑 — 어느 한쪽이
   비어 있다면 명시.
4. **Layered gold annotation** 부재 진단:
   - Gold final answer — `gold_answer` 필드로 **present**
   - Gold sub-queries (planner 평가 기준) — **absent / partial 측정**
   - Gold evidence chunk IDs (retriever 평가 기준) — `target_doc_ids` 가 chunk-level 인지
     doc-level 인지 측정
   - Gold reasoning summary (trajectory 평가 기준) — **absent / partial 측정**
   - 난이도 라벨 (easy/medium/hard) — **absent / partial 측정**
5. **Private real eval** (ADR 0005 boundary) audit: `eval/real_config.example.yaml` /
   `eval/private_hardcase.example.yaml` 가 커밋된 example 인지, 실제 private 100-doc 이
   local-only 인지 확인. ADR 0005 위반 없는지 진단.

**Phase 1 acceptance:** raw 수치 + 재현 커맨드 포함된 7-item gap table 산출; broken baseline
3개 supply 제안 (config row 패치 형태) 산출; layered annotation 부재 항목 명시. **실제 eval
set 재구축 / config.yaml 수정 / annotation 작성 0건** — 모두 supply 제안만.

### Phase 2 — Component isolation audit

1. 각 component 별로 **oracle-injected upstream input 으로 평가할 수 있는 인터페이스가
   존재하는지** 측정:
   - `planner_eval(query) → sub_queries`: gold sub-queries 대비 decomposition F1 + LLM-as-judge rubric
   - `retriever_eval(sub_query OR oracle_sub_queries) → chunks`: gold chunk ID 대비 recall@k, MRR, nDCG
   - `verifier_eval(context, claim) → sufficient?`: 라벨링된 (context, claim, sufficiency) 쌍에서 precision/recall
   - `generator_eval(query, oracle_context) → answer`: faithfulness, answer correctness, citation accuracy

   각 인터페이스에 대해 `rag_query.py` / `rag_retrieval.py` / `rag_verifier.py` /
   `rag_answer.py` 의 entrypoint 와 oracle-injection 가능 지점 grep — 현재 oracle switch 가
   있는지 (`eval/config.yaml` flag 등) 측정.
2. **Oracle injection switch 부재 여부** 진단. 각 pipeline 경계에 config flag 하나로 real
   vs oracle input 토글 가능한지 — 가능하면 file path + flag name 인용, 불가능하면 차단
   원인 진단.
3. **5개 조건 실행 가능 여부** 진단: 전부 real / oracle planner / oracle retriever / oracle
   verifier / oracle generator. 각 조건이 CLI 한 줄로 실행 가능한지 측정 — 현재
   `eval/run_eval.py` 의 ablation row 표현력으로 어디까지 가능한지.

**Phase 2 acceptance:** 4-component × oracle-switch 가능여부 표 산출; supply 제안 (어느
경계에 oracle injection point 가 필요한지) 명시; raw grep / file inspection 결과 포함.
**실제 oracle switch 구현 0건.**

### Phase 3 — Process + trajectory audit

1. **Per-query 로깅 범위** 진단: total latency, component별 latency, retriever call count,
   verifier retry count, token in/out, 추정 $. 어떤 항목이 이미 수집되는지 (현재
   `reports/eval_summary.json` `stage_latency` block 인용) / 무엇이 누락인지 측정.
2. **Trajectory 직렬화 가능 여부** 진단: 전체 trajectory (모든 LLM call의 input/output) 이
   eval 예제별 구조화 포맷으로 저장 가능한지. 저장된다면 file path / schema 인용, 안 되면
   차단 원인 진단.
3. **Trajectory-rationality rubric 존재 여부** 진단 (LLM-as-judge 기반): "Planner
   decomposition이 query 의도와 일치하는가? Retrieval 재호출이 합당한 이유로 발생했는가?
   Verifier 판정이 evidence와 정합적인가?" rubric 또는 prompt 가 repo 에 있는지 grep.
4. **Pareto reporting 가능 여부** 진단: quality vs cost 를 2D 로 plot 하는 자산이 있는지
   측정 (`scripts/plot_cost_frontier.py` 등). 있으면 file 인용, 없으면 supply 제안.

**Phase 3 acceptance:** per-query 로깅 / trajectory 직렬화 / rationality rubric / pareto
plot 4-item present/partial/absent 표 산출; 누락 항목별 supply 제안 명시. **실제 로깅
추가 / trajectory writer 작성 0건.**

### Phase 4 — Statistical rigor audit

1. **Multi-seed 운영 여부** 진단. 각 system variant 가 3 seed 이상으로 실행되어 mean ± std
   가 보고되는지 — `eval/run_eval.py` / `eval/config.yaml` 의 seed 처리 grep.
2. **Paired bootstrap CI 운영 여부** 진단. Variant 비교 시 동일 eval 예제에 대한 paired
   bootstrap CI 가 산출되는지 — `eval/bootstrap.py` 의 현재 능력 측정 (paired vs unpaired,
   CI level, sample size 요구).
3. **`claim_validator.py` 부재 여부** 진단. 개선 주장(e.g. "verifier가 accuracy를 4% 개선")을
   입력받아 측정된 Δ, CI, sample size, p-value 출력하고 CI 가 0을 가로지르는 주장을 거부할
   validator 가 존재하는지 — repo grep. 없으면 supply 제안 (file path / signature 제안).

**Phase 4 acceptance:** multi-seed / paired bootstrap / claim validator 3-item
present/partial/absent 표 산출; 각 누락 항목 supply 제안 명시. **실제 validator 구현 / seed
스윕 추가 0건.**

### Phase 5 — Closed error loop audit

1. **Failure taxonomy 정의 존재 여부** 진단. (시작 카테고리: retrieval_miss /
   planner_under_decomposition / verifier_false_negative / verifier_false_positive /
   generator_hallucination / context_dilution / unknown). 현재 repo 에 taxonomy 정의 파일
   / 태깅 자산이 있는지 grep.
2. **Failure distribution 대시보드 생성 가능 여부** 진단 (bar chart + table). 자산이 있으면
   file 인용, 없으면 supply 제안.
3. **Eval set monotone-harden process 부재 여부** 진단. 새 failure mode 발견 → 카테고리 추가
   + 해당 패턴 예제 ≥ 5개를 eval set에 추가하는 워크플로 / 자동화 / 거버넌스 문서가 있는지
   진단.

**Phase 5 acceptance:** taxonomy / distribution dashboard / monotone-harden process 3-item
present/partial/absent 표 산출; 각 누락 항목 supply 제안 명시 + audit 중 실제로 새 failure
mode 1개 이상이 raw 측정 (broken baseline 실행 결과 또는 기존 `reports/` 분석) 에서
발견되었는지 보고. **실제 taxonomy 파일 추가 / 대시보드 작성 0건.**

## Repo conventions

- `evals/`: eval set 데이터 및 스크립트. `evals/run.py`가 entrypoint
- `metrics/`: metric 구현 (모듈별 분리 + unit test)
- `reports/`: phase audit report 및 결과 스냅샷 (jsonl + markdown summary)
- `pytest` 사용. metric monotonicity 같은 곳엔 property-based test 적용
- 모든 eval 실행은 저장: timestamp, git commit hash, config, per-example raw 결과, aggregated metrics
- Random seed 명시적; 숨은 nondeterminism 금지

(BidMate-DocAgent 실제 surface 는 `eval/` (single 's') / `rag_*.py` / `eval/run_eval.py` —
위 일반 convention은 audit report 작성 시 따르되, 측정 대상 파일 경로는 실제 repo 경로로 인용.)

## 턴 단위 작업 방식

- 매 턴: 1개 phase 분량 (또는 blocker 만나면 그 이하)
- 매 턴 종료 시 audit report: 측정 명령(`grep`, `wc -l`, `python -c`), raw 결과 인용, gap
  table, supply 제안 — supply 제안은 어떤 file 에 어떤 인터페이스 / fixture / config row 를
  추가할지 **제안만**, 실제 구현 LOC 금지.
- 사용자 승인 없이 다음 phase 시작 금지
- **Audit ≠ build**: audit 결과는 raw 측정 + gap, supply 제안만. 실제 구축은 사용자 승인 후
  별개 PR (skill 외부) — 이 skill의 어떤 turn 도 production code 수정 / 신규 module 생성
  하지 않음. 만약 supply 가 1-line config 패치 수준이면 사용자가 명시적으로 "이 turn에
  반영" 이라고 승인할 때만 적용.
- 이전 phase의 진단이 틀렸음이 드러나면 다음 report에 명시. 조용한 retcon 금지

## 첫 번째 action

Phase 1의 step 1만 수행: 현재 eval set 4개 jsonl 파일을 `wc -l` + 1행 schema 인용 + 기존
summary 파일(`eval/dev_queries_v1_summary.md` 등) 인용으로 프로파일 출력. **새 코드 / 새
파일 작성 0건**. 지금 무엇이 있는지만 보고할 것 — gap 분석은 step 3 이후, supply 제안은
phase report 마지막.
