# 0063: Cross-worktree ADR number collision PreToolUse hook

- **Status**: proposed
- **Date**: 2026-05-20
- **Deciders**: hskim
- **Related**: [ADR 0007](./0007-issue-linked-branch-naming.md) (governance gates as CI checks), [ADR 0047](./0047-solo-author-adr-governance.md) (solo-author ADR lifecycle), issue [#1069](https://github.com/hskim-solv/BidMate-DocAgent/issues/1069)

## Context

ADR number collisions recur whenever two worktrees/sessions draft ADRs concurrently: 0022→0023, 0023→0025, 0029→0030 each forced a renumber-on-merge (file + body heading + cross-refs + README index row).

The existing guard — `scripts/_governance.py --check-adr-collision`, run by [`.githooks/pre-commit`](../../.githooks/pre-commit) — is **deliberately filesystem-only** (offline-safe, no `gh`). It cannot see a number already reserved by an open PR on another branch/worktree. CLAUDE.md asks for a manual `gh pr list --search "ADR" --state open` before drafting; that manual step is the one that keeps getting skipped.

## Decision

Add a PreToolUse hook [`scripts/claude-hooks/pretooluse-adr-collision.sh`](../../scripts/claude-hooks/pretooluse-adr-collision.sh) (matcher `Edit|MultiEdit|Write`) that, on a *new* `docs/adr/<NNNN>-*.md` Write, queries open PRs and refuses (exit 2) when `<NNNN>` is already reserved in another PR's title or head branch.

- **Cross-worktree only**: local same-number collisions stay pre-commit's job — single responsibility, no SSoT duplication.
- **Number source**: PR `title` + `headRefName`, zero-pad-insensitive (`ADR 0063`, `ADR-63`, `adr#63`, `…-adr-0063-…` all resolve to 63). PR body is ignored — bodies cite *other* ADRs constantly ("supersedes 0012") and would manufacture false positives. The match is re-filtered locally by exact integer so a loose `--search "ADR in:title"` can never over-block.
- **Fail-open**: gh absent / network failure / missing token / empty list / parse failure all → exit 0. pre-commit remains the merge-time backstop. Only a positive, named collision blocks.
- **Early-exit**: non-Write / non-ADR-filename / existing-file gates run before any `gh` call, so the network is touched only on genuine new-ADR Writes (a few times per week), bounded by `timeout 8` where available.

## Consequences

- The manual `gh pr list` discipline becomes automatic at write time; the recurring renumber-on-merge cost is caught before the draft is committed, not after merge.
- A new blocking governance surface (exit 2) joins the three existing PreToolUse hooks. Mitigated by fail-open on every infrastructure ambiguity — the only thing that blocks is a concrete cross-worktree collision, printed with the colliding PR number + a renumber remediation.
- **This ADR was itself caught by the collision it prevents.** `--next-adr-number` first returned 0060, and `gh pr list` showed only 0061 reserved (PR #1061). Mid-branch, ADR 0060 (`outcome-telemetry`, issue #1039) merged from another worktree — the exact cross-worktree race this hook closes. Re-checking returned 0061 (now filesystem-taken by the merge) with open PRs #1061 (0061) and #1073 (0062), so this ADR landed at 0063. Had the hook been active in this session it would have blocked the first Write at 0060.

## Alternatives considered

- **Extend `pretooluse-adr-template.sh`**: rejected — would couple a flaky network call into the deterministic offline template check and force one fail-policy onto two checks that want opposite ones (template fail-closed, collision fail-open).
- **Make pre-commit query open PRs**: rejected — `_governance.py`'s collision check is intentionally offline-safe; adding `gh` there breaks that contract and still fires only after the draft is fully written.
- **Warn-only (exit 0)**: rejected — a scrollable warning reproduces the skipped-manual-step failure that motivated this work. Block precision is high (exact integer match against an open PR's title/branch), and every ambiguity is already fail-open.

## Verification

<!-- verifies-key: scripts/claude-hooks/pretooluse-adr-collision.sh:adr-collision -->
<!-- verifies-key: tests/test_hook_pretooluse_adr_collision.py:test_collision_via_pr_title_blocks -->
<!-- verifies-key: .claude/settings.json:pretooluse-adr-collision.sh -->
