#!/usr/bin/env python3
"""Shared local RAG primitives for the public BidMate sample.

The implementation keeps the public demo deterministic: retrieval is local,
generation is extractive, and external LLM/API calls are not required.
"""

from __future__ import annotations

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

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_HASH_DIM = 384
INDEX_FILENAME = "index.json"
MODEL_CACHE: dict[tuple[str, bool], Any] = {}

TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]+")
ENTITY_RE = re.compile(r"기관\s*[A-Za-z0-9가-힣]+")
SENTENCE_RE = re.compile(r"(?<=[.!?。])\s+")

STOPWORDS = {
    "그럼",
    "그리고",
    "어떻게",
    "알려줘",
    "차이",
    "차이는",
    "차이를",
    "비교",
    "비교해줘",
    "기관",
    "요구",
    "요구가",
    "요구사항",
    "기능",
    "목표",
    "성능",
    "초점",
    "필수",
    "그중",
    "어떤",
    "누가",
    "포함돼야",
    "해",
    "있나",
    "무엇을",
    "사용해",
    "진행해",
    "중심으로",
    "시간",
    "지표나",
    "하는",
    "것은",
    "의",
    "와",
    "과",
    "는",
    "은",
    "를",
    "을",
    "이",
    "가",
    "에",
    "내",
    "돼",
    "무엇",
    "뭐야",
    "대한",
    "있는",
    "없는",
    "되나요",
    "습니까",
    "인가요",
}

TOPIC_KEYWORDS = [
    "AI",
    "품질관리",
    "품질",
    "보안",
    "보안 통제",
    "통제",
    "로그",
    "데이터",
    "거버넌스",
    "MLOps",
    "자동화",
    "모니터링",
    "일정",
    "산출물",
    "제출조건",
    "예산",
    "챗봇",
    "응답",
    "상담",
    "블록체인",
    "납품",
    "실적",
]

STRICT_METADATA_CONFIDENCE = 0.90
REDUCED_METADATA_CONFIDENCE = 0.70
AMBIGUOUS_CONFIDENCE_DELTA = 0.05

METADATA_GENERIC_TOKENS = {
    "rfp",
    "사업",
    "용역",
    "구축",
    "고도화",
    "개발",
    "운영",
    "정보",
    "시스템",
}

KOREAN_PARTICLE_SUFFIXES = (
    "으로",
    "에서",
    "에게",
    "과",
    "와",
    "의",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "로",
    "에",
)


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: np.ndarray
    backend: str
    model: str


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
            normalized_sections.append({"heading": heading, "text": text})
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


def build_chunks(documents: Iterable[dict[str, Any]], max_chars: int = 520) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for doc in documents:
        chunk_seq = 1
        for section in doc["sections"]:
            sentences = []
            for sentence in sentence_split(section["text"]) or [section["text"]]:
                sentences.extend(split_long_text_unit(sentence, max_chars))
            current: list[str] = []
            current_len = 0
            for sentence in sentences:
                next_len = current_len + len(sentence) + 1
                if current and next_len > max_chars:
                    chunks.append(make_chunk(doc, section["heading"], current, chunk_seq))
                    chunk_seq += 1
                    overlap = current[-1:]
                    overlap_len = sum(len(s) + 1 for s in overlap)
                    if overlap_len + len(sentence) + 1 <= max_chars:
                        current = overlap
                        current_len = overlap_len
                    else:
                        current = []
                        current_len = 0
                current.append(sentence)
                current_len += len(sentence) + 1
            if current:
                chunks.append(make_chunk(doc, section["heading"], current, chunk_seq))
                chunk_seq += 1
    return chunks


def make_chunk(
    doc: dict[str, Any],
    section: str,
    sentences: list[str],
    chunk_seq: int,
) -> dict[str, Any]:
    text = " ".join(sentences).strip()
    return {
        "chunk_id": f"{doc['doc_id']}::chunk-{chunk_seq:03d}",
        "doc_id": doc["doc_id"],
        "title": doc["title"],
        "agency": doc.get("agency", ""),
        "project": doc.get("project", ""),
        "metadata": doc.get("metadata", {}),
        "section": section,
        "text": text,
        "tokens": tokenize(" ".join([doc["title"], doc.get("agency", ""), section, text])),
    }


def embed_texts(
    texts: list[str],
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    backend: str = "auto",
    local_only: bool = False,
) -> EmbeddingResult:
    if backend not in {"auto", "sentence-transformers", "hashing"}:
        raise ValueError("--embedding_backend must be one of: auto, sentence-transformers, hashing")

    should_try_sentence_transformers = backend == "sentence-transformers" or (
        backend == "auto" and sentence_transformer_cache_available(model_name)
    )

    if should_try_sentence_transformers:
        try:
            with huggingface_offline(local_only or backend == "auto"):
                from sentence_transformers import SentenceTransformer

                cache_key = (model_name, local_only or backend == "auto")
                model = MODEL_CACHE.get(cache_key)
                if model is None:
                    model = SentenceTransformer(model_name)
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
) -> dict[str, Any]:
    documents = load_raw_documents(input_dir)
    return build_index_payload_from_documents(
        documents,
        source_dir=str(input_dir),
        model_name=model_name,
        embedding_backend=embedding_backend,
        message="Public synthetic RFP index for local minimum E2E RAG.",
    )


def build_index_payload_from_documents(
    documents: list[dict[str, Any]],
    source_dir: str,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    embedding_backend: str = "auto",
    message: str = "RFP index for local minimum E2E RAG.",
) -> dict[str, Any]:
    chunks = build_chunks(documents)
    embedding_inputs = [
        " ".join([chunk["title"], chunk.get("agency", ""), chunk["section"], chunk["text"]])
        for chunk in chunks
    ]
    embedding_result = embed_texts(embedding_inputs, model_name=model_name, backend=embedding_backend)
    for chunk, vector in zip(chunks, embedding_result.vectors.tolist()):
        chunk["embedding"] = vector

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
        "schema_version": 1,
        "mode": "rag",
        "message": message,
        "embedding": {
            "backend": embedding_result.backend,
            "model": embedding_result.model,
            "dimension": int(embedding_result.vectors.shape[1]),
            "normalized": True,
        },
        "build": {
            "num_documents": len(public_docs),
            "num_chunks": len(chunks),
            "source_dir": source_dir,
        },
        "documents": public_docs,
        "chunks": chunks,
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
    return payload


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
    return {
        "doc_id": str(doc.get("doc_id") or ""),
        "agency": str(doc.get("agency") or ""),
        "project": str(doc.get("project") or ""),
        "field": field,
        "value": value,
        "compact": compact_metadata_text(value),
        "tokens": tokens,
        "core_tokens": core_tokens,
        "aliases": metadata_aliases(field, value, tokens),
    }


def metadata_aliases(field: str, value: str, tokens: list[str]) -> list[str]:
    aliases = []
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

    alias_hits = [alias for alias in target.get("aliases", []) if alias in query_token_set]
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


def is_metadata_ambiguous(matches: list[dict[str, Any]], query_type: str) -> bool:
    if query_type == "comparison":
        return False
    reduced_matches = metadata_matches_for_stage(matches, "reduced")
    if not reduced_matches:
        return False
    scores = best_metadata_doc_scores(reduced_matches)
    if len(scores) <= 1:
        return False
    top_score = max(scores.values())
    close_doc_ids = [
        doc_id for doc_id, score in scores.items() if score >= top_score - AMBIGUOUS_CONFIDENCE_DELTA
    ]
    return len(close_doc_ids) > 1


def analyze_query(
    query: str,
    entities: list[Any],
    context_entities: list[str] | None = None,
) -> dict[str, Any]:
    targets = coerce_metadata_targets(entities)
    normalized_query = normalize_entity(query)
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

    comparison_terms = ("차이", "비교", "각각", "대비")
    comparison_joiners = ("와", "과", "및", ",", "/")
    reduced_matches = metadata_matches_for_stage(metadata_matches, "reduced")
    matched_doc_ids = ordered_unique(match["doc_id"] for match in reduced_matches)
    matched_agencies = ordered_unique(match["agency"] for match in reduced_matches)
    matched_projects = ordered_unique(match["project"] for match in reduced_matches)
    has_comparison_term = any(term in normalized_query for term in comparison_terms)
    has_multi_target_joiner = len(matched_doc_ids) > 1 and any(
        joiner in normalized_query for joiner in comparison_joiners
    )
    if has_comparison_term or has_multi_target_joiner:
        query_type = "comparison"
    elif context_used:
        query_type = "follow_up"
    else:
        query_type = "single_doc"

    strict_matches = metadata_matches_for_stage(metadata_matches, "strict")
    strict_filters = metadata_filters_from_matches(strict_matches)
    reduced_filters = metadata_filters_from_matches(reduced_matches)

    return {
        "query_type": query_type,
        "entities": matched_agencies,
        "topics": topics[:8],
        "context_entities": context_entities or [],
        "context_used": context_used,
        "tokens": tokenize(normalized_query),
        "metadata_matches": metadata_matches,
        "matched_doc_ids": matched_doc_ids,
        "matched_agencies": matched_agencies,
        "matched_projects": matched_projects,
        "metadata_confidence": round(max((m["confidence"] for m in metadata_matches), default=0.0), 3),
        "metadata_ambiguous": is_metadata_ambiguous(metadata_matches, query_type),
        "metadata_filters_by_stage": {
            "strict": strict_filters,
            "reduced": reduced_filters,
            "relaxed": {},
        },
        "metadata_doc_scores": best_metadata_doc_scores(reduced_matches),
    }


def make_plan(
    analysis: dict[str, Any],
    relaxed: bool = False,
    top_k: int | None = None,
    stage: str | None = None,
    metadata_first: bool = True,
    rerank: bool = True,
    verifier_retry: bool = True,
) -> dict[str, Any]:
    default_top_k = 6 if analysis["query_type"] == "comparison" else 4
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
    return {
        "strategy": scoring if not metadata_first else f"metadata-first {scoring}",
        "filter_stage": stage,
        "metadata_first": metadata_first,
        "rerank": rerank,
        "verifier_retry": verifier_retry,
        "metadata_filters": filters,
        "top_k": top_k or default_top_k,
        "relaxed": stage == "relaxed",
        "retry_policy": "try strict metadata filters, then reduced fuzzy filters, then relaxed retrieval",
    }


def retrieve(
    index: dict[str, Any],
    query: str,
    analysis: dict[str, Any],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
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
    query_embedding = embed_query_for_index(query, embedding_config)
    query_tokens = set(analysis.get("tokens", []))
    query_topics = analysis.get("topics", [])
    scored = []
    for chunk in candidates:
        dense_score = dense_similarity(query_embedding, chunk.get("embedding"))
        lexical_score = lexical_similarity(query_tokens, query_topics, chunk)
        metadata_score = metadata_similarity(analysis, chunk)
        if not plan.get("rerank", True):
            score = dense_score
        elif not plan.get("metadata_first", True):
            score = (0.70 * dense_score) + (0.30 * lexical_score)
        else:
            score = (0.60 * dense_score) + (0.25 * lexical_score) + (0.15 * metadata_score)
        scored.append(
            {
                "doc_id": chunk["doc_id"],
                "chunk_id": chunk["chunk_id"],
                "title": chunk["title"],
                "agency": chunk.get("agency", ""),
                "project": chunk.get("project", ""),
                "metadata": chunk.get("metadata", {}),
                "section": chunk["section"],
                "text": chunk["text"],
                "score": round(float(score), 4),
                "score_parts": {
                    "dense": round(float(dense_score), 4),
                    "lexical": round(float(lexical_score), 4),
                    "metadata": round(float(metadata_score), 4),
                },
            }
        )

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[: int(plan["top_k"])]


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
    return hashing_embeddings([query], dimension)[0]


def dense_similarity(query_vector: np.ndarray, chunk_vector: Any) -> float:
    if chunk_vector is None:
        return 0.0
    doc_vector = np.asarray(chunk_vector, dtype=np.float32)
    if doc_vector.shape != query_vector.shape:
        return 0.0
    score = float(np.dot(query_vector, doc_vector))
    return max(0.0, min(1.0, (score + 1.0) / 2.0))


def lexical_similarity(query_tokens: set[str], topics: list[str], chunk: dict[str, Any]) -> float:
    if not query_tokens and not topics:
        return 0.0
    chunk_text = " ".join(
        [
            chunk.get("title", ""),
            chunk.get("agency", ""),
            chunk.get("project", ""),
            chunk.get("section", ""),
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


def verify_evidence(analysis: dict[str, Any], evidence: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    reasons = []
    if not evidence:
        return False, ["no_evidence"]
    if evidence[0]["score"] < 0.18:
        reasons.append("low_top_score")

    combined = " ".join(
        " ".join([item.get("title", ""), item.get("section", ""), item["text"]])
        for item in evidence
    ).lower()
    topics = [topic for topic in analysis.get("topics", []) if topic.lower() not in {"ai"}]
    if topics and not all(topic.lower() in combined for topic in topics):
        reasons.append("topic_not_grounded")

    entities = analysis.get("entities") or []
    if analysis.get("query_type") == "comparison" and len(entities) > 1:
        covered = {item.get("agency") for item in evidence}
        missing = [entity for entity in entities if entity not in covered]
        if missing:
            reasons.append("missing_comparison_entity:" + ",".join(missing))

    matched_doc_ids = analysis.get("matched_doc_ids") or []
    if analysis.get("query_type") == "comparison" and len(matched_doc_ids) > 1:
        covered_doc_ids = {item.get("doc_id") for item in evidence}
        missing_doc_ids = [doc_id for doc_id in matched_doc_ids if doc_id not in covered_doc_ids]
        if missing_doc_ids:
            reasons.append("missing_comparison_doc:" + ",".join(missing_doc_ids))

    return not reasons, reasons


def generate_answer(
    query: str,
    analysis: dict[str, Any],
    evidence: list[dict[str, Any]],
    verified: bool,
) -> tuple[str, bool]:
    if not verified:
        return (
            f"제공된 공개 샘플 RFP 근거에서는 '{query}'에 답할 수 있는 내용을 찾지 못했습니다.",
            True,
        )

    if analysis.get("query_type") == "comparison" and len(analysis.get("entities", [])) > 1:
        parts = []
        for entity in analysis["entities"]:
            entity_evidence = [item for item in evidence if item.get("agency") == entity]
            if not entity_evidence:
                continue
            best = best_sentence(entity_evidence[0]["text"], analysis.get("topics", []), analysis["tokens"])
            parts.append(f"{entity}: {best} [{entity_evidence[0]['chunk_id']}]")
        if parts:
            return " ".join(parts), False

    selected = []
    seen = set()
    for item in evidence:
        sentence = best_sentence(item["text"], analysis.get("topics", []), analysis.get("tokens", []))
        key = (item["chunk_id"], sentence)
        if key in seen:
            continue
        seen.add(key)
        selected.append(f"{sentence} [{item['chunk_id']}]")
        if len(selected) >= 2:
            break
    return " ".join(selected), False


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


def select_supporting_evidence(
    analysis: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    topics = [topic.lower() for topic in analysis.get("topics", [])]
    topic_matched = [
        item
        for item in evidence
        if not topics or any(topic in item["text"].lower() for topic in topics)
    ]

    if analysis.get("query_type") == "comparison" and len(analysis.get("entities", [])) > 1:
        selected = []
        for entity in analysis["entities"]:
            match = next((item for item in topic_matched if item.get("agency") == entity), None)
            if not match:
                match = next((item for item in evidence if item.get("agency") == entity), None)
            if match:
                selected.append(match)
        return selected or (topic_matched or evidence)[:2]

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
        stages.append("strict")
    if verifier_retry:
        stages.append("relaxed")
    return stages


def summarize_stage_attempt(
    plan: dict[str, Any],
    verified: bool,
    verification_reasons: list[str],
) -> dict[str, Any]:
    return {
        "stage": plan.get("filter_stage"),
        "metadata_filters": plan.get("metadata_filters") or {},
        "top_k": plan.get("top_k"),
        "candidate_count": plan.get("candidate_count"),
        "total_chunks": plan.get("total_chunks"),
        "filter_fallback_used": plan.get("filter_fallback_used", False),
        "verified": verified,
        "verification_reasons": verification_reasons,
    }


def run_rag_query(
    index: dict[str, Any],
    query: str,
    top_k: int | None = None,
    context_entities: list[str] | None = None,
    metadata_first: bool = True,
    rerank: bool = True,
    verifier_retry: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    analysis = analyze_query(query, metadata_targets(index), context_entities=context_entities)
    stage_sequence = metadata_stage_sequence(
        analysis,
        metadata_first=metadata_first,
        verifier_retry=verifier_retry,
    )
    stage_attempts = []
    retry_count = 0
    plan: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []
    verified = False
    verification_reasons: list[str] = []

    for attempt_index, stage in enumerate(stage_sequence):
        attempt_top_k = top_k
        if attempt_index > 0:
            attempt_top_k = max(top_k or 0, 8)
        plan = make_plan(
            analysis,
            top_k=attempt_top_k,
            stage=stage,
            metadata_first=metadata_first,
            rerank=rerank,
            verifier_retry=verifier_retry,
        )
        evidence = retrieve(index, query, analysis, plan)
        if verifier_retry:
            verified, verification_reasons = verify_evidence(analysis, evidence)
        else:
            verified = bool(evidence)
            verification_reasons = [] if verified else ["no_evidence"]
        stage_attempts.append(summarize_stage_attempt(plan, verified, verification_reasons))
        if verified:
            break
        if attempt_index < len(stage_sequence) - 1:
            retry_count += 1

    if not verified:
        evidence = []
    else:
        evidence = select_supporting_evidence(analysis, evidence)
    answer, abstained = generate_answer(query, analysis, evidence, verified)
    latency_ms = (time.perf_counter() - started) * 1000
    return {
        "mode": "rag",
        "query": query,
        "analysis": analysis,
        "plan": plan,
        "answer": answer,
        "evidence": strip_internal_scores(evidence),
        "diagnostics": {
            "latency_ms": round(latency_ms, 2),
            "retry_count": retry_count,
            "abstained": abstained,
            "verification_reasons": verification_reasons,
            "filter_stage_attempts": stage_attempts,
            "final_relaxation_reason": stage_attempts[-2]["verification_reasons"] if retry_count else [],
            "embedding_backend": index.get("embedding", {}).get("backend"),
            "embedding_model": index.get("embedding", {}).get("model"),
            "metadata_first": metadata_first,
            "rerank": rerank,
            "verifier_retry": verifier_retry,
        },
    }


def strip_internal_scores(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "doc_id": item["doc_id"],
            "chunk_id": item["chunk_id"],
            "title": item["title"],
            "text": item["text"],
            "score": item["score"],
            "agency": item.get("agency", ""),
            "metadata": item.get("metadata", {}),
            "section": item.get("section", ""),
        }
        for item in evidence
    ]


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
