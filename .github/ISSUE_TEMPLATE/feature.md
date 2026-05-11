---
name: Feature / enhancement
about: A new capability or improvement to an existing one.
title: "[feat] "
labels: enhancement
---

<!--
Per ADR 0007, every PR must be linked to an issue. Open this first;
your branch will be `feat/issue-<N>-<slug>` once this issue is filed.
-->

## Motivation

<!-- What user-visible / reviewer-visible problem does this solve?
Link to a failure taxonomy entry, ADR, or prior PR if applicable. -->

## Proposed scope

<!-- Bulleted list of the smallest change that delivers the motivation.
"One PR, one concern" — if this needs more than ~3 bullets,
consider splitting into multiple issues. -->

## Out of scope

<!-- What this issue is deliberately NOT going to touch. Helps the
implementer resist "while I'm here" scope creep (CLAUDE.md). -->

## Acceptance signal

<!-- How the reviewer will know it's done. A metric, a test name, a
demo command, or an artifact. If it's RAG-related, name the eval
metric you'd expect to move (or "No behavior change in retrieval /
verifier path" for governance-only work). -->

## Surface

<!-- Tick all that apply, but the implementer's PR will declare a
single PR concern. -->

- [ ] Ingestion (`ingestion.py`, `visual_ingestion.py`)
- [ ] Retrieval / verifier / answer (`rag_core.py`)
- [ ] Eval / metrics (`eval/`)
- [ ] API demo (`api/`)
- [ ] Docs / governance
- [ ] Other:
