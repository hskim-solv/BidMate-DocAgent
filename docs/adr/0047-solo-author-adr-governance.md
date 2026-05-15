# 0047: Solo-author ADR governance — lifecycle SLA + verification contract

- **Status**: accepted
- **Date**: 2026-05-15
- **Deciders**: hskim
- **Related**: [ADR 0007](./0007-issue-linked-branch-naming.md), issue [#757](https://github.com/hskim-solv/BidMate-DocAgent/issues/757) (A2 number reservation), issue [#793](https://github.com/hskim-solv/BidMate-DocAgent/issues/793) (B3 verification lint), issue [#817](https://github.com/hskim-solv/BidMate-DocAgent/issues/817) (D1 — this ADR), issue [#818](https://github.com/hskim-solv/BidMate-DocAgent/issues/818) (regex follow-up)

## Context

By 2026-05-15 this repo had accumulated 43+ ADRs over two weeks, all authored by a single person. The rules for *how* to write an ADR were scattered across three prose files (`CLAUDE.md`, `docs/engineering-governance.md`, `docs/adr/README.md`) — but no ADR codified the governance itself. A May 15 self-audit (`~/.claude/plans/fizzy-splashing-cherny-adr-governance.md`) caught three structural gaps:

- **A2** — number reservation was manual, broken at least 3× historically (`0022→0023, 0023→0025, 0029→0030`). Fixed by issue [#757](https://github.com/hskim-solv/BidMate-DocAgent/issues/757) (PR #765): `--next-adr-number` + `--check-adr-collision` CLI + pre-commit hook.
- **B3** — Consequences promised metrics that no CI verified; "Decision Theatre" risk. Fixed by issue [#793](https://github.com/hskim-solv/BidMate-DocAgent/issues/793) (PR #796): `## Verification` section + `<!-- verifies-key: <path>:<key> -->` marker + pre-commit lint.
- **D1** — no meta-ADR existed for ADR governance. This is the dogfooding gap closed here.

Two live race conditions surfaced *during* this self-audit and validated A2/B3's value in real time:

1. While drafting this ADR, PR #740 reserved ADR 0044 in a parallel worktree (caught by manual `gh pr list --search "ADR" --state open`, the cross-worktree fallback A2 documents).
2. While running `--next-adr-number` post-merge, the CLI returned `0044` despite `0044-realN-eval-case-expansion.md` existing on main — the lowercase-only `ADR_FILENAME_RE` rejected the mixed-case slug. Captured as issue [#818](https://github.com/hskim-solv/BidMate-DocAgent/issues/818) follow-up.

## Decision

ADR governance for this repo is **solo-author-by-design** with four mechanical guards substituting for absent peer review:

1. **Authority is explicit and single-party.** `Deciders: hskim` is the only meta-block author field. No `Reviewers` / `Approvers` field is added — that would imply multi-party authorization this repo does not have. Soliciting external review (mentor, ex-colleague, code-review consultant) is *encouraged* but never *blocking*. The honesty of `Deciders: <single name>` is the signal external readers should rely on.

2. **Proposed-status lifecycle SLA.** Any ADR with `Status: proposed` first committed on or after `2026-05-15` must resolve within **30 days** (`accepted`, `superseded by NNNN`, or `deprecated`). Resolution = git history mutation or an explicit `## Resolution` paragraph appended to the file. The 5 currently-proposed ADRs (`0011 / 0016 / 0023 / 0029 / 0039`) are grandfathered on first-commit-date. Automatic enforcement is a follow-up (`_governance.py` `proposed_adr_age()`); the SLA is normative now and gets a measurement collector later.

3. **Verification contract on new ADRs.** Every ADR first committed on or after `2026-05-15` must include a `## Verification` H2 section with at least one `<!-- verifies-key: <relative-path>:<key-substring> -->` marker (per [#793](https://github.com/hskim-solv/BidMate-DocAgent/issues/793)). The pre-commit hook (`.githooks/pre-commit`) enforces this on newly added files only. The 41 ADRs existing on `2026-05-15` are grandfathered; retrofit happens per-ADR in follow-up PRs so each retrofit is independently reviewable.

4. **Number reservation is mechanical.** `python scripts/_governance.py --next-adr-number` returns the next filesystem-free number. Authors MUST also run `gh pr list --search "ADR" --state open` to catch cross-worktree reservations the CLI cannot see (the failure mode this audit re-discovered while running). The pre-commit hook calls `--check-adr-collision` on any commit that adds a new ADR file, blocking same-worktree duplicates fast.

These four together replace what peer review would otherwise enforce: A2 (#757) substitutes for "did someone else check the number was free?", B3 (#793) substitutes for "did someone else challenge the Consequences claims?", and this ADR's lifecycle + authority rules substitute for "did someone else gate the merge?".

## Consequences

- **The 1-author limit becomes a surface fact.** External readers (recruiters, code-reviewers) can see `Deciders: hskim` 44+ times and infer the governance shape immediately. No false signal of distributed authorization.
- **Proposed limbo gets a deadline.** Without #2, the 5 grandfathered Proposed ADRs would have remained ambiguous indefinitely. The 30-day SLA forces a per-ADR "promote or prune" decision for everything new — automatic emission of an `adr_health.json` signal is a follow-up but the rule itself is committed now.
- **Verification grandfather is finite work.** 41 retrofit PRs (1 per existing ADR) are bounded backlog, not open-ended cleanup. Each retrofit is `add Verification section + markers, no behavior change` — small, parallelizable.
- **Honesty surface for hiring narrative.** Self-documenting "this is 1-author with mechanical guards" is stronger interview material than implicit "we just write ADRs."
- **Bus factor 1 stays bus factor 1.** None of these rules adds a second decision-maker; they only make the singleness explicit + mechanically guarded. If a future collaborator joins, the `Reviewers` field can be added in a Status: superseded ADR rather than retrofit silently.

## Alternatives considered

- **Mandate external reviewer per ADR.** Realistically blocked by repo being 1-author. Could be soft-mandated for ADRs touching `LOAD_BEARING_PATHS` but enforcement is still 1-person honor. Rejected as theater.
- **Stop writing ADRs entirely.** Sunk cost (41 existing ADRs already justify retrieval/answer contract / eval split / baseline preservation) makes deletion impossible. Plus ADRs are working as the load-bearing-decision SoT they were designed to be.
- **LLM-based reviewer bot in CI.** Over-engineering. A2/B3 mechanical guards already close ~80% of the gap. An LLM reviewer would judge content (Alternatives quality, Consequences honesty) — high false-positive risk + ongoing prompt-engineering cost.
- **Lifecycle SLA of 60d / 90d.** Risks Proposed limbo growing past one quarter. 30d is strict but forces the "promote or prune" framing weekly during self-review, not annually.

## Verification

This ADR's commitments map to concrete code paths that already exist:

<!-- verifies-key: scripts/_governance.py:next_adr_number -->
<!-- verifies-key: scripts/_governance.py:lint_adr_verification -->
<!-- verifies-key: scripts/_governance.py:find_duplicate_adr_numbers -->
<!-- verifies-key: docs/adr/_template.md:Verification -->
<!-- verifies-key: .githooks/pre-commit:lint-adr-consequences -->

Reading guide:

- `next_adr_number` — A2 #757 CLI for mechanical number reservation (decision #4).
- `lint_adr_verification` — B3 #793 lint that this ADR is the **first dogfood of** (decision #3).
- `find_duplicate_adr_numbers` — A2 #757 collision detection called by the pre-commit hook.
- `_template.md:Verification` — the template section that B3 added; new ADRs copy this.
- `.githooks/pre-commit:lint-adr-consequences` — the hook line that enforces #3 on newly added ADR files.

Running `python3 scripts/_governance.py --lint-adr-consequences docs/adr/0047-solo-author-adr-governance.md` from repo root must exit 0 — every marker above resolves to an existing key in an existing file. If a future refactor renames any of these (e.g. `next_adr_number` → `next_adr_id`), this ADR will fail its own lint and the rename PR must update both surfaces in lockstep.

## Live race history (post-mortem note for this ADR's own creation)

This ADR was authored as D1 of a 3-step audit (A2 #757 → B3 #793 → D1 #817). During the self-paced loop that shipped all three:

1. PR #740 reserved ADR 0044 (`0044-realN-eval-case-expansion.md`) — caught manually before this branch's first commit; renumbered draft 0044 → 0046.
2. After A2 merged, `--next-adr-number` returned `0044` despite the 0044 file existing on main, because the regex rejected the mixed-case `realN` slug. Captured as follow-up issue #818.
3. After this branch pushed PR #820 with the 0046 number, PR #824 merged a different ADR 0046 (`0046-ood-evaluation-domain-selection.md`) and PR #766 merged 0045 (`0045-rag-core-leaf-migration-plan.md`). GitHub flagged the PR `CONFLICTING`. Renumbered 0046 → 0047 and rebased.

Three live collisions in a 90-minute window validate the audit's premise: this single ADR ran into the failure mode the audit caught **three times** during its own authoring. The mechanical guards (A2 CLI + B3 lint + `gh pr list` cross-check) reduced the resolution cost from "silent merge collision" to "rebase + renumber + comment." Without them, ADR 0046 would have shipped twice with two different bodies, and the regex bug (#818) would still be invisible.
