"""Regression guards for embedding versioning in run_manifest.

``config_sha256`` pins the pipeline knobs, but the embedding model lives in the
*index*, not the config — so an eval_summary snapshot was not self-describing
about which embedding produced its retrieval metrics. ``compute_run_manifest``
now records ``embedding_backend`` + ``embedding_model_id`` from the loaded
index, both ``None`` when the index is omitted or carries no embedding meta
(forward-compat with pre-versioning snapshots).
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.run_eval import compute_run_manifest  # noqa: E402

CONFIG_PATH = ROOT / "eval" / "config.yaml"


class RunManifestVersioningTest(unittest.TestCase):
    def test_version_fields_from_index(self) -> None:
        index = {
            "schema_version": 2,
            "embedding": {
                "backend": "hashing",
                "model": "hashing-384",
                "dimension": 384,
            },
            "build": {
                "chunking": {
                    "requested_strategy": "fixed",
                    "chunker_version": "chunker.fixed.v1",
                    "max_chars": 520,
                    "overlap_sentences": 1,
                }
            },
        }
        manifest = compute_run_manifest(CONFIG_PATH, index)
        self.assertEqual(manifest["index_schema_version"], 2)
        self.assertEqual(manifest["embedding_backend"], "hashing")
        self.assertEqual(manifest["embedding_model_id"], "hashing-384")
        self.assertEqual(manifest["embedding_dim"], 384)
        self.assertEqual(manifest["chunking_strategy"], "fixed")
        self.assertEqual(manifest["chunker_version"], "chunker.fixed.v1")
        self.assertEqual(manifest["chunk_max_chars"], 520)
        self.assertEqual(manifest["chunk_overlap_sentences"], 1)
        # existing reproducibility fields are untouched
        self.assertIn("git_commit", manifest)
        self.assertIn("config_sha256", manifest)

    def test_missing_index_is_none(self) -> None:
        manifest = compute_run_manifest(CONFIG_PATH)
        self.assertIsNone(manifest["embedding_backend"])
        self.assertIsNone(manifest["embedding_model_id"])
        self.assertIsNone(manifest["index_schema_version"])
        self.assertIsNone(manifest["chunking_strategy"])

    def test_index_without_embedding_meta_is_none(self) -> None:
        manifest = compute_run_manifest(CONFIG_PATH, {"chunks": []})
        self.assertIsNone(manifest["embedding_backend"])
        self.assertIsNone(manifest["embedding_model_id"])

    def test_chunker_version_derived_for_legacy_chunking_meta(self) -> None:
        manifest = compute_run_manifest(
            CONFIG_PATH,
            {"build": {"chunking": {"requested_strategy": "section"}}},
        )
        self.assertEqual(manifest["chunker_version"], "chunker.section.v1")


if __name__ == "__main__":
    unittest.main()
