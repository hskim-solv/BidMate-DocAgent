"""Contract tests for the Streamlit demo helpers.

The helpers in ``demo/helpers.py`` are deliberately Streamlit-free so
they can be tested without installing the optional ``streamlit`` extra.
The Streamlit module itself is verified via an AST parse — the test
shouldn't depend on the package being installed in CI.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from demo.helpers import (
    SAMPLE_QUERIES,
    STATUS_BADGE,
    VALID_QUERY_TYPES,
    run_pipeline,
)
from rag_core import build_index_payload
from tests._shared_index_cache import get_shared_raw_index


class SampleQueriesContractTest(unittest.TestCase):
    def test_sample_queries_well_formed(self) -> None:
        self.assertGreaterEqual(len(SAMPLE_QUERIES), 4)
        for kind, query, hint in SAMPLE_QUERIES:
            self.assertIn(kind, VALID_QUERY_TYPES)
            self.assertTrue(query.strip(), "query string must not be empty")
            self.assertTrue(hint.strip(), "hint string must not be empty")

    def test_covers_every_query_type(self) -> None:
        # A reviewer landing on the demo should see one representative
        # query for each type the pipeline handles — otherwise the
        # comparison-aware ranking or first-class abstention features
        # are invisible.
        covered = {kind for kind, _, _ in SAMPLE_QUERIES}
        self.assertEqual(
            covered,
            VALID_QUERY_TYPES,
            f"sample query types missing: {VALID_QUERY_TYPES - covered}",
        )

    def test_status_badge_covers_all_statuses(self) -> None:
        # Whatever the pipeline returns as `status`, the UI must have a
        # rendering for it. Drift here is silent — the user just sees
        # the raw status string with no badge.
        from rag_core import (
            ANSWER_STATUS_INSUFFICIENT,
            ANSWER_STATUS_PARTIAL,
            ANSWER_STATUS_SUPPORTED,
        )

        for status in (
            ANSWER_STATUS_SUPPORTED,
            ANSWER_STATUS_PARTIAL,
            ANSWER_STATUS_INSUFFICIENT,
        ):
            self.assertIn(status, STATUS_BADGE)


class StreamlitModuleSyntaxTest(unittest.TestCase):
    def test_streamlit_app_parses(self) -> None:
        # Don't import — that requires the `streamlit` package. AST
        # parse catches syntax errors and stale references introduced
        # by future refactors without needing the heavy install.
        path = ROOT_DIR / "demo" / "streamlit_app.py"
        ast.parse(path.read_text(encoding="utf-8"))

    def test_streamlit_app_imports_from_helpers(self) -> None:
        # The Streamlit module should re-use the helpers (not duplicate
        # SAMPLE_QUERIES) so a future refactor changing the sample set
        # in one place updates both surfaces.
        path = ROOT_DIR / "demo" / "streamlit_app.py"
        source = path.read_text(encoding="utf-8")
        self.assertIn("from demo.helpers import", source)
        self.assertIn("SAMPLE_QUERIES", source)

    def test_run_pipeline_calls_pass_index_first(self) -> None:
        # Regression for issue #303: a single-mode call site invoked
        # ``run_pipeline(query, ...)`` directly, mapping ``query`` to the
        # ``index`` parameter and producing a TypeError at request time.
        # Every call to ``run_pipeline`` in the Streamlit module must pass
        # at least 2 positional args (index, query) — caller code should
        # use the ``_run`` helper which auto-injects ``get_index()``.
        path = ROOT_DIR / "demo" / "streamlit_app.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bad_calls: list[tuple[int, int]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id == "run_pipeline":
                if len(node.args) < 2:
                    bad_calls.append((node.lineno, len(node.args)))
        self.assertEqual(
            bad_calls, [],
            f"streamlit_app.py has run_pipeline() calls with <2 positional args "
            f"at {bad_calls}. Use _run(query, ...) instead — _run injects "
            f"get_index() as the first positional arg. See issue #303.",
        )


class RunPipelineIntegrationTest(unittest.TestCase):
    """End-to-end exercise of ``run_pipeline`` against the real index.

    Catches the kind of regression that broke the Phase 1.1 Dockerfile
    (forgetting to copy ``rag_synthesis.py`` into the image) — if the
    helper or its dependencies drift, this test fails before the demo
    silently breaks for reviewers.
    """

    @classmethod
    def setUpClass(cls) -> None:
        # Issue #915 — worker-local cache, see tests/_shared_index_cache.py.
        cls.index = get_shared_raw_index()

    def test_runs_extractive(self) -> None:
        result = run_pipeline(
            self.index,
            "기관 A의 보안 통제 요구사항은?",
            pipeline="agentic_full",
            top_k=4,
            retrieval_mode="flat",
            context_entities=[],
        )
        self.assertIn("answer", result)
        self.assertEqual(result["answer"]["status"], "supported")
        self.assertGreater(result["_wall_ms"], 0)

    def test_runs_llm_synthesis_with_stub(self) -> None:
        # Verifies the agentic_full_llm preset still resolves and the
        # synthesis path activates (stub backend, byte-equal to
        # extractive per ADR 0011).
        result = run_pipeline(
            self.index,
            "기관 A의 보안 통제 요구사항은?",
            pipeline="agentic_full_llm",
            top_k=4,
            retrieval_mode="flat",
            context_entities=[],
        )
        diag = result.get("diagnostics") or {}
        synthesis = diag.get("synthesis")
        self.assertIsNotNone(synthesis, "synthesis metadata must be present for llm preset")
        assert synthesis is not None
        self.assertEqual(synthesis["backend"], "stub")
        self.assertFalse(synthesis["fell_back"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
