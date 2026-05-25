# 0077: Real-eval difficulty profile surface

- **Status**: accepted
- **Date**: 2026-05-25
- **Deciders**: hskim (solo author)
- **Related**: ADR 0001, ADR 0005, ADR 0052, ADR 0069, ADR 0075, ADR 0076

## Context

The private real-eval baseline can show low Naive RAG scores without telling a
reviewer whether the benchmark is globally invalid, globally too hard, or hard
only in specific slices such as multi-chunk evidence, table-heavy evidence, low
lexical overlap, or unanswerable questions.

Existing aggregate reports expose corpus EDA, pipeline dynamics, normalized
failure distribution, and multi-chunk failure analysis. They do not provide one
aggregate profile that joins difficulty buckets with Naive RAG retrieval,
citation, abstention, and failure outcomes.

The required inputs live in local-only artifacts:
`reports/real100/eval_summary.json::case_results` and
`data/index/real100/index.json::chunks`. These may contain private question
text, evidence text, document identifiers, chunk identifiers, filenames, and
paths, so ADR 0005 allows only aggregate outputs to cross the commit boundary.

## Decision

Add `scripts/render_difficulty_profile.py` as a read-only renderer that consumes
the local private eval summary and matching index, computes difficulty features
in memory, and emits:

- `reports/real100/difficulty_profile.aggregate.json`
- `reports/real100/difficulty_profile.md`

The aggregate schema is `schema_version: 1` and contains only safe provenance,
population counts, closed difficulty buckets, per-bucket metric means, failure
category distributions, validity counters, and explicit conclusions. The
renderer rejects non-Naive primary runs unless `--allow-non-naive` is passed, so
claims about Naive RAG do not accidentally use an agentic run.

Difficulty buckets include answerability, single-doc vs multi-doc gold
evidence, single-chunk vs multi-chunk gold evidence, expected-terms count,
date/amount/score-like question flags, table-like evidence, similar-clause
distractor proxy, gold evidence count, gold chunk length, and lexical overlap.
Lexical overlap and table detection may read private text locally, but only the
bucket labels and counts are written.

## Consequences

- Reviewers can distinguish "hard benchmark" from "invalid benchmark" using
  aggregate validity counters and per-slice outcomes.
- The report can justify benchmark splitting into easy sanity, standard real,
  and hard stress subsets without committing raw cases.
- Runtime RAG behavior is unchanged: retrieval, verifier, prompt, chunking,
  reranker, answer, and scorer paths do not import this renderer.
- The renderer cannot explain individual failures; per-case inspection remains
  local-only.

## Alternatives considered

- **Commit anonymized per-case rows**: rejected because joined bucket rows can
  still re-identify private cases through rare combinations.
- **Add new fields to eval runtime**: rejected because the needed diagnostics
  already exist and the task is aggregate-only analysis.
- **Use only existing aggregate baseline files**: rejected because difficulty
  joins require per-case local computation before aggregation.

## Verification

<!-- verifies-key: scripts/render_difficulty_profile.py:def build_aggregate -->
<!-- verifies-key: tests/test_render_difficulty_profile.py:test_schema_bucketization_and_no_raw_content_rendered -->
<!-- verifies-key: .gitignore:difficulty_profile.aggregate.json -->
