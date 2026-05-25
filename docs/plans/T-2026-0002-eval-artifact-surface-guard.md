# Plan: T-2026-0002 Eval Artifact Surface Guard

- Status: review
- Owner role: Implementer
- Related task: `tasks/queue.md::T-2026-0002`
- Related issue / PR: [#1480](https://github.com/hskim-solv/BidMate-DocAgent/issues/1480) / PR TBD
- Related ADR: [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md)
- Created: 2026-05-25
- Last updated: 2026-05-25

## Problem Statement

Multiple files named `eval_summary.json` exist across public fixture smoke,
public synthetic benchmark, private real-eval, and harness runs. The default
delta comparator did not identify the surface being compared, so incompatible
artifact comparisons could look legitimate.

## Desired Behavior

`scripts/compare_eval.py` renders best-effort surface labels for base/head
summaries and offers an opt-in fail-closed gate for mismatched known surfaces.
Unknown surfaces remain non-blocking but visible.

## Constraints

- Do not change metric calculation or regression thresholds.
- Do not require private raw data or make private real-eval a CI dependency.
- Keep existing PR fixture smoke workflow backward compatible.

## Architecture Impact

- Affected modules: eval delta comparator and focused CLI tests.
- Load-bearing paths: none directly, but this is eval governance tooling.
- ADR required: no, this enforces existing ADR 0005 surface separation.
- Backward compatibility: default compare remains non-blocking for unknown or matching surfaces.

## Validation Strategy

```bash
python3 -m pytest tests/test_compare_eval_regression_gate.py -q
python3 scripts/check_doc_links.py --check-all
python3 -m pytest tests/test_eval_artifact_privacy_regression.py -q
```

## Reviewer Notes

Attack claim boundary wording first: smoke, synthetic benchmark, private
real-eval, and harness summaries must not be silently treated as interchangeable.
