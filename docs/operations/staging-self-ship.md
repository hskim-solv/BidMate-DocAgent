# Staging self-ship lane — operator runbook (P1, ADR 0088)

`make 시작-ship` is an **opt-in** lane that lets the autonomous loop merge its own
work into the long-lived `autopilot/integration` branch (never `main`, never
force-push). It composes the byte-identical `make 시작` loop (`EXECUTE_SHIP=0`,
unchanged) with the isolated `scripts/_staging_ship.py` module as a post step;
`scripts/agent_loop.py` is untouched.

## Enforcement model (read this first)

The in-process guards in `scripts/_staging_ship.py` (force-push / staging-boundary /
data-boundary / kill-switch / cap) are a **best-effort 1차 fast-fail only**. A
workspace-write runner can bypass them. The **authority** is external, in a domain
the loop has no permission over:

1. GitHub **branch protection** on `autopilot/integration` with the
   `staging-self-ship-guard` workflow as a **required status check**.
2. A **permission-separated merge token** that cannot bypass branch protection.

Until both are verified, `scripts/_staging_ship.py` **fails closed**
(`blocked-on-user`) and refuses to ship. It does NOT fake gate 3.

## Prerequisites — operator GitHub-admin actions (blocked-on-user)

> ⚠️ These steps require GitHub admin rights and a token/App creation. They are NOT
> performed by the agent/ralph (the agent has no authority to provision protected
> branches or scoped tokens). Run them yourself.

### 1. Create the protected integration branch
```bash
# create the long-lived integration branch from main
git switch -c autopilot/integration origin/main
git push -u origin autopilot/integration

# branch protection: required check + force-push deny + no admin bypass
gh api -X PUT repos/:owner/:repo/branches/autopilot/integration/protection \
  -f 'required_status_checks[strict]=true' \
  -f 'required_status_checks[checks][][context]=staging-self-ship-guard' \
  -F 'enforce_admins=true' \
  -F 'required_pull_request_reviews=null' \
  -F 'restrictions=null' \
  -F 'allow_force_pushes=false' \
  -F 'allow_deletions=false'
```

### 2. Provision a permission-separated merge token
- Create a **fine-grained PAT** (or GitHub App installation token) scoped to this repo
  with **Contents: read/write + Pull requests: read/write** but **NOT** Administration.
  It must be unable to edit branch protection.
- Store it as the loop's merge credential (out of the loop's writable workspace).

### 3. Flip the verification flags only after gate 3 passes
```bash
export BIDMATE_SHIP_PROTECTION_VERIFIED=1
export BIDMATE_SHIP_TOKEN_SEPARATED=1
```

## Gate 3 — live e2e (mock不可, run once after setup)

These two adversarial checks prove the external authority is real. They cannot be
mocked — they exercise actual GitHub server state.

1. **Guard-file change is blocked.** Open a PR into `autopilot/integration` that edits
   `scripts/_staging_ship.py` *without* the `[constitutional-change-ack]` marker in the
   body. Expected: the `staging-self-ship-guard` required check **fails** and the
   merge is blocked.
2. **Merge token cannot disable protection.** With the permission-separated token:
   ```bash
   GH_TOKEN=$MERGE_TOKEN gh api -X PATCH \
     repos/:owner/:repo/branches/autopilot/integration/protection \
     -F 'allow_force_pushes=true'
   ```
   Expected: **HTTP 403**.

Only when both behave as expected is the external enforcement verified.

## Running the lane
```bash
# fails closed (blocked-on-user, exit 2) until prerequisites + gate 3 are done:
make 시작-ship

# kill-switch (engages immediately): create the file OR set the env var
touch .omc/state/KILL                 # file form
export BIDMATE_SHIP_KILL_SWITCH=1     # env form
```
`make 시작-ship` also fail-closes if `make ship-arm` is armed (`.claude/.ship-armed`
present) — the two ship authorities are mutually exclusive (ADR 0088 §7).

## What P1 (ralph) built vs what is blocked-on-user

| Built locally (this PR set) | Blocked-on-user (you) |
|---|---|
| `_ship_payload_guard.py` free-text data-boundary scanner + tests | Create `autopilot/integration` + branch protection |
| `_staging_ship.py` guards + breakers (T1/T4) + lane (CI-green gate, fail-closed) + tests | Provision permission-separated merge token |
| `시작-ship` Makefile target (시작 byte-identical) | Gate-3 live e2e (the two checks above) |
| `staging-self-ship-guard` CI workflow (required-check candidate) | Flip `BIDMATE_SHIP_*` verification flags |
| this runbook | |

The lane intentionally refuses to ship until you complete the GitHub-admin steps —
that refusal is the correct behaviour, not a bug.

## Scope boundary

This is **P1 only**: a single staging-ship demo with external enforcement. The more
aggressive capabilities from the spec (unlimited self-modify / option 3, main
auto-promotion, infinite mode, task auto-generation, multi-worker arbitration) are
P2/P3 and each requires its own ADR (G1-G4) and explicit approval. See the
consensus plan `.omc/plans/make-sijak-full-automation-consensus.md` (local planning
artifact, gitignored — not committed).
