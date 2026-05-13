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


# KIWI morphological tokenizer (issue #486, ADR 0030) — additive
# Korean-morphology-aware BM25 path. Lazy-imported so the
# ``kiwipiepy`` dependency stays optional: a missing wheel (or import
# error on an unusual platform) silently falls back to the regex
# tokenizer at every call site below. POS filter retains
# 체언 (NNG / NNP / NP / NR), 용언 (VV / VA / VX / VCP / VCN),
# 수식어 (MM / MAG / MAJ), and 외래어 / 한자 / 숫자 (SL / SH / SN)
# — drops 조사 (J*), 어미 (E*), and punctuation (S* except SL/SH/SN)
# which carry no retrieval signal.
_KIWI_POS_KEEP: frozenset[str] = frozenset(
    {
        # 체언
        "NNG",
        "NNP",
        "NP",
        "NR",
        # 용언
        "VV",
        "VA",
        "VX",
        "VCP",
        "VCN",
        # 수식어
        "MM",
        "MAG",
        "MAJ",
        # 외래어 / 한자 / 숫자
        "SL",
        "SH",
        "SN",
    }
)


@lru_cache(maxsize=1)
def _kiwi_instance() -> Any | None:
    """Return a singleton ``Kiwi`` analyzer or ``None`` if unavailable.

    Cached so the (~30 MB) model isn't reloaded per call. ``None``
    return signals callers to fall back to the regex tokenizer — the
    never-raise contract for ADR 0001 invariant preservation.
    """
    try:
        from kiwipiepy import Kiwi  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        return Kiwi()
    except Exception:  # noqa: BLE001 — bootstrap can fail for many reasons
        return None


def kiwi_tokens(text: str) -> list[str] | None:
    """Morpheme-tokenize ``text`` and return BM25-worthy base forms.

    Returns a list of token strings filtered by :data:`_KIWI_POS_KEEP`
    (체언 / 용언 / 수식어 / 외래어 / 한자 / 숫자). Returns ``None`` if
    ``kiwipiepy`` is not installed or fails to initialize — callers
    then fall back to the existing regex tokenizer (issue #486 contract).
    Returns ``[]`` for empty input.
    """
    if not text:
        return []
    kiwi = _kiwi_instance()
    if kiwi is None:
        return None
    try:
        analyzed = kiwi.tokenize(text)
    except Exception:  # noqa: BLE001 — defensive against malformed inputs
        return None
    tokens: list[str] = []
    for token in analyzed:
        if token.tag in _KIWI_POS_KEEP:
            form = (token.form or "").strip()
            if form:
                tokens.append(form)
    return tokens
