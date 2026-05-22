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

from pathlib import Path

import pytest

import rag_retrieval
from eval.run_eval import normalize_run_config
from rag_core import build_index_payload, run_rag_query
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


# ---------------------------------------------------------------------------
# Contract 4: end-to-end plan plumbing (the measurement-validity guard)
# ---------------------------------------------------------------------------
#
# Issue #988 / ADR 0057 — the `full_bm25s` eval row declares
# `bm25_backend: bm25s`, but the swap is only MEASURED if the value reaches
# `rag_retrieval._make_bm25_instance` through the full
# normalize_run_config -> run_rag_query -> make_plan -> retrieve_candidates
# chain. The original ADR 0057 PR left a gap: `make_plan` never wrote
# `bm25_backend` into the plan dict and `run_rag_query` never threaded the
# kwarg, so `retrieve_candidates` silently fell back to okapi while the
# eval summary still labelled the run `bm25s` — okapi measured under a
# bm25s label. Contracts 1-3 above are unit-level (`_make_bm25_instance`
# parity, preset defaults, cache keys) and did NOT catch this; the missing
# guard was the eval-row -> executed-plan flow. These tests spy on
# `_make_bm25_instance` (delegating to okapi so the optional bm25s wheel is
# not required) to assert which backend the *executed plan* actually requests.

_E2E_QUERY = "기관 A의 보안 통제 요구사항은?"


@pytest.fixture
def fresh_hashing_index() -> dict:
    """A fresh per-test index so the BM25 cache starts empty — the spy must
    observe the build call, not a cache hit warmed by an earlier test."""
    return build_index_payload(Path("data/raw"), embedding_backend="hashing")


def _spy_make_bm25_instance(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Patch `_make_bm25_instance` to record the requested backend and always
    build okapi, so the threading assertion runs without the bm25s wheel."""
    recorded: list[str] = []
    real = rag_retrieval._make_bm25_instance

    def spy(corpus: list[list[str]], backend: str) -> object:
        recorded.append(backend)
        return real(corpus, "okapi")

    monkeypatch.setattr(rag_retrieval, "_make_bm25_instance", spy)
    return recorded


def test_full_bm25s_config_row_normalizes_to_bm25s() -> None:
    """The committed `full_bm25s` ablation row must normalize to a run_config
    whose `bm25_backend` is `bm25s` (the value that drives the executed plan)."""
    import yaml

    raw = yaml.safe_load(Path("eval/config.yaml").read_text(encoding="utf-8"))
    row = next(r for r in raw["ablation_runs"] if r.get("name") == "full_bm25s")
    run_config = normalize_run_config(row)
    assert run_config["bm25_backend"] == "bm25s"
    assert run_config["retrieval_backend"] == "hybrid"


def test_bm25s_backend_reaches_make_bm25_instance(
    fresh_hashing_index: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: bm25_backend='bm25s' threads through run_rag_query ->
    make_plan -> retrieve_candidates -> _make_bm25_instance(..., 'bm25s').

    The guard the original ADR 0057 PR lacked — it fails on the dropped
    `plan['bm25_backend']` (okapi-as-bm25s mislabel) regression."""
    recorded = _spy_make_bm25_instance(monkeypatch)

    result = run_rag_query(
        fresh_hashing_index,
        _E2E_QUERY,
        pipeline="agentic_full",
        retrieval_backend="hybrid",
        bm25_backend="bm25s",
    )

    assert recorded, "BM25 was never built — query did not hit the hybrid path"
    assert set(recorded) == {"bm25s"}, (
        f"executed plan requested backends {set(recorded)} — bm25_backend did "
        "not thread to retrieve_candidates (okapi-as-bm25s mislabel regression)"
    )
    assert result["plan"]["bm25_backend"] == "bm25s"
    assert result["diagnostics"]["bm25_backend"] == "bm25s"


def test_okapi_backend_is_default_and_reaches_make_bm25_instance(
    fresh_hashing_index: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: the default hybrid run requests okapi, never bm25s — so the
    bm25s assertion above is meaningful (not vacuously satisfied by a
    backend-blind code path). Also pins the ADR 0001 okapi default."""
    recorded = _spy_make_bm25_instance(monkeypatch)

    result = run_rag_query(
        fresh_hashing_index,
        _E2E_QUERY,
        pipeline="agentic_full",
        retrieval_backend="hybrid",
    )

    assert recorded, "BM25 was never built — query did not hit the hybrid path"
    assert set(recorded) == {"okapi"}
    assert result["plan"]["bm25_backend"] == "okapi"
    assert result["diagnostics"]["bm25_backend"] == "okapi"
