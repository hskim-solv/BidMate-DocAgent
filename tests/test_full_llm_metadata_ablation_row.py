"""Regression tests for ``full_llm_metadata`` ablation row (issue #804).

Found while investigating #800.  ``eval/config.yaml`` had two ablation rows
— ``full`` and ``full_llm_metadata`` — that were byte-identical once the
``name`` field was excluded.  Both shared the same
``pipeline / metadata_first / rerank / verifier_retry / retrieval_mode``
five-tuple, so the eval runner produced the same leaderboard values for
two named columns.

The real dimension that differentiates them is the **metadata extraction
backend** selected at index-build time via the ``BIDMATE_METADATA_BACKEND``
env var (ADR 0017): ``regex`` (ADR 0001 default) vs ``anthropic_tool_use``
(LLM tool use) vs ``openai_function_call``.  That dimension is environmental
(it happens during ``ingestion.normalize_ingestion_row``), not part of the
runner's per-query config — so the config row was missing its discriminator.

Issue #804 codified the discriminator: each row now carries an explicit
``metadata_backend`` key.  The runner silently ignores unknown keys (see
``eval/run_eval.py::normalize_run_config``), so this is additive — but it
restores the property that the byte-identity invariant test from #800 can
catch alias drift across the *entire* ablation set, not just one pair.

These tests pin three properties:

1.  Both rows exist (no accidental delete).
2.  Both rows carry the ``metadata_backend`` discriminator with the
    correct value.
3.  Once ``name`` is stripped, the two rows are NOT byte-identical
    (this is the same invariant the #800 test pins for
    retrieval_only / no_verifier_retry).
"""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "eval" / "config.yaml"


class TestFullLlmMetadataAblationRow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(CONFIG_PATH) as f:
            cls.config = yaml.safe_load(f)
        cls.ablation_runs: list[dict] = cls.config.get("ablation_runs", [])
        cls.ablation_by_name = {row["name"]: row for row in cls.ablation_runs}

    def test_full_row_exists(self) -> None:
        self.assertIn(
            "full",
            self.ablation_by_name,
            "Ablation row 'full' missing from eval/config.yaml",
        )

    def test_full_llm_metadata_row_exists(self) -> None:
        self.assertIn(
            "full_llm_metadata",
            self.ablation_by_name,
            "Ablation row 'full_llm_metadata' missing from eval/config.yaml",
        )

    def test_full_carries_regex_metadata_backend(self) -> None:
        """``full`` is the ADR 0001 default — regex metadata extraction."""
        row = self.ablation_by_name["full"]
        self.assertEqual(
            row.get("metadata_backend"),
            "regex",
            "full: metadata_backend must be 'regex' (ADR 0001 default). "
            "Without the explicit discriminator the byte-identity test "
            "(issue #804) cannot differentiate this row from full_llm_metadata.",
        )

    def test_full_llm_metadata_carries_llm_backend(self) -> None:
        """``full_llm_metadata`` selects the LLM tool-use backend (ADR 0017)."""
        row = self.ablation_by_name["full_llm_metadata"]
        backend = row.get("metadata_backend")
        # Accept either of the two LLM backends documented in the file
        # comment + ``rag_metadata_extraction.ENV_BACKEND`` values, but
        # NOT regex/stub (which would re-introduce the alias).
        self.assertIn(
            backend,
            {"anthropic_tool_use", "openai_function_call"},
            "full_llm_metadata: metadata_backend must be 'anthropic_tool_use' "
            "or 'openai_function_call' (ADR 0017). Got: "
            f"{backend!r}. See eval/config.yaml comment block above the row.",
        )

    def test_full_llm_metadata_differs_from_full(self) -> None:
        """Issue #804 invariant: ``full`` and ``full_llm_metadata`` must
        NOT be byte-identical (name aside).

        The original config defined both rows with identical
        pipeline/metadata_first/rerank/verifier_retry/retrieval_mode, so
        the ablation runner produced identical leaderboard values for
        two named columns.  This is the same Goodhart failure mode that
        #800 pinned for retrieval_only/no_verifier_retry, generalized to
        the full vs full_llm_metadata pair.

        Fix: explicit ``metadata_backend`` discriminator.  If a future
        refactor removes or aliases that key, this test catches it
        before the leaderboard ships two columns with the same number.
        """
        full = self.ablation_by_name["full"]
        full_llm_metadata = self.ablation_by_name["full_llm_metadata"]
        full_minus_name = {k: v for k, v in full.items() if k != "name"}
        flm_minus_name = {
            k: v for k, v in full_llm_metadata.items() if k != "name"
        }
        self.assertNotEqual(
            full_minus_name,
            flm_minus_name,
            "full and full_llm_metadata are byte-identical (issue #804). "
            "If you intended full_llm_metadata to be an alias, delete the "
            "duplicate row; otherwise restore the metadata_backend "
            "discriminator that differentiates them.",
        )

    def test_metadata_backend_does_not_break_runner_normalize(self) -> None:
        """The new key must not crash ``normalize_run_config``.

        ``normalize_run_config`` returns a fixed-shape dict and ignores
        unknown keys, so adding ``metadata_backend`` is additive.  This
        test pins that contract so a future refactor that tightens the
        runner's schema validation (e.g. ``extra='forbid'``) does not
        silently drop this row.
        """
        from eval.run_eval import normalize_run_config

        full_llm_metadata = self.ablation_by_name["full_llm_metadata"]
        normalized = normalize_run_config(full_llm_metadata)
        self.assertEqual(normalized["name"], "full_llm_metadata")
        self.assertEqual(normalized["pipeline"], "agentic_full")


if __name__ == "__main__":
    unittest.main()
