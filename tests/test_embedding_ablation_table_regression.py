"""Regression guards for the retrieval-surface embedding ablation runner.

``scripts/run_embedding_ablation.py`` gained (issue #1359) the ability to
print the ADR 0069 retrieval aggregates (``chunk_recall@k`` / ``mrr`` /
``ndcg``) with their bootstrap CI band + a ``(SIG)`` / ``(overlap)`` flag, a
per-non-baseline-model delta block (the old single-column delta only compared
the *last* model), and to build from the real PDF/HWP corpus via
``--metadata-csv`` / ``--files-dir`` / ``--eval-config`` instead of the
public fixture ``--input-dir``.

These are pure table-rendering + argv-construction guards — no model download,
no eval run — so they stay deterministic and offline in CI.
"""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts import run_embedding_ablation as rea  # noqa: E402


def _run_block(recall10: float, *, ci_lo: float, ci_hi: float) -> dict:
    """One ablation-run block with both answer + retrieval metrics + CI."""
    return {
        "accuracy": 0.80,
        "groundedness": 0.90,
        "citation_precision": 0.70,
        "abstention": 0.10,
        "answer_format_compliance": 1.0,
        "chunk_recall_at_5": recall10 - 0.05,
        "chunk_recall_at_10": recall10,
        "chunk_recall_at_20": recall10 + 0.03,
        "chunk_mrr": recall10 - 0.10,
        "chunk_ndcg_at_10": recall10 - 0.08,
        "ci": {
            "chunk_recall_at_10": {"ci_lo": ci_lo, "ci_hi": ci_hi},
            "chunk_recall_at_5": {"ci_lo": ci_lo - 0.05, "ci_hi": ci_hi - 0.05},
            "chunk_recall_at_20": {"ci_lo": ci_lo + 0.03, "ci_hi": ci_hi + 0.03},
            "chunk_mrr": {"ci_lo": ci_lo - 0.10, "ci_hi": ci_hi - 0.10},
            "chunk_ndcg_at_10": {"ci_lo": ci_lo - 0.08, "ci_hi": ci_hi - 0.08},
        },
    }


def _model_runs(recall10: float, *, ci_lo: float, ci_hi: float) -> dict:
    return {name: _run_block(recall10, ci_lo=ci_lo, ci_hi=ci_hi) for name in rea.ABLATION_NAMES}


def _capture(per_model: dict) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rea.print_table(per_model)
    return buf.getvalue()


class PrintTableRetrievalSurfaceTest(unittest.TestCase):
    def test_retrieval_rows_present(self) -> None:
        out = _capture(
            {
                "MiniLM": _model_runs(0.60, ci_lo=0.55, ci_hi=0.66),
                "nlpai-lab/KURE-v1": _model_runs(0.71, ci_lo=0.68, ci_hi=0.80),
            }
        )
        for label in ("chunk_recall@5", "chunk_recall@10", "chunk_recall@20", "chunk_mrr", "chunk_ndcg@10"):
            self.assertIn(label, out)
        # answer-quality rows still present
        self.assertIn("accuracy", out)

    def test_per_model_delta_block_and_sign(self) -> None:
        out = _capture(
            {
                "MiniLM": _model_runs(0.60, ci_lo=0.55, ci_hi=0.66),
                "KURE-v1": _model_runs(0.71, ci_lo=0.68, ci_hi=0.80),
            }
        )
        self.assertIn("Δ vs baseline (MiniLM, pp)", out)
        self.assertIn("KURE-v1", out)
        # +0.11 recall@10 → +11.0pp, printed with explicit + sign
        self.assertIn("+11.0", out)

    def test_three_model_delta_each_vs_baseline(self) -> None:
        # The old single-column delta only compared the LAST model; every
        # non-baseline model must now get its own delta line.
        out = _capture(
            {
                "MiniLM": _model_runs(0.60, ci_lo=0.55, ci_hi=0.66),
                "KURE-v1": _model_runs(0.71, ci_lo=0.68, ci_hi=0.80),
                "bge-m3-korean": _model_runs(0.65, ci_lo=0.60, ci_hi=0.70),
            }
        )
        delta_section = out.split("Δ vs baseline", 1)[1]
        self.assertIn("KURE-v1", delta_section)
        self.assertIn("bge-m3-korean", delta_section)

    def test_non_overlapping_ci_flagged_sig(self) -> None:
        # baseline CI [0.55,0.66] vs candidate [0.68,0.80] → disjoint → (SIG)
        out = _capture(
            {
                "MiniLM": _model_runs(0.60, ci_lo=0.55, ci_hi=0.66),
                "KURE-v1": _model_runs(0.71, ci_lo=0.68, ci_hi=0.80),
            }
        )
        self.assertIn("(SIG)", out)
        self.assertNotIn("(overlap)", out)

    def test_overlapping_ci_flagged_overlap(self) -> None:
        # baseline [0.55,0.66] vs candidate [0.60,0.70] → overlap
        out = _capture(
            {
                "MiniLM": _model_runs(0.60, ci_lo=0.55, ci_hi=0.66),
                "KURE-v1": _model_runs(0.63, ci_lo=0.60, ci_hi=0.70),
            }
        )
        self.assertIn("(overlap)", out)
        self.assertNotIn("(SIG)", out)

    def test_none_metric_renders_na(self) -> None:
        base = _model_runs(0.60, ci_lo=0.55, ci_hi=0.66)
        cand = _model_runs(0.71, ci_lo=0.68, ci_hi=0.80)
        # gold-free slice → recall is None for the candidate
        for name in rea.ABLATION_NAMES:
            cand[name]["chunk_recall_at_10"] = None
        out = _capture({"MiniLM": base, "KURE-v1": cand})
        self.assertIn("N/A", out)

    def test_missing_ci_falls_back_to_point_delta(self) -> None:
        base = _model_runs(0.60, ci_lo=0.55, ci_hi=0.66)
        cand = _model_runs(0.71, ci_lo=0.68, ci_hi=0.80)
        for name in rea.ABLATION_NAMES:
            cand[name]["ci"] = {}  # no bands
            base[name]["ci"] = {}
        out = _capture({"MiniLM": base, "KURE-v1": cand})
        # delta still printed, just without the CI annotation
        self.assertIn("+11.0", out)
        self.assertNotIn("CI[", out)


class ConfigAgnosticAblationNamesTest(unittest.TestCase):
    """The real100 config defines different run names than the public fixture
    one (full / random_retrieval / single_chunk / full_bm25s, no naive_baseline).
    print_table must read run names from the data, not the hardcoded tuple, or a
    multi-model real run KeyErrors on the missing naive_baseline."""

    def _block(self, recall10: float) -> dict:
        return {
            "accuracy": 0.8,
            "chunk_recall_at_10": recall10,
            "ci": {"chunk_recall_at_10": {"ci_lo": recall10 - 0.05, "ci_hi": recall10 + 0.05}},
        }

    def test_real_config_run_names_do_not_crash(self) -> None:
        real_runs = ("full", "random_retrieval", "single_chunk", "full_bm25s")
        per_model = {
            "MiniLM": {n: self._block(0.20) for n in real_runs},
            "KURE-v1": {n: self._block(0.28) for n in real_runs},
        }
        out = _capture(per_model)  # must not raise
        self.assertIn("--- full:", out)
        self.assertIn("--- full_bm25s:", out)
        self.assertNotIn("naive_baseline", out)

    def test_run_missing_from_candidate_is_skipped(self) -> None:
        per_model = {
            "MiniLM": {"full": self._block(0.20), "full_bm25s": self._block(0.30)},
            "KURE-v1": {"full": self._block(0.28)},  # missing full_bm25s
        }
        out = _capture(per_model)  # must not KeyError
        self.assertIn("--- full:", out)
        self.assertNotIn("--- full_bm25s:", out)


class BuildIndexArgvTest(unittest.TestCase):
    def setUp(self) -> None:
        self._captured: list[list[str]] = []
        self._orig_run = rea._run
        rea._run = lambda cmd: self._captured.append(cmd)  # type: ignore[assignment]

    def tearDown(self) -> None:
        rea._run = self._orig_run  # type: ignore[assignment]

    def test_public_fixture_uses_input_dir(self) -> None:
        rea.build_index(
            "nlpai-lab/KURE-v1",
            Path("/tmp/idx"),
            backend="sentence-transformers",
            input_dir="eval/fixtures/smoke_rfp/raw",
            metadata_csv=None,
            files_dir="data/files",
        )
        cmd = self._captured[-1]
        self.assertIn("--input_dir", cmd)
        self.assertIn("eval/fixtures/smoke_rfp/raw", cmd)
        self.assertNotIn("--metadata_csv", cmd)
        self.assertEqual(cmd[cmd.index("--model") + 1], "nlpai-lab/KURE-v1")

    def test_real_corpus_uses_metadata_csv_and_files_dir(self) -> None:
        rea.build_index(
            "Qwen/Qwen3-Embedding-0.6B",
            Path("/tmp/idx_real"),
            backend="sentence-transformers",
            input_dir="eval/fixtures/smoke_rfp/raw",
            metadata_csv="data/data_list.csv",
            files_dir="data/files",
        )
        cmd = self._captured[-1]
        self.assertIn("--metadata_csv", cmd)
        self.assertEqual(cmd[cmd.index("--metadata_csv") + 1], "data/data_list.csv")
        self.assertIn("--files_dir", cmd)
        self.assertNotIn("--input_dir", cmd)

    def test_run_eval_passes_config(self) -> None:
        rea.run_eval(Path("/tmp/idx"), Path("/tmp/out"), config="eval/real_config.local.yaml")
        cmd = self._captured[-1]
        self.assertEqual(cmd[cmd.index("--config") + 1], "eval/real_config.local.yaml")


if __name__ == "__main__":
    unittest.main()
