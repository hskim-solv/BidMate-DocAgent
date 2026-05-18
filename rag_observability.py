#!/usr/bin/env python3
"""LLM Ops observability backends for ADR 0013.

Wraps the existing ``rag_core.run_rag_query`` pipeline stages in trace
spans without changing pipeline behavior. Trace data lives in
``diagnostics.trace_*`` keys; the ADR 0003 answer contract is preserved
by construction. Mirrors the additive, fail-closed, pluggable-backend
pattern from ADR 0007 (LLM synthesis) — see ``rag_synthesis.py``.

Backends (``BIDMATE_TRACE_BACKEND``):

* ``none`` (default) — zero-overhead noop. No SDK requirement. The
  query path runs identically to a build without this module.
* ``langfuse`` — LangFuse self-hosted or cloud. Requires
  ``LANGFUSE_PUBLIC_KEY``, ``LANGFUSE_SECRET_KEY``; optional
  ``LANGFUSE_HOST``. Trace URLs surface in ``diagnostics.trace_url``.
* ``otel`` — OpenTelemetry, vendor-agnostic. Honors the standard
  ``OTEL_EXPORTER_OTLP_ENDPOINT`` / ``OTEL_SERVICE_NAME`` SDK env
  vars. Optional ``BIDMATE_TRACE_URL_TEMPLATE`` renders a clickable
  URL (e.g. ``https://ui.honeycomb.io/.../trace?trace_id={trace_id}``).

Any failure — missing optional dep, missing credentials, SDK
exception, span/finish raise — falls back to the noop backend and
captures a reason in ``diagnostics.trace_unavailable_reason`` or
``diagnostics.trace_error``. ``run_rag_query`` always succeeds.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager, nullcontext
from typing import Any, Callable, Iterator, Protocol

OBSERVABILITY_SCHEMA_VERSION = 1

ENV_TRACE_BACKEND = "BIDMATE_TRACE_BACKEND"
ENV_TRACE_URL_TEMPLATE = "BIDMATE_TRACE_URL_TEMPLATE"
ENV_LANGFUSE_PUBLIC_KEY = "LANGFUSE_PUBLIC_KEY"
ENV_LANGFUSE_SECRET_KEY = "LANGFUSE_SECRET_KEY"
ENV_LANGFUSE_HOST = "LANGFUSE_HOST"
ENV_OTEL_ENDPOINT = "OTEL_EXPORTER_OTLP_ENDPOINT"
ENV_OTEL_SERVICE_NAME = "OTEL_SERVICE_NAME"

DEFAULT_BACKEND = "none"
DEFAULT_OTEL_SERVICE_NAME = "bidmate-docagent"
DEFAULT_LANGFUSE_HOST = "https://cloud.langfuse.com"


class TraceContext(Protocol):
    """Per-query trace handle. Always usable — span()/set_tag()/finish() never raise."""

    def span(self, name: str, **attrs: Any) -> Any: ...
    def set_tag(self, key: str, value: Any) -> None: ...
    def finish(self, diagnostics: dict[str, Any]) -> str | None: ...


class TraceBackend(Protocol):
    """Factory for per-query ``TraceContext`` instances."""

    name: str

    def start_trace(self, query: str, tags: dict[str, Any]) -> TraceContext: ...


# ---------------------------------------------------------------------------
# Noop backend (default; zero overhead)
# ---------------------------------------------------------------------------


class _NoopTraceContext:
    """Implements ``TraceContext`` with no side effects.

    Used by the ``none`` backend and as the fail-closed fallback when
    any other backend errors. ``span()`` returns a ``nullcontext`` so
    the ``_StageTimer`` wrapping is free of cost.
    """

    __slots__ = ()

    def span(self, name: str, **attrs: Any) -> Any:
        return nullcontext()

    def set_tag(self, key: str, value: Any) -> None:
        return None

    def finish(self, diagnostics: dict[str, Any]) -> str | None:
        return None


class _NoneBackend:
    name = "none"

    def start_trace(self, query: str, tags: dict[str, Any]) -> TraceContext:
        return _NoopTraceContext()


# ---------------------------------------------------------------------------
# LangFuse backend
# ---------------------------------------------------------------------------


class _LangfuseTraceContext:
    """Wraps a langfuse trace object with the ``TraceContext`` protocol.

    Each ``span()`` opens a child span on the underlying trace; SDK
    exceptions inside spans are swallowed so a misbehaving exporter
    can never break the query path. ``finish()`` calls ``flush`` and
    returns the trace URL.
    """

    def __init__(self, client: Any, trace: Any) -> None:
        self._client = client
        self._trace = trace

    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[None]:
        sp = None
        started = time.perf_counter()
        try:
            sp = self._trace.span(name=name, input=attrs or None)
        except Exception:
            sp = None
        try:
            yield None
        finally:
            if sp is not None:
                try:
                    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
                    sp.end(output={"latency_ms": elapsed_ms})
                except Exception:
                    pass

    def set_tag(self, key: str, value: Any) -> None:
        try:
            self._trace.update(metadata={key: value})
        except Exception:
            pass

    def finish(self, diagnostics: dict[str, Any]) -> str | None:
        try:
            self._trace.update(
                output={
                    "answer_status": diagnostics.get("answer_status"),
                    "latency_ms": diagnostics.get("latency_ms"),
                    "abstained": diagnostics.get("abstained"),
                },
            )
        except Exception:
            pass
        try:
            self._client.flush()
        except Exception:
            pass
        try:
            return self._trace.get_trace_url()
        except Exception:
            return None


class _LangfuseBackend:
    name = "langfuse"

    def __init__(self, client: Any) -> None:
        self._client = client

    def start_trace(self, query: str, tags: dict[str, Any]) -> TraceContext:
        try:
            trace = self._client.trace(
                name="rag_query",
                input={"query": query},
                metadata=dict(tags),
            )
        except Exception:
            return _NoopTraceContext()
        return _LangfuseTraceContext(self._client, trace)


def _build_langfuse_backend() -> TraceBackend:
    """Construct ``_LangfuseBackend`` or return ``_NoneBackend`` on any failure.

    Failure modes (each results in fail-closed noop):

    * ``langfuse`` package not installed
    * ``LANGFUSE_PUBLIC_KEY`` or ``LANGFUSE_SECRET_KEY`` missing
    * ``Langfuse(...)`` constructor raises
    """
    public_key = os.environ.get(ENV_LANGFUSE_PUBLIC_KEY)
    secret_key = os.environ.get(ENV_LANGFUSE_SECRET_KEY)
    if not public_key or not secret_key:
        return _make_unavailable("missing_credentials:langfuse")
    try:
        from langfuse import Langfuse  # type: ignore[import-not-found]
    except Exception as exc:
        return _make_unavailable(f"missing_dependency:langfuse:{type(exc).__name__}")
    try:
        client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            # Langfuse 4.x docs recommend `base_url=`; `host=` remains a
            # backwards-compatible alias today but may be deprecated in
            # a future major. Verified against langfuse 4.6.1 (issue #976).
            base_url=os.environ.get(ENV_LANGFUSE_HOST) or DEFAULT_LANGFUSE_HOST,
        )
    except Exception as exc:
        return _make_unavailable(f"backend_init_error:langfuse:{type(exc).__name__}")
    return _LangfuseBackend(client)


# ---------------------------------------------------------------------------
# OpenTelemetry backend
# ---------------------------------------------------------------------------


class _OtelTraceContext:
    """Wraps OTel ``Tracer`` + root span. Each ``span()`` opens a child."""

    def __init__(self, tracer: Any, root_span: Any, trace_id_hex: str | None) -> None:
        self._tracer = tracer
        self._root = root_span
        self._trace_id_hex = trace_id_hex
        self._url_template = os.environ.get(ENV_TRACE_URL_TEMPLATE)

    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[None]:
        cm = None
        try:
            cm = self._tracer.start_as_current_span(name)
            sp = cm.__enter__()
            try:
                for key, value in (attrs or {}).items():
                    try:
                        sp.set_attribute(key, value)
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            cm = None
        try:
            yield None
        finally:
            if cm is not None:
                try:
                    cm.__exit__(None, None, None)
                except Exception:
                    pass

    def set_tag(self, key: str, value: Any) -> None:
        try:
            self._root.set_attribute(key, value)
        except Exception:
            pass

    def finish(self, diagnostics: dict[str, Any]) -> str | None:
        try:
            self._root.set_attribute("answer_status", str(diagnostics.get("answer_status") or ""))
            self._root.set_attribute("latency_ms", float(diagnostics.get("latency_ms") or 0.0))
            self._root.set_attribute("abstained", bool(diagnostics.get("abstained")))
        except Exception:
            pass
        try:
            self._root.end()
        except Exception:
            pass
        if not self._trace_id_hex or not self._url_template:
            return None
        try:
            return self._url_template.format(trace_id=self._trace_id_hex)
        except Exception:
            return None


class _OtelBackend:
    name = "otel"

    def __init__(self, tracer: Any) -> None:
        self._tracer = tracer

    def start_trace(self, query: str, tags: dict[str, Any]) -> TraceContext:
        try:
            span = self._tracer.start_span("rag_query")
            for key, value in tags.items():
                try:
                    span.set_attribute(key, value)
                except Exception:
                    pass
            try:
                ctx = span.get_span_context()
                trace_id_hex = format(ctx.trace_id, "032x") if ctx and ctx.trace_id else None
            except Exception:
                trace_id_hex = None
        except Exception:
            return _NoopTraceContext()
        return _OtelTraceContext(self._tracer, span, trace_id_hex)


def _build_otel_backend() -> TraceBackend:
    """Construct ``_OtelBackend`` or fail closed.

    Uses the SDK's standard env vars (``OTEL_EXPORTER_OTLP_ENDPOINT``,
    ``OTEL_SERVICE_NAME``) — we do not re-export the world here.
    """
    try:
        from opentelemetry import trace as otel_trace  # type: ignore[import-not-found]
        from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore[import-not-found]
    except Exception as exc:
        return _make_unavailable(f"missing_dependency:opentelemetry:{type(exc).__name__}")
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found]
            OTLPSpanExporter,
        )
    except Exception as exc:
        return _make_unavailable(
            f"missing_dependency:opentelemetry-exporter-otlp:{type(exc).__name__}"
        )
    service_name = os.environ.get(ENV_OTEL_SERVICE_NAME) or DEFAULT_OTEL_SERVICE_NAME
    try:
        provider = otel_trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            otel_trace.set_tracer_provider(provider)
        tracer = otel_trace.get_tracer(service_name)
    except Exception as exc:
        return _make_unavailable(f"backend_init_error:opentelemetry:{type(exc).__name__}")
    return _OtelBackend(tracer)


# ---------------------------------------------------------------------------
# Fail-closed plumbing
# ---------------------------------------------------------------------------


class _UnavailableBackend:
    """Sentinel returned by builder functions when a real backend can't be made.

    ``resolve_trace_backend`` swaps this for ``_NoneBackend`` while
    propagating ``_unavailable_reason`` for the diagnostics dict.
    """

    name = "none"

    def __init__(self, reason: str) -> None:
        self._unavailable_reason = reason

    def start_trace(self, query: str, tags: dict[str, Any]) -> TraceContext:
        return _NoopTraceContext()


def _make_unavailable(reason: str) -> TraceBackend:
    return _UnavailableBackend(reason)


# ---------------------------------------------------------------------------
# Backend registry + resolver
# ---------------------------------------------------------------------------


_BACKENDS: dict[str, Callable[[], TraceBackend]] = {
    "none": _NoneBackend,
    "langfuse": _build_langfuse_backend,
    "otel": _build_otel_backend,
}


def resolve_trace_backend(
    backend: str | None = None,
) -> tuple[TraceBackend, str, str | None]:
    """Resolve a backend instance by name with fail-closed fallback.

    Returns ``(instance, resolved_name, unavailable_reason)``. Callers
    should treat ``unavailable_reason`` as informational — the returned
    instance is always safe to call.
    """
    requested = (backend or os.environ.get(ENV_TRACE_BACKEND) or DEFAULT_BACKEND).lower()
    factory = _BACKENDS.get(requested)
    if factory is None:
        return _NoneBackend(), "none", f"unknown_backend:{requested}"
    try:
        instance = factory()
    except Exception as exc:
        return (
            _NoneBackend(),
            "none",
            f"backend_init_error:{requested}:{type(exc).__name__}:{str(exc)[:120]}",
        )
    reason = getattr(instance, "_unavailable_reason", None)
    if reason:
        return _NoneBackend(), "none", str(reason)
    return instance, requested, None


__all__ = [
    "OBSERVABILITY_SCHEMA_VERSION",
    "ENV_TRACE_BACKEND",
    "DEFAULT_BACKEND",
    "TraceContext",
    "TraceBackend",
    "resolve_trace_backend",
]
