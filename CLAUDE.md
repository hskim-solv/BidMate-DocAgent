# CLAUDE.md

This repository is an RFP-focused DocAgent system.

Core product flow:
ingestion -> metadata normalization -> chunking -> retrieval -> reranking/planning -> evidence aggregation -> grounded answer -> verification -> evaluation -> reviewer-facing docs

Rules:
- Treat this as a Bid/RFP document intelligence system, not a generic AI playground.
- Preserve a naive baseline before adding advanced retrieval methods.
- Prefer metadata-aware retrieval where appropriate.
- Keep answers grounded in retrieved evidence.
- Favor reproducible evaluation and reviewer-friendly artifacts.
- Avoid unrelated abstractions and broad rewrites.
- Before coding, inspect the current implementation and explain what already exists.
- When changing code, name files affected, risks, and verification steps.
- Add or update tests when behavior changes.
- Keep backward compatibility unless there is a strong reason not to.
