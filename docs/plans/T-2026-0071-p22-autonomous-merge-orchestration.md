# Plan: T-2026-0071 (P2.2) Staging self-ship autonomous merge orchestration

- Status: blocked
- Owner role: Planner (this doc) → Implementer → Security Reviewer → Deep Reviewer → Reviewer
- Related task: `tasks/queue.md::T-2026-0071`
- Related issue / PR: closed issue [#1703](https://github.com/hskim-solv/BidMate-DocAgent/issues/1703) (P2.2 SSoT); this plan PR closes [#1707](https://github.com/hskim-solv/BidMate-DocAgent/issues/1707); maintenance-gate refresh [#2152](https://github.com/hskim-solv/BidMate-DocAgent/issues/2152); builds on PR #1698 (D-minus), #1700 (codex-gate), #1702 (AR3 CODEOWNERS)
- Related ADR: [0088](../adr/0088-opt-in-staging-self-ship-external-enforcement.md), [0090](../adr/0090-activate-staging-self-ship-lane-live-enforcement.md), [0091](../adr/0091-constitutional-guard-codeowners-trusted-signal.md) — all currently `proposed`. P2.2 needs **1 new ADR + 1 ADR 0090 amendment** (see Architecture Impact).
- Created: 2026-06-01
- Last updated: 2026-06-04

> Current status (2026-06-04): this plan is **not** an automatic
> implementation-ready lane. Issue #1703 and the P2.2 follow-up set are closed,
> but remaining work is gated on maintainer decisions, ADR reservation, and an
> operator/live integration window. Resume only as a single-writer lane after
> those gates are explicitly satisfied.

> NOTE: ADR/issue numbers for the implementation PRs are NOT reserved by this plan. Reserve at ship time (`ls docs/adr/` + `gh pr list --search "ADR" --state open`). Inside this doc they appear as `ADR 00XX (reserve)`.

## Problem Statement

P2.0 D-minus (ADR 0090) landed the **enforcement model + manifest contract**, but the lane `_staging_ship.py main()` always returns `rc 2 (blocked-on-user)`: `_RealGitOps.open_pr` / `merge` are honest stubs that `raise EnforcementNotVerified`, `required_checks_all_success` hard-returns `False`, and `agent_loop.py` never emits a manifest. The autonomous loop therefore cannot merge its own gated work into `autopilot/integration` — the entire point of the lane. The remaining work lives only in transcript + issue #1703; without a plan doc the next session re-discovers the seam boundaries from scratch.

Reviewer-visible consequence if not done: the staging self-ship lane stays a permanently-refusing pre-flight harness, and three ADRs (0088/0090/0091) cannot move `proposed → accepted` because their P2.2 verification surfaces (live merge, token 403, cap+1 halt) never exist.

## Current Behavior

State after D-minus (verified by reading source on this branch):

- **`scripts/_staging_ship.py` (669 lines)** holds the full design already:
  - `StagingShipLane.ship()` (lines 368-402) is the **complete orchestration sequence**: ship-arm mutex → kill-switch → staging-target assert → force-push assert → data-boundary payload guard → `protection_verified` (LIVE) → daily-cap → `open_pr` → `required_checks_all_success` → `merge` → `record_merge`. Only the last three `GitOps` methods are stubbed.
  - `_RealGitOps.protection_verified` (456-530) is **live and complete**: queries `gh api .../branches/<enc>/protection`, requires `staging-self-ship-guard` in `required_status_checks.contexts|checks`, `strict is True`, `allow_force_pushes.enabled is False`, `enforce_admins.enabled is True`. Drops ambient `GH_TOKEN`/`GITHUB_TOKEN`/`GH_REPO` via `_GH_AMBIENT_DROP_KEYS`, binds `cwd=repo_root`, fail-closed on every subprocess error.
  - `_RealGitOps.open_pr` (532-536) and `merge` (541-545) `raise EnforcementNotVerified("... deferred to P2.2 ...")`; `required_checks_all_success` (538-539) returns `False`.
  - Manifest contract done + unit-tested: `write_ship_manifest` (signature includes `source_sha`, lines 179-196), `read_ship_manifest` (idempotent, 244-258), `archive_ship_manifest`. `_SHA_RE` enforces 40-char lowercase hex on `source_sha` (212, 245-247). `--match-head-commit` is named in the contract comment (188-190) but not yet used.
  - `DailyMergeCapCounter` (307-326) + `ImmutableCounterStore` Protocol (292-305) exist as **in-memory contracts only**. `__post_init__` refuses any store whose `loop_writable` is truthy. No file-backed implementation, no cross-worktree lock.
  - `BoundedFailureCounter` (270-289) is the bounded-lane T1 (limit 3).
  - `main()` (548-669) reads the manifest if present (else `--source`), runs cheap guards, runs the live protection pre-flight (always, even with no work — issue #1697 Fix 2), then **always returns 2**.
- **`scripts/agent_loop.py` (~19k lines)**: `local-gate-complete` is set at **line 10747** (`cycle["completion_decision"] = "local-gate-complete"`). There is **no `_maybe_write_ship_manifest`** anywhere (ADR 0090 verification relies on that grep being empty). `strip_ship_secret_env` is already imported (line 36) and applied across all write/read/omc lanes (395, 13886, 14423, 14460, 15882 + the two turn modules).
- **`scripts/_ship_env.py`**: single 14-line leaf, `strip_ship_secret_env` deny-by-prefix `BIDMATE_SHIP_`. Already imported by `agent_loop.py`, `agent_loop_claude_turn.py`, `agent_loop_codex_turn.py`.
- **`scripts/_governance.py`**: has `LOAD_BEARING_PATHS` (11 entries) + `THRESHOLDS`. **`SELF_IMMUTABLE_PATHS` does not exist in code** — it is only named in ADR 0090 / runbook prose.
- **`scripts/run_codex_adversarial_precommit.py`** line 140: comment says the canonical `_ship_env.strip_ship_secret_env` helper lands on main; the inline `sanitized_env()` strip from #1700 is the AR1-dedup target (separate follow-up, not in this stack).
- **`scripts/check_constitutional_review.py`** line 46: `PROTECTED_PATHS` already lists `scripts/_ship_env.py`. (CODEOWNERS parity test guards this.)
- **`make 시작-ship`** runs the byte-identical `make 시작` loop with secrets `env -u`'d, then calls `_staging_ship.py --manifest-dir "$(ACTIVE_SHIP_STATE_DIR)"` as a post-step. No `BIDMATE_SHIP_MANIFEST_DIR` injected into the loop sub-make (emission deferred).

## Desired Behavior

Smallest useful end state, observable by command/artifact:

1. With operator branch-protection live + `BIDMATE_SHIP_MERGE_TOKEN` + `BIDMATE_SHIP_CAP_STORE` set, `make 시작-ship` after a `local-gate-complete` cycle: writes a manifest bound to the real committed `source_sha`, opens (or reuses) a PR into `autopilot/integration` with head pinned to that SHA, polls required checks within a bounded budget, and merges via the permission-separated token — recording the merge in a self-immutable, cross-worktree-locked daily cap store.
2. Without those prerequisites, the lane stays `rc 2` and fakes nothing (D-minus behavior preserved as the fail-closed default).
3. Gate-3 live e2e both pass: (1) guard-file PR without CODEOWNERS approval → required check fail; (2) merge-token `PATCH protection` → HTTP 403.
4. `SELF_IMMUTABLE_PATHS` exists in `_governance.py`, contains `_ship_env.py` + the manifest emission seam + cap-store path, and the lane refuses to ship any PR whose diff touches those paths.

## Constraints

- Scope constraints: P2.2 only. Explicitly NOT main auto-promotion (P3), unlimited self-modify / option 3 (P2.1-P3, separate ADRs G1-G4), task auto-generation (P3). The 3 small follow-ups in #1703 (AR1 dedup, codex 8→2-3 cascade, codex pre-commit re-enable) are tracked separately — **not** part of this plan's PR stack (cascade needs its own ADR 0066 change; re-enable is an operator toggle).
- Architecture constraints: 2-process privilege split is invariant — `agent_loop.py` must NOT call `ship()`/`open_pr`/`merge` directly (it only emits a manifest); the merge token must never enter the runner write domain (`BIDMATE_SHIP_*` stays stripped from all 6 runner lanes). Authority stays external (branch protection + permission-separated token); in-process guards remain 1차 fast-fail only.
- Compatibility constraints: `make 시작` (no args) byte-identical (ADR 0085/0088). ADR 0001 baseline untouched. Manifest `schema_version` + `read/write/archive` signatures are a frozen contract (ADR 0090) — extend additively, do not break. `source_sha` stays 40-char hex.
- Eval/privacy constraints: Surface = **none** (governance/automation, not retrieval/eval). PR body + commits + any external notification must carry numbers/counts allowlist only — no raw private RFP text (ADR 0005/0088 §5). `assert_no_raw_payload` already guards title/body.
- Tooling/CI constraints: `staging-self-ship-guard.yml` required check + CODEOWNERS review gate all PRs touching constitutional paths (`_staging_ship.py`, `_ship_env.py`, `_ship_payload_guard.py`, `_governance.py`, the workflow, CODEOWNERS, `.githooks/pre-commit`). **Every PR in this stack that touches `_staging_ship.py` will itself require a non-author CODEOWNERS approval** — plan the review lane accordingly. `bash scripts/test.sh` must pass. Behavior change ⇒ regression test in `tests/`.
- Non-goals: force-push / history-rewrite (permanently forbidden, revert-only rollback); merging into `main`; mocking Gate-3 live checks; promoting `agent_loop.py` to LOAD_BEARING (ADR 0087 d / 0091 deliberately exclude it).

## Architecture Impact

- Affected modules or docs: `scripts/_staging_ship.py` (live ops, cap store, poll, idempotency, serialization), `scripts/agent_loop.py` (manifest emission seam only), `scripts/_governance.py` (new `SELF_IMMUTABLE_PATHS`), `Makefile` (`시작-ship` injects `BIDMATE_SHIP_MANIFEST_DIR` into the loop sub-make for emission), `docs/operations/staging-self-ship.md` (move rows from deferred→built), `tasks/queue.md` (T-2026-0071 status), `tests/`.
- Affected contracts or invariants: manifest contract (extend, don't break); `GitOps` Protocol (`open_pr`/`merge`/`required_checks_all_success` go live); `ImmutableCounterStore` (`loop_writable=False` invariant on the new file store); 2-process privilege split; external-authority model.
- Load-bearing paths: none of P2.2's files are in `LOAD_BEARING_PATHS` (that list is RAG-pipeline). But `_staging_ship.py`/`_ship_env.py`/`_governance.py`/the workflow/`.githooks/pre-commit` are in the **constitutional CODEOWNERS-protected set** (ADR 0091) — a stricter gate than load-bearing. Reviewer must treat any diff to these as security-sensitive.
- ADR required: **YES — two decision artifacts.**
  - **New ADR 00XX (reserve): permission-separated merge token + self-immutable cross-worktree cap store as a security contract.** This introduces a new credential trust boundary (`BIDMATE_SHIP_MERGE_TOKEN` ambient-strip + token-only `merge()`) and a new self-immutable measurement/safety surface (file-backed cap store + cross-worktree lock + daily-cap transactionality). Both are exactly the "new measurement surface / reviewer-relied contract" + "load-bearing security decision" ADR triggers in CLAUDE.md. ADR 0088 §6 promised T4 self-immutability but left the *store implementation* + *concurrency model* unspecified; ADR 0090 deferred them explicitly to "P2.2 별도 ADR이 필요".
  - **ADR 0090 amendment (append a `## P2.2 Resolution` / addendum section, do not rename — file-preservation rule):** records that the emission seam + live `open_pr`/`merge` + `--match-head-commit` binding + bounded poll + idempotency are now implemented, and updates the verification surface. Alternatively folded into the new ADR's "Supersession / 관계" if cleaner — decide at ship time (see Open Questions).
  - `SELF_IMMUTABLE_PATHS` introduction: covered under the same new ADR (it is the enforcement mechanism for the cap-store / seam immutability the ADR defines). No separate ADR.
  - AR4 protection-completeness: **no ADR** — it tightens an existing live check (additive assertions), not a new contract.
- Backward compatibility expectation: default `make 시작` + lane-without-prerequisites both unchanged (still `rc 2`). New behavior is gated entirely behind the merge token + cap store env + live protection.

## Affected Interfaces

- CLI/API/config: new env `BIDMATE_SHIP_MERGE_TOKEN`, `BIDMATE_SHIP_CAP_STORE`, `BIDMATE_SHIP_CHECK_ATTEMPTS`, `BIDMATE_SHIP_CHECK_INTERVAL_SECONDS`, `BIDMATE_SHIP_MANIFEST_DIR` (loop-injected). All in the `BIDMATE_SHIP_*` stripped namespace.
- Input data: `<state-dir>/ship_manifest.json` (now loop-emitted with real `source_sha`).
- Output artifacts: live PR into `autopilot/integration`; `<state-dir>/ship_manifest.json.consumed` after merge; cap-store file (counts only).
- Docs/review surfaces: `docs/operations/staging-self-ship.md` built-vs-deferred table; Gate-3 runbook steps.
- Tests/eval entrypoints: `tests/test_staging_ship*.py` (extend), new `tests/test_*_regression.py` for cap-store concurrency + idempotency.

## Data / Eval Impact

- Surface: **none** (governance/automation).
- Data boundary: no private RFP data touched; PR/commit/notification payloads = numeric/count allowlist only (ADR 0005/0088 §5). `assert_no_raw_payload` guards.
- Allowed claim: "autonomous staging merge orchestration with permission-separated token + self-immutable cap implemented; Gate-3 e2e verified."
- Disallowed claim: anything about retrieval/eval metrics; "main auto-merge"; "unlimited self-modify".
- Baseline or control affected: no (ADR 0001 untouched).
- Benchmark/eval auditor required: no. **Security Reviewer required: YES** (token trust boundary, self-immutable store, ouroboros class).

## Task Breakdown — PR stack (one concern per PR, dependency-ordered)

The 9 issue #1703 units map to **6 stacked PRs**. Stack via `gh pr create --base <parent>`; avoid `--delete-branch` on a base with open children (CLAUDE.md). Ordering principle: **maximize what is unit-testable without live merge first** (cap store + seam + token-strip all testable offline), defer the irreversible live-merge wiring + e2e to last.

Recommended safe-start order is **PR-1 and PR-2 first** (both fully offline-testable, no branch-protection dependency), then PR-3, with PR-4/5/6 gated on operator prerequisites.

> **⚠️ 2026-06-01 실측 정정 (issue #1720):** 이 "PR-1 and PR-2 first" 권고는 첫 시도에서 **둘 다 codex 적대 리뷰가 정당하게 block**했다. PR-1(manifest seam)은 no-ship 경로에서 `source_sha`를 emit하면 stale HEAD bind가 되어(codex critical, freq 5/8; runbook도 동일하게 P2.2 유보 명시) **PR-4(live merge, 실제 커밋 존재)와 함께** 구현하도록 이동한다. PR-2(cap store)는 self-immutable 우회·per-worktree 카운터·day-key rotation 우회 결함으로 **재설계**가 필요하다. 상세는 본 문서 끝 "P2.2 첫 시도 결과" 섹션 참조.

### PR-1 — `agent_loop.py` manifest emission seam + Makefile wiring (issue unit 1; ADR 0090 amendment)

> **⚠️ 2026-06-01: PR-4로 이동 (independent PR 아님).** D-minus(`EXECUTE_SHIP=0`)에서는 게이트 통과 시점에 커밋이 없어 `source_sha=HEAD`가 stale/무의미하다 — codex critical(freq 5/8) + runbook 유보 명시와 일치. seam은 실제 커밋이 생기는 live-merge 경로(PR-4)에서만 의미가 있으므로 거기서 함께 구현한다. 아래 Goal/Scope는 PR-4 구현 시 참조용으로 보존한다.

- Goal: Loop emits `<state-dir>/ship_manifest.json` bound to the real committed `source_sha` (HEAD of the gated commit) on `local-gate-complete`, only when `BIDMATE_SHIP_MANIFEST_DIR` is set (i.e. invoked from `make 시작-ship`).
- Scope: add `_maybe_write_ship_manifest(...)` in `agent_loop.py`, called from the `local-gate-complete` block (line ~10747); it calls the existing `write_ship_manifest` contract. `Makefile` `시작-ship` injects `BIDMATE_SHIP_MANIFEST_DIR=$(ACTIVE_SHIP_STATE_DIR)` into the **loop** sub-make. ADR 0090 addendum section.
- Non-Goals: no PR open, no merge, no token, no cap store. Seam is no-op when env unset (default `make 시작` stays byte-identical).
- Acceptance Criteria:
  - [ ] `_maybe_write_ship_manifest` exists; `source_sha` = `git rev-parse HEAD` of the committed gated change (NOT stale working-tree HEAD), passing `_SHA_RE`.
  - [ ] With `BIDMATE_SHIP_MANIFEST_DIR` unset, `make 시작` output byte-identical to origin/main (regression test) and no manifest written.
  - [ ] ADR 0090 verification's old "grep `_maybe_write_ship_manifest` is empty" assertion is updated/superseded in the amendment (this PR intentionally makes that grep non-empty).
- Test strategy: unit test the seam (env-gated write/no-write); regression test on `make 시작` byte-identity; assert manifest round-trips through `read_ship_manifest`.
- Risk: **`agent_loop.py` is deliberately EXCLUDED from the CODEOWNERS constitutional set** (ADR 0091, "too frequently edited") — so this PR does NOT trip the owner-review gate, which is correct. But it is the seam where a stale SHA = wrong-commit merge later; SHA derivation must be the committed SHA. Medium risk; high blast radius if SHA wrong.

### PR-2 — File-backed self-immutable cap store + cross-worktree lock (issue unit 4; **new ADR 00XX**) — blocked-on: none

> **⚠️ 2026-06-01: 재설계 필요 (codex 5x block).** 첫 시도 구현이 다음 결함으로 block됐다: self-immutable 가드 빈 리스트 우회(freq 6/8), 상대경로 cap-store = per-worktree 카운터(4/8), day-key rotation 우회(4/8), public initializer reset(1/8). 재설계 방향은 끝 "P2.2 첫 시도 결과" 섹션 참조. **ADR 0092는 #1717(lane bottleneck)이 선점** — cap store ADR은 0093+로 예약.

- Goal: Implement `_FileMergeCapStore` satisfying `ImmutableCounterStore` with `loop_writable=False`, backed by `BIDMATE_SHIP_CAP_STORE`, with cross-worktree shared file lock + transactional daily-cap increment; malformed file → fail-closed.
- Scope: new class in `_staging_ship.py`; new ADR 00XX (reserve) for the self-immutable cap-store + cross-worktree concurrency contract; `SELF_IMMUTABLE_PATHS` construct in `_governance.py` (unit 9, the immutability mechanism the ADR defines) seeded with cap-store path + `_ship_env.py` + manifest seam path; lane refuses to ship a PR whose diff touches `SELF_IMMUTABLE_PATHS`.
- Non-Goals: no live merge, no token, no PR open. Cap store is exercised through `StagingShipLane.ship()` with the existing stub ops in tests.
- Acceptance Criteria:
  - [ ] `_FileMergeCapStore.loop_writable is False`; `DailyMergeCapCounter(__post_init__)` accepts it and rejects a loop-writable store.
  - [ ] Concurrent increments from two simulated worktrees serialize correctly (no lost update); cap+1 → `blocked-cap`, counter not resettable by the lane.
  - [ ] Malformed / missing cap file → fail-closed (`rc 2` / refuse), never silent-zero.
  - [ ] `SELF_IMMUTABLE_PATHS` exists in `_governance.py`; a PR diff touching any of them is refused by the lane (unit-tested).
  - [ ] New ADR 00XX present; README index row added.
- Test strategy: unit tests for store immutability + malformed-file fail-closed; concurrency regression test (`tests/test_*_regression.py`) spawning parallel increments against a tmp lock file; `SELF_IMMUTABLE_PATHS` block test.
- Risk: cross-worktree lock correctness (this repo runs 20-30 concurrent worktrees — see CLAUDE.md `/tmp` collision incidents #1274). Use `flock`-style OS lock on the store path, NOT a fixed `/tmp` name. **High risk** — concurrency + self-immutability are the security crux. Touches `_staging_ship.py` + `_governance.py` → **CODEOWNERS owner review required**.

### PR-3 — Permission-separated merge token + ambient-credential stripping in `merge()` (issue unit 3) — blocked-on: PR-2 (shares `_staging_ship.py` ops surface; sequence to avoid conflict)

- Goal: `merge()` uses ONLY `BIDMATE_SHIP_MERGE_TOKEN`, with ambient `GH_TOKEN`/`GITHUB_TOKEN`/`GH_ENTERPRISE_TOKEN` stripped from the merge subprocess env (mirror the read-only `_GH_AMBIENT_DROP_KEYS` pattern already in `_gh`).
- Scope: token plumbing into `_RealGitOps` merge subprocess env; ambient strip; fail-closed if token absent. Keep this PR's diff token-isolation-only (leave the actual `gh pr merge` invocation to PR-4) to keep review tight — see Open Questions.
- Non-Goals: no PR creation, no poll, no idempotency.
- Acceptance Criteria:
  - [ ] Merge subprocess env contains the merge token and NOT the ambient mutation tokens (unit test inspecting constructed env).
  - [ ] Token absent → fail-closed, no merge attempted.
  - [ ] Covered by ADR 00XX (PR-2) token trust-boundary section, or a short addendum if PR-2's ADR didn't pre-cover the merge-token half.
- Test strategy: unit test env construction with an injectable runner (no network); assert token-only.
- Risk: token leakage into logs / child env. **High risk / security-critical.** Touches `_staging_ship.py` → **CODEOWNERS owner review required**.

### PR-4 — Live `gh pr create` / `gh pr merge` + bounded check poll (issue units 2, 6) — **blocked-on: PR-1 (manifest), PR-3 (token), + operator branch-protection live (blocked-on-user)**

- Goal: Replace the `open_pr` / `required_checks_all_success` / `merge` stubs with live `gh` calls; `required_checks_all_success` polls within `BIDMATE_SHIP_CHECK_ATTEMPTS` × `BIDMATE_SHIP_CHECK_INTERVAL_SECONDS` (pending/absent → False, bounded).
- Scope: live `gh pr create --base autopilot/integration`, `gh pr checks` poll loop, `gh pr merge` via PR-3's token env. Wire `archive_ship_manifest` on merge success.
- Non-Goals: idempotency + `--match-head-commit` + serialization (PR-5); AR4 (PR-6).
- Acceptance Criteria:
  - [ ] `open_pr` returns a real PR id; `merge` merges via the separated token; `archive_ship_manifest` moves manifest to `.consumed` on success only.
  - [ ] Poll is bounded (terminates at attempt cap → `blocked-ci`), pending check → not merged.
  - [ ] **Gate-3 live e2e check 2 passes**: `GH_TOKEN=$BIDMATE_SHIP_MERGE_TOKEN gh api -X PATCH .../protection -F allow_force_pushes=true` → **HTTP 403** (token cannot edit protection).
- Test strategy: unit tests with injectable runner for poll bounding + archive-on-success-only; **live e2e is manual + cannot be mocked** (exercises real GitHub state) — documented in runbook, run once by operator.
- Risk: this is the **first irreversible step** (real merges). Depends on operator branch protection existing or `protection_verified` keeps it `rc 2` (safe). **High risk.** CODEOWNERS owner review required.

### PR-5 — `source_sha` → PR head binding (`--match-head-commit`) + serialized promotion + PR idempotency (issue units 5, 7) — blocked-on: PR-4

- Goal: Bind the merge to the exact gated commit (`gh pr merge --match-head-commit <source_sha>`); reuse an existing open `source→base` PR instead of opening duplicates; serialize promotions so concurrent worktrees can't race two merges into `autopilot/integration`.
- Scope: thread manifest `source_sha` into `merge()`; idempotent `open_pr` (query existing open PR for `source→base`); serialized promotion (reuse / extend PR-2's cross-worktree lock to also gate the promote critical section).
- Non-Goals: AR4.
- Acceptance Criteria:
  - [ ] Merge uses `--match-head-commit <source_sha>`; a head-moved PR is rejected (no merge of a different commit than the manifest binds).
  - [ ] Second `open_pr` for the same `source→base` reuses the existing PR (no duplicate).
  - [ ] Two concurrent promotions serialize (lock); only one proceeds at a time.
- Test strategy: unit tests for idempotent open + match-head argument construction; concurrency regression test for serialized promotion (reuse PR-2 lock harness).
- Risk: head-moved-between-create-and-merge race; lock scope correctness. **Medium-high.** CODEOWNERS owner review required.

### PR-6 — AR4 protection-completeness hardening (issue unit 8) — blocked-on: PR-4 (extends live verify path)

- Goal: Tighten `protection_verified` with the remaining protection-completeness assertions beyond the D-minus set (which already covers `staging-self-ship-guard` required, `strict=True`, `allow_force_pushes=false`, `enforce_admins=true`). Candidate additions: `required_pull_request_reviews.require_code_owner_reviews=true` (ties AR3/ADR 0091 into the live verify), `allow_deletions=false` re-assert, `lock_branch`/`block_creations` where relevant.
- Scope: additive assertions in `_RealGitOps.protection_verified`; fixture tests for each new fail-closed branch. (`allow_deletions` was already verified in D-minus per #1703 — confirm and avoid duplicate.)
- Non-Goals: any merge-path change.
- Acceptance Criteria:
  - [ ] Each new protection field absent/false → `protection_verified` returns False (fail-closed), unit-tested per field.
  - [ ] No regression to the D-minus assertions.
- Test strategy: parametrized unit tests over protection-JSON fixtures (one missing field each → False; complete → True).
- Risk: low (additive read-only assertions). CODEOWNERS owner review required (touches `_staging_ship.py`).

## Acceptance Criteria

- [ ] All 9 issue #1703 P2.2 units land across PR-1..PR-6 with the dependency edges above honored.
- [ ] New ADR 00XX (merge-token + self-immutable cross-worktree cap store) accepted; ADR 0090 amended (emission seam + live ops now implemented).
- [ ] `SELF_IMMUTABLE_PATHS` exists in `_governance.py` and the lane refuses to ship PRs touching it.
- [ ] Default `make 시작` byte-identical; lane-without-prerequisites still `rc 2` (fail-closed default preserved).
- [ ] Gate-3 live e2e both pass (guard-file PR → required-check fail; token PATCH protection → 403).
- [ ] `bash scripts/test.sh` green; every behavior-changing PR carries a regression test.
- [ ] `tasks/queue.md` T-2026-0071 updated; runbook built-vs-deferred table updated.

## Validation Strategy

```bash
# default-path preservation (every PR)
make -n 시작            # byte-identical loop invocation; no BIDMATE_SHIP_MANIFEST_DIR
bash scripts/test.sh    # full suite (CI gate)

# seam intentionally present after PR-1 (inverts ADR 0090's empty-grep)
grep -n "_maybe_write_ship_manifest" scripts/agent_loop.py

# cap-store + SELF_IMMUTABLE_PATHS after PR-2
python3 -m pytest tests/test_staging_ship*.py -q
grep -n "SELF_IMMUTABLE_PATHS" scripts/_governance.py

# Gate-3 live e2e (operator, after branch protection + token — NOT mockable)
GH_TOKEN=$BIDMATE_SHIP_MERGE_TOKEN gh api -X PATCH \
  repos/:owner/:repo/branches/autopilot%2Fintegration/protection \
  -F 'allow_force_pushes=true'   # expect HTTP 403
```

Expected evidence:
- Test/eval output: `pytest` green on extended `test_staging_ship*` + new concurrency/idempotency regression tests.
- Generated artifact: a real merged PR into `autopilot/integration` + `ship_manifest.json.consumed`.
- Reviewer checklist: token never in logs/child env; cap store `loop_writable=False`; cross-worktree lock not a fixed `/tmp` path; `--match-head-commit` present.
- Explicitly not validated by unit tests (reason): Gate-3 live e2e — exercises real GitHub server state, cannot be mocked; run once by operator.

## Rollback Strategy

Per-PR revert via `git revert` (append-only — force-push/history-rewrite forbidden at every step, ADR 0088 §3). The lane fails CLOSED, so reverting any live-merge PR (PR-4/5) returns the lane to `rc 2` with no orphaned state. **Do NOT delete** the cap-store file or any `ship_manifest.json.consumed` during rollback (audit trail). If a bad merge reaches `autopilot/integration`, revert the merge commit on the integration branch (never main, never force-push). Operator can instantly halt via kill-switch (`touch $(ACTIVE_SHIP_STATE_DIR)/KILL` or `BIDMATE_SHIP_KILL_SWITCH=1`) independent of any code rollback.

## Failure Modes

- Failure mode: stale `source_sha` (working-tree HEAD vs committed SHA) → merges wrong commit. Detection: `--match-head-commit` (PR-5) rejects head mismatch; manifest `_SHA_RE` validation. Stop: lane refuses; manual inspect.
- Failure mode: cross-worktree cap race → daily cap exceeded. Detection: cap-store concurrency regression test; T4 self-immutable counter. Stop: `blocked-cap`, lock serializes.
- Failure mode: merge token leaks into runner/child env or logs. Detection: env-inspection unit test (PR-3); `BIDMATE_SHIP_*` strip across 6 lanes. Stop: token-absent → fail-closed.
- Failure mode: `gh api` rate-limit / outage during `protection_verified` or poll. Detection: existing fail-closed on subprocess error. Stop: `rc 2` (blocked-on-user), bounded poll terminates.
- Failure mode: duplicate PRs from re-runs. Detection: idempotency test (PR-5). Stop: reuse existing open PR.
- Failure mode: ship-arm armed concurrently. Detection: `assert_ship_arm_not_active` (already in `ship()` + `시작-ship`). Stop: fail-closed (ADR 0088 §7).

## Observability

- `<state-dir>/ship_manifest.json` (pending) → `.consumed` (merged) — merge lifecycle.
- Cap-store file (counts only) — daily merge count, self-immutable.
- `staging-self-ship-guard` required-check status + `check_constitutional_review.py` result on each PR.
- `_staging_ship.py main()` stderr lines (already structured `[staging-self-ship] ...`).
- SLA counters (daily merge count / revert rate / main-green rate) are ADR 0090's P2.2 reservation — surface them if cheap, else defer to a follow-up (see Open Questions).
- CI: `bash scripts/test.sh` + the guard workflow.

## Reviewer Notes

Attack first, in priority order:

1. **Token trust boundary (PR-3)**: prove the merge token cannot leak into any runner/child/log env and that ambient mutation tokens are stripped from the merge subprocess. This is the ouroboros-class risk.
2. **Self-immutability + cross-worktree concurrency (PR-2)**: prove the loop cannot reset its own cap, the lock is not a fixed `/tmp` path (incident #1274 class), and malformed cap files fail closed.
3. **`source_sha` integrity (PR-1/PR-5)**: prove the manifest binds the *committed* SHA and `--match-head-commit` blocks a moved head.
4. **Default-path byte-identity**: prove `make 시작` (no args) and the lane-without-prerequisites are unchanged.
5. **Data boundary**: PR/commit/notification payloads carry counts only.
6. **ADR scope**: confirm the new ADR + 0090 amendment cover exactly the new contracts and do not silently expand into P3 (main auto-promote / option 3).

## Open Questions

- [ ] **ADR shape**: single new ADR 00XX covering both merge-token + cap-store, with a separate `## P2.2 Resolution` addendum on ADR 0090 — OR fold the 0090 resolution into the new ADR's "Supersession / 관계"? — Affects how many ADR numbers to reserve at ship time.
- [ ] **PR-3 boundary**: implement only token-env-construction in PR-3 (leaving the actual `gh pr merge` call to PR-4) vs wire the live merge in PR-3 too? — Tighter review vs fewer PRs.
- [ ] **SLA counters** (daily merge / revert rate / main-green, ADR 0090 P2.2 reservation): include in PR-2's cap store or split to a follow-up PR-7? — Scope creep vs completeness.
- [ ] **AR4 field set**: exactly which protection fields beyond the D-minus set does AR4 add (`require_code_owner_reviews`? `lock_branch`? `block_creations`?) — needs a maintainer call on how strict, since each is a fail-closed gate that could block legitimate operator config.

## Handoff Notes

```markdown
## Session Handoff - 2026-06-01

- Role: Planner (plan-only)
- Branch / worktree: docs/issue-1707-p22-plan
- Issue / PR: issue #1703 (P2.2 SSoT); plan issue #1707
- Task: T-2026-0071 P2.2 plan doc
- Current status: plan drafted; awaiting maintainer review + ADR/issue number reservation
- Decisions made: 6-PR stack, 1 new ADR + 0090 amendment, cap-store/seam offline-testable → safe-start first
- Commands run: gh issue view 1703; read ADR 0088/0090/0091, _staging_ship.py, _ship_env.py, agent_loop.py grep, _governance.py, queue.md
- Results: confirmed StagingShipLane.ship() + cap Protocol + manifest source_sha contract already exist; only GitOps stubs + file cap store + emission seam + SELF_IMMUTABLE_PATHS missing
- Next safe command: reserve ADR number (ls docs/adr/ + gh pr list --search ADR --state open), then start PR-1 or PR-2 (both offline-testable, no branch-protection dependency)
- Open questions: see Open Questions section (4 items)
- Risks: PR-2 cross-worktree lock + PR-3 token leakage are the security crux; all _staging_ship.py-touching PRs need non-author CODEOWNERS approval

---

## P2.2 첫 시도 결과 (2026-06-01, issue #1720)

P2.2를 3개 worktree agent 동시 실행으로 착수했다가 거버넌스(codex 적대 리뷰)가 PR-1·PR-2를 모두 정당하게 block했고, agent 병렬 오케스트레이션 자체가 메인 repo 오염 + exit hygiene 실패를 일으켰다. 실측 요약:

### 안착 (이번 세션 merged)
- **AR1 `_ship_env` dedup** (#1706): `sanitized_env`가 `strip_ship_secret_env` 공유 헬퍼에 위임.
- **verdict cache 정책 키** (#1710/#1713): codex verdict 캐시 키가 review policy(attempts/min_frequency/timeout)를 무시하던 버그 수정. codex가 잡은 `_policy_digest` 시그니처 + `os` 미정의 버그를 거쳐 머지.
- **operator branch-protection + AR3** (CODEOWNERS code-owner review): `autopilot/integration` + `main` 양쪽에 required check(`staging-self-ship-guard`) + force-push deny + enforce_admins + require_code_owner_reviews 설정. `protection_verified` live 검증 VERIFIED.

### 보류 (codex self-catch — 모두 정당)
- **PR-1 manifest seam**: codex critical(freq 5/8) "no-ship 경로 stale `source_sha`" → PR-4(live merge)와 병합. 위 PR-1 섹션 노트 참조.
- **PR-2 cap store**: codex 5회 block(self-immutable 빈 리스트 우회 6/8, per-worktree 상대경로 카운터 4/8, day-key rotation 우회 4/8, public initializer reset 1/8) → 재설계.
- **cascade DEFAULT_ATTEMPTS 8→3** (ADR 0066, #1709 철회): codex가 "load-bearing-only 트리거라 attempts를 낮추면 핵심 망라성 희생"으로 self-catch. env override가 안전한 경로.

### Gate-3 한계
- `staging-self-ship-guard` 워크플로는 `on: pull_request: branches: ["autopilot/**"]` 전용이라 `main` base PR로는 트리거 불가. e2e 검증은 integration 레인 운영 시점으로 이관.

### cap store 재설계 방향 (codex findings 기준, 다음 1-lane 세션)
1. **changed-files 산출**: 자기 작성 가능한 입력 대신 lane-internal trusted git/GitHub 메타데이터에서 도출 + fail-closed.
2. **cap-store 경로**: 상대경로 금지 → 절대경로(worktree 무관 단일 카운터). `flock`-style OS lock, 고정 `/tmp` 이름 금지(#1274).
3. **day key**: 자기 회전 가능 키 금지 → trusted UTC date 버킷.
4. **immutability authority**: in-process self-guard만으로 불충분 → 외부 append-only/monotonic authority. `SELF_IMMUTABLE_PATHS` 빈 리스트면 fail-closed.
5. **ADR**: 0092 선점 → 0093+ 예약. permission-separated merge token + self-immutable cross-worktree cap store를 security contract로.

### agent 오케스트레이션 교훈 (issue #1719)
P2.2 security-critical 작업은 **단일 writer lane**으로 진행해야 한다. 병렬 worktree agent는 confinement 실패(부모 repo 오염) + exit hygiene 부재(TaskStop 후 pid 생존)를 일으켰다(codex 검증). 가드 백로그 = issue #1719.
```

## P2.2 재개 준비 상태 (2026-06-01, follow-up 3건 마감)

첫 시도(위 §"P2.2 첫 시도 결과")에서 파생된 follow-up 3건이 전부 main 안착 — 이 섹션이 현재 재개 상태의 SSoT:

- **escalation** #1728 → PR #1734 (`4b22c77f`): codex pre-commit adaptive escalation (START=2 → CAP=8). ADR 0066 Status **Proposed 유지**(Gate-3 e2e 미배선). dogfood self-catch(freq 2/2 "clean 2-pass START 가 CAP 안전망 skip")은 ADR 0066 Consequences 에 **수용된 한계 + escape hatch** `BIDMATE_CODEX_ADVERSARIAL_START_ATTEMPTS=CAP` 로 문서화(은폐 X).
- **ADR clarify** #1727 → PR #1735 (`06dfffa0`): ADR 0090 strict-check 계약(4 fail-closed protection_verified 조건) 명료화 + ADR 0091 CODEOWNERS 런북 동기화(`require_code_owner_reviews=true` full object).
- **agent isolation guards** #1719 → PR #1736 (`82efdab2`): `agent_loop.py` write-patch lane 에 confinement assert + parent-repo write ban + claimed-files disjoint + exit hygiene(commit-before-teardown) **4종 가드 + 15 테스트**. → 위 §"agent 오케스트레이션 교훈"의 백로그 **해소**, P2.2 single-writer lane 격리 전제조건 충족.

### 재개 시 남은 것 (전부 maintainer 결정 / 운영 시점 대기)
1. **Open Questions 4건** (위 §Open Questions) — ADR shape / PR-3 boundary / SLA counters / AR4 field set. **maintainer 결정 선행 필수**.
2. **cap store 재설계** (위 §"cap store 재설계 방향" 5항, 1-lane 세션) — ADR 0093+ 예약.
3. **manifest seam** — PR-4(live merge)와 병합.
4. **live merge e2e** — integration 레인 운영 시점 (Gate-3 한계: 워크플로 `autopilot/**` 전용).

다음 안전 명령: maintainer가 위 Open Questions 4건을 먼저 결정하고 integration 운영 창을 승인한 뒤, ADR 0093+ 번호 예약(`ls docs/adr/` + `gh pr list --search ADR --state open`)으로 재개한다. **병렬 worktree agent 금지 — 단일 writer lane** (#1719 교훈, 위 §).
