# AI Review Checklists

이 문서는 AI-agent가 만든 변경을 검토할 때 사용하는 reviewer checklist다.
목표는 단순 test pass가 아니라 architecture drift, benchmark contamination,
unverifiable claim, regression risk를 잡는 것이다.

## Normal Code Review

- Scope가 task/plan의 goal과 acceptance criteria에 묶여 있는가?
- unrelated refactor, formatting churn, drive-by cleanup이 섞이지 않았는가?
- 기존 helper/API/ADR contract를 재사용했는가?
- dead code, unused config, orphaned docs가 생기지 않았는가?
- duplicated logic이 기존 module과 분기하지 않는가?
- behavior change에 regression test 또는 focused validation이 있는가?
- answer dict schema, `naive_baseline`, eval split 등 invariant가 조용히 바뀌지 않았는가?
- validation command가 실제 실행됐고 결과가 보고됐는가?

## Adversarial Review

AI-agent failure mode를 일부러 찾는다.

- 테스트가 통과하지만 실제 path가 실행되지 않는 superficial test pass인가?
- abstraction이 문제를 줄이지 않고 이름만 늘렸는가?
- "future-proof" code가 현재 요구보다 넓은 surface를 여는가?
- hidden coupling이 생겨 다른 preset/API/eval runner가 같은 값을 다르게 해석하는가?
- fallback이 silent degrade를 만들지 않는가?
- error handling이 실패를 숨기고 metric을 좋게 보이게 하지 않는가?
- PR 설명의 claim이 diff와 validation evidence보다 강하지 않은가?
- generated artifact가 source-of-truth처럼 쓰이는가?

## Benchmark Validity Audit

다음 중 하나라도 있으면 이 checklist를 사용한다: `eval/`, `benchmarks/`,
`harness/`, `configs/eval/`, `reports/real100_v2/` (current private eval),
historical `reports/real100/`, `docs/evaluation/`, metric claim.

- Surface가 public fixture smoke, public synthetic benchmark, private real-eval 중 어디인지 명시됐는가?
- Dataset/config/index/provenance/command가 함께 제시됐는가?
- Synthetic benchmark 결과를 real-world performance claim으로 쓰지 않았는가?
- Smoke test가 wiring/regression 이상의 의미로 해석되지 않았는가?
- Private result는 current `real100_v2` aggregate-only evidence이고 raw question/answer/evidence/doc id/chunk id를 노출하지 않는가?
- Legacy `reports/real100/`, v1, 221-case, or kordoc artifacts를 새 task/PR/claim 근거로 재사용하지 않았는가?
- Metric denominator, skipped cases, `None` semantics, confidence interval이 claim wording과 맞는가?
- Baseline과 treatment가 같은 corpus/index/config 조건에서 비교됐는가?
- `make real-eval` hashing 경로로 semantic dense/hybrid retrieval claim을 만들지 않았는가?
- 개선 metric과 guardrail metric이 함께 보고됐는가?
- Benchmark contamination 가능성: index build가 questions/gold/expected answer를 읽지 않는가?

## Regression Review

- 이 변경이 과거 incident를 다시 열 수 있는가? 특히 #69 intended-abstention regression,
  ADR 번호 collision, doc dead link, private artifact leak, baseline provenance drift.
- 기존 regression test가 이 변경의 위험을 실제로 커버하는가?
- Public fixture smoke로 잡히지 않는 private real-eval risk가 있는가?
- Failure category count, abstention, citation precision, latency 같은 guardrail이 악화될 수 있는가?
- Slow test 또는 real-model test가 필요한데 생략됐는가?
- Rollback path가 명확한가?

## Documentation / Governance Review

- 새 문서가 기존 source of truth를 대체한다고 암시하지 않는가?
- `CLAUDE.md`, `AGENTS.md`, `docs/engineering-governance.md`, ADR, README 사이에 drift가 생기지 않았는가?
- multi-session 또는 parallel worktree PR이면 [`overlap-preflight`](../operations/ai-codex-workflow.md#overlap-preflight) 결과와 evidence path가 남아 있고 `clear/warn/blocked` 해석이 PR scope와 맞는가?
- Links가 상대 경로 기준으로 유효한가? `make check-doc-links` 또는 `python scripts/check_doc_links.py --check-all`를 실행했는가?
- 새 eval/benchmark 문서가 [`docs/evaluation/surface-map.md`](../evaluation/surface-map.md)의 claim boundary를 따르는가?
- 새 plan/task/review 문서가 실제로 다음 agent가 실행 가능한 수준인가?
- "N/A"가 필요한 곳에 사유가 있고, 사유가 검증 가능한가?

## Review Output Format

리뷰 결과는 findings를 먼저 쓴다.

```markdown
## Findings

- [blocking] <file/path>:<line> — 문제와 영향. 필요한 수정.
- [non-blocking] <file/path>:<line> — follow-up 권고.

## Evidence Checked

- Task:
- Plan:
- Commands:
- Eval surface:

## Verdict

Approve / Needs changes / Needs benchmark audit / Needs deep review
```
