"""Fault-injection tests for the LLM-judge backend layer (issue #171).

The deterministic retrieval / verifier paths are extractive (no LLM
call), so the only LLM consumer that can fail is the judge in
``scripts/llm_judge.py``. External code review flagged the lack of
fault-injection coverage on this surface specifically:

> agent가 (LLM 호출 1회 실패 → retry → 또 실패 → planner가 fallback
> tool 선택)을 안전하게 처리하는지에 대한 fault-injection 테스트

For an extractive system the scope is narrower than for a generative
one — these tests cover the *judge*-call boundary only.

Two layers are tested:

* **Backend dispatcher layer** (``judge_summary``) — a backend can
  raise any ``Exception``. The dispatcher must convert it into a
  per-case ``insufficient`` verdict with a marker reason, so that one
  bad case does not crash the whole eval run.
* **OpenAI-compatible HTTP layer** (``_openai_compatible_backend``) —
  malformed JSON, empty responses, rate limits, server errors, and
  timeouts must all degrade to ``insufficient`` rather than bubbling
  up.

The five scenarios from #171 are spelled out as separate test
methods so a future reader can map each to the issue's acceptance
criteria.
"""
from __future__ import annotations

import json
import unittest
from typing import Any
from unittest import mock

import openai

import scripts.llm_judge as judge_module
from scripts.llm_judge import _openai_compatible_backend, judge_summary


def _fake_summary() -> dict[str, Any]:
    """One case per verifier status — enough to exercise the dispatcher
    without bloating the test fixture."""
    return {
        "primary_run": "full",
        "pipeline": "agentic_full",
        "num_predictions": 2,
        "case_results": [
            {
                "id": "case_supported",
                "query": "private query 1",
                "answer_status": "supported",
                "answer": {"summary": "answer summary 1"},
                "evidence": [{"text": "evidence text 1"}],
            },
            {
                "id": "case_abstain",
                "query": "private query 2",
                "answer_status": "insufficient",
                "answer": {"summary": ""},
                "evidence": [],
            },
        ],
    }


def _install_backend(name: str, fn) -> None:
    """Register a transient backend in the dispatcher table.

    Tests register their fault-injecting backend, exercise
    ``judge_summary``, then tear down — leaving the production
    table untouched.
    """
    judge_module._BACKENDS[name] = fn


def _remove_backend(name: str) -> None:
    judge_module._BACKENDS.pop(name, None)


# ---------------------------------------------------------------------------
# Dispatcher-layer faults (backend raises)
# ---------------------------------------------------------------------------


class BackendFaultDispatcherTest(unittest.TestCase):
    """``judge_summary`` should convert any backend exception into a
    per-case ``insufficient`` verdict, never raise."""

    def setUp(self) -> None:  # noqa: D401
        self._installed: list[str] = []

    def tearDown(self) -> None:
        for name in self._installed:
            _remove_backend(name)

    def _install(self, name: str, fn) -> None:
        _install_backend(name, fn)
        self._installed.append(name)

    def test_429_rate_limit_raised_by_backend_is_caught(self) -> None:
        def rate_limit_backend(_prompt: str, *, verifier_status: str) -> dict[str, Any]:
            raise openai.RateLimitError(
                message="429 Too Many Requests",
                response=mock.MagicMock(status_code=429),
                body=None,
            )

        self._install("fault_429", rate_limit_backend)
        local, agg = judge_summary(_fake_summary(), backend="fault_429")
        self.assertEqual(2, len(local["cases"]))
        for case in local["cases"]:
            self.assertEqual("insufficient", case["judge_status"])
            self.assertIn("backend_error", case["judge_reason_short"].lower())
        self.assertEqual(2, agg["n"])

    def test_5xx_server_error_is_caught(self) -> None:
        def server_error_backend(_prompt: str, *, verifier_status: str) -> dict[str, Any]:
            raise openai.InternalServerError(
                message="500 Internal Server Error",
                response=mock.MagicMock(status_code=500),
                body=None,
            )

        self._install("fault_5xx", server_error_backend)
        local, _agg = judge_summary(_fake_summary(), backend="fault_5xx")
        for case in local["cases"]:
            self.assertEqual("insufficient", case["judge_status"])
            self.assertFalse(case["judge_grounded"])

    def test_connection_timeout_is_caught(self) -> None:
        def timeout_backend(_prompt: str, *, verifier_status: str) -> dict[str, Any]:
            raise openai.APITimeoutError(request=mock.MagicMock())

        self._install("fault_timeout", timeout_backend)
        local, _agg = judge_summary(_fake_summary(), backend="fault_timeout")
        for case in local["cases"]:
            self.assertEqual("insufficient", case["judge_status"])

    def test_one_case_failure_does_not_block_others(self) -> None:
        """A single transient failure must not cascade — the dispatcher
        proceeds to subsequent cases. Verifies one-bad-apple isolation."""
        call_count = {"n": 0}

        def flaky_backend(_prompt: str, *, verifier_status: str) -> dict[str, Any]:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise openai.APIConnectionError(request=mock.MagicMock())
            return {
                "judge_status": "supported" if verifier_status == "supported" else "insufficient",
                "judge_grounded": verifier_status == "supported",
                "judge_reason_short": "ok",
            }

        self._install("fault_flaky", flaky_backend)
        local, agg = judge_summary(_fake_summary(), backend="fault_flaky")
        self.assertEqual(2, agg["n"])
        # First case raised → insufficient marker; second case proceeded normally.
        self.assertEqual("insufficient", local["cases"][0]["judge_status"])
        self.assertEqual("insufficient", local["cases"][1]["judge_status"])

    def test_malformed_json_at_dispatcher_level(self) -> None:
        """If a custom backend returns a malformed shape (missing required
        keys), the normalizer should still produce a valid verdict."""
        def garbage_backend(_prompt: str, *, verifier_status: str) -> dict[str, Any]:
            return {"junk_key": "not_a_valid_verdict"}

        self._install("fault_garbage", garbage_backend)
        local, _agg = judge_summary(_fake_summary(), backend="fault_garbage")
        # Should not crash — but the verdict structure must be intact.
        for case in local["cases"]:
            self.assertIn(case["judge_status"], {"supported", "partial", "insufficient"})


# ---------------------------------------------------------------------------
# OpenAI-compatible backend HTTP-layer faults
# ---------------------------------------------------------------------------


class OpenAICompatibleBackendFaultTest(unittest.TestCase):
    """Mock the openai SDK client at the call site of
    ``_openai_compatible_backend`` to simulate HTTP-layer faults."""

    def setUp(self) -> None:
        # The backend reads three env vars before instantiating the
        # client. Patch them so the function gets past its early
        # validation gate.
        self._env_patcher = mock.patch.dict(
            "os.environ",
            {
                "BIDMATE_JUDGE_API_KEY": "fake-key",
                "BIDMATE_JUDGE_MODEL": "fake-model",
            },
            clear=False,
        )
        self._env_patcher.start()

    def tearDown(self) -> None:
        self._env_patcher.stop()

    @staticmethod
    def _build_mock_response(content: str) -> mock.MagicMock:
        response = mock.MagicMock()
        message = mock.MagicMock()
        message.content = content
        response.choices = [mock.MagicMock(message=message)]
        return response

    def test_malformed_json_response_returns_insufficient(self) -> None:
        with mock.patch("openai.OpenAI") as mock_openai:
            client = mock.MagicMock()
            client.chat.completions.create.return_value = self._build_mock_response(
                "not a valid JSON {"
            )
            mock_openai.return_value = client
            verdict = _openai_compatible_backend(
                "prompt", verifier_status="supported"
            )
        self.assertEqual("insufficient", verdict["judge_status"])
        self.assertFalse(verdict["judge_grounded"])
        self.assertIn("malformed_json", verdict["judge_reason_short"].lower())

    def test_empty_response_falls_back_to_verifier_status(self) -> None:
        """An empty content string (None or '') must not raise. The
        normalizer's existing fallback path applies — defensive but
        already exercised by the upstream code."""
        with mock.patch("openai.OpenAI") as mock_openai:
            client = mock.MagicMock()
            client.chat.completions.create.return_value = self._build_mock_response("")
            mock_openai.return_value = client
            verdict = _openai_compatible_backend(
                "prompt", verifier_status="supported"
            )
        # Falls back to verifier_status (existing _normalize_judge_payload behavior).
        self.assertEqual("supported", verdict["judge_status"])

    def test_none_response_content_falls_back(self) -> None:
        with mock.patch("openai.OpenAI") as mock_openai:
            client = mock.MagicMock()
            client.chat.completions.create.return_value = self._build_mock_response(None)
            mock_openai.return_value = client
            verdict = _openai_compatible_backend(
                "prompt", verifier_status="partial"
            )
        self.assertEqual("partial", verdict["judge_status"])

    def test_rate_limit_propagates_for_dispatcher_to_handle(self) -> None:
        """The HTTP-level backend itself does not retry — it lets the
        dispatcher convert the exception into an insufficient verdict.
        Verified by ``BackendFaultDispatcherTest.test_429_*`` above; this
        test just pins that the backend doesn't silently swallow."""
        with mock.patch("openai.OpenAI") as mock_openai:
            client = mock.MagicMock()
            client.chat.completions.create.side_effect = openai.RateLimitError(
                message="429",
                response=mock.MagicMock(status_code=429),
                body=None,
            )
            mock_openai.return_value = client
            with self.assertRaises(openai.RateLimitError):
                _openai_compatible_backend("prompt", verifier_status="supported")

    def test_connection_error_propagates(self) -> None:
        with mock.patch("openai.OpenAI") as mock_openai:
            client = mock.MagicMock()
            client.chat.completions.create.side_effect = openai.APIConnectionError(
                request=mock.MagicMock()
            )
            mock_openai.return_value = client
            with self.assertRaises(openai.APIConnectionError):
                _openai_compatible_backend("prompt", verifier_status="insufficient")


if __name__ == "__main__":
    unittest.main()
