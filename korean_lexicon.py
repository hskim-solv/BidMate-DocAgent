"""Korean linguistic + RFP-domain lexicon for BidMate-DocAgent.

Externalized from rag_core.py in issue #344 (PR-D). The YAML payload at
``data/lexicon/ko_default.yaml`` is the single source of truth for the
~155 Korean / RFP-domain tokens previously hard-coded as Python set,
tuple, frozenset, and dict literals; this module reconstructs the
original Python container types so existing call sites — including the
re-exports from ``rag_core`` and the direct imports in
``tests/test_hybrid_retrieval_regression.py`` — are bit-for-bit
unchanged.

Future overlay support (e.g. ``medical_rfp.yaml``) lands as a follow-up
on top of this loader, not here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_YAML_PATH = Path(__file__).resolve().parent / "data" / "lexicon" / "ko_default.yaml"


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    with _YAML_PATH.open(encoding="utf-8") as fp:
        return yaml.safe_load(fp)


_data = _load()

STOPWORDS: set[str] = set(_data["stopwords"])
TOPIC_KEYWORDS: list[str] = list(_data["topic_keywords"])
IMPLICIT_REFERENCE_PATTERNS: tuple[str, ...] = tuple(_data["implicit_reference_patterns"])
METADATA_GENERIC_TOKENS: set[str] = set(_data["metadata_generic_tokens"])
VERIFICATION_INTENT_TOKENS: set[str] = set(_data["verification_intent_tokens"])
METADATA_EVIDENCE_LABELS: dict[str, tuple[str, ...]] = {
    key: tuple(values) for key, values in _data["metadata_evidence_labels"].items()
}
METADATA_CLAIM_LABELS: dict[str, str] = dict(_data["metadata_claim_labels"])
METADATA_CLAIM_TOPIC_LABELS: dict[str, tuple[str, ...]] = {
    key: tuple(values) for key, values in _data["metadata_claim_topic_labels"].items()
}
KOREAN_PARTICLE_SUFFIXES: tuple[str, ...] = tuple(_data["korean_particle_suffixes"])
BM25_EXTRA_PARTICLE_SUFFIXES: tuple[str, ...] = tuple(_data["bm25_extra_particle_suffixes"])
BM25_EXTRA_STOPWORDS: frozenset[str] = frozenset(_data["bm25_extra_stopwords"])
