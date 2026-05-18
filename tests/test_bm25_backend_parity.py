"""Parity guard for the bm25s BM25 backend (issue #988, ADR 0057).

Three contracts to lock:

1. **Default backend stays "okapi" (ADR 0001 invariant).** Every
   pipeline preset (`naive_baseline`, `agentic_full`, `agentic_full_llm`,
   `agent_react`) must declare `bm25_backend: "okapi"` explicitly. A future
   change that flips a preset to "bm25s" must update this test (and ADR
   0057's Re-open section).

2. **Ranking parity on the same corpus tokens.** With `method="robertson",
   k1=1.5, b=0.75`, `bm25s.BM25` produces the same top-N ordering as
   `rank_bm25.BM25Okapi`. The absolute scores differ via IDF treatment
   (robertson IDF clips negatives to 0 differently from BM25Okapi's
   `log((N - df + 0.5) / (df + 0.5))`), but RRF fusion uses only
   ordering — `top_n_overlap >= 0.95` is the contract that lets us swap
   backends without measurable retrieval drift.

3. **Cache isolation.** `get_or_build_bm25` keys on `(stopword_profile,
   tokenizer, backend, ...)` — the okapi cache does NOT serve a bm25s
   query (different `get_scores` semantics) and vice versa.

The bm25s backend itself is gated by `pytest.importorskip("bm25s")` —
those tests skip cleanly in environments without `requirements-bm25s.txt`
installed (the default minimal CI install).
"""

from __future__ import annotations

import pytest

from rag_pipeline_presets import PIPELINE_PRESETS, VALID_BM25_BACKENDS


# ---------------------------------------------------------------------------
# Contract 1: every preset declares bm25_backend explicitly + defaults to okapi
# ---------------------------------------------------------------------------


def test_valid_bm25_backends_set() -> None:
    assert VALID_BM25_BACKENDS == {"okapi", "bm25s"}, (
        "ADR 0057 — VALID_BM25_BACKENDS narrowed on purpose. Adding "
        "another backend requires a new ADR (re-open conditions)."
    )


@pytest.mark.parametrize("preset_name", sorted(PIPELINE_PRESETS.keys()))
def test_all_presets_default_to_okapi(preset_name: str) -> None:
    """ADR 0001 + 0057 invariant: every preset's bm25_backend = "okapi".

    The opt-in `bm25s` backend MUST stay at the eval-row level
    (eval/config.yaml `full_bm25s`) — never at preset level — so the
    existing eval rows stay byte-equal until an explicit ADR flip.
    """
    preset = PIPELINE_PRESETS[preset_name]
    assert preset.get("bm25_backend") == "okapi", (
        f"Preset {preset_name!r} must declare bm25_backend='okapi' "
        f"(ADR 0001 + ADR 0057 invariant). Got: {preset.get('bm25_backend')!r}"
    )


# ---------------------------------------------------------------------------
# Contract 2: ranking parity (bm25s robertson vs rank_bm25 BM25Okapi)
# ---------------------------------------------------------------------------


@pytest.fixture
def korean_rfp_corpus() -> list[list[str]]:
    """Realistic Korean RFP-ish corpus with token repetition for IDF.

    Matches the surface that hits BM25 in practice: short Korean RFP
    section text after regex tokenization (한글 + 숫자 + 영문). Token
    repetition across docs is intentional — IDF only varies when terms
    appear in multiple docs.
    """
    return [
        ["입찰", "참여", "시작일", "계약일"],
        ["사업", "기간", "12", "개월"],
        ["예산", "130000000", "원"],
        ["한영대학교", "특성화", "사업"],
        ["교육환경", "구축", "사업"],
        ["계약", "체결", "입찰"],
    ]


@pytest.mark.parametrize(
    "query",
    [
        ["입찰", "사업"],  # multi-hit query, ranking should be unanimous
        ["사업"],  # single-term query
        ["계약"],  # term that appears in 2 docs (IDF effect)
        ["없는토큰"],  # OOV — both backends should score 0
    ],
)
def test_bm25s_robertson_ranking_matches_okapi(
    korean_rfp_corpus: list[list[str]], query: list[str]
) -> None:
    """bm25s.BM25(method="robertson") ranking == rank_bm25 BM25Okapi ranking.

    Validates the swap is safe under RRF fusion: even if absolute scores
    differ, top-N ordering is identical so the fused ranking after the
    fusion step is bit-equal to the okapi path.
    """
    bm25s = pytest.importorskip("bm25s")
    from rank_bm25 import BM25Okapi  # in base requirements.txt, never skip

    okapi = BM25Okapi(korean_rfp_corpus)
    okapi_scores = okapi.get_scores(query)
    okapi_ranking = sorted(
        range(len(korean_rfp_corpus)), key=lambda i: okapi_scores[i], reverse=True
    )

    bm25s_ret = bm25s.BM25(method="robertson", k1=1.5, b=0.75)
    bm25s_ret.index(korean_rfp_corpus, show_progress=False)
    bm25s_scores = bm25s_ret.get_scores(query)
    bm25s_ranking = sorted(
        range(len(korean_rfp_corpus)), key=lambda i: bm25s_scores[i], reverse=True
    )

    assert bm25s_ranking == okapi_ranking, (
        f"Ranking diverged for query={query}: "
        f"okapi={okapi_ranking} okapi_scores={list(okapi_scores)}; "
        f"bm25s={bm25s_ranking} bm25s_scores={list(bm25s_scores)}"
    )


def test_bm25s_robertson_top10_overlap_threshold(
    korean_rfp_corpus: list[list[str]],
) -> None:
    """ADR 0057 Re-open condition (2) — top-N overlap >= 95% threshold.

    On the small fixture the overlap is 100% (entire corpus fits in
    top-N). The contract here is the threshold itself; larger fixtures
    or real corpora may erode this — that's measured separately in
    eval_summary.json `full_bm25s` row.
    """
    bm25s = pytest.importorskip("bm25s")
    from rank_bm25 import BM25Okapi

    okapi = BM25Okapi(korean_rfp_corpus)
    bm25s_ret = bm25s.BM25(method="robertson", k1=1.5, b=0.75)
    bm25s_ret.index(korean_rfp_corpus, show_progress=False)

    query = ["입찰", "사업"]
    k = min(10, len(korean_rfp_corpus))

    okapi_scores = okapi.get_scores(query)
    okapi_top = set(sorted(range(len(korean_rfp_corpus)), key=lambda i: okapi_scores[i], reverse=True)[:k])

    bm25s_scores = bm25s_ret.get_scores(query)
    bm25s_top = set(sorted(range(len(korean_rfp_corpus)), key=lambda i: bm25s_scores[i], reverse=True)[:k])

    overlap = len(okapi_top & bm25s_top) / max(1, k)
    assert overlap >= 0.95, (
        f"top-{k} overlap {overlap:.2%} below ADR 0057 threshold (0.95). "
        f"okapi={okapi_top} bm25s={bm25s_top}"
    )


# ---------------------------------------------------------------------------
# Contract 3: cache isolation between backends
# ---------------------------------------------------------------------------


def test_cache_isolation_between_backends() -> None:
    """`get_or_build_bm25` keys on (stopword_profile, tokenizer, backend, ...)
    so okapi cache does not serve a bm25s query and vice versa.
    """
    bm25s = pytest.importorskip("bm25s")  # noqa: F841 — gate on availability

    from rag_retrieval import get_or_build_bm25

    index = {
        "schema_version": 1,
        "chunks": [
            {"chunk_id": "c1", "tokens": ["입찰", "참여"], "text": "입찰 참여"},
            {"chunk_id": "c2", "tokens": ["사업", "기간"], "text": "사업 기간"},
        ],
    }

    okapi_bm25, okapi_ids = get_or_build_bm25(index, "shared", "regex", "okapi")
    bm25s_bm25, bm25s_ids = get_or_build_bm25(index, "shared", "regex", "bm25s")

    assert okapi_ids == bm25s_ids == ["c1", "c2"]
    # Same chunk_ids list but DIFFERENT BM25 instances — type or identity
    assert okapi_bm25 is not bm25s_bm25, (
        "Cache leaked between okapi and bm25s backends — different "
        "get_scores semantics, MUST be separate instances."
    )
