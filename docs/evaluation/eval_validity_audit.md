# Eval Validity Audit: Naive RAG Baseline

## TL;DR

Latest inspected run: `naive_baseline_20260524T054514Z`.

This run is a public fixture smoke/regression measurement over a tiny prebuilt index, not a real baseline benchmark. It exercises the real `run_rag_query()` code path, but the corpus, gold labels, answer scorers, and latency envelope are too constrained to judge RAG performance improvements.

## Latest Run Inspected

- Source report: `docs/evaluation/naive_rag_baseline_report.md`.
- Run ID: `naive_baseline_20260524T054514Z`.
- Reported dataset: 5 questions, 4 answerable and 1 unanswerable.
- Reported gold source: 0 explicit cases, 4 derived from `expected_doc_ids` + `expected_terms`.
- Reported metrics: Recall@5/10, MRR@5, nDCG@5, faithfulness, answer relevancy all `1.000`; citation accuracy `0.875`; hallucination rate `0.000`; unanswerable detection `0.000`; P95 latency `2.52 ms`.

The committed `experiments/runs/<run_id>/` artifacts are intentionally absent because run artifacts are `.gitignore` output. I reproduced the same smoke path into `/private/tmp/bidmate_eval_audit_runs/audit_repro` for per-case inspection without writing tracked files. The reproduced latency varied slightly, but the structural findings below are independent of that local timing.

## Classification

- Latest reported run: public fixture smoke evaluation.
- Related guardrail: golden regression coverage exists for `naive_baseline` ranking invariance, but that is a stability check, not a quality benchmark.
- Not a real baseline eval: the latest run is too small, uses a prebuilt public fixture index, and derives gold from the same indexed content.

## Is This Measuring Real Naive RAG?

Partially. The runner calls the real RAG query path, but the evaluation surface is smoke-sized.

- `scripts/run_naive_baseline_eval.py` is an eval wrapper. It filters `eval/config.yaml` to the `naive_baseline` row and delegates to `eval/run_eval.py`; it does not change retrieval, chunking, prompting, verifier, or answer behavior (`scripts/run_naive_baseline_eval.py:1-8`).
- `eval/run_eval.py` calls `run_rag_query()` for each case when `oracle_evidence_source` is not `"gold"` (`eval/run_eval.py:1307-1326`).
- The oracle gold-evidence injection path exists, but only activates when `oracle_evidence_source == "gold"` (`eval/run_eval.py:1282-1306`). The latest naive run does not set that option.
- The eval uses an existing `data/index` via `--index_dir`; it does not run ingestion, parsing, chunking, embedding build, or index build inside the timed/evaluated loop.
- The retriever does not receive gold evidence labels at query time. Gold evidence is derived after prediction and passed into `score_case()` (`eval/run_eval.py:1334-1345`).

There are no runtime mocks or cached/golden answers in the latest wrapper path. However, the repository also has explicit golden regression guards for `naive_baseline` ranking (`tests/test_naive_baseline_ranking_invariance.py:1-18`), and the latest report is based on public fixture smoke data. That makes it useful for regression stability, not for performance claims.

## Why The Retrieval Metrics Are Perfect

The perfect retrieval metrics are expected from the fixture design.

- `eval/config.yaml` declares this config as "Public fixture smoke evaluation for deterministic CI reproducibility" and says it is not a public benchmark (`eval/config.yaml:1-5`).
- The latest report has only 5 questions and 4 answerable retrieval-scored cases (`docs/evaluation/naive_rag_baseline_report.md:13-17`).
- The evaluated fixture corpus is only 5 documents / 6 chunks in `data/index`; the naive preset returns `top_k=5` (`rag_pipeline_presets.py:99-107`). Returning five chunks from a six-chunk corpus makes Recall@5 easy to saturate.
- The latest report says gold evidence is derived from `expected_doc_ids` + `expected_terms`, not independently annotated (`docs/evaluation/naive_rag_baseline_report.md:17`).
- The derivation scans the same loaded index and marks any chunk in an expected doc containing any expected term as gold (`eval/scorers/chunk_metrics.py:56-73`).
- Retrieval metrics then compare retrieved `chunk_id`s to those derived gold `chunk_id`s (`eval/scorers/case.py:169-181`).

The metric implementation itself is not loose: Recall/MRR/nDCG use exact `chunk_id` equality. The validity issue is that the gold labels are derived from the same tiny fixture chunks being retrieved, while the queries are authored with near-exact terms from those chunks. Several questions have direct lexical overlap with their target chunk, and the answerable cases ask for terms such as `보안 통제`, `매일`, and `분기별` that appear directly in the source text (`eval/config.yaml:185-236`).

## Why The Answer Metrics Are Perfect

The answer metrics are rule-based placeholders, not real semantic answer-quality evaluators.

- The contract explicitly describes `faithfulness` as a placeholder and `answer_relevancy` as expected-term containment (`docs/evaluation/naive_rag_eval_contract.md:99-107`).
- The wrapper maps `Faithfulness` to `groundedness` and `Answer relevancy` to `accuracy` (`scripts/run_naive_baseline_eval.py:36-40`).
- For answerable cases, `accuracy` is `1.0` when expected docs are in evidence and expected terms appear in answer plus evidence text; `groundedness` is `1.0` when expected terms appear and evidence is non-empty (`eval/scorers/case.py:127-133`).
- The answer text scorer uses both generated answer and evidence text (`eval/scorers/case.py:87-91`). This can award relevance when the retrieved evidence contains the expected terms, even if the rendered answer is verbose or poorly synthesized.
- The answer generator is deterministic extractive code, not LLM generation, unless `prompt_profile == "llm_synthesis"` (`rag_answer.py:102-132`, `rag_core.py:1079-1095`). The latest naive profile is `minimal_grounded_extractive`.
- Unanswerable cases set `accuracy`, `groundedness`, and `citation_precision` to `None`; only `abstention` is scored (`eval/scorers/case.py:134-147`). Therefore the failed abstention does not lower answer relevancy or faithfulness means.

The reported `Hallucination rate: 0.000` is also not a semantic hallucination metric. The wrapper computes it only from `failure_category_counts["generator_hallucination"]` (`scripts/run_naive_baseline_eval.py:255-276`). The failed abstention is categorized separately as `verifier_false_negative` / `answer: failed to abstain`, so it does not raise the hallucination headline.

## Why P95 Latency Is Millisecond-Level

The latency number is real for the direct code region it measures, but it is not end-to-end RAG system latency.

- `run_rag_query()` starts timing after config normalization and before the query phases (`rag_core.py:680-699`).
- The final `latency_ms` is computed inside `_phase_build_answer()` from that internal start time (`rag_core.py:1104-1131`).
- `eval/run_eval.py` aggregates per-case `latency_ms` from case results (`eval/run_eval.py:608-612`, `eval/run_eval.py:708-713`).
- Stage latency summaries for query analysis, context resolution, answer generation, retrieval, and verify are computed only from warm results; cold-start samples are separated (`eval/run_eval.py:637-675`).
- The run does not time ingestion, parsing, chunking, embedding/index build, or `load_index`.
- Retrieval is against a six-chunk hashing-embedding index, and answer generation is deterministic extraction. There is no LLM call in the latest naive path.

So `2.52 ms` is plausible for this smoke fixture, but it should be reported as warm in-process fixture latency, not product or real-corpus RAG latency.

## Citation And Page Metadata Failures

Citation problems are visible, but they are not fully reflected in the headline metrics.

- The latest report shows `page metadata missing: 5`, `missing page number: 5`, and `correct answer but wrong citation: 1` (`docs/evaluation/naive_rag_baseline_report.md:35-54`).
- Citation metadata coverage checks whether citations contain page/region metadata; missing page data yields `page_metadata_missing` (`eval/scorers/citation.py:157-210`).
- `scripts/run_naive_baseline_eval.py` records index-level page metadata absence as parsing and citation failure counts (`scripts/run_naive_baseline_eval.py:411-418`).
- Headline `Citation accuracy` is document/chunk precision over evidence, not page citation precision (`eval/scorers/case.py:104-110`, `eval/scorers/case.py:127-133`).
- Wrong citation can lower `citation_precision`, as seen in `0.875`, but it does not lower `groundedness` / headline `Faithfulness` because those metrics only require term match plus non-empty evidence.

Therefore citation page failures are trustworthy as failure counts, but not adequately represented by the headline citation/faithfulness summary.

## Unanswerable Detection

Unanswerable detection is implemented as a narrow abstention metric, and the latest score of `0.000` is meaningful for the single unanswerable smoke case.

- The unanswerable case is `smoke_abstention_missing_blockchain` with `answerable: false` (`eval/config.yaml:231-236`).
- For unanswerable cases, `abstention = 1.0` only if the system abstained; otherwise `0.0` (`eval/scorers/case.py:134-147`).
- The wrapper exports `Unanswerable detection rate` from the aggregate `abstention` metric (`scripts/run_naive_baseline_eval.py:269-276`).
- The latest report separately records `answer: failed to abstain: 1` (`docs/evaluation/naive_rag_baseline_report.md:49-54`).

The issue is not that unanswerable detection is hidden. The issue is that failed abstention is not counted in headline hallucination, answer relevancy, or faithfulness, so those headlines can remain perfect while an unanswerable safety case fails.

## Trustworthiness

Currently trustworthy:

- The eval runner really invokes `run_rag_query()` for the latest naive row.
- The latest run ID, dataset size, and public smoke nature in `naive_rag_baseline_report.md`.
- Exact chunk-id retrieval metric implementation on the smoke fixture.
- `citation_accuracy = 0.875` as a narrow chunk/doc citation precision signal.
- `missing page number` and `page metadata missing` failure counts as evidence of citation metadata absence.
- `unanswerable_detection = 0.000` for the single unanswerable smoke case.
- Latency as warm, in-process smoke-fixture latency only.

Not trustworthy for performance claims:

- Recall@5/10, MRR@5, and nDCG@5 as evidence of real retrieval performance.
- Faithfulness and answer relevancy as semantic answer quality.
- Hallucination rate as an overall unsupported-answer or failed-abstention rate.
- P95 latency as product, real-corpus, end-to-end, or LLM-backed latency.
- Any comparison that treats this public fixture run as a real baseline benchmark.

## Bugs And Design Issues

1. **Benchmark framing bug:** the report headline table can be mistaken for real baseline performance, despite being a smoke fixture.
2. **Gold derivation leakage:** latest gold evidence is derived from the same indexed chunks using expected terms, so retrieval is measured against labels created from the retrieval corpus itself.
3. **Corpus saturation:** `top_k=5` over 6 chunks makes retrieval metrics near-ceiling by construction.
4. **Answer metric naming mismatch:** `Faithfulness` and `Answer relevancy` are labels over rule-based `groundedness` / `accuracy`, not semantic evaluators.
5. **Unanswerable failure undercount in headlines:** failed abstention does not affect hallucination, faithfulness, or answer relevancy headlines.
6. **Citation metadata underweighting:** missing page numbers are counted as failures but do not lower headline citation accuracy or faithfulness.
7. **Latency ambiguity:** the report does not make clear that timing excludes ingestion/index build/load and runs over a six-chunk hashing index.

## Recommended Fixes

P0:

- Keep the current report framed as public fixture smoke, not real baseline benchmark.
- Do not use the current headline metrics for performance optimization or PR claims.
- Add a visible warning wherever the headline table is surfaced: these numbers are regression/smoke health only.

P1:

- Build a real naive baseline eval with a larger corpus, distractor chunks, independently authored queries, and explicit gold evidence/support spans.
- Separate smoke/golden regression artifacts from benchmark artifacts in filenames, docs, and summaries.
- Rename or clearly annotate `Faithfulness` and `Answer relevancy` as placeholder/rule-based metrics until real claim-to-evidence evaluation exists.
- Decide whether failed abstention should increment hallucination rate, answer failure rate, or a separate headline `unsafe_answer_rate`.

P2:

- Add citation page precision / page coverage to the headline or required artifact set.
- Report index size, embedding backend, timed code region, excluded setup costs, and cold/warm split beside latency.
- Add a random or adversarial distractor baseline sanity check to detect metric saturation.

## Bottom Line

The latest naive run is suitable for deterministic CI smoke and regression checks. It is not suitable for judging retrieval quality, answer quality, hallucination behavior, or latency improvements. Concrete eval validity fixes should land before any RAG performance optimization is claimed from these metrics.
