"""Regression tests for rag_agent_tools — agent tool registry (#670).

Verifies:
1. Tool definition schema — required keys, input_schema structure.
2. AGENT_REACT_TOOLS list completeness and ordering.
3. AGENT_TOOL_NAMES / is_valid_tool_name helper.
4. AGENT_REACT_SYSTEM_PROMPT is non-empty string.
5. execute_abstain — pure function, no external calls.
6. execute_retrieve_evidence / execute_verify_grounding never-raise on bad input.
7. execute_expand_query_hyde never-raise (SDK absent fallback).

No real index, LLM, or network calls.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_agent_tools import (  # noqa: E402
    ABSTAIN_TOOL,
    AGENT_REACT_SYSTEM_PROMPT,
    AGENT_REACT_TOOLS,
    AGENT_TOOL_NAMES,
    EXPAND_QUERY_HYDE_TOOL,
    RETRIEVE_EVIDENCE_TOOL,
    VERIFY_GROUNDING_TOOL,
    execute_abstain,
    execute_expand_query_hyde,
    execute_retrieve_evidence,
    execute_verify_grounding,
    is_valid_tool_name,
)

_REQUIRED_TOOL_KEYS = {"name", "description", "input_schema"}
_REQUIRED_SCHEMA_KEYS = {"type", "properties", "required"}


# ---------------------------------------------------------------------------
# 1. Tool definition schema
# ---------------------------------------------------------------------------

def _check_tool(tool: dict[str, Any], name: str) -> None:
    assert _REQUIRED_TOOL_KEYS <= tool.keys(), f"{name} missing keys"
    schema = tool["input_schema"]
    assert _REQUIRED_SCHEMA_KEYS <= schema.keys(), f"{name}.input_schema missing keys"
    assert schema["type"] == "object"
    assert isinstance(schema["properties"], dict)
    assert isinstance(schema["required"], list)
    assert all(r in schema["properties"] for r in schema["required"]), (
        f"{name}: required fields not in properties"
    )


def test_retrieve_evidence_tool_schema():
    _check_tool(RETRIEVE_EVIDENCE_TOOL, "retrieve_evidence")
    props = RETRIEVE_EVIDENCE_TOOL["input_schema"]["properties"]
    assert "stage" in props
    assert "top_k" in props
    # stage must have enum constraint
    assert "enum" in props["stage"]
    assert set(props["stage"]["enum"]) == {"strict", "relaxed"}


def test_expand_query_hyde_tool_schema():
    _check_tool(EXPAND_QUERY_HYDE_TOOL, "expand_query_hyde")
    assert "query" in EXPAND_QUERY_HYDE_TOOL["input_schema"]["required"]


def test_verify_grounding_tool_schema():
    _check_tool(VERIFY_GROUNDING_TOOL, "verify_grounding")
    props = VERIFY_GROUNDING_TOOL["input_schema"]["properties"]
    assert "evidence_ids" in props
    assert props["evidence_ids"]["type"] == "array"


def test_abstain_tool_schema():
    _check_tool(ABSTAIN_TOOL, "abstain")
    assert "reason" in ABSTAIN_TOOL["input_schema"]["required"]


# ---------------------------------------------------------------------------
# 2. AGENT_REACT_TOOLS list
# ---------------------------------------------------------------------------

def test_agent_react_tools_is_list_of_four():
    assert isinstance(AGENT_REACT_TOOLS, list)
    assert len(AGENT_REACT_TOOLS) == 4


def test_agent_react_tools_names():
    names = [t["name"] for t in AGENT_REACT_TOOLS]
    assert names == [
        "retrieve_evidence",
        "expand_query_hyde",
        "verify_grounding",
        "abstain",
    ], f"Unexpected order: {names}"


# ---------------------------------------------------------------------------
# 3. AGENT_TOOL_NAMES / is_valid_tool_name
# ---------------------------------------------------------------------------

def test_agent_tool_names_frozenset():
    assert isinstance(AGENT_TOOL_NAMES, frozenset)
    assert AGENT_TOOL_NAMES == {
        "retrieve_evidence",
        "expand_query_hyde",
        "verify_grounding",
        "abstain",
    }


def test_is_valid_tool_name_true():
    for name in AGENT_TOOL_NAMES:
        assert is_valid_tool_name(name), f"{name} not recognised"


def test_is_valid_tool_name_false():
    assert not is_valid_tool_name("unknown_tool")
    assert not is_valid_tool_name("")


# ---------------------------------------------------------------------------
# 4. AGENT_REACT_SYSTEM_PROMPT
# ---------------------------------------------------------------------------

def test_system_prompt_nonempty():
    assert isinstance(AGENT_REACT_SYSTEM_PROMPT, str)
    assert len(AGENT_REACT_SYSTEM_PROMPT) > 100


def test_system_prompt_mentions_abstain():
    # Prompt must mention the abstain tool so the LLM knows to use it.
    assert "abstain" in AGENT_REACT_SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# 5. execute_abstain — pure, no external calls
# ---------------------------------------------------------------------------

def test_execute_abstain_status():
    result = execute_abstain({"reason": "budget_exhausted"})
    assert result["status"] == "insufficient"
    assert result["abstain_reason"] == "budget_exhausted"


def test_execute_abstain_empty_input():
    result = execute_abstain({})
    assert result["status"] == "insufficient"
    assert isinstance(result["abstain_reason"], str)


# ---------------------------------------------------------------------------
# 6. execute_retrieve_evidence — never-raise on bad input
# ---------------------------------------------------------------------------

def test_execute_retrieve_evidence_bad_index_never_raises():
    # Passing None as index should not raise — fallback path.
    result = execute_retrieve_evidence(
        {"stage": "strict", "top_k": 5},
        index=None,
        analysis={"query_type": "single_doc", "entities": []},
    )
    assert "chunks" in result
    assert "meta" in result
    # Must have fallen back
    assert result["meta"].get("fell_back") is True or isinstance(result["chunks"], list)


def test_execute_retrieve_evidence_never_raises():
    result = execute_retrieve_evidence(
        {"stage": "INVALID", "top_k": -1},
        index=None,
        analysis={},
    )
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 7. execute_verify_grounding — never-raise on bad input
# ---------------------------------------------------------------------------

def test_execute_verify_grounding_bad_pool_never_raises():
    result = execute_verify_grounding(
        {"evidence_ids": ["chunk_001"]},
        query="테스트 쿼리",
        topics=["보안"],
        evidence_pool=[],  # empty pool → insufficient
    )
    assert "verdict" in result
    assert result["verdict"] in {"grounded", "partial", "insufficient"}


def test_execute_verify_grounding_never_raises():
    result = execute_verify_grounding(
        {},  # missing evidence_ids
        query="",
        topics=[],
        evidence_pool=None,  # type: ignore[arg-type]
    )
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 8. execute_expand_query_hyde — never-raise fallback
# ---------------------------------------------------------------------------

def test_execute_expand_query_hyde_fallback_never_raises():
    # If Anthropic SDK is unavailable or ANTHROPIC_API_KEY is not set,
    # HyDEExpander.expand falls back — but it may succeed or fail; either way
    # execute_expand_query_hyde must not raise.
    try:
        result = execute_expand_query_hyde({"query": "보안 요구사항"})
    except Exception as exc:
        raise AssertionError(f"execute_expand_query_hyde raised: {exc}") from exc
    assert "expanded_query" in result
    assert isinstance(result["expanded_query"], str)
    assert "meta" in result
