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


# KIWI morphological tokenizer (issue #486, ADR 0031) — additive
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


# ---------------------------------------------------------------------------
# Mecab-ko tokenizer (issue #561 / ADR 0031 valid-set expansion)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _mecab_instance() -> Any | None:
    """Return a singleton Mecab analyzer or ``None`` if unavailable.

    Tries ``python-mecab-ko`` first, then ``konlpy.tag.Mecab`` as fallback.
    ``None`` return signals callers to fall back to the regex tokenizer
    (never-raise contract, ADR 0001 invariant).
    """
    try:
        from mecab import MeCab  # type: ignore[import-not-found]  # python-mecab-ko
        return MeCab()
    except (ImportError, Exception):  # noqa: BLE001
        pass
    try:
        from konlpy.tag import Mecab  # type: ignore[import-not-found]
        return Mecab()
    except (ImportError, Exception):  # noqa: BLE001
        return None


def mecab_tokens(text: str) -> list[str] | None:
    """Morpheme-tokenize ``text`` using Mecab-ko, return BM25-worthy nouns/verbs.

    Returns ``None`` if Mecab is not installed — callers fall back to the
    regex tokenizer (never-raise, ADR 0001 invariant). Same contract as
    :func:`kiwi_tokens`.
    """
    if not text:
        return []
    mecab = _mecab_instance()
    if mecab is None:
        return None
    try:
        # python-mecab-ko returns list of (surface, tag) tuples via morphs/pos.
        # konlpy.tag.Mecab.pos() returns the same structure.
        pos_list = mecab.pos(text)
    except Exception:  # noqa: BLE001
        return None
    # Keep open-class morphemes: NNG/NNP (nouns), VV/VA (verbs/adjectives),
    # XR (roots), SL (foreign), SN (numbers), NR (numerals).
    keep_prefixes = ("NN", "VV", "VA", "XR", "SL", "SN", "NR")
    tokens: list[str] = []
    for surface, tag in pos_list:
        if any(tag.startswith(p) for p in keep_prefixes):
            surface = surface.strip()
            if surface:
                tokens.append(surface)
    return tokens


# ---------------------------------------------------------------------------
# Khaiii tokenizer (issue #561 / ADR 0031 valid-set expansion)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _khaiii_instance() -> Any | None:
    """Return a singleton KhaiiiApi instance or ``None`` if unavailable.

    Khaiii requires a compiled C++ shared library. ``None`` return signals
    callers to fall back to the regex tokenizer (never-raise contract).
    """
    try:
        from khaiii import KhaiiiApi  # type: ignore[import-not-found]
        api = KhaiiiApi()
        api.open()
        return api
    except (ImportError, Exception):  # noqa: BLE001
        return None


def khaiii_tokens(text: str) -> list[str] | None:
    """Morpheme-tokenize ``text`` using Khaiii, return BM25-worthy morphemes.

    Returns ``None`` if Khaiii is not installed or fails to initialize —
    callers fall back to the regex tokenizer (never-raise, ADR 0001 invariant).
    Same contract as :func:`kiwi_tokens` and :func:`mecab_tokens`.
    """
    if not text:
        return []
    api = _khaiii_instance()
    if api is None:
        return None
    try:
        words = api.analyze(text)
    except Exception:  # noqa: BLE001
        return None
    keep_prefixes = ("NN", "VV", "VA", "XR", "SL", "SN", "NR")
    tokens: list[str] = []
    for word in words:
        for morpheme in word.morphs:
            tag = getattr(morpheme, "tag", "") or ""
            surface = (getattr(morpheme, "lex", "") or "").strip()
            if surface and any(tag.startswith(p) for p in keep_prefixes):
                tokens.append(surface)
    return tokens
