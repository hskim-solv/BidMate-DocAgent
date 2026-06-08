# T-2026-0076 real100_v2 Retrieval Collapse Diagnosis Plan

**Goal:** Produce an aggregate-only diagnosis artifact for the page-aware `real100_v2` retrieval collapse so downstream experiments do not optimize against a stale or incomparable baseline.

**Architecture:** Add a small reporting script that compares the current page-aware eval summary with the checked-in hashing backup using only aggregate metrics and safe run-manifest fields. Keep raw `case_results` private by emitting counts/rates only, plus a Markdown reviewer note and targeted regression tests.

**Files:**
- Create: `scripts/diagnose_real100_v2_retrieval_collapse.py` — aggregate-only comparison builder/renderer.
- Create: `tests/test_diagnose_real100_v2_retrieval_collapse.py` — privacy and metric regression tests.
- Create: `docs/plans/T-2026-0076-real100-v2-retrieval-collapse-diagnosis.md` — task plan/evidence.
- Create/update: `docs/evaluation/real100_v2-retrieval-collapse-diagnosis.md` — generated reviewer-facing Markdown.
- Create/update: `reports/real100_v2/retrieval_collapse_diagnosis.aggregate.json` — generated aggregate JSON.
- Modify: `tasks/queue.md` — record T-2026-0076 completion and issue #2751.

**Steps:**
1. Write failing test for aggregate-only output and doc-level/chunk-level metric deltas.
2. Run targeted test and confirm import/script failure.
3. Implement minimal reporting script.
4. Run targeted tests and generate JSON/Markdown artifacts.
5. Update queue with the diagnosis outcome.
6. Run real100_v2 guard, privacy/static checks, branch check, and commit/ship.

## Outcome

- Issue: #2751.
- Aggregate JSON: `reports/real100_v2/retrieval_collapse_diagnosis.aggregate.json`.
- Reviewer Markdown: `docs/evaluation/real100_v2-retrieval-collapse-diagnosis.md`.
- Verdict: `doc_ranking_collapse_not_chunk_id_only`; the current page-aware MiniLM run changed stack fields relative to the hashing backup and has materially lower doc/chunk hit rates, so the backup is not a comparable baseline for downstream optimization.
- Decision: keep page-aware chunking as an unresolved diagnostic input; do not tune reranker/window/context tasks until same-stack page-aware MiniLM retrieval provenance/remeasurement is available.

## Validation Target

```bash
python3 -m pytest tests/test_diagnose_real100_v2_retrieval_collapse.py tests/test_run_manifest_versioning_regression.py -q
python3 scripts/diagnose_real100_v2_retrieval_collapse.py
make real-eval-v2-guard
python3 scripts/agent_loop.py privacy-audit-output
python3 scripts/agent_loop.py claim-audit --from-git
git diff --check
make check-branch
```
