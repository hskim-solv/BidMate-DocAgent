"""Integration tests for the FastAPI demo surface (issue #75).

These tests bypass uvicorn and use FastAPI's ``TestClient`` so they
remain fast and offline. The index is built in-memory from the
existing ``data/raw`` fixture using the hashing embedding backend,
matching the pattern used by other retrieval regression tests.
"""
from __future__ import annotations

import unittest

import pytest
from fastapi.testclient import TestClient

from api import main as api_main


class ApiSmokeTest(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _inject_shared_index(self, shared_raw_index):
        self.index = shared_raw_index

    def _client(self, *, with_index: bool = True) -> TestClient:
        client = TestClient(api_main.app)
        # TestClient triggers lifespan, which tries to load_index() from
        # disk. Override the loaded state with our in-memory index so we
        # never depend on a prebuilt data/index dir.
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        if with_index:
            api_main.app.state.index = self.index
            api_main.app.state.index_load_error = None
        else:
            api_main.app.state.index = None
            api_main.app.state.index_load_error = "forced for test"
        return client

    def test_health_reports_loaded_index(self) -> None:
        client = self._client()
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["index_loaded"])
        self.assertGreater(body["chunk_count"], 0)
        self.assertGreater(body["doc_count"], 0)

    def test_health_reports_degraded_when_index_missing(self) -> None:
        client = self._client(with_index=False)
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 503)
        detail = resp.json()["detail"]
        self.assertFalse(detail["index_loaded"])
        self.assertEqual(detail["load_error"], "forced for test")

    def test_pipelines_lists_available_presets(self) -> None:
        client = self._client()
        resp = client.get("/pipelines")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("default", body)
        self.assertIsInstance(body["available"], list)
        self.assertIn(body["default"], body["available"])

    def test_query_returns_grounded_answer_contract(self) -> None:
        client = self._client()
        resp = client.post(
            "/query",
            json={"query": "기관 A의 보안 통제 요구사항은?"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        # The API must preserve the run_rag_query contract: at minimum
        # an answer payload and an evidence list must be present.
        self.assertIn("answer", body)
        self.assertIn("evidence", body)
        self.assertIsInstance(body["evidence"], list)

    def test_query_rejects_empty_string(self) -> None:
        client = self._client()
        resp = client.post("/query", json={"query": ""})
        # pydantic v2 returns 422 on min_length violations.
        self.assertEqual(resp.status_code, 422)

    def test_query_503s_when_index_not_loaded(self) -> None:
        client = self._client(with_index=False)
        resp = client.post("/query", json={"query": "anything"})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["detail"]["error"], "index_not_loaded")


if __name__ == "__main__":
    unittest.main()
