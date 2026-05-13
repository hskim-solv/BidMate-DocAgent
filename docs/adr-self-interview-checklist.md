# ADR Self-Interview Checklist

본 문서는 BidMate-DocAgent ADR 29개에 대한 **시니어 면접 대비 자가진단** 도구다.
[`senior-positioning.md`](senior-positioning.md) (outward, 리뷰어용)와 짝을 이루는 **inward·line-level audit** — "내가 이 ADR을 진짜 아는가" 를 5분 카드 사이클로 측정한다.

## 사용법

1. 한 번에 1개 ADR 카드를 골라 5분 타이머를 켠다.
2. 카드의 Q1·Q2·Q3에 **소리 내어 답한다** — LLM·문서·코드 검색 일절 금지. ADR 본문조차 보지 않는다.
3. 3개 모두 30초 이내 즉답되면 `3/3`, 1개라도 막히면 `x/3` + 막힌 Q 번호를 [`memory/adr_interview_log.md`](file:///Users/hskim/.claude/projects/-Users-hskim-Desktop-projects-BidMate-DocAgent/memory/adr_interview_log.md) 에 1줄 기록.
4. 1주 후 같은 ADR을 다시 돌려 회귀 측정(3/3 → 2/3 이하면 빨간불).
5. Q1·Q3는 매월 1개 rotate — variant 후보는 카드 하단 `<!-- variants -->` 주석에 적어두고 교체.

**카드에 정답을 적지 않는다.** 정답 *위치*(`file:___`)만 적고, 그것조차 line 번호는 빈칸으로 두어 *기억에서 호출*하는 것을 강제한다.

## Ownership 4축 (이 체크리스트가 검증하는 것)

본 체크리스트는 **#1·#2** 만 ADR 단위로 측정한다. #3·#4 는 행동 surface라 별도 도구 (디버깅 시나리오 워크북, LLM-off PR 가이드 — 후속 plan).

1. **결정 주체성** — trade-off를 본인이 평가하고 골랐는가. Alternatives 섹션을 *무참조로* 30초 안에 1쌍(선택 vs 거부) 댈 수 있는가.
2. **의도 추적성** — 결정이 코드의 *어느 라인*에 잠겨있는지 아는가. file:line을 즉답 가능한가.
3. (별도 도구) 디버깅 자력성 — LLM 끈 채 1시간 안에 가설 수립.
4. (별도 도구) 확장 자력성 — LLM 보조 모드로 PR leading.

## Senior signal 5축 (cross-reference)

[`senior-positioning.md`](senior-positioning.md) 의 시그널 #1~#5 와 각 ADR을 매핑한다. 카드의 `Linked signals` 필드는 이 표를 참조만 — 답이 아니라 *방향 표지*.

- **#1** 아키텍처 결정의 추적성 (ADR + status + supersession)
- **#2** 측정의 엄격성 (95% CI, SHA-256 결정성, empirical threshold)
- **#3** 실패를 시스템적으로 다룬다 (분류 + regression test 잠금)
- **#4** 거버넌스가 코드와 같이 진화 (PR template, hook, SSoT)
- **#5** 재현성을 갖춘 시연 (`make smoke` / `make reproduce`)

## 빨간불 기준 (per-ADR, 4개)

1. **30초 내 trade-off 1쌍(선택 vs 거부)을 못 댄다** — Alternatives 섹션이 사문(死文). #1 결정주체성 fail.
2. **Code anchor 3개 중 2개 이상 파일 위치 미상** — 외운 narrative만 있고 코드 매핑 끊김. #2 의도 추적성 fail.
3. **Q3 (가상 디버깅 "X 지우면 어디서 깨지나") 첫 30초 침묵** — 시스템을 외부에서만 본 상태. 디버깅 자력 신호 0.
4. **1주 후 재시도 score 회귀** (3/3 → 2/3 이하) — 답을 외웠을 뿐 모델 없음. *재시도 가능성*이 self-interview의 핵심 검증.

빨간불 카드는 본문 + 코드 + 인접 PR/이슈를 다시 학습. 1주 후 재측정.

## Phase / Status

- **Phase 1 (이 PR)**: 5개 시범 카드 fully formed — 0001 / 0003 / 0005 / 0008 / 0023. 24개 stub.
- **Phase 2 (follow-up PRs)**: 5개씩 6주에 걸쳐 채움. 한 번에 LLM이 다 채우면 외운 답이 되니 *직접 빈칸 채우는 페이스*가 본질.

---

## Summary Tracker

| #    | Slug                                     | Status   | Senior signal | Ownership | Last tested | Red-flag |
|------|------------------------------------------|----------|---------------|-----------|-------------|----------|
| 0001 | preserve-naive-baseline                  | accepted | #1, #2        | #1, #2    | —           |          |
| 0002 | metadata-first-retrieval                 | accepted | #1, #2        | #1, #2    | —           |          |
| 0003 | structured-answer-citation-contract      | accepted | #1, #4        | #1, #2    | —           |          |
| 0004 | verifier-retry-policy                    | accepted | #1, #3        | #1, #2    | —           |          |
| 0005 | eval-split-public-synthetic-private-local| accepted | #1, #2, #3    | #1, #2    | —           |          |
| 0006 | llm-judge-on-real-data-only              | accepted | #1, #2        | #1, #2    | —           |          |
| 0007 | issue-linked-branch-naming               | accepted | #4            | #1, #2    | —           |          |
| 0008 | evidence-boundary                        | accepted | #1, #5        | #1, #2    | —           |          |
| 0009 | external-baseline-comparison             | proposed | #1, #2        | #1, #2    | —           |          |
| 0010 | hybrid-bm25-dense-retrieval-rrf          | accepted | #1, #2        | #1, #2    | —           |          |
| 0011 | llm-synthesis-as-additive-ablation       | proposed | #1, #3        | #1, #2    | —           |          |
| 0012 | llm-judge-on-public-synthetic            | accepted | #1, #2        | #1, #2    | —           |          |
| 0013 | observability-as-additive-pluggable      | accepted | #1, #4        | #1, #2    | —           |          |
| 0014 | ragas-judge-additive-synthetic           | accepted | #1, #2        | #1, #2    | —           |          |
| 0015 | cost-telemetry-additive                  | accepted | #1, #2        | #1, #2    | —           |          |
| 0016 | judge-human-agreement                    | proposed | #1, #2, #3    | #1, #2    | —           |          |
| 0017 | llm-metadata-extraction-additive         | proposed | #1, #3        | #1, #2    | —           |          |
| 0018 | korean-public-rag-bench                  | accepted | #2, #5        | #1, #2    | —           |          |
| 0019 | embedding-default-stays-minilm           | accepted | #1, #2        | #1, #2    | —           |          |
| 0021 | bge-m3-completes-phase-1-3               | accepted | #1, #2        | #1, #2    | —           |          |
| 0022 | langgraph-orchestration-stage-1          | accepted | #1, #3        | #1, #2    | —           |          |
| 0023 | hyde-query-expansion-ablation            | proposed | #1, #2        | #1, #2    | —           |          |
| 0024 | agentic-full-llm-as-api-default          | accepted | #1, #3        | #1, #2    | —           |          |
| 0025 | cost-frontier-defer-until-real-baselines | accepted | #1, #2        | #1, #2    | —           |          |
| 0026 | cross-encoder-reranker-deferral          | accepted | #1, #2        | #1, #2    | —           |          |
| 0027 | lora-finetuned-embedding-additive        | proposed | #1, #2        | #1, #2    | —           |          |
| 0028 | security-screen-additive                 | accepted | #1, #5        | #1, #2    | —           |          |
| 0029 | real-data-case-proposer-additive         | proposed | #1, #3        | #1, #2    | —           |          |
| 0030 | leaderboard-headline-includes-agentic    | accepted | #1, #2        | #1, #2    | —           |          |

(0020 결번. Senior signal 매핑은 *제안*이며 카드 작성 시 조정.)

---

## Phase 1 시범 카드 (5개)

### ADR 0001 — Preserve naive baseline (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off (선택 1 / 거부 1)**: ___ / ___
- **Q1 (counterfactual)**: 왜 `agentic_full` 한 줄만 ship하고 `naive_baseline` 을 drop하지 않았나? "extra complexity가 일을 하는가" 를 어떻게 증명 가능 상태로 두는가?
- **Q2 (line-level)**: `naive_baseline` preset을 누군가 silent하게 제거하려 하면 *어느 함수 한 줄* 이 source of truth로 막아주는가? 그 함수 이름은?
- **Q3 (가상 디버깅)**: agentic_full이 baseline보다 citation_grounding이 낮아지는 회귀가 들어왔을 때, 어떤 artifact의 어떤 컬럼에서 가장 먼저 보이는가?
- **Code anchors (file:line)**: `rag_core.py:___` (`pipeline_cli_choices`) / `eval/config.yaml:___` (ablation rows) / `app.py:___` (CLI default)
- **Linked signals**: senior #1(추적성), #2(측정 엄격성) | ownership #1, #2
- **Self-score log**:

<!--
variants (rotate monthly):
- Q1 alt: "naive baseline을 코드에 두되 eval에서 빼는 안은 왜 기각됐나?"
- Q3 alt: "make ask로 같은 query를 baseline vs full로 돌려 비교하려면 명령은?"
-->

### ADR 0003 — Structured answer / citation contract `schema_version: 2` (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off (선택 1 / 거부 1)**: ___ / ___
- **Q1 (counterfactual)**: 왜 free-text 답변 + regex citation 파싱을 거부했나? LangChain의 generic response model 옵션은 왜 기각됐나?
- **Q2 (line-level)**: `schema_version: 2` literal과 `status ∈ {supported, partial, insufficient}` enum이 *어느 파일·어느 상수*에 박혀있나? `claims` 안의 chunk_id가 evidence list 밖을 가리키면 *어느 함수*에서 거부되는가?
- **Q3 (가상 디버깅)**: 누군가 `answer_text` 형식을 바꿔 eval 메트릭에 영향을 주려 한다면, ADR 0003은 어디서 그것을 막는가? (힌트: "tooling must not key off it")
- **Code anchors (file:line)**: `rag_answer.py:___` (`generate_answer` / `build_claims`) / `rag_answer_schema.py:___` (`ANSWER_SCHEMA_VERSION` / `ANSWER_STATUS_*`) / `eval/run_eval.py:___` (메트릭 key-off 지점)
- **Linked signals**: senior #1(추적성), #4(거버넌스) | ownership #1, #2
- **Self-score log**:

<!--
variants:
- Q1 alt: "insufficiency를 fallback이 아니라 first-class status로 만든 이유는?"
- Q2 alt: "verifier가 partial 판정을 내릴 때 status_reason.code는 어떤 값이 가능한가?"
-->

### ADR 0005 — Eval split (public synthetic vs private local) (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off (선택 1 / 거부 1)**: ___ / ___
- **Q1 (counterfactual)**: 단일 config + 조건부 private extension 안이 왜 기각됐나? public-only 또는 private-only 안 각각의 결정적 결함은?
- **Q2 (line-level)**: private corpus 본문이 commit되지 않도록 막는 *2가지 메커니즘*은 어디에 코드화되어 있나? (`*.example.yaml` 컨벤션 + `.gitignore` 행)
- **Q3 (가상 디버깅)**: 누군가 `eval/real_config.local.yaml` 또는 `data/files/<corp>.pdf` 를 `git add` 하려 한다면, 어느 hook 또는 CI gate가 어느 단계에서 막아주는가? 막지 못한다면 어디가 빠진 것인가?
- **Code anchors (file:line)**: `eval/config.yaml:___` (public surface) / `eval/real_config.example.yaml:___` (scaffold) / `.gitignore:___` (boundary 행)
- **Linked signals**: senior #1, #2, #3 | ownership #1, #2
- **Self-score log**:

<!--
variants:
- Q1 alt: "왜 README headline은 공개 합성에서만 끌어오나? 비공개 결과를 README에 올릴 수 없는 이유는?"
- Q3 alt: "실수로 private case가 commit됐을 때 사후 처리 순서는?"
-->

### ADR 0008 — Evidence text boundary + instruction-like pattern neutralization (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off (선택 1 / 거부 1)**: ___ / ___
- **Q1 (counterfactual)**: 왜 `Sanitizer` 클래스 + pluggable rules 대신 단일 helper 함수를 골랐나? "silent strip" 안은 왜 거부됐고, "LLM judge boundary에서만 sanitize" 안은 왜 거부됐나?
- **Q2 (line-level)**: RFP 본문에 `<|im_start|>` 토큰이 섞여 있을 때 그것이 *정확히 어느 함수의 어느 줄*에서 `[REDACTED_CHAT_TOKEN]` 으로 대체되는가? `EVIDENCE_BOUNDARY` 상수는 verifier와 LLM judge 양쪽에 어떤 경로로 도달하는가?
- **Q3 (가상 디버깅)**: `neutralize_instruction_patterns` 본문을 no-op (입력 그대로 반환)으로 바꿔도 verifier substring 매칭은 통과한다. 그러면 어느 회귀 테스트가 어떤 메시지로 fail하는가? (힌트: ADR 0008 Wins § "Regression test prevents silent removal")
- **Code anchors (file:line)**: `rag_verifier.py:___` (`EVIDENCE_BOUNDARY` + `neutralize_instruction_patterns`) / `scripts/llm_judge.py:___` (`_build_prompt` apply site) / `tests/test_prompt_injection_regression.py:___`
- **Linked signals**: senior #1(추적성), #5(회귀 잠금) | ownership #1, #2
- **Self-score log**:

<!--
variants:
- Q1 alt: "ADR 0028 (query-side screen)과 0008(evidence-side)이 왜 짝으로 존재해야 하나?"
- Q2 alt: "RFP에 정당하게 '이전 지시사항 무시' 라는 문구가 있는 규정이 들어오면 어떤 일이 생기는가?"
-->

### ADR 0023 — HyDE query expansion ablation (proposed)

- **One-line decision (빈칸)**: ___
- **Trade-off (선택 1 / 거부 1)**: ___ / ___
- **Q1 (counterfactual)**: 왜 `Reranker` Protocol을 재사용하지 않고 별도 `QueryExpander` Protocol을 만들었나? "raw query를 HyDE로 전면 교체" 안은 왜 거부됐나?
- **Q2 (line-level)**: ADR 0001 `naive_baseline` 골든의 비트동일이 *어디서·어떤 키*에 잠겨있나? (`PIPELINE_CONFIG_KEYS` / preset config / expander class — 셋 중 어디서 default가 잠기는지)
- **Q3 (가상 디버깅)**: `IdentityExpander.expand` 를 지우고 `default_expander` 가 unknown 값에 raise하도록 바꾸면, *어느 테스트가 어떤 메시지로 먼저 깨지는가*? 그리고 *어느 ablation 행*이 CI에서 fail하는가?
- **Code anchors (file:line)**: `rag_query_expansion.py:___` (`QueryExpander` + `IdentityExpander` + `default_expander`) / `rag_pipeline_presets.py:___` (`PIPELINE_CONFIG_KEYS` `query_expansion` 키) / `tests/test_naive_baseline_ranking_invariance.py:___`
- **Linked signals**: senior #1, #2 | ownership #1, #2
- **Self-score log**:

<!--
variants:
- Q1 alt: "multi-query HyDE는 왜 이 ADR scope에서 빠졌나? 어떤 trade-off가 더 들어와야 하나?"
- Q3 alt: "ANTHROPIC_API_KEY 없는 CI에서 full_hyde가 full과 byte-equal이 되는 *메커니즘*은?"
-->

---

## Phase 2 stub 카드 (24개)

> 각 카드는 follow-up PR에서 5개씩 fully formed로 land한다. 현재는 title + status + linked signals 만 채워둠.

### ADR 0002 — Metadata-first retrieval (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1 (counterfactual)**: ___
- **Q2 (line-level)**: ___
- **Q3 (가상 디버깅)**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #2 | ownership #1, #2
- **Self-score log**:

### ADR 0004 — Verifier retry policy (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #3 | ownership #1, #2
- **Self-score log**:

### ADR 0006 — LLM judge on real-data only (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #2 | ownership #1, #2
- **Self-score log**:

### ADR 0007 — Issue-linked branch naming (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #4 | ownership #1, #2
- **Self-score log**:

### ADR 0009 — External baseline comparison (proposed)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #2 | ownership #1, #2
- **Self-score log**:

### ADR 0010 — Hybrid BM25 + dense retrieval (RRF) (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #2 | ownership #1, #2
- **Self-score log**:

### ADR 0011 — LLM synthesis as additive ablation (proposed)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #3 | ownership #1, #2
- **Self-score log**:

### ADR 0012 — LLM judge on public synthetic, stub-default (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #2 | ownership #1, #2
- **Self-score log**:

### ADR 0013 — Observability as additive·pluggable·fail-closed (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #4 | ownership #1, #2
- **Self-score log**:

### ADR 0014 — RAGAS judge additive synthetic (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #2 | ownership #1, #2
- **Self-score log**:

### ADR 0015 — Cost telemetry additive (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #2 | ownership #1, #2
- **Self-score log**:

### ADR 0016 — Judge-human agreement calibration (proposed)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #2, #3 | ownership #1, #2
- **Self-score log**:

### ADR 0017 — LLM metadata extraction additive (proposed)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #3 | ownership #1, #2
- **Self-score log**:

### ADR 0018 — Korean public RAG bench (KorQuAD 2.1) (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #2, #5 | ownership #1, #2
- **Self-score log**:

### ADR 0019 — Embedding default stays MiniLM-L12-v2 (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #2 | ownership #1, #2
- **Self-score log**:

### ADR 0021 — BGE-M3 completes Phase 1.3 (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #2 | ownership #1, #2
- **Self-score log**:

### ADR 0022 — LangGraph orchestration Stage 1 (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #3 | ownership #1, #2
- **Self-score log**:

### ADR 0024 — agentic_full_llm as API default (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #3 | ownership #1, #2
- **Self-score log**:

### ADR 0025 — Cost frontier deferral (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #2 | ownership #1, #2
- **Self-score log**:

### ADR 0026 — Cross-encoder reranker deferral (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #2 | ownership #1, #2
- **Self-score log**:

### ADR 0027 — LoRA-finetuned embedding additive (proposed)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #2 | ownership #1, #2
- **Self-score log**:

### ADR 0028 — Security screen additive (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #5 | ownership #1, #2
- **Self-score log**:

### ADR 0029 — Real-data case proposer additive (proposed)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #3 | ownership #1, #2
- **Self-score log**:

### ADR 0030 — Leaderboard headline includes agentic_full (accepted)

- **One-line decision (빈칸)**: ___
- **Trade-off**: ___ / ___
- **Q1**: ___
- **Q2**: ___
- **Q3**: ___
- **Code anchors**: `___:___` / `___:___` / `___:___`
- **Linked signals**: senior #1, #2 | ownership #1, #2
- **Self-score log**:

---

## Related

- [`senior-positioning.md`](senior-positioning.md) — outward 5축 narrative (시그널 #1~#5 정의)
- [`portfolio-launch-checklist.md`](portfolio-launch-checklist.md) — 배포 준비 체크리스트 (목적 다름, 보완 관계)
- `~/.claude/skills/adr-portfolio-signals/SKILL.md` — 단일 ADR을 5축에 yes/partial/no 매핑 (outward evidence pack 용)
- [`memory/adr_interview_log.md`](file:///Users/hskim/.claude/projects/-Users-hskim-Desktop-projects-BidMate-DocAgent/memory/adr_interview_log.md) — 사적 self-score log (1주 회귀 측정)
