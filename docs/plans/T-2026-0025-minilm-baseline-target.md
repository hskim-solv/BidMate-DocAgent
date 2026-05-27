# Plan: T-2026-0025 MiniLM Baseline Target

- Status: review
- Owner role: Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0025`
- Related issue / PR: [#1575](https://github.com/hskim-solv/BidMate-DocAgent/issues/1575) / [#1579](https://github.com/hskim-solv/BidMate-DocAgent/pull/1579)

## Problem

The private real-eval surface used ambiguous naming: `DEFAULT_EMBEDDING_MODEL`
is MiniLM, but `make real-eval` forces `EMBEDDING_BACKEND=hashing`, so the
actual index records `embedding.backend=hashing` and
`embedding.model=local-hashing-bow`. Operators could reasonably mistake that
hashing run for a MiniLM semantic baseline.

## Desired Outcome

Make the three baseline surfaces explicit:

- `make real-eval`: hashing/offline workflow-validation surface.
- `make real-eval-minilm`: MiniLM sentence-transformers private baseline.
- `make real-eval-semantic`: BGE-M3 semantic comparison surface.

## Scope

- Add a named MiniLM target with isolated local index/output/report paths.
- Update docs so backend/model selection is explicit.
- Add focused tests that lock the Makefile target and script comment wording.
- Keep aggregate run-manifest provenance explicit for embedding backend/model.

## Out Of Scope

- Do not run MiniLM or BGE-M3 private eval.
- Do not update aggregate baselines or performance reports.
- Do not expose private paths or raw private artifacts in aggregate reports.
- Do not claim any quality, recall, latency, or production improvement.
- Do not change retrieval, reranking, verifier, prompt, answer, or eval scoring.

## Validation

```bash
bash -n scripts/smoke_real.sh
python3 -m pytest -q tests/test_smoke_real_script.py tests/test_provenance_banner.py
python3 -m pytest -q tests/test_run_real_eval_delta.py -k run_manifest
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0025-minilm-baseline-target.md docs/evaluation/private_real_eval_workflow.md docs/private-real-eval-inventory.md docs/evaluation/surface-map.md
git diff --check
make check-branch
```

## Evidence

- `make real-eval-minilm` sets `EMBEDDING_BACKEND=sentence-transformers`,
  `MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, and
  separate `real100_minilm` local paths.
- Private workflow docs state that `make real-eval` is hashing/offline and not a
  MiniLM semantic run.
- Aggregate `run_manifest` extraction keeps `embedding_backend`,
  `embedding_model_id`, and `embedding_dim` while still dropping `config_path`
  and redacting local embedding model paths.

## Reviewer Focus

- Confirm target naming matches actual backend/model behavior.
- Confirm no performance claim is made.
- Confirm no private raw artifact or path is committed.

## Session Handoff

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: `eval/issue-1575-minilm-baseline-target` / Codex worktree
- Current status: implementation validated; PR still needed.
- Files touched: `Makefile`, `scripts/smoke_real.sh`,
  `scripts/run_real_eval_delta.py`,
  `docs/evaluation/private_real_eval_workflow.md`,
  `docs/evaluation/surface-map.md`, `docs/private-real-eval-inventory.md`,
  `tests/test_smoke_real_script.py`, `tests/test_run_real_eval_delta.py`,
  `docs/plans/T-2026-0025-minilm-baseline-target.md`, `tasks/queue.md`.
- Commands run: `bash -n scripts/smoke_real.sh`; `python3 -m pytest -q tests/test_smoke_real_script.py tests/test_provenance_banner.py`; `python3 -m pytest -q tests/test_run_real_eval_delta.py -k run_manifest`; `python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0025-minilm-baseline-target.md docs/evaluation/private_real_eval_workflow.md docs/private-real-eval-inventory.md docs/evaluation/surface-map.md`; `git diff --check`; `make check-branch`.
- Results: named MiniLM target added; docs now separate hashing, MiniLM, and
  BGE-M3 surfaces; aggregate run-manifest extraction preserves embedding
  provenance without private path leakage, including local model paths.
- Blockers: none known.
- Open risks: MiniLM target existence does not prove model availability or
  performance; actual private eval remains a separate local run.
- Next action: push and mark PR ready.
- Next safe command: `git status --short`
- Reviewer focus: baseline wording, no performance claim, and actual
  backend/model naming.
- Eval surface: workflow/docs only; no retrieval or eval runtime behavior change
  except new opt-in target.
