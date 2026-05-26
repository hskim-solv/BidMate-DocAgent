---
description: Summarize the BidMate agent-loop state, surface, and next safe command.
argument-hint: "[optional TASK_ID]"
allowed-tools: Bash(python3 scripts/agent_loop.py status:*), Bash(python3 scripts/agent_loop.py gate-status:*), Bash(python3 scripts/agent_loop.py loop-state:*)
---

# Agent Loop Status

Run the local BidMate agent-loop status check. This command is read/report centered.

Arguments from the user:

```text
$ARGUMENTS
```

If the argument contains a task id matching `T-YYYY-NNNN`, run:

```bash
python3 scripts/agent_loop.py status --task <TASK_ID> --from-git
python3 scripts/agent_loop.py gate-status --task <TASK_ID> --from-git
python3 scripts/agent_loop.py loop-state --task <TASK_ID> --from-git
```

Otherwise run:

```bash
python3 scripts/agent_loop.py status --from-git
python3 scripts/agent_loop.py gate-status --from-git
python3 scripts/agent_loop.py loop-state --from-git
```

Report the current gate, surface classification, validation suggestions, generated artifact paths, and the next safe command. Do not push, create/merge/close PRs, delete branches, force-push, or make benchmark/private-real-eval claims.
