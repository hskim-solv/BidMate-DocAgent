# Retrieval hardening milestone

이 문서는 이슈 #55, #56, #57, #59, #61에서 요구한 retrieval robustness 변경을 검토할 때 확인할 코드 경로와 진단 필드를 정리한다.

## What changed

- Metadata filter는 `strict`, `reduced`, `relaxed` 단계로 실행된다. 후보가 없는 `strict`는 더 이상 이름만 strict인 전체 검색으로 기록하지 않고 `relaxed`로 기록한다.
- Agency/project/title matching은 spacing/punctuation compact normalization, partial token overlap, fuzzy similarity, explicit alias lexicon을 함께 사용한다.
- 문서 metadata의 `aliases`, `agency_aliases`, `project_aliases`, `title_aliases`가 alias lexicon으로 읽힌다. Public synthetic docs에는 축약 project alias만 최소로 추가했다.
- Follow-up query는 session state의 active agency와 project를 retrieval query 앞에 주입한다. 세션 상태에는 active doc/project/agency 후보와 ambiguity flag가 남는다.
- Single/follow-up query에서 metadata 후보가 낮은 confidence 차이로 충돌하면 retrieval을 진행하지 않고 clarification 형태의 `insufficient` 응답을 반환한다. Comparison query는 여러 후보를 정상 target set으로 허용한다.
- Planner는 query type별 기본 retrieval budget을 사용한다. `single_doc=4`, `follow_up=6`, `comparison=6`이며 comparison은 coverage-aware top-k가 필요한 경우 기존 adaptive budget을 사용한다.

## Diagnostics to inspect

- `diagnostics.filter_stage_attempts[]`: stage, filters, candidate count, selected top_k, verifier reasons.
- `diagnostics.metadata_resolution`: normalized query/tokens, all metadata candidates, selected candidates by stage, selected doc ids, ambiguity decision.
- `diagnostics.context_resolution`: follow-up carryover source, reused agencies/projects/doc ids, confidence, clarification reason.
- `plan.retrieval_budget`: selected top_k, query type, reason, defaults.
- `reports/eval_summary.json.case_results[]`: `filter_stage`, `selected_top_k`, `metadata_ambiguous`, `ambiguity_decision`, `metadata_candidate_count`, `metadata_selected_doc_ids`.

## How to validate

```bash
python3 -m unittest tests.test_fuzzy_retrieval -v
python3 -m unittest tests.test_eval_metrics -v
python3 scripts/build_index.py --input_dir data/raw --output_dir data/index
python3 app.py --input_dir data/index --output_dir outputs --query "기관 A와 기관 B의 AI 요구사항 차이 알려줘" --pipeline agentic_full
python3 eval/run_eval.py --index_dir data/index --output_dir reports --config eval/config.yaml
python3 scripts/update_readme_metrics.py --report reports/eval_summary.json --readme README.md --check
```

## Issue coverage

- #55: staged metadata filters and per-stage diagnostics.
- #56: explicit alias lexicon plus fuzzy/partial candidate expansion.
- #57: persistent follow-up state and retrieval-query carryover.
- #59: ambiguity detection with clarification-before-retrieval behavior.
- #61: planner-owned query-type top_k selection and diagnostics.
