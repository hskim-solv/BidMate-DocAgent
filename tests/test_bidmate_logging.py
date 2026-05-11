"""Contract test for ``bidmate_logging``.

Locks down the env-var-driven setup and the JSON/text formatter
output shape. The pipeline emits ``query_start``/``query_complete``
records via ``log_query_event``; downstream log aggregation depends
on the keys being stable.
"""

from __future__ import annotations

import io
import json
import logging

import pytest

import bidmate_logging


@pytest.fixture(autouse=True)
def _reset_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip the cached root setup between tests so env vars take effect."""
    monkeypatch.delenv(bidmate_logging.ENV_LEVEL, raising=False)
    monkeypatch.delenv(bidmate_logging.ENV_FORMAT, raising=False)
    monkeypatch.delenv(bidmate_logging.ENV_STREAM, raising=False)
    root = logging.getLogger(bidmate_logging.LOGGER_ROOT)
    for h in list(root.handlers):
        root.removeHandler(h)
    if hasattr(root, "_bidmate_configured"):
        delattr(root, "_bidmate_configured")
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
    if hasattr(root, "_bidmate_configured"):
        delattr(root, "_bidmate_configured")


def _capture(_logger: logging.Logger) -> io.StringIO:
    """Attach an extra StreamHandler on the bidmate root for capture.

    Records emitted by any child propagate to the root, so capturing
    on the root is sufficient and matches the formatter set by
    ``get_logger`` (which only installs a handler at the root).
    """
    root = logging.getLogger(bidmate_logging.LOGGER_ROOT)
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(root.handlers[0].formatter)
    root.addHandler(handler)
    return buf


def test_json_format_promotes_extra_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(bidmate_logging.ENV_FORMAT, "json")
    logger = bidmate_logging.get_logger("rag_core")
    buf = _capture(logger)
    bidmate_logging.log_query_event(
        logger,
        "query_complete",
        query_hash="abcd1234",
        latency_ms=42.5,
        status="supported",
        abstained=False,
    )
    line = buf.getvalue().strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "bidmate.rag_core"
    assert payload["msg"] == "query_complete"
    assert payload["event"] == "query_complete"
    assert payload["query_hash"] == "abcd1234"
    assert payload["latency_ms"] == 42.5
    assert payload["status"] == "supported"
    assert payload["abstained"] is False
    assert "ts" in payload


def test_text_format_renders_kv_pairs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(bidmate_logging.ENV_FORMAT, "text")
    logger = bidmate_logging.get_logger("rag_core")
    buf = _capture(logger)
    bidmate_logging.log_query_event(logger, "query_start", pipeline="naive_baseline", top_k=5)
    rendered = buf.getvalue()
    assert "query_start" in rendered
    assert "pipeline='naive_baseline'" in rendered
    assert "top_k=5" in rendered


def test_default_level_is_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(bidmate_logging.ENV_LEVEL, raising=False)
    logger = bidmate_logging.get_logger("rag_core")
    assert logger.getEffectiveLevel() == logging.INFO


def test_level_env_var_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(bidmate_logging.ENV_LEVEL, "WARNING")
    logger = bidmate_logging.get_logger("rag_core")
    assert logger.getEffectiveLevel() == logging.WARNING


def test_invalid_level_falls_back_to_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(bidmate_logging.ENV_LEVEL, "NOT_A_LEVEL")
    logger = bidmate_logging.get_logger("rag_core")
    assert logger.getEffectiveLevel() == logging.INFO


def test_get_logger_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(bidmate_logging.ENV_FORMAT, "json")
    first = bidmate_logging.get_logger("rag_core")
    second = bidmate_logging.get_logger("rag_core")
    assert first is second
    root = logging.getLogger(bidmate_logging.LOGGER_ROOT)
    # Only the initial handler — re-calling get_logger does not stack handlers.
    assert len(root.handlers) == 1


def test_non_json_serializable_field_is_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(bidmate_logging.ENV_FORMAT, "json")
    logger = bidmate_logging.get_logger("rag_core")
    buf = _capture(logger)

    class Marker:
        def __repr__(self) -> str:
            return "MARKER_INSTANCE"

    bidmate_logging.log_query_event(logger, "query_complete", obj=Marker())
    payload = json.loads(buf.getvalue().strip().splitlines()[-1])
    assert payload["obj"] == "MARKER_INSTANCE"
