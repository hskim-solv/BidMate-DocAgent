---
description: Enable, disable, or inspect the agent-loop Stop-hook report refresher.
argument-hint: "on|off|status"
allowed-tools: Bash(touch .claude/.agent-loop-watch), Bash(rm -f .claude/.agent-loop-watch), Bash(test -f .claude/.agent-loop-watch), Bash(python3 scripts/agent_loop.py gate-status:*), Bash(python3 scripts/agent_loop.py loop-state:*), Bash(python3 scripts/agent_loop.py auto-pass-check:*)
---

# Agent Loop Watch

Control the optional Stop-hook report refresher.

Arguments:

```text
$ARGUMENTS
```

Behavior:

- `on`: run `touch .claude/.agent-loop-watch`, then generate current reports:

```bash
python3 scripts/agent_loop.py gate-status --from-git --out reports/agent_loop/gate_status.md
python3 scripts/agent_loop.py loop-state --from-git --out reports/agent_loop/loop_state.json
python3 scripts/agent_loop.py auto-pass-check --from-git --out reports/agent_loop/auto_pass.md
```

- `off`: run `rm -f .claude/.agent-loop-watch`.
- `status` or empty: run `test -f .claude/.agent-loop-watch` and report whether watch mode is active.

The Stop hook only refreshes ignored local reports. It does not run validation, push, create/merge/close PRs, delete branches, force-push, run private real-eval, or approve claims.
