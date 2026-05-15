"""Document ingestion + index build/load extracted from ``rag_core.py``.

ADR 0045 G3 / issue #858 — second large extraction in the rag_core
slim-down series after ``rag_embedding`` (G2 / issue #843).  Moves the
raw-document → chunk → index-payload pipeline plus the index I/O
layer into a single leaf module.

Public surface:

- ``load_raw_documents`` / ``normalize_json_document`` /
  ``normalize_text_document`` — read JSON/MD/TXT under ``data/raw/``
  and produce the normalized in-memory document shape.
- ``validate_chunking_options`` / ``resolve_chunking_strategy`` —
  guard rails around the ``auto`` / ``section`` / ``fixed`` choice.
- ``build_chunk_records`` / ``build_chunks`` / ``make_chunk`` —
  document → chunk records with section / parent_section_id /
  chunking diagnostics.
- ``build_index_payload`` / ``build_index_payload_from_documents`` —
  raw / pre-loaded document path through chunking → embeddings →
  index-payload dict.  The output is the schema-2 in-memory shape
  consumed by ``run_rag_query`` and ``scripts/build_index.py``.
- ``load_index`` / ``write_index`` — atomic JSON + ``embeddings.npy``
  sidecar round-trip.
- ``known_entities`` / ``metadata_targets`` — small index→derived-list
  helpers used by the analysis and retrieval surface.

Constants:

- ``DEFAULT_CHUNK_MAX_CHARS = 520`` — naive-baseline canonical value.
- ``DEFAULT_CHUNK_OVERLAP_SENTENCES = 1`` — naive-baseline canonical.
- ``VALID_CHUNKING_STRATEGIES = {"auto", "section", "fixed"}``.
- ``INDEX_FILENAME = "index.json"`` — the on-disk JSON shape.
- ``INDEX_SCHEMA_VERSION = 2`` — current ``schema_version`` field.

Leaf status: depends only on ``rag_text_processing`` (`tokenize`,
``normalize_entity``), ``rag_metadata_processing`` (`normalize_regions`,
``normalize_page_span``, ``normalize_document_sections``,
``fixed_parent_section``, ``split_section_text``,
``make_metadata_target``), ``rag_embedding`` (`embed_texts`,
``DEFAULT_EMBEDDING_MODEL``), and ``rag_vector_store``
(`vector_store_from_matrix`, ``load_vector_store``,
``EMBEDDINGS_FILENAME``) — every one of these is itself a leaf.  Zero
back-edges to ``rag_core`` / ``rag_retrieval`` / ``rag_query`` /
``rag_verifier`` / ``rag_answer``.

``rag_core`` re-exports every public symbol so existing call sites
(`from rag_core import build_index_payload`, etc.) keep working
unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from rag_embedding import DEFAULT_EMBEDDING_MODEL, embed_texts
from rag_metadata_processing import (
    fixed_parent_section,
    make_metadata_target,
    normalize_document_sections,
    normalize_page_span,
    normalize_regions,
    split_section_text,
)
from rag_text_processing import normalize_entity, tokenize
from rag_vector_store import (
    EMBEDDINGS_FILENAME,
    load_vector_store,
    vector_store_from_matrix,
)


DEFAULT_CHUNK_MAX_CHARS = 520
DEFAULT_CHUNK_OVERLAP_SENTENCES = 1
VALID_CHUNKING_STRATEGIES = {"auto", "section", "fixed"}

INDEX_FILENAME = "index.json"
INDEX_SCHEMA_VERSION = 2


def load_raw_documents(input_dir: Path) -> list[dict[str, Any]]:
    files = sorted(
        p
        for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in {".json", ".md", ".txt"}
    )
    documents: list[dict[str, Any]] = []
    for path in files:
        if path.name.startswith("."):
            continue
        # E2 OOD corpus (data/ood_synthetic_legal/, ADR 0046) writes
        # ``manifest.json`` and ``README.md`` siblings recording corpus
        # metadata. Neither is a document — skip both so ``build_index``
        # treats the directory as exactly the contract files. RFP corpora
        # under ``data/raw/`` ship neither file, so the existing path
        # stays byte-identical (ADR 0001 invariant preserved).
        if path.name in {"manifest.json", "README.md"}:
            continue
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            documents.append(normalize_json_document(data, path))
        else:
            documents.append(normalize_text_document(path))
    if not documents:
        raise ValueError(f"No JSON/Markdown/Text documents found in {input_dir}")
    return documents


def normalize_json_document(data: dict[str, Any], path: Path) -> dict[str, Any]:
    doc_id = str(data.get("doc_id") or path.stem)
    title = str(data.get("title") or path.stem)
    agency = str(data.get("agency") or "")
    project = str(data.get("project") or "")
    sections = data.get("sections") or []
    if not isinstance(sections, list) or not sections:
        text = str(data.get("text") or "")
        sections = [{"heading": "본문", "text": text}]
    normalized_sections = []
    for idx, section in enumerate(sections, start=1):
        heading = str(section.get("heading") or f"section-{idx}")
        text = str(section.get("text") or "").strip()
        if text:
            normalized_section = {"heading": heading, "text": text}
            if section.get("section_path"):
                normalized_section["section_path"] = section.get("section_path")
            regions = normalize_regions(section.get("regions"))
            page_span = normalize_page_span(section.get("page_span"), regions)
            if regions:
                normalized_section["regions"] = regions
            if page_span:
                normalized_section["page_span"] = page_span
            normalized_sections.append(normalized_section)
    if not normalized_sections:
        raise ValueError(f"Document has no text: {path}")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    return {
        "doc_id": doc_id,
        "title": title,
        "agency": agency,
        "project": project,
        "metadata": metadata,
        "sections": normalized_sections,
        "source_path": str(path),
    }


def normalize_text_document(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Document has no text: {path}")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = lines[0].lstrip("# ").strip() if lines else path.stem
    return {
        "doc_id": path.stem,
        "title": title,
        "agency": "",
        "project": "",
        "metadata": {},
        "sections": [{"heading": "본문", "text": text}],
        "source_path": str(path),
    }


def validate_chunking_options(
    chunking_strategy: str,
    max_chars: int,
    overlap_sentences: int,
) -> None:
    if chunking_strategy not in VALID_CHUNKING_STRATEGIES:
        choices = ", ".join(sorted(VALID_CHUNKING_STRATEGIES))
        raise ValueError(f"chunking_strategy must be one of: {choices}")
    if max_chars < 1:
        raise ValueError("chunk_max_chars must be positive.")
    if overlap_sentences < 0:
        raise ValueError("chunk_overlap_sentences must be zero or positive.")


def resolve_chunking_strategy(doc: dict[str, Any], requested_strategy: str) -> str:
    if requested_strategy == "auto":
        from rag_metadata_processing import document_has_section_structure
        return "section" if document_has_section_structure(doc) else "fixed"
    return requested_strategy


def build_chunk_records(
    documents: Iterable[dict[str, Any]],
    max_chars: int = DEFAULT_CHUNK_MAX_CHARS,
    chunking_strategy: str = "auto",
    overlap_sentences: int = DEFAULT_CHUNK_OVERLAP_SENTENCES,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    validate_chunking_options(chunking_strategy, max_chars, overlap_sentences)
    chunks: list[dict[str, Any]] = []
    parent_sections: list[dict[str, Any]] = []
    strategy_counts = {"section": 0, "fixed": 0}
    document_diagnostics = []

    for doc in documents:
        normalized_sections = normalize_document_sections(doc)
        actual_strategy = resolve_chunking_strategy(doc, chunking_strategy)
        parent_candidates = (
            normalized_sections
            if actual_strategy == "section"
            else [fixed_parent_section(doc, normalized_sections)]
        )
        doc_chunk_count = 0
        chunk_seq = 1

        for parent in parent_candidates:
            parent = {**parent, "chunking_strategy": actual_strategy}
            parent_sections.append(parent)
            section_chunks = split_section_text(parent["text"], max_chars, overlap_sentences)
            total_chunks_in_section = len(section_chunks)
            for chunk_seq_in_section, sentences in enumerate(section_chunks, start=1):
                chunks.append(
                    make_chunk(
                        doc,
                        parent,
                        sentences,
                        chunk_seq,
                        chunk_seq_in_section,
                        total_chunks_in_section,
                        actual_strategy,
                    )
                )
                chunk_seq += 1
                doc_chunk_count += 1

        strategy_counts[actual_strategy] += 1
        document_diagnostics.append(
            {
                "doc_id": doc["doc_id"],
                "requested_strategy": chunking_strategy,
                "actual_strategy": actual_strategy,
                "num_input_sections": len(normalized_sections),
                "num_parent_sections": len(parent_candidates),
                "num_chunks": doc_chunk_count,
            }
        )

    total_docs = strategy_counts["section"] + strategy_counts["fixed"]
    section_detection_rate: float | None = (
        strategy_counts["section"] / total_docs if total_docs else None
    )
    diagnostics = {
        "requested_strategy": chunking_strategy,
        "max_chars": max_chars,
        "overlap_sentences": overlap_sentences,
        "num_parent_sections": len(parent_sections),
        "actual_strategy_counts": {
            key: value for key, value in strategy_counts.items() if value
        },
        "section_detection_rate": section_detection_rate,
        "documents": document_diagnostics,
    }
    return chunks, parent_sections, diagnostics


def build_chunks(
    documents: Iterable[dict[str, Any]],
    max_chars: int = DEFAULT_CHUNK_MAX_CHARS,
    chunking_strategy: str = "auto",
    overlap_sentences: int = DEFAULT_CHUNK_OVERLAP_SENTENCES,
) -> list[dict[str, Any]]:
    chunks, _, _ = build_chunk_records(
        documents,
        max_chars=max_chars,
        chunking_strategy=chunking_strategy,
        overlap_sentences=overlap_sentences,
    )
    return chunks


def make_chunk(
    doc: dict[str, Any],
    parent_section: dict[str, Any],
    sentences: list[str],
    chunk_seq: int,
    chunk_seq_in_section: int,
    total_chunks_in_section: int,
    chunking_strategy: str,
) -> dict[str, Any]:
    text = " ".join(sentences).strip()
    section_path = parent_section.get("section_path") or [parent_section.get("section", "")]
    section_label = str(parent_section.get("section") or section_path[-1])
    regions = normalize_regions(parent_section.get("regions"))
    page_span = normalize_page_span(parent_section.get("page_span"), regions)
    chunk = {
        "chunk_id": f"{doc['doc_id']}::chunk-{chunk_seq:03d}",
        "section_id": parent_section["section_id"],
        "parent_section_id": parent_section["section_id"],
        "doc_id": doc["doc_id"],
        "title": doc["title"],
        "agency": doc.get("agency", ""),
        "project": doc.get("project", ""),
        "metadata": doc.get("metadata", {}),
        "section": section_label,
        "section_path": section_path,
        "chunk_seq_in_section": chunk_seq_in_section,
        "total_chunks_in_section": total_chunks_in_section,
        "chunking_strategy": chunking_strategy,
        "text": text,
        "tokens": tokenize(
            " ".join([doc["title"], doc.get("agency", ""), " > ".join(section_path), text])
        ),
    }
    if regions:
        chunk["regions"] = regions
    if page_span:
        chunk["page_span"] = page_span
    return chunk


def build_index_payload(
    input_dir: Path,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    embedding_backend: str = "auto",
    chunking_strategy: str = "auto",
    chunk_max_chars: int = DEFAULT_CHUNK_MAX_CHARS,
    chunk_overlap_sentences: int = DEFAULT_CHUNK_OVERLAP_SENTENCES,
) -> dict[str, Any]:
    documents = load_raw_documents(input_dir)
    return build_index_payload_from_documents(
        documents,
        source_dir=str(input_dir),
        model_name=model_name,
        embedding_backend=embedding_backend,
        chunking_strategy=chunking_strategy,
        chunk_max_chars=chunk_max_chars,
        chunk_overlap_sentences=chunk_overlap_sentences,
        message="Public synthetic RFP index for local minimum E2E RAG.",
    )


def build_index_payload_from_documents(
    documents: list[dict[str, Any]],
    source_dir: str,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    embedding_backend: str = "auto",
    chunking_strategy: str = "auto",
    chunk_max_chars: int = DEFAULT_CHUNK_MAX_CHARS,
    chunk_overlap_sentences: int = DEFAULT_CHUNK_OVERLAP_SENTENCES,
    message: str = "RFP index for local minimum E2E RAG.",
) -> dict[str, Any]:
    chunks, parent_sections, chunking_diagnostics = build_chunk_records(
        documents,
        max_chars=chunk_max_chars,
        chunking_strategy=chunking_strategy,
        overlap_sentences=chunk_overlap_sentences,
    )
    embedding_inputs = [
        " ".join(
            [
                chunk["title"],
                chunk.get("agency", ""),
                " > ".join(chunk.get("section_path") or [chunk["section"]]),
                chunk["text"],
            ]
        )
        for chunk in chunks
    ]
    embedding_result = embed_texts(embedding_inputs, model_name=model_name, backend=embedding_backend)
    # M2 (#207): vectors live in a sidecar .npy. Chunks reference rows by
    # embedding_idx — inline lists were ~85% of the JSON file size and
    # forced a per-query Python-list → NumPy materialization.
    # Stage 1 of #176 (#232): the matrix is wrapped in a VectorStore so
    # future backends (Qdrant, pgvector) can slot in without touching
    # chunk-metadata storage. InMemoryVectorStore is bit-identical.
    vectors_matrix = np.asarray(embedding_result.vectors, dtype=np.float32)
    for idx, chunk in enumerate(chunks):
        chunk["embedding_idx"] = idx
        chunk.pop("embedding", None)

    public_docs = [
        {
            "doc_id": doc["doc_id"],
            "title": doc["title"],
            "agency": doc.get("agency", ""),
            "project": doc.get("project", ""),
            "metadata": doc.get("metadata", {}),
            "source_path": doc["source_path"],
        }
        for doc in documents
    ]
    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "mode": "rag",
        "message": message,
        "embedding": {
            "backend": embedding_result.backend,
            "model": embedding_result.model,
            "dimension": int(embedding_result.vectors.shape[1]),
            "normalized": True,
            "storage": "sidecar_npy",
        },
        "build": {
            "num_documents": len(public_docs),
            "num_chunks": len(chunks),
            "num_parent_sections": len(parent_sections),
            "source_dir": source_dir,
            "chunking": chunking_diagnostics,
        },
        "documents": public_docs,
        "parent_sections": parent_sections,
        "chunks": chunks,
        "_vector_store": vector_store_from_matrix(vectors_matrix),
    }


def load_index(index_dir: Path) -> dict[str, Any]:
    path = index_dir / INDEX_FILENAME
    if not path.exists():
        raise ValueError(f"RAG index not found: {path}. Run scripts/build_index.py first.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("mode") != "rag":
        raise ValueError(f"Unsupported index mode: {payload.get('mode')}. Rebuild the index.")
    if not payload.get("chunks"):
        raise ValueError(f"Index has no chunks: {path}")
    schema = int(payload.get("schema_version", 1))
    # Stage 1 of #176 (#232): the vector matrix is now hidden behind a
    # VectorStore. load_vector_store handles the schema-2 sidecar path
    # and the legacy schema-1 inline-list materialization. The legacy
    # chunk-mutation loop (embedding_idx / pop) stays here because it
    # mutates payload["chunks"], not the store — and must run *after*
    # load_vector_store has read the inline lists.
    if schema < INDEX_SCHEMA_VERSION:
        payload["_vector_store"] = load_vector_store(
            index_dir, schema, chunks=payload["chunks"]
        )
        if payload["_vector_store"] is not None:
            for idx, chunk in enumerate(payload["chunks"]):
                chunk["embedding_idx"] = idx
                chunk.pop("embedding", None)
    else:
        payload["_vector_store"] = load_vector_store(index_dir, schema)
    return payload


def write_index(payload: dict[str, Any], output_dir: Path) -> Path:
    """Atomically persist an index payload + embeddings sidecar.

    Pops the in-memory ``_vector_store`` from the payload, asks it to
    persist its vectors (typically ``embeddings.npy``), and serializes
    the remaining JSON-compatible structure to ``index.json``. The
    caller's ``payload`` dict is mutated (the private key is removed) —
    see scripts/build_index.py for the canonical use site.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    store = payload.pop("_vector_store", None)
    if store is not None:
        store.persist(output_dir)
    out_path = output_dir / INDEX_FILENAME
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def known_entities(index: dict[str, Any]) -> list[str]:
    entities = []
    for doc in index.get("documents", []):
        agency = normalize_entity(str(doc.get("agency", "")))
        if agency and agency not in entities:
            entities.append(agency)
    return entities


def metadata_targets(index: dict[str, Any]) -> list[dict[str, Any]]:
    targets = []
    for doc in index.get("documents", []):
        for field in ("agency", "project", "title"):
            value = str(doc.get(field) or "").strip()
            if value:
                targets.append(make_metadata_target(doc, field, value))
    return targets
