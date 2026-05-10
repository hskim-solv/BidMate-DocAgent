# Grounding and eval hardening

이 문서는 phase 1 grounding/eval hardening 변경을 리뷰어가 재현할 수 있도록 정리한다.

## What changed

- Public eval slice를 `single_doc`, `comparison`, `follow_up`, `abstention`으로 표준화했다. 기존 `multi_doc` config 값은 호환 alias로 계속 읽는다.
- 공개 eval에 claim-level citation spec과 partial comparison 케이스를 추가했다.
- `answer` 객체를 schema v2로 고정하고 `schema_version`, `status_reason`을 추가했다.
- `run_rag_query` 결과에 `trace`를 추가해 planner 선택과 query rewrite/context resolution을 한 곳에서 볼 수 있게 했다. 필드 정의와 해석 가이드는 [planner-trace.md](./planner-trace.md) 참고.
- `eval/run_eval.py`는 각 run/case의 trace를 `reports/traces/<run>/<case>.trace.json`에 쓴다. `reports/`는 gitignored라 private/local trace가 커밋되지 않는다. `--redact_trace` 플래그로 doc ID / entity 마스킹을 켤 수 있다.
- `claim_citation_alignment`과 `claim_citation_error_counts`를 추가해 whole-answer citation precision과 claim-level drift를 분리했다.

## Why it changed

기존 report는 전체 답변의 expected term/doc match를 잘 보여줬지만, 다음 질문에는 답하기 어려웠다.

- 비교 질문에서 어떤 target이 빠졌는가?
- follow-up query가 실제로 어떤 query로 rewrite 되었는가?
- `supported`, `partial`, `insufficient`가 같은 JSON 계약으로 안정적으로 나오는가?
- 답변 전체는 맞아 보여도 claim이 엉뚱한 chunk를 citation으로 달고 있지 않은가?

이번 변경은 retrieval/chunking 구조를 바꾸지 않고, reviewer가 위 질문을 report와 trace artifact에서 직접 확인하도록 만든다.

## How to validate

```bash
python3 scripts/build_index.py --input_dir data/raw --output_dir data/index
python3 app.py --input_dir data/index --output_dir outputs --query "기관 A와 기관 B의 AI 요구사항 차이 알려줘"
python3 eval/run_eval.py --index_dir data/index --output_dir reports --config eval/config.yaml
python3 scripts/update_readme_metrics.py --report reports/eval_summary.json --readme README.md --check
python3 -m pytest tests/test_eval_metrics.py tests/test_fuzzy_retrieval.py
make test-regression  # P0 retrieval-loop / answerable-smoke regression guards (#68)
```

Inspect these artifacts:

- `outputs/answer.json`: `answer.schema_version == 2`, `answer.status_reason`, `trace.planner`, `trace.query_rewrite`
- `reports/eval_summary.json`: `by_slice`, `claim_citation_alignment`, `claim_citation_error_counts`, `case_results[*].trace_path`
- `reports/traces/full/*.trace.json`: readable planner and rewrite traces for the stronger agentic run
- `reports/traces/naive_baseline/*.trace.json`: baseline control traces for comparison

## Interpreting failures

- Low `citation_precision`: whole-answer evidence doc/term quality is weak.
- Low `claim_citation_alignment`: at least one emitted claim is not directly supported by its cited chunk, even if the overall answer found the right document.
- `expected_claim_missing`: a target-specific claim required by eval was not emitted.
- `claim_text_not_supported_by_citation`: likely citation drift; inspect the case trace and the claim citation chunk.
- `answer_format_compliance` failure with `status_match`: the answer schema status did not match expected `supported`, `partial`, or `insufficient`.
- `trace.query_rewrite.rewritten == true`: follow-up context was used to rewrite the query. Check `rewrite_type`, `context_entities`, and `active_doc_ids`.

## Issue coverage

- #58: public eval has broader slice-aware reporting through `by_slice` plus expanded comparison/partial/claim cases.
- #60: local planner/rewrite traces are emitted in both `outputs/answer.json` and `reports/traces/`.
- #63: answer schema v2 explicitly represents `supported`, `partial`, and `insufficient` with machine-readable status reasons.
- #64: claim-level citation alignment is measured separately from whole-answer citation precision.

Out of scope remains chunking redesign (#62) and confidentiality/reporting flow (#65).
