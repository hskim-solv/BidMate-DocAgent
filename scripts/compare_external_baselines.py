#!/usr/bin/env python3
"""External baseline comparison (ADR 0009).

Runs LangChain ``RetrievalQA`` or LlamaIndex ``QueryEngine`` against
the same public synthetic eval cases used by ``eval/run_eval.py`` and
emits a symmetric-metric aggregate to ``reports/external_baselines.json``
plus per-case detail to ``reports/external_baselines.local.json``
(git-ignored).

The symmetric metric subset (accuracy / retrieval_recall@k / latency)
is the only honest comparison surface — external systems do not produce
the structured ``claims[].citations[]`` shape required for the
asymmetric metrics (citation_precision, claim_citation_alignment,
abstention_accuracy, answer_format_compliance). See ADR 0009 for the
methodology decision.

Backends (selected by ``BIDMATE_EXTERNAL_BACKEND``):

* ``stub`` (default) — deterministic mock. Mirrors the API shape using
  a templated response derived from ``expected_terms``; not a quality
  claim about external systems. Used by tests / CI / contributors
  without API keys.
* ``langchain`` — ``langchain.chains.RetrievalQA`` with
  ``HuggingFaceEmbeddings`` (matches our default
  ``paraphrase-multilingual-MiniLM-L12-v2``) + FAISS retriever +
  ``ChatAnthropic`` (Claude). Requires
  ``pip install langchain langchain-community langchain-anthropic
  faiss-cpu sentence-transformers`` and ``ANTHROPIC_API_KEY``.
* ``llamaindex`` — ``llama_index.core.query_engine.RetrieverQueryEngine``
  with the same embedding + LLM stack.

Usage::

    python3 scripts/compare_external_baselines.py           # stub
    BIDMATE_EXTERNAL_BACKEND=langchain \\
        ANTHROPIC_API_KEY=... \\
        python3 scripts/compare_external_baselines.py

Per ADR 0009 this script is **not** invoked by ``make smoke`` or
``pr-eval.yml``; CI stays deterministic and free.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import yaml

from eval.bootstrap import bootstrap_ci

DEFAULT_CONFIG_PATH = ROOT_DIR / "eval" / "config.yaml"
DEFAULT_CORPUS_DIR = ROOT_DIR / "data" / "raw"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "reports" / "external_baselines.json"
DEFAULT_LOCAL_PATH = ROOT_DIR / "reports" / "external_baselines.local.json"

DEFAULT_TOP_K = 4
DEFAULT_CHUNK_SIZE = 520
DEFAULT_CHUNK_OVERLAP = 80
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_LLM_MODEL = "claude-sonnet-4-6"

ASYMMETRIC_KEYS = (
    "citation_precision",
    "claim_citation_alignment",
    "abstention_accuracy",
    "answer_format_compliance",
)


# -----------------------------------------------------------------------------
# Corpus + cases
# -----------------------------------------------------------------------------


def load_cases(config_path: Path) -> list[dict[str, Any]]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    cases = config.get("cases") or []
    if not isinstance(cases, list):
        raise ValueError(f"{config_path}: cases must be a list.")
    return [case for case in cases if isinstance(case, dict)]


def load_corpus(corpus_dir: Path) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for path in sorted(corpus_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or not data.get("doc_id"):
            continue
        sections = data.get("sections") or []
        text_parts: list[str] = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            heading = str(section.get("heading") or "").strip()
            text = str(section.get("text") or "").strip()
            if heading:
                text_parts.append(heading)
            if text:
                text_parts.append(text)
        docs.append(
            {
                "doc_id": str(data["doc_id"]),
                "title": str(data.get("title") or ""),
                "agency": str(data.get("agency") or ""),
                "text": "\n".join(text_parts).strip(),
            }
        )
    return docs


def chunk_text(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    n = len(text)
    step = max(1, chunk_size - overlap)
    while start < n:
        end = min(start + chunk_size, n)
        chunks.append(text[start:end])
        if end >= n:
            break
        start += step
    return chunks


# -----------------------------------------------------------------------------
# Scoring (symmetric metric subset)
# -----------------------------------------------------------------------------


def score_case(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    answerable = bool(case.get("answerable", True))
    expected_doc_ids = [
        str(d) for d in (case.get("expected_doc_ids") or []) if d is not None
    ]
    expected_terms = [
        str(t) for t in (case.get("expected_terms") or []) if t is not None
    ]
    retrieved_doc_ids = [
        str(d) for d in (result.get("retrieved_doc_ids") or []) if d
    ]
    answer_text = str(result.get("answer_text") or "")

    if expected_doc_ids:
        doc_hits = sum(1 for d in expected_doc_ids if d in retrieved_doc_ids)
        retrieval_recall = doc_hits / len(expected_doc_ids)
        doc_match = doc_hits == len(expected_doc_ids)
    else:
        retrieval_recall = None
        doc_match = True

    if expected_terms:
        term_match = all(term in answer_text for term in expected_terms)
    else:
        term_match = True

    if answerable:
        accuracy = 1.0 if (doc_match and term_match) else 0.0
    else:
        accuracy = 1.0 if not answer_text.strip() or _looks_like_abstention(answer_text) else 0.0

    return {
        "accuracy": accuracy,
        "retrieval_recall": retrieval_recall,
        "latency_ms": result.get("latency_ms"),
    }


def _looks_like_abstention(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return True
    markers = (
        "i don't know",
        "i do not know",
        "no information",
        "not provided",
        "근거 부족",
        "정보가 없",
        "확인할 수 없",
    )
    return any(marker in lowered for marker in markers)


# -----------------------------------------------------------------------------
# Backends
# -----------------------------------------------------------------------------


def _stub_backend_init(corpus: list[dict[str, Any]]) -> dict[str, Any]:
    return {"corpus": corpus, "model": "stub"}


def _stub_backend_query(state: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    expected_terms = [
        str(t) for t in (case.get("expected_terms") or []) if t is not None
    ]
    expected_doc_ids = [
        str(d) for d in (case.get("expected_doc_ids") or []) if d is not None
    ]
    answerable = bool(case.get("answerable", True))
    started = time.perf_counter()
    if answerable and expected_terms:
        answer_text = " ".join(expected_terms)
    elif not answerable:
        answer_text = "근거 부족"
    else:
        answer_text = ""
    retrieved = expected_doc_ids[:DEFAULT_TOP_K] if expected_doc_ids else [
        doc["doc_id"] for doc in state["corpus"][:DEFAULT_TOP_K]
    ]
    latency_ms = round((time.perf_counter() - started) * 1000, 4)
    return {
        "answer_text": answer_text,
        "retrieved_doc_ids": retrieved,
        "latency_ms": latency_ms,
        "model": state["model"],
    }


def _langchain_backend_init(corpus: list[dict[str, Any]]) -> dict[str, Any]:  # pragma: no cover - external SDK
    try:
        from langchain.chains import RetrievalQA
        from langchain.docstore.document import Document
        from langchain_community.embeddings import HuggingFaceEmbeddings
        from langchain_community.vectorstores import FAISS
        from langchain_anthropic import ChatAnthropic
    except Exception as exc:
        raise RuntimeError(
            "langchain backend requires `pip install langchain langchain-community "
            "langchain-anthropic faiss-cpu sentence-transformers` or "
            "BIDMATE_EXTERNAL_BACKEND=stub."
        ) from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    model = os.environ.get("BIDMATE_EXTERNAL_MODEL") or DEFAULT_LLM_MODEL
    embedding_model = os.environ.get("BIDMATE_EXTERNAL_EMBEDDING") or DEFAULT_EMBEDDING_MODEL

    documents: list[Any] = []
    for doc in corpus:
        for chunk in chunk_text(doc["text"], chunk_size=DEFAULT_CHUNK_SIZE, overlap=DEFAULT_CHUNK_OVERLAP):
            documents.append(
                Document(
                    page_content=chunk,
                    metadata={"doc_id": doc["doc_id"], "agency": doc["agency"]},
                )
            )

    embedder = HuggingFaceEmbeddings(model_name=embedding_model)
    vector_store = FAISS.from_documents(documents, embedder)
    retriever = vector_store.as_retriever(search_kwargs={"k": DEFAULT_TOP_K})
    llm = ChatAnthropic(model=model, temperature=0.0, anthropic_api_key=api_key)
    chain = RetrievalQA.from_chain_type(
        llm=llm, retriever=retriever, return_source_documents=True
    )
    return {"chain": chain, "model": model, "embedding": embedding_model}


def _langchain_backend_query(state: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - external SDK
    query = str(case.get("query") or "")
    started = time.perf_counter()
    response = state["chain"].invoke({"query": query})
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    answer_text = str(response.get("result") or "")
    source_documents = response.get("source_documents") or []
    retrieved_doc_ids: list[str] = []
    for doc in source_documents:
        doc_id = (doc.metadata or {}).get("doc_id")
        if doc_id and doc_id not in retrieved_doc_ids:
            retrieved_doc_ids.append(str(doc_id))
    return {
        "answer_text": answer_text,
        "retrieved_doc_ids": retrieved_doc_ids,
        "latency_ms": latency_ms,
        "model": state["model"],
    }


def _llamaindex_backend_init(corpus: list[dict[str, Any]]) -> dict[str, Any]:  # pragma: no cover - external SDK
    try:
        from llama_index.core import Document, VectorStoreIndex, Settings
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
        from llama_index.llms.anthropic import Anthropic
    except Exception as exc:
        raise RuntimeError(
            "llamaindex backend requires `pip install llama-index "
            "llama-index-embeddings-huggingface llama-index-llms-anthropic` "
            "or BIDMATE_EXTERNAL_BACKEND=stub."
        ) from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    model = os.environ.get("BIDMATE_EXTERNAL_MODEL") or DEFAULT_LLM_MODEL
    embedding_model = os.environ.get("BIDMATE_EXTERNAL_EMBEDDING") or DEFAULT_EMBEDDING_MODEL

    Settings.embed_model = HuggingFaceEmbedding(model_name=embedding_model)
    Settings.llm = Anthropic(model=model, api_key=api_key, temperature=0.0)

    documents: list[Any] = []
    for doc in corpus:
        documents.append(
            Document(text=doc["text"], metadata={"doc_id": doc["doc_id"], "agency": doc["agency"]})
        )
    index = VectorStoreIndex.from_documents(documents)
    query_engine = index.as_query_engine(similarity_top_k=DEFAULT_TOP_K)
    return {"engine": query_engine, "model": model, "embedding": embedding_model}


def _llamaindex_backend_query(state: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - external SDK
    query = str(case.get("query") or "")
    started = time.perf_counter()
    response = state["engine"].query(query)
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    answer_text = str(response)
    retrieved_doc_ids: list[str] = []
    for node in getattr(response, "source_nodes", None) or []:
        meta = (getattr(node, "metadata", None) or {})
        doc_id = meta.get("doc_id")
        if doc_id and doc_id not in retrieved_doc_ids:
            retrieved_doc_ids.append(str(doc_id))
    return {
        "answer_text": answer_text,
        "retrieved_doc_ids": retrieved_doc_ids,
        "latency_ms": latency_ms,
        "model": state["model"],
    }


_BACKENDS: dict[str, dict[str, Any]] = {
    "stub": {"init": _stub_backend_init, "query": _stub_backend_query},
    "langchain": {"init": _langchain_backend_init, "query": _langchain_backend_query},
    "llamaindex": {"init": _llamaindex_backend_init, "query": _llamaindex_backend_query},
}


# -----------------------------------------------------------------------------
# Pipeline
# -----------------------------------------------------------------------------


def run_comparison(
    cases: list[dict[str, Any]],
    corpus: list[dict[str, Any]],
    *,
    backend: str = "stub",
) -> tuple[dict[str, Any], dict[str, Any]]:
    if backend not in _BACKENDS:
        raise ValueError(
            f"Unknown backend {backend!r}; choose one of {sorted(_BACKENDS)}."
        )
    state = _BACKENDS[backend]["init"](corpus)
    query_fn = _BACKENDS[backend]["query"]

    per_case: list[dict[str, Any]] = []
    for case in cases:
        result = query_fn(state, case)
        scored = score_case(case, result)
        per_case.append(
            {
                "id": case.get("id"),
                "query": case.get("query"),
                "answerable": bool(case.get("answerable", True)),
                "expected_doc_ids": case.get("expected_doc_ids") or [],
                "expected_terms": case.get("expected_terms") or [],
                "answer_text": result.get("answer_text"),
                "retrieved_doc_ids": result.get("retrieved_doc_ids"),
                "accuracy": scored["accuracy"],
                "retrieval_recall": scored["retrieval_recall"],
                "latency_ms": scored["latency_ms"],
            }
        )

    accuracy = [c["accuracy"] for c in per_case if c.get("accuracy") is not None]
    recall = [c["retrieval_recall"] for c in per_case if c.get("retrieval_recall") is not None]
    latencies = [c["latency_ms"] for c in per_case if c.get("latency_ms") is not None]

    aggregate = {
        "schema_version": 1,
        "backend": backend,
        "model": state.get("model") if isinstance(state, dict) else None,
        "n_cases": len(per_case),
        "metrics": {
            "accuracy": _summary(accuracy),
            "retrieval_recall": _summary(recall),
            "latency_ms": _latency_summary(latencies),
        },
        "asymmetric_metrics": {key: None for key in ASYMMETRIC_KEYS},
        "asymmetric_metrics_note": (
            "External baselines do not produce the structured "
            "claims[].citations[] shape required for chunk-level "
            "citation metrics or first-class abstention status. See "
            "docs/adr/0009-external-baseline-comparison.md."
        ),
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    local_payload = {
        "schema_version": 1,
        "backend": backend,
        "model": aggregate["model"],
        "cases": per_case,
        "generated_at": aggregate["generated_at"],
    }
    return aggregate, local_payload


def _summary(values: list[float]) -> dict[str, Any] | None:
    if not values:
        return None
    return bootstrap_ci(values)


def _latency_summary(values: list[float]) -> dict[str, Any] | None:
    if not values:
        return None
    arr = sorted(float(v) for v in values)
    p50 = arr[len(arr) // 2]
    p95_idx = max(0, int(round(0.95 * (len(arr) - 1))))
    return {
        "p50_ms": round(p50, 2),
        "p95_ms": round(arr[p95_idx], 2),
        "mean_ms": round(sum(arr) / len(arr), 2),
        "n": len(arr),
    }


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS_DIR))
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    ap.add_argument("--local-output", default=str(DEFAULT_LOCAL_PATH))
    ap.add_argument(
        "--backend",
        default=os.environ.get("BIDMATE_EXTERNAL_BACKEND", "stub"),
        choices=sorted(_BACKENDS),
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    corpus_dir = Path(args.corpus)
    if not config_path.exists():
        print(f"[ERROR] Eval config not found: {config_path}", file=sys.stderr)
        return 2
    if not corpus_dir.exists():
        print(f"[ERROR] Corpus directory not found: {corpus_dir}", file=sys.stderr)
        return 2

    cases = load_cases(config_path)
    corpus = load_corpus(corpus_dir)
    if not corpus:
        print(f"[ERROR] No documents in {corpus_dir}", file=sys.stderr)
        return 2

    aggregate, local_payload = run_comparison(cases, corpus, backend=args.backend)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] Aggregate written: {out_path}")

    local_path = Path(args.local_output)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(json.dumps(local_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] Per-case detail written: {local_path}")

    print(json.dumps(aggregate["metrics"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
