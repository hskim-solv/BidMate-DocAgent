"""Metadata processing: targets, matching, regions, sections, and scoring.

Extracted from ``rag_core.py`` (issue #557) as the second step of the
rag_core decomposition. Owns the metadata surface that sits between the
text-processing primitives (rag_text_processing) and the retrieval /
answer / query layers:

Public functions and constants:

- :data:`WEAK_SECTION_HEADINGS` / :data:`STRICT_METADATA_CONFIDENCE` /
  :data:`REDUCED_METADATA_CONFIDENCE` — policy constants consumed by the
  matching and section-structure helpers.
- :func:`metadata_tokens` — tokenise + normalise a metadata value string.
- :func:`normalize_regions` / :func:`normalize_page_span` — citation
  geometry normalisation (used by ingestion, rag_answer, rag_retrieval).
- :func:`normalize_document_sections` / :func:`document_has_section_structure` /
  :func:`fixed_parent_section` / :func:`split_section_text` — section-level
  document structure helpers (ingestion + chunking path).
- :func:`make_metadata_target` / :func:`metadata_explicit_aliases` /
  :func:`metadata_aliases` — target-object constructors consumed by the
  matching pipeline.
- :func:`coerce_metadata_targets` / :func:`match_metadata_targets` /
  :func:`match_metadata_target` / :func:`best_metadata_phrase_similarity` —
  metadata entity matching.
- :func:`make_metadata_match` / :func:`dedupe_metadata_matches` /
  :func:`metadata_matches_for_stage` / :func:`metadata_filters_from_matches` /
  :func:`best_metadata_doc_scores` / :func:`metadata_ambiguity_details` —
  match result post-processing.

Circular-import avoidance: all dependencies are leaves —
``rag_text_processing`` (stdlib + korean_lexicon) and
``rag_conversation_state`` (stdlib only). ``rag_core`` re-exports every
public name so existing callers keep their ``from rag_core import ...``
imports unchanged.

JSON-identity guarantee: every function moves byte-for-byte from
``rag_core``. The metadata-touching regression gates remain green.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

from korean_lexicon import METADATA_GENERIC_TOKENS, STOPWORDS
from rag_conversation_state import AMBIGUOUS_CONFIDENCE_DELTA
from rag_text_processing import (
    TOKEN_RE,
    coerce_alias_values,
    compact_metadata_text,
    normalize_metadata_token,
    normalize_section_path,
    ordered_unique,
    sentence_split,
    split_long_text_unit,
)

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

STRICT_METADATA_CONFIDENCE = 0.90
REDUCED_METADATA_CONFIDENCE = 0.70


def metadata_tokens(text: str) -> list[str]:
    tokens = []
    for match in TOKEN_RE.finditer(unicodedata.normalize("NFC", text)):
        token = normalize_metadata_token(match.group(0))
        if token and token not in STOPWORDS:
            tokens.append(token)
    return tokens


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
