# 근거 연결(Grounding) 및 eval 강화(hardening)

이 문서는 phase 1 grounding/eval hardening 변경을 리뷰어가 재현할 수 있도록 정리한다.

## 무엇이 바뀌었나

- Public eval slice를 `single_doc`, `comparison`, `follow_up`, `abstention`으로 표준화했다. 기존 `multi_doc` config 값은 호환 alias로 계속 읽는다.
- 공개 eval에 claim-level citation spec과 partial comparison 케이스를 추가했다.
- `answer` 객체를 schema v2로 고정하고 `schema_version`, `status_reason`을 추가했다.
- `run_rag_query` 결과에 `trace`를 추가해 planner 선택과 query rewrite/context resolution을 한 곳에서 볼 수 있게 했다. 필드 정의와 해석 가이드는 [planner-trace.md](../agentic/planner-trace.md) 참고.
- `eval/run_eval.py`는 각 run/case의 trace를 `reports/traces/<run>/<case>.trace.json`에 쓴다. `reports/`는 gitignored라 private/local trace가 커밋되지 않는다. `--redact_trace` 플래그로 doc ID / entity 마스킹을 켤 수 있다.
- `claim_citation_alignment`과 `claim_citation_error_counts`를 추가해 whole-answer citation precision과 claim-level drift를 분리했다.

## 왜 바뀌었나

기존 report는 전체 답변의 expected term/doc match를 잘 보여줬지만, 다음 질문에는 답하기 어려웠다.

- 비교 질문에서 어떤 target이 빠졌는가?
- follow-up query가 실제로 어떤 query로 rewrite 되었는가?
- `supported`, `partial`, `insufficient`가 같은 JSON 계약으로 안정적으로 나오는가?
- 답변 전체는 맞아 보여도 claim이 엉뚱한 chunk를 citation으로 달고 있지 않은가?

이번 변경은 retrieval/chunking 구조를 바꾸지 않고, reviewer가 위 질문을 report와 trace artifact에서 직접 확인하도록 만든다.

## 검증 방법

```bash
python3 scripts/build_index.py --input_dir eval/fixtures/smoke_rfp/raw --output_dir data/index
python3 app.py --input_dir data/index --output_dir outputs --query "기관 A와 기관 B의 AI 요구사항 차이 알려줘"
python3 eval/run_eval.py --index_dir data/index --output_dir reports --config eval/config.yaml
python3 scripts/update_readme_metrics.py --report reports/eval_summary.json --readme README.md --check
python3 -m pytest tests/test_eval_metrics.py tests/test_fuzzy_retrieval.py
make test-regression  # P0 retrieval-loop / answerable-smoke regression guards (#68)
```

다음 산출물을 점검하라:

- `outputs/answer.json`: `answer.schema_version == 2`, `answer.status_reason`, `trace.planner`, `trace.query_rewrite`
- `reports/eval_summary.json`: `by_slice`, `claim_citation_alignment`, `claim_citation_error_counts`, `case_results[*].trace_path`
- `reports/traces/full/*.trace.json`: 더 강한 agentic run 의 가독성 있는 planner 및 rewrite trace
- `reports/traces/naive_baseline/*.trace.json`: 비교용 baseline 대조군 trace

## 실패 해석

- 낮은 `citation_precision`: 전체 답변의 근거(evidence) 문서/용어 품질이 약함.
- 낮은 `claim_citation_alignment`: 전체 답변이 올바른 문서를 찾았더라도, 방출된 claim 중 적어도 하나가 인용된 chunk 로 직접 뒷받침되지 않음.
- `expected_claim_missing`: eval 이 요구한 target 특정 claim 이 방출되지 않음.
- `claim_text_not_supported_by_citation`: citation drift 가능성; 케이스 trace 와 claim citation chunk 를 점검하라.
- `status_match` 와 함께 나타나는 `answer_format_compliance` 실패: 답변 스키마 상태가 기대한 `supported`, `partial`, `insufficient` 와 일치하지 않음.
- `trace.query_rewrite.rewritten == true`: follow-up 컨텍스트가 쿼리 rewrite 에 사용됨. `rewrite_type`, `context_entities`, `active_doc_ids` 를 확인하라.

## Issue 커버리지

- #58: public eval 이 `by_slice` 와 확장된 comparison/partial/claim 케이스를 통해 더 넓은 slice-aware 리포팅을 갖는다.
- #60: 로컬 planner/rewrite trace 가 `outputs/answer.json` 과 `reports/traces/` 양쪽에 방출된다.
- #63: answer 스키마 v2 가 `supported`, `partial`, `insufficient` 를 기계 판독 가능한 status reason 과 함께 명시적으로 표현한다.
- #64: claim 단위 citation alignment 가 전체 답변 citation precision 과 별도로 측정된다.
- #69: relaxed (last-attempt) verifier 단계의 partial-topic grounding — 아래 참고.

범위 밖으로 남는 것은 chunking 재설계(#62)와 기밀성/리포팅 흐름(#65)이다.

## Partial-topic 근거 연결(grounding) (issue #69)

`docs/real-data/real-data-failure-taxonomy.md` C6 는 실제 corpora 에서 남은
영향력 최고의 실패로 false abstention 을 지목했다: 12 개 real100
누락 중 9 개가 `retry_trigger_reason: topic_not_grounded × 2` 로 끝났다 —
strict 와 relaxed 단계 모두 동일하게 약하지만 사용 가능한 근거를 거부했는데,
verifier 가 **모든** verification topic 이 결합된 근거 텍스트에 나타나도록
요구했기 때문이다. 의도된 abstention 케이스
(P-13~15)는 이미 강건했다; 실패는 under-strict 검색이 아니라
over-strict 검증이었다.

### 무엇이 바뀌었나

- `verify_evidence(..., allow_partial_topic=False)` 에 명시적 플래그가
  생겼다. 검색 루프는 strict 단계가 현재 기준을 유지하도록 **마지막
  예정 시도에서만** 이를 `True` 로 설정한다.
- 마지막 시도에서, 적어도 하나의 topic 과 모든 verification topic 의 적어도
  `PARTIAL_TOPIC_GROUNDING_MIN_FRACTION` (현재 `0.5`) 이
  근거에 나타나면, verifier 는
  non-blocking `partial_topic_grounding` reason 과 함께 `verified=True` 를 반환한다.
- `answer_status` 는 그 reason 을 `ANSWER_STATUS_PARTIAL` (`supported`
  아님) 로 매핑하고, `answer_status_reason` 은
  `code: partial_topic_grounding` 을 방출하므로 partial 경로가
  기존 `partial_comparison` 경로와 구분된다. 둘 다
  [`answer-policy.md`](../agentic/answer-policy.md) 에 문서화돼 있다.
- 다른 모든 바닥값(floor)은 strict 를 유지한다: `low_top_score`, comparison entity /
  doc coverage, per-entity comparison topic 체크는 여전히
  blocking 이다. Partial-topic grounding 이
  hallucination floor 를 무료 통과시켜주지는 않는다.

### Trade-off

이는 [ADR 0004](../adr/0004-verifier-retry-policy.md) 에서 예견한
strict-vs-relaxed 노브(knob)다. trade-off 는
명시적이다:

- **얻은 것**: 유의미한 비율의 false-abstention 쿼리가
  `insufficient` 대신 `partial` 로 회복된다. public fixture smoke eval 에서는
  새 `partial_topic_security_quantum` 케이스가 in-tree
  가드로 함께 머지된다; real-data 영향은 C6 backlog (9 케이스)에서 기대된다.
- **비용**: `citation_precision` 이 약간 떨어질 수 있는데, partial
  답변이 요청된 topic 중 일부만 근거 짓는 chunk 에 대한
  citation 을 포함할 수 있기 때문이다. 상태 자체(`partial`)가
  답변이 완전히 근거 지어지지 않았음을 호출자에게 알리는
  계약이다.

### 로컬 검증 방법

```bash
python3 scripts/build_index.py --input_dir eval/fixtures/smoke_rfp/raw --output_dir data/index --embedding_backend hashing
python3 eval/run_eval.py --index_dir data/index --output_dir reports --config eval/config.yaml
python3 -m pytest tests/test_partial_topic_grounding.py -v
```

`answer_status == "partial"` 이고 `verification_reasons` 에
`partial_topic_grounding` 을 포함하는
`case_results[*].id == "partial_topic_security_quantum"` 를 찾아라. 동일한 eval 은
unanswerable slice 에서
`abstention` (의도된 abstention) 지표를 변하지 않게 유지해야 한다.
