---
description: Render an adversarial review prompt and review gate summary for a BidMate task.
argument-hint: "TASK_ID [PR_NUMBER]"
allowed-tools: Bash(python3 scripts/agent_loop.py review-prompt:*), Bash(python3 scripts/agent_loop.py gate-status:*), Bash(python3 scripts/agent_loop.py claim-audit:*), Bash(python3 scripts/agent_loop.py privacy-audit-output:*)
---

# Agent Loop Review Prompt

Use this to prepare a copy-paste adversarial review prompt and local review gate evidence.

Arguments from the user:

```text
$ARGUMENTS
```

Require a task id matching `T-YYYY-NNNN`. If a numeric PR number is also present, pass it with `--pr`.

Run one of:

```bash
python3 scripts/agent_loop.py review-prompt --task <TASK_ID> --from-git --out reports/agent_loop/review_prompt.txt
python3 scripts/agent_loop.py gate-status --task <TASK_ID> --from-git --out reports/agent_loop/gate_status.md
python3 scripts/agent_loop.py claim-audit --from-git --out reports/agent_loop/claim_audit.md
python3 scripts/agent_loop.py privacy-audit-output --path reports/agent_loop --out reports/agent_loop/privacy_audit.md
```

or, with a PR number:

```bash
python3 scripts/agent_loop.py review-prompt --task <TASK_ID> --pr <PR_NUMBER> --from-git --out reports/agent_loop/review_prompt.txt
python3 scripts/agent_loop.py gate-status --task <TASK_ID> --pr <PR_NUMBER> --from-git --out reports/agent_loop/gate_status.md
python3 scripts/agent_loop.py claim-audit --pr <PR_NUMBER> --out reports/agent_loop/claim_audit.md
python3 scripts/agent_loop.py privacy-audit-output --path reports/agent_loop --out reports/agent_loop/privacy_audit.md
```

Summarize required reviewer modes, surface classification, claim/privacy boundaries, and next safe command. Do not auto-fix review comments unless the user explicitly asks for a scoped implementation pass.
