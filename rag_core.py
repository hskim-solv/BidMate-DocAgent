#!/usr/bin/env python3
"""Shared local RAG primitives for the public BidMate sample.

The implementation keeps the public demo deterministic: retrieval is local,
generation is extractive, and external LLM/API calls are not required.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import difflib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any, Iterable
import unicodedata

import numpy as np

try:
    from rank_bm25 import BM25Okapi as _BM25Okapi
except ImportError:  # pragma: no cover — defensive; declared in requirements.txt
    _BM25Okapi = None  # type: ignore[assignment]

from bidmate_logging import get_logger, log_query_event
from rag_observability import resolve_trace_backend
from rag_query_expansion import default_expander
from rag_synthesis import synthesize_answer

_LOGGER = get_logger("rag_core")
from rag_vector_store import (
    InMemoryVectorStore,
    VectorStore,
    load_vector_store,
    vector_store_from_matrix,
)
from text_normalize import expand_forms, normalize_text

# Korean lexicon constants live in korean_lexicon.py (data/lexicon/ko_default.yaml).
# Re-exported here so existing call sites — including
# `tests/test_hybrid_retrieval_regression.py` which imports
# BM25_EXTRA_PARTICLE_SUFFIXES / BM25_EXTRA_STOPWORDS from rag_core —
# keep working unchanged. See issue #344.
from korean_lexicon import (
    BM25_EXTRA_PARTICLE_SUFFIXES,
    BM25_EXTRA_STOPWORDS,
    IMPLICIT_REFERENCE_PATTERNS,
    KOREAN_PARTICLE_SUFFIXES,
    METADATA_CLAIM_LABELS,
    METADATA_CLAIM_TOPIC_LABELS,
    METADATA_EVIDENCE_LABELS,
    METADATA_GENERIC_TOKENS,
    STOPWORDS,
    TOPIC_KEYWORDS,
    VERIFICATION_INTENT_TOKENS,
)

# Pipeline preset registry (PIPELINE_PRESETS, PIPELINE_ALIASES, helpers,
# RRF_K, VALID_RRF_K_RANGE, etc.) lives in rag_pipeline_presets.py as
# of issue #364 — stage 1 of the rag_core.py decomposition epic. The
# symbols below are re-exported so the FastAPI server, CLI app,
# benchmark / build_index / eval scripts, Streamlit demo and the test
# suite keep importing them from ``rag_core`` unchanged.
from rag_pipeline_presets import (
    DEFAULT_CLI_PIPELINE_NAME,
    DEFAULT_COMPARISON_BALANCE,
    DEFAULT_RAG_PIPELINE_NAME,
    PIPELINE_ALIASES,
    PIPELINE_CONFIG_KEYS,
    PIPELINE_PRESETS,
    RRF_K,
    VALID_BM25_STOPWORD_PROFILES,
    VALID_QUERY_EXPANSIONS,
    VALID_RETRIEVAL_BACKENDS,
    VALID_RETRIEVAL_MODES,
    VALID_RRF_K_RANGE,
    canonical_pipeline_name,
    is_pipeline_name,
    pipeline_cli_choices,
    resolve_pipeline_config,
)
# PR-H1a (issue #459): post-retrieval fusion / comparison balance /
# hierarchical reassembly extracted to rag_retrieval. Public functions
# re-exported for backward compatibility with any caller that imports
# them from rag_core (no in-repo callers do so today, but the import
# surface stays stable).
from rag_retrieval import (
    apply_comparison_balance,
    apply_fusion_and_reranking,
    reassemble_parent_sections,
)

# Conversation state schema + helpers live in rag_conversation_state.py as
# of issue #415 (PR-E stage 3 of the rag_core.py decomposition epic). The
# symbols below are direct-imported (no re-export wrapper) — repo-wide
# grep at PR filing confirmed zero external consumers.
from rag_conversation_state import (
    AMBIGUOUS_CONFIDENCE_DELTA,
    CONTEXT_RESOLUTION_THRESHOLD,
    CONVERSATION_STATE_SCHEMA_VERSION,
    MAX_CONVERSATION_TURNS,
    empty_conversation_state,
    normalize_conversation_state,
)

# ADR 0003 answer-contract schema constants live in rag_answer_schema.py
# as of issue #417 (PR-E stage 4a). Re-exported here so external
# consumers (tests/test_demo_helpers, tests/test_governance,
# tests/test_answer_contract_snapshot) keep their existing
# ``from rag_core import ANSWER_STATUS_SUPPORTED, ANSWER_SCHEMA_VERSION``
# imports unchanged.
from rag_answer_schema import (
    ANSWER_SCHEMA_VERSION,
    ANSWER_STATUS_INSUFFICIENT,
    ANSWER_STATUS_PARTIAL,
    ANSWER_STATUS_SUPPORTED,
)

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_HASH_DIM = 384
DEFAULT_CHUNK_MAX_CHARS = 520
DEFAULT_CHUNK_OVERLAP_SENTENCES = 1
VALID_CHUNKING_STRATEGIES = {"auto", "section", "fixed"}

# Hard cap on the per-query agent loop. ``metadata_stage_sequence`` today
# returns at most ["strict", "reduced", "relaxed"] (3 stages). This constant
# pins the contract — any future addition to the stage list that pushes
# past 3 must update this value and explain why in the PR description.
MAX_AGENT_ITERATIONS = 3

QUERY_TYPE_TOP_K_DEFAULTS: dict[str, int] = {
    "single_doc": 4,
    "follow_up": 6,
    "comparison": 6,
}
WEAK_SECTION_HEADINGS = {
    "",
    "본문",
    "body",
    "text",
    "document",
    "문서",
    "문서 전체",
    "section",
    "section-1",
    "section-001",
}
INDEX_FILENAME = "index.json"
# M2 (#207): vectors live in a sidecar .npy so the JSON stays small and a
# future VectorStore abstraction (#176) can swap in alternate backends
# without touching the chunk-metadata payload.
EMBEDDINGS_FILENAME = "embeddings.npy"
INDEX_SCHEMA_VERSION = 2
MODEL_CACHE: dict[tuple[str, bool, str | None], Any] = {}

TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]+")
ENTITY_RE = re.compile(r"기관\s*[-_]?\s*([A-Za-z0-9]+)", re.IGNORECASE)
SENTENCE_RE = re.compile(r"(?<=[.!?。])\s+")

TRACE_SCHEMA_VERSION = 1

STRICT_METADATA_CONFIDENCE = 0.90
REDUCED_METADATA_CONFIDENCE = 0.70


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: np.ndarray
    backend: str
    model: str


@dataclass(frozen=True)
class QueryParams:
    """Bundle of pipeline configuration kwargs for ``run_rag_query`` (issue #260).

    Additive, non-breaking signature extension. Existing callers using
    individual kwargs (``top_k=...``, ``rerank=...``, etc.) keep working
    unchanged. New callers can pass a single ``params=QueryParams(...)``
    bundle instead.

    Per-call inputs (``context_entities``, ``conversation_state``) stay
    separate kwargs on ``run_rag_query`` — they vary per turn, not per
    pipeline configuration. The return contract (ADR 0003) is unchanged.
    """

    top_k: int | None = None
    metadata_first: bool | None = None
    rerank: bool | None = None
    verifier_retry: bool | None = None
    retrieval_mode: str | None = None
    retrieval_backend: str | None = None
    pipeline: str | None = None
    prompt_profile: str | None = None
    comparison_balance: dict[str, Any] | None = None
    rrf_k: int | None = None
    bm25_stopword_profile: str | None = None


def normalize_entity(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def compact_metadata_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).lower()
    return re.sub(r"[^0-9a-z가-힣]+", "", normalized)


def normalize_metadata_token(token: str) -> str:
    token = unicodedata.normalize("NFC", token).lower().strip()
    if re.fullmatch(r"[가-힣]+", token):
        changed = True
        while changed:
            changed = False
            for suffix in KOREAN_PARTICLE_SUFFIXES:
                if len(token) > len(suffix) + 1 and token.endswith(suffix):
                    token = token[: -len(suffix)]
                    changed = True
                    break
    return token


def metadata_tokens(text: str) -> list[str]:
    tokens = []
    for match in TOKEN_RE.finditer(unicodedata.normalize("NFC", text)):
        token = normalize_metadata_token(match.group(0))
        if token and token not in STOPWORDS:
            tokens.append(token)
    return tokens


def ordered_unique(values: Iterable[str]) -> list[str]:
    seen = set()
    ordered = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return ordered_unique(str(item).strip() for item in value if str(item).strip())


def coerce_alias_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_values = re.split(r"[,;/|]", value)
        return ordered_unique(part.strip() for part in raw_values if part.strip())
    if isinstance(value, list):
        return ordered_unique(str(item).strip() for item in value if str(item).strip())
    return []



def tokenize(text: str) -> list[str]:
    tokens = [normalize_metadata_token(m.group(0)) for m in TOKEN_RE.finditer(text)]
    return [t for t in tokens if t and t not in STOPWORDS]


def sentence_split(text: str) -> list[str]:
    parts = SENTENCE_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def split_long_text_unit(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for line in lines:
            if len(line) > max_chars:
                if current:
                    chunks.append(" ".join(current).strip())
                    current = []
                    current_len = 0
                chunks.extend(split_long_text_unit(line, max_chars))
                continue
            next_len = current_len + len(line) + 1
            if current and next_len > max_chars:
                chunks.append(" ".join(current).strip())
                current = []
                current_len = 0
            current.append(line)
            current_len += len(line) + 1
        if current:
            chunks.append(" ".join(current).strip())
        return chunks

    words = text.split()
    if len(words) <= 1:
        return [text[idx : idx + max_chars].strip() for idx in range(0, len(text), max_chars)]

    chunks = []
    current = []
    current_len = 0
    for word in words:
        if len(word) > max_chars:
            if current:
                chunks.append(" ".join(current).strip())
                current = []
                current_len = 0
            chunks.extend(word[idx : idx + max_chars] for idx in range(0, len(word), max_chars))
            continue
        next_len = current_len + len(word) + 1
        if current and next_len > max_chars:
            chunks.append(" ".join(current).strip())
            current = []
            current_len = 0
        current.append(word)
        current_len += len(word) + 1
    if current:
        chunks.append(" ".join(current).strip())
    return [chunk for chunk in chunks if chunk]


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


def normalize_section_path(section: dict[str, Any], heading: str) -> list[str]:
    raw_path = section.get("section_path") or section.get("path") or []
    if isinstance(raw_path, str):
        parts = [part.strip() for part in raw_path.split(">")]
    elif isinstance(raw_path, list):
        parts = [str(part).strip() for part in raw_path]
    else:
        parts = []
    path = [part for part in parts if part]
    if not path:
        path = [heading]
    return path


def normalize_regions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    regions = []
    for item in value:
        if not isinstance(item, dict):
            continue
        region: dict[str, Any] = {}
        page_number = item.get("page_number")
        if isinstance(page_number, int):
            region["page_number"] = page_number
        elif page_number is None:
            region["page_number"] = None
        bbox = item.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            region["bbox"] = bbox
        elif bbox is None:
            region["bbox"] = None
        for key in ("source", "type", "block_id"):
            if item.get(key) is not None:
                region[key] = str(item.get(key))
        if region:
            regions.append(region)
    return regions


def normalize_page_span(value: Any, regions: list[dict[str, Any]]) -> list[int] | None:
    if isinstance(value, list) and len(value) == 2:
        try:
            return [int(value[0]), int(value[1])]
        except (TypeError, ValueError):
            pass
    page_numbers = [
        int(region["page_number"])
        for region in regions
        if isinstance(region.get("page_number"), int)
    ]
    if not page_numbers:
        return None
    return [min(page_numbers), max(page_numbers)]


def normalize_document_sections(doc: dict[str, Any]) -> list[dict[str, Any]]:
    normalized = []
    for idx, section in enumerate(doc.get("sections") or [], start=1):
        heading = str(section.get("heading") or f"section-{idx}").strip()
        text = str(section.get("text") or "").strip()
        if not text:
            continue
        section_path = normalize_section_path(section, heading)
        regions = normalize_regions(section.get("regions"))
        page_span = normalize_page_span(section.get("page_span"), regions)
        normalized_section = {
            "section_id": f"{doc['doc_id']}::section-{idx:03d}",
            "doc_id": doc["doc_id"],
            "title": doc["title"],
            "agency": doc.get("agency", ""),
            "project": doc.get("project", ""),
            "metadata": doc.get("metadata", {}),
            "section": section_path[-1],
            "heading": heading,
            "section_path": section_path,
            "text": text,
        }
        if regions:
            normalized_section["regions"] = regions
        if page_span:
            normalized_section["page_span"] = page_span
        normalized.append(normalized_section)
    return normalized


def document_has_section_structure(doc: dict[str, Any]) -> bool:
    sections = normalize_document_sections(doc)
    if len(sections) > 1:
        return True
    if not sections:
        return False
    section = sections[0]
    heading = str(section.get("heading") or "").strip().lower()
    section_path = section.get("section_path") or []
    return len(section_path) > 1 or heading not in WEAK_SECTION_HEADINGS


def resolve_chunking_strategy(doc: dict[str, Any], requested_strategy: str) -> str:
    if requested_strategy == "auto":
        return "section" if document_has_section_structure(doc) else "fixed"
    return requested_strategy


def fixed_parent_section(doc: dict[str, Any], sections: list[dict[str, Any]]) -> dict[str, Any]:
    parts = []
    regions = []
    for section in sections:
        heading = str(section.get("section") or "").strip()
        text = str(section.get("text") or "").strip()
        regions.extend(normalize_regions(section.get("regions")))
        if heading and heading not in WEAK_SECTION_HEADINGS:
            parts.append(f"{heading}\n{text}")
        else:
            parts.append(text)
    parent = {
        "section_id": f"{doc['doc_id']}::section-001",
        "doc_id": doc["doc_id"],
        "title": doc["title"],
        "agency": doc.get("agency", ""),
        "project": doc.get("project", ""),
        "metadata": doc.get("metadata", {}),
        "section": "문서 전체",
        "heading": "문서 전체",
        "section_path": ["문서 전체"],
        "text": "\n\n".join(part for part in parts if part).strip(),
    }
    page_span = normalize_page_span(None, regions)
    if regions:
        parent["regions"] = regions
    if page_span:
        parent["page_span"] = page_span
    return parent


def split_section_text(
    text: str,
    max_chars: int,
    overlap_sentences: int,
) -> list[list[str]]:
    sentences = []
    for sentence in sentence_split(text) or [text]:
        sentences.extend(split_long_text_unit(sentence, max_chars))

    chunks: list[list[str]] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        next_len = current_len + len(sentence) + 1
        if current and next_len > max_chars:
            chunks.append(current)
            overlap = current[-overlap_sentences:] if overlap_sentences else []
            overlap_len = sum(len(s) + 1 for s in overlap)
            if overlap and overlap_len + len(sentence) + 1 <= max_chars:
                current = overlap
                current_len = overlap_len
            else:
                current = []
                current_len = 0
        current.append(sentence)
        current_len += len(sentence) + 1
    if current:
        chunks.append(current)
    return chunks


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

    diagnostics = {
        "requested_strategy": chunking_strategy,
        "max_chars": max_chars,
        "overlap_sentences": overlap_sentences,
        "num_parent_sections": len(parent_sections),
        "actual_strategy_counts": {
            key: value for key, value in strategy_counts.items() if value
        },
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


def embed_texts(
    texts: list[str],
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    backend: str = "auto",
    local_only: bool = False,
) -> EmbeddingResult:
    if backend not in {"auto", "sentence-transformers", "hashing", "openai"}:
        raise ValueError(
            "--embedding_backend must be one of: auto, sentence-transformers, hashing, openai"
        )

    if backend == "openai":
        return _embed_with_openai(texts, model_name=model_name)

    should_try_sentence_transformers = backend == "sentence-transformers" or (
        backend == "auto" and sentence_transformer_cache_available(model_name)
    )

    if should_try_sentence_transformers:
        try:
            with huggingface_offline(local_only or backend == "auto"):
                from sentence_transformers import SentenceTransformer

                # ADR 0027 — additive LoRA adapter, gated by env var so
                # the default (env unset) path remains byte-identical
                # to pre-#434 behavior. ``adapter_path`` is part of the
                # cache key so adapted / unadapted variants of the same
                # base model don't clobber each other.
                adapter_path = os.environ.get("BIDMATE_EMBEDDING_LORA_ADAPTER") or None
                cache_key = (model_name, local_only or backend == "auto", adapter_path)
                model = MODEL_CACHE.get(cache_key)
                if model is None:
                    model = SentenceTransformer(model_name)
                    if adapter_path:
                        # PEFT is lazy-imported (optional dep in
                        # requirements-lora.txt) — the hashing-only CI
                        # path never executes this branch and so never
                        # needs the package installed.
                        from peft import PeftModel  # type: ignore[import-not-found]

                        underlying = model[0].auto_model
                        adapted = PeftModel.from_pretrained(underlying, adapter_path)
                        model[0].auto_model = adapted.merge_and_unload()
                    MODEL_CACHE[cache_key] = model
            vectors = model.encode(
                texts,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return EmbeddingResult(
                vectors=np.asarray(vectors, dtype=np.float32),
                backend="sentence-transformers",
                model=model_name,
            )
        except Exception as exc:
            if backend == "sentence-transformers":
                raise RuntimeError(f"Failed to load embedding model {model_name}: {exc}") from exc

    return EmbeddingResult(
        vectors=hashing_embeddings(texts, DEFAULT_HASH_DIM),
        backend="hashing",
        model="local-hashing-bow",
    )


def _embed_with_openai(texts: list[str], *, model_name: str) -> EmbeddingResult:
    try:
        import openai  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "openai backend requires the openai SDK. "
            "Install with `pip install openai` or use --embedding_backend sentence-transformers."
        ) from exc
    api_key = os.environ.get("BIDMATE_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "BIDMATE_OPENAI_API_KEY (or OPENAI_API_KEY) is not set for embedding_backend=openai."
        )
    client = openai.OpenAI(api_key=api_key)
    vectors: list[list[float]] = []
    batch_size = 100
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        resp = client.embeddings.create(model=model_name, input=batch)
        vectors.extend(item.embedding for item in resp.data)
    arr = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True).clip(min=1e-12)
    return EmbeddingResult(
        vectors=arr / norms,
        backend="openai",
        model=model_name,
    )


def sentence_transformer_cache_available(model_name: str) -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache
    except Exception:
        return False
    for filename in ("modules.json", "config_sentence_transformers.json", "config.json"):
        cached = try_to_load_from_cache(model_name, filename)
        if isinstance(cached, str):
            return True
    return False


class huggingface_offline:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.previous: dict[str, str | None] = {}

    def __enter__(self) -> None:
        if not self.enabled:
            return
        for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
            self.previous[key] = os.environ.get(key)
            os.environ[key] = "1"

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if not self.enabled:
            return
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def hashing_embeddings(texts: list[str], dim: int) -> np.ndarray:
    vectors = np.zeros((len(texts), dim), dtype=np.float32)
    for row, text in enumerate(texts):
        for token in expand_features(tokenize(text)):
            digest = hashlib.md5(token.encode("utf-8")).hexdigest()
            idx = int(digest[:8], 16) % dim
            sign = 1.0 if int(digest[8:10], 16) % 2 == 0 else -1.0
            vectors[row, idx] += sign
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def expand_features(tokens: list[str]) -> list[str]:
    features = list(tokens)
    for left, right in zip(tokens, tokens[1:]):
        features.append(f"{left}_{right}")
    return features


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


def make_metadata_target(doc: dict[str, Any], field: str, value: str) -> dict[str, Any]:
    tokens = metadata_tokens(value)
    core_tokens = [token for token in tokens if token not in METADATA_GENERIC_TOKENS]
    explicit_aliases = metadata_explicit_aliases(doc, field)
    return {
        "doc_id": str(doc.get("doc_id") or ""),
        "agency": str(doc.get("agency") or ""),
        "project": str(doc.get("project") or ""),
        "field": field,
        "value": value,
        "compact": compact_metadata_text(value),
        "tokens": tokens,
        "core_tokens": core_tokens,
        "aliases": metadata_aliases(field, value, tokens, explicit_aliases),
        "explicit_aliases": explicit_aliases,
    }


def metadata_explicit_aliases(doc: dict[str, Any], field: str) -> list[str]:
    metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    aliases: list[str] = []
    aliases.extend(coerce_alias_values(metadata.get(f"{field}_aliases")))

    generic_aliases = metadata.get("aliases")
    if isinstance(generic_aliases, dict):
        aliases.extend(coerce_alias_values(generic_aliases.get(field)))
    else:
        aliases.extend(coerce_alias_values(generic_aliases))

    return ordered_unique(aliases)


def metadata_aliases(
    field: str,
    value: str,
    tokens: list[str],
    explicit_aliases: list[str] | None = None,
) -> list[str]:
    aliases = []
    aliases.extend(explicit_aliases or [])
    if field == "agency":
        for token in tokens:
            if 1 <= len(token) <= 4 and re.search(r"[a-z0-9]", token):
                aliases.append(token)
        compact = compact_metadata_text(value)
        if compact.startswith("기관") and len(compact) > 2:
            aliases.append(compact[2:])
    return ordered_unique(aliases)


def coerce_metadata_targets(values: list[Any]) -> list[dict[str, Any]]:
    if not values:
        return []
    if isinstance(values[0], dict):
        return values
    return [
        make_metadata_target(
            {"doc_id": f"agency::{value}", "agency": str(value), "project": ""},
            "agency",
            str(value),
        )
        for value in values
    ]


def match_metadata_targets(query: str, targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    query_compact = compact_metadata_text(query)
    query_tokens = metadata_tokens(query)
    query_token_set = set(query_tokens)
    matches = []
    for target in targets:
        match = match_metadata_target(query_compact, query_tokens, query_token_set, target)
        if match:
            matches.append(match)
    return dedupe_metadata_matches(matches)


def match_metadata_target(
    query_compact: str,
    query_tokens: list[str],
    query_token_set: set[str],
    target: dict[str, Any],
) -> dict[str, Any] | None:
    target_compact = target.get("compact", "")
    target_tokens = target.get("core_tokens") or target.get("tokens") or []

    if target_compact and len(target_compact) >= 2 and target_compact in query_compact:
        return make_metadata_match(target, 1.0, "compact_contains", target_tokens)

    explicit_alias_hits = []
    for alias in target.get("explicit_aliases", []):
        alias_compact = compact_metadata_text(str(alias))
        alias_tokens = set(metadata_tokens(str(alias)))
        if (
            (alias_compact and alias_compact in query_compact)
            or bool(alias_tokens and alias_tokens.issubset(query_token_set))
        ):
            explicit_alias_hits.append(str(alias))
    if explicit_alias_hits:
        return make_metadata_match(target, 0.92, "explicit_alias", explicit_alias_hits)

    alias_hits = []
    for alias in target.get("aliases", []):
        alias_compact = compact_metadata_text(str(alias))
        if alias in query_token_set or (
            alias_compact and len(alias_compact) >= 2 and alias_compact in query_compact
        ):
            alias_hits.append(str(alias))
    if alias_hits:
        return make_metadata_match(target, 0.78, "abbreviation", alias_hits)

    overlap = [token for token in target_tokens if token in query_token_set]
    if len(overlap) >= 2:
        overlap_ratio = len(overlap) / max(1, len(target_tokens))
        confidence = min(0.89, 0.70 + (0.19 * overlap_ratio))
        return make_metadata_match(target, confidence, "partial_tokens", overlap)
    if len(overlap) == 1 and target["field"] in {"project", "title"} and len(target_tokens) <= 2:
        if len(overlap[0]) >= 3:
            return make_metadata_match(target, 0.72, "partial_tokens", overlap)

    fuzzy_score = best_metadata_phrase_similarity(target_tokens, query_tokens)
    if fuzzy_score >= REDUCED_METADATA_CONFIDENCE:
        confidence = min(0.84, fuzzy_score)
        return make_metadata_match(target, confidence, "fuzzy_similarity", target_tokens)

    return None


def best_metadata_phrase_similarity(target_tokens: list[str], query_tokens: list[str]) -> float:
    if not target_tokens or not query_tokens:
        return 0.0
    target_text = "".join(target_tokens)
    min_size = max(1, len(target_tokens) - 1)
    max_size = min(len(query_tokens), len(target_tokens) + 1)
    best = 0.0
    for size in range(min_size, max_size + 1):
        for start in range(0, len(query_tokens) - size + 1):
            phrase = "".join(query_tokens[start : start + size])
            best = max(best, difflib.SequenceMatcher(None, target_text, phrase).ratio())
    return best


def make_metadata_match(
    target: dict[str, Any],
    confidence: float,
    match_type: str,
    matched_terms: list[str],
) -> dict[str, Any]:
    stage = "strict" if confidence >= STRICT_METADATA_CONFIDENCE else "reduced"
    return {
        "doc_id": target["doc_id"],
        "agency": target.get("agency", ""),
        "project": target.get("project", ""),
        "field": target["field"],
        "value": target["value"],
        "confidence": round(float(confidence), 3),
        "stage": stage,
        "match_type": match_type,
        "matched_terms": ordered_unique(matched_terms),
    }


def dedupe_metadata_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_target: dict[tuple[str, str, str], dict[str, Any]] = {}
    for match in matches:
        key = (match["doc_id"], match["field"], match["value"])
        current = best_by_target.get(key)
        if current is None or match["confidence"] > current["confidence"]:
            best_by_target[key] = match
    return sorted(
        best_by_target.values(),
        key=lambda item: (item["confidence"], item["field"] == "agency"),
        reverse=True,
    )


def metadata_matches_for_stage(matches: list[dict[str, Any]], stage: str) -> list[dict[str, Any]]:
    if stage == "strict":
        return [match for match in matches if match["confidence"] >= STRICT_METADATA_CONFIDENCE]
    if stage == "reduced":
        return [match for match in matches if match["confidence"] >= REDUCED_METADATA_CONFIDENCE]
    return []


def metadata_filters_from_matches(matches: list[dict[str, Any]]) -> dict[str, Any]:
    if not matches:
        return {}
    return {
        "doc_ids": ordered_unique(match["doc_id"] for match in matches),
        "agencies": ordered_unique(match["agency"] for match in matches),
        "projects": ordered_unique(match["project"] for match in matches),
        "confidence": round(max(match["confidence"] for match in matches), 3),
    }


def best_metadata_doc_scores(matches: list[dict[str, Any]]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for match in matches:
        doc_id = match.get("doc_id", "")
        if doc_id:
            scores[doc_id] = max(scores.get(doc_id, 0.0), float(match["confidence"]))
    return scores


def metadata_ambiguity_details(matches: list[dict[str, Any]], query_type: str) -> dict[str, Any]:
    if query_type == "comparison":
        return {
            "ambiguous": False,
            "reason": "comparison_allows_multiple_targets",
            "candidate_doc_ids": [],
            "top_score": 0.0,
            "confidence_delta": AMBIGUOUS_CONFIDENCE_DELTA,
        }
    reduced_matches = metadata_matches_for_stage(matches, "reduced")
    if not reduced_matches:
        return {
            "ambiguous": False,
            "reason": "no_reduced_candidates",
            "candidate_doc_ids": [],
            "top_score": 0.0,
            "confidence_delta": AMBIGUOUS_CONFIDENCE_DELTA,
        }
    scores = best_metadata_doc_scores(reduced_matches)
    if len(scores) <= 1:
        return {
            "ambiguous": False,
            "reason": "single_candidate",
            "candidate_doc_ids": list(scores.keys()),
            "top_score": round(max(scores.values(), default=0.0), 3),
            "confidence_delta": AMBIGUOUS_CONFIDENCE_DELTA,
        }
    top_score = max(scores.values())
    close_doc_ids = [
        doc_id for doc_id, score in scores.items() if score >= top_score - AMBIGUOUS_CONFIDENCE_DELTA
    ]
    ambiguous = len(close_doc_ids) > 1
    return {
        "ambiguous": ambiguous,
        "reason": "close_candidate_scores" if ambiguous else "clear_top_candidate",
        "candidate_doc_ids": close_doc_ids,
        "top_score": round(top_score, 3),
        "confidence_delta": AMBIGUOUS_CONFIDENCE_DELTA,
    }


def is_metadata_ambiguous(matches: list[dict[str, Any]], query_type: str) -> bool:
    return bool(metadata_ambiguity_details(matches, query_type).get("ambiguous"))


def has_implicit_reference(query: str) -> bool:
    normalized_query = normalize_entity(query)
    return any(pattern in normalized_query for pattern in IMPLICIT_REFERENCE_PATTERNS)


def has_comparison_request(query: str) -> bool:
    comparison_terms = ("차이", "비교", "각각", "대비")
    return any(term in normalize_entity(query) for term in comparison_terms)


def extract_requested_agencies(query: str) -> list[str]:
    agencies = []
    for match in ENTITY_RE.finditer(unicodedata.normalize("NFC", query)):
        token = normalize_metadata_token(match.group(1))
        if not token:
            continue
        if re.fullmatch(r"[a-z0-9]+", token):
            token = token.upper()
        agencies.append(f"기관 {token}")
    return ordered_unique(agencies)


def active_state_terms(state: dict[str, Any]) -> list[str]:
    terms = [
        *coerce_string_list(state.get("active_agencies")),
        *coerce_string_list(state.get("active_projects")),
    ]
    if terms:
        return ordered_unique(terms)
    return coerce_string_list(state.get("active_doc_ids"))


def active_state_size(state: dict[str, Any]) -> int:
    return max(
        len(state.get("active_agencies") or []),
        len(state.get("active_projects") or []),
        len(state.get("active_doc_ids") or []),
    )


def inject_entities_into_query(query: str, entities: list[str]) -> str:
    """Prepend resolved entities to the retrieval query (issue #71).

    Skips entities that already appear in the query (case-insensitive)
    so user-typed entities don't get duplicated. Order is preserved so
    deterministic reproduction of dense embeddings is unaffected when
    no augmentation is needed.
    """
    if not entities:
        return query
    lowered_query = query.lower()
    missing = [
        entity
        for entity in entities
        if entity and entity.lower() not in lowered_query
    ]
    if not missing:
        return query
    return " ".join([*missing, query])


def make_context_resolution(
    status: str,
    source: str,
    confidence: float,
    reason: str = "",
    resolved_query: str | None = None,
    context_entities: list[str] | None = None,
    context_projects: list[str] | None = None,
    active_doc_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "source": source,
        "confidence": round(float(confidence), 3),
        "reason": reason,
        "resolved_query": resolved_query,
        "context_entities": context_entities or [],
        "context_projects": context_projects or [],
        "active_doc_ids": active_doc_ids or [],
    }


def resolve_conversation_context(
    query: str,
    initial_analysis: dict[str, Any],
    conversation_state: dict[str, Any],
    context_entities: list[str] | None = None,
) -> tuple[str, list[str], dict[str, Any]]:
    explicit_context = coerce_string_list(context_entities or [])
    if explicit_context:
        # Issue #71: prepend entities into the retrieval query string
        # so dense / lexical scoring picks up the entity anchor — the
        # same augmentation the conversation_state branch below
        # already performs. Without this, follow-ups like "그럼 일정은?"
        # carrying `context_entities=["기관 A"]` lost the entity in
        # token space (only the metadata match path saw it). Resolved
        # by injection so dense embedding and `lexical_similarity`
        # both gain the anchor. Real-data taxonomy C4-1.
        augmented_query = inject_entities_into_query(query, explicit_context)
        return (
            augmented_query,
            explicit_context,
            make_context_resolution(
                "resolved",
                "context_entities",
                1.0,
                resolved_query=augmented_query,
                context_entities=explicit_context,
            ),
        )

    if initial_analysis.get("matched_doc_ids"):
        return (
            query,
            [],
            make_context_resolution("not_needed", "query", 1.0, resolved_query=query),
        )

    if not has_implicit_reference(query):
        return (
            query,
            [],
            make_context_resolution("not_needed", "none", 0.0, resolved_query=query),
        )

    state_terms = active_state_terms(conversation_state)
    state_agencies = coerce_string_list(conversation_state.get("active_agencies"))
    state_projects = coerce_string_list(conversation_state.get("active_projects"))
    state_doc_ids = coerce_string_list(conversation_state.get("active_doc_ids"))
    if not state_terms:
        return (
            query,
            [],
            make_context_resolution(
                "needs_clarification",
                "conversation_state",
                0.0,
                reason="no_active_state",
                resolved_query=query,
                active_doc_ids=state_doc_ids,
            ),
        )

    state_confidence = float(conversation_state.get("confidence") or 0.0)
    if state_confidence < CONTEXT_RESOLUTION_THRESHOLD:
        return (
            query,
            [],
            make_context_resolution(
                "needs_clarification",
                "conversation_state",
                state_confidence,
                reason="weak_active_state",
                resolved_query=query,
                context_entities=state_agencies or state_terms,
                context_projects=state_projects,
                active_doc_ids=state_doc_ids,
            ),
        )

    if active_state_size(conversation_state) > 1 and not has_comparison_request(query):
        return (
            query,
            [],
            make_context_resolution(
                "needs_clarification",
                "conversation_state",
                state_confidence,
                reason="ambiguous_active_state",
                resolved_query=query,
                context_entities=state_agencies or state_terms,
                context_projects=state_projects,
                active_doc_ids=state_doc_ids,
            ),
        )

    resolved_query = inject_entities_into_query(query, state_terms)
    return (
        resolved_query,
        state_terms,
        make_context_resolution(
            "resolved",
            "conversation_state",
            state_confidence,
            resolved_query=resolved_query,
            context_entities=state_agencies or state_terms,
            context_projects=state_projects,
            active_doc_ids=state_doc_ids,
        ),
    )


def analyze_query(
    query: str,
    entities: list[Any],
    context_entities: list[str] | None = None,
) -> dict[str, Any]:
    targets = coerce_metadata_targets(entities)
    normalized_query = normalize_entity(query)
    requested_agencies = extract_requested_agencies(normalized_query)
    metadata_matches = match_metadata_targets(normalized_query, targets)

    context_used = False
    if not metadata_matches and context_entities:
        context_matches = []
        for entity in context_entities:
            context_matches.extend(match_metadata_targets(entity, targets))
        if context_matches:
            context_used = True
            metadata_matches = dedupe_metadata_matches(context_matches)

    topics = []
    for keyword in TOPIC_KEYWORDS:
        if keyword.lower() in normalized_query.lower() and keyword not in topics:
            topics.append(keyword)
    for token in tokenize(normalized_query):
        if len(token) > 1 and token not in STOPWORDS:
            if any(token == topic.lower() for topic in topics):
                continue
            if not token.startswith("기관"):
                topics.append(token)

    # ADR 0007 / issue #170: add canonical-form tokens from Korean money/date
    # normalization so substring topic matching can bridge 5천만원 ↔ 50,000,000.
    # Strictly additive — existing tokens are kept; new tokens compete for the
    # topics[:8] cap on equal footing.
    canonical_query = normalize_text(normalized_query)
    if canonical_query != normalized_query:
        existing = {topic.lower() for topic in topics}
        for token in tokenize(canonical_query):
            if (
                len(token) > 1
                and token not in STOPWORDS
                and not token.startswith("기관")
                and token.lower() not in existing
            ):
                topics.append(token)
                existing.add(token.lower())

    comparison_terms = ("차이", "비교", "각각", "대비")
    comparison_joiners = ("와", "과", "및", ",", "/")
    reduced_matches = metadata_matches_for_stage(metadata_matches, "reduced")
    matched_doc_ids = ordered_unique(match["doc_id"] for match in reduced_matches)
    matched_agencies = ordered_unique(match["agency"] for match in reduced_matches)
    matched_projects = ordered_unique(match["project"] for match in reduced_matches)
    has_comparison_term = any(term in normalized_query for term in comparison_terms)
    has_multi_target_joiner = len(matched_agencies) > 1 and any(
        joiner in normalized_query for joiner in comparison_joiners
    )
    if has_comparison_term or has_multi_target_joiner:
        query_type = "comparison"
    elif context_used:
        query_type = "follow_up"
    else:
        query_type = "single_doc"
    analysis_entities = matched_agencies
    if query_type == "comparison":
        analysis_entities = ordered_unique([*requested_agencies, *matched_agencies])

    strict_matches = metadata_matches_for_stage(metadata_matches, "strict")
    strict_filters = metadata_filters_from_matches(strict_matches)
    reduced_filters = metadata_filters_from_matches(reduced_matches)
    ambiguity = metadata_ambiguity_details(metadata_matches, query_type)

    return {
        "query_type": query_type,
        "entities": analysis_entities,
        "requested_entities": requested_agencies,
        "missing_requested_entities": [
            entity for entity in requested_agencies if entity not in matched_agencies
        ],
        "topics": topics[:8],
        "context_entities": context_entities or [],
        "context_used": context_used,
        "tokens": tokenize(normalized_query),
        "metadata_matches": metadata_matches,
        "matched_doc_ids": matched_doc_ids,
        "matched_agencies": matched_agencies,
        "matched_projects": matched_projects,
        "metadata_confidence": round(max((m["confidence"] for m in metadata_matches), default=0.0), 3),
        "metadata_ambiguous": bool(ambiguity.get("ambiguous")),
        "metadata_ambiguity": ambiguity,
        "metadata_filters_by_stage": {
            "strict": strict_filters,
            "reduced": reduced_filters,
            "relaxed": {},
        },
        "metadata_doc_scores": best_metadata_doc_scores(reduced_matches),
    }


def comparison_targets_for_analysis(analysis: dict[str, Any]) -> tuple[list[str], str]:
    """Return (targets, target_field) for comparison balancing.

    Prefers matched doc_ids when ≥2 are present; otherwise falls back to matched
    agencies. Returns ([], "") when balancing is not applicable.
    """
    matched_doc_ids = list(analysis.get("matched_doc_ids") or [])
    if len(matched_doc_ids) >= 2:
        return ordered_unique(matched_doc_ids), "doc_id"
    entities = list(analysis.get("entities") or [])
    if len(entities) >= 2:
        return ordered_unique(entities), "agency"
    return [], ""


def summarize_metadata_match(match: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_id": match.get("doc_id", ""),
        "field": match.get("field", ""),
        "value": match.get("value", ""),
        "agency": match.get("agency", ""),
        "project": match.get("project", ""),
        "confidence": match.get("confidence", 0.0),
        "stage": match.get("stage", ""),
        "match_type": match.get("match_type", ""),
        "matched_terms": match.get("matched_terms", []),
    }


def metadata_resolution_diagnostics(
    query: str,
    analysis: dict[str, Any],
    *,
    selected_stage: str | None = None,
    decision: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    matches = list(analysis.get("metadata_matches") or [])
    selected_by_stage: dict[str, list[dict[str, Any]]] = {}
    for stage in ("strict", "reduced"):
        selected_by_stage[stage] = [
            summarize_metadata_match(match)
            for match in metadata_matches_for_stage(matches, stage)
        ]
    selected_by_stage["relaxed"] = []

    selected_stage = selected_stage or ""
    selected_matches = selected_by_stage.get(selected_stage, [])
    ambiguity = dict(analysis.get("metadata_ambiguity") or {})
    ambiguous = bool(analysis.get("metadata_ambiguous"))
    if decision is None:
        decision = "clarify" if ambiguous and analysis.get("query_type") != "comparison" else "use_selected_candidates"

    return {
        "normalized_query": normalize_entity(query),
        "normalized_query_compact": compact_metadata_text(query),
        "normalized_query_tokens": metadata_tokens(query),
        "candidate_count": len(matches),
        "candidates": [summarize_metadata_match(match) for match in matches],
        "selected_stage": selected_stage,
        "selected_candidates_by_stage": selected_by_stage,
        "selected_candidates": selected_matches,
        "selected_doc_ids": ordered_unique(match.get("doc_id", "") for match in selected_matches),
        "matched_doc_ids": coerce_string_list(analysis.get("matched_doc_ids")),
        "ambiguity": {
            **ambiguity,
            "ambiguous": ambiguous,
            "decision": decision,
            "decision_reason": reason or ambiguity.get("reason", ""),
        },
    }


def query_type_default_top_k(query_type: str) -> int:
    return QUERY_TYPE_TOP_K_DEFAULTS.get(query_type, QUERY_TYPE_TOP_K_DEFAULTS["single_doc"])


def make_plan(
    analysis: dict[str, Any],
    relaxed: bool = False,
    top_k: int | None = None,
    top_k_reason: str | None = None,
    stage: str | None = None,
    metadata_first: bool = True,
    rerank: bool = True,
    verifier_retry: bool = True,
    retrieval_mode: str = "flat",
    retrieval_backend: str = "dense",
    pipeline: str = DEFAULT_RAG_PIPELINE_NAME,
    prompt_profile: str = "structured_grounded_claims",
    comparison_balance: dict[str, Any] | None = None,
    rrf_k: int = RRF_K,
    bm25_stopword_profile: str = "shared",
) -> dict[str, Any]:
    if retrieval_mode not in VALID_RETRIEVAL_MODES:
        choices = ", ".join(sorted(VALID_RETRIEVAL_MODES))
        raise ValueError(f"retrieval_mode must be one of: {choices}")
    if retrieval_backend not in VALID_RETRIEVAL_BACKENDS:
        choices = ", ".join(sorted(VALID_RETRIEVAL_BACKENDS))
        raise ValueError(f"retrieval_backend must be one of: {choices}")
    rrf_lo, rrf_hi = VALID_RRF_K_RANGE
    if int(rrf_k) < rrf_lo or int(rrf_k) > rrf_hi:
        raise ValueError(f"rrf_k must be in [{rrf_lo}, {rrf_hi}].")
    if bm25_stopword_profile not in VALID_BM25_STOPWORD_PROFILES:
        choices = ", ".join(sorted(VALID_BM25_STOPWORD_PROFILES))
        raise ValueError(f"bm25_stopword_profile must be one of: {choices}")
    query_type = str(analysis.get("query_type") or "single_doc")
    default_top_k = query_type_default_top_k(query_type)
    budget_reason = top_k_reason or (
        "explicit_override" if top_k is not None else f"{query_type}_default"
    )

    targets, target_field = comparison_targets_for_analysis(analysis)
    balance_enabled = bool(
        comparison_balance
        and comparison_balance.get("enabled")
        and analysis.get("query_type") == "comparison"
        and len(targets) >= 2
    )
    if balance_enabled and analysis.get("query_type") == "comparison":
        k_per_target = int(comparison_balance.get("k_per_target", 3))
        headroom = int(comparison_balance.get("headroom", 2))
        max_top_k = int(comparison_balance.get("max_top_k", 12))
        adaptive = k_per_target * len(targets) + headroom
        default_top_k = max(default_top_k, min(max_top_k, adaptive))
        if top_k is None:
            budget_reason = "comparison_coverage_adaptive"

    if relaxed:
        stage = "relaxed"
    if not metadata_first:
        stage = "relaxed"
    stage = stage or "strict"
    if stage == "relaxed":
        filters = {}
    else:
        filters_by_stage = analysis.get("metadata_filters_by_stage") or {}
        filters = filters_by_stage.get(stage) or {}
        if not filters and not filters_by_stage:
            filters = {"agencies": analysis.get("entities", [])}
    scoring = "dense"
    if rerank and metadata_first:
        scoring = "dense + lexical + metadata rerank"
    elif rerank:
        scoring = "dense + lexical rerank"
    if retrieval_backend == "hybrid":
        scoring = f"hybrid (bm25 + {scoring}) rrf"
    elif retrieval_backend == "m3":
        # Issue #151 — BGE-M3 dense + sparse + ColBERT multi-vector fused
        # via N-way RRF. Opt-in measurement spike; see
        # ``docs/m3-multichannel-spike.md``.
        scoring = "m3 (dense + sparse + colbert) rrf"
    plan: dict[str, Any] = {
        "strategy": scoring if not metadata_first else f"metadata-first {scoring}",
        "pipeline": pipeline,
        "prompt_profile": prompt_profile,
        "filter_stage": stage,
        "metadata_first": metadata_first,
        "rerank": rerank,
        "verifier_retry": verifier_retry,
        "retrieval_mode": retrieval_mode,
        "retrieval_backend": retrieval_backend,
        "rrf_k": int(rrf_k),
        "bm25_stopword_profile": bm25_stopword_profile,
        "metadata_filters": filters,
        "top_k": top_k or default_top_k,
        "retrieval_budget": {
            "selected_top_k": top_k or default_top_k,
            "query_type": query_type,
            "reason": budget_reason,
            "defaults": dict(QUERY_TYPE_TOP_K_DEFAULTS),
        },
        "relaxed": stage == "relaxed",
        "retry_policy": "try strict metadata filters, then reduced fuzzy filters, then relaxed retrieval",
    }
    if comparison_balance is not None:
        plan["comparison_balance"] = dict(comparison_balance)
    if targets:
        plan["comparison_targets"] = targets
        plan["comparison_target_field"] = target_field
    return plan


def retrieve(
    index: dict[str, Any],
    query: str,
    analysis: dict[str, Any],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    scored = retrieve_candidates(index, query, analysis, plan)
    return apply_fusion_and_reranking(scored, index, query, analysis, plan)


def retrieve_candidates(
    index: dict[str, Any],
    query: str,
    analysis: dict[str, Any],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """Filter + per-chunk dense / lexical / metadata / BM25 scoring; the
    pre-fusion phase of ``retrieve``. Split out so future Phase 3
    multi-query / HyDE work can fan out this phase without piling onto
    the fusion+rerank tail. Mutates ``plan`` with ``candidate_count``,
    ``total_chunks``, ``filter_fallback_used`` (unchanged order)."""
    chunks = index["chunks"]
    filters = plan.get("metadata_filters") or {}
    doc_ids = set(filters.get("doc_ids") or [])
    agencies = set(filters.get("agencies") or [])
    projects = set(filters.get("projects") or [])
    candidates = [
        c
        for c in chunks
        if (
            (doc_ids and c.get("doc_id") in doc_ids)
            or (not doc_ids and agencies and c.get("agency") in agencies)
            or (not doc_ids and projects and c.get("project") in projects)
            or not (doc_ids or agencies or projects)
        )
    ]
    plan["candidate_count"] = len(candidates)
    plan["total_chunks"] = len(chunks)
    plan["filter_fallback_used"] = False
    if not candidates:
        candidates = chunks
        plan["candidate_count"] = len(candidates)
        plan["filter_fallback_used"] = True

    embedding_config = index.get("embedding", {})
    # #396 / ADR 0023 — pluggable query expansion. Default is the
    # ``IdentityExpander`` so ``naive_baseline`` and any preset without
    # an explicit ``query_expansion`` knob produce a bit-identical
    # ``embed_query_for_index`` call (ADR 0001 golden invariant).
    # HyDE replaces ONLY the dense embedding input — the BM25 / lexical /
    # metadata paths below consume ``analysis.tokens`` (computed
    # upstream from the raw ``query``), so they remain invariant.
    expander = default_expander(plan)
    embed_text, expansion_meta = expander.expand(query, plan=plan)
    plan["query_expansion_meta"] = expansion_meta
    query_embedding = embed_query_for_index(embed_text, embedding_config)
    query_tokens = set(analysis.get("tokens", []))
    query_topics = analysis.get("topics", [])
    retrieval_backend = str(plan.get("retrieval_backend", "dense"))

    bm25_score_by_chunk: dict[str, float] = {}
    if retrieval_backend == "hybrid":
        bm25_score_by_chunk = bm25_scores_for_index(
            index,
            list(query_tokens),
            stopword_profile=str(plan.get("bm25_stopword_profile", "shared")),
        )

    # Issue #151 — BGE-M3 multi-channel spike. Lazy: only entered when
    # the caller opted into ``retrieval_backend = "m3"``. Default ``dense``
    # and ``hybrid`` paths skip the import + forward pass entirely
    # (ADR 0001 bit-identical invariant; public CI never installs the
    # FlagEmbedding dep). Cache is per-index, in-memory only — no schema
    # change to ``index.json`` for the spike.
    m3_sparse_by_chunk: dict[str, float] = {}
    m3_colbert_by_chunk: dict[str, float] = {}
    if retrieval_backend == "m3":
        from rag_m3 import compute_m3_index_cache, get_m3_encoder

        encoder = get_m3_encoder()
        cache = index.get("_m3_cache")
        if cache is None:
            cache = compute_m3_index_cache(encoder, chunks)
            index["_m3_cache"] = cache
        query_m3 = encoder.encode([query])
        q_sparse = query_m3.sparse[0] if query_m3.sparse else {}
        q_colbert = query_m3.colbert[0] if query_m3.colbert else np.zeros((0, 0), dtype=np.float32)
        # Score every chunk against the query on the two new channels.
        # Dense score is reused from the existing ``raw_cosine_by_idx``
        # path below — BGE-M3 dense vectors aren't re-routed through the
        # vector store for the spike; the chunk's existing dense channel
        # (whatever embedding backend built the index) plays the role of
        # the "dense rank". A follow-up PR can swap the dense channel
        # for BGE-M3's if the spike justifies it.
        for chunk_idx, chunk in enumerate(chunks):
            chunk_id = str(chunk.get("chunk_id"))
            m3_sparse_by_chunk[chunk_id] = encoder.sparse_score(
                q_sparse, cache.sparse[chunk_idx] if chunk_idx < len(cache.sparse) else {}
            )
            colbert_vec = (
                cache.colbert[chunk_idx]
                if chunk_idx < len(cache.colbert)
                else np.zeros((0, 0), dtype=np.float32)
            )
            m3_colbert_by_chunk[chunk_id] = encoder.colbert_score(q_colbert, colbert_vec)

    vector_store = index.get("_vector_store")
    # #176 Stage 2c: drive dense scoring through ``VectorStore.query``
    # instead of looping ``store.get(idx)`` + ``dense_similarity`` per
    # chunk. On the default in-memory backend the math is identical
    # (numpy dot on the same L2-normalized matrix, then the same
    # ``(cosine + 1) / 2`` affine clamp). On the Qdrant backend the
    # query is delegated to the Qdrant collection — ranking parity to
    # the in-memory backend is asserted by
    # ``tests/test_vector_store_qdrant.py::test_qdrant_query_matches_in_memory_top_k_ranking``
    # (PR #296, 1e-5 tolerance). Inline-embedding fixtures fall back
    # to the per-chunk ``dense_similarity`` path below.
    raw_cosine_by_idx: dict[int, float] = {}
    if vector_store is not None and len(vector_store) > 0:
        for idx, raw in vector_store.query(query_embedding, top_k=len(vector_store)):
            raw_cosine_by_idx[int(idx)] = float(raw)
    scored = []
    for chunk in candidates:
        embedding_idx = chunk.get("embedding_idx")
        if (
            vector_store is not None
            and embedding_idx is not None
            and int(embedding_idx) in raw_cosine_by_idx
        ):
            raw = raw_cosine_by_idx[int(embedding_idx)]
            # Mirror ``dense_similarity``'s affine clamp so the verifier
            # score floor (rag_core.py:2254, threshold tuned for
            # ``(cosine + 1) / 2``) keeps working byte-identically.
            dense_score = max(0.0, min(1.0, (raw + 1.0) / 2.0))
        else:
            # Defensive fallback: a chunk dict produced outside the normal
            # load_index path (e.g., a hand-crafted test fixture) may still
            # carry an inline embedding. Keeps tests/test_partial_topic_*.py
            # style fixtures working without forcing a sidecar.
            chunk_vec = chunk.get("embedding")
            dense_score = dense_similarity(query_embedding, chunk_vec)
        lexical_score = lexical_similarity(query_tokens, query_topics, chunk)
        metadata_score = metadata_similarity(analysis, chunk)
        chunk_id_str = str(chunk.get("chunk_id"))
        bm25_score = float(bm25_score_by_chunk.get(chunk_id_str, 0.0))
        m3_sparse_score = float(m3_sparse_by_chunk.get(chunk_id_str, 0.0))
        m3_colbert_score = float(m3_colbert_by_chunk.get(chunk_id_str, 0.0))
        if retrieval_backend in ("hybrid", "m3"):
            # RRF backends defer scoring to ``apply_fusion_and_reranking``
            # — the per-chunk score here is a placeholder. The
            # diagnostic ``score_parts`` keys carry the channel-level
            # signals for the fusion stage to rank on.
            score = 0.0
        elif not plan.get("rerank", True):
            score = dense_score
        elif not plan.get("metadata_first", True):
            score = (0.70 * dense_score) + (0.30 * lexical_score)
        else:
            score = (0.60 * dense_score) + (0.25 * lexical_score) + (0.15 * metadata_score)
        score_parts: dict[str, float] = {
            "dense": round(float(dense_score), 4),
            "lexical": round(float(lexical_score), 4),
            "metadata": round(float(metadata_score), 4),
            "bm25": round(float(bm25_score), 4),
        }
        if retrieval_backend == "m3":
            # Diagnostic-only; consumed by N-way RRF downstream. Score
            # ranges: sparse ≥ 0 (SPLADE dot), colbert ∈ [0, T_q]
            # (max-sim sum). Rounded for log stability.
            score_parts["m3_sparse"] = round(float(m3_sparse_score), 4)
            score_parts["m3_colbert"] = round(float(m3_colbert_score), 4)
        item = {
            "doc_id": chunk["doc_id"],
            "chunk_id": chunk["chunk_id"],
            "title": chunk["title"],
            "agency": chunk.get("agency", ""),
            "project": chunk.get("project", ""),
            "metadata": chunk.get("metadata", {}),
            "section": chunk["section"],
            "section_id": chunk.get("section_id"),
            "parent_section_id": chunk.get("parent_section_id") or chunk.get("section_id"),
            "section_path": chunk.get("section_path") or [chunk.get("section", "")],
            "chunk_seq_in_section": chunk.get("chunk_seq_in_section"),
            "total_chunks_in_section": chunk.get("total_chunks_in_section"),
            "chunking_strategy": chunk.get("chunking_strategy", "legacy"),
            "retrieval_mode": "flat",
            "text": chunk["text"],
            "score": round(float(score), 4),
            "score_parts": score_parts,
        }
        regions = normalize_regions(chunk.get("regions"))
        page_span = normalize_page_span(chunk.get("page_span"), regions)
        if regions:
            item["regions"] = regions
        if page_span:
            item["page_span"] = page_span
        scored.append(item)
    return scored



def embed_query_for_index(query: str, embedding_config: dict[str, Any]) -> np.ndarray:
    backend = str(embedding_config.get("backend") or "hashing")
    model = str(embedding_config.get("model") or DEFAULT_EMBEDDING_MODEL)
    dimension = int(embedding_config.get("dimension") or DEFAULT_HASH_DIM)
    if backend == "sentence-transformers":
        try:
            return embed_texts(
                [query],
                model_name=model,
                backend="sentence-transformers",
                local_only=True,
            ).vectors[0]
        except Exception:
            return hashing_embeddings([query], dimension)[0]
    if backend == "openai":
        try:
            return embed_texts([query], model_name=model, backend="openai").vectors[0]
        except Exception:
            return hashing_embeddings([query], dimension)[0]
    return hashing_embeddings([query], dimension)[0]


def dense_similarity(query_vector: np.ndarray, chunk_vector: Any) -> float:
    if chunk_vector is None:
        return 0.0
    doc_vector = np.asarray(chunk_vector, dtype=np.float32)
    if doc_vector.shape != query_vector.shape:
        return 0.0
    score = float(np.dot(query_vector, doc_vector))
    return max(0.0, min(1.0, (score + 1.0) / 2.0))


def _strip_bm25_extra_suffixes(token: str) -> str:
    """Strip ``BM25_EXTRA_PARTICLE_SUFFIXES`` greedily from a pure-Hangul token.

    Mirrors :func:`normalize_metadata_token`'s suffix-stripping loop but
    against the BM25-only extension list (issue #150). Returns the
    original token unchanged for non-Hangul tokens.
    """
    if not re.fullmatch(r"[가-힣]+", token):
        return token
    changed = True
    while changed:
        changed = False
        for suffix in BM25_EXTRA_PARTICLE_SUFFIXES:
            if len(token) > len(suffix) + 1 and token.endswith(suffix):
                token = token[: -len(suffix)]
                changed = True
                break
    return token


def _apply_bm25_extra_filter(tokens: Iterable[str]) -> list[str]:
    """Apply the BM25-extra particle suffix strip + stopword filter (issue #150).

    Called only from the BM25 corpus-build and query-side paths under
    ``bm25_stopword_profile = "bm25_extra"``. Never touches the tokens
    cached on chunks at index time, so the dense + Jaccard lexical
    scoring paths stay bit-stable (issue #150 acceptance criterion).
    """
    out: list[str] = []
    for token in tokens:
        stripped = _strip_bm25_extra_suffixes(str(token))
        if stripped and stripped not in BM25_EXTRA_STOPWORDS:
            out.append(stripped)
    return out


def _chunk_tokens_for_bm25(
    chunk: dict[str, Any],
    stopword_profile: str = "shared",
) -> list[str]:
    tokens = chunk.get("tokens")
    if isinstance(tokens, list) and tokens:
        base = [str(t) for t in tokens]
    else:
        section_path = chunk.get("section_path") or [chunk.get("section", "")]
        text = " ".join(
            [
                chunk.get("title", ""),
                chunk.get("agency", ""),
                chunk.get("project", ""),
                " > ".join(section_path),
                chunk.get("text", ""),
            ]
        )
        base = tokenize(text)
    if stopword_profile == "bm25_extra":
        base = _apply_bm25_extra_filter(base)
    return base


def get_or_build_bm25(
    index: dict[str, Any],
    stopword_profile: str = "shared",
) -> tuple[Any, list[str]]:
    """Lazy-build and cache a BM25Okapi index over chunk tokens.

    Returns the cached ``(bm25, chunk_ids)`` tuple keyed by
    ``stopword_profile`` (issue #150). The ``shared`` profile uses the
    common tokens cached on each chunk; the ``bm25_extra`` profile
    applies :func:`_apply_bm25_extra_filter` (strips the BM25-only
    extension particle set and drops short BM25-only stopwords) before
    constructing BM25Okapi. Each profile gets its own ``BM25Okapi``
    instance inside ``index["_bm25_by_profile"]`` so the IDF
    distribution stays consistent between corpus build and query side.

    For back-compat the ``shared`` build is mirrored at
    ``index["_bm25"]`` / ``index["_bm25_chunk_ids"]`` so any external
    code that inspected those keys keeps working.

    Raises RuntimeError if the optional ``rank_bm25`` dependency is
    missing — the caller must gate on ``retrieval_backend == "hybrid"``.
    """
    if _BM25Okapi is None:
        raise RuntimeError(
            "retrieval_backend='hybrid' requires the 'rank_bm25' package "
            "(install via requirements.txt)."
        )
    if stopword_profile not in VALID_BM25_STOPWORD_PROFILES:
        choices = ", ".join(sorted(VALID_BM25_STOPWORD_PROFILES))
        raise ValueError(f"bm25_stopword_profile must be one of: {choices}")
    profile_cache = index.setdefault("_bm25_by_profile", {})
    entry = profile_cache.get(stopword_profile)
    if isinstance(entry, tuple) and len(entry) == 2:
        return entry  # type: ignore[return-value]
    chunks = index.get("chunks") or []
    corpus = [_chunk_tokens_for_bm25(c, stopword_profile) for c in chunks]
    # rank_bm25 requires at least one non-empty document. If the corpus
    # is entirely empty (degenerate test fixture) substitute a single
    # placeholder token so BM25Okapi doesn't divide by zero.
    if not any(corpus):
        corpus = [["__empty__"] for _ in chunks] or [["__empty__"]]
    bm25 = _BM25Okapi(corpus)
    chunk_ids = [str(c.get("chunk_id")) for c in chunks]
    profile_cache[stopword_profile] = (bm25, chunk_ids)
    if stopword_profile == "shared":
        # Back-compat: legacy callers may still inspect ``_bm25`` /
        # ``_bm25_chunk_ids``. Mirror the shared-profile entry there
        # without exposing the per-profile dict to them.
        index["_bm25"] = bm25
        index["_bm25_chunk_ids"] = chunk_ids
    return bm25, chunk_ids


def bm25_scores_for_index(
    index: dict[str, Any],
    query_tokens: list[str],
    stopword_profile: str = "shared",
) -> dict[str, float]:
    """Return a ``chunk_id -> bm25_score`` map across all chunks in the
    index for the given ``stopword_profile``. Callers filter to their
    candidate slice. Empty query tokens (or tokens that the
    ``bm25_extra`` filter strips to empty) yield an all-zero map.
    """
    chunks = index.get("chunks") or []
    if not query_tokens:
        return {str(c.get("chunk_id")): 0.0 for c in chunks}
    effective_tokens = list(query_tokens)
    if stopword_profile == "bm25_extra":
        effective_tokens = _apply_bm25_extra_filter(effective_tokens)
        if not effective_tokens:
            return {str(c.get("chunk_id")): 0.0 for c in chunks}
    bm25, chunk_ids = get_or_build_bm25(index, stopword_profile)
    raw = bm25.get_scores(effective_tokens)
    return {chunk_id: float(score) for chunk_id, score in zip(chunk_ids, raw)}


def lexical_similarity(query_tokens: set[str], topics: list[str], chunk: dict[str, Any]) -> float:
    if not query_tokens and not topics:
        return 0.0
    section_path = chunk.get("section_path") or [chunk.get("section", "")]
    chunk_text = " ".join(
        [
            chunk.get("title", ""),
            chunk.get("agency", ""),
            chunk.get("project", ""),
            " > ".join(section_path),
            chunk.get("text", ""),
        ]
    ).lower()
    chunk_tokens = set(chunk.get("tokens") or tokenize(chunk_text))
    overlap = len(query_tokens & chunk_tokens) / max(1, len(query_tokens))
    topic_hits = sum(1 for topic in topics if topic.lower() in chunk_text)
    topic_score = topic_hits / max(1, len(topics))
    return min(1.0, (0.55 * overlap) + (0.45 * topic_score))


def metadata_similarity(analysis: dict[str, Any], chunk: dict[str, Any]) -> float:
    doc_scores = analysis.get("metadata_doc_scores") or {}
    doc_id = chunk.get("doc_id")
    if doc_id in doc_scores:
        return float(doc_scores[doc_id])
    entities = analysis.get("entities") or []
    if not entities:
        return 0.0
    return 1.0 if chunk.get("agency") in entities else 0.0


# Partial-topic grounding requires BOTH (a) at least
# PARTIAL_TOPIC_GROUNDING_MIN_MATCHED matched verification topics AND
# (b) the matched fraction to be at least
# PARTIAL_TOPIC_GROUNDING_MIN_FRACTION of all topics. The "≥ 2 matched"
# floor exists because a 1-of-2 incidental-overlap pattern flipped
# intended-abstention real-data cases to `partial` after #69 (see
# issue #89 and the Real-data Decision Log in
# docs/private-100-doc-experiments.md). Genuine partial recovery
# requires structural agreement across multiple topics. Keep both
# guards: the fraction floor still rejects 2-of-5 = 0.4 etc.
# See issue #69 / docs/real-data-failure-taxonomy.md C6, ADR 0004 for
# the strict→relaxed staging policy this implements.
PARTIAL_TOPIC_GROUNDING_MIN_FRACTION = 0.5
PARTIAL_TOPIC_GROUNDING_MIN_MATCHED = 2
PARTIAL_TOPIC_GROUNDING_REASON = "partial_topic_grounding"


def verify_evidence(
    analysis: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    allow_partial_topic: bool = False,
) -> tuple[bool, list[str]]:
    """Verify that ``evidence`` supports the query in ``analysis``.

    When ``allow_partial_topic`` is ``True`` (caller signals this is the
    last retrieval attempt), a partial topic match — at least
    :data:`PARTIAL_TOPIC_GROUNDING_MIN_MATCHED` matched topics AND at
    least :data:`PARTIAL_TOPIC_GROUNDING_MIN_FRACTION` of all topics
    present in the combined evidence text — is accepted with
    ``verified=True`` and a non-blocking
    :data:`PARTIAL_TOPIC_GROUNDING_REASON` in the reasons list. The
    caller (see :func:`answer_status`) maps that reason to
    ``ANSWER_STATUS_PARTIAL`` so the answer surfaces the weaker
    grounding instead of abstaining outright.

    The ``≥ 2 matched`` floor (issue #89) cuts the 1-of-2 incidental
    overlap pattern that flipped real-data intended-abstention cases
    to ``partial`` after #69; the fraction floor remains as a guard
    against weakly-balanced cases like 2-of-5.

    All other checks (low top score, comparison entity / doc coverage)
    remain strict — partial topic grounding does not bypass hallucination
    floors or comparison contracts.
    """
    reasons: list[str] = []
    if not evidence:
        return False, ["no_evidence"]
    if evidence[0]["score"] < 0.18:
        reasons.append("low_top_score")

    combined = " ".join(evidence_text_for_verification(item) for item in evidence).lower()
    # ADR 0007 / issue #170: Korean money/date OR-match. Build canonical form
    # once; substring check tests (form ∈ combined) OR (form ∈ canonical) for
    # each form in expand_forms(topic). Strictly additive — legacy
    # (topic ∈ combined) is preserved as the first branch.
    combined_canonical = normalize_text(combined)
    topics = verification_topics(analysis)
    if topics:
        matched_topic_count = sum(
            1
            for topic in topics
            if any(
                form in combined or form in combined_canonical
                for form in expand_forms(topic.lower())
            )
        )
        if matched_topic_count < len(topics):
            if (
                allow_partial_topic
                and matched_topic_count >= PARTIAL_TOPIC_GROUNDING_MIN_MATCHED
                and (matched_topic_count / len(topics)) >= PARTIAL_TOPIC_GROUNDING_MIN_FRACTION
            ):
                # Soft signal — caller surfaces this as `partial` status.
                reasons.append(PARTIAL_TOPIC_GROUNDING_REASON)
            else:
                reasons.append("topic_not_grounded")

    entities = analysis.get("entities") or []
    if analysis.get("query_type") == "comparison" and len(entities) > 1:
        covered = {item.get("agency") for item in evidence}
        missing = [entity for entity in entities if entity not in covered]
        if missing:
            reasons.append("missing_comparison_entity:" + ",".join(missing))
        if topics:
            missing_topic_entities = []
            for entity in entities:
                entity_evidence = [item for item in evidence if item.get("agency") == entity]
                if entity_evidence and not any(evidence_has_topic(item, topics) for item in entity_evidence):
                    missing_topic_entities.append(entity)
            if missing_topic_entities:
                reasons.append("missing_comparison_topic:" + ",".join(missing_topic_entities))

    matched_doc_ids = analysis.get("matched_doc_ids") or []
    if analysis.get("query_type") == "comparison" and len(matched_doc_ids) > 1:
        covered_doc_ids = {item.get("doc_id") for item in evidence}
        missing_doc_ids = [doc_id for doc_id in matched_doc_ids if doc_id not in covered_doc_ids]
        if missing_doc_ids:
            reasons.append("missing_comparison_doc:" + ",".join(missing_doc_ids))

    # `partial_topic_grounding` is non-blocking: it surfaces the weaker
    # grounding to the answer layer without forcing an abstention.
    blocking_reasons = [reason for reason in reasons if reason != PARTIAL_TOPIC_GROUNDING_REASON]
    return not blocking_reasons, reasons


def specific_topics(analysis: dict[str, Any]) -> list[str]:
    return verification_topics(analysis)


def verification_topics(analysis: dict[str, Any]) -> list[str]:
    metadata_terms = metadata_terms_for_verification(analysis)
    keyword_terms = {
        normalize_metadata_token(keyword)
        for keyword in TOPIC_KEYWORDS
        if normalize_metadata_token(keyword).lower() != "ai"
    }
    topics = []
    for topic in analysis.get("topics", []):
        normalized = normalize_metadata_token(str(topic))
        if not normalized or normalized.lower() == "ai":
            continue
        if normalized in metadata_terms and normalized not in keyword_terms:
            continue
        if normalized in METADATA_GENERIC_TOKENS or normalized in VERIFICATION_INTENT_TOKENS:
            continue
        topics.append(normalized)
    return ordered_unique(topics)


def metadata_terms_for_verification(analysis: dict[str, Any]) -> set[str]:
    values: list[str] = []
    for key in ("entities", "matched_agencies", "matched_projects", "context_entities"):
        values.extend(str(value) for value in analysis.get(key) or [])
    for match in analysis.get("metadata_matches") or []:
        values.extend(
            str(match.get(key) or "")
            for key in ("agency", "project", "value")
        )
        values.extend(str(term) for term in match.get("matched_terms") or [])
    return set(metadata_tokens(" ".join(values)))


EVIDENCE_BOUNDARY = "\n[---EVIDENCE_BOUNDARY---]\n"

_CHAT_TEMPLATE_TOKEN_RE = re.compile(
    r"<\|(?:im_start|im_end|system|user|assistant|tool|begin_of_text|end_of_text|fim_[a-z_]+|endoftext)\|>",
    re.IGNORECASE,
)
_ROLE_TAG_LINE_RE = re.compile(
    r"(?im)^[ \t]*(SYSTEM|ASSISTANT|USER|TOOL)\s*:\s*.+$"
)
_INSTRUCTION_OVERRIDE_LINE_RE = re.compile(
    r"(?im)^[ \t]*(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,80}?\b(?:instructions?|prompts?|rules?|directives?|system|guidance)\b.*$"
)


def neutralize_instruction_patterns(text: str) -> str:
    """Neutralize chat-template and instruction-override patterns in document-controlled text.

    Wraps suspicious lines with ``[INSTRUCTION_LIKE]...[/INSTRUCTION_LIKE]``
    and replaces chat template tokens with ``[REDACTED_CHAT_TOKEN]`` so they
    cannot impersonate role boundaries in downstream LLM consumers. Content
    is preserved (citations remain readable) — see ADR 0008.
    """
    if not text:
        return text
    out = _CHAT_TEMPLATE_TOKEN_RE.sub("[REDACTED_CHAT_TOKEN]", text)
    out = _ROLE_TAG_LINE_RE.sub(
        lambda m: f"[INSTRUCTION_LIKE]{m.group(0)}[/INSTRUCTION_LIKE]", out
    )
    out = _INSTRUCTION_OVERRIDE_LINE_RE.sub(
        lambda m: f"[INSTRUCTION_LIKE]{m.group(0)}[/INSTRUCTION_LIKE]", out
    )
    return out


def evidence_text_for_verification(item: dict[str, Any]) -> str:
    parts = [
        neutralize_instruction_patterns(str(item.get("title", "") or "")),
        neutralize_instruction_patterns(str(item.get("agency", "") or "")),
        neutralize_instruction_patterns(str(item.get("project", "") or "")),
        neutralize_instruction_patterns(str(item.get("section", "") or "")),
        neutralize_instruction_patterns(str(item.get("text", "") or "")),
    ]
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            if value is None or value == "":
                continue
            parts.extend(METADATA_EVIDENCE_LABELS.get(str(key), (str(key),)))
            parts.append(neutralize_instruction_patterns(str(value)))
    return " ".join(str(part) for part in parts if str(part).strip())


def evidence_has_topic(item: dict[str, Any], topics: list[str]) -> bool:
    text = evidence_text_for_verification(item).lower()
    text_canonical = normalize_text(text)
    return any(
        (form in text) or (form in text_canonical)
        for topic in topics
        for form in expand_forms(topic.lower())
    )


def generate_answer(
    query: str,
    analysis: dict[str, Any],
    evidence: list[dict[str, Any]],
    verified: bool,
    verification_reasons: list[str] | None = None,
) -> tuple[dict[str, Any], str, bool]:
    claims = build_claims(analysis, evidence)
    effective_reasons = answer_verification_reasons(analysis, verification_reasons or [])
    status = answer_status(analysis, claims, verified, effective_reasons)
    insufficiency = None
    if status != ANSWER_STATUS_SUPPORTED:
        insufficiency = build_insufficiency(
            query,
            analysis,
            claims,
            verified,
            effective_reasons,
        )

    answer = {
        "schema_version": ANSWER_SCHEMA_VERSION,
        "status": status,
        "status_reason": answer_status_reason(status, verified, effective_reasons),
        "query_type": answer_query_type(analysis, status),
        "summary": answer_summary(query, analysis, claims, status, insufficiency),
        "claims": claims,
        "insufficiency": insufficiency,
    }
    answer_text = render_answer_text(answer)
    return answer, answer_text, status == ANSWER_STATUS_INSUFFICIENT


def answer_verification_reasons(
    analysis: dict[str, Any],
    verification_reasons: list[str],
) -> list[str]:
    reasons = list(verification_reasons)
    if analysis.get("query_type") == "comparison":
        for entity in analysis.get("missing_requested_entities") or []:
            reason = f"missing_requested_entity:{entity}"
            if reason not in reasons:
                reasons.append(reason)
    return reasons


def answer_status_reason(
    status: str,
    verified: bool,
    verification_reasons: list[str],
    code: str | None = None,
) -> dict[str, Any]:
    if code is None:
        if status == ANSWER_STATUS_SUPPORTED:
            code = "verified"
        elif status == ANSWER_STATUS_PARTIAL:
            # Disambiguate between the two partial paths so the status
            # reason is machine-readable: comparison-coverage partial
            # vs partial-topic grounding (#69 / ADR 0004).
            if PARTIAL_TOPIC_GROUNDING_REASON in verification_reasons:
                code = "partial_topic_grounding"
            else:
                code = "partial_comparison"
        else:
            code = "insufficient_evidence"
    return {
        "code": code,
        "verified": bool(verified),
        "verification_reasons": verification_reasons,
    }


def build_claims(analysis: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if analysis.get("query_type") == "comparison" and len(analysis.get("entities", [])) > 1:
        return build_comparison_claims(analysis, evidence)

    return build_extract_claims(analysis, evidence)


def build_comparison_claims(
    analysis: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    claims = []
    used_chunks = set()
    for entity in analysis["entities"]:
        entity_evidence = [item for item in evidence if item.get("agency") == entity]
        if not entity_evidence:
            continue
        item = entity_evidence[0]
        if item["chunk_id"] in used_chunks:
            continue
        used_chunks.add(item["chunk_id"])
        claims.append(make_claim(entity, item, analysis))
    return claims


def build_extract_claims(analysis: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = []
    seen = set()
    for item in evidence:
        metadata_sentences = metadata_claim_sentences(item, analysis)
        for metadata_sentence in metadata_sentences:
            key = (item["chunk_id"], metadata_sentence)
            if key in seen:
                continue
            seen.add(key)
            selected.append(
                make_claim(
                    claim_target(item),
                    item,
                    analysis,
                    sentence=metadata_sentence,
                    support=metadata_sentence,
                )
            )
            if len(selected) >= 2:
                break
        if len(selected) >= 2:
            break

        sentence = best_sentence(item["text"], analysis.get("topics", []), analysis.get("tokens", []))
        if metadata_sentences and not sentence_has_verification_topic(sentence, analysis):
            continue
        key = (item["chunk_id"], sentence)
        if key in seen:
            continue
        seen.add(key)
        selected.append(make_claim(claim_target(item), item, analysis, sentence=sentence))
        if len(selected) >= 2:
            break
    return selected


def make_claim(
    target: str,
    item: dict[str, Any],
    analysis: dict[str, Any],
    sentence: str | None = None,
    support: str | None = None,
) -> dict[str, Any]:
    claim_text = sentence or best_sentence(item["text"], analysis.get("topics", []), analysis.get("tokens", []))
    return {
        "target": target,
        "claim": claim_text,
        "support": support or item["text"],
        "citations": [make_citation(item)],
    }


def claim_target(item: dict[str, Any]) -> str:
    return str(item.get("agency") or item.get("title") or item.get("doc_id") or "unknown")


def make_citation(item: dict[str, Any]) -> dict[str, Any]:
    citation = {
        "doc_id": item.get("doc_id", ""),
        "chunk_id": item.get("chunk_id", ""),
        "title": item.get("title", ""),
        "section": item.get("section", ""),
        "agency": item.get("agency", ""),
    }
    regions = normalize_regions(item.get("regions"))
    page_span = normalize_page_span(item.get("page_span"), regions)
    if regions:
        citation["regions"] = regions
    if page_span:
        citation["page_span"] = page_span
    return citation


def answer_status(
    analysis: dict[str, Any],
    claims: list[dict[str, Any]],
    verified: bool,
    verification_reasons: list[str],
) -> str:
    has_partial_topic = PARTIAL_TOPIC_GROUNDING_REASON in verification_reasons
    if verified:
        has_missing_requested = any(
            reason.startswith("missing_requested_entity") for reason in verification_reasons
        )
        if has_partial_topic and claims:
            # Verified via the relaxed-stage partial-topic path: surface
            # the weaker grounding as ``partial`` rather than the
            # unconditional ``supported`` that strict verification yields.
            return ANSWER_STATUS_PARTIAL
        if not has_missing_requested and not has_partial_topic:
            return ANSWER_STATUS_SUPPORTED
    has_partial_comparison_reason = any(
        reason.startswith("missing_comparison")
        or reason.startswith("missing_requested_entity")
        for reason in verification_reasons
    )
    if analysis.get("query_type") == "comparison" and claims and has_partial_comparison_reason:
        return ANSWER_STATUS_PARTIAL
    return ANSWER_STATUS_INSUFFICIENT


def answer_query_type(analysis: dict[str, Any], status: str) -> str:
    if status == ANSWER_STATUS_INSUFFICIENT:
        return "abstention"
    if analysis.get("query_type") == "comparison":
        return "comparison"
    if analysis.get("query_type") == "follow_up":
        return "follow_up"
    return "single_doc"


def answer_summary(
    query: str,
    analysis: dict[str, Any],
    claims: list[dict[str, Any]],
    status: str,
    insufficiency: dict[str, Any] | None,
) -> str:
    if status == ANSWER_STATUS_INSUFFICIENT:
        return f"제공된 공개 샘플 RFP 근거에서는 '{query}'에 답할 수 있는 내용을 찾지 못했습니다."

    compact_claims = " ".join(f"{claim['target']}: {claim['claim']}" for claim in claims)
    if status == ANSWER_STATUS_PARTIAL:
        missing = ", ".join((insufficiency or {}).get("missing_targets") or [])
        suffix = f" 확인되지 않은 대상: {missing}." if missing else ""
        return f"일부 근거만 확인했습니다. {compact_claims}{suffix}".strip()

    if analysis.get("query_type") == "comparison":
        return compact_claims
    return " ".join(claim["claim"] for claim in claims)


def build_insufficiency(
    query: str,
    analysis: dict[str, Any],
    claims: list[dict[str, Any]],
    verified: bool,
    verification_reasons: list[str],
) -> dict[str, Any]:
    supported_targets = {claim.get("target") for claim in claims}
    checked_entities = analysis.get("entities") or analysis.get("context_entities") or []
    missing_targets = [entity for entity in checked_entities if entity not in supported_targets]
    if not verified and not missing_targets and checked_entities:
        missing_targets = list(checked_entities)
    return {
        "message": f"'{query}'에 대한 충분한 근거를 찾지 못했습니다.",
        "reasons": verification_reasons or (["verification_failed"] if not verified else []),
        "missing_targets": missing_targets,
        "missing_topics": specific_topics(analysis),
        "checked_entities": checked_entities,
        "checked_doc_ids": analysis.get("matched_doc_ids") or [],
    }


def render_answer_text(answer: dict[str, Any]) -> str:
    lines = [str(answer.get("summary") or "").strip()]
    for claim in answer.get("claims") or []:
        citations = claim.get("citations") or []
        citation_ids = ", ".join(citation.get("chunk_id", "") for citation in citations if citation.get("chunk_id"))
        suffix = f" [{citation_ids}]" if citation_ids else ""
        lines.append(f"- {claim.get('target')}: {claim.get('claim')}{suffix}")
    insufficiency = answer.get("insufficiency")
    if insufficiency:
        reasons = ", ".join(insufficiency.get("reasons") or [])
        missing_targets = ", ".join(insufficiency.get("missing_targets") or [])
        details = []
        if reasons:
            details.append(f"사유: {reasons}")
        if missing_targets:
            details.append(f"확인 필요 대상: {missing_targets}")
        if details:
            lines.append("- 근거 부족: " + "; ".join(details))
    return "\n".join(line for line in lines if line)


def best_sentence(text: str, topics: list[str], query_tokens: list[str]) -> str:
    sentences = sentence_split(text) or [text]
    scored = []
    token_set = set(query_tokens)
    for sentence in sentences:
        lowered = sentence.lower()
        topic_hits = sum(1 for topic in topics if topic.lower() in lowered)
        sentence_tokens = set(tokenize(sentence))
        token_hits = len(token_set & sentence_tokens)
        scored.append((topic_hits * 3 + token_hits, len(sentence), sentence))
    scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    return scored[0][2]


def metadata_claim_sentences(item: dict[str, Any], analysis: dict[str, Any]) -> list[str]:
    metadata = item.get("metadata")
    if not isinstance(metadata, dict):
        return []

    sentences = []
    for key in METADATA_CLAIM_LABELS:
        value = metadata.get(key)
        if value is None or value == "":
            continue
        if not metadata_field_requested(key, value, analysis):
            continue
        sentences.append(f"{METADATA_CLAIM_LABELS[key]}: {format_metadata_claim_value(key, value)}")
    return ordered_unique(sentences)


def metadata_field_requested(key: str, value: Any, analysis: dict[str, Any]) -> bool:
    terms = [term for term in verification_topics(analysis) if term]
    if not terms:
        return False

    labels = METADATA_CLAIM_TOPIC_LABELS.get(key) or METADATA_EVIDENCE_LABELS.get(key, (key,))
    label_text = " ".join(str(label) for label in labels)
    value_text = str(value)
    searchable = compact_metadata_text(" ".join([label_text, value_text]))
    for term in terms:
        compact_term = compact_metadata_text(str(term))
        if compact_term and compact_term in searchable:
            return True
    return False


def format_metadata_claim_value(key: str, value: Any) -> str:
    if key == "budget" and isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            return f"{value:,.2f}원"
        return f"{int(value):,}원"
    return str(value)


def sentence_has_verification_topic(sentence: str, analysis: dict[str, Any]) -> bool:
    topics = verification_topics(analysis)
    if not topics:
        return True
    lowered = sentence.lower()
    return any(topic.lower() in lowered for topic in topics)


def select_supporting_evidence(
    analysis: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    topics = [topic.lower() for topic in verification_topics(analysis)]
    topic_matched = [
        item
        for item in evidence
        if not topics or any(topic in evidence_text_for_verification(item).lower() for topic in topics)
    ]

    if analysis.get("query_type") == "comparison" and len(analysis.get("entities", [])) > 1:
        selected = []
        for entity in analysis["entities"]:
            match = next((item for item in topic_matched if item.get("agency") == entity), None)
            if not match and not topics:
                match = next((item for item in evidence if item.get("agency") == entity), None)
            if match:
                selected.append(match)
        if topics:
            return selected or topic_matched[:2]
        return selected or evidence[:2]

    pool = topic_matched or evidence
    return pool[:2]


def metadata_stage_sequence(
    analysis: dict[str, Any],
    metadata_first: bool = True,
    verifier_retry: bool = True,
) -> list[str]:
    if not metadata_first:
        return ["relaxed"]

    filters_by_stage = analysis.get("metadata_filters_by_stage") or {}
    strict_filters = filters_by_stage.get("strict") or {}
    reduced_filters = filters_by_stage.get("reduced") or {}
    stages = []
    if strict_filters:
        stages.append("strict")
    if reduced_filters and reduced_filters != strict_filters:
        stages.append("reduced")
    if not stages:
        return ["relaxed", "relaxed"] if verifier_retry else ["relaxed"]
    if verifier_retry:
        stages.append("relaxed")
    return stages


_PROCESS_WARM = False


class _StageTimer:
    """Accumulate ``time.perf_counter`` deltas (ms) into a dict bucket.

    Adds the elapsed milliseconds to ``bucket[key]`` so re-entering the same
    key (e.g. a stage invoked twice) sums into a single total.

    Optionally wraps the timed region in a ``TraceContext.span`` (ADR
    0010). The span context manager is best-effort — any exception
    from the backend is swallowed so a misbehaving tracer cannot break
    the pipeline.
    """

    def __init__(
        self,
        bucket: dict[str, float],
        key: str,
        *,
        trace: Any = None,
        attrs: dict[str, Any] | None = None,
    ) -> None:
        self.bucket = bucket
        self.key = key
        self._trace = trace
        self._attrs = attrs or {}
        self._span_cm: Any = None

    def __enter__(self) -> "_StageTimer":
        self._t0 = time.perf_counter()
        if self._trace is not None:
            span_name = self.key[:-3] if self.key.endswith("_ms") else self.key
            try:
                self._span_cm = self._trace.span(span_name, **self._attrs)
                self._span_cm.__enter__()
            except Exception:
                self._span_cm = None
        return self

    def __exit__(self, *exc: Any) -> None:
        elapsed_ms = (time.perf_counter() - self._t0) * 1000
        self.bucket[self.key] = self.bucket.get(self.key, 0.0) + elapsed_ms
        if self._span_cm is not None:
            try:
                self._span_cm.__exit__(*exc)
            except Exception:
                pass


def _attach_trace_diagnostics(
    result: dict[str, Any],
    trace_handle: Any,
    backend_name: str,
    unavailable_reason: str | None,
    trace_error: str | None,
) -> None:
    """Inject the ADR 0013 trace fields into ``result['diagnostics']``.

    Calls ``trace_handle.finish(diagnostics)`` to flush the trace and
    capture a URL when the backend supports one. Any exception in
    ``finish`` is swallowed and recorded — the additive-ablation
    invariant requires that tracing never breaks the query path.
    """
    diagnostics = result.setdefault("diagnostics", {})
    trace_url: str | None = None
    if trace_handle is not None:
        try:
            trace_url = trace_handle.finish(diagnostics)
        except Exception as exc:
            trace_error = (trace_error or "") + f"|finish:{type(exc).__name__}:{str(exc)[:120]}"
    diagnostics["trace_url"] = trace_url
    diagnostics["trace_backend"] = backend_name
    diagnostics["trace_unavailable_reason"] = unavailable_reason
    diagnostics["trace_error"] = trace_error or None


def summarize_stage_attempt(
    plan: dict[str, Any],
    verified: bool,
    verification_reasons: list[str],
    *,
    timings: dict[str, float] | None = None,
) -> dict[str, Any]:
    summary = {
        "stage": plan.get("filter_stage"),
        "pipeline": plan.get("pipeline"),
        "prompt_profile": plan.get("prompt_profile"),
        "metadata_filters": plan.get("metadata_filters") or {},
        "top_k": plan.get("top_k"),
        "retrieval_budget": plan.get("retrieval_budget") or {},
        "candidate_count": plan.get("candidate_count"),
        "parent_candidate_count": plan.get("parent_candidate_count"),
        "total_chunks": plan.get("total_chunks"),
        "filter_fallback_used": plan.get("filter_fallback_used", False),
        "retrieval_mode": plan.get("retrieval_mode", "flat"),
        "verified": verified,
        "verification_reasons": verification_reasons,
        "retrieve_ms": round(float((timings or {}).get("retrieve_ms", 0.0)), 2),
        "verify_ms": round(float((timings or {}).get("verify_ms", 0.0)), 2),
    }
    if plan.get("comparison_coverage") is not None:
        summary["comparison_coverage"] = plan["comparison_coverage"]
    return summary


def build_query_rewrite_trace(
    original_query: str,
    resolved_query: str,
    context_resolution: dict[str, Any],
) -> dict[str, Any]:
    rewritten = bool(resolved_query and resolved_query != original_query)
    source = str(context_resolution.get("source") or "none")
    status = str(context_resolution.get("status") or "")
    if rewritten and source == "conversation_state":
        rewrite_type = "conversation_state_prefix"
    elif source == "context_entities":
        rewrite_type = "explicit_context"
    elif status == "needs_clarification":
        rewrite_type = "clarification_required"
    else:
        rewrite_type = "none"

    return {
        "original_query": original_query,
        "resolved_query": resolved_query or original_query,
        "rewritten": rewritten,
        "rewrite_type": rewrite_type,
        "context_source": source,
        "context_status": status,
        "context_resolution_confidence": round(
            float(context_resolution.get("confidence") or 0.0), 3
        ),
        "reason": context_resolution.get("reason", ""),
        "context_entities": context_resolution.get("context_entities") or [],
        "context_projects": context_resolution.get("context_projects") or [],
        "active_doc_ids": context_resolution.get("active_doc_ids") or [],
        "readable_summary": (
            f"{rewrite_type}: {original_query} -> {resolved_query}"
            if rewritten
            else f"{rewrite_type}: query used without text rewrite"
        ),
    }


def build_planner_trace(
    analysis: dict[str, Any],
    plan: dict[str, Any],
    metadata_resolution: dict[str, Any],
    stage_sequence: list[str],
    stage_attempts: list[dict[str, Any]],
    *,
    stage_latencies_ms: dict[str, float] | None = None,
) -> dict[str, Any]:
    attempts = [
        {
            "stage": attempt.get("stage"),
            "top_k": attempt.get("top_k"),
            "verified": bool(attempt.get("verified")),
            "verification_reasons": attempt.get("verification_reasons") or [],
            "metadata_doc_ids": (attempt.get("metadata_filters") or {}).get("doc_ids") or [],
        }
        for attempt in stage_attempts
    ]
    selected_doc_ids = metadata_resolution.get("selected_doc_ids") or []
    query_type = str(analysis.get("query_type") or "")
    filter_stage = str(plan.get("filter_stage") or "")
    top_k = plan.get("top_k")
    latencies = {
        key: round(float((stage_latencies_ms or {}).get(key, 0.0)), 2)
        for key in (
            "query_analysis_ms",
            "context_resolution_ms",
            "answer_generation_ms",
        )
    }
    return {
        "query_type": query_type,
        "pipeline": plan.get("pipeline"),
        "prompt_profile": plan.get("prompt_profile"),
        "strategy": plan.get("strategy"),
        "retrieval_mode": plan.get("retrieval_mode"),
        "metadata_first": bool(plan.get("metadata_first")),
        "rerank": bool(plan.get("rerank")),
        "verifier_retry": bool(plan.get("verifier_retry")),
        "stage_sequence": stage_sequence,
        "selected_stage": filter_stage,
        "selected_top_k": top_k,
        "retrieval_budget": plan.get("retrieval_budget") or {},
        "metadata_candidate_count": metadata_resolution.get("candidate_count"),
        "metadata_selected_doc_ids": selected_doc_ids,
        "metadata_ambiguous": bool(analysis.get("metadata_ambiguous")),
        "comparison_coverage": plan.get("comparison_coverage"),
        "stage_latencies_ms": latencies,
        "attempts": attempts,
        "readable_summary": (
            f"{query_type} planned with {plan.get('pipeline')} "
            f"stage={filter_stage or 'none'} top_k={top_k} "
            f"metadata_docs={selected_doc_ids or 'none'}"
        ),
    }


def build_result_trace(
    original_query: str,
    resolved_query: str,
    analysis: dict[str, Any],
    plan: dict[str, Any],
    metadata_resolution: dict[str, Any],
    context_resolution: dict[str, Any],
    stage_sequence: list[str],
    stage_attempts: list[dict[str, Any]],
    answer: dict[str, Any],
    *,
    stage_latencies_ms: dict[str, float] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "query_rewrite": build_query_rewrite_trace(
            original_query,
            resolved_query,
            context_resolution,
        ),
        "planner": build_planner_trace(
            analysis,
            plan,
            metadata_resolution,
            stage_sequence,
            stage_attempts,
            stage_latencies_ms=stage_latencies_ms,
        ),
        "answer_schema": {
            "schema_version": answer.get("schema_version"),
            "status": answer.get("status"),
            "status_reason": answer.get("status_reason") or {},
            "query_type": answer.get("query_type"),
            "claim_count": len(answer.get("claims") or []),
        },
    }


REDACTED_LIST_PLACEHOLDER = "<redacted>"


def redact_trace(
    trace: dict[str, Any],
    *,
    include_doc_ids: bool = True,
    include_entities: bool = True,
) -> dict[str, Any]:
    """Return a deep copy of `trace` with sensitive list fields masked.

    `include_doc_ids=False` masks active doc ids in query_rewrite, planner
    metadata selections, and per-attempt metadata filters. `include_entities=False`
    masks context entity / project lists. Counts are preserved so reviewers can
    still see structural shape.
    """
    if not isinstance(trace, dict):
        return trace
    redacted = copy.deepcopy(trace)

    def _mask(values: Any) -> list[str]:
        items = values if isinstance(values, list) else []
        return [REDACTED_LIST_PLACEHOLDER] * len(items)

    rewrite = redacted.get("query_rewrite")
    if isinstance(rewrite, dict):
        if not include_entities:
            rewrite["context_entities"] = _mask(rewrite.get("context_entities"))
            rewrite["context_projects"] = _mask(rewrite.get("context_projects"))
        if not include_doc_ids:
            rewrite["active_doc_ids"] = _mask(rewrite.get("active_doc_ids"))

    planner = redacted.get("planner")
    if isinstance(planner, dict) and not include_doc_ids:
        masked_selected = _mask(planner.get("metadata_selected_doc_ids"))
        planner["metadata_selected_doc_ids"] = masked_selected
        attempts = planner.get("attempts")
        if isinstance(attempts, list):
            for attempt in attempts:
                if isinstance(attempt, dict):
                    attempt["metadata_doc_ids"] = _mask(attempt.get("metadata_doc_ids"))
        # readable_summary embeds the selected doc IDs verbatim; rebuild it
        # so masking is consistent with the structured fields.
        planner["readable_summary"] = (
            f"{planner.get('query_type', '')} planned with {planner.get('pipeline')} "
            f"stage={planner.get('selected_stage') or 'none'} "
            f"top_k={planner.get('selected_top_k')} "
            f"metadata_docs={masked_selected or 'none'}"
        )

    return redacted


def clarification_answer(query: str, context_resolution: dict[str, Any]) -> str:
    reason = context_resolution.get("reason")
    if reason == "no_active_state":
        return (
            f"'{query}'는 이전 문맥의 기관이나 사업을 확인해야 답할 수 있습니다. "
            "기관명 또는 사업명을 포함해 다시 질문해 주세요."
        )
    if reason == "ambiguous_active_state":
        entities = ", ".join(
            ordered_unique(
                [
                    *(context_resolution.get("context_entities") or []),
                    *(context_resolution.get("context_projects") or []),
                ]
            )
        )
        return (
            f"'{query}'에서 가리키는 대상이 모호합니다. "
            f"현재 문맥 후보는 {entities}입니다. 기관명 또는 사업명을 하나로 지정해 주세요."
        )
    return (
        f"'{query}'의 생략된 참조를 충분히 확정하지 못했습니다. "
        "기관명 또는 사업명을 포함해 다시 질문해 주세요."
    )


def make_context_clarification_result(
    index: dict[str, Any],
    query: str,
    analysis: dict[str, Any],
    conversation_state: dict[str, Any],
    context_resolution: dict[str, Any],
    started: float,
    metadata_first: bool,
    rerank: bool,
    verifier_retry: bool,
    retrieval_mode: str,
    retrieval_backend: str,
    pipeline: str,
    prompt_profile: str,
    *,
    stage_timings: dict[str, float] | None = None,
    cold_start: bool = False,
    rrf_k: int = RRF_K,
    bm25_stopword_profile: str = "shared",
) -> dict[str, Any]:
    reason = str(context_resolution.get("reason") or "context_resolution_failed")
    analysis = dict(analysis)
    analysis["query_type"] = "follow_up"
    analysis["context_resolution"] = context_resolution
    metadata_resolution = metadata_resolution_diagnostics(
        query,
        analysis,
        selected_stage="",
        decision="clarify",
        reason=reason,
    )
    latency_ms = (time.perf_counter() - started) * 1000
    insufficiency = {
        "message": f"'{query}'의 생략된 참조를 충분히 확정하지 못했습니다.",
        "reasons": [reason],
        "missing_targets": context_resolution.get("context_entities") or [],
        "missing_topics": specific_topics(analysis),
        "checked_entities": context_resolution.get("context_entities") or [],
        "checked_doc_ids": context_resolution.get("active_doc_ids") or [],
    }
    answer = {
        "schema_version": ANSWER_SCHEMA_VERSION,
        "status": ANSWER_STATUS_INSUFFICIENT,
        "status_reason": answer_status_reason(
            ANSWER_STATUS_INSUFFICIENT,
            False,
            [reason],
            code="context_clarification",
        ),
        "query_type": "abstention",
        "summary": clarification_answer(query, context_resolution),
        "claims": [],
        "insufficiency": insufficiency,
    }
    answer_text = render_answer_text(answer)
    plan = {
        "strategy": "conversation-state clarification",
        "pipeline": pipeline,
        "prompt_profile": prompt_profile,
        "metadata_first": metadata_first,
        "rerank": rerank,
        "verifier_retry": verifier_retry,
        "retrieval_mode": retrieval_mode,
        "retrieval_backend": retrieval_backend,
        "rrf_k": int(rrf_k),
        "bm25_stopword_profile": bm25_stopword_profile,
        "metadata_filters": {},
        "top_k": None,
        "retrieval_budget": {
            "selected_top_k": None,
            "query_type": "follow_up",
            "reason": "clarification_before_retrieval",
            "defaults": dict(QUERY_TYPE_TOP_K_DEFAULTS),
        },
        "relaxed": False,
        "retry_policy": "clarify before retrieval when entity resolution is weak",
    }
    trace = build_result_trace(
        query,
        context_resolution.get("resolved_query") or query,
        analysis,
        plan,
        metadata_resolution,
        context_resolution,
        [],
        [],
        answer,
        stage_latencies_ms=stage_timings,
    )
    return {
        "mode": "rag",
        "query": query,
        "resolved_query": context_resolution.get("resolved_query") or query,
        "analysis": analysis,
        "plan": plan,
        "answer": answer,
        "answer_text": answer_text,
        "evidence": [],
        "trace": trace,
        "conversation_state": conversation_state,
        "diagnostics": {
            "latency_ms": round(latency_ms, 2),
            "retry_count": 0,
            "abstained": True,
            "answer_status": answer["status"],
            "answer_query_type": answer["query_type"],
            "claim_count": 0,
            "citation_count": 0,
            "verification_reasons": [reason],
            "filter_stage_attempts": [],
            "final_relaxation_reason": [],
            "context_resolution": context_resolution,
            "metadata_resolution": metadata_resolution,
            "selected_top_k": None,
            "embedding_backend": index.get("embedding", {}).get("backend"),
            "embedding_model": index.get("embedding", {}).get("model"),
            "metadata_first": metadata_first,
            "rerank": rerank,
            "verifier_retry": verifier_retry,
            "retrieval_mode": retrieval_mode,
            "retrieval_backend": retrieval_backend,
            "rrf_k": int(rrf_k),
            "bm25_stopword_profile": bm25_stopword_profile,
            "pipeline": pipeline,
            "prompt_profile": prompt_profile,
            "cold_start": cold_start,
            "stage_latency": {
                "query_analysis_ms": round(float((stage_timings or {}).get("query_analysis_ms", 0.0)), 2),
                "context_resolution_ms": round(float((stage_timings or {}).get("context_resolution_ms", 0.0)), 2),
                "answer_generation_ms": round(float((stage_timings or {}).get("answer_generation_ms", 0.0)), 2),
            },
        },
    }


def metadata_clarification_answer(query: str, analysis: dict[str, Any]) -> str:
    """Clarification text shown when ambiguous metadata matches force
    abstention (issue #72).

    Lists each candidate as `agency · project (doc_id)` so the user can
    pick a more specific phrasing without having to look up doc_ids.
    Falls back to bare doc_ids if metadata_matches don't carry agency /
    project (defensive — should not happen on well-formed indexes).
    """
    ambiguity = analysis.get("metadata_ambiguity") or {}
    candidate_doc_ids = ambiguity.get("candidate_doc_ids") or analysis.get("matched_doc_ids") or []
    metadata_matches = analysis.get("metadata_matches") or []
    agency_project_by_doc: dict[str, str] = {}
    for match in metadata_matches:
        doc_id = match.get("doc_id")
        if doc_id and doc_id not in agency_project_by_doc:
            agency = (match.get("agency") or "").strip()
            project = (match.get("project") or "").strip()
            if agency and project:
                agency_project_by_doc[doc_id] = f"{agency} · {project}"
            elif agency:
                agency_project_by_doc[doc_id] = agency
            elif project:
                agency_project_by_doc[doc_id] = project
    candidates_rendered = []
    for doc_id in candidate_doc_ids:
        label = agency_project_by_doc.get(doc_id)
        if label:
            candidates_rendered.append(f"{label} ({doc_id})")
        else:
            candidates_rendered.append(doc_id)
    if not candidates_rendered:
        suffix = ""
    else:
        joined = ", ".join(candidates_rendered)
        suffix = f" 현재 후보는 {joined}입니다."
    return (
        f"'{query}'에서 가리키는 기관 또는 사업 후보가 여러 개라서 하나로 확정할 수 없습니다."
        f"{suffix} 기관명 또는 사업명을 더 구체적으로 지정해 주세요."
    )


def make_metadata_clarification_result(
    index: dict[str, Any],
    query: str,
    retrieval_query: str,
    analysis: dict[str, Any],
    conversation_state: dict[str, Any],
    context_resolution: dict[str, Any],
    started: float,
    metadata_first: bool,
    rerank: bool,
    verifier_retry: bool,
    retrieval_mode: str,
    retrieval_backend: str,
    pipeline: str,
    prompt_profile: str,
    *,
    stage_timings: dict[str, float] | None = None,
    cold_start: bool = False,
    rrf_k: int = RRF_K,
    bm25_stopword_profile: str = "shared",
) -> dict[str, Any]:
    reason = "metadata_ambiguous"
    analysis = dict(analysis)
    analysis["context_resolution"] = context_resolution
    metadata_resolution = metadata_resolution_diagnostics(
        retrieval_query,
        analysis,
        selected_stage="reduced",
        decision="clarify",
        reason=reason,
    )
    latency_ms = (time.perf_counter() - started) * 1000
    checked_entities = ordered_unique(
        [
            *(analysis.get("entities") or []),
            *(analysis.get("matched_projects") or []),
        ]
    )
    insufficiency = {
        "message": f"'{query}'의 기관 또는 사업 후보를 충분히 확정하지 못했습니다.",
        "reasons": [reason],
        "missing_targets": checked_entities,
        "missing_topics": specific_topics(analysis),
        "checked_entities": checked_entities,
        "checked_doc_ids": analysis.get("matched_doc_ids") or [],
    }
    answer = {
        "schema_version": ANSWER_SCHEMA_VERSION,
        "status": ANSWER_STATUS_INSUFFICIENT,
        "status_reason": answer_status_reason(
            ANSWER_STATUS_INSUFFICIENT,
            False,
            [reason],
            code="metadata_ambiguity_clarification",
        ),
        "query_type": "abstention",
        "summary": metadata_clarification_answer(query, analysis),
        "claims": [],
        "insufficiency": insufficiency,
    }
    answer_text = render_answer_text(answer)
    plan = {
        "strategy": "metadata ambiguity clarification",
        "pipeline": pipeline,
        "prompt_profile": prompt_profile,
        "metadata_first": metadata_first,
        "rerank": rerank,
        "verifier_retry": verifier_retry,
        "retrieval_mode": retrieval_mode,
        "retrieval_backend": retrieval_backend,
        "rrf_k": int(rrf_k),
        "bm25_stopword_profile": bm25_stopword_profile,
        "metadata_filters": {},
        "top_k": None,
        "retrieval_budget": {
            "selected_top_k": None,
            "query_type": analysis.get("query_type"),
            "reason": "clarification_before_retrieval",
            "defaults": dict(QUERY_TYPE_TOP_K_DEFAULTS),
        },
        "relaxed": False,
        "retry_policy": "clarify before retrieval when metadata resolution is ambiguous",
    }
    trace = build_result_trace(
        query,
        retrieval_query,
        analysis,
        plan,
        metadata_resolution,
        context_resolution,
        [],
        [],
        answer,
        stage_latencies_ms=stage_timings,
    )
    return {
        "mode": "rag",
        "query": query,
        "resolved_query": retrieval_query,
        "analysis": analysis,
        "plan": plan,
        "answer": answer,
        "answer_text": answer_text,
        "evidence": [],
        "trace": trace,
        "conversation_state": conversation_state,
        "diagnostics": {
            "latency_ms": round(latency_ms, 2),
            "retry_count": 0,
            "abstained": True,
            "answer_status": answer["status"],
            "answer_query_type": answer["query_type"],
            "claim_count": 0,
            "citation_count": 0,
            "verification_reasons": [reason],
            "verification_topics": verification_topics(analysis),
            "filter_stage_attempts": [],
            "final_relaxation_reason": [],
            "context_resolution": context_resolution,
            "metadata_resolution": metadata_resolution,
            "selected_top_k": None,
            "embedding_backend": index.get("embedding", {}).get("backend"),
            "embedding_model": index.get("embedding", {}).get("model"),
            "metadata_first": metadata_first,
            "rerank": rerank,
            "verifier_retry": verifier_retry,
            "retrieval_mode": retrieval_mode,
            "retrieval_backend": retrieval_backend,
            "rrf_k": int(rrf_k),
            "bm25_stopword_profile": bm25_stopword_profile,
            "pipeline": pipeline,
            "prompt_profile": prompt_profile,
            "cold_start": cold_start,
            "stage_latency": {
                "query_analysis_ms": round(float((stage_timings or {}).get("query_analysis_ms", 0.0)), 2),
                "context_resolution_ms": round(float((stage_timings or {}).get("context_resolution_ms", 0.0)), 2),
                "answer_generation_ms": round(float((stage_timings or {}).get("answer_generation_ms", 0.0)), 2),
            },
        },
    }


def update_conversation_state(
    conversation_state: dict[str, Any],
    original_query: str,
    resolved_query: str,
    analysis: dict[str, Any],
    evidence: list[dict[str, Any]],
    context_resolution: dict[str, Any],
) -> dict[str, Any]:
    active_doc_ids = ordered_unique(
        [
            *coerce_string_list(analysis.get("matched_doc_ids")),
            *(item.get("doc_id", "") for item in evidence),
        ]
    )
    active_agencies = ordered_unique(
        [
            *coerce_string_list(analysis.get("entities")),
            *(item.get("agency", "") for item in evidence),
        ]
    )
    active_projects = ordered_unique(
        [
            *coerce_string_list(analysis.get("matched_projects")),
            *(item.get("project", "") for item in evidence),
        ]
    )
    active_topics = coerce_string_list(analysis.get("topics"))
    active_candidates = [
        {
            "doc_id": doc_id,
            "agency": next((item.get("agency", "") for item in evidence if item.get("doc_id") == doc_id), ""),
            "project": next((item.get("project", "") for item in evidence if item.get("doc_id") == doc_id), ""),
        }
        for doc_id in active_doc_ids
    ]

    if not (active_doc_ids or active_agencies or active_projects):
        return conversation_state

    metadata_confidence = float(analysis.get("metadata_confidence") or 0.0)
    resolution_confidence = float(context_resolution.get("confidence") or 0.0)
    confidence = max(metadata_confidence, resolution_confidence, 0.85)
    if analysis.get("metadata_ambiguous"):
        confidence = min(confidence, 0.65)

    turns = list(conversation_state.get("turns") or [])
    turns.append(
        {
            "turn": len(turns) + 1,
            "query": original_query,
            "resolved_query": resolved_query,
            "active_agencies": active_agencies,
            "active_projects": active_projects,
            "active_topics": active_topics,
            "active_doc_ids": active_doc_ids,
            "context_resolution": {
                "status": context_resolution.get("status"),
                "source": context_resolution.get("source"),
                "confidence": context_resolution.get("confidence"),
                "reason": context_resolution.get("reason", ""),
                "context_entities": context_resolution.get("context_entities", []),
                "context_projects": context_resolution.get("context_projects", []),
                "active_doc_ids": context_resolution.get("active_doc_ids", []),
            },
        }
    )

    return {
        "schema_version": CONVERSATION_STATE_SCHEMA_VERSION,
        "active_agencies": active_agencies,
        "active_projects": active_projects,
        "active_topics": active_topics,
        "active_doc_ids": active_doc_ids,
        "active_candidates": active_candidates,
        "confidence": round(float(confidence), 3),
        "ambiguous": bool(analysis.get("metadata_ambiguous")),
        "turns": turns[-MAX_CONVERSATION_TURNS:],
    }


@dataclass
class _RunContext:
    """Mutable per-query state threaded through the ``run_rag_query`` phase functions.

    ADR 0022 stage 2 decomposes ``run_rag_query`` into
    :func:`_phase_analyze` / :func:`_phase_retrieve_loop` /
    :func:`_phase_build_answer` so the LangGraph orchestrator in
    :mod:`rag_graph_agentic_full` can call the same phase code that the
    direct path runs. JSON-identity vs the direct path therefore holds
    by construction. Underscore-prefixed because
    :mod:`rag_graph_agentic_full` is the only intended consumer.
    """

    index: dict[str, Any]
    query: str
    context_entities: list[str] | None
    top_k: int | None
    requested_top_k: int | None
    metadata_first: bool
    rerank: bool
    verifier_retry: bool
    retrieval_mode: str
    retrieval_backend: str
    pipeline_name: str
    prompt_profile: str
    rrf_k: int
    bm25_stopword_profile: str
    resolved_comparison_balance: Any
    state: dict[str, Any]
    targets: list[dict[str, Any]]
    query_hash: str
    cold_start: bool
    started: float
    stage_timings: dict[str, float]
    trace_backend_obj: Any
    trace_backend_name: str
    trace_unavailable_reason: Any
    trace_error: Any
    trace_handle: Any
    retrieval_query: str = ""
    effective_context_entities: list[str] | None = None
    context_resolution: dict[str, Any] | None = None
    analysis: dict[str, Any] | None = None
    stage_sequence: list[Any] | None = None
    stage_attempts: list[dict[str, Any]] | None = None
    retry_count: int = 0
    plan: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] | None = None
    verified: bool = False
    verification_reasons: list[str] | None = None
    retrieved_chunk_ids: list[str] | None = None


def _build_run_context(
    index: dict[str, Any],
    query: str,
    *,
    top_k: int | None,
    context_entities: list[str] | None,
    metadata_first: bool | None,
    rerank: bool | None,
    verifier_retry: bool | None,
    retrieval_mode: str | None,
    retrieval_backend: str | None,
    pipeline: str | None,
    prompt_profile: str | None,
    conversation_state: dict[str, Any] | None,
    comparison_balance: dict[str, Any] | None,
    rrf_k: int | None,
    bm25_stopword_profile: str | None,
    params: QueryParams | None,
) -> _RunContext:
    """Normalize raw ``run_rag_query`` inputs into a :class:`_RunContext`.

    Handles ``params=`` bundle normalization, pipeline-preset resolution,
    the ``_PROCESS_WARM`` cold-start flag, query hashing, the
    ``query_start`` log event, and trace-backend startup. Splitting this
    out of ``run_rag_query`` lets the LangGraph orchestrator
    (ADR 0022 stage 2) build the context once and pass it through the
    three graph nodes.
    """
    if params is not None:
        legacy_pipeline_kwargs = {
            "top_k": top_k,
            "metadata_first": metadata_first,
            "rerank": rerank,
            "verifier_retry": verifier_retry,
            "retrieval_mode": retrieval_mode,
            "retrieval_backend": retrieval_backend,
            "pipeline": pipeline,
            "prompt_profile": prompt_profile,
            "comparison_balance": comparison_balance,
            "rrf_k": rrf_k,
            "bm25_stopword_profile": bm25_stopword_profile,
        }
        conflicting = sorted(k for k, v in legacy_pipeline_kwargs.items() if v is not None)
        if conflicting:
            raise ValueError(
                "run_rag_query: cannot mix params= with explicit pipeline kwargs; "
                f"set them on the QueryParams instance instead. Conflicting kwargs: {conflicting}"
            )
        top_k = params.top_k
        metadata_first = params.metadata_first
        rerank = params.rerank
        verifier_retry = params.verifier_retry
        retrieval_mode = params.retrieval_mode
        retrieval_backend = params.retrieval_backend
        pipeline = params.pipeline
        prompt_profile = params.prompt_profile
        comparison_balance = params.comparison_balance
        rrf_k = params.rrf_k
        bm25_stopword_profile = params.bm25_stopword_profile

    pipeline_source: dict[str, Any] = {"pipeline": pipeline or DEFAULT_RAG_PIPELINE_NAME}
    for key, value in (
        ("top_k", top_k),
        ("metadata_first", metadata_first),
        ("rerank", rerank),
        ("verifier_retry", verifier_retry),
        ("retrieval_mode", retrieval_mode),
        ("retrieval_backend", retrieval_backend),
        ("prompt_profile", prompt_profile),
        ("rrf_k", rrf_k),
        ("bm25_stopword_profile", bm25_stopword_profile),
    ):
        if value is not None:
            pipeline_source[key] = value
    if comparison_balance is not None:
        pipeline_source["comparison_balance"] = comparison_balance
    pipeline_config = resolve_pipeline_config(
        pipeline_source,
        default_pipeline=DEFAULT_RAG_PIPELINE_NAME,
    )
    resolved_top_k = pipeline_config["top_k"]
    requested_top_k = resolved_top_k
    metadata_first_val = bool(pipeline_config["metadata_first"])
    rerank_val = bool(pipeline_config["rerank"])
    verifier_retry_val = bool(pipeline_config["verifier_retry"])
    retrieval_mode_val = str(pipeline_config["retrieval_mode"])
    retrieval_backend_val = str(pipeline_config["retrieval_backend"])
    pipeline_name = str(pipeline_config["pipeline"])
    prompt_profile_val = str(pipeline_config["prompt_profile"])
    rrf_k_val = int(pipeline_config["rrf_k"])
    bm25_stopword_profile_val = str(pipeline_config["bm25_stopword_profile"])
    resolved_comparison_balance = pipeline_config.get("comparison_balance")

    global _PROCESS_WARM
    cold_start = not _PROCESS_WARM
    if cold_start:
        _PROCESS_WARM = True

    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]
    log_query_event(
        _LOGGER,
        "query_start",
        query_hash=query_hash,
        query_length=len(query),
        pipeline=pipeline_name,
        prompt_profile=prompt_profile_val,
        retrieval_backend=retrieval_backend_val,
        retrieval_mode=retrieval_mode_val,
        top_k=requested_top_k,
        cold_start=cold_start,
    )

    started = time.perf_counter()
    stage_timings: dict[str, float] = {}
    state = normalize_conversation_state(conversation_state)
    targets = metadata_targets(index)

    trace_backend_obj, trace_backend_name, trace_unavailable_reason = resolve_trace_backend()
    trace_error: str | None = None
    trace_handle: Any = None
    if trace_backend_name != "none":
        try:
            trace_handle = trace_backend_obj.start_trace(
                query,
                {
                    "pipeline": pipeline_name,
                    "prompt_profile": prompt_profile_val,
                    "embedding_backend": index.get("embedding", {}).get("backend"),
                    "retrieval_backend": retrieval_backend_val,
                    "retrieval_mode": retrieval_mode_val,
                    "metadata_first": metadata_first_val,
                    "rerank": rerank_val,
                    "verifier_retry": verifier_retry_val,
                    "cold_start": cold_start,
                },
            )
        except Exception as exc:
            trace_error = f"start_trace:{type(exc).__name__}:{str(exc)[:120]}"
            trace_handle = None

    return _RunContext(
        index=index,
        query=query,
        context_entities=context_entities,
        top_k=resolved_top_k,
        requested_top_k=requested_top_k,
        metadata_first=metadata_first_val,
        rerank=rerank_val,
        verifier_retry=verifier_retry_val,
        retrieval_mode=retrieval_mode_val,
        retrieval_backend=retrieval_backend_val,
        pipeline_name=pipeline_name,
        prompt_profile=prompt_profile_val,
        rrf_k=rrf_k_val,
        bm25_stopword_profile=bm25_stopword_profile_val,
        resolved_comparison_balance=resolved_comparison_balance,
        state=state,
        targets=targets,
        query_hash=query_hash,
        cold_start=cold_start,
        started=started,
        stage_timings=stage_timings,
        trace_backend_obj=trace_backend_obj,
        trace_backend_name=trace_backend_name,
        trace_unavailable_reason=trace_unavailable_reason,
        trace_error=trace_error,
        trace_handle=trace_handle,
    )


def _phase_analyze(ctx: _RunContext) -> dict[str, Any] | None:
    """Run query analysis + context resolution + ambiguity check (ADR 0022 stage 2).

    Returns a final result dict if the query short-circuits with a
    context-clarification or metadata-ambiguity reply, otherwise ``None``
    after mutating ``ctx`` with the analysis outputs that
    :func:`_phase_retrieve_loop` and :func:`_phase_build_answer` consume.
    """
    with _StageTimer(ctx.stage_timings, "query_analysis_ms", trace=ctx.trace_handle, attrs={"iteration": 1}):
        initial_analysis = analyze_query(ctx.query, ctx.targets)
    with _StageTimer(ctx.stage_timings, "context_resolution_ms", trace=ctx.trace_handle):
        retrieval_query, effective_context_entities, context_resolution = resolve_conversation_context(
            ctx.query,
            initial_analysis,
            ctx.state,
            context_entities=ctx.context_entities,
        )
    if context_resolution["status"] == "needs_clarification":
        result = make_context_clarification_result(
            ctx.index,
            ctx.query,
            initial_analysis,
            ctx.state,
            context_resolution,
            ctx.started,
            ctx.metadata_first,
            ctx.rerank,
            ctx.verifier_retry,
            ctx.retrieval_mode,
            ctx.retrieval_backend,
            ctx.pipeline_name,
            ctx.prompt_profile,
            stage_timings=ctx.stage_timings,
            cold_start=ctx.cold_start,
            rrf_k=ctx.rrf_k,
            bm25_stopword_profile=ctx.bm25_stopword_profile,
        )
        _attach_trace_diagnostics(
            result,
            ctx.trace_handle,
            ctx.trace_backend_name,
            ctx.trace_unavailable_reason,
            ctx.trace_error,
        )
        return result

    with _StageTimer(ctx.stage_timings, "query_analysis_ms", trace=ctx.trace_handle, attrs={"iteration": 2}):
        analysis = analyze_query(
            retrieval_query,
            ctx.targets,
            context_entities=effective_context_entities,
        )
    if context_resolution["source"] in {"conversation_state", "context_entities"}:
        analysis["query_type"] = "follow_up"
        analysis["context_used"] = True
    analysis["context_resolution"] = context_resolution
    if ctx.trace_handle is not None:
        try:
            ctx.trace_handle.set_tag("query_type", str(analysis.get("query_type") or ""))
        except Exception:
            pass
    if analysis.get("metadata_ambiguous") and analysis.get("query_type") != "comparison":
        result = make_metadata_clarification_result(
            ctx.index,
            ctx.query,
            retrieval_query,
            analysis,
            ctx.state,
            context_resolution,
            ctx.started,
            ctx.metadata_first,
            ctx.rerank,
            ctx.verifier_retry,
            ctx.retrieval_mode,
            ctx.retrieval_backend,
            ctx.pipeline_name,
            ctx.prompt_profile,
            stage_timings=ctx.stage_timings,
            cold_start=ctx.cold_start,
            rrf_k=ctx.rrf_k,
            bm25_stopword_profile=ctx.bm25_stopword_profile,
        )
        _attach_trace_diagnostics(
            result,
            ctx.trace_handle,
            ctx.trace_backend_name,
            ctx.trace_unavailable_reason,
            ctx.trace_error,
        )
        return result

    stage_sequence = metadata_stage_sequence(
        analysis,
        metadata_first=ctx.metadata_first,
        verifier_retry=ctx.verifier_retry,
    )
    if len(stage_sequence) > MAX_AGENT_ITERATIONS:
        raise RuntimeError(
            f"stage_sequence length {len(stage_sequence)} exceeds "
            f"MAX_AGENT_ITERATIONS={MAX_AGENT_ITERATIONS}; "
            "update MAX_AGENT_ITERATIONS and revisit the loop contract."
        )

    ctx.retrieval_query = retrieval_query
    ctx.effective_context_entities = effective_context_entities
    ctx.context_resolution = context_resolution
    ctx.analysis = analysis
    ctx.stage_sequence = stage_sequence
    return None


def _phase_retrieve_loop(ctx: _RunContext) -> None:
    """Run the metadata-stage retry loop (ADR 0022 stage 2).

    Mutates ``ctx`` with ``stage_attempts``, ``retry_count``, ``plan``,
    ``evidence``, ``verified``, ``verification_reasons``,
    ``retrieved_chunk_ids``.
    """
    stage_attempts: list[dict[str, Any]] = []
    retry_count = 0
    plan: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []
    verified = False
    verification_reasons: list[str] = []

    stage_sequence = ctx.stage_sequence or []
    analysis = ctx.analysis or {}
    for attempt_index, stage in enumerate(stage_sequence):
        attempt_top_k = ctx.top_k
        top_k_reason = None
        if ctx.requested_top_k is not None:
            top_k_reason = "pipeline_or_explicit_override"
        if attempt_index > 0:
            attempt_top_k = max(ctx.top_k or 0, 8)
            top_k_reason = "retry_expansion"
        attempt_timings: dict[str, float] = {}
        with _StageTimer(
            attempt_timings,
            "retrieve_ms",
            trace=ctx.trace_handle,
            attrs={"attempt_index": attempt_index, "stage": str(stage or ""), "top_k": attempt_top_k or 0},
        ):
            plan = make_plan(
                analysis,
                top_k=attempt_top_k,
                top_k_reason=top_k_reason,
                stage=stage,
                metadata_first=ctx.metadata_first,
                rerank=ctx.rerank,
                verifier_retry=ctx.verifier_retry,
                retrieval_mode=ctx.retrieval_mode,
                retrieval_backend=ctx.retrieval_backend,
                pipeline=ctx.pipeline_name,
                prompt_profile=ctx.prompt_profile,
                comparison_balance=ctx.resolved_comparison_balance,
                rrf_k=ctx.rrf_k,
                bm25_stopword_profile=ctx.bm25_stopword_profile,
            )
            evidence = retrieve(ctx.index, ctx.retrieval_query, analysis, plan)
        with _StageTimer(
            attempt_timings,
            "verify_ms",
            trace=ctx.trace_handle,
            attrs={"attempt_index": attempt_index, "verifier_retry": ctx.verifier_retry},
        ):
            if ctx.verifier_retry:
                is_last_attempt = attempt_index == len(stage_sequence) - 1
                verified, verification_reasons = verify_evidence(
                    analysis,
                    evidence,
                    allow_partial_topic=is_last_attempt,
                )
            else:
                verified = bool(evidence)
                verification_reasons = [] if verified else ["no_evidence"]
        stage_attempts.append(
            summarize_stage_attempt(plan, verified, verification_reasons, timings=attempt_timings)
        )
        if verified:
            break
        if attempt_index < len(stage_sequence) - 1:
            retry_count += 1

    retrieved_chunk_ids: list[str] = [
        str(item.get("chunk_id") or "") for item in evidence if item.get("chunk_id")
    ]

    if verified or analysis.get("query_type") == "comparison":
        evidence = select_supporting_evidence(analysis, evidence)
    else:
        evidence = []

    ctx.stage_attempts = stage_attempts
    ctx.retry_count = retry_count
    ctx.plan = plan
    ctx.evidence = evidence
    ctx.verified = verified
    ctx.verification_reasons = verification_reasons
    ctx.retrieved_chunk_ids = retrieved_chunk_ids


def _phase_build_answer(ctx: _RunContext) -> dict[str, Any]:
    """Build the final answer and result dict (ADR 0022 stage 2).

    Reads phase-1/2 outputs from ``ctx``, writes the ``query_complete``
    log event, attaches trace diagnostics, and returns the result dict
    in the same key order as the legacy ``run_rag_query`` body — the
    JSON-identity contract pinned by
    ``tests/test_langgraph_orchestrator_regression.py``.
    """
    analysis = ctx.analysis or {}
    evidence = ctx.evidence or []
    verification_reasons = ctx.verification_reasons or []
    plan = ctx.plan or {}
    stage_attempts = ctx.stage_attempts or []

    with _StageTimer(ctx.stage_timings, "answer_generation_ms", trace=ctx.trace_handle):
        answer, answer_text, abstained = generate_answer(
            ctx.query,
            analysis,
            evidence,
            ctx.verified,
            verification_reasons,
        )
    synthesis_meta: dict[str, Any] | None = None
    if ctx.prompt_profile == "llm_synthesis" and not abstained:
        with _StageTimer(ctx.stage_timings, "synthesis_ms", trace=ctx.trace_handle, attrs={"prompt_profile": ctx.prompt_profile}):
            synthesized, synthesis_meta = synthesize_answer(
                ctx.query, analysis, answer, evidence
            )
        if synthesized is not None:
            answer = synthesized
            answer_text = synthesized.get("answer_text", answer_text)
    next_state = update_conversation_state(
        ctx.state,
        ctx.query,
        ctx.retrieval_query,
        analysis,
        evidence,
        ctx.context_resolution,
    )
    latency_ms = (time.perf_counter() - ctx.started) * 1000
    stage_latency = {
        "query_analysis_ms": round(ctx.stage_timings.get("query_analysis_ms", 0.0), 2),
        "context_resolution_ms": round(ctx.stage_timings.get("context_resolution_ms", 0.0), 2),
        "answer_generation_ms": round(ctx.stage_timings.get("answer_generation_ms", 0.0), 2),
    }
    if "synthesis_ms" in ctx.stage_timings:
        stage_latency["synthesis_ms"] = round(ctx.stage_timings.get("synthesis_ms", 0.0), 2)
    metadata_resolution = metadata_resolution_diagnostics(
        ctx.retrieval_query,
        analysis,
        selected_stage=str(plan.get("filter_stage") or ""),
    )
    result_trace = build_result_trace(
        ctx.query,
        ctx.retrieval_query,
        analysis,
        plan,
        metadata_resolution,
        ctx.context_resolution,
        ctx.stage_sequence,
        stage_attempts,
        answer,
        stage_latencies_ms=stage_latency,
    )
    diagnostics: dict[str, Any] = {
        "latency_ms": round(latency_ms, 2),
        "retry_count": ctx.retry_count,
        "abstained": abstained,
        "answer_status": answer["status"],
        "answer_query_type": answer["query_type"],
        "claim_count": len(answer["claims"]),
        "citation_count": sum(len(claim.get("citations") or []) for claim in answer["claims"]),
        "verification_reasons": (answer.get("status_reason") or {}).get("verification_reasons") or verification_reasons,
        "verification_topics": verification_topics(analysis),
        "filter_stage_attempts": stage_attempts,
        "retrieved_chunk_ids": ctx.retrieved_chunk_ids,
        "final_relaxation_reason": stage_attempts[-2]["verification_reasons"] if ctx.retry_count and len(stage_attempts) >= 2 else [],
        "context_resolution": ctx.context_resolution,
        "metadata_resolution": metadata_resolution,
        "selected_top_k": plan.get("top_k"),
        "embedding_backend": ctx.index.get("embedding", {}).get("backend"),
        "embedding_model": ctx.index.get("embedding", {}).get("model"),
        "metadata_first": ctx.metadata_first,
        "rerank": ctx.rerank,
        "verifier_retry": ctx.verifier_retry,
        "retrieval_mode": ctx.retrieval_mode,
        "retrieval_backend": ctx.retrieval_backend,
        "rrf_k": int(ctx.rrf_k),
        "bm25_stopword_profile": ctx.bm25_stopword_profile,
        "pipeline": ctx.pipeline_name,
        "prompt_profile": ctx.prompt_profile,
        "cold_start": ctx.cold_start,
        "stage_latency": stage_latency,
        "synthesis": synthesis_meta,
    }
    result = {
        "mode": "rag",
        "query": ctx.query,
        "resolved_query": ctx.retrieval_query,
        "analysis": analysis,
        "plan": plan,
        "answer": answer,
        "answer_text": answer_text,
        "evidence": strip_internal_scores(evidence),
        "trace": result_trace,
        "conversation_state": next_state,
        "diagnostics": diagnostics,
    }
    _attach_trace_diagnostics(
        result,
        ctx.trace_handle,
        ctx.trace_backend_name,
        ctx.trace_unavailable_reason,
        ctx.trace_error,
    )
    log_query_event(
        _LOGGER,
        "query_complete",
        query_hash=ctx.query_hash,
        status=answer["status"],
        query_type=answer["query_type"],
        latency_ms=round(latency_ms, 2),
        retry_count=ctx.retry_count,
        abstained=abstained,
        claim_count=len(answer["claims"]),
        citation_count=diagnostics["citation_count"],
        pipeline=ctx.pipeline_name,
        cold_start=ctx.cold_start,
        trace_backend=ctx.trace_backend_name,
    )
    return result


def run_rag_query(
    index: dict[str, Any],
    query: str,
    top_k: int | None = None,
    context_entities: list[str] | None = None,
    metadata_first: bool | None = None,
    rerank: bool | None = None,
    verifier_retry: bool | None = None,
    retrieval_mode: str | None = None,
    retrieval_backend: str | None = None,
    pipeline: str | None = None,
    prompt_profile: str | None = None,
    conversation_state: dict[str, Any] | None = None,
    comparison_balance: dict[str, Any] | None = None,
    rrf_k: int | None = None,
    bm25_stopword_profile: str | None = None,
    *,
    params: QueryParams | None = None,
    _skip_graph: bool = False,
) -> dict[str, Any]:
    # ADR 0022 — opt-in LangGraph orchestrator dispatch.
    # ``BIDMATE_ORCHESTRATOR=langgraph`` (default ``direct``) routes
    # through :func:`rag_graph_agentic_full.run_via_langgraph` which
    # builds the run context once and threads it through three nodes
    # (analyze / retrieve_loop / build_answer) — stage 2 of the
    # ADR-0022 migration. Each node calls the same ``_phase_*`` helper
    # the direct path runs, so JSON-identity vs the direct path holds
    # by construction (regression pinned by
    # ``tests/test_langgraph_orchestrator_regression.py``).
    # The ``_skip_graph`` kwarg forces the direct path even with the
    # env var set — kept as a private override for callers that need
    # deterministic dispatch independent of the environment. The
    # ``naive_baseline`` preset stays on the direct path (ADR 0001)
    # regardless of the env var.
    if (
        not _skip_graph
        and os.environ.get("BIDMATE_ORCHESTRATOR", "direct").strip().lower() == "langgraph"
        and (pipeline is None or pipeline != "naive_baseline")
        and (params is None or params.pipeline != "naive_baseline")
    ):
        from rag_graph_agentic_full import run_via_langgraph

        return run_via_langgraph(
            index,
            query,
            top_k=top_k,
            context_entities=context_entities,
            metadata_first=metadata_first,
            rerank=rerank,
            verifier_retry=verifier_retry,
            retrieval_mode=retrieval_mode,
            retrieval_backend=retrieval_backend,
            pipeline=pipeline,
            prompt_profile=prompt_profile,
            conversation_state=conversation_state,
            comparison_balance=comparison_balance,
            rrf_k=rrf_k,
            bm25_stopword_profile=bm25_stopword_profile,
            params=params,
        )

    ctx = _build_run_context(
        index,
        query,
        top_k=top_k,
        context_entities=context_entities,
        metadata_first=metadata_first,
        rerank=rerank,
        verifier_retry=verifier_retry,
        retrieval_mode=retrieval_mode,
        retrieval_backend=retrieval_backend,
        pipeline=pipeline,
        prompt_profile=prompt_profile,
        conversation_state=conversation_state,
        comparison_balance=comparison_balance,
        rrf_k=rrf_k,
        bm25_stopword_profile=bm25_stopword_profile,
        params=params,
    )

    early_result = _phase_analyze(ctx)
    if early_result is not None:
        return early_result

    _phase_retrieve_loop(ctx)
    return _phase_build_answer(ctx)


async def arun_rag_query(
    index: dict[str, Any],
    query: str,
    top_k: int | None = None,
    context_entities: list[str] | None = None,
    metadata_first: bool | None = None,
    rerank: bool | None = None,
    verifier_retry: bool | None = None,
    retrieval_mode: str | None = None,
    retrieval_backend: str | None = None,
    pipeline: str | None = None,
    prompt_profile: str | None = None,
    conversation_state: dict[str, Any] | None = None,
    comparison_balance: dict[str, Any] | None = None,
    rrf_k: int | None = None,
    bm25_stopword_profile: str | None = None,
) -> dict[str, Any]:
    """Async-aware entry point for the RAG pipeline (#173 Stage 1).

    Stage 1 (this PR): thin async wrapper that runs
    :func:`run_rag_query` on a worker thread via
    :func:`asyncio.to_thread` so async callers (FastAPI, future
    Streamlit-async hooks) do not block the event loop. The sync
    body and its output are byte-identical to ``run_rag_query`` —
    no behavior change.

    Stage 2 (deferred): fan-out the comparison-query per-target
    retrieval branches with :func:`asyncio.gather`. The async
    surface introduced here is the seam Stage 2 needs.
    """
    import asyncio

    return await asyncio.to_thread(
        run_rag_query,
        index,
        query,
        top_k=top_k,
        context_entities=context_entities,
        metadata_first=metadata_first,
        rerank=rerank,
        verifier_retry=verifier_retry,
        retrieval_mode=retrieval_mode,
        retrieval_backend=retrieval_backend,
        pipeline=pipeline,
        prompt_profile=prompt_profile,
        conversation_state=conversation_state,
        comparison_balance=comparison_balance,
        rrf_k=rrf_k,
        bm25_stopword_profile=bm25_stopword_profile,
    )


def strip_internal_scores(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stripped = []
    for item in evidence:
        public_item = {
            "doc_id": item["doc_id"],
            "chunk_id": item["chunk_id"],
            "title": item["title"],
            "text": item["text"],
            "score": item["score"],
            "agency": item.get("agency", ""),
            "metadata": item.get("metadata", {}),
            "section": item.get("section", ""),
            "section_id": item.get("section_id"),
            "parent_section_id": item.get("parent_section_id"),
            "section_path": item.get("section_path") or [],
            "chunk_seq_in_section": item.get("chunk_seq_in_section"),
            "total_chunks_in_section": item.get("total_chunks_in_section"),
            "chunking_strategy": item.get("chunking_strategy", ""),
            "retrieval_mode": item.get("retrieval_mode", "flat"),
            "child_chunk_ids": item.get("child_chunk_ids", []),
        }
        regions = normalize_regions(item.get("regions"))
        page_span = normalize_page_span(item.get("page_span"), regions)
        if regions:
            public_item["regions"] = regions
        if page_span:
            public_item["page_span"] = page_span
        stripped.append(public_item)
    return stripped


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def rate(scores: list[float]) -> float | None:
    if not scores:
        return None
    return sum(scores) / len(scores)
