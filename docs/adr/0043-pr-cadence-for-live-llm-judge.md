# 0043: PR-level cadence for live LLM-judge signal (label-gated workflow)

- **Status**: accepted
- **Date**: 2026-05-14
- **Related**: [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) §
  "LLM-judge gate layers" · [ADR 0012](./0012-llm-judge-on-public-synthetic.md) ·
  [ADR 0004](./0004-verifier-retry-policy.md) · issue #722
- **Deciders**: hskim

## Context

[ADR 0012](./0012-llm-judge-on-public-synthetic.md) § *Cadence* specifies:

> *"A developer who wants the real signal runs `make synthetic-judge` with a live
> backend manually, attaches the resulting committed aggregate diff to the PR, and
> lets reviewers read the rendered table."*

This works but has no enforcement mechanism.  In practice:

- Reviewers cannot *request* a live judge run on-demand — they depend on the
  author to remember.
- Authors forget, or skip it on small PRs where they suspect no signal change.
- There is no visible record in the PR thread of *whether* a live run was
  performed for this change set.

[ADR 0005](./0005-eval-split-public-synthetic-private-local.md) §
"LLM-judge gate layers" (Gate 2) states the invariant:
*"CI runs stub-only, live backend is offline opt-in."*
Any PR-level automation must respect this: the existing `pr-eval.yml` must
not be modified to call a live LLM.

A new, **separate** workflow that fires only when explicitly requested does not
violate Gate 2 — the trigger is a deliberate human action (label attachment),
not an automatic CI gate on every commit.

## Decision

Introduce a **label-gated PR workflow** for live LLM-judge signal:

- A new workflow file `.github/workflows/pr-judge.yml` fires on the
  `labeled` event when the label `live-judge-please` is attached to a PR.
- The workflow runs `make eval && make synthetic-judge` with
  `BIDMATE_SYNTHETIC_JUDGE_BACKEND=openai_compatible` using repository
  secrets (`BIDMATE_JUDGE_API_KEY`, `BIDMATE_JUDGE_MODEL`,
  `BIDMATE_JUDGE_BASE_URL`).
- Results are posted as a **PR comment** (markdown table: `n`,
  `faithfulness_mean`, `answer_relevance_mean`, `agreement_with_verifier`,
  `by_query_type` slice) plus uploaded as a workflow artifact.
- The aggregate is **not auto-committed** to the repository; the author may
  choose to commit it separately after reviewing the signal.

### Invariants preserved

| Invariant | How preserved |
|-----------|---------------|
| **ADR 0004** reproducibility | `pr-eval.yml` unchanged; stub default still runs on every push. |
| **ADR 0005** commit boundary | Workflow artifact upload only; no `git push` of per-case data. |
| **ADR 0003** answer contract | Judge never feeds back into `run_rag_query`; comment-only surface. |
| **ADR 0012** cadence | Manual opt-in preserved; label = explicit request, not auto-gate. |

### Secrets required

| Secret | Description |
|--------|-------------|
| `BIDMATE_JUDGE_API_KEY` | API key for the OpenAI-compatible judge endpoint |
| `BIDMATE_JUDGE_MODEL` | Model identifier (e.g. `claude-sonnet-4-5`) |
| `BIDMATE_JUDGE_BASE_URL` | Optional custom base URL (e.g. Anthropic-Compat) |

These secrets are already used by the local `make synthetic-judge` path;
this ADR does not introduce new credentials.

### Goodhart guard

The workflow runs on `labeled` but **not** on `synchronize` (new push).
A label must be re-attached after each new push to get a fresh judge run.
This prevents the judge signal from becoming an optimization target that
authors game by pushing micro-commits.

Fork PRs do not receive `BIDMATE_JUDGE_API_KEY` from repository secrets by
default (GitHub isolates secrets from forks).  The workflow must use
`pull_request_target` or explicitly check that `github.event.pull_request
.head.repo.full_name == github.repository` — see implementation PR for details.

## Alternatives considered

### (a) Nightly cron on main only

Run live judge nightly against the latest main commit.

*Rejected*: signal arrives too late — reviewer sees the aggregate days after
the PR was merged, not while reviewing.  Also conflates multiple PRs' changes
in a single run.

### (b) Automatic on every PR push (feature-flag gated)

Run live judge on every push but skip via env var in fork contexts.

*Rejected*: violates ADR 0004's *"CI never calls live LLM"* spirit even if
framed as a "second workflow".  Token cost per push is unjustified for PRs
that make no retrieval or answer changes.  Most critically, it creates
Goodhart pressure: authors will tune prompts/retrieval to maximise the
automatically-reported score rather than to improve real-world accuracy.

### (c) PR template mandatory field

Require authors to fill in a "live judge results" field in the PR template
and fail CI if blank.

*Rejected*: high friction, no automation.  Authors will write "N/A" or paste
stale results.  Adds reviewer burden without adding reliability.

### (d) `workflow_dispatch` author trigger

Add a manual dispatch button that authors click in the GitHub Actions UI.

*Rejected*: less discoverable than a label (requires navigating to Actions UI);
does not let the reviewer request a run without author involvement; the label
approach achieves the same explicit-trigger property with better UX.

## Consequences

**Wins**

- Reviewers can request a live RAGAS signal by attaching a label — no
  need to ask the author to re-run locally.
- A persistent PR comment creates a visible record of whether the live
  judge was consulted for this change set.
- Token cost is bounded: one run per label-attach event, not per commit.
- ADR 0004 / 0005 / 0012 invariants are all preserved.

**Costs**

- Requires repository secrets to be configured once by the repo owner.
- Fork PRs cannot run the live judge unless the workflow is written with
  `pull_request_target` and appropriate security checks.
- The label must be manually re-attached after each push — slight friction
  compared to a fully automatic trigger.

**Unchanged**

- `make synthetic-judge` local workflow remains the primary path for
  developers who want live RAGAS during development (pre-PR).
- `reports/synthetic_judge.aggregate.json` snapshot cadence is unchanged —
  developers still commit it manually after a meaningful signal update.
