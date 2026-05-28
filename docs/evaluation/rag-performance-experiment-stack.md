# RAG Performance Experiment Stack

This document selects the next RAG performance experiments from the broad RAG
technique space and orders them for BidMate-DocAgent. It is a planning surface,
not a performance claim. It contains no private raw questions, answers,
evidence text, filenames, exact local paths, document identifiers, or chunk
identifiers.

## TL;DR

Do not start with GraphRAG, Agentic RAG, late chunking, or multi-vector search.
Start with the weakest measurable links:

1. Refresh private real-eval coverage and semantic baselines after the page
   metadata and MiniLM target work.
2. Make retrieval diagnostics explain candidate-pool recall, rank quality, and
   evidence split before changing retrieval behavior.
3. Run small-to-big retrieval, reranking, retrieval-depth/fusion, context
   packing, query decomposition, parser/layout, embedding, and generator
   grounding as separate opt-in experiments with paired aggregate deltas.
4. Insert replanning gates after each measurement round so weak hypotheses are
   retired and strong ones are promoted to end-to-end bakeoff.
5. Add security, abstention, conflict, metadata, freshness, latency, and cost
   guardrails before any production-facing claim.
6. Gate advanced architectures behind no-go/go feasibility evidence and a final
   optimization decision packet.

## Selection Rules

- A performance claim requires private real-eval aggregate paired delta with
  matched dataset, config, index provenance, command, and embedding/backend
  provenance.
- Public fixture smoke can prove wiring or regression behavior only.
- Public synthetic benchmark can expose a controlled failure mode only.
- Private raw artifacts stay local and ignored.
- Experiments must state the expected primary metric and guardrails before
  implementation.
- Any experiment that increases candidate count, reranking, LLM calls, or
  context length must carry a stage latency and cost guardrail.
- If Recall@K improves but MRR, nDCG, citation, abstention, or latency regresses,
  the result is not a winner by default.
- Isolated experiment winners do not become default behavior. They must pass an
  end-to-end bakeoff and final decision gate before default-change work starts.

## Existing Evidence To Respect

- Page metadata recovery is available on current main through `T-2026-0024`.
- MiniLM and BGE-M3 semantic private real-eval targets are separated through
  `T-2026-0025`.
- The hybrid sweep report found recall-only gains but ranking and latency
  regressions; do not reopen hybrid as a broad "just add BM25" change.
- The multi-chunk strategy report deferred retrieval changes until page-aware
  evidence can distinguish same-document from multi-document evidence splits.
- `T-2026-0026` makes Chroma the canonical `naive_baseline` vector DB backend.
  Treat it as backend parity, provenance, latency, and operations work unless
  paired same-embedding deltas prove ranking drift.

## Priority Stack

| Priority | Task | Status | Why this order |
|---|---|---|---|
| P0 | `T-2026-0028` Private coverage and semantic baseline refresh | done | Establish the current baseline and coverage before experiments. |
| P0 | `T-2026-0029` Retrieval diagnostic workbench | review | Explain recall/rank/candidate-pool failures before behavior changes. |
| P0 | `T-2026-0030` Latency and cost budget envelope | ready | Prevent multi-query/rerank/compression experiments from winning on quality while breaking operations. |
| P1 | `T-2026-0031` Parent/section-window retrieval experiment | blocked | Highest-value retrieval change after page-aware evidence. |
| P1 | `T-2026-0032` Reranker candidate-budget experiment | blocked | Improve precision only after candidate-pool recall is observable. |
| P1 | `T-2026-0033` Context packing and citation ordering experiment | backlog | Use found evidence better without changing corpus or embeddings. |
| P1 | `T-2026-0034` Query rewrite and decomposition experiment | backlog | Target comparison, multi-hop, abbreviation, and mixed Korean/English queries. |
| P1 | `T-2026-0035` Prompt-injection and data/command boundary guardrail | backlog | Security must be a guardrail before more agentic or tool-using retrieval. |
| P2 | `T-2026-0036` Abstention, conflict, and freshness calibration | backlog | Improve no-answer and precedence behavior after retrieval evidence is stable. |
| P2 | `T-2026-0037` Metadata, authority, and freshness ranking experiment | backlog | Use RFP metadata only after coverage and missing-field behavior are measured. |
| P2 | `T-2026-0038` Contextual retrieval and sentence-window proof of concept | backlog | Test chunk-context enrichment after simpler small-to-big retrieval. |
| P3 | `T-2026-0039` Advanced architecture feasibility gate | backlog | Evaluate RAPTOR, GraphRAG, LightRAG, Agentic RAG, late chunking, multi-vector, and long-context only after P0/P1 evidence. |
| P0 planning | `T-2026-0046` RAG experiment task expansion | review | Adds the executable experiment tasks and replanning gates. |
| P0 | `T-2026-0047` Page metadata blocker repair/rescope | backlog | Unblock or rescope claim-bearing page/window experiments. |
| P0 | `T-2026-0048` Candidate-depth and fusion-budget sweep | backlog | Attack `not_observable_limited_depth` before adding expensive reranking/query calls. |
| P0 replanning | `T-2026-0049` Round 1 synthesis and plan adjustment | backlog | Reorder the next experiments after latency, page metadata, retrieval-depth, and reranker evidence. |
| P1 | `T-2026-0050` Parser/layout/table coverage experiment | backlog | Decide whether misses are parser/layout failures rather than retrieval failures. |
| P1 | `T-2026-0051` Embedding and representation controlled sweep | backlog | Measure embedding effects without mixing vector DB backend or prompt changes. |
| P1 | `T-2026-0052` Generator grounding and citation calibration | backlog | Measure prompt/model/decoding effects after retrieval/context evidence stabilizes. |
| P1 replanning | `T-2026-0053` Round 2 synthesis and plan adjustment | backlog | Promote at most three isolated winners to bakeoff and retire weak hypotheses. |
| P2 | `T-2026-0054` End-to-end winning-variant bakeoff | backlog | Test combined winners under one aggregate latency/cost/privacy guardrail. |
| P2 decision | `T-2026-0055` Final optimization decision packet | backlog | Decide default-change-ready, more-experiment-needed, or no-go. |

## Experiment Cadence

The stack is intentionally iterative. Do not execute every experiment just
because it appears in the queue.

1. Measurement foundation: complete `T-2026-0030` and keep `T-2026-0028` /
   `T-2026-0029` evidence current.
2. Early retrieval round: run `T-2026-0032`, `T-2026-0047`, and
   `T-2026-0048` as separate PRs. `T-2026-0031` remains blocked until page or
   window evidence is repaired or explicitly rescoped.
3. Round 1 replanning: run `T-2026-0049` to update queue status and select the
   next two to four experiments. No runtime change is allowed in the replanning
   task.
4. Full P1 experiment round: run selected tasks from `T-2026-0031`,
   `T-2026-0033` through `T-2026-0038`, and `T-2026-0050` through
   `T-2026-0052`.
5. Round 2 replanning: run `T-2026-0053` to retire low-signal branches and
   select at most three variants for `T-2026-0054`.
6. End-to-end bakeoff: run `T-2026-0054` with matched `real100_v2` provenance.
7. Decision: run `T-2026-0055`. Only this task can say whether a later
   default-change implementation should be opened.

## Replanning Gates

| Gate | Inputs | Required decision |
|---|---|---|
| `T-2026-0049` Round 1 | `T-2026-0030`, `T-2026-0032`, `T-2026-0047`, `T-2026-0048` | Choose the next experiments, keep/rescope `T-2026-0031`, and set budget caps. |
| `T-2026-0053` Round 2 | Selected P1 experiments, parser/layout, embedding, generator evidence | Promote at most three variants to bakeoff; retire no-go hypotheses; decide whether `T-2026-0039` is justified. |
| `T-2026-0055` Final decision | Baseline, diagnostics, all synthesis gates, `T-2026-0054` bakeoff | Call default-change-ready, more-experiment-needed, or no-go. |

## Deferred Techniques

| Technique | Default decision | Reason |
|---|---|---|
| GraphRAG / LightRAG | defer to `T-2026-0039` | Expensive build/eval surface; best for corpus-level sensemaking, not first-line RFP QA failures. |
| RAPTOR | defer to `T-2026-0039` | Requires summary-tree build and summary faithfulness checks. |
| Agentic RAG / Self-RAG / CRAG / FLARE | defer to `T-2026-0039` | Adds loop/tool/security complexity before retrieval and context baselines are stable. |
| Late chunking | defer to `T-2026-0039` | Requires long-context embedding model and index rebuild provenance. |
| ColBERT / multi-vector retrieval | defer to `T-2026-0039` | Storage and latency profile are large; candidate-pool diagnostics must justify it. |
| Broad hybrid BM25 rerun | do not reopen without a new hypothesis | Prior sweep showed recall-only gains with rank/latency regressions. |
| Long-context "put everything in prompt" | do not use as default | Token cost, lost-in-middle risk, ACL/privacy boundary, and citation traceability remain unresolved. |

## Metrics Required By Experiment Type

| Experiment type | Primary metric | Guardrails |
|---|---|---|
| Coverage/baseline | explicit gold coverage, parse/page coverage, run provenance | privacy, no raw IDs, no performance claim without paired delta |
| Retrieval | Recall@K, Hit@K, MRR, nDCG, candidate-pool coverage | citation, abstention, latency, same corpus/index provenance |
| Reranking | MRR@K, nDCG@K, answer containment, precision@K | candidate recall, p50/p95 latency, cost |
| Context packing | citation accuracy, faithfulness, completeness | lost-in-middle placement, token count, no hallucination increase |
| Query rewrite/decomposition | slice delta by query type | extra LLM calls, rewrite drift, no private egress without approval |
| Abstention/conflict | no-answer accuracy, conflict precedence accuracy | false abstention, citation, freshness provenance |
| Security | injection detection, instruction/data isolation checks | false positives, privacy redaction, tool-call policy |
| Parser/layout | searchable evidence coverage, page/section/table coverage | parser latency, privacy, no raw layout/text artifacts |
| Embedding/representation | Recall@K, MRR, nDCG, citation/answer delta | matched corpus/config/index, build time, index size, backend separation |
| Generator grounding | answer correctness, groundedness, citation accuracy | no-answer, conflict handling, provider/payload provenance, latency/cost |
| Replanning | bottleneck ranking, task promotion/retirement | no runtime change, no incompatible aggregate averaging |
| End-to-end bakeoff | answer/citation/abstention paired delta | latency/cost, privacy, rollback, interaction effects |
| Advanced architecture | feasibility score and no-go/go rationale | build cost, latency, privacy, rollback path |

## Execution Rules

- Create a GitHub issue and ADR 0007 branch for each implementation task when
  that task starts.
- Keep each PR to one task ID and one concern.
- Put private raw runs under ignored local paths only.
- Commit only aggregate reports that pass privacy checks.
- Record whether real private eval ran and whether any performance claim is
  made in every PR body.
- Prefer no-go reports over premature implementation when evidence is missing.
- After each replanning gate, update blocked/backlog/ready status before
  starting another experiment PR.
- Keep integrated variants out of default runtime until `T-2026-0055` produces
  a decision packet and any required ADR work is reserved.

## First Next Task

Current main has completed the baseline refresh and retrieval diagnostics. The
next execution task is `T-2026-0030`; after that, run the early retrieval round
and `T-2026-0049` before widening into parser, embedding, query, context, or
generator experiments.
