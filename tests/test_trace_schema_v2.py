"""Tests for trace schema v2 (issue #967, ADR 0001 invariant preserved).

Covers:
- ``TRACE_SCHEMA_VERSION = 2`` baked into ``build_result_trace`` output
- ``synthesis_llm_call = None`` when ``synthesis_meta`` is absent or env=off
- ``synthesis_llm_call`` populated when ``synthesis_meta`` carries
  ``user_prompt_text`` + ``completion_text`` (env=on simulated by passing them)
- Two calls with identical inputs produce byte-identical traces (ADR 0001
  run-to-run determinism — schema bump is deterministic per-config, not
  per-config-version)

These tests do NOT exercise the real anthropic/openai backends — they
operate on ``build_result_trace`` directly with synthetic inputs, which is
the surgical scope of issue #967 (the LLM call sites only *populate* the
synthesis_meta dict; ``build_result_trace`` is the consumer).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_tracing import TRACE_SCHEMA_VERSION, build_result_trace  # noqa: E402


def _minimal_trace_args(answer_status: str = "ok") -> dict:
    """Build the minimum positional kwargs for build_result_trace."""
    return dict(
        original_query="기관 A 의 사업기간은?",
        resolved_query="기관 A 의 사업기간은?",
        analysis={"query_type": "single_doc"},
        plan={"top_k": 4, "pipeline": "agentic_full"},
        metadata_resolution={"active_doc_ids": ["doc_1"]},
        context_resolution={"rewritten": False},
        stage_sequence=["base"],
        stage_attempts=[
            {"stage": "base", "verification_reasons": [], "metadata_filters": {}}
        ],
        answer={
            "schema_version": 2,
            "status": answer_status,
            "status_reason": {},
            "query_type": "single_doc",
            "claims": [{"text": "사업기간은 12개월", "citations": [{"chunk_id": "c1"}]}],
        },
    )


class TestSchemaVersionBumped(unittest.TestCase):
    def test_schema_version_constant_is_2(self):
        self.assertEqual(TRACE_SCHEMA_VERSION, 2)

    def test_trace_carries_schema_version_2(self):
        trace = build_result_trace(**_minimal_trace_args())
        self.assertEqual(trace["schema_version"], 2)


class TestSynthesisLlmCallEnvOff(unittest.TestCase):
    def test_no_synthesis_meta_yields_null_llm_call(self):
        trace = build_result_trace(**_minimal_trace_args())
        self.assertIn("synthesis_llm_call", trace)
        self.assertIsNone(trace["synthesis_llm_call"])

    def test_synthesis_meta_without_prompt_text_yields_null(self):
        # Simulates env=off: synthesis ran, captured tokens, but did NOT
        # capture full prompt/completion. Trace v2 surfaces None — the
        # presence of tokens alone does not promote the case to "llm_call
        # captured".
        meta_without_full_io = {
            "backend": "anthropic",
            "model": "claude-sonnet-4-6",
            "tokens_in": 1200,
            "tokens_out": 350,
        }
        trace = build_result_trace(
            **_minimal_trace_args(),
            synthesis_meta=meta_without_full_io,
        )
        self.assertIsNone(trace["synthesis_llm_call"])

    def test_non_dict_synthesis_meta_is_safe(self):
        trace = build_result_trace(
            **_minimal_trace_args(),
            synthesis_meta="not-a-dict",  # type: ignore[arg-type]
        )
        self.assertIsNone(trace["synthesis_llm_call"])


class TestSynthesisLlmCallEnvOn(unittest.TestCase):
    def test_synthesis_meta_with_prompt_text_yields_payload(self):
        # Simulates env=on: synthesis backend captured prompt + completion
        # in the returned dict, top-level synthesize_summary copied them to
        # meta. build_result_trace surfaces them as synthesis_llm_call.
        meta_with_full_io = {
            "backend": "anthropic",
            "model": "claude-sonnet-4-6",
            "tokens_in": 1200,
            "tokens_out": 350,
            "user_prompt_text": "Query: 기관 A 사업기간\n\nEvidence: ...",
            "completion_text": '{"summary": "12개월", "used_chunk_ids": ["c1"]}',
        }
        trace = build_result_trace(
            **_minimal_trace_args(),
            synthesis_meta=meta_with_full_io,
        )
        llm_call = trace["synthesis_llm_call"]
        self.assertIsNotNone(llm_call)
        self.assertEqual(llm_call["backend"], "anthropic")
        self.assertEqual(llm_call["model"], "claude-sonnet-4-6")
        self.assertEqual(llm_call["tokens_in"], 1200)
        self.assertEqual(llm_call["tokens_out"], 350)
        self.assertEqual(llm_call["user_prompt_text"], "Query: 기관 A 사업기간\n\nEvidence: ...")
        self.assertEqual(llm_call["completion_text"], '{"summary": "12개월", "used_chunk_ids": ["c1"]}')


class TestRunToRunDeterminism(unittest.TestCase):
    """ADR 0001 invariant — two runs of build_result_trace with identical
    inputs produce byte-identical JSON output. Schema bump 1→2 does NOT
    break this; it only shifts the absolute value of schema_version."""

    def test_byte_identical_traces(self):
        args = _minimal_trace_args()
        meta = {
            "backend": "anthropic",
            "model": "claude-sonnet-4-6",
            "tokens_in": 1200,
            "tokens_out": 350,
            "user_prompt_text": "same prompt",
            "completion_text": "same completion",
        }
        t1 = build_result_trace(**args, synthesis_meta=meta)
        t2 = build_result_trace(**args, synthesis_meta=meta)
        self.assertEqual(
            json.dumps(t1, sort_keys=True, ensure_ascii=False),
            json.dumps(t2, sort_keys=True, ensure_ascii=False),
        )


if __name__ == "__main__":
    unittest.main()
