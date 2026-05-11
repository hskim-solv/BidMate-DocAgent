---
name: Bug report
about: Something in the pipeline produced the wrong answer, failed, or regressed.
title: "[bug] "
labels: bug
---

<!--
Per ADR 0007, every PR must be linked to an issue. Open this first;
your branch will be `fix/issue-<N>-<slug>` once this issue is filed.
-->

## What happened

<!-- The shortest concrete reproduction. Include the query, the expected
answer, and the observed answer (or stack trace). -->

## Expected behavior

<!-- What the answer / log / output should have been, and which doc /
ADR / test makes that the expected baseline. -->

## Suggested next step

<!-- One sentence: where you'd start looking. Filename + line if you
can. Useful even if you don't intend to take the fix yourself. -->

## Surface

<!-- Tick one. Most bugs live in exactly one. -->

- [ ] Ingestion (`ingestion.py`, `visual_ingestion.py`)
- [ ] Retrieval / verifier / answer (`rag_core.py`)
- [ ] Eval / metrics (`eval/`)
- [ ] API demo (`api/`)
- [ ] Docs / governance
- [ ] Other:
