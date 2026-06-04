"""Property / metamorphic invariants for ``retrieve()`` (issue #1826, T1-b).

Matures the example-based regression guards (``tests/test_*_regression.py``,
notably ``tests/test_hybrid_retrieval_regression.py``) into a property layer.
Each invariant is a *metamorphic relation*: instead of asserting a fixed
expected output, it transforms an input and asserts how the output must (or
must not) change.

Scope (this PR adds tests + the ``hypothesis`` dev dependency only — **zero
behaviour change**, no ``rag_*.py`` production edit):

* **INV-2 (determinism)** — the same ``(query, backend, index)`` retrieved
  twice yields a byte-identical ``[(chunk_id, score), …]`` list. Green
  regression guard; pins the determinism the other invariants lean on.
* **INV-4 (reranker idempotence)** — applying the default ``stub`` reranker
  backend (``BIDMATE_RERANK_BACKEND=stub``, the CI default) is an identity
  pass-through, so the reranked top-k chunk_id list equals the non-reranked
  one and a second application is a fixed point. Green-by-construction under
  the stub; guards against a future reranker stage silently reordering or
  dropping chunks on the no-op path.
* **INV-3 (chunk-order permutation invariance)** — permuting
  ``index["chunks"]`` (and invalidating the order-keyed BM25 cache) must not
  change the retrieved **top-k chunk_id set**. This is the bug-exposure
  candidate: the final fusion sort (``rag_retrieval.py:196``,
  ``scored.sort(key=score, reverse=True)``) carries **no chunk_id tie-break**,
  so on a score tie Python's stable sort preserves input (= chunk) order and
  the retrieved *order* becomes permutation-dependent. The assertion is
  therefore on the set, not the list — see ``test_inv3_order_finding`` below
  for the empirically observed list-equality verdict (a fixed-output guard,
  not a property, kept alongside as the documented evidence). Any future
  tie-break fix (PR-2) is free to make the stronger list relation hold.
* **INV-1 (noise invariance)** — for a query with an unambiguous gold chunk,
  adding unrelated (noise) chunks to the corpus must not lower recall@k.
  Scoped to the ``dense`` backend and a lexically-distinct gold query whose
  agency token is omitted (so the metadata filter does NOT pre-exclude the
  noise — it genuinely reaches the dense scorer). Asserted as recall NOT
  decreasing (the conservative form); hybrid is excluded because BM25 IDF is
  corpus-global, so adding documents shifts term weights and the
  no-regression guarantee does not hold there.

Determinism prerequisites (hard requirement for every relation here):
hashing embedding backend + the ``eval/fixtures/smoke_rfp/raw`` fixture +
fixed shuffle seeds. Non-deterministic backends (bge/cohere/m3/random/real
models) are deliberately excluded.
"""

from __future__ import annotations

import copy
import random
import unittest
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from rag_core import (
    analyze_query,
    build_index_payload,
    make_plan,
    metadata_targets,
    retrieve,
)
from eval.scorers.chunk_metrics import chunk_recall_at_k

# Deterministic backends only. ``dense`` is the ADR 0001 baseline; ``hybrid``
# adds the BM25 + RRF fusion channel (ADR 0010/0058). Both are pure-Python /
# hashing-stable under the smoke fixture, so property exploration is flake-free.
BACKENDS = ["dense", "hybrid"]

# Fixed query set drawn from the smoke fixture (one probe per agency present in
# eval/fixtures/smoke_rfp/raw). Small, closed example space → derandomized
# Hypothesis enumerates it exhaustively with zero flakiness.
QUERIES = [
    "기관 A의 보안 통제 요구사항은?",
    "기관 B MLOps 거버넌스 모니터링 요구사항은?",
    "기관 D 분광기 라만 캘리브레이션 주기는?",
    "기관 E 수질 측정 주기와 기준 항목은?",
]

TOP_K = 8

# Seeds for the INV-3 chunk-order permutations. Several independent shuffles
# guard against a single permutation accidentally being a no-op (e.g. a fixed
# point of the sort) and broaden the metamorphic coverage.
SHUFFLE_SEEDS = [1, 7, 13, 101]

# BM25 caches are keyed by chunk order and (for the shared/regex/okapi build)
# mirrored to legacy back-compat keys. Confirmed against rag_retrieval.py:
#   * ``index["_bm25_by_profile"]`` — primary per-(profile,tokenizer,backend)
#     cache; cache_key embeds len(chunks)+schema_version but NOT chunk order,
#     so a same-length shuffle would silently reuse a stale chunk_ids mapping.
#   * ``index["_bm25"]`` / ``index["_bm25_chunk_ids"]`` — legacy mirror of the
#     (shared, regex, okapi) entry.
# All three are dropped after a permutation so the hybrid BM25 channel rebuilds
# against the new order. (Empirically BM25 scores are order-invariant on this
# fixture — the cache stores (bm25, chunk_ids) as a matched pair, so the set
# stays robust even with a stale entry — but invalidating is correct hygiene
# and keeps the relation honest for any corpus where the mapping could diverge.)
_BM25_CACHE_KEYS = ("_bm25_by_profile", "_bm25", "_bm25_chunk_ids")


def _retrieve(index, query, *, backend="dense", top_k=TOP_K, rerank_cross_encoder=False):
    """Run the planner→retrieve path exactly as the regression suite does.

    Mirror of ``tests/test_hybrid_retrieval_regression.py``'s helper: flat
    retrieval mode, metadata-first, identity rerank (stub), no verifier retry.
    Returns the evidence ``list[dict]`` (each item carries chunk_id / doc_id /
    score / score_parts).

    ``rerank_cross_encoder`` (default ``False``) routes the result through
    ``apply_fusion_and_reranking``'s cross-encoder reranker block; under the
    CI-default ``BIDMATE_RERANK_BACKEND=stub`` that block is an identity
    pass-through (``rag_rerank._stub_backend``), which is exactly the property
    INV-4 below pins.
    """
    analysis = analyze_query(query, metadata_targets(index))
    plan = make_plan(
        analysis,
        top_k=top_k,
        metadata_first=True,
        rerank=True,
        rerank_cross_encoder=rerank_cross_encoder,
        verifier_retry=False,
        retrieval_mode="flat",
        retrieval_backend=backend,
    )
    return retrieve(index, query, analysis, plan)


def _id_score_list(evidence):
    """Ordered ``[(chunk_id, score), …]`` projection — the determinism key."""
    return [(item["chunk_id"], item["score"]) for item in evidence]


def _id_set(evidence):
    """Unordered top-k ``{chunk_id, …}`` projection — the permutation key."""
    return {item["chunk_id"] for item in evidence}


def _invalidate_bm25_cache(index):
    """Drop every order-keyed BM25 cache so the hybrid channel rebuilds.

    Required after permuting ``index["chunks"]``: the cache_key
    (rag_retrieval.py:902) embeds ``len(chunks)`` + ``schema_version`` but not
    chunk order, so without this a same-length shuffle would reuse the
    pre-shuffle ``(bm25, chunk_ids)`` entry instead of rebuilding against the
    permuted order. Dropping it forces the rebuild so the permutation is
    actually exercised on the hybrid path.
    """
    for key in _BM25_CACHE_KEYS:
        index.pop(key, None)


def _permuted_index(index, seed):
    """Return a copy of ``index`` with ``chunks`` permuted under ``seed``.

    A full ``copy.deepcopy`` is impossible: the index carries an unpicklable
    ``_vector_store`` (Chroma ``builtins.Bindings`` handle). That store is
    queried by id and the dense channel reads embeddings via each chunk's own
    ``embedding_idx`` (rag_retrieval.py:584-628) — both order-independent — so
    sharing it is sound. We therefore shallow-copy the dict, deep-copy only the
    order-sensitive ``chunks`` list, shuffle it, and drop the BM25 caches so the
    hybrid channel rebuilds against the new order. The shared class-level index
    stays pristine across Hypothesis examples.
    """
    permuted = dict(index)
    permuted["chunks"] = copy.deepcopy(index["chunks"])
    random.Random(seed).shuffle(permuted["chunks"])
    _invalidate_bm25_cache(permuted)
    return permuted


# INV-1 noise-invariance probe. The query is lexically distinct (rare term
# "라만" / Raman) and deliberately OMITS the agency token ("기관 D") so the
# metadata filter does NOT pre-exclude the unrelated documents — the noise
# chunks genuinely reach the dense scorer rather than being filtered out
# upstream. The gold document's two "라만"-bearing chunks rank top-2 on this
# fixture even with the full noisy corpus present.
NOISE_PROBE_QUERY = "라만 캘리브레이션 분광기"
NOISE_GOLD_DOC = "rfp-agency-d-spectrometer-probe"
NOISE_GOLD_TERM = "라만"


def _gold_chunk_ids(index):
    """Gold chunk_ids = chunks of ``NOISE_GOLD_DOC`` carrying ``NOISE_GOLD_TERM``."""
    return [
        str(chunk["chunk_id"])
        for chunk in index["chunks"]
        if str(chunk.get("doc_id")) == NOISE_GOLD_DOC
        and NOISE_GOLD_TERM in str(chunk.get("text") or "")
    ]


def _clean_corpus(index):
    """Shallow-copy ``index`` restricted to the gold document's chunks.

    The ``clean`` corpus (gold doc only) is the no-noise control; the full
    fixture is the noisy corpus (gold + 10 unrelated chunks). The shared
    ``_vector_store`` is reused unchanged — dense scores are read per chunk via
    ``embedding_idx`` (order/subset-independent), so restricting ``chunks`` is
    sound without rebuilding the store.
    """
    clean = dict(index)
    clean["chunks"] = [
        chunk
        for chunk in index["chunks"]
        if str(chunk.get("doc_id")) == NOISE_GOLD_DOC
    ]
    return clean


class RetrievalInvariantsPropertyTest(unittest.TestCase):
    """Metamorphic relations over the deterministic retrieval path.

    Hypothesis ``@settings`` is applied per ``@given`` method (it cannot wrap a
    ``unittest.TestCase`` class): ``derandomize=True`` makes the small closed
    example space reproducible run-to-run (flake-free), ``max_examples=40``
    exhausts the finite query×backend×seed grid (INV-3 = 4×2×4 = 32, INV-2 =
    4×2 = 8, both fully enumerated rather than sampled), and
    ``deadline=None`` avoids spurious timeouts from the one-time index build /
    BM25 warm-up.
    """

    index: dict

    @classmethod
    def setUpClass(cls) -> None:
        # Build once; the hashing backend makes this deterministic. Individual
        # examples deep-copy before mutating so this stays pristine.
        cls.index = build_index_payload(
            Path("eval/fixtures/smoke_rfp/raw"),
            embedding_backend="hashing",
        )

    # -- INV-2 — determinism (green regression guard) ---------------------

    @settings(derandomize=True, max_examples=40, deadline=None)
    @given(query=st.sampled_from(QUERIES), backend=st.sampled_from(BACKENDS))
    def test_inv2_retrieve_is_deterministic(self, query: str, backend: str) -> None:
        """Same (query, backend, index) → byte-identical (chunk_id, score) list.

        Pins the determinism every other relation depends on. Stronger than a
        set comparison: order *and* score must reproduce exactly.
        """
        first = _id_score_list(_retrieve(self.index, query, backend=backend))
        second = _id_score_list(_retrieve(self.index, query, backend=backend))
        self.assertEqual(first, second)
        self.assertGreater(len(first), 0, "fixture query retrieved nothing")

    # -- INV-3 — chunk-order permutation invariance (top-k set) -----------

    @settings(derandomize=True, max_examples=40, deadline=None)
    @given(
        query=st.sampled_from(QUERIES),
        backend=st.sampled_from(BACKENDS),
        seed=st.sampled_from(SHUFFLE_SEEDS),
    )
    def test_inv3_topk_set_invariant_under_chunk_permutation(
        self, query: str, backend: str, seed: int
    ) -> None:
        """Permuting index["chunks"] must not change the top-k chunk_id SET.

        Metamorphic relation: retrieval result content is a function of
        (query, corpus), not of the storage order of the corpus. The assertion
        is on the *set* because the final fusion sort lacks a chunk_id
        tie-break (rag_retrieval.py:196) — see ``test_inv3_order_finding`` for
        the list-equality (order) verdict, which PR-2's tie-break fix would
        promote. The BM25 cache is invalidated on the permuted copy so the
        hybrid channel rebuilds against the new chunk order rather than reusing
        an order-keyed cached ``(bm25, chunk_ids)`` entry (correct hygiene;
        BM25 scores happen to be order-invariant on this fixture, so the set is
        robust either way, but the invalidation keeps the relation honest for
        any corpus where stale chunk_ids could diverge).
        """
        baseline = _id_set(_retrieve(self.index, query, backend=backend))
        self.assertGreater(len(baseline), 0, "fixture query retrieved nothing")

        permuted = _permuted_index(self.index, seed)
        shuffled = _id_set(_retrieve(permuted, query, backend=backend))

        self.assertEqual(
            baseline,
            shuffled,
            f"top-k chunk_id set changed after chunk permutation "
            f"(backend={backend}, seed={seed})",
        )

    def test_inv3_order_finding_dense_list_stable_hybrid_tie_flips(self) -> None:
        """Document the empirical list-equality verdict behind INV-3's set choice.

        This is a fixed-output *evidence* guard (not a Hypothesis property): it
        pins the exact current behaviour so PR-2's tie-break fix has a visible
        anchor to update. Verdict on the smoke fixture:

        * ``dense``  — list-equality HOLDS under every permutation. No two
          top-k chunks share a score on this fixture, so the final stable sort
          (rag_retrieval.py:196, no chunk_id tie-break) never has to break a
          tie. This is fixture-luck, not a guarantee — hence INV-3 asserts the
          set, not the list, for the deterministic property.
        * ``hybrid`` — list-equality FAILS for the "기관 B MLOps …" query: two
          chunks (``…::chunk-002`` / ``…::chunk-003``) tie at RRF score
          0.975674, and permuting their order in ``chunks`` flips their output
          order (stable sort + missing tie-break). The set is still invariant.

        So the missing tie-break is observable only as an *order* instability on
        a score tie, and only the hybrid RRF path produces such ties on this
        fixture. PR-2 (the tie-break fix) should make ``hybrid`` list-stable too
        and can then flip this method's hybrid branch from ``assertNotEqual`` to
        ``assertEqual``.
        """
        tie_query = "기관 B MLOps 거버넌스 모니터링 요구사항은?"
        order_flip_seed = 1  # observed to swap the chunk-002/003 tie order

        # dense: order is stable across the permutation (no ties on this fixture)
        dense_base = _id_score_list(_retrieve(self.index, tie_query, backend="dense"))
        dense_perm = _id_score_list(
            _retrieve(_permuted_index(self.index, order_flip_seed), tie_query, backend="dense")
        )
        self.assertEqual(
            dense_base,
            dense_perm,
            "dense list-order unexpectedly changed — fixture gained a score tie?",
        )

        # hybrid: the RRF tie makes the *order* permutation-dependent while the
        # set stays invariant. Asserting the inequality locks in the current
        # (pre-tie-break) behaviour so PR-2 has a tripwire.
        hybrid_base = _id_score_list(_retrieve(self.index, tie_query, backend="hybrid"))
        hybrid_perm = _id_score_list(
            _retrieve(_permuted_index(self.index, order_flip_seed), tie_query, backend="hybrid")
        )
        self.assertEqual(
            {cid for cid, _ in hybrid_base},
            {cid for cid, _ in hybrid_perm},
            "hybrid top-k set must stay invariant even though order flips",
        )
        self.assertNotEqual(
            hybrid_base,
            hybrid_perm,
            "expected the hybrid RRF tie to flip output order under permutation; "
            "if this now holds, PR-2's tie-break may have landed — promote INV-3 "
            "to list-equality and update this evidence guard",
        )

    # -- INV-4 — reranker idempotence (stub identity) ---------------------

    @settings(derandomize=True, max_examples=40, deadline=None)
    @given(query=st.sampled_from(QUERIES), backend=st.sampled_from(BACKENDS))
    def test_inv4_stub_reranker_is_idempotent(self, query: str, backend: str) -> None:
        """Default stub reranker is identity → out_ids == in_ids, idempotent.

        Metamorphic relation: applying the cross-encoder reranker (the CI
        default ``BIDMATE_RERANK_BACKEND=stub``, ``rag_rerank._stub_backend``)
        is an identity pass-through. So the reranked top-k chunk_id list equals
        the non-reranked one, and a second independent rerank retrieval
        reproduces it (determinism of the stub rerank path — a true
        ``rerank(rerank(x))`` composition is out of scope for this option-B
        test, which never mutates the production rerank stage). This pins the
        never-reorder
        contract of the stub backend the regression suite relies on; a real
        backend (bge/cohere) is opt-in and out of scope for this deterministic
        property. Compared on chunk_id only — the stub leaves order and
        membership untouched, which is the full identity claim.
        """
        in_ids = [item["chunk_id"] for item in _retrieve(self.index, query, backend=backend)]
        self.assertGreater(len(in_ids), 0, "fixture query retrieved nothing")

        out_ids = [
            item["chunk_id"]
            for item in _retrieve(self.index, query, backend=backend, rerank_cross_encoder=True)
        ]
        self.assertEqual(
            in_ids,
            out_ids,
            f"stub reranker changed the ranking (backend={backend}) — expected identity",
        )

        # Determinism: a second independent rerank retrieval reproduces the ids.
        out_ids_again = [
            item["chunk_id"]
            for item in _retrieve(self.index, query, backend=backend, rerank_cross_encoder=True)
        ]
        self.assertEqual(
            out_ids,
            out_ids_again,
            f"stub reranker is not idempotent (backend={backend})",
        )

    # -- INV-1 — noise invariance (dense, recall non-decreasing) ----------

    @settings(derandomize=True, max_examples=40, deadline=None)
    @given(k=st.sampled_from([5, 10]))
    def test_inv1_noise_does_not_lower_recall_dense(self, k: int) -> None:
        """Adding noise chunks must not evict gold from the dense top-k.

        Concrete guard (the comparative "recall NOT decreasing" framing would
        overstate it): the clean corpus is the gold document alone (3 chunks),
        so at ``top_k=10`` every gold chunk is returned and ``recall_clean`` is
        structurally pinned to 1.0. The assertion ``recall_noisy >=
        recall_clean`` therefore reduces to ``recall_noisy >= 1.0`` — i.e.
        **both gold chunks must stay in the noisy top-k**; noise must not push
        gold out on the dense path. The noisy corpus is the full smoke fixture
        (gold + the other-document chunks reaching the dense scorer, since
        ``NOISE_PROBE_QUERY`` omits the agency token and is not
        metadata-filtered). Scoped to ``dense`` on purpose: BM25 IDF is
        corpus-global, so adding documents reweights terms and the
        no-regression guarantee does not hold on the hybrid path — that is a
        genuine NOT-GUARANTEED case, not a test gap, and is left out rather
        than weakened into a false invariant.
        """
        gold = _gold_chunk_ids(self.index)
        self.assertTrue(gold, "fixture changed: gold probe doc/term no longer present")

        clean_ids = [
            item["chunk_id"]
            for item in _retrieve(_clean_corpus(self.index), NOISE_PROBE_QUERY, backend="dense", top_k=10)
        ]
        noisy_ids = [
            item["chunk_id"]
            for item in _retrieve(self.index, NOISE_PROBE_QUERY, backend="dense", top_k=10)
        ]

        recall_clean = chunk_recall_at_k(clean_ids, gold, k)
        recall_noisy = chunk_recall_at_k(noisy_ids, gold, k)
        # gold is non-empty (asserted above) so chunk_recall_at_k never returns
        # None here; a plain assert (unlike unittest.assertIsNotNone) also
        # narrows float|None → float for static type-checkers.
        assert recall_clean is not None and recall_noisy is not None
        self.assertGreaterEqual(
            recall_noisy,
            recall_clean,
            f"recall@{k} regressed when noise was added: "
            f"clean={recall_clean} noisy={recall_noisy}",
        )


if __name__ == "__main__":
    unittest.main()
