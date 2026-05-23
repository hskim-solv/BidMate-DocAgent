"""Smoke tests for ``scripts/phase3_mode_ablation`` — keep coverage
narrow but pin (a) the variant grid the runner declares and (b) that
``--reaggregate`` produces a complete REPORT.md without re-running
retrieval. Full-pipeline measurement is exercised in the PR-D
measurement run itself, not in CI.
"""
from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.phase3_mode_ablation import (  # noqa: E402
    VariantSpec,
    _resolve_specs,
    main,
    run_single_case,
)


class ResolveSpecsTest(unittest.TestCase):
    def test_variant_spec_resolution_4_variants(self) -> None:
        # Pin the variant grid: order matters because the runner uses
        # specs[0] for the index_dir echo in REPORT.md config, and the
        # per-category winner table iterates in this order.
        ns = argparse.Namespace(index_dir="data/index/real100")
        specs = _resolve_specs(ns)
        self.assertEqual(
            [s.name for s in specs],
            ["dense", "hybrid_bm25_k30", "hybrid_bm25_k60", "hybrid_bm25_k100"],
        )
        backends = [s.retrieval_backend for s in specs]
        self.assertEqual(backends, ["dense", "hybrid", "hybrid", "hybrid"])
        rrf_ks = [s.rrf_k for s in specs]
        self.assertEqual(rrf_ks, [None, 30, 60, 100])
        # All 4 variants must share the same index_dir — Phase 3's core
        # claim is "no reindexing for mode changes" (BM25 lazy-builds in
        # rag_retrieval.get_or_build_bm25, cached on the index dict).
        self.assertEqual(
            {str(s.index_dir) for s in specs}, {"data/index/real100"}
        )


class ReaggregateMainTest(unittest.TestCase):
    def test_main_dry_run_with_reaggregate_minimal(self) -> None:
        # End-to-end --reaggregate exercise: no retrieval, no index load.
        # Builds a tiny 2-case × 4-variant raw_results + spec sidecar +
        # eval_config in a tmpdir and asserts the report renders.
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            raw_dir = tmp_path / "in"
            raw_dir.mkdir()
            out_dir = tmp_path / "out"
            # Same 4 variants the runner declares, with deliberately
            # different metric values so paired CI on multi_hop will be
            # non-degenerate (mean_diff != 0 across variants).
            measurements: dict[str, dict[str, object]] = {}
            for variant, score_offset in [
                ("dense", 0.5),
                ("hybrid_bm25_k30", 0.55),
                ("hybrid_bm25_k60", 0.60),
                ("hybrid_bm25_k100", 0.58),
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
                    "name": v,
                    "retrieval_backend": ("dense" if v == "dense" else "hybrid"),
                    "rrf_k": ({"dense": None, "hybrid_bm25_k30": 30,
                               "hybrid_bm25_k60": 60, "hybrid_bm25_k100": 100}[v]),
                    "index_dir": "data/index/real100",
                    "num_documents": 100,
                    "num_chunks": 1234,
                }
                for v in ["dense", "hybrid_bm25_k30", "hybrid_bm25_k60", "hybrid_bm25_k100"]
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
            # paired CI delta tables.
            for metric in ["chunk_recall@5", "chunk_recall@10", "mrr", "ndcg@10"]:
                self.assertIn(f"## {metric}", report)
                self.assertIn(
                    f"### {metric} — `dense` 대비 paired CI delta", report
                )
            # Variant header + per-category winner + Notes section (Korean).
            self.assertIn("## 변형(variants)", report)
            self.assertIn("## 카테고리별 winner", report)
            self.assertIn("## 비고(notes)", report)
            # Line budget: REPORT.md must stay <=200 lines per skill spec.
            self.assertLessEqual(report.count("\n"), 200)
            # Sidecar artifacts written.
            self.assertTrue((out_dir / "deltas.json").exists())
            self.assertTrue((out_dir / "mode_specs.json").exists())
            self.assertTrue((out_dir / "raw_results.json").exists())


class RrfApplicationRegressionTest(unittest.TestCase):
    """Regression guard for issue #1366 — the bug that shipped broken
    Phase 3 numbers (#956): ``run_single_case`` sorted hybrid candidates
    by ``c["score"]``, but ``rag_retrieval`` sets ``score = 0.0`` for RRF
    backends and defers ranking to ``apply_fusion_and_reranking``. With
    every score equal, Python's stable sort fell back to candidate
    (index) insertion order, so RRF never ran and ``rrf_k`` had zero
    effect on the output — all three ``hybrid_bm25_k{30,60,100}``
    variants were byte-identical and worse than ``dense``. #994 wired
    the fusion call into the runner; these tests pin the invariant so a
    future revert is caught in CI instead of in a published REPORT.md.
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
                "RRF fusion likely skipped (issue #1366 regression).",
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
        # c0 (insertion order).
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
            name="hybrid_bm25_k60", retrieval_backend="hybrid",
            rrf_k=60, index_dir=Path("data/index/real100"),
        )
        retrieved_ids, _ = run_single_case(index, {"query": query}, spec, top_k=10)

        # Insertion (degenerate) order top-1 is c0; RRF must instead rank
        # c3 first since both channels favor it.
        self.assertEqual(
            retrieved_ids[0], "c3",
            "hybrid top-1 fell back to index insertion order — "
            "apply_fusion_and_reranking was not applied (issue #1366).",
        )
        self.assertNotEqual(retrieved_ids[0], "c0")


if __name__ == "__main__":
    unittest.main()
