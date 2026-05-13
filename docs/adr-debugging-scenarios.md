# ADR Debugging Scenarios Workbook

BidMate-DocAgent ownership 4축 중 **#3 디버깅 자력성** 측정 도구. ADR 결정의 *결과로 만들어진 시스템*이 무너졌을 때, LLM 끈 채 본인이 1시간 안에 가설 → 검증 명령까지 도달할 수 있는가를 자가검증한다.

[`adr-self-interview-checklist.md`](adr-self-interview-checklist.md) (ownership #1·#2)의 자매 문서.

## 사용법

1. 시나리오 1개를 골라 **1시간 타이머**를 켠다. LLM·문서 검색·코드 grep 모두 금지된 상태로 시작 — 본인 머릿속 만으로.
2. **0~30분**: 가설 3개 (`H`/`M`/`L` 우선순위) 와 *왜 그 우선순위인지* 한 줄씩 적는다. 답을 적지 않음 — *어디부터 본다*만.
3. **30~60분**: 검증 명령 (`make` / `pytest` / `grep -n` / `python -c`) 1~2개를 적고 *실제로 돌려본다*. 명령이 가설을 confirm/refute 하는가.
4. Score 2/2 / 1/2 / 0/2 + 막힌 시점 1줄을 [`memory/debugging_scenario_log.md`](file:///Users/hskim/.claude/projects/-Users-hskim-Desktop-projects-BidMate-DocAgent/memory/debugging_scenario_log.md) 에 append.
5. 같은 시나리오 1주 후 재시도 — 점수 회귀 측정.

**답은 카드에 적지 않는다.** 시나리오 (외부 trigger) 와 connected anchors 만 명시; 가설/명령/이유는 매번 *기억에서 호출*한다.

## Ownership 4축 #3 정의

**디버깅 자력성** — "real-eval에서 abstention rate가 30%p 떨어졌다" 같은 가상/실제 시나리오에서 LLM 없이 어디서부터 보겠는지 본인이 list-up 가능하고, *그 가설을 confirm 할 명령*까지 정확히 적을 수 있는가.

- 가설 = `<후보 위치> + 우선순위 + 왜`
- 검증 = `<grep / pytest / git log / make 등 실제 돌릴 수 있는 명령>`
- 둘 다 *외부 도움 없이* 30분 / 30분 = 1시간 안에 land.

## Senior signal 연결

- 시그널 #3 (실패를 시스템적으로 다룬다) — [`docs/real-data-failure-taxonomy.md`](real-data-failure-taxonomy.md) C1~C6 + P0~P3 백로그가 본 도구의 시나리오 source.
- 시그널 #5 (재현성을 갖춘 시연) — 검증 명령은 `make`/`pytest` 같은 *재현 가능* 형식. 추정/감상 금지.

## 빨간불 기준 (per-scenario, 4개)

1. **첫 5분 침묵** — 시스템을 외부에서만 본 신호. 시나리오 자체가 어디 닿는지 인지 0.
2. **가설이 LLM 답안 어조** (`"아마 ~일 가능성이 높습니다"`, `"X로 인해 ~ 한 것으로 보입니다"`) — memorized narrative. 가설은 *후보 위치* 명사구로 적어야.
3. **검증 명령 없이 추정만** — `make` / `pytest` / `grep -n` vocabulary 0. 다음 1시간이 LLM 호출로 흐를 위험.
4. **연결 anchor 1개 미상** — ADR/test/codepath 매핑 끊김. 시스템의 *지도*가 본인 머릿속에 없음.

빨간불 시나리오는 [`docs/real-data-failure-taxonomy.md`](real-data-failure-taxonomy.md) + 인접 ADR + 회귀 테스트를 재학습. 1주 후 재측정.

## Phase / Status

- **Phase 1 (이 PR)**: 4 fully formed 시나리오 — R2 회귀 / naive_baseline golden 깨짐 / verifier false negative (C6 #69) / abstention 분해 (incorrect_answer 증가). 4 stub.
- **Phase 2 (follow-up)**: stub 4개를 1~2주에 1개씩 fully form. LLM 일괄 작성 금지 (외운 가설 함정).

---

## Phase 1 Fully Formed 시나리오 (4개)

### S1 — R2 회귀: 모든 answerable 케이스가 abstain (실 사고 재현)

- **증상 한 줄**: `make real-eval-delta` 표에서 `abstention_rate` 가 base 0.40 → head 1.00 (+0.60). `incorrect_answer` 0, `correct_refusal` 도 base level 그대로 — answerable 케이스 전부가 *false abstain* 으로 빠짐.
- **가설 후보 (사용자가 H/M/L + 왜 채움)**:
  - `___ retrieve loop 본문 missing` — merge conflict resolution 잔여
  - `___ stage_attempts 누적 분기 깨짐` — `retry_count>0` 시 가드 없음
  - `___ verifier topic_not_grounded 임계값 과도 엄격`
- **검증 명령 (실제 돌릴 명령)**: `___ / ___`
- **연결 anchors**: [`tests/test_retrieval_loop_regression.py`](../tests/test_retrieval_loop_regression.py) (R2 regression gate) · ADR 0001 (naive_baseline invariant) · [`real-data-failure-taxonomy.md`](real-data-failure-taxonomy.md) C6
- **Self-score** (가설 land + 명령 정확): `___ / 2` ·  막힌 시점: `___`

<!-- variants:
- 같은 증상, 단 `correct_refusal` 만 증가하고 `abstention_rate` 동일 → 어떤 다른 hypothesis?
- 같은 증상, head 만 깨지고 base 도 같이 → main 의 어떤 회귀?
-->

### S2 — `naive_baseline` golden 깨짐: hashing backend ranking 미세 이동

- **증상 한 줄**: `pytest tests/test_naive_baseline_ranking_invariance.py` 가 새 PR 에서만 fail. diff 출력: `tests/data/naive_baseline_top_k.json` 의 `case_3` chunk_ids 순서가 `["a","b","c"]` → `["a","c","b"]` 로 미세 이동. dense cosine 점수는 본 PR 변경 영역 밖.
- **가설 후보**:
  - `___ tokenize / normalize 보조 함수가 hashing 임베딩에 들어가는 sequence 변경`
  - `___ RRF tie-break 결정성 회귀 (ADR 0001 invariant)`
  - `___ 새 PR 이 비-결정 random/datetime 의존 도입`
- **검증 명령**: `___ / ___`
- **연결 anchors**: [`tests/test_naive_baseline_ranking_invariance.py`](../tests/test_naive_baseline_ranking_invariance.py) · [`tests/data/naive_baseline_top_k.json`](../tests/data/naive_baseline_top_k.json) · ADR 0001 · [`docs/private-100-doc-experiments.md`](private-100-doc-experiments.md) (#189 RRF deterministic tie-break)
- **Self-score**: `___ / 2` · 막힌 시점: `___`

<!-- variants:
- 같은 증상, 단 `tests/data/...` regen 이 정답인가 *틀린 답인가* — ADR 0001 trade-off 호출.
- chunk_ids 순서 대신 점수 자체가 미세 이동 — 어떤 부동소수점/hashing seed 의심?
-->

### S3 — Verifier false negative: `topic_not_grounded` × 2로 9/12 false abstention (C6 root cause)

- **증상 한 줄**: real-eval 12 케이스 중 9 케이스가 `status: insufficient` + `verification_reasons: ["topic_not_grounded", "topic_not_grounded"]`. 해당 evidence chunk 본문에 *topic literal 이 substring 으로 명백히 존재*. answerable 케이스가 false abstain 되는 패턴.
- **가설 후보**:
  - `___ verify_evidence 의 topic grounding 임계값이 partial_topic 으로 회귀`
  - `___ evidence_has_topic 의 normalize/expand_forms 적용 누락`
  - `___ neutralize_instruction_patterns 가 topic literal 도 marker 로 래핑 (ADR 0008 부작용)`
- **검증 명령**: `___ / ___`
- **연결 anchors**: [`rag_verifier.py`](../rag_verifier.py) (`verify_evidence` / `evidence_has_topic` / `PARTIAL_TOPIC_GROUNDING_*`) · ADR 0004 (verifier retry policy) · ADR 0008 (`neutralize_instruction_patterns`) · [`real-data-failure-taxonomy.md`](real-data-failure-taxonomy.md) C6 · #69 incident
- **Self-score**: `___ / 2` · 막힌 시점: `___`

<!-- variants:
- 같은 증상, single-topic query 만 false abstain → `PARTIAL_TOPIC_GROUNDING_MIN_MATCHED` 어느 값에서 회귀?
- 한국어 query 만 false abstain → text_normalize 회귀 의심?
-->

### S4 — Abstention 분해: abstention_rate -0.30 인데 `incorrect_answer` +6

- **증상 한 줄**: real-eval 표에서 `abstention_rate` 0.65 → 0.35 (-0.30) — 표면적으로는 "더 잘 답함". 그러나 `abstention_outcomes.incorrect_answer` 가 4 → 10 (+6) 으로 같이 증가, `correct_refusal` 은 8 → 4 (-4). 헤드라인 metric 만 보면 win 처럼 보이는 *silent regression*.
- **가설 후보**:
  - `___ retrieve loop 가 evidence threshold 를 낮춰서 unsupported 답을 강제 산출`
  - `___ verifier strict 단계 skip 으로 partial → supported 오판`
  - `___ answer generator 가 metadata-only evidence 로 답 합성 (citation 약화)`
- **검증 명령**: `___ / ___`
- **연결 anchors**: [`eval/run_eval.py`](../eval/run_eval.py) (`_abstention_outcomes` 분해, ADR 0030 SAFE_*) · ADR 0001 / ADR 0024 (baseline vs full) · #463 (분해 도입) · [`docs/answer-policy.md`](answer-policy.md)
- **Self-score**: `___ / 2` · 막힌 시점: `___`

<!-- variants:
- 같은 증상, 단 base 와 head 양쪽 모두 `correct_refusal` 감소 → 합성 표면 시그널 약화?
- `boundary_partial` 만 증가 → ADR 0004 retry policy 어느 단계 회귀?
-->

---

## Phase 2 Stub 시나리오 (4개)

> 1~2주에 1개씩 fully form. LLM 일괄 작성 금지.

### S5 — R1 IndexError: `retry_count>0` + `len(stage_attempts)<2` (실 사고)

- **증상 한 줄**: ___
- **가설 후보**: `___ / ___ / ___`
- **검증 명령**: `___ / ___`
- **연결 anchors**: `rag_core.py:___ (retrieve loop / retry_count 분기)` · `tests/test_retrieval_loop_regression.py:___`
- **Self-score**: `___ / 2`

### S6 — Evidence `chunk_id` leak: `claims[].chunk_id` 가 evidence list 밖 (ADR 0003 violation)

- **증상 한 줄**: ___
- **가설 후보**: `___ / ___ / ___`
- **검증 명령**: `___ / ___`
- **연결 anchors**: `rag_answer.py:___ (make_citation / claim_target)` · ADR 0003 · `rag_answer_schema.py:___`
- **Self-score**: `___ / 2`

### S7 — LLM judge co-regression: judge 와 verifier 가 같은 방향으로 흔들림 (ADR 0016)

- **증상 한 줄**: ___
- **가설 후보**: `___ / ___ / ___`
- **검증 명령**: `___ / ___`
- **연결 anchors**: `scripts/llm_judge.py:___` · ADR 0006 · ADR 0016 (judge-human agreement)
- **Self-score**: `___ / 2`

### S8 — Metadata ambiguity divergence: 공개 합성 통과, real-data 0.05 confidence delta 미통과 (C2)

- **증상 한 줄**: ___
- **가설 후보**: `___ / ___ / ___`
- **검증 명령**: `___ / ___`
- **연결 anchors**: `rag_query.py:___ (metadata_resolution_diagnostics)` · ADR 0002 (metadata-first) · `real-data-failure-taxonomy.md` C2 · #72
- **Self-score**: `___ / 2`

---

## Related

- [`adr-self-interview-checklist.md`](adr-self-interview-checklist.md) — ownership #1·#2 audit (자매 문서, 같은 inward 패턴)
- `llm-off-pr-guide.md` (sibling, ownership #4) — 별 PR 로 land 예정. 본 워크북은 그 가이드의 "CI fail 5분 룰" fallback 으로도 동작.
- [`real-data-failure-taxonomy.md`](real-data-failure-taxonomy.md) — C1~C6 + P0~P3, 본 워크북 시나리오 source
- [`docs/private-100-doc-experiments.md`](private-100-doc-experiments.md) Decision Log — 실 사고 source (#69 / #89 / R1 / R2)
- `tests/test_*_regression.py` 16개 — 각 시나리오의 anchor test
- `~/.claude/projects/-Users-hskim-Desktop-projects-BidMate-DocAgent/memory/debugging_scenario_log.md` — 사적 score log (회귀 측정)
