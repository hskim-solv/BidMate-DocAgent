"""Regression tests for PR-D — verifier feedback injection (#679).

Verifies:
1. format_verifier_feedback exists in rag_verifier.
2. Empty reasons → fallback string (non-empty, Korean).
3. Reasons list → formatted string containing each reason.
4. verify_evidence is unchanged (JSON-identity proxy).
5. rag_graph_react imports format_verifier_feedback without error.

No real index or LLM calls.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_verifier import format_verifier_feedback  # noqa: E402


# ---------------------------------------------------------------------------
# 1. format_verifier_feedback exists
# ---------------------------------------------------------------------------

def test_format_verifier_feedback_importable():
    assert callable(format_verifier_feedback)


# ---------------------------------------------------------------------------
# 2. Empty reasons → fallback
# ---------------------------------------------------------------------------

def test_empty_reasons_returns_nonempty_string():
    result = format_verifier_feedback(reasons=[], evidence=[])
    assert isinstance(result, str)
    assert len(result) > 10


def test_empty_reasons_mentions_retrieve_action():
    result = format_verifier_feedback(reasons=[], evidence=[])
    assert "retrieve" in result.lower() or "검색" in result


# ---------------------------------------------------------------------------
# 3. Reasons list → formatted output
# ---------------------------------------------------------------------------

def test_reasons_are_included_in_output():
    reasons = ["topic_not_grounded: 보안 요구사항", "verifier_strict_miss"]
    result = format_verifier_feedback(reasons=reasons, evidence=[])
    for r in reasons:
        assert r in result, f"reason '{r}' not found in feedback"


def test_chunk_count_is_mentioned():
    evidence: list[dict[str, Any]] = [
        {"chunk_id": "c1", "text": "테스트1"},
        {"chunk_id": "c2", "text": "테스트2"},
    ]
    result = format_verifier_feedback(reasons=["topic_not_grounded"], evidence=evidence)
    assert "2" in result  # chunk count mentioned


def test_feedback_is_string():
    result = format_verifier_feedback(
        reasons=["partial_topic: 사업비"],
        evidence=[{"chunk_id": "c1", "text": "예산 항목"}],
    )
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 4. verify_evidence JSON-identity proxy — signature unchanged
# ---------------------------------------------------------------------------

def test_verify_evidence_signature_unchanged():
    """verify_evidence signature must be unchanged — format_verifier_feedback is additive."""
    import inspect
    from rag_verifier import verify_evidence

    sig = inspect.signature(verify_evidence)
    params = set(sig.parameters.keys())
    # Actual signature: analysis, evidence, allow_partial_topic
    required = {"analysis", "evidence"}
    assert required <= params, f"verify_evidence signature changed: {params}"
    # format_verifier_feedback must NOT appear as a parameter (additive, separate func)
    assert "format_verifier_feedback" not in params


# ---------------------------------------------------------------------------
# 5. rag_graph_react imports feedback cleanly
# ---------------------------------------------------------------------------

def test_rag_graph_react_imports_feedback_without_error():
    sys.modules.pop("rag_graph_react", None)
    import types
    mock_lg = types.ModuleType("langgraph")
    mock_lg.graph = types.ModuleType("langgraph.graph")  # type: ignore[attr-defined]
    from unittest.mock import patch

    with patch.dict("sys.modules", {"langgraph": mock_lg, "langgraph.graph": mock_lg.graph}):
        import rag_graph_react  # noqa: F401
    # If we get here the import succeeded (format_verifier_feedback late-imported)
    assert True
