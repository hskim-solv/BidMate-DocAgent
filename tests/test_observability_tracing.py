"""Contract tests for ADR 0013 — observability as additive pluggable surface.

These tests lock four invariants:

1. **Default is noop.** With ``BIDMATE_TRACE_BACKEND`` unset, the query
   path runs identically to a build without ``rag_observability``;
   ``diagnostics`` carries the trace keys but they are all ``None`` /
   ``"none"``.
2. **Span topology.** A backend-injected recording context observes
   every documented stage (``query_analysis`` × 2, ``context_resolution``,
   ``retrieve`` × N, ``verify`` × N, ``answer_generation``) with the
   pipeline-config tags on the root trace.
3. **Fail-closed at every backend boundary.** Exceptions in
   ``start_trace`` / ``span()`` / ``finish()`` never reach the caller;
   the result is byte-identical to a noop run after stripping the
   ``trace_*`` keys (the additive-ablation invariant from ADR 0001 /
   ADR 0007).
4. **Missing optional dep gracefully falls back.** ``langfuse`` /
   ``opentelemetry`` not installed → ``trace_unavailable_reason`` is
   populated, ``run_rag_query`` succeeds.

Following ``tests/test_llm_synthesis.py`` conventions: flat
``unittest.TestCase``, ``setUpClass`` builds a hashing-backend index,
``_BACKENDS`` registry monkey-patched via try/finally.
"""

from __future__ import annotations

import importlib
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import rag_observability
from rag_core import build_index_payload, run_rag_query


ANSWERABLE_QUERY = "기관 A의 보안 통제 요구사항은?"
ABSTAIN_QUERY = "기관 A의 보안과 드론은?"


class _RecordingTraceContext:
    """In-memory ``TraceContext`` for the test suite."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []
        self.tags: dict[str, Any] = {}
        self.finished = False
        self._fixed_url = "https://example.test/trace/abc"

    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[None]:
        self.events.append(("start", name, dict(attrs)))
        try:
            yield None
        finally:
            self.events.append(("end", name, dict(attrs)))

    def set_tag(self, key: str, value: Any) -> None:
        self.tags[key] = value

    def finish(self, diagnostics: dict[str, Any]) -> str | None:
        self.finished = True
        return self._fixed_url


class _RecordingBackend:
    name = "recording"

    def __init__(self) -> None:
        self.last_trace: _RecordingTraceContext | None = None

    def start_trace(self, query: str, tags: dict[str, Any]) -> _RecordingTraceContext:
        self.last_trace = _RecordingTraceContext()
        for key, value in tags.items():
            self.last_trace.set_tag(key, value)
        return self.last_trace


@contextmanager
def _registered_backend(name: str, instance: Any) -> Iterator[None]:
    """Monkey-patch ``_BACKENDS`` for the duration of one test."""
    saved = rag_observability._BACKENDS.get(name)
    rag_observability._BACKENDS[name] = lambda: instance
    prior_env = os.environ.get("BIDMATE_TRACE_BACKEND")
    os.environ["BIDMATE_TRACE_BACKEND"] = name
    try:
        yield
    finally:
        if saved is None:
            rag_observability._BACKENDS.pop(name, None)
        else:
            rag_observability._BACKENDS[name] = saved
        if prior_env is None:
            os.environ.pop("BIDMATE_TRACE_BACKEND", None)
        else:
            os.environ["BIDMATE_TRACE_BACKEND"] = prior_env


@contextmanager
def _unset_trace_env() -> Iterator[None]:
    prior = os.environ.pop("BIDMATE_TRACE_BACKEND", None)
    try:
        yield
    finally:
        if prior is not None:
            os.environ["BIDMATE_TRACE_BACKEND"] = prior


class ObservabilityTracingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = build_index_payload(
            Path("data/raw"),
            embedding_backend="hashing",
        )

    # ------------------------------------------------------------------
    # Invariant 1: default is noop
    # ------------------------------------------------------------------

    def test_default_is_none_backend(self) -> None:
        with _unset_trace_env():
            result = run_rag_query(
                self.index, ANSWERABLE_QUERY, pipeline="agentic_full", top_k=4
            )
        diag = result["diagnostics"]
        self.assertEqual(diag["trace_backend"], "none")
        self.assertIsNone(diag["trace_url"])
        self.assertIsNone(diag["trace_error"])
        self.assertIsNone(diag["trace_unavailable_reason"])

    # ------------------------------------------------------------------
    # Invariant 2: span topology + tags
    # ------------------------------------------------------------------

    def test_recording_backend_emits_all_stage_spans(self) -> None:
        backend = _RecordingBackend()
        with _registered_backend("recording", backend):
            result = run_rag_query(
                self.index, ANSWERABLE_QUERY, pipeline="agentic_full", top_k=4
            )
        trace = backend.last_trace
        self.assertIsNotNone(trace)
        assert trace is not None
        starts = [name for kind, name, _ in trace.events if kind == "start"]
        self.assertIn("query_analysis", starts)
        self.assertIn("context_resolution", starts)
        self.assertIn("retrieve", starts)
        self.assertIn("verify", starts)
        self.assertIn("answer_generation", starts)
        self.assertEqual(
            starts.count("query_analysis"), 2,
            "query_analysis emits two spans (pre + post context resolution)",
        )
        self.assertTrue(trace.finished, "finish() must be called once")
        # Root tags include pipeline metadata
        for required in (
            "pipeline",
            "prompt_profile",
            "embedding_backend",
            "retrieval_backend",
            "retrieval_mode",
            "metadata_first",
            "rerank",
            "verifier_retry",
            "cold_start",
            "query_type",
        ):
            self.assertIn(required, trace.tags, f"missing root tag: {required}")
        # query_type tag is set after analysis
        self.assertIn(trace.tags["query_type"], {"single_doc", "comparison", "follow_up", "abstention"})
        # Trace URL surfaces to diagnostics
        self.assertEqual(result["diagnostics"]["trace_url"], "https://example.test/trace/abc")
        self.assertEqual(result["diagnostics"]["trace_backend"], "recording")

    def test_retry_loop_emits_attempt_indexed_spans(self) -> None:
        backend = _RecordingBackend()
        # Query that should trigger retry behavior (the abstention guard
        # exercises stage_sequence iteration when verifier_retry=True).
        with _registered_backend("recording", backend):
            run_rag_query(
                self.index, ABSTAIN_QUERY, pipeline="agentic_full", top_k=4
            )
        trace = backend.last_trace
        assert trace is not None
        retrieve_starts = [
            attrs for kind, name, attrs in trace.events
            if kind == "start" and name == "retrieve"
        ]
        verify_starts = [
            attrs for kind, name, attrs in trace.events
            if kind == "start" and name == "verify"
        ]
        self.assertGreaterEqual(len(retrieve_starts), 1)
        self.assertEqual(len(retrieve_starts), len(verify_starts))
        # attempt_index attribute is monotonically increasing
        indices = [a.get("attempt_index") for a in retrieve_starts]
        self.assertEqual(indices, sorted(indices))

    # ------------------------------------------------------------------
    # Invariant 3: fail-closed at every backend boundary
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_volatile(diag: dict[str, Any]) -> dict[str, Any]:
        """Strip timing + trace fields that legitimately vary run-to-run."""
        stripped = dict(diag)
        for key in ("trace_url", "trace_backend", "trace_error", "trace_unavailable_reason"):
            stripped.pop(key, None)
        stripped.pop("latency_ms", None)
        stripped.pop("stage_latency", None)
        cleaned_attempts = []
        for attempt in stripped.get("filter_stage_attempts") or []:
            cleaned = {k: v for k, v in attempt.items() if k not in ("retrieve_ms", "verify_ms")}
            cleaned_attempts.append(cleaned)
        if "filter_stage_attempts" in stripped:
            stripped["filter_stage_attempts"] = cleaned_attempts
        return stripped

    def _baseline_diagnostics(self) -> dict[str, Any]:
        """Run query with no trace backend; strip volatile keys for diffing."""
        with _unset_trace_env():
            result = run_rag_query(
                self.index, ANSWERABLE_QUERY, pipeline="agentic_full", top_k=4
            )
        return self._strip_volatile(result["diagnostics"])

    def test_start_trace_exception_falls_back(self) -> None:
        class Exploding:
            name = "exploding"

            def start_trace(self, query: str, tags: dict[str, Any]) -> Any:
                raise RuntimeError("explode")

        baseline = self._baseline_diagnostics()
        with _registered_backend("exploding", Exploding()):
            result = run_rag_query(
                self.index, ANSWERABLE_QUERY, pipeline="agentic_full", top_k=4
            )
        diag = result["diagnostics"]
        self.assertIsNotNone(diag["trace_error"])
        self.assertIn("start_trace", diag["trace_error"])
        self.assertIsNone(diag["trace_url"])
        # Additive-ablation invariant: result byte-identical to baseline
        # after stripping volatile timing keys.
        self.assertEqual(self._strip_volatile(diag), baseline)

    def test_span_exception_does_not_break_query(self) -> None:
        class BrokenSpanCtx:
            def __init__(self) -> None:
                self._call = 0

            @contextmanager
            def span(self, name: str, **attrs: Any) -> Iterator[None]:
                self._call += 1
                if self._call == 1:
                    raise RuntimeError("span boom")
                yield None

            def set_tag(self, key: str, value: Any) -> None:
                pass

            def finish(self, diagnostics: dict[str, Any]) -> str | None:
                return None

        class BrokenBackend:
            name = "brokenspan"

            def start_trace(self, query: str, tags: dict[str, Any]) -> Any:
                return BrokenSpanCtx()

        with _registered_backend("brokenspan", BrokenBackend()):
            result = run_rag_query(
                self.index, ANSWERABLE_QUERY, pipeline="agentic_full", top_k=4
            )
        # Query still completes successfully
        self.assertIn(result["diagnostics"]["answer_status"], {"supported", "partial"})

    def test_finish_exception_falls_back_to_no_url(self) -> None:
        class BrokenFinish:
            @contextmanager
            def span(self, name: str, **attrs: Any) -> Iterator[None]:
                yield None

            def set_tag(self, key: str, value: Any) -> None:
                pass

            def finish(self, diagnostics: dict[str, Any]) -> str | None:
                raise RuntimeError("finish boom")

        class BrokenFinishBackend:
            name = "brokenfinish"

            def start_trace(self, query: str, tags: dict[str, Any]) -> Any:
                return BrokenFinish()

        with _registered_backend("brokenfinish", BrokenFinishBackend()):
            result = run_rag_query(
                self.index, ANSWERABLE_QUERY, pipeline="agentic_full", top_k=4
            )
        diag = result["diagnostics"]
        self.assertIsNone(diag["trace_url"])
        self.assertIsNotNone(diag["trace_error"])
        self.assertIn("finish", diag["trace_error"])

    def test_unknown_backend_name_falls_back(self) -> None:
        os.environ["BIDMATE_TRACE_BACKEND"] = "does-not-exist"
        try:
            result = run_rag_query(
                self.index, ANSWERABLE_QUERY, pipeline="agentic_full", top_k=4
            )
        finally:
            os.environ.pop("BIDMATE_TRACE_BACKEND", None)
        diag = result["diagnostics"]
        self.assertEqual(diag["trace_backend"], "none")
        self.assertIsNotNone(diag["trace_unavailable_reason"])
        self.assertIn("unknown_backend", diag["trace_unavailable_reason"])

    # ------------------------------------------------------------------
    # Invariant 4: missing optional dep
    # ------------------------------------------------------------------

    def test_missing_langfuse_dep_falls_back(self) -> None:
        # Make `import langfuse` fail by shadowing the module.
        saved_modules: dict[str, Any] = {}
        for k in list(sys.modules.keys()):
            if k == "langfuse" or k.startswith("langfuse."):
                saved_modules[k] = sys.modules.pop(k)
        sys.modules["langfuse"] = None  # type: ignore[assignment]
        os.environ["BIDMATE_TRACE_BACKEND"] = "langfuse"
        os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-test"
        os.environ["LANGFUSE_SECRET_KEY"] = "sk-test"
        try:
            result = run_rag_query(
                self.index, ANSWERABLE_QUERY, pipeline="agentic_full", top_k=4
            )
        finally:
            sys.modules.pop("langfuse", None)
            for k, v in saved_modules.items():
                sys.modules[k] = v
            for k in ("BIDMATE_TRACE_BACKEND", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
                os.environ.pop(k, None)
        diag = result["diagnostics"]
        self.assertEqual(diag["trace_backend"], "none")
        self.assertIsNotNone(diag["trace_unavailable_reason"])
        self.assertIn("missing_dependency", diag["trace_unavailable_reason"])

    def test_missing_credentials_falls_back(self) -> None:
        for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
            os.environ.pop(k, None)
        os.environ["BIDMATE_TRACE_BACKEND"] = "langfuse"
        try:
            result = run_rag_query(
                self.index, ANSWERABLE_QUERY, pipeline="agentic_full", top_k=4
            )
        finally:
            os.environ.pop("BIDMATE_TRACE_BACKEND", None)
        diag = result["diagnostics"]
        self.assertEqual(diag["trace_backend"], "none")
        self.assertIsNotNone(diag["trace_unavailable_reason"])
        self.assertIn("missing_credentials", diag["trace_unavailable_reason"])

    # ------------------------------------------------------------------
    # Invariant 5: clarification early-exit still finishes the trace
    # ------------------------------------------------------------------

    def test_metadata_clarification_path_finishes_trace(self) -> None:
        # An ambiguous bare reference triggers the metadata-clarification
        # early-exit branch in run_rag_query. The trace must still be
        # finished and the trace_backend recorded.
        backend = _RecordingBackend()
        with _registered_backend("recording", backend):
            result = run_rag_query(
                self.index, "그 기관의 보안 통제 요구사항은?",
                pipeline="agentic_full", top_k=4,
            )
        diag = result["diagnostics"]
        self.assertEqual(diag["trace_backend"], "recording")
        # Even on early-exit paths, finish() runs
        if backend.last_trace is not None:
            self.assertTrue(backend.last_trace.finished)


class ResolveBackendUnitTest(unittest.TestCase):
    """Direct contract tests on ``resolve_trace_backend``."""

    def test_default_is_none(self) -> None:
        with _unset_trace_env():
            inst, name, reason = rag_observability.resolve_trace_backend()
        self.assertEqual(name, "none")
        self.assertIsNone(reason)

    def test_unknown_backend_returns_none_with_reason(self) -> None:
        inst, name, reason = rag_observability.resolve_trace_backend("ghost")
        self.assertEqual(name, "none")
        self.assertIsNotNone(reason)
        self.assertIn("unknown_backend:ghost", reason or "")

    def test_explicit_none_skips_env(self) -> None:
        os.environ["BIDMATE_TRACE_BACKEND"] = "langfuse"
        try:
            inst, name, _ = rag_observability.resolve_trace_backend("none")
        finally:
            os.environ.pop("BIDMATE_TRACE_BACKEND", None)
        self.assertEqual(name, "none")


if __name__ == "__main__":
    unittest.main()
