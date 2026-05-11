#!/usr/bin/env python3
"""Structured logging entry point for BidMate-DocAgent.

Single source of logger configuration so the pipeline can emit
machine-parseable events without each call-site reinventing setup.
Mirrors the additive, fail-closed shape from ADR 0013 (observability):
configuration is via env vars, defaults are zero-overhead, and any
formatter failure falls back to the standard ``logging`` defaults.

Env vars:

* ``BIDMATE_LOG_LEVEL`` — ``DEBUG``/``INFO``/``WARNING``/``ERROR``.
  Default ``INFO``. Invalid values fall back to ``INFO``.
* ``BIDMATE_LOG_FORMAT`` — ``text`` (default, human-readable single
  line) or ``json`` (one JSON object per line, suited for log
  aggregation: CloudLogging, ELK, Datadog).
* ``BIDMATE_LOG_STREAM`` — ``stderr`` (default) or ``stdout``.

``log_query_event(logger, event, **fields)`` is a convenience that
emits a single ``INFO`` record carrying the ``event`` name and
arbitrary structured fields — the JSON formatter promotes them to
top-level keys, the text formatter renders them as ``key=value``
pairs. This is the recommended call site for stage-summary events.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

ENV_LEVEL = "BIDMATE_LOG_LEVEL"
ENV_FORMAT = "BIDMATE_LOG_FORMAT"
ENV_STREAM = "BIDMATE_LOG_STREAM"

DEFAULT_LEVEL = "INFO"
DEFAULT_FORMAT = "text"
DEFAULT_STREAM = "stderr"

LOGGER_ROOT = "bidmate"
_RESERVED_FIELDS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime",
}


class _JsonFormatter(logging.Formatter):
    """One JSON object per record, with extra fields promoted to top-level.

    Reserved record attributes (the standard ``LogRecord`` fields) are
    suppressed so the output stays compact. Anything passed via
    ``logger.info("...", extra={...})`` is included verbatim.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_FIELDS or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        try:
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return super().format(record)


class _TextFormatter(logging.Formatter):
    """Human-friendly single-line format with structured fields appended."""

    DEFAULT_FMT = "%(asctime)s %(levelname)-5s %(name)s: %(message)s"

    def __init__(self) -> None:
        super().__init__(fmt=self.DEFAULT_FMT, datefmt="%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = []
        for key, value in record.__dict__.items():
            if key in _RESERVED_FIELDS or key.startswith("_"):
                continue
            extras.append(f"{key}={value!r}")
        if extras:
            return f"{base} {' '.join(extras)}"
        return base


def _resolve_level() -> int:
    name = (os.environ.get(ENV_LEVEL) or DEFAULT_LEVEL).upper()
    return getattr(logging, name, logging.INFO)


def _resolve_stream():
    target = (os.environ.get(ENV_STREAM) or DEFAULT_STREAM).lower()
    return sys.stdout if target == "stdout" else sys.stderr


def _resolve_formatter() -> logging.Formatter:
    fmt = (os.environ.get(ENV_FORMAT) or DEFAULT_FORMAT).lower()
    return _JsonFormatter() if fmt == "json" else _TextFormatter()


def _configure_root_once() -> logging.Logger:
    root = logging.getLogger(LOGGER_ROOT)
    if getattr(root, "_bidmate_configured", False):
        return root
    root.setLevel(_resolve_level())
    root.propagate = False
    handler = logging.StreamHandler(_resolve_stream())
    handler.setFormatter(_resolve_formatter())
    root.addHandler(handler)
    root._bidmate_configured = True  # type: ignore[attr-defined]
    return root


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under the ``bidmate`` namespace.

    Idempotent: first call configures the root handler/formatter from
    env vars; subsequent calls just return child loggers.
    """
    _configure_root_once()
    if not name or name == LOGGER_ROOT:
        return logging.getLogger(LOGGER_ROOT)
    return logging.getLogger(f"{LOGGER_ROOT}.{name}")


def log_query_event(
    logger: logging.Logger,
    event: str,
    /,
    **fields: Any,
) -> None:
    """Emit a single structured event at INFO level.

    ``event`` is a short snake_case identifier (``query_start``,
    ``query_complete``, ``verifier_retry``, ...). All other kwargs are
    attached as extra fields — JSON formatter surfaces them as
    top-level keys, text formatter renders them as ``k=v`` suffixes.
    """
    logger.info(event, extra={"event": event, **fields})


__all__ = [
    "ENV_LEVEL",
    "ENV_FORMAT",
    "ENV_STREAM",
    "DEFAULT_LEVEL",
    "DEFAULT_FORMAT",
    "DEFAULT_STREAM",
    "LOGGER_ROOT",
    "get_logger",
    "log_query_event",
]
