# T-EXAMPLE-002 — Eval regression safety surface separation

- Status: example
- Owner role: Reviewer
- Related issue: example only
- Related PR: example only
- Related plan: TBD
- Created: 2026-05-25
- Last updated: 2026-05-25

## Goal

Ensure future PRs do not use public fixture smoke, public synthetic benchmark,
and private real-eval artifacts interchangeably when claiming regression safety.

## Context

This repo has several files named `eval_summary.json` across smoke, harness,
benchmark, and private real-eval flows. The safe interpretation rules are in
[`docs/evaluation/surface-map.md`](../../docs/evaluation/surface-map.md).

## Scope

- Confirm docs and PR template tell agents which artifact they are reading.
- Confirm private raw artifacts remain local-only.
- Add doc/test guard only if a concrete ambiguity exists.

## Non-Goals

- No scoring changes.
- No private data inspection.
- No new CI dependency on private real-eval.

## Acceptance Criteria

- [ ] Smoke result is described as regression/wiring only.
- [ ] Synthetic result is described as controlled benchmark only.
- [ ] Private result is aggregate-only and marked private/non-public.
- [ ] Incompatible `eval_summary.json` comparisons are called out.

## Validation Commands

```bash
python3 scripts/check_doc_links.py --check-all
python3 -m pytest tests/test_eval_artifact_privacy_regression.py -q
```

## Evidence Required

- Doc link check output.
- Focused pytest output.
- Reviewer note confirming no unsupported performance claim.

## Failure Conditions

- Stop if raw private questions, answers, evidence, doc IDs, chunk IDs, or exact
  local paths would be needed.
- Stop if metric semantics are being changed; create a new plan and benchmark audit.
