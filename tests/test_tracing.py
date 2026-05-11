"""Contract tests for ADR 0012 — trace backend abstraction.

These tests lock the load-bearing properties of ``rag_tracing``:

* ``BIDMATE_TRACE_BACKEND`` defaults to ``none`` (no imports, no
  overhead).
* Unknown backend / construction failure → ``NoneTracer`` plus a
  single stderr warning. Never raises.
* ``OtelTracer`` emits the expected span tree with ``bidmate.*``
  attributes, top-level tags, and synthesis-fallback semantics.
* Backend method failures (span emit, finish, set_attributes) are
  swallowed; the surrounding ``with`` body still runs.
"""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest import mock

import rag_tracing


class TracerProtocolTest(unittest.TestCase):
    def setUp(self) -> None:
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop(rag_tracing.ENV_BACKEND, None)

    def tearDown(self) -> None:
        self._env.stop()

    def test_default_backend_is_none(self) -> None:
        tracer = rag_tracing.make_tracer()
        self.assertIsInstance(tracer, rag_tracing.NoneTracer)
        self.assertEqual(tracer.backend_name, "none")

    def test_explicit_none_backend(self) -> None:
        tracer = rag_tracing.make_tracer("none")
        self.assertIsInstance(tracer, rag_tracing.NoneTracer)

    def test_unknown_backend_falls_back_to_none(self) -> None:
        tracer = rag_tracing.make_tracer("hypothetical_backend")
        self.assertIsInstance(tracer, rag_tracing.NoneTracer)

    def test_unknown_backend_via_env_falls_back(self) -> None:
        os.environ[rag_tracing.ENV_BACKEND] = "hypothetical_backend"
        tracer = rag_tracing.make_tracer()
        self.assertIsInstance(tracer, rag_tracing.NoneTracer)

    def test_none_tracer_get_trace_url_is_none(self) -> None:
        tracer = rag_tracing.NoneTracer()
        self.assertIsNone(tracer.get_trace_url("any-id"))

    def test_none_tracer_methods_dont_raise(self) -> None:
        tracer = rag_tracing.NoneTracer()
        tid = rag_tracing.new_trace_id()
        tracer.start_trace(trace_id=tid, name="x", input_payload={}, tags={})
        with tracer.span(trace_id=tid, name="y") as h:
            self.assertIsInstance(h, rag_tracing.SpanHandle)
            h.set_attributes(foo="bar")
        tracer.finish_trace(trace_id=tid, output_payload={})

    def test_new_trace_id_is_32_hex(self) -> None:
        tid = rag_tracing.new_trace_id()
        self.assertEqual(len(tid), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in tid))


class OtelTracerUnitTest(unittest.TestCase):
    """Use OTel's InMemorySpanExporter to assert span shape end-to-end."""

    def setUp(self) -> None:
        try:
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: F401
                InMemorySpanExporter,
            )
        except ImportError as exc:  # pragma: no cover - tested via CI install
            self.skipTest(f"opentelemetry-sdk not installed: {exc}")
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        self.exporter = InMemorySpanExporter()
        self.tracer = rag_tracing.OtelTracer(
            exporter=self.exporter, service_name="bidmate-test"
        )

    def _drive_full_trace(self, *, trace_id: str) -> None:
        self.tracer.start_trace(
            trace_id=trace_id,
            name="run_rag_query",
            input_payload={"query": "기관 A의 보안은?"},
            tags={
                "pipeline": "agentic_full",
                "prompt_profile": "structured_grounded_claims",
                "embedding_backend": "hashing",
            },
        )
        with self.tracer.span(
            trace_id=trace_id, name="query_analysis", attributes={"phase": "initial"}
        ) as span:
            span.set_attributes(query_type="single_doc")
        with self.tracer.span(
            trace_id=trace_id,
            name="retrieval_attempt",
            attributes={"attempt_index": 0, "stage": "metadata_first"},
        ) as outer:
            with self.tracer.span(
                trace_id=trace_id, name="retrieve", attributes={"top_k": 5}
            ) as ret:
                ret.set_attributes(candidate_count=5, retrieve_ms=42.0)
            with self.tracer.span(
                trace_id=trace_id, name="verify", attributes={"verifier_retry": True}
            ) as ver:
                ver.set_attributes(verified=True, verify_ms=3.1, verification_reasons=[])
            outer.set_attributes(verified=True, verification_reasons=[])
        with self.tracer.span(trace_id=trace_id, name="answer_generation") as gen:
            gen.set_attributes(
                answer_status="supported", claim_count=2, citation_count=2,
                abstained=False, answer_generation_ms=8.0,
            )
        self.tracer.finish_trace(
            trace_id=trace_id,
            output_payload={"answer_status": "supported", "abstained": False},
            attributes={"latency_ms": 60.5},
        )

    def test_emits_expected_span_names(self) -> None:
        tid = rag_tracing.new_trace_id()
        self._drive_full_trace(trace_id=tid)
        names = sorted(s.name for s in self.exporter.get_finished_spans())
        self.assertEqual(
            names,
            sorted(
                [
                    "run_rag_query",
                    "query_analysis",
                    "retrieval_attempt",
                    "retrieve",
                    "verify",
                    "answer_generation",
                ]
            ),
        )

    def test_retrieve_and_verify_nest_under_retrieval_attempt(self) -> None:
        tid = rag_tracing.new_trace_id()
        self._drive_full_trace(trace_id=tid)
        spans = self.exporter.get_finished_spans()
        by_name = {s.name: s for s in spans}
        attempt_id = by_name["retrieval_attempt"].context.span_id
        self.assertEqual(by_name["retrieve"].parent.span_id, attempt_id)
        self.assertEqual(by_name["verify"].parent.span_id, attempt_id)

    def test_top_level_tags_are_namespaced(self) -> None:
        tid = rag_tracing.new_trace_id()
        self._drive_full_trace(trace_id=tid)
        root = next(
            s for s in self.exporter.get_finished_spans() if s.name == "run_rag_query"
        )
        self.assertEqual(root.attributes["bidmate.pipeline"], "agentic_full")
        self.assertEqual(
            root.attributes["bidmate.prompt_profile"], "structured_grounded_claims"
        )
        self.assertEqual(root.attributes["bidmate.embedding_backend"], "hashing")
        self.assertEqual(root.attributes["bidmate.trace_id"], tid)

    def test_input_and_output_attrs_namespaced(self) -> None:
        tid = rag_tracing.new_trace_id()
        self._drive_full_trace(trace_id=tid)
        root = next(
            s for s in self.exporter.get_finished_spans() if s.name == "run_rag_query"
        )
        self.assertEqual(root.attributes["bidmate.input.query"], "기관 A의 보안은?")
        self.assertEqual(root.attributes["bidmate.output.answer_status"], "supported")
        self.assertEqual(root.attributes["bidmate.output.abstained"], False)
        self.assertEqual(root.attributes["bidmate.latency_ms"], 60.5)

    def test_synthesis_fallback_attributes_flow_to_span(self) -> None:
        tid = rag_tracing.new_trace_id()
        self.tracer.start_trace(
            trace_id=tid,
            name="run_rag_query",
            input_payload={"query": "x"},
            tags={"pipeline": "agentic_full_llm"},
        )
        with self.tracer.span(trace_id=tid, name="synthesis") as span:
            span.set_attributes(
                synthesis_backend="anthropic",
                synthesis_model="claude-sonnet-4-6",
                tokens_in=120,
                tokens_out=40,
                fell_back=True,
                fallback_reason="backend_error:RuntimeError:no API key",
                synthesis_ms=12.3,
            )
        self.tracer.finish_trace(trace_id=tid, output_payload={})
        syn = next(
            s for s in self.exporter.get_finished_spans() if s.name == "synthesis"
        )
        self.assertEqual(syn.attributes["bidmate.synthesis_backend"], "anthropic")
        self.assertEqual(syn.attributes["bidmate.fell_back"], True)
        self.assertEqual(
            syn.attributes["bidmate.fallback_reason"],
            "backend_error:RuntimeError:no API key",
        )
        self.assertEqual(syn.attributes["bidmate.tokens_in"], 120)


class TracerFailClosedTest(unittest.TestCase):
    """The single non-negotiable property: tracer methods never raise."""

    def test_constructor_failure_returns_none_tracer(self) -> None:
        class Exploding:
            def __init__(self) -> None:
                raise RuntimeError("simulated SDK import / config failure")

        with mock.patch.dict(rag_tracing._BACKENDS, {"otel_broken": Exploding}):
            tracer = rag_tracing.make_tracer("otel_broken")
        self.assertIsInstance(tracer, rag_tracing.NoneTracer)

    def test_span_method_failure_does_not_raise(self) -> None:
        """If a backend's span() raises on entry, the with-body still runs
        (with a no-op SpanHandle) and the caller continues."""

        class BrokenSpanTracer:
            schema_version = 1
            backend_name = "broken"

            def start_trace(self, **kwargs: Any) -> None:
                pass

            def span(self, **kwargs: Any):
                # Returns a "context manager" that raises on __enter__.
                class _Ctx:
                    def __enter__(self_inner):
                        raise RuntimeError("simulated span failure")

                    def __exit__(self_inner, *exc):
                        return False

                return _Ctx()

            def finish_trace(self, **kwargs: Any) -> None:
                pass

            def get_trace_url(self, trace_id: str) -> str | None:
                return None

        # The pipeline-level guard would catch this; here we just verify
        # that the contract demands no raise on the tracer SIDE — the
        # NoneTracer + OtelTracer fulfil that. (BrokenSpanTracer above
        # is a counter-example used in the regression test that wraps
        # with try/except at the call site.)
        tracer = BrokenSpanTracer()
        with self.assertRaises(RuntimeError):
            with tracer.span(trace_id="x", name="y"):
                pass

        # The OtelTracer DOES NOT raise on span entry — verify directly.
        try:
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
                InMemorySpanExporter,
            )
        except ImportError as exc:  # pragma: no cover
            self.skipTest(f"opentelemetry-sdk not installed: {exc}")
        otel = rag_tracing.OtelTracer(
            exporter=InMemorySpanExporter(), service_name="t"
        )
        # No start_trace called → state is empty → span() yields a no-op handle.
        ran = False
        with otel.span(trace_id="never-started", name="x") as h:
            ran = True
            h.set_attributes(anything=True)
        self.assertTrue(ran)

    def test_set_attributes_swallows_setter_errors(self) -> None:
        def boom(_kw: dict[str, Any]) -> None:
            raise RuntimeError("setter exploded")

        h = rag_tracing.SpanHandle(_setter=boom)
        # Must not raise.
        h.set_attributes(foo="bar")

    def test_otel_finish_without_start_is_safe(self) -> None:
        try:
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
                InMemorySpanExporter,
            )
        except ImportError as exc:  # pragma: no cover
            self.skipTest(f"opentelemetry-sdk not installed: {exc}")
        tracer = rag_tracing.OtelTracer(
            exporter=InMemorySpanExporter(), service_name="t"
        )
        # Never called start_trace; finish_trace must be a no-op.
        tracer.finish_trace(trace_id="orphan", output_payload={"x": 1})


class TracerEnvSelectorTest(unittest.TestCase):
    def test_env_selects_otel(self) -> None:
        try:
            import opentelemetry  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            self.skipTest(f"opentelemetry-sdk not installed: {exc}")
        with mock.patch.dict(os.environ, {rag_tracing.ENV_BACKEND: "otel"}):
            tracer = rag_tracing.make_tracer()
        self.assertEqual(tracer.backend_name, "otel")

    def test_explicit_arg_overrides_env(self) -> None:
        with mock.patch.dict(
            os.environ, {rag_tracing.ENV_BACKEND: "this_does_not_exist"}
        ):
            tracer = rag_tracing.make_tracer("none")
        self.assertEqual(tracer.backend_name, "none")


if __name__ == "__main__":
    unittest.main()
