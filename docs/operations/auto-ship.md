# Auto-ship pipeline

The auto-ship pipeline is a Stop-hook–driven sequence that takes a feature
branch from local commits to a squash-merged PR on `main` with one
ack: `make ship-arm`. Every cycle is single-shot — success or failure
both disarm the trigger.

This page documents the operational contract: how to arm it, what each
gate / stage enforces, where the safety nets live, and which discipline
rules (notably the stacked-PR gate) must be respected when bypassing
them. The implementation lives in
[`scripts/claude-hooks/stop-ship.sh`](../scripts/claude-hooks/stop-ship.sh)
(Stop hook entry point) and
[`scripts/claude-hooks/_ship_pr_body.py`](../scripts/claude-hooks/_ship_pr_body.py)
(PR body generator). Registration:
[`.claude/settings.json`](../.claude/settings.json) `Stop` hook.

## Arming: `make ship-arm`

The Makefile target writes [`.claude/.ship-armed`](../Makefile) (a JSON
state file) and exits; the actual pipeline runs on the next Claude Stop
event. Knobs (env-var overrides):

| Var | Default | Effect |
|---|---|---|
| `TTL` | `2h` | Arm lifetime. `30m`, `90m`, `1d` accepted. Expiry → silent disarm. |
| `REAL_EVAL` | `auto` | §5b cascade mode. `skip` forces escape; `async` defers; `auto` runs delta-or-full. |
| `DRAFT` | `false` | Open PR as draft. |
| `DRY_RUN` | `0` | With `1`, all mutating commands are echoed to `.claude/.ship-dryrun.log` instead of executed. |
| `CROSS_OWNER` | _(empty)_ | `ack` bypasses the multi-agent lock check ([`docs/multi-agent-ownership.md`](../multi-agent-ownership.md)). |
| `STACKED` | _(empty)_ | `ack` bypasses the heterogeneous-prefix refusal (see [Stacked-PR discipline](#stacked-pr-discipline-tier-7) below). |

`make ship-disarm` removes the arm file and pid file. `make ship-status`
prints a human-readable summary. See
[`Makefile:289-339`](../Makefile) and
[`scripts/claude-hooks/_ship_arm.py`](../scripts/claude-hooks/_ship_arm.py).

## Pipeline overview

```
make ship-arm  (writes .claude/.ship-armed)
    ↓
Claude Stop event  →  scripts/claude-hooks/stop-ship.sh fires
    ↓
Gate 0 — 8 pre-checks (silent exit on any failure)
    ↓
Stage 1: commit   (private-path filter → multi-agent lock → tier-7 prefix gate → bash scripts/test.sh → git commit)
Stage 2: push     (ADR 0007 branch check → git push)
Stage 3: PR       (_ship_pr_body.py → §5b cascade → gh pr create)
Stage 4: CI wait  (gh pr checks --watch, 30-min timeout)
Stage 5: merge    (gh pr merge --squash --admin --delete-branch → checkout main → disarm)
```

Single-shot disarm: success deletes the arm file at the end of Stage 5;
failure deletes it via `abort_disarm` in any stage. The pipeline is
re-armed only with another explicit `make ship-arm`.

## Gate 0 — eight silent pre-checks

The Stop hook fires on every Claude turn. The dominant case is no-op
(`.claude/.ship-armed` absent). Each gate exits silently on failure so
unarmed turns stay under 100ms:

| # | Gate | Behaviour | Source |
|---|---|---|---|
| 1 | armed file exists | no file → `exit 0` | [`stop-ship.sh:39-41`](../scripts/claude-hooks/stop-ship.sh) |
| 2 | armed file parses | malformed JSON → silent disarm | [`stop-ship.sh:43-69`](../scripts/claude-hooks/stop-ship.sh) |
| 3 | not expired | past TTL → silent disarm | [`stop-ship.sh:71-81`](../scripts/claude-hooks/stop-ship.sh) |
| 4 | branch matches arm | switched branch → silent disarm | [`stop-ship.sh:83-91`](../scripts/claude-hooks/stop-ship.sh) |
| 5 | not on protected branch | main/master/develop/HEAD/release/* → **hard abort** (tier-3 firewall) | [`stop-ship.sh:93-98`](../scripts/claude-hooks/stop-ship.sh) |
| 6 | has work to ship | clean tree + no unpushed commits → silent exit | [`stop-ship.sh:100-108`](../scripts/claude-hooks/stop-ship.sh) |
| 7 | no git transition in progress | merge / rebase / cherry-pick / revert detected → silent exit | [`stop-ship.sh:110-119`](../scripts/claude-hooks/stop-ship.sh) |
| 8 | no live pid | previous run still alive → silent exit | [`stop-ship.sh:121-131`](../scripts/claude-hooks/stop-ship.sh) |

The "silent" disposition matters: a contributor who arms once and then
keeps working on unrelated branches doesn't accidentally trigger a ship
— and doesn't get warned, either, because the arm has effectively
self-cleaned.

## Stages 1–5

### Stage 1 — commit ([`stop-ship.sh:183-279`](../scripts/claude-hooks/stop-ship.sh))

1. **Filter private paths** out of the staging candidate set:
   `data/files/`, `data/data_list.{csv,xlsx}`, `eval/*.local.yaml`,
   `reports/real*/`. Pre-commit hook (`.githooks/pre-commit`) is the
   second-line gate; this filter just prevents proposing them.
2. **Multi-agent lock check** via
   [`_ship_lock_check.py`](../scripts/claude-hooks/_ship_lock_check.py).
   Cross-owner edits abort unless `CROSS_OWNER=ack`.
3. **Tier-7 heterogeneous-prefix gate** — see [Stacked-PR discipline](#stacked-pr-discipline-tier-7).
4. Run `bash scripts/test.sh`; cache the summary at
   `/tmp/ship-test-summary.txt` for PR body §4.
5. `git add` each surviving file; commit with a generated subject
   `<type>: <issue title> (#<N>)`, body containing `Closes #<N>` and
   the Co-Authored-By footer.

### Stage 2 — push ([`stop-ship.sh:285-297`](../scripts/claude-hooks/stop-ship.sh))

Runs `python3 scripts/check_branch_and_issue.py --branch <X> --check-issue`
(ADR 0007 + issue-exists check), then `git push` (with `-u` if no
upstream yet).

### Stage 3 — PR create ([`stop-ship.sh:303-346`](../scripts/claude-hooks/stop-ship.sh))

Idempotent: reuses an existing PR if one already targets the head
branch. Otherwise calls
[`_ship_pr_body.py`](../scripts/claude-hooks/_ship_pr_body.py) to
generate the body (template §1–§7, including the §5b cascade below),
then `gh pr create --base main --head <branch> --title ... --body-file ...`
(plus `--draft` if `DRAFT=true`). The PR title is the squash-merge
commit subject, so the merged commit on `main` lands with the title as
the first line.

### Stage 4 — CI wait ([`stop-ship.sh:352-368`](../scripts/claude-hooks/stop-ship.sh))

`timeout 1800 gh pr checks <N> --watch --interval 30`. On timeout
(rc 124): post a PR comment and abort, **leaving the PR open**. On any
non-zero rc: comment + abort. The pipeline never merges on red.

### Stage 5 — squash-merge ([`stop-ship.sh:374-424`](../scripts/claude-hooks/stop-ship.sh))

`gh pr merge <N> --squash --admin --delete-branch`. Verifies the
post-merge state is `MERGED` (otherwise leaves the arm file in place
for inspection). Then `git checkout main && git pull --ff-only`,
delete the local branch, log a `S5_OK` line to
`.claude/.ship-history.log`, remove the arm file.

**Worktree auto-cleanup (issue #520):** if the pipeline ran from a
linked worktree (i.e. `git rev-parse --git-dir` contains `/worktrees/`),
Stage 5 calls `git worktree remove --force <path>` after disarming.
This prevents merged worktrees from accumulating and inflating the
per-session base-load cost. Failure is non-blocking — a warning is
logged and the caller must clean up manually (`git worktree prune`).

## Stacked-PR discipline (tier 7)

The "one PR, one concern" rule from [`CLAUDE.md`](../CLAUDE.md) is
mechanically enforced in Stage 1 by counting unique commit prefixes on
the branch:

```bash
# scripts/claude-hooks/stop-ship.sh:221-227
if [[ "$ARM_STACKED" != "ack" ]]; then
  local prefixes
  prefixes=$(git log "@{upstream}..HEAD" --format=%s 2>/dev/null | \
             sed -E 's/^([a-z]+)(\(.*\))?:.*/\1/' | sort -u | wc -l | tr -d ' ')
  if [[ "${prefixes:-0}" -gt 1 ]]; then
    abort_disarm "s1" "heterogeneous commit prefixes (one PR per concern); bypass with STACKED=ack"
  fi
fi
```

If the branch carries commits with ≥2 distinct conventional prefixes
(e.g. one `feat:` and one `fix:`), the pipeline refuses. The bypass is
explicit and audited:

```
make ship-arm STACKED=ack
```

When `STACKED=ack` belongs in the cycle:

- **Legitimate stacked work.** A downstream fix or follow-up depends on
  an upstream feature that hasn't merged yet; rebasing the fix onto
  `main` would either be impossible or churn the diff. Example:
  commit `127a9a1` (`feat(eval): close ADR 0019 with BGE-M3 Phase 1.3
  measurement + ADR 0021 (#392)`) bundled an `eval` measurement closure
  *and* a new ADR — one logical "close out ADR 0019" concern, two
  prefixes.
- **Two-issue closure.** A single PR legitimately closes more than one
  related issue and the commit history reflects that.

When `STACKED=ack` is **wrong**:

- Mid-review "while I'm here" cleanups. Open a follow-up issue + branch.
- Unrelated typo + feature. Split into two PRs (cheap).
- Pre-emptive bundling because you'd rather not push twice. The tier-7
  gate exists precisely to flag this.

The bypass is logged in `.claude/.ship-armed` and printed by
`make ship-status`, so the audit trail survives the cycle.

## §5b real-data delta cascade

[`_ship_pr_body.py:126-162`](../scripts/claude-hooks/_ship_pr_body.py)
`render_5b()` decides what to write under "### 5b. Real-data delta" in
the PR body. The decision tree:

| Condition | Output |
|---|---|
| No load-bearing path changed | `No behavior change in retrieval / verifier path. (no load-bearing path changed)` |
| `REAL_EVAL=skip` | same escape, suffixed `(REAL_EVAL=skip)` |
| Real-eval not runnable (private `data/files/` or `eval/real_config.local.yaml` absent) | escape with reason |
| `REAL_EVAL=async` | escape + `<!-- real-eval-pending -->` |
| Cache valid (no load-bearing diff since `provenance.git_commit`) | `make real-eval-delta` (120 s timeout) |
| Cache stale | `make real-eval` (1800 s) → `make real-eval-delta` |

The PR body is round-trip-validated against the CI gate
(`scripts/check_branch_and_issue.py --check-5b` regexes:
`FIVE_B_TABLE_RE`, `FIVE_B_ESCAPE_RE`); the generator refuses to emit a
body the CI would reject ([`_ship_pr_body.py:266-278`](../scripts/claude-hooks/_ship_pr_body.py)).

Load-bearing paths are defined once in
[`scripts/_governance.py`](../scripts/_governance.py) `LOAD_BEARING_PATHS`
— the single source of truth referenced from `CLAUDE.md`,
`.githooks/pre-push`, the pre-commit hook, and `_ship_pr_body.py`.

## Squash-merge & multi-concern tracking

Stage 5 uses `gh pr merge --squash --admin --delete-branch`, so the
final commit on `main` is one squashed commit whose subject is the PR
title and whose body carries the original `Closes #<N>` markers from
each constituent commit.

If a PR legitimately closes more than one issue (typical with
`STACKED=ack` cycles), put each closure on its own line in the PR body:

```
Closes #N
Closes #M
Closes #L
```

GitHub will auto-close all three when the squash lands.

For ADR-introducing commits, prefer "issue + ADR" in the same PR rather
than two separate PRs — the cluster narrative in
[`docs/adr/README.md`](../adr/README.md) treats an ADR + its enabling
code change as one decision.

## Failure modes & safety nets

| Failure | Stage | Behaviour |
|---|---|---|
| Tier-3 firewall hit (ship from main/master/develop/release/*) | Gate 0 | hard abort, arm preserved for inspection |
| Pre-commit hook block | Stage 1 | `git commit` non-zero → abort with stage-1 log line |
| Multi-agent lock violation | Stage 1 | abort unless `CROSS_OWNER=ack` |
| Tier-7 heterogeneous prefix | Stage 1 | abort unless `STACKED=ack` |
| Branch convention or missing issue | Stage 2 | abort before push |
| §5b validation fail (load-bearing changed, body lacks delta) | Stage 3 | `_ship_pr_body.py` exits 1, Stage 3 aborts |
| CI red or timeout | Stage 4 | post a PR comment, abort, PR stays open |
| `gh pr merge` rejected (admin merge unavailable, branch protections) | Stage 5 | abort, PR stays open |
| Post-merge state ≠ `MERGED` | Stage 5 | leave arm file in place, exit 1 |

The arm file's `dry_run: 1` mode is the recommended way to validate a
new pipeline configuration end-to-end without touching `origin`. All
mutating commands echo to `.claude/.ship-dryrun.log`.

## Related

- [`CLAUDE.md`](../CLAUDE.md) — "Frequently used commands", "Core principles" (one PR per concern), Prohibited list.
- [`docs/engineering-governance.md`](../engineering-governance.md) — navigation hub.
- [`docs/multi-agent-ownership.md`](../multi-agent-ownership.md) — owner lock map consumed by Stage 1.
- [ADR 0007](../adr/0007-issue-linked-branch-naming.md) — branch convention enforced in Gate 0 / Stage 2.
- [`.github/pull_request_template.md`](../.github/pull_request_template.md) — the template `_ship_pr_body.py` fills in.
- [`scripts/_governance.py`](../scripts/_governance.py) — load-bearing SSoT.
