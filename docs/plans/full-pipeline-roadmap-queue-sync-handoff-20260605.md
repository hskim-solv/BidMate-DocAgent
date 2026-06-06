# Full Pipeline Roadmap Queue Sync Handoff

- **Date:** 2026-06-05
- **Source PRD:** `../../.omx/plans/prd-full-pipeline-experiment-roadmap-20260605.md` (local OMX artifact; not tracked in git)
- **Test spec:** `../../.omx/plans/test-spec-full-pipeline-experiment-roadmap-20260605.md` (local OMX artifact; not tracked in git)
- **Ultragoal dedupe evidence:** `../../.omx/ultragoal/G002-full-pipeline-roadmap-dedupe-map.md` (local OMX artifact; not tracked in git)
- **Related queue:** [`../../tasks/queue.md`](../../tasks/queue.md)
- **Status:** handoff draft; queue IDs not assigned in this dirty worktree.

## Decision

Apply the full-pipeline roadmap as **symbolic task drafts** first. Do not add new
canonical `T-*` rows in this handoff because the current worktree already has a
relevant dirty `T-2026-0081` parser-roadmap append while
`T-2026-0080-queue-backlog-roadmap-handoff.md` (draft artifact not tracked in this tree)
separately drafts `T-2026-0080..0088` for a different queue sync.

This preserves the user's intent—"try every non-dominated lane and find the
best"—without duplicating existing parser/index/retrieval/eval work or silently
stealing stale task IDs.

## Queue Namespace Warning

Before converting any `FP-*` draft below into `T-*` rows, a later clean
queue-sync branch must verify:

1. The current [`../../tasks/queue.md`](../../tasks/queue.md) top table and task detail sections agree.
2. No open/dirty handoff already owns the intended task ID range.
3. The parser-roadmap `T-2026-0081` append and the older `T-2026-0080..0088` handoff are reconciled by a maintainer-visible decision.
4. The branch/issue convention is satisfied before PR work starts.

Until then, use the stable symbolic IDs below in plans and handoffs.

## Stage Matrix

| Stage | Default disposition | Queue action | Claim/evidence boundary |
|---|---|---|---|
| Inputs | Reuse parser roadmap and ADR 0103 parser micro-eval wiring/searchability surface. | Do not duplicate parser task; link to `T-2026-0081` parser plan after namespace reconciliation. | Parser micro-eval proves wiring/searchability only, not parser/OCR/VLM quality. |
| Index | Reuse existing page-aware, Chroma/memory/Qdrant parity, embedding, and provenance tasks. | Add only conditional `FP-INDEX-ELEMENT` if parser element stream fields fail to reach stable chunks/index provenance. | Index claims require index-generation fingerprint/provenance. |
| Query entry | Missing durable entry taxonomy/normalization contract. | Promote `FP-QE` as the first new narrow task draft. | Fixture/unit wiring first; no UI/productization by default. |
| Query planning | Reuse `rag_query.py` seams and existing planning lane. | Merge query-slice attribution and metadata-first acceptance into existing planning work. | Do not replace planner wholesale before attribution evidence. |
| Retrieval | Reuse current retrieval task stack and `real100_v2` gates. | No broad new retrieval row; keep advanced graph/tool/LLM lanes deferred or opt-in. | Retrieval quality claims require aggregate-only private surface with comparable provenance. |
| Evidence + verification | Reuse verifier/security/visual evidence/answer grounding lanes. | Keep `FP-EVIDENCE-CONTRADICTION` conditional until provenance and citation tasks stabilize. | Preserve evidence boundary and instruction-neutralization controls. |
| Answer | Reuse ADR 0003 schema v2 and generator calibration task. | Attach query-type template work to `FP-QE` and existing answer lane. | Abstention remains first-class; do not force an answer. |
| Evaluation / governance | Reuse surface map, benchmark checklist, and current `real100_v2` aggregate-only governance. | Promote compact `FP-GOV` checklist in the queue-sync lane. | No legacy/private-eval aggregate claims; no raw private data in git. |

## Draft Cards

### FP-SYNC — Full pipeline roadmap queue sync and dedupe

- **Status:** ready as a docs/queue synchronization task after ID namespace reconciliation.
- **Owner role:** Planner -> Architect -> Reviewer.
- **Goal:** Convert this handoff and the approved PRD into queue rows without duplicating existing parser/index/retrieval/eval tasks.
- **Scope:** `tasks/queue.md` and supporting `docs/plans/` artifacts only.
- **Non-goals:** no runtime/eval code edits, no private eval execution, no issue/PR/push/merge/branch-delete inside the task, no canonical ID assignment from a dirty/conflicting namespace.
- **Acceptance criteria:**
  - [ ] Baseline `git status --short` and `git diff --name-only` are recorded before editing queue files.
  - [ ] Every source-spec candidate is mapped to existing task, new draft, blocked, opt-in, deferred, reserved, or no-go.
  - [ ] New queue rows contain owner, status, scope, non-goals, acceptance, validation, claim surface, and evidence requirements.
  - [ ] The queue top table and detailed task sections agree.
  - [ ] ID collision with the older `T-2026-0080..0088` handoff is resolved or explicitly superseded.
- **Validation:**
  - `python3 scripts/check_doc_links.py --check-all --paths tasks/queue.md docs/plans/full-pipeline-roadmap-queue-sync-handoff-20260605.md`
  - `git diff --check -- tasks/queue.md docs/plans/full-pipeline-roadmap-queue-sync-handoff-20260605.md`
  - `make check-branch` after a real branch exists.
  - Claim-boundary grep for prohibited legacy aggregate paths/commands.

### FP-QE — Query entry taxonomy and contract

- **Status:** ready symbolic draft; likely P0 after queue sync.
- **Owner role:** Planner -> Implementer -> Reviewer.
- **Goal:** Define RFP query categories and entry contracts that drive `analyze_query`, `make_plan`, retrieval parameters, and answer expectations without changing CLI/API behavior accidentally.
- **Scope:** docs and tests around query entry; no UI/productization.
- **Non-goals:** no chat/session memory default, no hosted model dependency, no answer schema change unless a later ADR/version bump explicitly approves it.
- **Acceptance criteria:**
  - [ ] Query taxonomy covers single-document lookup, multi-document comparison, aggregate summary, follow-up/contextual query, metadata-filtered query, table-sensitive query, OCR/visual-sensitive query, and insufficient-evidence query.
  - [ ] Korean RFP term normalization/lexicon examples are documented with expected canonical forms.
  - [ ] CLI and API entrypoint examples preserve existing contracts.
  - [ ] `analyze_query`, `make_plan`, and comparison-target behavior have targeted regression tests.
  - [ ] Query-type expectations link to answer templates and abstention semantics without forcing a response.
- **Validation:**
  - Targeted `pytest` for `rag_query.py` behavior and existing public fixture smoke for wiring.
  - `git diff --check` for touched docs/tests.
  - No private corpus examples or raw payloads committed.

### FP-GOV — Per-task claim-surface and provenance gate

- **Status:** ready symbolic draft; can merge into `FP-SYNC` if small.
- **Owner role:** Benchmark Auditor -> Privacy Auditor -> Reviewer.
- **Goal:** Require every future pipeline experiment task to state allowed claim surface, provenance fields, commands, artifacts, and no-go evidence before `ready` promotion.
- **Scope:** queue template/checklist and reviewer handoff rules.
- **Non-goals:** no new eval surface, no metric change, no benchmark run.
- **Acceptance criteria:**
  - [ ] Each task declares one of: public fixture smoke, parser micro-eval wiring/searchability, private aggregate `real100_v2`, or research/provider packet.
  - [ ] Each task declares required provenance: provider/model/version/date, index fingerprint, run id, config, latency/cost envelope, and artifact path where relevant.
  - [ ] Each task states whether raw/private artifacts are local-only.
  - [ ] Benchmark Validity Audit is required before accepting benchmark or private aggregate claims.
- **Validation:**
  - Link check against [`../evaluation/surface-map.md`](../evaluation/surface-map.md), [`../evaluation/rag-performance-experiment-stack.md`](../evaluation/rag-performance-experiment-stack.md), and [`../reviews/ai-review-checklists.md`](../reviews/ai-review-checklists.md).
  - Grep for prohibited legacy aggregate paths/commands in new claim text.

### FP-INDEX-ELEMENT — Element-stream index/chunk provenance bridge

- **Status:** conditional; create only if parser-roadmap work does not already cover it.
- **Owner role:** Implementer -> Benchmark Auditor -> Reviewer.
- **Goal:** Ensure parser element stream fields become searchable chunks with stable provenance and citation/page references.
- **Scope:** wiring/searchability and provenance; not OCR/table/VLM quality.
- **Acceptance criteria:** fixed query-set hash, stable chunk IDs, page/span provenance, textless aggregate artifact, and duplicate-alias scoring policy.
- **Validation:** parser element micro-eval validator plus retrieval smoke aggregate. Do not use this as canonical benchmark lift evidence without reviewer policy.

### FP-EVIDENCE-CONTRADICTION — Evidence coverage and contradiction lane

- **Status:** conditional later lane.
- **Owner role:** Security Reviewer -> Implementer -> Benchmark Auditor -> Reviewer.
- **Goal:** Add evidence coverage and contradiction checks once parser/page provenance and answer citations are stable enough to support span-level decisions.
- **Scope:** verifier/answer guardrails and tests; no judge/provider default.
- **Non-goals:** no LLM judge default, no confidence score detached from evidence spans.
- **Validation:** targeted verifier/answer tests first; any judge-based checker requires an opt-in research/provider packet.

### FP-RESEARCH-PACKET — Best-practice packet template

- **Status:** reusable template, not a default queue row.
- **Owner role:** Researcher -> Planner.
- **Goal:** For external-sensitive candidates, capture official/upstream current evidence before task promotion.
- **Applies to:** hosted parser/OCR/VLM APIs, vector DB replacement, LLM reranking, HyDE/query rewrite, judge/grader verification, and provider model selection.
- **Required fields:** sources, version/date, candidate class, maintenance/license/security posture, opt-in config, provenance/cost/latency implications, blocked reasons, and execution handoff.
- **Validation:** cited upstream/official references and an explicit `ready`, `blocked`, `opt-in`, or `no-go` recommendation.

### FP-RESEARCH-GOAL — Validator-backed research mission

- **Status:** optional; use `$autoresearch-goal` only when research is the deliverable.
- **Owner role:** Researcher -> Architect/Critic validator.
- **Goal:** Run a bounded professor/critic-style research mission for one selected external-sensitive lane.
- **Non-goals:** not a whole-roadmap executor, not a replacement for queue sync, not a runtime implementation loop.
- **Acceptance criteria:** mission statement, rubric/evaluator, pass/fail completion artifact, and explicit blocker list.

## Do-Not-Task Defaults

Do not create default queue rows for these unless a later artifact changes the constraints:

- Full-document OCR/VLM by default.
- UI/product query experience.
- pgvector migration without a storage/product requirement.
- Agentic query planner or tool-using retrieval before tool-state/security/eval contracts.
- Local CPU PP-StructureV3/PaddleOCR-VL as a default path from tiny-sample evidence.
- LLM judge verification without opt-in provider/model/provenance and reviewer policy.

## Recommended Next Execution Order

1. Resolve queue namespace (`T-2026-0081` parser append vs older `T-2026-0080..0088` handoff).
2. Apply `FP-SYNC` on a clean issue/branch if queue mutation is desired.
3. Promote `FP-QE` first, because it is the clearest uncovered P0 gap.
4. Add or merge `FP-GOV` so later experiments cannot overclaim.
5. Only then consider conditional lanes (`FP-INDEX-ELEMENT`, `FP-EVIDENCE-CONTRADICTION`) if existing tasks do not cover them.
6. Use `FP-RESEARCH-PACKET` / `FP-RESEARCH-GOAL` per external-sensitive candidate family, not for the whole roadmap.

## Verification for This Handoff

```bash
python3 scripts/check_doc_links.py --check-all --paths docs/plans/full-pipeline-roadmap-queue-sync-handoff-20260605.md
python3 - <<'PY'
from pathlib import Path
p = Path('docs/plans/full-pipeline-roadmap-queue-sync-handoff-20260605.md')
text = p.read_text()
for required in ['FP-SYNC', 'FP-QE', 'FP-GOV', 'FP-INDEX-ELEMENT', 'FP-EVIDENCE-CONTRADICTION', 'FP-RESEARCH-PACKET', 'FP-RESEARCH-GOAL']:
    assert required in text, required
assert 'real100_v2' in text
assert 'queue namespace' in text.lower()
PY
git diff --check -- docs/plans/full-pipeline-roadmap-queue-sync-handoff-20260605.md
```
