# Staging self-ship lane — operator runbook (P2.0 D-minus, ADR 0088 + ADR 0090)

`make 시작-ship` is an **opt-in** lane that composes the byte-identical `make 시작`
loop (`EXECUTE_SHIP=0`, unchanged) with the isolated `scripts/_staging_ship.py`
module as a post step. Its long-term goal is to let the autonomous loop merge its
own work into the long-lived `autopilot/integration` branch. **As of P2.0 D-minus the
lane verifies enforcement prerequisites and refuses to merge — autonomous merge is
P2.2.**

**P2.0 D-minus change (ADR 0090):** This PR makes the enforcement model real:

- P1 env-trust flags (`BIDMATE_SHIP_PROTECTION_VERIFIED` / `BIDMATE_SHIP_TOKEN_SEPARATED`)
  are **removed** — a workspace-write runner inheriting the env could spoof them
  (constitutional-invariant bypass).
- `protection_verified` is now a **live `gh api` query** (specific
  `staging-self-ship-guard` required check + `allow_force_pushes.enabled=false` +
  `enforce_admins.enabled=true`, slashed branch URL-encoded, bound to repo_root,
  fail-closed on missing gh / timeout / error).
- All `BIDMATE_SHIP_*` env vars are stripped from every runner subprocess lane via
  a **single-source `scripts/_ship_env.py`** (deny-by-prefix, all 6 lanes).
  `make 시작-ship` `env -u`'s the secrets before the loop sub-make and pre-checks
  the kill-switch.
- `_staging_ship.py` defines the **manifest CONTRACT functions**
  (`write_ship_manifest` / `read_ship_manifest` / `archive_ship_manifest`,
  unit-tested). `main()` reads a manifest **if present** (idempotent — not
  consumed), or accepts `--source` for manual exercise. **`agent_loop.py` does NOT
  auto-emit a manifest in this PR** — the loop runs with `EXECUTE_SHIP=0` so no
  change is committed; `source_sha=HEAD` would be stale/meaningless. Manifest
  emission is deferred to P2.2 where HEAD-binding is real.
- `_staging_ship.py main()` is a **verify-and-refuse pre-flight harness**: reads
  the manifest (if present), runs the constitutional guards + live protection check,
  then **always returns rc 2 (blocked-on-user)**. `open_pr`/`merge` are explicit
  P2.2-deferred stubs that raise if called.

The lane always refusing to merge is **correct D-minus behavior** — not a bug.

## Enforcement model (read this first)

The in-process guards in `scripts/_staging_ship.py` (force-push / staging-boundary /
data-boundary / kill-switch) are a **best-effort 1차 fast-fail only**. A
workspace-write runner can bypass them. The **authority** is external, in a domain
the loop has no permission over:

1. GitHub **branch protection** on `autopilot/integration` with the
   `staging-self-ship-guard` workflow as a **required status check**.
2. (P2.2) A **permission-separated merge token** (`BIDMATE_SHIP_MERGE_TOKEN`) that
   cannot bypass branch protection — stored **out of the runner write domain**.

`protection_verified` performs a **live `gh api` query** against
`repos/:owner/:repo/branches/autopilot%2Fintegration/protection`. It checks that the
`staging-self-ship-guard` required check is present **and** force-push is denied. It
is not sufficient for any other required check to exist — this specific guard must
be listed. There is no env flag to override this. If the query fails or returns
insufficient protection, `_staging_ship.py` exits with code 2 (blocked-on-user).

All `BIDMATE_SHIP_*` env vars are **stripped from all runner subprocess lanes**
(claude write + 2 codex patch write lanes + 2 read/review turn lanes + omc lane)
via deny-by-prefix, single-source in `scripts/_ship_env.py`. Runner children cannot
read or spoof ship secrets (ADR 0090).

## Constitutional-change enforcement = CODEOWNERS review (ADR 0091)

Changes to the constitutional ship-lane files are gated by a **CODEOWNERS code-owner
review**, NOT by a PR-body marker. The old author-writable `[constitutional-change-ack]`
marker was self-satisfiable by the autonomous loop (the PR author can write its own
PR body), so it was never a real external gate — the same ouroboros class as the
env-trust flags ADR 0090 removed. ADR 0091 supersedes that marker mechanism.

The trusted signal is now: a CODEOWNERS code owner who is **not** the PR author must
submit an **APPROVED** review. GitHub blocks a PR author from approving their own PR,
so the autonomous loop (= the PR author) physically cannot produce this signal.

- `.github/CODEOWNERS` maps the protected paths to the owner.
- `scripts/check_constitutional_review.py` is the required-check logic: it fetches the
  PR's changed files / author / approved reviewers via `gh api` and fails (exit 1)
  unless a non-author code owner has approved. Its `PROTECTED_PATHS` set is kept in
  sync with `.github/CODEOWNERS` by a parity test (`tests/test_constitutional_review.py`).
- Protected set (expanded in ADR 0091): `scripts/_staging_ship.py`,
  `scripts/_ship_env.py`, `scripts/_ship_payload_guard.py`, `scripts/_governance.py`,
  `.github/workflows/staging-self-ship-guard.yml`, `.github/CODEOWNERS` itself, and
  `.githooks/pre-commit`. (`scripts/agent_loop.py` is deliberately excluded — too
  frequently edited.)

**Operator blocked-on-user step:** enable branch protection **"Require review from
Code Owners"** on the relevant branch(es) (`main` and `autopilot/integration`, plus
any P2.2 integration branch). Without it, GitHub will not enforce the code-owner
review and the gate's first line of authority is missing. This is a GitHub admin
action the agent cannot perform.

## Prerequisites — operator GitHub-admin actions (blocked-on-user)

> These steps require GitHub admin rights. They are NOT performed by the agent
> (the agent has no authority to provision protected branches). The protection setup
> below is what `protection_verified` checks — without it the lane always exits 2.

### 1. Create the protected integration branch

```bash
# create the long-lived integration branch from main
git switch -c autopilot/integration origin/main
git push -u origin autopilot/integration

# branch protection: staging-self-ship-guard required check + force-push deny
#
# WARNING (ADR 0091): required_pull_request_reviews MUST include
# require_code_owner_reviews=true. Setting required_pull_request_reviews=null
# would SILENTLY DISABLE the CODEOWNERS gate (the constitutional-change guard
# that blocks the autonomous loop from self-approving guard-file PRs).
# Always pass the full required_pull_request_reviews object as shown below.
gh api -X PUT repos/:owner/:repo/branches/autopilot%2Fintegration/protection \
  -f 'required_status_checks[strict]=true' \
  -f 'required_status_checks[checks][][context]=staging-self-ship-guard' \
  -F 'enforce_admins=true' \
  -F 'required_pull_request_reviews[require_code_owner_reviews]=true' \
  -F 'required_pull_request_reviews[dismiss_stale_reviews]=false' \
  -F 'required_pull_request_reviews[required_approving_review_count]=1' \
  -F 'restrictions=null' \
  -F 'allow_force_pushes=false' \
  -F 'allow_deletions=false'
```

### 2. P2.2: permission-separated merge token and cap store (deferred)

These are **not needed for D-minus** and are deferred to P2.2:

- `BIDMATE_SHIP_MERGE_TOKEN` — a fine-grained PAT (or GitHub App installation
  token) scoped to this repo with **Contents: read/write + Pull requests:
  read/write** but **NOT** Administration. It must be unable to edit branch
  protection.
- `BIDMATE_SHIP_CAP_STORE` — path to a T4 self-immutable cap store file (outside
  the runner write domain) for cross-worktree daily-cap transactionality.

## Ship manifest flow (P2.0 D-minus)

`make 시작-ship` runs the byte-identical `make 시작` loop (secrets stripped via
`env -u`, kill-switch pre-checked), then invokes `_staging_ship.py` as a post step.

**No manifest auto-emission in this PR.** `agent_loop.py` does NOT write
`ship_manifest.json` — the loop runs with `EXECUTE_SHIP=0` so the gated change is
never committed; `source_sha=HEAD` would be stale. The manifest emission seam
(`_maybe_write_ship_manifest`) is deferred to P2.2 where a real commit exists and
HEAD-binding is meaningful.

The manifest **contract functions** are defined and unit-tested in `_staging_ship.py`:
- `write_ship_manifest(state_dir, ...)` — writes `<state-dir>/ship_manifest.json`
- `read_ship_manifest(state_dir)` — **idempotent read** (does not consume/archive)
- `archive_ship_manifest(state_dir)` — moves to `.consumed` (called by P2.2 merge
  success path)

`_staging_ship.py main()` reads the manifest **if it is already present**
(idempotent), or uses `--source` if provided by the operator, then runs the
constitutional guards + live protection check, and exits rc 2.

```bash
# manifest path (contract, written by P2.2 emission seam; operator-placed for testing):
# $(ACTIVE_SHIP_STATE_DIR)/ship_manifest.json

# to manually exercise the live protection-verify harness today:
python scripts/_staging_ship.py --source <branch> --state-dir reports/agent_loop/active
```

## Gate 3 — live e2e (D-minus: verify external enforcement; P2.2: verify merge)

After operator branch-protection setup, these two adversarial checks prove the
external authority is real. They cannot be mocked — they exercise actual GitHub
server state.

1. **Guard-file change is blocked.** Open a PR into `autopilot/integration` that
   edits `scripts/_staging_ship.py` *without* an APPROVED review from a CODEOWNERS
   code owner who is not the PR author. Expected: the `staging-self-ship-guard`
   required check **fails** and the merge is blocked (see "Constitutional-change
   enforcement" below — ADR 0091).
2. **Merge token cannot disable protection.** (P2.2, after token provisioning)
   ```bash
   GH_TOKEN=$BIDMATE_SHIP_MERGE_TOKEN gh api -X PATCH \
     repos/:owner/:repo/branches/autopilot%2Fintegration/protection \
     -F 'allow_force_pushes=true'
   ```
   Expected: **HTTP 403**.

Gate 3 check 1 verifies protection is real. Check 2 is deferred to P2.2 (requires
the permission-separated token to exist).

## Running the lane

```bash
# fails closed (blocked-on-user, exit 2) — correct D-minus behavior:
make 시작-ship

# kill-switch (engages immediately): create the file OR set the env var.
# The file form MUST live under the lane's state dir (ACTIVE_SHIP_STATE_DIR),
# which is what `make 시작-ship` passes as --state-dir — NOT .omc/state.
touch reports/agent_loop/active/KILL   # file form (= $(ACTIVE_SHIP_STATE_DIR)/KILL)
export BIDMATE_SHIP_KILL_SWITCH=1      # env form
```

`make 시작-ship` also fail-closes if `make ship-arm` is armed (`.claude/.ship-armed`
present) — the two ship authorities are mutually exclusive (ADR 0088 §7).

The lane refuses to merge until `protection_verified` passes the live `gh api` query.
This is correct behavior — not a bug. Autonomous merge will be unblocked in P2.2
when the merge token, cap store, and serialized promotion logic are implemented.

## What P2.0 D-minus built vs blocked-on-user / deferred

| Built (P2.0 D-minus) | Blocked-on-user (you) | Deferred to P2.2 |
|---|---|---|
| `ship_manifest.json` **contract functions** (`write_ship_manifest` / `read_ship_manifest` / `archive_ship_manifest` in `_staging_ship.py`, unit-tested) | Create `autopilot/integration` + branch protection with `staging-self-ship-guard` required check | **`agent_loop.py` manifest emission seam** (`_maybe_write_ship_manifest`) — deferred because `EXECUTE_SHIP=0` makes `source_sha=HEAD` stale |
| Live `protection_verified` — real `gh api` query checking `staging-self-ship-guard` required check + `allow_force_pushes=false` + `enforce_admins=true`, URL-encoded slashed branch, fail-closed; env-trust flags removed | Gate-3 live e2e check 1 (guard-file PR → required check fail) | Live `gh pr create` / `gh pr merge` (open_pr/merge are P2.2-deferred stubs) |
| `BIDMATE_SHIP_*` env isolation — single-source `scripts/_ship_env.py`, deny-by-prefix across all 6 runner subprocess lanes; `make 시작-ship` strips secrets before loop sub-make | ADR 0090 Status `proposed → accepted` | Permission-separated merge token (`BIDMATE_SHIP_MERGE_TOKEN`) + ambient-credential stripping in `merge()` |
| `main()` verify-and-refuse pre-flight harness — reads manifest if present (idempotent), accepts `--source`; always rc 2 | | T4 self-immutable cap store (`BIDMATE_SHIP_CAP_STORE`) + cross-worktree shared lock + daily-cap transactionality |
| ADR 0090 + this updated runbook | | `source_sha` → PR head binding (`--match-head-commit`) + serialized promotion |
| | | Bounded check poll (`BIDMATE_SHIP_CHECK_ATTEMPTS`/`BIDMATE_SHIP_CHECK_INTERVAL_SECONDS`) |
| | | Gate-3 live e2e check 2 (merge token PUT protection → 403) |
| | | P2.1: add `_ship_env.py` + manifest emission seam to `SELF_IMMUTABLE_PATHS` |

## Scope boundary

**P2.0 D-minus** is the enforcement model + manifest contract definition layer.
The loop manifest emission seam and autonomous merge orchestration are P2.2.
Capabilities beyond that (unlimited self-modify / option 3, main auto-promotion,
task auto-generation) are P2.1–P3 and each requires its own ADR and explicit
approval.

`_ship_env.py` and the manifest emission seam should be added to
`SELF_IMMUTABLE_PATHS` in P2.1 (currently deferred alongside the full
`SELF_IMMUTABLE_PATHS` implementation).
