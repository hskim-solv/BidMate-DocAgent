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

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.phase35_m3_ablation import _resolve_specs, main  # noqa: E402


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
                    f"### {metric} — paired CI delta vs `dense_m3`", report
                )
            # Variant header + per-category winner + Notes section.
            self.assertIn("## Variants", report)
            self.assertIn("## Per-category winner", report)
            self.assertIn("## Notes", report)
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


if __name__ == "__main__":
    unittest.main()
