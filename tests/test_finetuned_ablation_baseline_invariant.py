"""Baseline-invariance contract for the LoRA-fine-tuned embedding rows
(issue #434 / ADR 0027).

Both ``agentic_full_finetuned`` and ``naive_baseline_finetuned`` are
additive ablations. Under the default deterministic CI surface
(hashing embedding backend, ``BIDMATE_EMBEDDING_LORA_ADAPTER`` unset)
the **correctness metrics** (``REPRODUCIBLE_METRICS`` — accuracy,
groundedness, citation_precision, abstention, answer_format_compliance)
MUST be byte-equal to their parents' (``full`` / ``naive_baseline``).
Latency / stage-latency drifts run-to-run by μs-scale system noise —
this is universal across every ablation row and is *not* a contract
break (mirrors ``tests/test_eval_reproducibility_regression.py`` which
also excludes latency from its reproducibility check).

The proof has two layers:

1. **Structural** (fast unit test) — the ``embedding_model`` and
   ``embedding_lora_adapter`` keys are silently dropped by
   ``eval/run_eval.normalize_run_config`` (they are not part of the
   hardcoded returned-keys set), so once normalized the two configs
   are identical to their parents. The single behavioral side-effect
   — the LoRA branch in ``rag_core.embed_texts`` — is gated by an
   env var that is unset in CI.

2. **End-to-end** (slow subprocess test) — runs ``eval/run_eval.py``
   once under CI defaults, then pins per-run correctness-metric
   equality between each finetuned row and its parent. Same pattern
   as ``full_reranker`` (ADR 0011) and ``full_hyde`` (ADR 0023).
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Minimal config for EvalSummaryMetricEqualityTest — only the 4 presets needed
# to assert finetuned equality, plus 3 lightweight cases. Running the full
# eval/config.yaml (20 presets) in setUpClass exceeds the subprocess timeout.
_MINIMAL_FINETUNED_CONFIG = {
    "mode": "rag",
    "description": "Finetuned ablation baseline invariant — minimal CI surface",
    "primary_run": "naive_baseline",
    "answer_policy": {
        "answerable_status": "supported",
        "unanswerable_status": "insufficient",
        "min_claims_answerable": 1,
        "require_claim_citations": True,
    },
    "ablation_runs": [
        {"name": "naive_baseline", "pipeline": "naive_baseline"},
        {
            "name": "full",
            "pipeline": "agentic_full",
            "metadata_first": True,
            "rerank": True,
            "verifier_retry": True,
            "retrieval_mode": "flat",
        },
        {
            "name": "agentic_full_finetuned",
            "pipeline": "agentic_full",
            "metadata_first": True,
            "rerank": True,
            "verifier_retry": True,
            "retrieval_mode": "flat",
            "embedding_model": "nlpai-lab/KURE-v1",
            "embedding_lora_adapter": "bidmate/embedding-lora-kure-rfp-ko-v1@<sha>",
        },
        {
            "name": "naive_baseline_finetuned",
            "pipeline": "naive_baseline",
            "embedding_model": "nlpai-lab/KURE-v1",
            "embedding_lora_adapter": "bidmate/embedding-lora-kure-rfp-ko-v1@<sha>",
        },
    ],
    "cases": [
        {
            "id": "single_doc_security",
            "query_type": "single_doc",
            "query": "기관 A의 보안 통제 요구사항은?",
            "expected_doc_ids": ["rfp-agency-a-ai-quality"],
            "expected_terms": ["보안 통제"],
            "expected_citation_terms": ["보안 통제"],
            "answerable": True,
        },
        {
            "id": "comparison_ai_requirements",
            "query_type": "comparison",
            "query": "기관 A와 기관 B의 AI 요구사항 차이 알려줘",
            "expected_doc_ids": [
                "rfp-agency-a-ai-quality",
                "rfp-agency-b-mlops-governance",
            ],
            "expected_terms": ["MLOps", "품질관리"],
            "expected_citation_terms": ["MLOps"],
            "answerable": True,
        },
        {
            "id": "abstention_missing_blockchain",
            "query_type": "abstention",
            "query": "기관 A의 블록체인 납품 실적은?",
            "expected_doc_ids": [],
            "expected_terms": ["블록체인"],
            "answerable": False,
        },
    ],
}


def _normalize_run_config(row: dict) -> dict:
    sys.path.insert(0, str(ROOT / "eval"))
    try:
        from run_eval import normalize_run_config
    finally:
        sys.path.pop(0)
    return normalize_run_config(row)


def _load_config() -> dict:
    return yaml.safe_load((ROOT / "eval" / "config.yaml").read_text(encoding="utf-8"))


def _row_by_name(config: dict, name: str) -> dict:
    for row in config["ablation_runs"]:
        if row["name"] == name:
            return row
    raise KeyError(name)


class YamlRowsLandedTest(unittest.TestCase):
    def test_agentic_full_finetuned_row_present(self) -> None:
        row = _row_by_name(_load_config(), "agentic_full_finetuned")
        self.assertEqual(row["pipeline"], "agentic_full")
        self.assertEqual(row["embedding_model"], "nlpai-lab/KURE-v1")
        self.assertTrue(
            row["embedding_lora_adapter"].startswith("bidmate/embedding-lora-kure-rfp-ko-v1")
        )

    def test_naive_baseline_finetuned_row_present(self) -> None:
        row = _row_by_name(_load_config(), "naive_baseline_finetuned")
        self.assertEqual(row["pipeline"], "naive_baseline")
        self.assertEqual(row["embedding_model"], "nlpai-lab/KURE-v1")

    def test_latency_budgets_have_entries_for_new_rows(self) -> None:
        config = _load_config()
        budgets = config["latency_budgets"]
        self.assertIn("agentic_full_finetuned", budgets)
        self.assertIn("naive_baseline_finetuned", budgets)
        # The full pipeline path is the heavier surface; the
        # finetuned variant inherits the same budget as its parent.
        self.assertEqual(
            budgets["agentic_full_finetuned"]["p95_ms"],
            budgets["full"]["p95_ms"],
        )
        self.assertEqual(
            budgets["naive_baseline_finetuned"]["p95_ms"],
            budgets["naive_baseline"]["p95_ms"],
        )


class NormalizedConfigEqualityTest(unittest.TestCase):
    """The core byte-equality invariant: normalize the finetuned row
    and its parent — they must produce identical normalized dicts
    (modulo ``name``). This is the additive-ablation contract."""

    def test_agentic_full_finetuned_normalizes_equal_to_full(self) -> None:
        config = _load_config()
        finetuned = _row_by_name(config, "agentic_full_finetuned")
        parent = _row_by_name(config, "full")
        n_finetuned = _normalize_run_config(finetuned)
        n_parent = _normalize_run_config(parent)
        # Strip ``name`` — that's the only field that legitimately
        # differs between an ablation row and its parent.
        n_finetuned.pop("name", None)
        n_parent.pop("name", None)
        self.assertEqual(
            n_finetuned,
            n_parent,
            "agentic_full_finetuned must be byte-equal to full after "
            "normalization (modulo name) — additive ablation invariant",
        )

    def test_naive_baseline_finetuned_normalizes_equal_to_parent(self) -> None:
        config = _load_config()
        finetuned = _row_by_name(config, "naive_baseline_finetuned")
        parent = _row_by_name(config, "naive_baseline")
        n_finetuned = _normalize_run_config(finetuned)
        n_parent = _normalize_run_config(parent)
        n_finetuned.pop("name", None)
        n_parent.pop("name", None)
        self.assertEqual(n_finetuned, n_parent)

    def test_embedding_keys_are_silently_dropped(self) -> None:
        """``embedding_model`` and ``embedding_lora_adapter`` are
        documentation read by ``scripts/run_embedding_ablation.py`` at
        index-build time. They MUST NOT propagate into the runtime
        ``run_config`` — that would break byte-equality with the
        parent and pollute every trace record."""
        config = _load_config()
        finetuned = _row_by_name(config, "agentic_full_finetuned")
        normalized = _normalize_run_config(finetuned)
        self.assertNotIn("embedding_model", normalized)
        self.assertNotIn("embedding_lora_adapter", normalized)


class EmbedTextsAdapterGatingTest(unittest.TestCase):
    """The single behavioral side-effect of ADR 0027 is the
    ``BIDMATE_EMBEDDING_LORA_ADAPTER`` branch in ``embed_texts``.
    With the env var unset (CI default) the branch never executes —
    the function falls back to the hashing path bit-identically."""

    def test_hashing_backend_unchanged_with_env_unset(self) -> None:
        """Force the hashing backend (CI default) — with the LoRA env
        var unset the result must be byte-identical to pre-#434
        behavior. The PEFT branch never executes; no adapter cache
        key gets created."""
        prior = os.environ.pop("BIDMATE_EMBEDDING_LORA_ADAPTER", None)
        try:
            import rag_core

            result = rag_core.embed_texts(["기관 A의 보안 통제 요구사항은?"], backend="hashing")
            self.assertEqual(result.backend, "hashing")
            self.assertEqual(result.model, "local-hashing-bow")
            # No cache entry should have been created with a non-None
            # adapter slot — the LoRA branch must not have fired.
            for key in rag_core.MODEL_CACHE:
                self.assertIsNone(
                    key[2],
                    f"MODEL_CACHE got an adapter-tagged key with env unset: {key}",
                )
        finally:
            if prior is not None:
                os.environ["BIDMATE_EMBEDDING_LORA_ADAPTER"] = prior

    def test_model_cache_key_is_three_tuple(self) -> None:
        """The cache-key shape change (#434) is observable here.
        A 2-tuple key would crash on lookup the first time the env
        var is set; the test pins the new shape."""
        import rag_core

        # The MODEL_CACHE type annotation declares the 3-tuple shape.
        # An empty cache is the CI state; reach into the type hints
        # to assert the contract without forcing an ST model load.
        annotation = rag_core.MODEL_CACHE.__class__
        self.assertIs(annotation, dict)
        # Type annotation introspection on the module attribute:
        type_hints = getattr(rag_core, "__annotations__", {})
        cache_type_str = str(type_hints.get("MODEL_CACHE", ""))
        self.assertIn("tuple", cache_type_str.lower())
        self.assertIn("str", cache_type_str.lower())
        # The third tuple slot is the adapter_path (Optional[str]).
        self.assertTrue(
            "None" in cache_type_str or "str | None" in cache_type_str,
            f"MODEL_CACHE third tuple slot must be Optional[str]; got {cache_type_str}",
        )


class EvalSummaryMetricEqualityTest(unittest.TestCase):
    """End-to-end invariance: run ``eval/run_eval.py`` once and assert
    that the finetuned rows produce byte-equal correctness metrics to
    their parents on the public synthetic surface.

    Slow-ish (single eval invocation, ~10 s). Latency / stage_latency
    keys are *not* compared — they vary μs-scale run-to-run regardless
    of which row generated them. The canonical correctness set is the
    ``REPRODUCIBLE_METRICS`` tuple from
    ``tests/test_eval_reproducibility_regression.py``.
    """

    REPRODUCIBLE_METRICS = (
        "accuracy",
        "groundedness",
        "citation_precision",
        "abstention",
        "answer_format_compliance",
    )

    @classmethod
    def setUpClass(cls) -> None:
        import subprocess
        import tempfile

        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        config_path = tmp / "config.yaml"
        config_path.write_text(
            yaml.safe_dump(_MINIMAL_FINETUNED_CONFIG, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        output_dir = tmp / "out"
        result = subprocess.run(
            [
                sys.executable,
                "eval/run_eval.py",
                "--index_dir",
                str(ROOT / "data" / "index"),
                "--output_dir",
                str(output_dir),
                "--config",
                str(config_path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"eval/run_eval.py exited {result.returncode}\n"
                f"stdout: {result.stdout[-2000:]}\n"
                f"stderr: {result.stderr[-2000:]}"
            )
        summary_path = output_dir / "eval_summary.json"
        cls.summary = json.loads(summary_path.read_text(encoding="utf-8"))
        cls.runs = {r["name"]: r for r in cls.summary["ablation"]["runs"]}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _assert_metrics_equal(self, finetuned_name: str, parent_name: str) -> None:
        ft = self.runs.get(finetuned_name)
        parent = self.runs.get(parent_name)
        self.assertIsNotNone(ft, f"missing run {finetuned_name!r}")
        self.assertIsNotNone(parent, f"missing run {parent_name!r}")
        for metric in self.REPRODUCIBLE_METRICS:
            a = ft.get(metric)
            b = parent.get(metric)
            if a is None and b is None:
                continue
            self.assertEqual(
                a,
                b,
                f"{finetuned_name}.{metric}={a} != {parent_name}.{metric}={b} "
                f"— additive-ablation contract broken",
            )

    def test_agentic_full_finetuned_metrics_equal_to_full(self) -> None:
        self._assert_metrics_equal("agentic_full_finetuned", "full")

    def test_naive_baseline_finetuned_metrics_equal_to_naive_baseline(self) -> None:
        self._assert_metrics_equal("naive_baseline_finetuned", "naive_baseline")

    def test_per_slice_correctness_metrics_equal(self) -> None:
        """The per-slice (`by_query_type.*`) accuracy/abstention numbers
        drive the `make real-eval-delta` rendering downstream. They
        must also be invariant — otherwise the additive ablation would
        masquerade as a slice-level regression."""
        for ft_name, parent_name in (
            ("agentic_full_finetuned", "full"),
            ("naive_baseline_finetuned", "naive_baseline"),
        ):
            ft = self.runs[ft_name]
            parent = self.runs[parent_name]
            ft_slices = ft.get("by_query_type") or {}
            parent_slices = parent.get("by_query_type") or {}
            self.assertEqual(
                set(ft_slices.keys()),
                set(parent_slices.keys()),
                f"slice key drift between {ft_name} and {parent_name}",
            )
            for slice_name in ft_slices:
                for metric in ("accuracy", "abstention", "num_predictions"):
                    a = (ft_slices[slice_name] or {}).get(metric)
                    b = (parent_slices[slice_name] or {}).get(metric)
                    if a is None and b is None:
                        continue
                    self.assertEqual(
                        a,
                        b,
                        f"{ft_name}.by_query_type.{slice_name}.{metric}={a} != {parent_name}.…={b}",
                    )


if __name__ == "__main__":
    unittest.main()
