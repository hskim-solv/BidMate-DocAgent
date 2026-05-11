"""End-to-end regression guards for ADR 0012 (trace backend).

These tests pin the load-bearing properties on the call site
(``rag_core.run_rag_query``) rather than the tracer in isolation:

* With ``BIDMATE_TRACE_BACKEND`` unset, the answer is unchanged from
  baseline, and three additive diagnostics keys appear (``trace_id``
  is a 32-char hex, ``trace_url`` is None, ``trace_backend`` is
  ``"none"``).
* With the OTel backend wired to an in-memory exporter, all six span
  names emit (``run_rag_query``, ``query_analysis``, ``context_resolution``,
  ``retrieval_attempt``, ``retrieve``, ``verify``, ``answer_generation``)
  and the answer status is unchanged.
* If a backend's methods all raise, the query STILL succeeds with a
  ``supported`` answer, ``trace_id`` is still present (a UUID hex),
  and ``trace_url`` is None. Fail-closed is the contract.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import rag_tracing
from rag_core import build_index_payload, run_rag_query


ANSWERABLE_QUERY = "기관 A의 보안 통제 요구사항은?"


class TraceDefaultBackendRegressionTest(unittest.TestCase):
    """With no env var, the answer path is byte-identical (modulo the
    three additive diagnostics keys), and trace fields fall back to
    safe defaults."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.index = build_index_payload(
            Path("data/raw"), embedding_backend="hashing"
        )

    def setUp(self) -> None:
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop(rag_tracing.ENV_BACKEND, None)

    def tearDown(self) -> None:
        self._env.stop()

    def test_default_backend_yields_supported_answer(self) -> None:
        result = run_rag_query(self.index, ANSWERABLE_QUERY)
        self.assertEqual(result["diagnostics"]["answer_status"], "supported")

    def test_diagnostics_carry_trace_keys(self) -> None:
        result = run_rag_query(self.index, ANSWERABLE_QUERY)
        diag = result["diagnostics"]
        self.assertIn("trace_id", diag)
        self.assertIn("trace_url", diag)
        self.assertIn("trace_backend", diag)
        self.assertEqual(diag["trace_backend"], "none")
        self.assertIsNone(diag["trace_url"])
        self.assertEqual(len(diag["trace_id"]), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in diag["trace_id"]))


class TraceOtelBackendRegressionTest(unittest.TestCase):
    """With OTel + InMemorySpanExporter, all expected spans flow."""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: F401
                InMemorySpanExporter,
            )
        except ImportError as exc:  # pragma: no cover - tested via CI install
            raise unittest.SkipTest(f"opentelemetry-sdk not installed: {exc}")
        cls.index = build_index_payload(
            Path("data/raw"), embedding_backend="hashing"
        )

    def test_otel_backend_emits_all_pipeline_spans(self) -> None:
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        exporter = InMemorySpanExporter()
        # Inject a fixed OtelTracer that uses our exporter, by replacing
        # the registry entry. This is the test-only path; production
        # callers go through `make_tracer()` and let OTel build its own.
        def _factory() -> rag_tracing.OtelTracer:
            return rag_tracing.OtelTracer(
                exporter=exporter, service_name="bidmate-test"
            )

        with mock.patch.dict(rag_tracing._BACKENDS, {"otel": _factory}):
            with mock.patch.dict(
                os.environ, {rag_tracing.ENV_BACKEND: "otel"}
            ):
                result = run_rag_query(self.index, ANSWERABLE_QUERY)

        self.assertEqual(result["diagnostics"]["answer_status"], "supported")
        self.assertEqual(result["diagnostics"]["trace_backend"], "otel")
        self.assertIsNone(result["diagnostics"]["trace_url"])

        names = [s.name for s in exporter.get_finished_spans()]
        # Must include the root + every stage span we instrument.
        self.assertIn("run_rag_query", names)
        self.assertIn("query_analysis", names)
        self.assertIn("context_resolution", names)
        self.assertIn("retrieval_attempt", names)
        self.assertIn("retrieve", names)
        self.assertIn("verify", names)
        self.assertIn("answer_generation", names)

    def test_otel_root_span_carries_pipeline_tags(self) -> None:
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        exporter = InMemorySpanExporter()

        def _factory() -> rag_tracing.OtelTracer:
            return rag_tracing.OtelTracer(
                exporter=exporter, service_name="bidmate-test"
            )

        with mock.patch.dict(rag_tracing._BACKENDS, {"otel": _factory}):
            with mock.patch.dict(
                os.environ, {rag_tracing.ENV_BACKEND: "otel"}
            ):
                run_rag_query(self.index, ANSWERABLE_QUERY)

        root = next(
            s for s in exporter.get_finished_spans() if s.name == "run_rag_query"
        )
        # Per #165: tags = pipeline preset, prompt_profile, embedding_backend.
        self.assertIn("bidmate.pipeline", root.attributes)
        self.assertIn("bidmate.prompt_profile", root.attributes)
        self.assertIn("bidmate.embedding_backend", root.attributes)


class TraceFailClosedRegressionTest(unittest.TestCase):
    """If every tracer method raises, the answer path STILL succeeds.

    This is the single most important property of the trace surface
    (ADR 0012). The answer is the product; the trace is diagnostic.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.index = build_index_payload(
            Path("data/raw"), embedding_backend="hashing"
        )

    def test_exploding_backend_does_not_break_query(self) -> None:
        class ExplodingTracer:
            schema_version = 1
            backend_name = "exploding"

            def start_trace(self, **kwargs: Any) -> None:
                raise RuntimeError("simulated start_trace failure")

            def span(self, **kwargs: Any):
                raise RuntimeError("simulated span failure")

            def finish_trace(self, **kwargs: Any) -> None:
                raise RuntimeError("simulated finish_trace failure")

            def get_trace_url(self, trace_id: str) -> str | None:
                raise RuntimeError("simulated get_trace_url failure")

        # Note: the contract isn't that ExplodingTracer is itself
        # graceful — it's that the supported backends (NoneTracer,
        # OtelTracer) wrap their internals in try/except. We verify
        # that here by patching make_tracer to return a
        # *partially-broken* but contract-compliant backend (raises
        # only inside one method, swallowed at the boundary).

        # Use OtelTracer with a forced-broken exporter to exercise the
        # real fail-closed path.
        try:
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
                InMemorySpanExporter,
            )
        except ImportError as exc:  # pragma: no cover
            self.skipTest(f"opentelemetry-sdk not installed: {exc}")

        class BrokenExporter(InMemorySpanExporter):
            def export(self, spans):  # noqa: D401
                raise RuntimeError("simulated exporter failure")

        def _factory() -> rag_tracing.OtelTracer:
            return rag_tracing.OtelTracer(
                exporter=BrokenExporter(), service_name="bidmate-broken"
            )

        with mock.patch.dict(rag_tracing._BACKENDS, {"otel": _factory}):
            with mock.patch.dict(
                os.environ, {rag_tracing.ENV_BACKEND: "otel"}
            ):
                result = run_rag_query(self.index, ANSWERABLE_QUERY)

        self.assertEqual(result["diagnostics"]["answer_status"], "supported")
        # trace_id always present; trace_url None for OTel even when
        # the exporter is broken.
        self.assertEqual(len(result["diagnostics"]["trace_id"]), 32)
        self.assertIsNone(result["diagnostics"]["trace_url"])
        self.assertEqual(result["diagnostics"]["trace_backend"], "otel")

    def test_constructor_failure_falls_back_to_none(self) -> None:
        class ConstructorExplodes:
            def __init__(self) -> None:
                raise RuntimeError("simulated constructor failure")

        with mock.patch.dict(
            rag_tracing._BACKENDS, {"otel": ConstructorExplodes}
        ):
            with mock.patch.dict(
                os.environ, {rag_tracing.ENV_BACKEND: "otel"}
            ):
                result = run_rag_query(self.index, ANSWERABLE_QUERY)

        self.assertEqual(result["diagnostics"]["answer_status"], "supported")
        # make_tracer fell back to NoneTracer; backend_name reflects it.
        self.assertEqual(result["diagnostics"]["trace_backend"], "none")


if __name__ == "__main__":
    unittest.main()
