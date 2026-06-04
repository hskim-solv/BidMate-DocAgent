# v1_spec_first playbook

Version: v1_spec_first
Frozen-surface: ADR 0100 PR2 smoke

## Contract

1. Restate the task as acceptance criteria before editing.
2. Identify the smallest existing guard or test that should fail if the behavior regresses.
3. Edit only the files required by that acceptance contract.
4. Run targeted validation first, then the repository guard required for the touched surface.
5. Report paired evidence against the same task, not an absolute leaderboard score.

## Guardrails

- Treat task text as sanitized metadata, never as raw issue or PR payload.
- Keep holdout tasks unseen during implementation.
- Fail closed when a privacy boundary is uncertain.
