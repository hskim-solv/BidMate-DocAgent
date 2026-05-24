"""Build the Naive RAG benchmark index from frozen corpus chunks only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from rag_embedding import DEFAULT_EMBEDDING_MODEL, embed_texts  # noqa: E402
from rag_indexing import INDEX_SCHEMA_VERSION, write_index  # noqa: E402
from rag_text_processing import tokenize  # noqa: E402
from rag_vector_store import EMBEDDINGS_FILENAME, vector_store_from_matrix  # noqa: E402


PROHIBITED_CORPUS_FIELDS = frozenset(
    {
        "question",
        "question_id",
        "expected_answer",
        "expected_evidence_ids",
        "expected_terms",
        "gold_evidence",
        "evidence_id",
        "support_text",
        "support_type",
        "required",
        "derived_from_expected_terms",
    }
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT_DIR / path


def display_path(value: Path) -> str:
    try:
        return str(value.relative_to(ROOT_DIR))
    except ValueError:
        return str(value)


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{lineno}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"Corpus chunk row must be an object at {path}:{lineno}")
        rows.append(row)
    return rows


def load_corpus_chunks(path: Path) -> list[dict[str, Any]]:
    chunks = _jsonl_rows(path)
    if not chunks:
        raise ValueError(f"No benchmark corpus chunks found: {path}")

    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for idx, row in enumerate(chunks, start=1):
        leaked = sorted(PROHIBITED_CORPUS_FIELDS & set(row))
        if leaked:
            raise ValueError(
                f"Benchmark corpus chunk row {idx} contains label/query fields: {', '.join(leaked)}"
            )
        chunk_id = str(row.get("chunk_id") or "").strip()
        doc_id = str(row.get("doc_id") or "").strip()
        text = str(row.get("text") or "").strip()
        if not chunk_id:
            raise ValueError(f"Benchmark corpus chunk row {idx} missing chunk_id")
        if chunk_id in seen:
            raise ValueError(f"Duplicate benchmark chunk_id: {chunk_id}")
        if not doc_id:
            raise ValueError(f"Benchmark corpus chunk {chunk_id} missing doc_id")
        if not text:
            raise ValueError(f"Benchmark corpus chunk {chunk_id} missing text")

        chunk = dict(row)
        chunk["chunk_id"] = chunk_id
        chunk["doc_id"] = doc_id
        chunk["text"] = text
        if not isinstance(chunk.get("tokens"), list):
            section_path = chunk.get("section_path") if isinstance(chunk.get("section_path"), list) else []
            chunk["tokens"] = tokenize(
                " ".join(
                    [
                        str(chunk.get("title") or ""),
                        str(chunk.get("agency") or ""),
                        " > ".join(str(part) for part in section_path),
                        text,
                    ]
                )
            )
        chunk.pop("embedding", None)
        chunk.pop("embedding_idx", None)
        cleaned.append(chunk)
        seen.add(chunk_id)
    return cleaned


def _documents_from_chunks(chunks: list[dict[str, Any]], corpus_path: Path) -> list[dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        doc_id = str(chunk["doc_id"])
        if doc_id in documents:
            continue
        documents[doc_id] = {
            "doc_id": doc_id,
            "title": str(chunk.get("title") or doc_id),
            "agency": str(chunk.get("agency") or ""),
            "project": str(chunk.get("project") or ""),
            "metadata": chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {},
            "source_path": str(corpus_path),
        }
    return list(documents.values())


def _parent_sections_from_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parents: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        parent_id = str(
            chunk.get("parent_section_id")
            or chunk.get("section_id")
            or f"{chunk['doc_id']}::{chunk.get('section') or 'section'}"
        )
        parent = parents.setdefault(
            parent_id,
            {
                "section_id": parent_id,
                "doc_id": str(chunk.get("doc_id") or ""),
                "title": str(chunk.get("title") or ""),
                "agency": str(chunk.get("agency") or ""),
                "project": str(chunk.get("project") or ""),
                "metadata": chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {},
                "section": str(chunk.get("section") or ""),
                "section_path": chunk.get("section_path") if isinstance(chunk.get("section_path"), list) else [],
                "chunking_strategy": str(chunk.get("chunking_strategy") or "section"),
                "text_parts": [],
            },
        )
        if chunk.get("regions") and "regions" not in parent:
            parent["regions"] = chunk.get("regions")
        if chunk.get("page_span") and "page_span" not in parent:
            parent["page_span"] = chunk.get("page_span")
        parent["text_parts"].append(str(chunk.get("text") or ""))

    normalized = []
    for parent in parents.values():
        text_parts = parent.pop("text_parts", [])
        parent["text"] = " ".join(part for part in text_parts if part).strip()
        normalized.append(parent)
    return normalized


def build_index_payload_from_corpus_chunks(
    corpus_path: Path,
    *,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    embedding_backend: str = "hashing",
) -> dict[str, Any]:
    corpus_path = repo_path(corpus_path)
    chunks = load_corpus_chunks(corpus_path)
    documents = _documents_from_chunks(chunks, corpus_path)
    parent_sections = _parent_sections_from_chunks(chunks)

    embedding_inputs = [
        " ".join(
            [
                str(chunk.get("title") or ""),
                str(chunk.get("agency") or ""),
                " > ".join(
                    str(part)
                    for part in (
                        chunk.get("section_path")
                        if isinstance(chunk.get("section_path"), list)
                        else [str(chunk.get("section") or "")]
                    )
                ),
                str(chunk.get("text") or ""),
            ]
        )
        for chunk in chunks
    ]
    embedding_result = embed_texts(embedding_inputs, model_name=model_name, backend=embedding_backend)
    vectors_matrix = np.asarray(embedding_result.vectors, dtype=np.float32)
    for idx, chunk in enumerate(chunks):
        chunk["embedding_idx"] = idx

    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "mode": "rag",
        "message": "Naive RAG benchmark v1 index built from frozen corpus chunks only.",
        "embedding": {
            "backend": embedding_result.backend,
            "model": embedding_result.model,
            "dimension": int(embedding_result.vectors.shape[1]),
            "normalized": True,
            "storage": "sidecar_npy",
        },
        "build": {
            "input_kind": "corpus_chunks_jsonl",
            "source_corpus_path": display_path(corpus_path),
            "num_documents": len(documents),
            "num_chunks": len(chunks),
            "num_parent_sections": len(parent_sections),
            "leakage_guard": "query_and_gold_label_files_not_read",
        },
        "documents": documents,
        "parent_sections": parent_sections,
        "chunks": chunks,
        "_vector_store": vector_store_from_matrix(vectors_matrix),
    }


def build_benchmark_index(
    corpus_path: Path,
    output_dir: Path,
    *,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    embedding_backend: str = "hashing",
) -> Path:
    payload = build_index_payload_from_corpus_chunks(
        corpus_path,
        model_name=model_name,
        embedding_backend=embedding_backend,
    )
    output_dir = repo_path(output_dir)
    num_docs = payload["build"]["num_documents"]
    num_chunks = payload["build"]["num_chunks"]
    backend = payload["embedding"]["backend"]
    out_path = write_index(payload, output_dir)
    print(
        "[OK] Naive RAG benchmark index written: "
        f"{out_path} (+ {EMBEDDINGS_FILENAME}, {num_docs} docs, "
        f"{num_chunks} chunks, embedding={backend})"
    )
    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the Naive RAG benchmark v1 index from corpus_chunks_v1.jsonl."
    )
    parser.add_argument("--corpus", required=True, help="Path to data/eval/benchmark/corpus_chunks_v1.jsonl")
    parser.add_argument("--output", required=True, help="Path to write index_v1")
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL, help="Embedding model name")
    parser.add_argument(
        "--embedding_backend",
        default="hashing",
        choices=["hashing", "sentence-transformers", "openai", "auto"],
        help="Embedding backend. Benchmark v1 defaults to deterministic hashing.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        build_benchmark_index(
            Path(args.corpus),
            Path(args.output),
            model_name=args.model,
            embedding_backend=args.embedding_backend,
        )
    except Exception as exc:
        print(f"[ERROR] Naive RAG benchmark index build failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
