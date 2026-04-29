#!/usr/bin/env python3
"""Shared local RAG primitives for the public BidMate sample.

The implementation keeps the public demo deterministic: retrieval is local,
generation is extractive, and external LLM/API calls are not required.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any, Iterable

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
    "비교",
    "기관",
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


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: np.ndarray
    backend: str
    model: str


def normalize_entity(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def tokenize(text: str) -> list[str]:
    tokens = [m.group(0).lower() for m in TOKEN_RE.finditer(text)]
    return [t for t in tokens if t and t not in STOPWORDS]


def sentence_split(text: str) -> list[str]:
    parts = SENTENCE_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


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
            sentences = sentence_split(section["text"]) or [section["text"]]
            current: list[str] = []
            current_len = 0
            for sentence in sentences:
                next_len = current_len + len(sentence) + 1
                if current and next_len > max_chars:
                    chunks.append(make_chunk(doc, section["heading"], current, chunk_seq))
                    chunk_seq += 1
                    current = current[-1:]
                    current_len = sum(len(s) + 1 for s in current)
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
        "message": "Public synthetic RFP index for local minimum E2E RAG.",
        "embedding": {
            "backend": embedding_result.backend,
            "model": embedding_result.model,
            "dimension": int(embedding_result.vectors.shape[1]),
            "normalized": True,
        },
        "build": {
            "num_documents": len(public_docs),
            "num_chunks": len(chunks),
            "source_dir": str(input_dir),
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


def analyze_query(
    query: str,
    entities: list[str],
    context_entities: list[str] | None = None,
) -> dict[str, Any]:
    normalized_query = normalize_entity(query)
    query_no_space = re.sub(r"\s+", "", normalized_query.lower())
    found_entities: list[str] = []
    for entity in entities:
        entity_no_space = re.sub(r"\s+", "", entity.lower())
        if entity_no_space and entity_no_space in query_no_space:
            found_entities.append(entity)

    for match in ENTITY_RE.findall(normalized_query):
        candidate = normalize_entity(match)
        for entity in entities:
            if re.sub(r"\s+", "", entity.lower()) == re.sub(r"\s+", "", candidate.lower()):
                if entity not in found_entities:
                    found_entities.append(entity)

    context_used = False
    if not found_entities and context_entities:
        for entity in context_entities:
            if entity in entities and entity not in found_entities:
                found_entities.append(entity)
                context_used = True

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

    comparison_terms = ("차이", "비교", "공통", "각각", "대비")
    if len(found_entities) > 1 or any(term in normalized_query for term in comparison_terms):
        query_type = "comparison"
    elif context_used:
        query_type = "follow_up"
    else:
        query_type = "single_doc"

    return {
        "query_type": query_type,
        "entities": found_entities,
        "topics": topics[:8],
        "context_entities": context_entities or [],
        "context_used": context_used,
        "tokens": tokenize(normalized_query),
    }


def make_plan(analysis: dict[str, Any], relaxed: bool = False, top_k: int | None = None) -> dict[str, Any]:
    default_top_k = 6 if analysis["query_type"] == "comparison" else 4
    filters = {} if relaxed else {"agencies": analysis.get("entities", [])}
    return {
        "strategy": "metadata-first dense retrieval with lexical reranking",
        "metadata_filters": filters,
        "top_k": top_k or default_top_k,
        "relaxed": relaxed,
        "retry_policy": "relax metadata filters and widen top-k when verifier rejects evidence",
    }


def retrieve(
    index: dict[str, Any],
    query: str,
    analysis: dict[str, Any],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    chunks = index["chunks"]
    filters = plan.get("metadata_filters") or {}
    agencies = set(filters.get("agencies") or [])
    candidates = [c for c in chunks if not agencies or c.get("agency") in agencies]
    if not candidates:
        candidates = chunks

    embedding_config = index.get("embedding", {})
    query_embedding = embed_query_for_index(query, embedding_config)
    query_tokens = set(analysis.get("tokens", []))
    query_topics = analysis.get("topics", [])
    scored = []
    for chunk in candidates:
        dense_score = dense_similarity(query_embedding, chunk.get("embedding"))
        lexical_score = lexical_similarity(query_tokens, query_topics, chunk)
        metadata_score = metadata_similarity(analysis, chunk)
        score = (0.60 * dense_score) + (0.25 * lexical_score) + (0.15 * metadata_score)
        scored.append(
            {
                "doc_id": chunk["doc_id"],
                "chunk_id": chunk["chunk_id"],
                "title": chunk["title"],
                "agency": chunk.get("agency", ""),
                "project": chunk.get("project", ""),
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

    combined = " ".join(item["text"] for item in evidence).lower()
    topics = [topic for topic in analysis.get("topics", []) if topic.lower() not in {"ai"}]
    if topics and not any(topic.lower() in combined for topic in topics):
        reasons.append("topic_not_grounded")

    entities = analysis.get("entities") or []
    if analysis.get("query_type") == "comparison" and len(entities) > 1:
        covered = {item.get("agency") for item in evidence}
        missing = [entity for entity in entities if entity not in covered]
        if missing:
            reasons.append("missing_comparison_entity:" + ",".join(missing))

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
    pool = topic_matched or evidence

    if analysis.get("query_type") == "comparison" and len(analysis.get("entities", [])) > 1:
        selected = []
        for entity in analysis["entities"]:
            match = next((item for item in pool if item.get("agency") == entity), None)
            if match:
                selected.append(match)
        return selected or pool[:2]

    return pool[:2]


def run_rag_query(
    index: dict[str, Any],
    query: str,
    top_k: int | None = None,
    context_entities: list[str] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    analysis = analyze_query(query, known_entities(index), context_entities=context_entities)
    plan = make_plan(analysis, top_k=top_k)
    evidence = retrieve(index, query, analysis, plan)
    verified, verification_reasons = verify_evidence(analysis, evidence)
    retry_count = 0

    if not verified:
        retry_count = 1
        plan = make_plan(analysis, relaxed=True, top_k=max(top_k or 0, 8))
        evidence = retrieve(index, query, analysis, plan)
        verified, verification_reasons = verify_evidence(analysis, evidence)

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
            "embedding_backend": index.get("embedding", {}).get("backend"),
            "embedding_model": index.get("embedding", {}).get("model"),
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
