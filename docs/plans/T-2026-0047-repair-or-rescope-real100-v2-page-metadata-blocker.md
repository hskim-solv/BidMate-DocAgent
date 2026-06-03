# Plan: T-2026-0047 repair or rescope real100_v2 page metadata blocker

- Status: done
- Owner role: Evaluator -> Implementer -> Benchmark Auditor -> Privacy Auditor -> Reviewer
- Related task: `tasks/queue.md::T-2026-0047`
- Related issue / PR: [#1645](https://github.com/hskim-solv/BidMate-DocAgent/issues/1645) / [#1648](https://github.com/hskim-solv/BidMate-DocAgent/pull/1648); refresh issue [#2131](https://github.com/hskim-solv/BidMate-DocAgent/issues/2131)
- Related ADR: [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md), [ADR 0003](../adr/0003-structured-answer-citation-contract.md)
- Created: 2026-05-28
- Last updated: 2026-06-04

## Problem Statement

`real100_v2` page/window experiments are blocked because the current private v2
index has no chunk-level page metadata. Without an aggregate readiness packet,
future work can accidentally claim page-aware citation improvements from an
index that cannot support those claims.

## Current Behavior

- `reports/real100_v2/retrieval_diagnostics.aggregate.json` records page-span
  coverage `0.0` and marks page/window claims blocked.
- `scripts/page_metadata_recovery_audit.py` can audit an index without reading
  retrieval predictions or emitting raw private content.
- The canonical private index is external to the tracked tree at
  `data/index/real100_v2` under the private root.

## Desired Behavior

Commit an aggregate-only `real100_v2` index readiness packet that either clears
the blocker or explicitly keeps private optimization claims no-go with the next
repair path. The readiness gate must fail closed for hashing-backed indexes and
indexes with 0.0 chunk page metadata coverage.

## Constraints

- Scope constraints: readiness/audit packet and guard only; no retrieval ranking
  change.
- Architecture constraints: retrieval, verifier, prompt, and answer behavior
  remain unchanged.
- Compatibility constraints: additive report and CLI output flags only.
- Eval/privacy constraints: `real100_v2` only; no legacy `real100`/v1/221/kordoc
  index evidence; no raw text, filenames, local paths, `doc_id`, or `chunk_id`.
- Tooling/CI constraints: private index stays ignored; committed output is
  aggregate-only.
- Non-goals: parser rewrite, index rebuild, default behavior change.

## Architecture Impact

- Affected modules or docs: `scripts/page_metadata_recovery_audit.py`,
  `tests/test_page_metadata_recovery_audit.py`, `reports/real100_v2/`,
  `docs/evaluation/`, `tasks/queue.md`.
- Affected contracts or invariants: ADR 0003 answer contract unchanged.
- Load-bearing paths: no runtime load-bearing path behavior change.
- ADR required: no, additive readiness measurement only.
- Backward compatibility expectation: existing `--output-dir` behavior remains
  supported; explicit `--out-json` and `--out-md` are additive.

## Affected Interfaces

- CLI/API/config: add optional `--out-json` and `--out-md` report outputs;
  tighten `make real-eval-v2-check` so bad private indexes fail closed.
- Input data: ignored private `real100_v2` index.
- Output artifacts: `reports/real100_v2/page_metadata_readiness.aggregate.json`
  and `docs/evaluation/real100_v2-page-metadata-readiness.md`.
- Docs/review surfaces: plan, queue, readiness report, PR §5b.
- Tests/eval entrypoints: focused page metadata audit tests and v2 guard.

## Data / Eval Impact

- Surface: private real-eval.
- Data boundary: aggregate-only private output.
- Allowed claim: current `real100_v2` index readiness is NO-GO because it uses
  hashing embeddings and has 0.0 chunk page metadata coverage.
- Disallowed claim: answer quality, retrieval quality, or page-aware performance
  improvement.
- Baseline or control affected: no; current index remains unchanged.
- Benchmark/eval auditor required: yes.

## Task Breakdown

1. Extend the existing page metadata audit script with explicit aggregate report
   output paths and MiniLM/page metadata index guard fields.
2. Run the audit against the canonical private `real100_v2` index only.
3. Make `real-eval-v2-check` reject hashing-backed private indexes and indexes
   with 0.0 chunk page metadata coverage.
4. Mark affected committed experiment reports as invalid for optimization
   claims until rerun on a MiniLM page-aware v2 index.
5. Run privacy, claim, link, and branch gates.

## Acceptance Criteria

- [x] The task either clears the page/window blocker or records an explicit
  no-go/rescope decision for `T-2026-0031`.
- [x] Page metadata coverage is reported as aggregate counts only.
- [x] Any index rebuild need records parser/index provenance as a future repair
  path, not as a completed behavior change.
- [x] Hashing-backed private real-eval indexes fail closed before experiment
  execution.
- [x] 0.0-coverage page metadata indexes fail closed before experiment
  execution.

## Validation Strategy

Commands that must be run:

```bash
REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent make real-eval-v2-check  # expected to fail for the current invalid hashing/page-0 index
python3 scripts/page_metadata_recovery_audit.py --index-dir /Users/hskim/Desktop/projects/BidMate-DocAgent/data/index/real100_v2 --out-json reports/real100_v2/page_metadata_readiness.aggregate.json --out-md docs/evaluation/real100_v2-page-metadata-readiness.md --format markdown
python3 -m pytest -q tests/test_real_eval_paths.py tests/test_page_metadata_recovery_audit.py tests/test_real100_v2_guard.py
make real-eval-v2-guard
python3 scripts/agent_loop.py privacy-audit-output
python3 scripts/agent_loop.py claim-audit --from-git
python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/T-2026-0047-repair-or-rescope-real100-v2-page-metadata-blocker.md docs/evaluation/real100_v2-page-metadata-readiness.md reports/real100_v2/README.md
git diff --check
make check-branch
```

Expected evidence:

- Test/eval output: focused tests and v2 readiness commands pass.
- Generated or updated artifact: aggregate-only page metadata readiness packet.
- Reviewer checklist or manual inspection: no private content, no performance
  improvement claim, no legacy evidence.
- Explicitly not validated, with reason: no MiniLM page-aware parser/index
  rebuild is performed in this PR.

## Rollback Strategy

Revert the additive script/report/doc updates. Do not delete private
`real100_v2` index artifacts or raw source files during rollback.

## Failure Modes

- Failure mode: report is mistaken for a page-aware improvement claim.
- Detection signal: claim audit or reviewer flags wording beyond NO-GO/readiness.
- Stop condition or fallback: keep `T-2026-0031` blocked and open a parser/index
  rebuild task.

- Failure mode: raw private identifiers leak into aggregate output.
- Detection signal: privacy audit or focused tests fail.
- Stop condition or fallback: remove unsafe fields and keep only counts/enums.

## Observability

- `reports/real100_v2/page_metadata_readiness.aggregate.json`
- `docs/evaluation/real100_v2-page-metadata-readiness.md`
- `make real-eval-v2-guard`
- `python3 scripts/agent_loop.py privacy-audit-output`
- `python3 scripts/agent_loop.py claim-audit --from-git`

## Reviewer Notes

Attack claim wording and data boundary first. The correct result is a NO-GO
readiness packet plus a fail-closed guard: current hashing-backed `real100_v2`
artifacts are not valid private optimization evidence until a MiniLM page-aware
index is rebuilt and measured.

## Handoff Notes

```markdown
## Session Handoff - 2026-05-28 14:25 KST

- Role: Evaluator / Implementer
- Branch / worktree: eval/issue-1645-repair-real100-v2-page-metadata-blocker / PR #1648
- Issue / PR: issue #1645 / PR #1648; refresh issue #2131
- Task: T-2026-0047
- Current status: merged in PR #1648; queue marks T-2026-0047 done. The aggregate readiness packet keeps affected optimization reports invalid for claims.
- Files touched: scripts/real_eval_paths.py, tests/test_real_eval_paths.py, scripts/page_metadata_recovery_audit.py, tests/test_page_metadata_recovery_audit.py, reports/real100_v2/page_metadata_readiness.aggregate.json, docs/evaluation/real100_v2-page-metadata-readiness.md, docs/evaluation/real100_v2-retrieval-diagnostics.md, docs/evaluation/real100_v2-latency-cost-budget.md, docs/evaluation/real100_v2-reranker-candidate-budget.md, docs/evaluation/real100_v2-context-packing.md, reports/real100_v2/README.md, .gitignore, .githooks/pre-commit, scripts/check_real100_v2_only.py, docs/plans/T-2026-0047-repair-or-rescope-real100-v2-page-metadata-blocker.md, tasks/queue.md
- Decisions made: no parser/index rebuild in this PR; T-2026-0031 remains blocked; T-2026-0029/T-2026-0030/T-2026-0032/T-2026-0033 optimization conclusions must be rerun on a MiniLM page-aware v2 index.
- Commands run: make ship-start TITLE="Repair real100 v2 page metadata blocker" TYPE=eval; make check-branch; python3 scripts/page_metadata_recovery_audit.py --index-dir <external_private_real100_v2_index> --out-json reports/real100_v2/page_metadata_readiness.aggregate.json --out-md docs/evaluation/real100_v2-page-metadata-readiness.md --format markdown; REAL_EVAL_ROOT=/Users/hskim/Desktop/projects/BidMate-DocAgent REAL100_V2_CONFIG=data/private/real100_v2/real_config_v2.local.yaml REAL100_V2_INDEX_DIR=data/index/real100_v2 REAL100_V2_REPORT_DIR=reports/real100_v2 make real-eval-v2-check.
- Results: `make real-eval-v2-check` now fails for current real100_v2 index because it uses hashing embeddings and chunk page metadata coverage is 0.0; readiness packet reports private real-eval index NO-GO.
- Next safe command: git status --short
- Open questions: none.
- Risks: existing historical aggregates remain in tree for auditability but are invalidated for optimization claims.
```
