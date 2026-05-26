---
description: Run local BidMate preflight for a task and write copy-paste prompts.
argument-hint: "TASK_ID"
allowed-tools: Bash(python3 scripts/agent_loop.py preflight:*), Bash(python3 scripts/agent_loop.py handoff-check:*), Bash(python3 scripts/agent_loop.py suggest-validation:*)
---

# Agent Loop Preflight

Use this when a BidMate task is about to move from implementation to review.

Task argument:

```text
$ARGUMENTS
```

Require a task id matching `T-YYYY-NNNN`. If it is missing, stop and ask for the task id.

Run:

```bash
python3 scripts/agent_loop.py preflight --task <TASK_ID> --from-git --write-prompts
```

If preflight fails, summarize missing handoff fields, weak validation evidence, or surface review requirements. If it passes, point to the rendered implementation and review prompts under `reports/agent_loop/`.

Do not edit queue/plan docs, push, create/merge/close PRs, delete branches, force-push, run private real-eval, or approve benchmark/performance claims.
