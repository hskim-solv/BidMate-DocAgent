---
description: Check whether a low-risk local gate can continue without human review.
argument-hint: "[optional TASK_ID]"
allowed-tools: Bash(python3 scripts/agent_loop.py auto-pass-check:*), Bash(python3 scripts/agent_loop.py loop-state:*)
---

# Agent Loop Auto-Pass

Run the fail-closed low-risk gate check. This is not a shipping approval.

Arguments from the user:

```text
$ARGUMENTS
```

If the argument contains a task id matching `T-YYYY-NNNN`, run:

```bash
python3 scripts/agent_loop.py auto-pass-check --task <TASK_ID> --from-git --run-validation --out reports/agent_loop/auto_pass.md
python3 scripts/agent_loop.py loop-state --task <TASK_ID> --from-git
```

Otherwise run:

```bash
python3 scripts/agent_loop.py auto-pass-check --from-git --run-validation --out reports/agent_loop/auto_pass.md
python3 scripts/agent_loop.py loop-state --from-git
```

Only treat `Decision: auto-pass` as permission to continue local read/report orchestration. It does not authorize push, PR creation, merge, close, branch deletion, force-push, private real-eval decisions, architecture decisions, or benchmark/performance claims.
