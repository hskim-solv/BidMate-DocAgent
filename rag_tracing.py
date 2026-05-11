#!/usr/bin/env python3
"""Trace backend dispatch for ADR 0012 (LLM-Ops observability).

This module is the *delivery contract* between ``rag_core.run_rag_query``
and an external trace surface. It is **observation-only**: no Tracer
method's return value is read by the pipeline, and no backend exception
is ever allowed to escape — the answer path is the product, the trace
is diagnostic.

Backends (``BIDMATE_TRACE_BACKEND``):

* ``none`` (default) — no-op tracer. Zero overhead, zero imports. Used
  by ``make smoke``, public CI, and any deploy without an observability
  stack.
* ``otel`` — emit spans via the OpenTelemetry SDK. Exporter is
  configurable via ``BIDMATE_TRACE_OTEL_EXPORTER`` (``console`` default;
  ``otlp_http`` for collectors like Tempo, Jaeger, Honeycomb, Datadog,
  Grafana). Vendor-neutral: any OTel-compatible APM ingests these.
* ``langfuse_self_hosted`` — emit one trace per query to a self-hosted
  LangFuse instance (registered in PR-B). Exposes a ``View trace`` URL
  that the Streamlit demo renders inline.

Span tree per ``run_rag_query``:

    run_rag_query                         tags: pipeline, prompt_profile, embedding_backend, ...
    ├── query_analysis                    attrs: query_type, entities_count, ...
    ├── context_resolution                attrs: status, source, ...
    ├── retrieval_attempt[i]              attrs: attempt_index, stage, verified, verification_reasons
    │   ├── retrieve                      attrs: top_k, candidate_count, retrieval_mode, ...
    │   └── verify                        attrs: verifier_retry, allow_partial_topic, verified, ...
    ├── (retrieval_attempt[i+1] ...)      when verifier_retry kicked in (ADR 0004)
    ├── answer_generation                 attrs: answer_status, claim_count, citation_count, abstained
    └── synthesis                         attrs: synthesis_backend, fell_back, fallback_reason,
                                                 tokens_in, tokens_out
                                          only when prompt_profile == "llm_synthesis" and not abstained

The OTel attribute namespace is ``bidmate.<snake_case>`` to avoid
collisions with reserved OTel keys (``http.*`` / ``db.*``). LangFuse
top-level tags are pipeline / prompt_profile / embedding_backend per
issue #165; everything else flows into ``metadata``.

Hosted LangFuse Cloud is **not** registered here. Per ADR 0005's commit
boundary, per-case query text must not leave the local surface unless
that boundary is explicitly widened by a follow-up ADR. See ADR 0012
``Upgrade paths``.
"""
from __future__ import annotations

import os
import sys
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, ContextManager, Protocol

TRACE_SCHEMA_VERSION = 1

ENV_BACKEND = "BIDMATE_TRACE_BACKEND"
ENV_OTEL_EXPORTER = "BIDMATE_TRACE_OTEL_EXPORTER"
ENV_OTEL_ENDPOINT = "BIDMATE_TRACE_OTEL_ENDPOINT"
ENV_OTEL_SERVICE = "BIDMATE_TRACE_OTEL_SERVICE"

DEFAULT_BACKEND = "none"
DEFAULT_OTEL_EXPORTER = "console"
DEFAULT_OTEL_ENDPOINT = "http://localhost:4318/v1/traces"
DEFAULT_OTEL_SERVICE = "bidmate-docagent"

OTEL_ATTR_PREFIX = "bidmate."

_WARN_LOCK = threading.Lock()
_WARNED: set[str] = set()


def _warn_once(key: str, msg: str) -> None:
    """Emit a single stderr line per (process, key). Tracing failures must
    not flood logs and must never raise."""
    with _WARN_LOCK:
        if key in _WARNED:
            return
        _WARNED.add(key)
    try:
        sys.stderr.write(f"[bidmate.tracing] {msg}\n")
    except Exception:
        pass


def new_trace_id() -> str:
    """Mint a 32-char hex trace id. Stable shape for downstream consumers."""
    return uuid.uuid4().hex


@dataclass
class SpanHandle:
    """Mutable handle yielded by ``Tracer.span``.

    Stages call ``set_attributes(**kw)`` to attach late-bound info
    (e.g. token counts after the synthesis backend returns). For
    ``NoneTracer`` and any failed backend path, ``_setter`` is None and
    calls are silently dropped.
    """

    _setter: Callable[[dict[str, Any]], None] | None = None

    def set_attributes(self, **kw: Any) -> None:
        if self._setter is None or not kw:
            return
        try:
            self._setter(kw)
        except Exception as exc:
            _warn_once(
                "span_set_attributes",
                f"backend error suppressed in set_attributes: {type(exc).__name__}: {exc}",
            )


class Tracer(Protocol):
    """The four-method contract every backend implements."""

    schema_version: int
    backend_name: str

    def start_trace(
        self,
        *,
        trace_id: str,
        name: str,
        input_payload: dict[str, Any],
        tags: dict[str, Any],
    ) -> None: ...

    def span(
        self,
        *,
        trace_id: str,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> ContextManager[SpanHandle]: ...

    def finish_trace(
        self,
        *,
        trace_id: str,
        output_payload: dict[str, Any],
        attributes: dict[str, Any] | None = None,
    ) -> None: ...

    def get_trace_url(self, trace_id: str) -> str | None: ...


class NoneTracer:
    """Default backend: no-op everything, zero overhead, zero imports."""

    schema_version: int = TRACE_SCHEMA_VERSION
    backend_name: str = "none"

    def start_trace(self, *, trace_id, name, input_payload, tags):  # noqa: D401
        return None

    @contextmanager
    def span(self, *, trace_id, name, attributes=None):
        yield SpanHandle()

    def finish_trace(self, *, trace_id, output_payload, attributes=None):
        return None

    def get_trace_url(self, trace_id):
        return None


def _coerce_otel_value(v: Any) -> Any:
    """OTel attribute values must be str / bool / int / float or list of same."""
    if isinstance(v, bool) or isinstance(v, (str, int, float)):
        return v
    if isinstance(v, (list, tuple)) and all(
        isinstance(x, (str, bool, int, float)) for x in v
    ):
        return list(v)
    if v is None:
        return ""
    return str(v)


def _otel_attrs(attrs: dict[str, Any], prefix: str = OTEL_ATTR_PREFIX) -> dict[str, Any]:
    return {f"{prefix}{k}": _coerce_otel_value(v) for k, v in attrs.items()}


class OtelTracer:
    """OpenTelemetry backend.

    Constructs a private ``TracerProvider`` (does NOT touch the OTel
    global provider, so this never collides with other instrumentation
    a user may have installed). Each instance owns its own provider +
    exporter + tracer.

    The ``exporter`` kwarg is for tests (e.g. ``InMemorySpanExporter``);
    production callers leave it None and the provider builds the
    exporter from ``BIDMATE_TRACE_OTEL_*`` env vars.
    """

    schema_version: int = TRACE_SCHEMA_VERSION
    backend_name: str = "otel"

    def __init__(
        self,
        *,
        exporter: Any = None,
        service_name: str | None = None,
    ) -> None:
        # Lazy-import: opentelemetry-sdk is NOT in requirements.txt; only
        # callers that actually opt into BIDMATE_TRACE_BACKEND=otel pay
        # the import cost (and the install cost — see docs/observability.md).
        from opentelemetry import trace as otel_trace  # type: ignore[import-not-found]
        from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # type: ignore[import-not-found]

        self._otel_trace = otel_trace
        resolved_service = (
            service_name
            or os.environ.get(ENV_OTEL_SERVICE)
            or DEFAULT_OTEL_SERVICE
        )
        resource = Resource.create({"service.name": resolved_service})
        provider = TracerProvider(resource=resource)
        if exporter is None:
            exporter = self._build_exporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        self._provider = provider
        self._tracer = provider.get_tracer("bidmate-docagent")
        self._traces: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _build_exporter() -> Any:
        kind = (os.environ.get(ENV_OTEL_EXPORTER) or DEFAULT_OTEL_EXPORTER).lower()
        if kind == "otlp_http":
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found]
                    OTLPSpanExporter,
                )

                endpoint = os.environ.get(ENV_OTEL_ENDPOINT) or DEFAULT_OTEL_ENDPOINT
                return OTLPSpanExporter(endpoint=endpoint)
            except ImportError:
                _warn_once(
                    "otel_otlp_missing",
                    "BIDMATE_TRACE_OTEL_EXPORTER=otlp_http requested but "
                    "opentelemetry-exporter-otlp-proto-http is not installed; "
                    "falling back to ConsoleSpanExporter.",
                )
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter  # type: ignore[import-not-found]

        return ConsoleSpanExporter()

    def start_trace(self, *, trace_id, name, input_payload, tags):
        try:
            from opentelemetry import context as otel_ctx  # type: ignore[import-not-found]

            attrs: dict[str, Any] = {f"{OTEL_ATTR_PREFIX}trace_id": trace_id}
            attrs.update(_otel_attrs(tags or {}))
            attrs.update(
                _otel_attrs(input_payload or {}, prefix=f"{OTEL_ATTR_PREFIX}input.")
            )
            root_span = self._tracer.start_span(name, attributes=attrs)
            ctx_token = otel_ctx.attach(self._otel_trace.set_span_in_context(root_span))
            with self._lock:
                self._traces[trace_id] = {
                    "root": root_span,
                    "token": ctx_token,
                }
        except Exception as exc:
            _warn_once(
                "otel_start_trace",
                f"OtelTracer.start_trace failed: {type(exc).__name__}: {exc}",
            )
            with self._lock:
                self._traces[trace_id] = {"poisoned": True}

    @contextmanager
    def span(self, *, trace_id, name, attributes=None):
        with self._lock:
            state = self._traces.get(trace_id, {})
        if state.get("poisoned") or "root" not in state:
            yield SpanHandle()
            return
        try:
            attrs = _otel_attrs(attributes or {})
            with self._tracer.start_as_current_span(name, attributes=attrs) as otel_span:

                def _setter(kw: dict[str, Any]) -> None:
                    for ok, ov in _otel_attrs(kw).items():
                        otel_span.set_attribute(ok, ov)

                yield SpanHandle(_setter=_setter)
        except Exception as exc:
            _warn_once(
                f"otel_span:{name}",
                f"OtelTracer.span({name}) failed: {type(exc).__name__}: {exc}",
            )
            yield SpanHandle()

    def finish_trace(self, *, trace_id, output_payload, attributes=None):
        try:
            with self._lock:
                state = self._traces.pop(trace_id, None)
            if not state or state.get("poisoned"):
                return
            from opentelemetry import context as otel_ctx  # type: ignore[import-not-found]

            root = state["root"]
            for ok, ov in _otel_attrs(
                output_payload or {}, prefix=f"{OTEL_ATTR_PREFIX}output."
            ).items():
                root.set_attribute(ok, ov)
            for ok, ov in _otel_attrs(attributes or {}).items():
                root.set_attribute(ok, ov)
            root.end()
            otel_ctx.detach(state["token"])
            try:
                self._provider.force_flush(timeout_millis=2000)
            except Exception:
                pass
        except Exception as exc:
            _warn_once(
                "otel_finish_trace",
                f"OtelTracer.finish_trace failed: {type(exc).__name__}: {exc}",
            )

    def get_trace_url(self, trace_id):
        return None


_BACKENDS: dict[str, type] = {
    "none": NoneTracer,
    "otel": OtelTracer,
}


def make_tracer(backend: str | None = None) -> Tracer:
    """Resolve ``BIDMATE_TRACE_BACKEND`` and return a Tracer.

    Unknown name or constructor failure → ``NoneTracer`` plus a single
    stderr warning. This is the only seam ``rag_core.run_rag_query``
    uses; failing closed here is the load-bearing property.
    """
    name = (backend or os.environ.get(ENV_BACKEND) or DEFAULT_BACKEND).lower()
    cls = _BACKENDS.get(name)
    if cls is None:
        _warn_once(
            f"unknown_backend:{name}",
            f"Unknown BIDMATE_TRACE_BACKEND={name!r}; valid: "
            f"{', '.join(sorted(_BACKENDS))}; falling back to 'none'.",
        )
        return NoneTracer()
    try:
        return cls()
    except Exception as exc:
        _warn_once(
            f"ctor_failed:{name}",
            f"{cls.__name__}() construction failed "
            f"({type(exc).__name__}: {exc}); falling back to 'none'.",
        )
        return NoneTracer()


__all__ = [
    "TRACE_SCHEMA_VERSION",
    "ENV_BACKEND",
    "ENV_OTEL_EXPORTER",
    "ENV_OTEL_ENDPOINT",
    "ENV_OTEL_SERVICE",
    "DEFAULT_BACKEND",
    "DEFAULT_OTEL_EXPORTER",
    "DEFAULT_OTEL_ENDPOINT",
    "DEFAULT_OTEL_SERVICE",
    "OTEL_ATTR_PREFIX",
    "SpanHandle",
    "Tracer",
    "NoneTracer",
    "OtelTracer",
    "make_tracer",
    "new_trace_id",
]
