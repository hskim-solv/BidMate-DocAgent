"""FastAPI demo surface for the BidMate-DocAgent RAG pipeline.

This package is intentionally thin — see ``api/main.py`` for the app and
``docs/operations/api-demo.md`` for the end-to-end startup flow. The CLI evaluation
flow (``scripts/build_index.py``, ``app.py``, ``eval/run_eval.py``) remains
the source of truth; this package only wraps :func:`rag_core.run_rag_query`
behind HTTP so reviewers can poke the system without stitching commands
together.
"""
