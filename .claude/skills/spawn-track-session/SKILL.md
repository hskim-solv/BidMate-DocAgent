---
name: spawn-track-session
description: |
  Judgment layer for spawning an isolated cmux track session with the existing `make spawn-track` / `scripts/spawn_track_session.sh` helper. Use when the user wants a side Claude track/workspace for an existing issue and needs the cold-start prompt to include the right BidMate surface rules. This skill classifies the track (eval, retrieval-baseline, embedding-M3, or other), synthesizes a quote-safe prompt, runs DRY_RUN first, and requires explicit approval before the real spawn. It never creates issues, changes helper code, pushes, opens PRs, or merges.
---

# /spawn-track-session — cmux side-track judgment layer

This skill is the judgment layer above [`scripts/spawn_track_session.sh`](../../../scripts/spawn_track_session.sh) and [`make spawn-track`](../../../Makefile). The helper owns worktree creation, ADR 0007 branch validation, overlap preflight, and cmux invocation. This skill owns only the choice of track surface and the cold-start prompt.

## Scope

- Existing issue only. If there is no issue number, stop and ask the caller to create one through the normal issue-first flow; this skill does not run `gh issue create`.
- One side track per invocation.
- No helper code changes. If `make spawn-track` is missing or broken, report the blocker instead of reimplementing spawning.
- No push, PR, merge, or branch deletion.

## Workflow

1. **Prerequisite gate**
   - Confirm the issue exists: `gh issue view <N> --json number,title,state,url`.
   - Confirm cmux is available in the current pane: `cmux identify --json` or the configured `CMUX_BIN identify --json`.
   - If cmux identify fails, stop after showing the helper fallback command shape; do not run the real spawn because this skill is specifically for cmux track creation.

2. **Classify the track**
   Pick exactly one surface and state the reason:

   | Track | Use when | Prompt rules to inject |
   | --- | --- | --- |
   | `eval` | real100_v2 eval, metric, benchmark, scorer, report, or aggregate work | Use real100_v2 only; legacy real100 v1 221 kordoc aggregate evidence is banned; prefer `make real-eval-v2-check`, `make real-eval-v2-inventory`, and `make real-eval-v2-guard`; no raw private text or paths. |
   | `retrieval-baseline` | retrieval defaults, baseline, Chroma, dense or hybrid comparison work | Preserve ADR 0001 naive_baseline behavior; Chroma is the default index backend; do not mix retrieval knobs without an explicit eval surface. |
   | `embedding-M3` | BGE-M3, embedding model, local GPU or memory-sensitive measurement work | BGE-M3 claims apply only to indexes built with BGE-M3; if local model resources are insufficient, use bounded fast checks instead of ad-hoc private rebuilds. |
   | `other` | docs, planning, agent-loop, or non-eval side work | Inject only common repo rules and the issue-specific goal. |

3. **Synthesize a quote-safe prompt**
   The helper nests `cmux workspace create --command "claude '<prompt>'"`. Therefore the prompt must avoid these characters: backtick, dollar sign, bang, double quote, and apostrophe. Do not sanitize silently; rewrite the prompt in plain text and re-check it. `#` is allowed for issue references.

   Include these common rules in every prompt:
   - Work only in the spawned worktree and branch.
   - Follow ADR 0007 issue-first branch convention.
   - Keep one PR concern and avoid unrelated edits.
   - Do not push, open PRs, merge, delete branches, or create issues without explicit user approval.
   - Verify locally before claiming completion.

4. **DRY_RUN first**
   Show the exact dry-run command before any state-changing spawn:

   ```bash
   DRY_RUN=1 ISSUE=<N> TYPE=<type> SLUG=<slug> PROMPT='<quote-safe prompt>' make spawn-track
   ```

   Read the output. It must show the expected `git fetch`, `overlap-preflight`, `git worktree add`, and cmux `workspace create` command shape. If the helper reports forbidden prompt characters, stale-base blockers, or branch convention failures, fix those before proceeding.

5. **Approval gate for real spawn**
   The real spawn creates a worktree and cmux workspace. Run it only after explicit go-ahead such as `진행`, `ㄱㄱ`, `ok`, or `go`:

   ```bash
   ISSUE=<N> TYPE=<type> SLUG=<slug> PROMPT='<same quote-safe prompt>' make spawn-track
   ```

   Treat short questions like `spawn?`, `PR?`, `ready?`, or `?` as questions, not approval.

6. **Handoff**
   Report the spawned worktree path, branch, cmux workspace if available, track classification, and the exact prompt used. If the helper fell back because cmux was unavailable, report the manual resume command and stop.

## Prompt template

Use this shape, then remove any forbidden characters before DRY_RUN:

```text
Issue #N. Track TYPE. Goal: <one sentence>. Work only in the spawned worktree and branch. Follow ADR 0007 and one PR one concern. <track-specific rules>. Do not push open PR merge delete branches or create issues without explicit user approval. Verify with <targeted checks> before claiming completion.
```

## What this skill does NOT do

- Does not create the issue.
- Does not alter `scripts/spawn_track_session.sh` or `Makefile`.
- Does not bypass the helper escape guard.
- Does not run private eval or rebuild indexes.
- Does not push, open PRs, merge, or delete branches.
