<!--
Per CLAUDE.md and docs/engineering-governance.md. Answer each section in order.
If a section truly doesn't apply, write "N/A" with a one-line reason — don't delete it.
-->

## 1. What changed and why

<!--
One paragraph. The `Closes #N` below is **required** (ADR 0007) and
must match the issue number in your branch name (e.g. branch
`feat/issue-79-foo` → `Closes #79`). The Branch & Issue Convention CI
check will block merge if missing or mismatched.
-->

Closes #

## 2. Files affected

<!--
Bulleted list. Flag any of these as load-bearing
(canonical list: scripts/_governance.py):
rag_core.py, rag_retrieval.py, rag_verifier.py, rag_answer.py, ingestion.py, visual_ingestion.py, eval/, api/, docs/adr/, scripts/build_index.py
-->

## 3. Risks

<!-- What is the most likely way this breaks? What specifically did you check to rule that out? -->

## 4. Tests

<!--
Which tests exercise the new behavior? Behavior changes must add at least one test
that fails before the change and passes after.
Regression tests for shipped bugs go in tests/test_*_regression.py
(pattern: tests/test_retrieval_loop_regression.py).
If no tests added, justify.
-->

## 5. Eval impact

<!--
What do you expect the CI eval delta to show?
"All `·`" is a valid answer for non-RAG changes — say so explicitly.
-->

### 5b. Real-data delta

<!--
Required if any load-bearing path changed
(rag_core.py, rag_retrieval.py, rag_verifier.py, rag_answer.py, ingestion.py, visual_ingestion.py, eval/, api/, docs/adr/, scripts/build_index.py).
Attach the `make real-eval-delta` aggregate table, or state explicitly:
"No behavior change in retrieval / verifier path."
See ADR 0005 and docs/private-100-doc-experiments.md.
The synthetic CI delta alone missed #69's intended-abstention regression;
the §5b CI gate (scripts/check_branch_and_issue.py --check-5b) now enforces this.
-->

## 6. Backward compatibility

<!--
Anything that breaks an existing contract, schema, CLI flag, or doc link?
Answer-contract change (ADR 0003) requires `schema_version` bump.
If yes, what's the migration?
-->

## 7. Out of scope

<!-- Anything you noticed and deliberately did not fix. -->
