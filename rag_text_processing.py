"""Text-processing primitives shared across the rag_* module family.

Extracted from ``rag_core.py`` (issue #545) as the first step of breaking
the late-import cycle: rag_answer, rag_query, rag_verifier, and rag_retrieval
all needed to late-import these utilities from rag_core to avoid a circular
dependency.  Moving them here gives them a home that none of the rag_* modules
depend on (this module imports only korean_lexicon and stdlib), so they can
be imported at module level everywhere.

``rag_core`` re-exports every public name for backward compatibility.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

from korean_lexicon import KOREAN_PARTICLE_SUFFIXES, STOPWORDS

QUERY_TYPE_TOP_K_DEFAULTS: dict[str, int] = {
    "single_doc": 4,
    "follow_up": 6,
    "comparison": 6,
}

TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]+")
ENTITY_RE = re.compile(r"기관\s*[-_]?\s*([A-Za-z0-9]+)", re.IGNORECASE)
SENTENCE_RE = re.compile(r"(?<=[.!?。])\s+")


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
