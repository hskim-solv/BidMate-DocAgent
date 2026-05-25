from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_private_hybrid_sweep import (  # noqa: E402
    FORBIDDEN_KEYS,
    assert_aggregate_privacy_safe,
    assert_rendered_output_privacy_safe,
    main,
    render_output_path,
    resolve_specs,
)


def _candidate(chunk_id: str, dense: float, bm25: float, score: float = 0.0) -> dict:
    return {
        "chunk_id": chunk_id,
        "score": score,
        "score_parts": {"dense": dense, "bm25": bm25},
    }


class HybridSweepGridTest(unittest.TestCase):
    def test_variant_grid_is_baseline_plus_27_hybrid_variants(self) -> None:
        specs = resolve_specs()
        self.assertEqual(len(specs), 28)
        self.assertEqual(specs[0].name, "full_dense_top20")
        self.assertEqual(specs[0].retrieval_backend, "dense")
        hybrids = specs[1:]
        self.assertEqual(len(hybrids), 27)
        self.assertEqual({spec.rrf_k for spec in hybrids}, {20, 60, 100})
        self.assertEqual({spec.dense_pool for spec in hybrids}, {20, 50, 100})
        self.assertEqual({spec.bm25_pool for spec in hybrids}, {20, 50, 100})
        self.assertTrue(
            all(spec.name.startswith("hybrid_bm25_dense_v1_") for spec in hybrids)
        )


class RrfChannelPoolTest(unittest.TestCase):
    def test_no_pool_matches_full_pool_behavior(self) -> None:
        from rag_retrieval import apply_fusion_and_reranking

        candidates_a = [
            _candidate("c0", 0.9, 0.1),
            _candidate("c1", 0.5, 0.5),
            _candidate("c2", 0.1, 0.9),
        ]
        candidates_b = [
            _candidate("c0", 0.9, 0.1),
            _candidate("c1", 0.5, 0.5),
            _candidate("c2", 0.1, 0.9),
        ]
        analysis = {"query_type": "single_doc"}
        base_plan = {"retrieval_backend": "hybrid", "top_k": 10, "rrf_k": 60}
        default = apply_fusion_and_reranking(candidates_a, {}, "q", analysis, dict(base_plan))
        explicit_full = apply_fusion_and_reranking(
            candidates_b,
            {},
            "q",
            analysis,
            {**base_plan, "rrf_channel_pools": {"dense": 3, "bm25": 3}},
        )
        self.assertEqual(
            [(row["chunk_id"], row["score"]) for row in default],
            [(row["chunk_id"], row["score"]) for row in explicit_full],
        )

    def test_dense_path_ignores_rrf_channel_pools(self) -> None:
        from rag_retrieval import apply_fusion_and_reranking

        candidates_a = [
            _candidate("c0", 0.0, 0.0, score=0.2),
            _candidate("c1", 0.0, 0.0, score=0.8),
        ]
        candidates_b = [
            _candidate("c0", 0.0, 0.0, score=0.2),
            _candidate("c1", 0.0, 0.0, score=0.8),
        ]
        analysis = {"query_type": "single_doc"}
        base = apply_fusion_and_reranking(
            candidates_a, {}, "q", analysis, {"retrieval_backend": "dense", "top_k": 10}
        )
        with_pools = apply_fusion_and_reranking(
            candidates_b,
            {},
            "q",
            analysis,
            {
                "retrieval_backend": "dense",
                "top_k": 10,
                "rrf_channel_pools": {"dense": 1, "bm25": 1},
            },
        )
        self.assertEqual(
            [(row["chunk_id"], row["score"]) for row in base],
            [(row["chunk_id"], row["score"]) for row in with_pools],
        )

    def test_pool_caps_affect_only_specified_channels(self) -> None:
        from rag_retrieval import apply_fusion_and_reranking

        def candidates() -> list[dict]:
            return [
                _candidate("dense_top", 0.9, 0.1),
                _candidate("bm25_top", 0.5, 0.9),
                _candidate("tail", 0.1, 0.5),
            ]

        analysis = {"query_type": "single_doc"}
        base_plan = {"retrieval_backend": "hybrid", "top_k": 10, "rrf_k": 60}
        dense_only_cap = apply_fusion_and_reranking(
            candidates(),
            {},
            "q",
            analysis,
            {**base_plan, "rrf_channel_pools": {"dense": 1}},
        )
        both_caps = apply_fusion_and_reranking(
            candidates(),
            {},
            "q",
            analysis,
            {**base_plan, "rrf_channel_pools": {"dense": 1, "bm25": 1}},
        )
        dense_only_scores = {row["chunk_id"]: row["score"] for row in dense_only_cap}
        both_scores = {row["chunk_id"]: row["score"] for row in both_caps}
        self.assertGreater(dense_only_scores["tail"], 0.0)
        self.assertEqual(both_scores["tail"], 0.0)


class HybridSweepHarnessTest(unittest.TestCase):
    def test_privacy_guard_rejects_raw_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "privacy guard"):
            assert_aggregate_privacy_safe({"variants": [{"doc_id": "raw-private-id"}]})

    def test_privacy_guard_rejects_private_path_fragments(self) -> None:
        with self.assertRaisesRegex(ValueError, "privacy guard"):
            assert_aggregate_privacy_safe({"safe_key": "/Users/example/private/file.pdf"})
        with self.assertRaisesRegex(ValueError, "privacy guard"):
            assert_aggregate_privacy_safe({"safe_key": "Desktop/projects/private"})
        with self.assertRaisesRegex(ValueError, "privacy guard"):
            assert_aggregate_privacy_safe({"safe_key": ".codex/worktrees/private"})

    def test_rendered_output_allows_relative_paths_only(self) -> None:
        relative = "reports/retrieval/hybrid_sweep_<timestamp>/aggregate.json"
        assert_rendered_output_privacy_safe(relative)

        with self.assertRaisesRegex(ValueError, "rendered output"):
            assert_rendered_output_privacy_safe(
                "/Users/hskim/.codex/worktrees/example/reports/retrieval/aggregate.json"
            )
        with self.assertRaisesRegex(ValueError, "rendered output"):
            assert_rendered_output_privacy_safe(
                "/Users/hskim/Desktop/projects/BidMate-DocAgent/data/index/real100"
            )
        with self.assertRaisesRegex(ValueError, "rendered output"):
            assert_rendered_output_privacy_safe("/opt/local/output/aggregate.json")

    def test_render_output_path_uses_repo_relative_path(self) -> None:
        rendered = render_output_path(
            REPO_ROOT / "reports" / "retrieval" / "hybrid_sweep_example" / "aggregate.json"
        )
        self.assertEqual(rendered, "reports/retrieval/hybrid_sweep_example/aggregate.json")
        assert_rendered_output_privacy_safe(rendered)

    def test_smoke_public_fixture_writes_aggregate_only(self) -> None:
        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "hybrid_sweep"
            stdout = StringIO()
            with redirect_stdout(stdout):
                rc = main(
                    [
                        "--config",
                        "eval/config.yaml",
                        "--index_dir",
                        "data/index",
                        "--output_dir",
                        str(out_dir),
                        "--cases_subset_n",
                        "3",
                    ]
                )
            self.assertEqual(rc, 0)
            rendered_output = stdout.getvalue()
            assert_rendered_output_privacy_safe(rendered_output)
            self.assertNotIn("/Users/", rendered_output)
            self.assertNotIn("Desktop/projects", rendered_output)
            self.assertNotIn(".codex/worktrees", rendered_output)
            self.assertIn("aggregate.json", rendered_output)
            aggregate_path = out_dir / "aggregate.json"
            self.assertTrue(aggregate_path.exists())
            payload = json.loads(aggregate_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["sweep"]["num_variants"], 28)
            self.assertEqual(payload["sweep"]["num_cases"], 3)
            self.assertEqual(len(payload["variants"]), 28)
            assert_aggregate_privacy_safe(payload)

            rendered = json.dumps(payload, ensure_ascii=False)
            public_cfg = yaml.safe_load((REPO_ROOT / "eval/config.yaml").read_text(encoding="utf-8"))
            for case in public_cfg["cases"][:3]:
                self.assertNotIn(str(case["query"]), rendered)
                for doc_id in case.get("expected_doc_ids") or []:
                    self.assertNotIn(str(doc_id), rendered)

            def walk_keys(node: object) -> list[str]:
                keys: list[str] = []
                if isinstance(node, dict):
                    for key, value in node.items():
                        keys.append(str(key).lower())
                        keys.extend(walk_keys(value))
                elif isinstance(node, list):
                    for item in node:
                        keys.extend(walk_keys(item))
                return keys

            self.assertTrue(FORBIDDEN_KEYS.isdisjoint(set(walk_keys(payload))))


if __name__ == "__main__":
    unittest.main()
