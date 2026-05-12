"""Regression guard for the API default pipeline (ADR 0024, issue #405).

PR-I conservative absorb: the FastAPI ``/query`` surface defaults to
``agentic_full_llm`` (ADR 0011 additive synthesis preset) while

- the CLI default stays ``naive_baseline`` (ADR 0001 invariant),
- the synthesis backend default stays ``stub`` (deterministic,
  token-less),
- the function-level ``DEFAULT_RAG_PIPELINE_NAME`` stays
  ``agentic_full`` so direct ``run_rag_query(...)`` callers (eval, CLI,
  scripts) keep their existing contract.

These three policy boundaries are easy to flip silently by anyone
editing ``api/main.py`` or ``rag_pipeline_presets.py``, so this module
pins them with explicit assertions.
"""

from __future__ import annotations

import unittest

import pytest
from fastapi.testclient import TestClient

import rag_core
import rag_pipeline_presets
from api import main as api_main


class ApiDefaultPipelineTest(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _inject_shared_index(self, shared_raw_index):
        self.index = shared_raw_index

    def _client(self) -> TestClient:
        client = TestClient(api_main.app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        api_main.app.state.index = self.index
        api_main.app.state.index_load_error = None
        return client

    def test_module_constant_pins_agentic_full_llm(self) -> None:
        """``DEFAULT_API_PIPELINE`` is the load-bearing constant; pin it."""
        self.assertEqual(api_main.DEFAULT_API_PIPELINE, "agentic_full_llm")

    def test_resolve_default_pipeline_returns_agentic_full_llm(self) -> None:
        # No env override → fall through to ``DEFAULT_API_PIPELINE``.
        resolved = api_main._resolve_default_pipeline()
        self.assertEqual(resolved, "agentic_full_llm")

    def test_query_without_pipeline_param_returns_agentic_full_llm(self) -> None:
        """``POST /query`` with no ``pipeline`` key must route through ADR 0011."""
        client = self._client()
        resp = client.post("/query", json={"query": "기관 A의 보안 통제 요구사항은?"})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        diagnostics = body.get("diagnostics") or {}
        self.assertEqual(diagnostics.get("pipeline"), "agentic_full_llm")

    def test_query_with_explicit_pipeline_overrides_default(self) -> None:
        """Per-request ``pipeline`` must override the API default."""
        client = self._client()
        resp = client.post(
            "/query",
            json={"query": "기관 A의 보안 통제 요구사항은?", "pipeline": "agentic_full"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        diagnostics = body.get("diagnostics") or {}
        self.assertEqual(diagnostics.get("pipeline"), "agentic_full")

    def test_cli_default_is_unchanged_naive_baseline(self) -> None:
        """ADR 0001 reproducibility invariant: CLI default stays ``naive_baseline``."""
        self.assertEqual(rag_pipeline_presets.DEFAULT_CLI_PIPELINE_NAME, "naive_baseline")
        self.assertEqual(rag_core.DEFAULT_CLI_PIPELINE_NAME, "naive_baseline")

    def test_function_level_default_is_unchanged_agentic_full(self) -> None:
        """Direct ``run_rag_query`` callers keep their existing default.

        The plan-level "conservative absorb" decision (see ADR 0024):
        flip the *API surface* default but leave the function-level
        default alone so eval / scripts / demo / tests that call
        ``run_rag_query(...)`` directly do not silently flip pipeline.
        """
        self.assertEqual(rag_pipeline_presets.DEFAULT_RAG_PIPELINE_NAME, "agentic_full")
        self.assertEqual(rag_core.DEFAULT_RAG_PIPELINE_NAME, "agentic_full")


if __name__ == "__main__":
    unittest.main()
