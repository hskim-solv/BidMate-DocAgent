# 0083: `make 시작` local gate completion and `real100_v2` judge egress profiles

- Status: accepted
- Date: 2026-05-29
- Related: [ADR 0005](./0005-eval-split-public-synthetic-private-local.md), [ADR 0061](./0061-external-and-paid-api-dependencies-allowed.md), [ADR 0079](./0079-agent-gated-offline-online-rfp-eval-loop.md), [ADR 0080](./0080-active-loop-registry-v2-dual-agent-lanes.md), [ADR 0081](./0081-chroma-backed-naive-baseline.md)
- Issue: #1667

## Context

`make 시작` is an operator-facing start alias for the active agent loop. It must
run a bounded queue wave and stop, but it must not silently ship by default.
The previous dry-run surface could spawn reviewer lanes and then invoke the
ship path once the conservative gate became ready. That made a local start
alias carry remote-mutation semantics.

The same loop also needs generation and judge evidence for `real100_v2`.
Offline users need a zero-cost route (`stub` or loopback OpenAI-compatible
server). Online users may intentionally approve external API egress, but ADR
0005 still forbids leaking raw private artifacts into committed outputs.

## Decision

1. `make 시작` runs a bounded active-auto-loop with `START_TASK_LIMIT=5`,
   runner execution enabled, and ship execution disabled by default.
2. A task can be recorded as locally complete only after the runner completes,
   conservative gate evidence is ready, and the privacy gate is clean. Runner
   completion alone is never enough.
3. When no explicit changed-file list is supplied, the active-auto-loop uses
   the current git diff as the active scope. If the current branch slug names a
   task id, that task is selected for the first cycle before generic queue
   selection.
4. `real100_v2` judge aggregates are first-class aggregate-only artifacts:
   `judge.aggregate.json`, `judge_ragas.aggregate.json`, and
   `rationality.aggregate.json`. Per-case local payloads, traces, prompts, and
   completions remain local-only.
5. Private external API egress is allowed only through explicit environment
   attestation profiles. This is channel-wide, not LLM-only: synthesis,
   metadata extraction, embeddings, reranking, query rewrite, and planning can
   all carry raw document/query/evidence text. `approved_external_api` and
   `customer_managed_cloud` mean the operator has already approved the
   provider/data boundary for every enabled external channel in this run.
   `redacted_external_api` is not accepted until the payload is actually proven
   redacted before egress.
6. Loopback OpenAI-compatible synthesis is a separate local path. It requires a
   loopback base URL and does not require external egress approval.

## Consequences

- `make 시작` can advance local task evidence without creating a PR, pushing,
  merging, or running `ship-run`.
- Reviewer and CI lanes see the real changed-file surface instead of stale
  task-doc-only assignments.
- Paid/external API use remains opt-in and auditable across all external API
  channels. The zero-cost path stays available through `stub` judge backends
  and local loopback model servers.
- This ADR does not claim parent/section-window retrieval quality. That remains
  blocked on paired `real100_v2` aggregate evidence.

## Alternatives Considered

- Keep `make 시작` ship-capable by default. Rejected: a start alias should not
  carry remote-mutation semantics.
- Treat read-only runner completion as task completion. Rejected: it would let
  reports alone masquerade as finished work.
- Allow a generic `redacted_external_api` profile now. Rejected: current
  generation/judge backends can send evidence text; redaction must be proven in
  code before the profile is safe.

## Verification

```bash
python3 -m pytest -q tests/test_agent_loop.py -k 'active_auto_loop or make_active_start or active_codex_runner'
python3 -m pytest -q tests/test_llm_judge.py -k 'CLI or out_aggregate or cli'
python3 scripts/agent_loop.py preflight --task T-2026-0031 --from-git
git diff --check
```

<!-- verifies-key: scripts/agent_loop.py:write_active_auto_loop -->
<!-- verifies-key: Makefile:시작 -->
<!-- verifies-key: bidmate_data_boundary.py:external_egress_allowed -->
<!-- verifies-key: rag_synthesis.py:LOCAL_OPENAI_BACKEND -->
<!-- verifies-key: scripts/llm_judge.py:parse_args -->
<!-- verifies-key: eval/judges/llm_judge.py:parse_args -->
<!-- verifies-key: eval/judges/rationality_judge.py:render_markdown -->
