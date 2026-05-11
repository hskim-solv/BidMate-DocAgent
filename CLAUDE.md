# CLAUDE.md

This repository is an RFP-focused DocAgent system.

Core product flow:
ingestion -> metadata normalization -> chunking -> retrieval -> reranking/planning -> evidence aggregation -> grounded answer -> verification -> evaluation -> reviewer-facing docs

This file is the **enforceable** governance layer for AI-assisted work
on this repo. The rules below are not aspirational — every change is
expected to satisfy them or to call out, in the PR, exactly which rule
is being waived and why.

For the broader workflow that ties this file together with ADRs,
tests, eval, and reviewer artifacts, see
[`docs/engineering-governance.md`](docs/engineering-governance.md).

---

## Product rules

- Treat this as a Bid/RFP document intelligence system, not a generic
  AI playground.
- Preserve a naive baseline before adding advanced retrieval methods.
  See [ADR 0001](docs/adr/0001-preserve-naive-baseline.md).
- Prefer metadata-aware retrieval where appropriate.
  See [ADR 0002](docs/adr/0002-metadata-first-retrieval.md).
- Keep answers grounded in retrieved evidence.
  The grounded answer / citation contract is fixed by
  [ADR 0003](docs/adr/0003-structured-answer-citation-contract.md);
  every behavior change that touches answers must respect it.
- Favor reproducible evaluation and reviewer-friendly artifacts.
  Public vs private eval split is fixed by
  [ADR 0005](docs/adr/0005-eval-split-public-synthetic-private-local.md).

## Change rules

- **Before coding**, inspect the current implementation and explain
  what already exists. Search for reusable functions / utilities
  before proposing new code. Most changes should reuse, not invent.
- **When changing code**, name in the PR: files affected, risks,
  verification steps. "It works on my machine" is not a verification
  step.
- **Add or update tests when behavior changes.** Behavior changes
  without test changes are presumed accidental; if intentional,
  justify in the PR.
- **Keep backward compatibility** unless there is a strong, stated
  reason not to. Breaking the answer contract (ADR 0003) is the
  highest-cost break and requires bumping `schema_version`.
- **Avoid unrelated abstractions and broad rewrites.** One PR, one
  concern. If you find a worthwhile fix outside the current scope,
  open an issue instead of expanding the diff.
- **ADR threshold.** Open an ADR when a change removes or replaces a
  load-bearing decision (baseline / pipeline / answer contract /
  eval surface). See [`docs/adr/README.md`](docs/adr/README.md).

## Pre-PR review checklist

Every PR description must answer these, in order:

1. **What changed and why.** One paragraph. Link the issue.
2. **Files affected.** A bulleted list; flag anything in
   `rag_core.py`, `eval/`, `api/`, or `docs/adr/` as load-bearing.
3. **Risks.** What is the most likely way this breaks? What
   specifically did you check to rule that out?
4. **Tests.** Which tests exercise the new behavior? If none, why is
   that acceptable?
5. **Eval impact.** What do you expect the CI eval delta to show?
   ("All `·`" is a valid answer for non-RAG changes — say so.)
   - **5b. Real-data delta.** If `rag_core.py`, `ingestion.py`,
     `visual_ingestion.py`, `eval/`, or `api/` changed, attach the
     `make real-eval-delta` aggregate table (or explicitly state
     "no behavior change in retrieval / verifier path"). The
     synthetic CI delta alone missed #69's intended-abstention
     regression — see ADR 0005 and
     [`docs/private-100-doc-experiments.md`](docs/private-100-doc-experiments.md).
6. **Backward compatibility.** Anything that breaks an existing
   contract, schema, CLI flag, or doc link? If yes, what's the
   migration?
7. **Out of scope.** Anything you noticed and deliberately did not
   fix.

## Testing rules

- `bash scripts/test.sh` (i.e. `pytest -q`) must pass locally before
  push. CI runs the same command and is the gate.
- Behavior changes in retrieval, verification, answer assembly, or
  citation grounding **must** add at least one test that fails before
  the change and passes after.
- Regression tests for shipped bugs go in `tests/test_*_regression.py`
  with a docstring linking the originating issue or taxonomy entry.
  See `tests/test_retrieval_loop_regression.py` for the pattern.
- Heavy-dep tests (visual ingestion, sentence-transformers) are fine
  but must use the hashing embedding backend wherever the test is
  about retrieval / verifier logic rather than the embedding itself.

## Local hook setup (one-time, per developer)

Activate the opt-in pre-push reminder hook:

```bash
git config core.hooksPath .githooks
```

The hook prints a warning if a push touches retrieval / verifier /
eval / api paths without (currently a soft signal — see CLAUDE.md
pre-PR checklist 5b). Skip with `git push --no-verify` only with a
documented reason. The hook is non-fatal; it never blocks a push.

## Reproducibility & performance expectations

- Public synthetic eval must runnable on every PR via the eval delta
  workflow without network access or paid APIs. Anything that breaks
  that constraint is a stop-the-line bug.
- The CLI `make smoke` flow stays under a few minutes on a developer
  laptop using `EMBEDDING_BACKEND=hashing`. Significant new latency
  in that path needs justification in the PR.
- API demo (`api/main.py`, `docker-entrypoint.sh`) must remain
  one-command startable. Don't add required setup steps without
  updating [`docs/api-demo.md`](docs/api-demo.md).
- Latency numbers reported in PR descriptions should come from the
  `stage_latency` block in `reports/eval_summary.json`, not ad-hoc
  measurement.

## Prohibited shortcuts

- Do **not** remove the naive baseline or its eval ablation. See
  ADR 0001.
- Do **not** delete or rename ADRs even when superseded. Mark
  status; keep the file.
- Do **not** skip pre-commit hooks (`--no-verify`,
  `--no-gpg-sign`) without explicit user approval.
- Do **not** commit anything from `data/files/`, `data/data_list.csv`,
  `eval/*.local.yaml`, or `reports/real*/`. These are the private
  side of the eval split (ADR 0005) and stay out of git.
- Do **not** introduce a parallel pydantic / TypedDict model that
  shadows the `run_rag_query` answer dict. The dict is the contract.
- Do **not** broaden a PR mid-review by adding unrelated commits.
  Open a follow-up.
