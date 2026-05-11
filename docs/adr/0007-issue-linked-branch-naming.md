# 0007: Issue-linked branch naming as a required check

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: extends [`docs/engineering-governance.md`](../engineering-governance.md) §"Change lifecycle"; supersedes the informal `claude/<auto>` worktree naming pattern
- **Deciders**: hskim

## Context

Until now the repo had no enforced linkage between work and a tracking issue:

- The PR template carries a `Closes #` placeholder under §1, but nothing
  validates it ([`.github/pull_request_template.md`](../../.github/pull_request_template.md)).
- Branch names in `git branch -a` are a mix of `claude/issue-<N>-<slug>`,
  `claude/<adj>-<name>-<hash>` (auto-named worktrees), and a few legacy
  `feat/<N>-<slug>` shapes. The convention is observable from history but
  not stated as a rule.
- `engineering-governance.md` step 1 ("Open or pick an issue") is a soft
  instruction. PRs can be merged without an issue number anywhere.

Consequence: traceability gaps. A reviewer cannot grep `Closes #123` to
find the PR that closed an issue if the link was never recorded. Worse,
the `claude/<auto>` worktree pattern actively obscures whether an issue
exists at all — the branch name encodes random words, not intent.

The new rule below makes the link required and machine-checked at the
PR boundary.

## Decision

Every PR merged to `main` must satisfy three conditions, enforced by a
new CI workflow `.github/workflows/branch-and-issue-check.yml`:

1. **Branch name matches the convention:**
   ```
   ^(?:feat|fix|docs|chore|refactor|test|ci|perf|build|style)/issue-(\d+)(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?$
   ```
   - Prefix is one of the conventional-commit types listed above.
     **`claude/` is rejected** — Claude Code's auto-named worktree
     branches must be renamed before opening a PR.
   - `issue-<N>` is mandatory; the slug after it is optional but
     recommended for human readability.
   - Examples: `feat/issue-79-senior-positioning`, `fix/issue-104`.

2. **The referenced issue exists** in this repo (state — open or closed
   — is not checked; follow-up branches can legitimately reference a
   closed issue).

3. **The PR body contains `Closes #N` (or `Fixes` / `Resolves`)** and
   at least one of those numbers equals the branch's `<N>`. This is
   the same regex GitHub uses to auto-close issues on merge, so the
   check piggybacks on existing UX.

The regex, issue check, and `Closes`-matching all live in a single
script — [`scripts/check_branch_and_issue.py`](../../scripts/check_branch_and_issue.py)
— used by both the CI workflow (`--pr <N>`) and the local
[`.githooks/pre-push`](../../.githooks/pre-push) hook (`--branch <name>`).
No regex duplication, no drift.

### Exemptions

The following branch prefixes skip the check (they have no tracking
issue by construction):

- `revert-*` — GitHub auto-generated revert branches.
- `dependabot/*` — Dependabot PRs.
- `renovate/*` — Renovate PRs.
- `pre-commit-ci/*` — pre-commit autoupdate PRs.

### Enforcement layers

| Layer | When | Bypassable? | What it checks |
|---|---|---|---|
| CI (`branch-and-issue-check.yml`) | every `pull_request` to `main` | **No** (required status check) | branch regex + issue exists + `Closes #N` matches |
| Local `.githooks/pre-push` | `git push` (opt-in via `make install-hooks`) | `--no-verify` | branch regex + (if `gh` installed) issue exists |

CI is the contract. The local hook is a fast-feedback mirror for
developers who have run `make install-hooks`.

## Consequences

**Wins**

- Every merged PR is issue-traceable. `git log --grep '#'` finds the
  whole change set for an issue, and the GitHub UI auto-closes the
  issue on merge.
- Branch names encode intent (`feat/issue-79-…` says what kind of work
  this is and what it tracks) rather than random words.
- The PR template's `Closes #` placeholder becomes a contract instead
  of a hint — reviewers know it will block merge if missing.
- CI gate cannot be silently bypassed; the local hook gives instant
  feedback for developers who opt in.

**Costs**

- **Claude Code's default worktree branch name (`claude/<adj>-<name>-<hash>`)
  will be rejected.** Contributors must rename before opening a PR
  (`git branch -m feat/issue-<N>-<slug>`). This is one rename per
  branch, paid at branch creation rather than commit time.
- One extra workflow run per PR. Fast (~15s, no checkout of code).
- Bots (Dependabot, Renovate) are exempted by prefix; their PRs are
  trusted.
- Some legitimate work (small typo fixes, doc-only follow-ups) now
  requires an issue first. We accept this friction in exchange for
  uniform traceability.

**Constraints introduced**

- The script `scripts/check_branch_and_issue.py` is the single source
  of truth for the regex. Future tweaks (allowed prefixes, exemptions,
  slug shape) edit that file and the corresponding test
  `tests/test_branch_convention.py` — never duplicate the regex in
  the CI workflow or the hook.
- Branch protection on `main` should mark *"Branch & Issue Convention"*
  as a required status check **after** the workflow has run green on
  one known-good PR and red on a deliberate probe.

## Alternatives considered

- **Keep `claude/issue-<N>-<slug>` allowed and just reject the
  auto-name pattern.** Rejected: the user explicitly opted to drop the
  `claude/` prefix in favor of conventional-commit types. This also
  aligns branch names with commit-message conventions and makes the
  branch list scan like a categorized changelog (`feat/`, `fix/`,
  `docs/` are immediately legible).
- **Allow `epic/<slug>` as an issue-less exception for multi-issue
  work.** Rejected: an epic is itself a tracking issue. Forcing the
  epic-issue number into the branch name (e.g.
  `feat/issue-<epic-N>-multi-doc-retrieval`) is a small price for
  uniformity.
- **Enforce only in the local hook, not in CI.** Rejected: the existing
  hooks are opt-in (`git config core.hooksPath .githooks`). Without CI,
  any contributor who hasn't run `make install-hooks` silently bypasses
  the rule. CI is the only universal surface.
- **Validate the issue *body* (e.g. require a checklist).** Rejected as
  scope creep. This ADR is about traceability, not about issue
  hygiene. Issue templates ([`.github/ISSUE_TEMPLATE/`](../../.github/ISSUE_TEMPLATE/))
  encourage hygiene without enforcing it.
- **Cross-check `Closes #N` without matching the branch's `<N>`.**
  Rejected: a PR that says `Closes #50` but lives on `feat/issue-49-…`
  is almost certainly a mistake — either the branch was reused or the
  body was copy-pasted from a sibling PR. The match catches this.
