"""Smoke tests for ``scripts/phase35_m3_ablation`` — keep coverage
narrow but pin (a) the 3-variant grid the runner declares and (b) that
``--reaggregate`` produces a complete REPORT.md without re-running
retrieval or loading the BGE-M3 encoder. Full-pipeline measurement
(FlagEmbedding import + ``_m3_cache`` build + 3-variant × 221 cases)
is exercised in the PR-E measurement run itself, not in CI — these
tests must stay default-CI safe (no FlagEmbedding import, no index
load).
"""
from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.phase35_m3_ablation import (  # noqa: E402
    VariantSpec,
    _prime_m3_index_cache_and_colbert,
    _resolve_specs,
    main,
    run_single_case,
)


class ResolveSpecsTest(unittest.TestCase):
    def test_variant_spec_resolution_3_variants(self) -> None:
        # Pin the variant grid: order matters because the runner uses
        # specs[0] for the index_dir echo in REPORT.md config and the
        # per-category winner table iterates in this order. dense_m3
        # must come first as it's the paired-CI baseline.
        ns = argparse.Namespace(index_dir_m3="data/index/real100_m3")
        specs = _resolve_specs(ns)
        self.assertEqual(
            [s.name for s in specs],
            ["dense_m3", "hybrid_bm25_k60_m3", "m3"],
        )
        backends = [s.retrieval_backend for s in specs]
        self.assertEqual(backends, ["dense", "hybrid", "m3"])
        rrf_ks = [s.rrf_k for s in specs]
        # dense_m3 + m3 use no explicit rrf_k (m3 falls back to the
        # default RRF_K=60 over 3 channels inside apply_fusion_and_reranking).
        # Only hybrid_bm25_k60_m3 pins k=60 explicitly.
        self.assertEqual(rrf_ks, [None, 60, None])
        # All 3 variants must share the same semantic index_dir — Phase
        # 3.5's core claim is "no reindexing for mode changes; BM25 lazy
        # builds on the index dict, m3 cache populates the same dict".
        self.assertEqual(
            {str(s.index_dir) for s in specs}, {"data/index/real100_m3"}
        )


class ReaggregateMainTest(unittest.TestCase):
    def test_main_dry_run_with_reaggregate_minimal(self) -> None:
        # End-to-end --reaggregate exercise: no retrieval, no index load,
        # no FlagEmbedding import. Builds a tiny 2-case × 3-variant
        # raw_results + spec sidecar + eval_config in a tmpdir and
        # asserts the report renders with both paired CI delta tables
        # (hybrid_bm25_k60_m3 vs dense_m3 + m3 vs dense_m3).
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            raw_dir = tmp_path / "in"
            raw_dir.mkdir()
            out_dir = tmp_path / "out"
            # Same 3 variants the runner declares, with deliberately
            # different metric values so paired CI on multi_hop will be
            # non-degenerate (mean_diff != 0 across variants).
            measurements: dict[str, dict[str, object]] = {}
            for variant, score_offset in [
                ("dense_m3", 0.5),
                ("hybrid_bm25_k60_m3", 0.55),
                ("m3", 0.60),
            ]:
                measurements[variant] = {
                    "variant": variant,
                    "per_case": [
                        {
                            "qid": "q1",
                            "query_type": "single_doc",
                            "categories": ["multi_hop"],
                            "gold_chunk_n": 2,
                            "latency_ms": 100.0,
                            "chunk_recall@5": score_offset,
                            "chunk_recall@10": score_offset + 0.1,
                            "mrr": score_offset,
                            "ndcg@10": score_offset,
                        },
                        {
                            "qid": "q2",
                            "query_type": "single_doc",
                            "categories": ["distractor_heavy"],
                            "gold_chunk_n": 1,
                            "latency_ms": 110.0,
                            "chunk_recall@5": score_offset - 0.1,
                            "chunk_recall@10": score_offset,
                            "mrr": score_offset - 0.1,
                            "ndcg@10": score_offset - 0.1,
                        },
                    ],
                    "latency_ms": {"p50": 105.0, "p95": 110.0, "mean": 105.0, "n": 2},
                }
            (raw_dir / "raw_results.json").write_text(
                json.dumps(measurements), encoding="utf-8"
            )
            specs_meta = [
                {
                    "name": "dense_m3",
                    "retrieval_backend": "dense",
                    "rrf_k": None,
                    "index_dir": "data/index/real100_m3",
                    "num_documents": 100,
                    "num_chunks": 26000,
                },
                {
                    "name": "hybrid_bm25_k60_m3",
                    "retrieval_backend": "hybrid",
                    "rrf_k": 60,
                    "index_dir": "data/index/real100_m3",
                    "num_documents": 100,
                    "num_chunks": 26000,
                },
                {
                    "name": "m3",
                    "retrieval_backend": "m3",
                    "rrf_k": None,
                    "index_dir": "data/index/real100_m3",
                    "num_documents": 100,
                    "num_chunks": 26000,
                },
            ]
            (raw_dir / "mode_specs.json").write_text(
                json.dumps(specs_meta), encoding="utf-8"
            )
            # Minimal eval_config — qids must match so reaggregate can
            # look them up to re-derive categories.
            eval_cfg = {
                "cases": [
                    {"id": "q1", "hardcase_categories": ["multi_hop"]},
                    {"id": "q2", "hardcase_categories": ["distractor_heavy"]},
                ]
            }
            cfg_path = tmp_path / "eval.yaml"
            cfg_path.write_text(json.dumps(eval_cfg), encoding="utf-8")

            rc = main([
                "--reaggregate", str(raw_dir / "raw_results.json"),
                "--eval_config", str(cfg_path),
                "--output_dir", str(out_dir),
                "--seeds", "17",
                "--ks", "5,10",
            ])
            self.assertEqual(rc, 0)

            report = (out_dir / "REPORT.md").read_text(encoding="utf-8")
            # Section coverage — all 4 metrics must appear with their
            # paired CI delta tables vs the dense_m3 baseline.
            for metric in ["chunk_recall@5", "chunk_recall@10", "mrr", "ndcg@10"]:
                self.assertIn(f"## {metric}", report)
                self.assertIn(
                    f"### {metric} — `dense_m3` 대비 paired CI delta", report
                )
            # Variant header + per-category winner + Notes section (Korean).
            self.assertIn("## 변형(variants)", report)
            self.assertIn("## 카테고리별 winner", report)
            self.assertIn("## 비고(notes)", report)
            # 3-variant grid must be in the variants table (m3 is the
            # one that distinguishes Phase 3.5 from Phase 3).
            self.assertIn("`dense_m3`", report)
            self.assertIn("`hybrid_bm25_k60_m3`", report)
            self.assertIn("`m3`", report)
            # Phase 3 cross-ref + ADR 0010/0021/0032 must appear in Notes
            # (per absolute rule #5: honest cross-reference of the prior
            # measurement so reviewers can trace the embedding-family swap).
            self.assertIn("Phase 3 cross-ref", report)
            self.assertIn("ADR 0010", report)
            # Line budget: REPORT.md must stay <=200 lines per skill spec.
            self.assertLessEqual(report.count("\n"), 200)
            # Sidecar artifacts written.
            self.assertTrue((out_dir / "deltas.json").exists())
            self.assertTrue((out_dir / "mode_specs.json").exists())
            self.assertTrue((out_dir / "raw_results.json").exists())


class PrimeColbertInt8RegressionTest(unittest.TestCase):
    """CI-safe (no FlagEmbedding): drive the batched colbert fast-path in
    ``_prime_m3_index_cache_and_colbert`` against a hand-built int8
    ``_m3_cache`` and assert two #1012 regressions stay fixed:

    1. The patched static method accepts the ``q_scale``/``d_scale``
       kwargs ``retrieve_candidates`` passes — the 2-positional signature
       raised ``TypeError`` on the first primed scoring.
    2. The fast-path score equals the per-chunk ``M3Encoder.colbert_score``
       under the same int8 dequant — the old ``q_colbert @ big.T`` skipped
       fp32 dequant + per-chunk scale, contaminating int8 measurements.

    No FlagEmbedding: a fake ``M3Encoder`` is seeded into the singleton
    cache via ``__new__`` (bypassing the weight-loading ``__init__``) and
    ``_m3_cache`` is pre-populated so the encoder is never asked to encode.
    """

    def setUp(self) -> None:
        import rag_m3
        from rag_m3 import DEFAULT_M3_MODEL, M3Encoder

        self.rag_m3 = rag_m3
        self.M3Encoder = M3Encoder
        # Real (unpatched) scorer captured before priming swaps it out.
        self._orig_colbert_score = M3Encoder.__dict__["colbert_score"]
        self._orig_cache = dict(rag_m3._ENCODER_CACHE)
        fake_encoder = M3Encoder.__new__(M3Encoder)  # skip __init__/weights
        rag_m3._ENCODER_CACHE.clear()
        rag_m3._ENCODER_CACHE[DEFAULT_M3_MODEL] = fake_encoder
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        # _prime_ mutates the class-level static method; put it back so
        # the rest of the suite sees the real scorer.
        self.M3Encoder.colbert_score = self._orig_colbert_score
        self.rag_m3._ENCODER_CACHE.clear()
        self.rag_m3._ENCODER_CACHE.update(self._orig_cache)

    def test_primed_fast_path_int8_kwargs_and_score_parity(self) -> None:
        from rag_m3 import M3Output

        rng = np.random.default_rng(0)

        def q_int8(rows: int) -> np.ndarray:
            return np.clip(
                np.round(rng.standard_normal((rows, 8)) * 40), -127, 127
            ).astype(np.int8)

        c0, c1 = q_int8(4), q_int8(3)
        scales = [0.013, 0.021]
        cache = M3Output(
            dense=np.zeros((2, 8), dtype=np.float32),
            sparse=[{}, {}],
            colbert=[c0, c1],
            colbert_scales=scales,
        )
        index = {
            "chunks": [
                {"chunk_id": "a", "text": "x"},
                {"chunk_id": "b", "text": "y"},
            ],
            "_m3_cache": cache,
        }
        # Real scorer (per-chunk dequant) for the parity reference.
        reference = self._orig_colbert_score.__func__

        _prime_m3_index_cache_and_colbert(index)
        patched = self.M3Encoder.colbert_score  # now the batched fast path

        q = q_int8(5)
        q_scale = 0.017
        # (1) kwargs accepted — no TypeError (the core #1012 crash).
        s0_fast = patched(q, c0, q_scale=q_scale, d_scale=scales[0])
        s1_fast = patched(q, c1, q_scale=q_scale, d_scale=scales[1])
        # (2) parity with the per-chunk dequant scorer (same arithmetic →
        # bit-identical modulo fp32 rounding).
        s0_ref = reference(q, c0, q_scale=q_scale, d_scale=scales[0])
        s1_ref = reference(q, c1, q_scale=q_scale, d_scale=scales[1])
        self.assertGreater(s0_ref, 0.0)  # non-degenerate fixture
        self.assertAlmostEqual(s0_fast, s0_ref, places=4)
        self.assertAlmostEqual(s1_fast, s1_ref, places=4)
        # Without dequant the raw int8 dot sum is ~1000x larger; assert the
        # fast path is nowhere near the un-scaled value (catches a silent
        # drop of the scale multiply).
        raw_unscaled = float(
            np.sum(np.max(q.astype(np.float32) @ c0.astype(np.float32).T, axis=1))
        )
        self.assertLess(s0_fast, raw_unscaled * 0.5)


class RrfApplicationRegressionTest(unittest.TestCase):
    """Regression guard for issue #1375 — the same bug that shipped broken
    Phase 3 numbers (#956, fixed in #994 / #1366): ``run_single_case``
    sorted hybrid candidates by ``c["score"]``, but ``rag_retrieval`` sets
    ``score = 0.0`` for RRF backends and defers ranking to
    ``apply_fusion_and_reranking``. With every score equal, Python's stable
    sort fell back to candidate (index) insertion order, so RRF never ran
    and ``rrf_k`` had zero effect on the output. The Phase 3.5 runner
    shipped already-fixed in #966 (it carried both calls from birth, having
    learned from #956), but had no test pinning the invariant — so a future
    revert would silently degenerate the hybrid + m3 ranks. These tests pin
    it so the revert is caught in CI instead of in a published REPORT.md.

    CI-safe: exercises only the ``hybrid`` variant path (hashing index) and
    ``apply_fusion_and_reranking`` directly — no FlagEmbedding / BGE-M3
    import, so the ``m3`` 3-channel variant (which OOMs locally) is out of
    scope here, mirroring the Phase 3 test.
    """

    def test_rrf_k_changes_per_item_fusion_score(self) -> None:
        # ``apply_fusion_and_reranking`` is the stage the broken runner
        # skipped. Feed it a pre-fusion candidate list where the dense
        # and bm25 channels disagree, then fuse with rrf_k=30 vs k=100.
        # The bug signature was "rrf_k has no effect"; the contract is
        # that (a) every fused score becomes non-zero and (b) the rrf_k
        # value flows into the numeric score (RRF normalization is
        # rrf_k / n_channels, so the scores differ even when the final
        # ranking happens to be stable across k).
        from rag_retrieval import apply_fusion_and_reranking

        def _candidates() -> list[dict[str, object]]:
            # dense prefers c0 > c1 > c2; bm25 prefers c2 > c1 > c0.
            return [
                {"chunk_id": "c0", "score": 0.0,
                 "score_parts": {"dense": 0.9, "bm25": 0.1}},
                {"chunk_id": "c1", "score": 0.0,
                 "score_parts": {"dense": 0.5, "bm25": 0.5}},
                {"chunk_id": "c2", "score": 0.0,
                 "score_parts": {"dense": 0.1, "bm25": 0.9}},
            ]

        analysis = {"query_type": "single_doc"}
        base_plan = {
            "retrieval_backend": "hybrid",
            "metadata_filters": {},
            "top_k": 10,
        }

        fused_k30 = apply_fusion_and_reranking(
            _candidates(), {}, "q", analysis, {**base_plan, "rrf_k": 30}
        )
        fused_k100 = apply_fusion_and_reranking(
            _candidates(), {}, "q", analysis, {**base_plan, "rrf_k": 100}
        )

        # (a) RRF actually ran — no fused score is left at the 0.0
        # placeholder the candidate stage emits for hybrid.
        self.assertTrue(all(item["score"] > 0.0 for item in fused_k30))
        self.assertTrue(all(item["score"] > 0.0 for item in fused_k100))

        # (b) rrf_k reaches the output: the per-chunk fused score differs
        # between k=30 and k=100 for every chunk.
        scores_k30 = {it["chunk_id"]: it["score"] for it in fused_k30}
        scores_k100 = {it["chunk_id"]: it["score"] for it in fused_k100}
        self.assertEqual(set(scores_k30), set(scores_k100))
        for cid in scores_k30:
            self.assertNotEqual(
                scores_k30[cid], scores_k100[cid],
                f"rrf_k had no effect on {cid}'s fused score — "
                "RRF fusion likely skipped (issue #1375 regression).",
            )

    def test_run_single_case_hybrid_is_not_index_order(self) -> None:
        # End-to-end guard at the runner boundary: with the fusion call
        # in place, the hybrid top-1 must be the chunk both channels
        # favor, NOT the first chunk in index insertion order (which is
        # what the broken score=0.0 stable sort returned). We pin the
        # disagreement deterministically: the LAST-inserted chunk (c3)
        # carries the only query-term match (bm25 rank 0) AND its inline
        # embedding equals the query embedding (dense cosine 1.0), so RRF
        # must surface c3 first. Under the #956 bug the result would be
        # c0 (insertion order). Uses the hashing index path + the
        # hybrid_bm25_k60_m3 spec, so no FlagEmbedding / BGE-M3 load.
        import numpy as np

        from rag_retrieval import embed_query_for_index

        dim = 16
        embedding_cfg = {"backend": "hashing", "model": "local-hashing-bow",
                         "dimension": dim, "normalized": True}
        query = "알파베타감마독점토큰"
        qe = embed_query_for_index(query, embedding_cfg)
        away = (-np.asarray(qe, dtype=np.float32)).tolist()

        def _chunk(cid: str, text: str, emb: list[float]) -> dict[str, object]:
            return {
                "chunk_id": cid, "doc_id": "d0", "title": "t",
                "section": "s", "section_id": "s0",
                "text": text, "embedding": emb,
            }

        # c0..c2 share filler text (no query-term hit); c3 holds the
        # distinctive query token and the query-aligned embedding.
        index = {
            "embedding": embedding_cfg,
            "chunks": [
                _chunk("c0", "공통 본문 내용 하나", away),
                _chunk("c1", "공통 본문 내용 둘", away),
                _chunk("c2", "공통 본문 내용 셋", away),
                _chunk("c3", f"공통 본문 {query} 내용 넷", list(qe)),
            ],
        }
        spec = VariantSpec(
            name="hybrid_bm25_k60_m3", retrieval_backend="hybrid",
            rrf_k=60, index_dir=Path("data/index/real100_m3"),
        )
        retrieved_ids, _ = run_single_case(index, {"query": query}, spec, top_k=10)

        # Insertion (degenerate) order top-1 is c0; RRF must instead rank
        # c3 first since both channels favor it.
        self.assertEqual(
            retrieved_ids[0], "c3",
            "hybrid top-1 fell back to index insertion order — "
            "apply_fusion_and_reranking was not applied (issue #1375).",
        )
        self.assertNotEqual(retrieved_ids[0], "c0")


if __name__ == "__main__":
    unittest.main()
