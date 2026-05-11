# 0009: External baseline comparison via a separate script

(Originally drafted as ADR 0008 alongside [#155](https://github.com/hskim-solv/BidMate-DocAgent/pull/155); renumbered to 0009 to avoid collision with the concurrent evidence-boundary ADR in [#144](https://github.com/hskim-solv/BidMate-DocAgent/pull/144), per the "numbers are never reused" rule in [docs/adr/README.md](./README.md).)

- **Status**: proposed
- **Date**: 2026-05-11
- **Related**: extends [ADR 0001](./0001-preserve-naive-baseline.md); reuses backend pattern from [ADR 0006](./0006-llm-judge-on-real-data-only.md)
- **Deciders**: hskim

## Context

[ADR 0001](./0001-preserve-naive-baseline.md) preserves `naive_baseline`
as the *internal* control, so every ablation has a "is the extra
machinery earning its keep?" comparison built in. The
[Limitations section of the README](../../README.md) explicitly flags a
gap: there is no comparison against an *external* framework. A
reviewer asking *"why build a custom pipeline instead of using
LangChain `RetrievalQA` or LlamaIndex `QueryEngine`?"* gets a prose
answer in `Why extractive, not generative?`, but no measurement.

Adding LangChain / LlamaIndex to `eval/config.yaml` as additional
ablations is the wrong shape because:

1. **Different dependency profile.** `langchain`, `langchain-community`,
   `faiss-cpu`, `llama-index`, `sentence-transformers` are
   100–300 MB of transitive deps that the rest of the project does not
   need. Adding them to `requirements.txt` taxes every contributor and
   every CI job.
2. **Different cost profile.** A faithful LangChain comparison needs
   an LLM (Anthropic / OpenAI). Per ADR 0004 / ADR 0006 the public CI
   path stays deterministic and free; tying the eval delta job to a
   paid API would break that invariant.
3. **Asymmetric metric coverage.** LangChain `RetrievalQA` returns
   `result` (free-text answer) + `source_documents`. It does not
   emit our structured `claims[].citations[].chunk_id` shape (ADR 0003).
   Some of our metrics (`citation_precision`, `citation_region_precision`,
   `claim_citation_alignment`, `answer_format_compliance`) have no
   defensible meaning when the external system does not produce the
   underlying signal.

The right shape is **a separate orchestration script** that produces a
parallel, smaller report covering only the metrics where both systems
can fairly compete.

## Decision

External baselines live in `scripts/compare_external_baselines.py` and
write to `reports/external_baselines.json`. They are **not** part of
`eval/config.yaml`'s `ablation_runs` and **not** part of
`make smoke` / `pr-eval.yml` / `make eval`.

### Symmetric metric subset

Only metrics whose definition is fair across systems are reported in
the comparison table:

| Metric | Our pipeline | LangChain RetrievalQA | LlamaIndex QueryEngine |
|---|---|---|---|
| `accuracy` (term match + doc match) | ✓ | ✓ | ✓ |
| `retrieval_recall@k` (expected_doc_ids ⊆ retrieved) | ✓ | ✓ | ✓ |
| `latency_ms` (wall-clock per query) | ✓ | ✓ | ✓ |
| `citation_precision` (chunk-level) | ✓ | ✗ (no chunk_id contract) | ✗ |
| `claim_citation_alignment` | ✓ | ✗ | ✗ |
| `abstention_accuracy` | ✓ (first-class status) | ✗ (free-text "I don't know" only) | ✗ |
| `answer_format_compliance` | ✓ (ADR 0003 JSON) | ✗ | ✗ |

The asymmetric columns are recorded as `null` in the external
columns, not omitted, so a future reader can see *which* dimensions the
external systems do not address — that is itself the answer to the
"why custom?" question.

### Backend pluggability

Reusing the ADR 0006 pattern, `BIDMATE_EXTERNAL_BACKEND` selects:

* `stub` (default) — deterministic fixture. Mirrors the API shape
  (free-text answer + source_documents) using a templated response
  derived from `expected_terms`. No network. Used by tests and by
  contributors without API keys. Stub *does not claim to compete* —
  it exists so the plumbing is exercised in CI.
* `langchain` — `langchain.chains.RetrievalQA` with
  `HuggingFaceEmbeddings` (matches our default embedding) + FAISS +
  `ChatAnthropic` (Claude). Requires `pip install langchain
  langchain-community langchain-anthropic faiss-cpu sentence-transformers`
  and `ANTHROPIC_API_KEY`.
* `llamaindex` — `llama_index.core.query_engine.RetrieverQueryEngine`
  with the same embedding + LLM. Same install footprint.

### Cadence

Manual. The author of a PR that materially changes retrieval or
answer generation re-runs the external comparison locally:

```bash
BIDMATE_EXTERNAL_BACKEND=langchain ANTHROPIC_API_KEY=... \\
  python3 scripts/compare_external_baselines.py
```

and attaches the resulting aggregate (`reports/external_baselines.json`)
to the PR if the relative comparison materially shifts. CI itself
never invokes the live backends.

### Commit boundary

`reports/external_baselines.json` is **committable** at the aggregate
level (mean ± CI per metric, n cases, backend, model). Per-case
external answers contain LLM-generated text whose privacy / licensing
implications we have not audited; they live in
`reports/external_baselines.local.json` which is git-ignored,
mirroring ADR 0005's split for the real-data surface.

## Consequences

**Wins**

- The "why not LangChain?" question gets a measurable answer for the
  metrics that both systems address.
- ADR 0001 invariant intact: `naive_baseline` and `agentic_full` /
  `agentic_full_llm` remain the internal controls.
- Public CI stays deterministic, free, and offline (ADR 0004 /
  ADR 0006). External backends are an opt-in side road.
- Backend abstraction is the same idiom already established by ADR 0006
  (`BIDMATE_JUDGE_BACKEND`) and ADR 0007
  (`BIDMATE_SYNTHESIS_BACKEND`) — readers learn it once.

**Costs**

- The comparison is **asymmetric by design**. A casual reader could
  misread N/A columns as a weakness of the external system; the
  README narrative must frame the asymmetry as a feature surface
  decision, not a bug.
- Two extra scripts to keep alive (`langchain` backend and
  `llamaindex` backend each have their own upstream API churn). Each
  backend is < 50 lines so the bus factor cost is small, but it is
  non-zero.
- Pre-computed sample comparisons committed to
  `reports/external_baselines.json` go stale if not refreshed. Same
  cadence convention as `reports/real100/` mitigates this.

**Constraints (unchanged)**

- ADR 0001 — `naive_baseline` stays in `pipeline_cli_choices()`.
- ADR 0003 — answer schema is not touched.
- ADR 0004 — public CI does not invoke external LLM endpoints.
- ADR 0005 — per-case LLM-generated text stays local.

## Alternatives considered

- **Add LangChain / LlamaIndex as ablation runs in
  `eval/config.yaml`.** Rejected for the three reasons in the
  Context section (dependencies, cost, asymmetric metrics).
- **Compare only on accuracy.** Rejected: accuracy alone hides the
  citation / abstention / format dimensions where the divergence
  actually matters for an RFP system, and the n=42 CI on accuracy
  (see ADR-free measurement work in [`eval/bootstrap.py`](../../eval/bootstrap.py))
  is too wide to be informative as a sole criterion.
- **Skip the external comparison entirely; rely on prose.**
  Rejected: prose claims about external systems are exactly the kind
  of unmeasured assertion the project tries to avoid. ADR 0001's
  defense of the internal baseline applies recursively — if the
  agentic pipeline is worth measuring against a naive one, it is
  also worth measuring against the most popular external framework.
