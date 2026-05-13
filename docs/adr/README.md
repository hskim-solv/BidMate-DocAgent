# Architecture Decision Records (ADR)

This directory holds the **load-bearing decisions** for BidMate-DocAgent
— the ones that, if reversed, would force significant rework or
invalidate published evaluation results.

## When to write an ADR

Write one when a change:

- Removes, replaces, or fundamentally alters a baseline / pipeline /
  evaluation contract that other parts of the system depend on.
- Picks between two viable approaches whose trade-off you will need to
  defend later (in review, in an interview, or to your future self).
- Establishes a new convention that future changes must follow.

Do **not** write one for routine code changes, bug fixes, refactors,
or doc edits. Those go straight into the PR description.

## File layout

```
docs/adr/
├── README.md           # this file
├── _template.md        # copy this when starting a new ADR
└── NNNN-slug.md        # one ADR per file
```

- `NNNN` is a 4-digit zero-padded sequence, e.g. `0001`, `0023`.
- Numbers are **never reused or renumbered**, even if an ADR is later
  superseded. Continuity matters more than tidiness.
- `slug` is short, kebab-case, and stable. Pick a name you will not
  want to rename later (e.g. `metadata-first-retrieval`, not
  `retrieval-changes-v2`).

## Status lifecycle

| status | meaning |
|---|---|
| `proposed` | Decision drafted but not yet implemented or merged. Open for change. |
| `accepted` | Reflected in code / docs / tests. Treated as the current convention. |
| `superseded by NNNN` | Replaced by a later ADR. The old file stays; the new one links back. |
| `deprecated` | No longer applies but no replacement exists. Rare. |

Always update the status header when status changes. Do not delete
old ADRs even when superseded — their existence is part of the
project record.

## Authoring conventions

- Keep each ADR short. One screen is the target. If you need more
  room, the decision probably needs to be split or the context
  belongs in a regular design doc.
- Use the section headings from [`_template.md`](./_template.md):
  **Context**, **Decision**, **Consequences**, **Alternatives
  considered**.
- Reference concrete code paths (`rag_core.py:L1843`) and existing
  docs rather than restating their content.
- Cross-link from any prose doc that previously held the rationale,
  so the ADR becomes the canonical source.

## Index

| # | Status | Title |
|---|---|---|
| [0001](./0001-preserve-naive-baseline.md) | accepted | Preserve a naive baseline alongside the agentic pipeline |
| [0002](./0002-metadata-first-retrieval.md) | accepted | Metadata-first retrieval strategy |
| [0003](./0003-structured-answer-citation-contract.md) | accepted | Structured answer / citation contract (`schema_version: 2`) |
| [0004](./0004-verifier-retry-policy.md) | accepted | Verifier-driven retry with strict → relaxed staging |
| [0005](./0005-eval-split-public-synthetic-private-local.md) | accepted | Eval split: public synthetic vs private local |
| [0006](./0006-llm-judge-on-real-data-only.md) | accepted | LLM-judge on the real-data surface only (refines 0004) |
| [0007](./0007-issue-linked-branch-naming.md) | accepted | Issue-linked branch naming convention |
| [0008](./0008-evidence-boundary.md) | accepted | Evidence-boundary defense against prompt injection |
| [0009](./0009-external-baseline-comparison.md) | proposed | External baseline comparison via a separate script (extends 0001) |
| [0010](./0010-hybrid-bm25-dense-retrieval-rrf.md) | accepted | Hybrid BM25 + dense retrieval with RRF fusion |
| [0011](./0011-llm-synthesis-as-additive-ablation.md) | proposed | LLM answer synthesis as additive ablation (extends 0001, preserves 0003) |
| [0012](./0012-llm-judge-on-public-synthetic.md) | accepted | LLM-judge on the public synthetic eval, stub-default (refines 0006, reuses 0011 backend pattern) |
| [0013](./0013-observability-as-additive-pluggable-surface.md) | accepted | Observability as an additive, pluggable, fail-closed surface |
| [0014](./0014-ragas-judge-additive-synthetic.md) | accepted | RAGAS-style LLM judge as additive enrichment on synthetic surface (extends 0012) |
| [0015](./0015-cost-telemetry-additive.md) | accepted | Cost telemetry as additive observability (extends 0011, 0013) |
| [0016](./0016-judge-human-agreement.md) | proposed | Judge↔human agreement as calibration gate on real-data eval (refines 0006) |
| [0017](./0017-llm-metadata-extraction-additive.md) | proposed | LLM metadata extraction as additive backend (extends 0011) |
| [0018](./0018-korean-public-rag-bench.md) | accepted | Korean public RAG bench as supplementary out-of-domain surface (extends 0005) |
| [0019](./0019-embedding-default-stays-minilm.md) | accepted | Embedding default stays MiniLM-L12-v2 with explicit re-open conditions (extends 0002) |
| [0021](./0021-bge-m3-completes-phase-1-3.md) | accepted | BGE-M3 closes ADR 0019 Phase 1.3 condition 2; default stays MiniLM (supplements 0019) |
| [0022](./0022-langgraph-orchestration-stage-1.md) | accepted | LangGraph orchestrator path for agentic_full presets — stages 1 (passthrough) + 2 (multi-node analyze / retrieve_loop / build_answer; `_phase_*` helpers shared with direct path; opt-in via BIDMATE_ORCHESTRATOR=langgraph, preserves ADR 0001) |
| [0023](./0023-hyde-query-expansion-ablation.md) | proposed | HyDE query expansion as additive ablation (extends 0001, preserves 0003, reuses 0011 / 0020 backend pattern) |
| [0024](./0024-agentic-full-llm-as-api-default.md) | accepted | API surface default preset = `agentic_full_llm`; backend default stays `stub` (complements 0011; CLI default stays `naive_baseline` per 0001) |
| [0025](./0025-cost-frontier-defer-until-real-baselines.md) | accepted | Cost-accuracy frontier deferred until external baseline real runs land (defers #177; backs README §Limitations "비용 영점"; follows ADR 0019 → 0021 measurement-gated pattern) |
| [0026](./0026-cross-encoder-reranker-deferral.md) | accepted | Cross-encoder reranker default stays stub-identity; real-backend (bge / bge_ko / cohere) measurement deferred — `full_reranker ≡ full` under CI stub by construction, `full` vs `no_rerank` already 0pp on public synthetic (mirrors ADR 0019 / 0025 pattern) |
| [0027](./0027-lora-finetuned-embedding-additive.md) | proposed | LoRA-fine-tuned embedding adapter as additive ablation, env-var gated (`BIDMATE_EMBEDDING_LORA_ADAPTER`), HF Hub adapter pinned by commit SHA (extends 0001 / 0011 / 0019; does NOT trigger 0019 re-open) |
| [0028](./0028-security-screen-additive.md) | accepted | Prompt-injection screen (query-side, diagnostic-only) + PII redaction (ingestion-time, opt-in via `BIDMATE_INGEST_REDACT_PII`) as additive security layer (extends 0008 to query side; preserves 0001 / 0003 / 0005) |
| [0029](./0029-real-data-case-proposer-additive.md) | proposed | Real-data case proposer as additive semi-supervised eval-set growth (extends 0005 / 0006; reuses 0011 / 0012 backend pattern; preserves 0001 / 0003 / 0004 / 0008; calibration mirrors 0016) |
| [0030](./0030-leaderboard-headline-includes-agentic-full.md) | accepted | Leaderboard headline expands to render `agentic_full` alongside `naive_baseline` as parallel time series; ADR 0001 baseline preserved, `ablation_full` aggregate key added to history snapshots (extends ADR 0001 / ADR 0024 visibility surface) |
| [0031](./0031-bm25-korean-morphology-additive.md) | accepted | BM25 Korean morphology tokenizer (`bm25_tokenizer: "regex" \| "kiwi"`) as additive ablation, kiwipiepy lazy-imported with never-raise fallback to regex (extends 0010 / 0011; preserves 0001 / 0003; follows 0019 → 0021 / 0026 measurement-gated pattern) |
| [0032](./0032-eval-saturation-routed-subset.md) | proposed | Eval-set saturation hypothesis + routed-subset measurement surface as falsifier for ADR 0019 deferral (extends 0019 / 0021; preserves 0001 / 0002; adds `agentic_full_routed` ablation preset; spread ≥ +3pp on routed subset triggers 0019 re-open) |
| [0033](./0033-multihop-cross-section-eval-slice.md) | proposed | Multi-hop cross-section eval slice as orthogonal saturation falsifier (complexity axis; extends 0032; 50-item synthesized dataset, LLM-judge quality filter; spread ≥ +5pp on multi-hop slice supplements ADR 0019 re-open conditions; preserves 0001 / 0003 / 0005) |

## Deferred decisions (measurement-gated re-open)

Several ADRs lock the *current* default while naming explicit measurement
conditions that, if satisfied, would re-open the decision and potentially
flip the default. This pattern (origin: ADR 0019 → ADR 0021) keeps the
decision honest without forcing premature changes — and provides a
ready answer when an external review re-suggests an option that was
already considered.

Each row below has a corresponding `adr-reopen`–labeled tracking issue
so the re-open condition is visible in the backlog rather than buried
in ADR prose.

| ADR | Locked default | Re-open trigger | Tracking |
|---|---|---|---|
| [0019](./0019-embedding-default-stays-minilm.md) + [0021](./0021-bge-m3-completes-phase-1-3.md) | Embedding stays MiniLM-L12-v2 | New candidate (e.g. KURE-v1, fine-tuned LoRA per [0027](./0027-lora-finetuned-embedding-additive.md)) shows ≥ +5pp `full` lift with non-overlapping 95% CIs — measurement surface for the saturation falsifier defined in [0032](./0032-eval-saturation-routed-subset.md) | [`adr-reopen` label](https://github.com/hskim-solv/BidMate-DocAgent/labels/adr-reopen) |
| [0025](./0025-cost-frontier-defer-until-real-baselines.md) | No modeled cost-accuracy frontier in repo | `reports/external_baselines.json` gets ≥ 1 entry with `backend != "stub"` (n ≥ 32) + ADR 0015 token aggregation wired into eval | [`adr-reopen` label](https://github.com/hskim-solv/BidMate-DocAgent/labels/adr-reopen) |
| [0026](./0026-cross-encoder-reranker-deferral.md) | `BIDMATE_RERANK_BACKEND=stub` (identity); `Reranker` Protocol kept | Real backend (`bge` / `bge_ko` / `cohere`) shows ≥ +3pp lift on `full_reranker` vs `full` with non-overlapping 95% CIs on public synthetic (n=42) | [`adr-reopen` label](https://github.com/hskim-solv/BidMate-DocAgent/labels/adr-reopen) |

Note that ADR 0024 (API default = `agentic_full_llm`) and ADR 0022
(LangGraph orchestrator stage 1) are *not* listed here because they are
already accepted action items, not deferrals. ADR 0027 (LoRA adapter)
and ADR 0032 (eval-saturation falsifier) are both *proposed* — they
inherit ADR 0019's re-open conditions and do not themselves defer
anything; ADR 0032 in particular *defines the measurement surface* that
makes ADR 0019's re-open trigger empirically testable.

## Decision evolution

Every ADR file carries `Date: 2026-05-11` because that's when the ADR
governance itself was introduced (PR #87 back-filled the five
foundational ADRs in a single batch). The decisions themselves
*evolved* through two weeks of build — see [`docs/portfolio-case-study.md`](../portfolio-case-study.md)
and the [`docs/blog/`](../blog) series for the experiment-narrative — but
on the time axis they look bunched.
The more honest evolution axis is **logical dependency**: what extends,
refines, defends, or reuses the backend of what. See
[`docs/engineering-governance.md`](../engineering-governance.md) for the
broader process context.

### Clusters

#### Foundation — what to preserve, what to measure (0001–0005)

[ADR 0001](./0001-preserve-naive-baseline.md) freezes the extractive
baseline as an invariant. [ADR 0002](./0002-metadata-first-retrieval.md)
names the retrieval strategy that beats naive lexical/dense on Korean
RFPs. [ADR 0003](./0003-structured-answer-citation-contract.md) is the
answer-and-citation contract every downstream metric reads.
[ADR 0004](./0004-verifier-retry-policy.md) makes verifier-driven retry
the failure-handling default. [ADR 0005](./0005-eval-split-public-synthetic-private-local.md)
splits public-synthetic from private-local eval so reviewers can
reproduce something without the private corpus.

#### Real-data hardening — when synthetic CI isn't enough (0006, 0008)

The deterministic verifier in 0004 hit a ceiling on real procurement
documents (issue #69 abstention regression). [ADR 0006](./0006-llm-judge-on-real-data-only.md)
refines 0004 with an LLM judge restricted to the private surface,
reinforcing 0005's public reproducibility. [ADR 0008](./0008-evidence-boundary.md)
defends the answer contract (0003) and the LLM judge (0006) against
prompt-injection patterns embedded in retrieved evidence.
[ADR 0016](./0016-judge-human-agreement.md) calibrates the 0006 judge
against human spot-labels (Cohen's κ + Spearman ρ) so a verifier-judge
co-regression cannot pass undetected.

#### Governance — process codified as a decision (0007)

[ADR 0007](./0007-issue-linked-branch-naming.md) lifts the issue↔branch
convention from informal practice to a CI-enforced rule. Without 0007
the rest of this index could not be maintained at scale.

#### Additive ablation surface — extend, don't replace (0009, 0010, 0011)

0001's "preserve the baseline" invariant materializes in three
alongside-ablations: [ADR 0009](./0009-external-baseline-comparison.md)
(external frameworks), [ADR 0010](./0010-hybrid-bm25-dense-retrieval-rrf.md)
(hybrid BM25+RRF retrieval), and [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md)
(LLM answer synthesis). Each adds a preset; none removes one. 0011 also
reuses the 0006 backend pattern so cost/trace plumbing stays consistent.

#### Eval depth — same answer, more lenses (0012, 0014)

[ADR 0012](./0012-llm-judge-on-public-synthetic.md) extends LLM-as-judge
to the synthetic surface as a stub-default enrichment, refining 0006's
"real-data only" restriction without breaking 0005's reproducibility.
[ADR 0014](./0014-ragas-judge-additive-synthetic.md) layers RAGAS-style
multi-axis judgment on top — both strictly additive (not gating).

#### Ops — observability as a fail-closed surface (0013)

[ADR 0013](./0013-observability-as-additive-pluggable-surface.md) makes
LangFuse / OpenTelemetry trace emission optional, pluggable, and
fail-closed. It extends 0001, preserves 0003, reuses the 0006 and 0011
backend pattern, and respects 0005's eval split.

### Dependency graph

```mermaid
graph LR
  subgraph Foundation
    A1[0001 Naive baseline]
    A2[0002 Metadata-first]
    A3[0003 Answer contract]
    A4[0004 Verifier retry]
    A5[0005 Eval split]
  end

  A7[0007 Branch naming]

  subgraph Real-data hardening
    A6[0006 LLM judge real-data]
    A8[0008 Evidence boundary]
    A16[0016 Judge-human agreement]
  end

  subgraph Additive ablation surface
    A9[0009 External baseline]
    A10[0010 Hybrid BM25+RRF]
    A11[0011 LLM synthesis]
  end

  subgraph Eval depth
    A12[0012 LLM judge synthetic]
    A14[0014 RAGAS additive]
  end

  A13[0013 Observability]

  A4 -- refines --> A6
  A5 -- reinforces --> A6
  A3 -. defends .-> A8
  A6 -. defends .-> A8

  A1 -- extends --> A9
  A1 -- extends --> A10
  A2 -- extends --> A10
  A1 -- extends --> A11
  A1 -- extends --> A13

  A6 -- refines --> A12
  A6 -- refines --> A14
  A6 -- calibrated by --> A16

  A6 -. backend .-> A9
  A6 -. backend .-> A11
  A6 -. backend .-> A13
  A11 -. backend .-> A12
  A11 -. backend .-> A13
  A11 -. backend .-> A14
```

Legend:

- **`-- extends -->`** — new ADR builds on an earlier invariant (0001's "preserve baseline" is the most extended).
- **`-- refines -->`** / **`-- reinforces -->`** — tightens or specializes an earlier decision.
- **`-. defends .->`** — protects an earlier contract against a specific attack or regression.
- **`-. backend .->`** — reuses the LLM-call backend pattern (env-keyed providers, fail-closed, cost/latency in diagnostics).

Edges intentionally omitted from the diagram (kept in each ADR's
`Related` field for accuracy): the chain of "preserves" courtesies that
0011, 0012, 0013, and 0014 extend toward 0003/0004/0005 — they reinforce
the cluster narratives but would clutter the visual.
