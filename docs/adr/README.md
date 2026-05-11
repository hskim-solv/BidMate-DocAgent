# Architecture Decision Records (ADR)

This directory holds the **load-bearing decisions** for BidMate-DocAgent
— the ones that, if reversed, would force significant rework or
invalidate published evaluation results.

## When to write an ADR

Write one when a change:

- Removes, replaces, or fundamentally alters a baseline / pipeline /
  evaluation contract that other parts of the system depend on.
- Picks between two viable approaches whose trade-off you will need to
  defend later (in review, in an interview, or to your future self).
- Establishes a new convention that future changes must follow.

Do **not** write one for routine code changes, bug fixes, refactors,
or doc edits. Those go straight into the PR description.

## File layout

```
docs/adr/
├── README.md           # this file
├── _template.md        # copy this when starting a new ADR
└── NNNN-slug.md        # one ADR per file
```

- `NNNN` is a 4-digit zero-padded sequence, e.g. `0001`, `0023`.
- Numbers are **never reused or renumbered**, even if an ADR is later
  superseded. Continuity matters more than tidiness.
- `slug` is short, kebab-case, and stable. Pick a name you will not
  want to rename later (e.g. `metadata-first-retrieval`, not
  `retrieval-changes-v2`).

## Status lifecycle

| status | meaning |
|---|---|
| `proposed` | Decision drafted but not yet implemented or merged. Open for change. |
| `accepted` | Reflected in code / docs / tests. Treated as the current convention. |
| `superseded by NNNN` | Replaced by a later ADR. The old file stays; the new one links back. |
| `deprecated` | No longer applies but no replacement exists. Rare. |

Always update the status header when status changes. Do not delete
old ADRs even when superseded — their existence is part of the
project record.

## Authoring conventions

- Keep each ADR short. One screen is the target. If you need more
  room, the decision probably needs to be split or the context
  belongs in a regular design doc.
- Use the section headings from [`_template.md`](./_template.md):
  **Context**, **Decision**, **Consequences**, **Alternatives
  considered**.
- Reference concrete code paths (`rag_core.py:L1843`) and existing
  docs rather than restating their content.
- Cross-link from any prose doc that previously held the rationale,
  so the ADR becomes the canonical source.

## Index

| # | Status | Title |
|---|---|---|
| [0001](./0001-preserve-naive-baseline.md) | accepted | Preserve a naive baseline alongside the agentic pipeline |
| [0002](./0002-metadata-first-retrieval.md) | accepted | Metadata-first retrieval strategy |
| [0003](./0003-structured-answer-citation-contract.md) | accepted | Structured answer / citation contract (`schema_version: 2`) |
| [0004](./0004-verifier-retry-policy.md) | accepted | Verifier-driven retry with strict → relaxed staging |
| [0005](./0005-eval-split-public-synthetic-private-local.md) | accepted | Eval split: public synthetic vs private local |
| [0006](./0006-llm-judge-on-real-data-only.md) | accepted | LLM-judge on the real-data surface only (refines 0004) |
| [0007](./0007-issue-linked-branch-naming.md) | accepted | Issue-linked branch naming convention |
| [0008](./0008-evidence-boundary.md) | accepted | Evidence-boundary defense against prompt injection |
| [0009](./0009-external-baseline-comparison.md) | proposed | External baseline comparison via a separate script (extends 0001) |
| [0010](./0010-hybrid-bm25-dense-retrieval-rrf.md) | accepted | Hybrid BM25 + dense retrieval with RRF fusion |
| [0011](./0011-llm-synthesis-as-additive-ablation.md) | proposed | LLM answer synthesis as additive ablation (extends 0001, preserves 0003) |
| [0012](./0012-llm-judge-on-public-synthetic.md) | accepted | LLM-judge on the public synthetic eval, stub-default (refines 0006, reuses 0011 backend pattern) |
