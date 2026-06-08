# T-2026-0076 real100_v2 Retrieval Collapse Diagnosis

This reviewer note is aggregate-only. It intentionally omits raw case rows, queries, answers, doc IDs, chunk IDs, and text previews.

## Verdict

- Primary signal: `doc_ranking_collapse_not_chunk_id_only`
- Baseline comparability: `not_comparable_stack_changed`
- Recommendation: Re-run or instrument a same-stack page-aware MiniLM retrieval aggregate with explicit retrieval_backend provenance before T-2026-0030/T-2026-0032/T-2026-0033 optimization.

## Aggregate comparison

| Metric | Current page-aware | Hashing backup | Delta current-backup |
| --- | ---: | ---: | ---: |
| doc_hit_at_5 | 0.106618 | 0.529412 | -0.422794 |
| doc_hit_at_8 | 0.121324 | 0.613971 | -0.492647 |
| chunk_hit_at_5 | 0.011029 | 0.375 | -0.363971 |
| chunk_hit_at_8 | 0.011029 | 0.441176 | -0.430147 |
| chunk_recall_at_5 | 0.009191 | 0.369485 | -0.360294 |

## Stack comparison

- Changed stack fields: `embedding_backend, embedding_model_id, chunking_strategy, chunker_version, vector_store_backend`
- Current run manifest: `{"chunk_max_chars": 520, "chunk_overlap_sentences": 1, "chunker_version": "chunker.section.v1", "chunking_strategy": "section", "config_sha256": "be6e5dc606418192", "embedding_backend": "sentence-transformers", "embedding_dim": 384, "embedding_model_id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "git_commit": "5f91a933e83f", "git_dirty": false, "index_schema_version": 2, "vector_store_backend": "chroma"}`
- Backup run manifest: `{"chunk_max_chars": 520, "chunk_overlap_sentences": 1, "chunker_version": "chunker.fixed.v1", "chunking_strategy": "fixed", "config_sha256": "7ff7aa1454ded52e", "embedding_backend": "hashing", "embedding_dim": 384, "embedding_model_id": "local-hashing-bow", "git_commit": "e94603713d83", "git_dirty": false, "index_schema_version": 2}`

## Interpretation

The page-aware current run changed retrieval stack fields and shows a doc-level hit-rate collapse, so downstream reranker/window experiments should not treat the hashing backup as a comparable baseline.
