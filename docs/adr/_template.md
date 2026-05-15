# NNNN: <decision title>

- **Status**: proposed | accepted | superseded by NNNN | deprecated
- **Date**: YYYY-MM-DD
- **Deciders**: <names or roles>
- **Related**: <issue / PR / doc links, optional>

## Context

What problem or constraint forced a decision? Keep this factual and
specific to this repo — link concrete files (`rag_core.py:L1843`) or
existing docs rather than re-explaining them. Three paragraphs max.

## Decision

The chosen approach, stated as one direct sentence followed by the
specifics needed to act on it. If the decision has a knob (threshold,
toggle, default), name it here so future readers know what to change
if they want to revisit.

## Consequences

What becomes easier, harder, or constrained because of this decision?
List both the wins and the costs. Include any contract this locks in
(e.g., a schema field other code relies on, a default that other ADRs
assume).

## Alternatives considered

Brief notes on the options that were not chosen and why. One or two
bullets each. The goal is to make the trade-off legible, not to
re-litigate it.

## Verification

How will the Consequences above stay honest 6 months from now? Make the
promise machine-checkable by adding one or more HTML-comment markers in
the format:

    <!-- verifies-key: <relative-path>:<key-substring> -->

`scripts/_governance.py --lint-adr-consequences docs/adr/NNNN-slug.md`
reads these markers, confirms `<relative-path>` exists, and looks for
`<key-substring>` inside it. The substring match is intentionally lenient
— the goal is "this ADR's commitment is wired into the measurement
surface," not "this exact JSON path resolves." Example marker (drop the
ones that do not apply, add as many as the Consequences imply):

<!-- verifies-key: reports/eval_summary.json:stage_attempts -->

The pre-commit hook (`.githooks/pre-commit`) refuses new ADRs that lack
this section or contain zero markers (issue #793). Existing ADRs are
grandfathered — retrofit happens per-ADR in follow-up PRs. The hook does
NOT fail on missing target files (e.g. `reports/eval_summary.json` may
not exist in a fresh clone); it only fails when the file exists and the
key substring is absent.
