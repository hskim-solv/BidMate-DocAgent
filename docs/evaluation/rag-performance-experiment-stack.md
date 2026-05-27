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
3. Run small-to-big retrieval, reranking, context packing, and query
   decomposition as separate opt-in experiments with paired aggregate deltas.
4. Add security, abstention, conflict, metadata, freshness, latency, and cost
   guardrails before any production-facing claim.
5. Gate advanced architectures behind no-go/go feasibility evidence.

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

## Existing Evidence To Respect

- Page metadata recovery is available on current main through `T-2026-0024`.
- MiniLM and BGE-M3 semantic private real-eval targets are separated through
  `T-2026-0025`.
- The hybrid sweep report found recall-only gains but ranking and latency
  regressions; do not reopen hybrid as a broad "just add BM25" change.
- The multi-chunk strategy report deferred retrieval changes until page-aware
  evidence can distinguish same-document from multi-document evidence splits.
- `T-2026-0026` tracks Chroma as a vector DB backend baseline. Treat it as
  backend parity, provenance, latency, and operations work unless paired
  same-embedding deltas prove ranking drift.

## Priority Stack

| Priority | Task | Status | Why this order |
|---|---|---|---|
| P0 | `T-2026-0028` Private coverage and semantic baseline refresh | ready after this PR | Establish the current baseline and coverage before experiments. |
| P0 | `T-2026-0029` Retrieval diagnostic workbench | backlog | Explain recall/rank/candidate-pool failures before behavior changes. |
| P0 | `T-2026-0030` Latency and cost budget envelope | backlog | Prevent multi-query/rerank/compression experiments from winning on quality while breaking operations. |
| P1 | `T-2026-0031` Parent/section-window retrieval experiment | backlog | Highest-value retrieval change after page-aware evidence. |
| P1 | `T-2026-0032` Reranker candidate-budget experiment | backlog | Improve precision only after candidate-pool recall is observable. |
| P1 | `T-2026-0033` Context packing and citation ordering experiment | backlog | Use found evidence better without changing corpus or embeddings. |
| P1 | `T-2026-0034` Query rewrite and decomposition experiment | backlog | Target comparison, multi-hop, abbreviation, and mixed Korean/English queries. |
| P1 | `T-2026-0035` Prompt-injection and data/command boundary guardrail | backlog | Security must be a guardrail before more agentic or tool-using retrieval. |
| P2 | `T-2026-0036` Abstention, conflict, and freshness calibration | backlog | Improve no-answer and precedence behavior after retrieval evidence is stable. |
| P2 | `T-2026-0037` Metadata, authority, and freshness ranking experiment | backlog | Use RFP metadata only after coverage and missing-field behavior are measured. |
| P2 | `T-2026-0038` Contextual retrieval and sentence-window proof of concept | backlog | Test chunk-context enrichment after simpler small-to-big retrieval. |
| P3 | `T-2026-0039` Advanced architecture feasibility gate | backlog | Evaluate RAPTOR, GraphRAG, LightRAG, Agentic RAG, late chunking, multi-vector, and long-context only after P0/P1 evidence. |

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

## First Next Task

Start with `T-2026-0028`. It should refresh the aggregate baseline after page
metadata recovery and MiniLM target separation, then decide which diagnostic
task is truly ready.
