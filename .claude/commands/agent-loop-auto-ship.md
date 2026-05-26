---
description: Prepare and plan the existing BidMate auto-ship path without arming it.
argument-hint: "[optional TASK_ID]"
allowed-tools: Bash(python3 scripts/agent_loop.py auto-ship-prepare:*), Bash(python3 scripts/agent_loop.py auto-ship-plan:*), Bash(python3 scripts/agent_loop.py ship-simulate:*), Bash(python3 scripts/agent_loop.py approval-packet:*), Bash(make ship-status)
---

# Agent Loop Auto-Ship Plan

Render local preparation and plan reports for using the existing `make ship-arm` Stop-hook pipeline.
This command is planning-only; it must not run `make ship-arm`.

Arguments from the user:

```text
$ARGUMENTS
```

If the argument contains a task id matching `T-YYYY-NNNN`, run:

```bash
python3 scripts/agent_loop.py auto-ship-prepare --out reports/agent_loop/auto_ship_prepare.md
python3 scripts/agent_loop.py auto-ship-plan --task <TASK_ID> --from-git --dry-run --out reports/agent_loop/auto_ship_plan.md
python3 scripts/agent_loop.py ship-simulate --task <TASK_ID> --from-git --out reports/agent_loop/ship_simulation.md
python3 scripts/agent_loop.py approval-packet --task <TASK_ID> --from-git --out reports/agent_loop/approval_packet.md
make ship-status
```

Otherwise run:

```bash
python3 scripts/agent_loop.py auto-ship-prepare --out reports/agent_loop/auto_ship_prepare.md
python3 scripts/agent_loop.py auto-ship-plan --from-git --dry-run --out reports/agent_loop/auto_ship_plan.md
python3 scripts/agent_loop.py ship-simulate --from-git --out reports/agent_loop/ship_simulation.md
python3 scripts/agent_loop.py approval-packet --from-git --out reports/agent_loop/approval_packet.md
make ship-status
```

Report the recommendation, blockers, warnings, dry-run command, and human gates.
Do not arm auto-ship, push, create/merge/close PRs, delete branches, force-push, run private real-eval, or approve benchmark/performance claims.
