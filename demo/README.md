---
title: BidMate-DocAgent
emoji: 📄
colorFrom: indigo
colorTo: green
sdk: streamlit
sdk_version: 1.37.0
app_file: demo/streamlit_app.py
pinned: false
license: mit
---

# BidMate-DocAgent live demo

<!-- Hero asset slot — recorded walkthrough (60-90 s). See
     docs/operations/deployment.md#recording-the-demo-video for capture instructions.
     The same asset is referenced from the repo-root README. -->
![Live demo walkthrough](../docs/assets/demo.gif)

This directory holds the **reviewer-facing** demo UI. The Streamlit
front-page lets anyone exercise the RAG pipeline (extractive +
LLM-synthesis ablation) against the public synthetic RFP corpus
without writing any code.

The YAML frontmatter above is the **Hugging Face Spaces** config —
mirror it into the Space's `README.md` when you create the Space.

## Run locally

```bash
make index            # one-time, builds data/index from data/raw
make demo             # streamlit run demo/streamlit_app.py
# open http://localhost:8501
```

Or via Docker (Streamlit + FastAPI together):

```bash
make demo-docker
# open http://localhost:8501  (Streamlit UI)
# open http://localhost:8000/docs  (FastAPI Swagger)
```

## Deploy

See [`docs/operations/deployment.md`](../docs/operations/deployment.md) for full recipes.
Short version:

| Target | Steps |
|---|---|
| **Fly.io** | `flyctl launch --copy-config --name <your-name>` → `flyctl deploy` |
| **HF Spaces** | Create a new Streamlit Space; mirror this directory's `README.md` frontmatter; push. |
| **Railway** | Connect this repo; Railway auto-detects the `Dockerfile`; set `BIDMATE_DEMO_MODE=streamlit`. |

All three targets work with the default `stub` synthesis backend (no
API key, no billing). To enable live Claude synthesis (ADR 0011):

```bash
flyctl secrets set ANTHROPIC_API_KEY=sk-ant-... \\
                   BIDMATE_SYNTHESIS_BACKEND=anthropic
```

## What the demo shows

- **Pipeline picker** — `naive_baseline` (control) vs `agentic_full`
  (extractive) vs `agentic_full_llm` (LLM synthesis, ADR 0011).
- **Sample queries** for each query type (single-doc, comparison,
  follow-up, abstention) including the regression-guard cases
  (#69 partial-topic, #89 1-of-2 topic).
- **Side-by-side comparison** of extractive vs LLM synthesis on the
  same query — the ADR 0011 "zero regression under stub" contract
  becomes visible.
- **Evidence pane** showing the retrieved chunks with their
  `chunk_id`, `agency`, section path, and score.
- **Diagnostics pane** with stage latency, retry count, synthesis
  backend / fallback reason, embedding info.
- **Raw JSON** of the full answer + trace for reviewers who want to
  inspect the structured contract directly.

## Scope discipline

This is a **demo**, not the production surface:

- No authentication, rate limiting, or persistence.
- The demo runs the deterministic hashing embedding backend by
  default — quality numbers in the README ablation tables use the
  same backend so the demo and the reported metrics agree.
- For real RFP documents, run the pipeline via `app.py` /
  `api/main.py` / `eval/run_eval.py` against a built index.
